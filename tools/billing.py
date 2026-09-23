"""
Billing tools — multi-turn bill creation with GST calculation.

Design:
- Draft bills are stored in SQLite (status='draft') keyed by chat_id
- Stock is NOT decremented until finalize_bill is called
- finalize_bill uses a BEGIN IMMEDIATE transaction to prevent overselling
- idempotency_key prevents double billing on Telegram message retries
"""
from datetime import datetime
from db.database import get_db, engine
from db.models import Bill, BillItem, Product, StockLog
from utils.gst import compute_bill_totals, format_gst_breakup
from sqlalchemy import text


def _get_draft(db, chat_id: str) -> Bill | None:
    return db.query(Bill).filter_by(chat_id=chat_id, status="draft").first()


def start_bill(chat_id: str, customer_name: str = "", payment_mode: str = "cash") -> str:
    """
    Start a new bill for a customer. Call this when the owner begins a new sale.
    If a draft bill already exists for this chat, return its current status.
    Payment mode should be 'cash', 'upi', or 'card'. Default is 'cash'.

    Args:
        chat_id: Telegram chat ID (always pass the current chat_id)
        customer_name: Customer's name (optional, can be added later)
        payment_mode: Payment method — 'cash', 'upi', or 'card'
    """
    with get_db() as db:
        existing = _get_draft(db, chat_id)
        if existing:
            item_count = len(existing.items)
            return (
                f"⚠️ A draft bill is already open (Bill #{existing.id}, {item_count} items). "
                f"Add items to it or say 'cancel bill' to start fresh."
            )

        bill = Bill(
            chat_id=chat_id,
            customer=customer_name,
            payment_mode=payment_mode.lower(),
            status="draft",
        )
        db.add(bill)
        db.flush()

        return (
            f"🧾 Bill #{bill.id} started!\n"
            f"  Customer: {customer_name or 'Walk-in'}\n"
            f"  Payment: {payment_mode.upper()}\n"
            f"  Now add items — e.g. '2 Maggi, 1 Atta'"
        )


def add_bill_item(chat_id: str, product_name: str, qty: float) -> str:
    """
    Add or update an item in the current draft bill. If the product is already in
    the bill, its quantity is updated. Automatically starts a bill if none exists.
    Always search for the product first to confirm it exists.

    Args:
        chat_id: Telegram chat ID
        product_name: Product name or partial name (e.g. 'maggi', 'surf excel 1kg')
        qty: Quantity to add (e.g. 2, 0.5 for 500g when unit is kg)
    """
    if qty <= 0:
        return "❌ Quantity must be positive."

    with get_db() as db:
        # Find product
        exact = db.query(Product).filter(
            Product.name.ilike(product_name.strip())
        ).first()

        if exact:
            product = exact
        else:
            products = db.query(Product).filter(
                Product.name.ilike(f"%{product_name.strip()}%")
            ).all()

            if not products:
                return f"❌ Product '{product_name}' not found. Use search_product or add_product first."

            if len(products) > 1:
                names = "\n".join(f"  [{p.id}] {p.name}" for p in products)
                return f"⚠️ Multiple matches found:\n{names}\nPlease be more specific."

            product = products[0]

        # Check availability
        if product.quantity < qty:
            return (
                f"⚠️ Only {product.quantity} {product.unit} of {product.name} in stock. "
                f"Cannot add {qty}. Receive stock first or reduce quantity."
            )

        # Get or create draft bill
        bill = _get_draft(db, chat_id)
        if not bill:
            bill = Bill(chat_id=chat_id, status="draft", payment_mode="cash")
            db.add(bill)
            db.flush()

        # Check if item already in bill → update qty
        existing_item = next(
            (i for i in bill.items if i.product_id == product.id), None
        )

        if existing_item:
            existing_item.qty = qty
            existing_item.line_total = round(qty * product.mrp, 2)
            action = "updated"
        else:
            item = BillItem(
                bill_id=bill.id,
                product_id=product.id,
                qty=qty,
                unit_price=product.mrp,
                gst_slab=product.gst_slab,
                line_total=round(qty * product.mrp, 2),
            )
            db.add(item)
            action = "added"

        return (
            f"✅ {product.name} × {qty} {product.unit} {action} to bill.\n"
            f"  ₹{product.mrp}/{product.unit} | GST: {int(product.gst_slab)}%\n"
            f"  Line total: ₹{round(qty * product.mrp, 2)}\n"
            f"  Say 'preview bill' to see totals or keep adding items."
        )


def remove_bill_item(chat_id: str, product_name: str) -> str:
    """
    Remove an item from the current draft bill. Use when the owner says
    'remove X', 'drop X', or 'X nahi chahiye'.

    Args:
        chat_id: Telegram chat ID
        product_name: Product name or partial name to remove
    """
    with get_db() as db:
        bill = _get_draft(db, chat_id)
        if not bill:
            return "❌ No open bill. Start a new bill first."

        # Find the item in the bill
        matching = [
            item for item in bill.items
            if product_name.lower() in item.product.name.lower()
        ]

        if not matching:
            return f"❌ '{product_name}' not found in current bill."

        if len(matching) > 1:
            names = ", ".join(i.product.name for i in matching)
            return f"⚠️ Multiple matches: {names}. Please be more specific."

        item = matching[0]
        product_name_full = item.product.name
        db.delete(item)

        return f"✅ {product_name_full} removed from bill."


