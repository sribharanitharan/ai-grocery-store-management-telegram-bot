"""
Khata (credit ledger) tools for tracking customer credit and payments.
Positive delta = credit given to customer, Negative delta = payment received.
"""
from db.database import get_db
from db.models import Khata
from sqlalchemy import func
from datetime import datetime, timedelta

IDEMPOTENCY_WINDOW_MINUTES = 5  # Prevent duplicate entries within this window


def add_credit(customer: str, amount: float, note: str = "") -> str:
    """
    Record a credit sale — when a customer takes goods on credit (udhar).
    Amount must be positive. Use when owner says 'X ka udhar karo', 'X ne credit liya'.

    Args:
        customer: Customer name (e.g. 'Ramesh', 'Sharma ji')
        amount: Amount of credit in rupees (positive number)
        note: Optional note about the transaction (e.g. 'grocery items')
    """
    if amount <= 0:
        return "❌ Credit amount must be positive."

    customer = customer.strip().title()
    cutoff = datetime.now() - timedelta(minutes=IDEMPOTENCY_WINDOW_MINUTES)

    with get_db() as db:
        # Idempotency: skip if identical credit was recorded in the last 5 minutes
        recent_duplicate = db.query(Khata).filter(
            Khata.customer == customer,
            Khata.delta == amount,
            Khata.created_at >= cutoff,
        ).first()
        if recent_duplicate:
            balance = db.query(func.sum(Khata.delta)).filter_by(customer=customer).scalar() or 0.0
            return (
                f"📋 Credit of ₹{amount:.2f} already recorded for {customer} recently.\n"
                f"  Total outstanding: ₹{balance:.2f}"
            )

        entry = Khata(customer=customer, delta=amount, note=note or "credit sale")
        db.add(entry)
        db.flush()  # flush so balance includes the new entry

        # Compute new balance
        balance = db.query(func.sum(Khata.delta)).filter_by(customer=customer).scalar() or 0.0

        return (
            f"📋 Khata updated for {customer}!\n"
            f"  Credit added: ₹{amount:.2f}\n"
            f"  Total outstanding: ₹{balance:.2f}"
        )


def record_payment(customer: str, amount: float) -> str:
    """
    Record a payment received from a customer towards their credit balance.
    Use when owner says 'X ne X rupaye diye', 'Ramesh paid 500'.

    Args:
        customer: Customer name
        amount: Amount paid in rupees (positive number)
    """
    if amount <= 0:
        return "❌ Payment amount must be positive."

    customer = customer.strip().title()
    cutoff = datetime.now() - timedelta(minutes=IDEMPOTENCY_WINDOW_MINUTES)

    with get_db() as db:
        # Check customer exists
        existing = db.query(Khata).filter_by(customer=customer).first()
        if not existing:
            return f"❌ Customer '{customer}' not found in khata. Check the name."

        # Idempotency: skip if identical payment was recorded in the last 5 minutes
        recent_duplicate = db.query(Khata).filter(
            Khata.customer == customer,
            Khata.delta == -amount,
            Khata.created_at >= cutoff,
        ).first()
        if recent_duplicate:
            current_balance = db.query(func.sum(Khata.delta)).filter_by(customer=customer).scalar() or 0.0
            return (
                f"💰 Payment of ₹{amount:.2f} already recorded for {customer} recently.\n"
                f"  Outstanding balance: ₹{current_balance:.2f}"
            )

        current_balance = (
            db.query(func.sum(Khata.delta)).filter_by(customer=customer).scalar() or 0.0
        )

        entry = Khata(
            customer=customer,
            delta=-amount,
            note="payment received",
        )
        db.add(entry)

        new_balance = current_balance - amount

        if new_balance == 0:
            status = "✅ Account fully cleared!"
        elif new_balance > 0:
            status = f"  Remaining balance: ₹{new_balance:.2f}"
        else:
            status = f"  Overpaid by ₹{abs(new_balance):.2f}"

        return (
            f"💰 Payment recorded for {customer}!\n"
            f"  Paid: ₹{amount:.2f}\n"
            f"  Previous balance: ₹{current_balance:.2f}\n"
            f"  {status}"
        )


def get_khata_balance(customer: str) -> str:
    """
    Get the current outstanding balance and recent transactions for a customer.
    Use when owner asks 'Ramesh ka kitna baaki hai', 'X's balance'.

    Args:
        customer: Customer name (full or partial)
    """
    customer_search = customer.strip()

    with get_db() as db:
        # Fuzzy match customer name
        all_customers = db.query(Khata.customer).distinct().all()
        matches = [
            c[0] for c in all_customers
            if customer_search.lower() in c[0].lower()
        ]

        if not matches:
            return f"❌ Customer '{customer}' not found in khata."

        results = []
        for name in matches:
            balance = (
                db.query(func.sum(Khata.delta)).filter_by(customer=name).scalar() or 0.0
            )

            # Last 5 transactions
            recent = (
                db.query(Khata)
                .filter_by(customer=name)
                .order_by(Khata.created_at.desc())
                .limit(5)
                .all()
            )

            txn_lines = []
            for t in recent:
                kind = "Credit" if t.delta > 0 else "Payment"
                txn_lines.append(
                    f"    {kind}: ₹{abs(t.delta):.2f} — {t.created_at.strftime('%d %b %Y')}"
                    + (f" ({t.note})" if t.note else "")
                )

            status = "🔴 Outstanding" if balance > 0 else "🟢 Clear"
            results.append(
                f"{status} | {name}\n"
                f"  Balance: ₹{balance:.2f}\n"
                f"  Recent transactions:\n" + "\n".join(txn_lines)
            )

        return "\n\n".join(results)


def reset_customer_khata(customer: str) -> str:
    """
    Clear all khata entries for a customer, resetting their balance to zero.
    Use ONLY when explicitly asked to 'reset', 'clear', or 'start fresh' for a customer.
    Do NOT use this for normal payment recording.

    Args:
        customer: Customer name to reset
    """
    customer = customer.strip().title()

    with get_db() as db:
        deleted = (
            db.query(Khata)
            .filter(Khata.customer == customer)
            .delete(synchronize_session=False)
        )
        if deleted == 0:
            return f"ℹ️ No khata entries found for '{customer}'."
        return (
            f"🗑️ Khata cleared for {customer}.\n"
            f"  Removed {deleted} transaction(s). Balance is now ₹0.00."
        )


def list_all_khata() -> str:
    """
    List all customers with outstanding credit balances.
    Use when the owner wants to see who owes money ('sabka udhar dikha').
    """
    with get_db() as db:
        # Group by customer and sum deltas
        from sqlalchemy import func
        results = (
            db.query(Khata.customer, func.sum(Khata.delta).label("balance"))
            .group_by(Khata.customer)
            .having(func.sum(Khata.delta) > 0)
            .order_by(func.sum(Khata.delta).desc())
            .all()
        )

        if not results:
            return "✅ No outstanding credit! Everyone is paid up."

        total_due = sum(r.balance for r in results)
        lines = [f"📋 Outstanding Khata ({len(results)} customers)\n{'─'*30}"]
        for r in results:
            lines.append(f"  {r.customer}: ₹{r.balance:.2f}")
        lines.append(f"{'─'*30}")
        lines.append(f"  Total outstanding: ₹{total_due:.2f}")

        return "\n".join(lines)
