"""
Inventory management tools.
All functions are registered as Gemini tools — docstrings define the tool description.
"""
from db.database import get_db
from db.models import Product, StockLog


def search_product(query: str) -> str:
    """
    Search for a product by name in the inventory database. Use this before billing
    or receiving stock to find the correct product ID. Returns matching products with
    their ID, name, unit, MRP, current stock, and GST slab.

    Args:
        query: Product name or partial name to search for (e.g. 'maggi', 'atta', 'surf')
    """
    with get_db() as db:
        results = db.query(Product).filter(
            Product.name.ilike(f"%{query}%")
        ).all()

        if not results:
            return f"❌ No product found matching '{query}'. Use add_product to create it."

        lines = ["🔍 Found products:"]
        for p in results:
            lines.append(
                f"  ID:{p.id} | {p.name} | ₹{p.mrp}/{p.unit} | "
                f"Stock: {p.quantity} {p.unit} | GST: {int(p.gst_slab)}%"
            )
        return "\n".join(lines)


def add_product(
    name: str,
    unit: str,
    mrp: float,
    cost_price: float,
    gst_slab: float,
    is_loose: bool = False,
    reorder_lvl: float = 5.0,
    hsn_code: str = "",
    initial_stock: float = 0.0,
) -> str:
    """
    Add a brand new product to the inventory. Use when the owner wants to stock a
    product that doesn't exist yet. Unit should be one of: kg, g, litre, ml, packet,
    piece, dozen. GST slab must be 0, 5, 12, or 18.

    Args:
        name: Full product name (e.g. 'Horlicks 500g')
        unit: Unit of measurement (kg/g/litre/ml/packet/piece/dozen)
        mrp: Maximum Retail Price in rupees
        cost_price: Cost price / purchase price in rupees
        gst_slab: GST percentage — must be 0, 5, 12, or 18
        is_loose: True if sold by weight/volume (rice, dal, oil), False for packaged items
        reorder_lvl: Minimum stock level before reorder alert (default: 5)
        hsn_code: HSN/SAC code for GST (optional, leave blank if unknown)
        initial_stock: Opening stock quantity (default: 0)
    """
    if gst_slab not in (0, 5, 12, 18):
        return f"❌ Invalid GST slab '{gst_slab}'. Must be 0, 5, 12, or 18."

    if mrp <= 0:
        return "❌ MRP must be greater than 0."

    with get_db() as db:
        # Check for duplicate name
        existing = db.query(Product).filter(
            Product.name.ilike(name)
        ).first()
        if existing:
            return (
                f"⚠️ Product '{existing.name}' already exists (ID: {existing.id}). "
                f"Current stock: {existing.quantity} {existing.unit}."
            )

        # Generate SKU from name
        sku = name.upper().replace(" ", "_")[:20]

        product = Product(
            name=name,
            sku=sku,
            unit=unit,
            is_loose=is_loose,
            cost_price=cost_price,
            mrp=mrp,
            quantity=initial_stock,
            reorder_lvl=reorder_lvl,
            hsn_code=hsn_code,
            gst_slab=gst_slab,
        )
        db.add(product)
        db.flush()  # get the ID

        # Log initial stock if any
        if initial_stock > 0:
            db.add(StockLog(
                product_id=product.id,
                delta=initial_stock,
                reason="received",
            ))

        return (
            f"✅ Product added!\n"
            f"  Name: {name}\n"
            f"  ID: {product.id} | MRP: ₹{mrp}/{unit} | Cost: ₹{cost_price}\n"
            f"  GST: {int(gst_slab)}% | HSN: {hsn_code or 'not set'}\n"
            f"  Stock: {initial_stock} {unit} | Reorder at: {reorder_lvl}"
        )


def receive_stock(product_name: str, qty: float, cost_price: float = 0.0) -> str:
    """
    Record incoming stock for an existing product. Use when the owner says new stock
    arrived (e.g. '50 maggi aaya', 'got 30 surf excel'). Increases the product's
    quantity and optionally updates the cost price.

    Args:
        product_name: Name or partial name of the product (e.g. 'maggi', 'atta 5kg')
        qty: Quantity received (must be positive)
        cost_price: New cost/purchase price per unit (optional; updates if provided)
    """
    if qty <= 0:
        return "❌ Quantity must be positive."

    with get_db() as db:
        results = db.query(Product).filter(
            Product.name.ilike(f"%{product_name}%")
        ).all()

        if not results:
            return f"❌ Product '{product_name}' not found. Use add_product to create it first."

        if len(results) > 1:
            names = ", ".join(f"'{p.name}' (ID:{p.id})" for p in results)
            return f"⚠️ Multiple matches: {names}. Please be more specific."

        product = results[0]
        old_qty = product.quantity
        product.quantity += qty
        if cost_price > 0:
            product.cost_price = cost_price

        db.add(StockLog(
            product_id=product.id,
            delta=qty,
            reason="received",
        ))

        return (
            f"✅ Stock updated!\n"
            f"  {product.name}\n"
            f"  Added: {qty} {product.unit}\n"
            f"  Old stock: {old_qty} → New stock: {product.quantity} {product.unit}"
            + (f"\n  Cost price updated to ₹{cost_price}" if cost_price > 0 else "")
        )


def query_stock(product_name: str) -> str:
    """
    Check current stock level, MRP, cost price and GST for a product.
    Use when the owner asks 'how much X do we have' or 'kitna X hai'.

    Args:
        product_name: Name or partial name of the product to check
    """
    with get_db() as db:
        results = db.query(Product).filter(
            Product.name.ilike(f"%{product_name}%")
        ).all()

        if not results:
            return f"❌ No product found matching '{product_name}'."

        lines = []
        for p in results:
            status = "🔴 LOW STOCK" if p.quantity <= p.reorder_lvl else "🟢 OK"
            lines.append(
                f"{status} | {p.name}\n"
                f"  Stock: {p.quantity} {p.unit} (reorder at {p.reorder_lvl})\n"
                f"  MRP: ₹{p.mrp} | Cost: ₹{p.cost_price} | GST: {int(p.gst_slab)}%"
            )
        return "\n\n".join(lines)


def list_low_stock() -> str:
    """
    List all products that are at or below their reorder level. Use when the owner
    asks what needs to be ordered, or 'kya khatam ho raha hai'.
    """
    with get_db() as db:
        low = db.query(Product).filter(
            Product.quantity <= Product.reorder_lvl
        ).order_by(Product.quantity).all()

        if not low:
            return "✅ All products are well-stocked! Nothing needs reordering."

        lines = [f"🔴 {len(low)} items need reordering:\n"]
        for p in low:
            lines.append(
                f"  • {p.name}: {p.quantity} {p.unit} left (reorder at {p.reorder_lvl})"
            )
        return "\n".join(lines)


def list_all_products() -> str:
    """
    List total products and high-level inventory overview.
    Use when the owner asks for full stock list or overall inventory status.
    """
    with get_db() as db:
        products = db.query(Product).order_by(Product.name).all()
        if not products:
            return "📦 No products in inventory yet."

        total_units = sum(p.quantity for p in products)
        low_count = sum(1 for p in products if p.quantity <= p.reorder_lvl)
        
        sample = [f"• {p.name}: {p.quantity} {p.unit}" for p in products[:8]]
        
        return (
            f"📦 Inventory Summary: {len(products)} products ({int(total_units)} total units in stock).\n"
            f"🔴 Low stock items: {low_count}\n"
            f"Sample items:\n" + "\n".join(sample) + "\n"
            f"...and {len(products)-8} more products. Search any specific product by name for details."
        )