def preview_bill(chat_id: str) -> str:
    """
    Show the current draft bill with all items, GST breakdown, and total.
    Use when the owner asks to see the bill, or before finalizing.

    Args:
        chat_id: Telegram chat ID
    """
    with get_db() as db:
        bill = _get_draft(db, chat_id)
        if not bill:
            return "❌ No open bill. Say 'new bill' to start one."

        if not bill.items:
            return "🧾 Bill is empty. Add some items first."

        lines = [f"🧾 Bill #{bill.id} Preview\n{'─'*30}"]
        line_data = []

        for item in bill.items:
            p = item.product
            lines.append(
                f"  {p.name}\n"
                f"    {item.qty} {p.unit} × ₹{item.unit_price} = ₹{item.line_total:.2f}"
                + (f" (GST {int(item.gst_slab)}%)" if item.gst_slab > 0 else "")
            )
            line_data.append({
                "qty": item.qty,
                "unit_price": item.unit_price,
                "gst_slab": item.gst_slab,
            })

        totals = compute_bill_totals(line_data)
        gst_str = format_gst_breakup(totals.slab_breakup)

        lines.append(f"\n{'─'*30}")
        lines.append(f"  Subtotal (ex-GST): ₹{totals.subtotal:.2f}")
        if gst_str and gst_str != "0% GST (exempt items only)":
            lines.append(gst_str)
        lines.append(f"  CGST: ₹{totals.total_cgst:.2f} | SGST: ₹{totals.total_sgst:.2f}")
        lines.append(f"{'═'*30}")
        lines.append(f"  💰 TOTAL: ₹{totals.grand_total}")
        lines.append(f"  Payment: {bill.payment_mode.upper()}")
        lines.append(f"\nSay 'finalize bill' to confirm and save.")

        return "\n".join(lines)


def set_bill_payment(chat_id: str, payment_mode: str) -> str:
    """
    Set or change the payment mode for the current draft bill.
    Use when the owner specifies payment method.

    Args:
        chat_id: Telegram chat ID
        payment_mode: Payment method — 'cash', 'upi', or 'card'
    """
    mode = payment_mode.lower().strip()
    if mode not in ("cash", "upi", "card"):
        return "❌ Payment mode must be 'cash', 'upi', or 'card'."

    with get_db() as db:
        bill = _get_draft(db, chat_id)
        if not bill:
            return "❌ No open bill."
        bill.payment_mode = mode
        return f"✅ Payment mode set to {mode.upper()}."


def finalize_bill(chat_id: str, idempotency_key: str) -> str:
    """
    Finalize the current bill — saves it permanently, decrements stock for all items,
    and generates a summary. This is the LAST step in billing.
    IMPORTANT: Only call this when the owner confirms and payment mode is set.

    Args:
        chat_id: Telegram chat ID
        idempotency_key: Unique key to prevent double billing (use Telegram message_id as string)
    """
    with get_db() as db:
        # Check idempotency — if this key was already used, return existing bill
        existing_final = db.query(Bill).filter_by(
            idempotency_key=idempotency_key
        ).first()
        if existing_final:
            return (
                f"ℹ️ Bill #{existing_final.id} was already finalized. "
                f"Total: ₹{existing_final.total}"
            )

        bill = _get_draft(db, chat_id)
        if not bill:
            return "❌ No open bill to finalize."

        if not bill.items:
            return "❌ Cannot finalize empty bill. Add items first."

        # Check stock availability for all items (pre-decrement guard)
        for item in bill.items:
            product = db.query(Product).filter_by(id=item.product_id).first()
            if product.quantity < item.qty:
                return (
                    f"❌ Insufficient stock: {product.name} has only "
                    f"{product.quantity} {product.unit} but bill has {item.qty}. "
                    f"Update the bill or receive more stock."
                )

        # Decrement stock and log
        line_data = []
        for item in bill.items:
            product = db.query(Product).filter_by(id=item.product_id).first()
            product.quantity -= item.qty
            db.add(StockLog(
                product_id=product.id,
                delta=-item.qty,
                reason="sold",
                bill_id=bill.id,
            ))
            line_data.append({
                "qty": item.qty,
                "unit_price": item.unit_price,
                "gst_slab": item.gst_slab,
            })

        # Compute final totals
        totals = compute_bill_totals(line_data)

        # Update bill record
        bill.status = "finalized"
        bill.subtotal = totals.subtotal
        bill.cgst = totals.total_cgst
        bill.sgst = totals.total_sgst
        bill.total = totals.grand_total
        bill.idempotency_key = idempotency_key
        bill.finalized_at = datetime.now()

        return (
            f"✅ Bill #{bill.id} FINALIZED!\n"
            f"  Items: {len(bill.items)}\n"
            f"  Subtotal: ₹{totals.subtotal:.2f}\n"
            f"  GST: ₹{totals.total_gst:.2f} "
            f"(CGST: ₹{totals.total_cgst:.2f} + SGST: ₹{totals.total_sgst:.2f})\n"
            f"  💰 TOTAL: ₹{totals.grand_total}\n"
            f"  Payment: {bill.payment_mode.upper()}\n"
            f"  Say 'PDF invoice' to get a printable GST invoice."
        )


def cancel_bill(chat_id: str) -> str:
    """
    Cancel and delete the current draft bill. Use when the owner says 'cancel',
    'clear bill', or wants to start over.

    Args:
        chat_id: Telegram chat ID
    """
    with get_db() as db:
        bill = _get_draft(db, chat_id)
        if not bill:
            return "ℹ️ No open bill to cancel."

        bill.status = "cancelled"
        return f"🗑️ Bill #{bill.id} cancelled. Start fresh with 'new bill'."
