"""
GST computation utilities for Indian kirana store billing.

GST Slabs:
  0%  — unpackaged food (rice, dal, wheat, salt, vegetables)
  5%  — packaged food, cooking oil, branded atta
  12% — processed food, dairy products, beverages
  18% — soaps, shampoos, detergents, cleaning items

For intra-state sales: GST = CGST + SGST (split equally)
"""
from typing import NamedTuple


class LineGST(NamedTuple):
    subtotal: float      # qty × unit_price (before tax)
    gst_amount: float    # total GST for this line
    cgst: float          # half of gst_amount
    sgst: float          # half of gst_amount
    line_total: float    # subtotal + gst_amount


class BillTotals(NamedTuple):
    subtotal: float
    total_cgst: float
    total_sgst: float
    total_gst: float
    grand_total: float
    slab_breakup: dict   # {5.0: {"cgst": x, "sgst": x, "base": x}, ...}


def compute_line_gst(qty: float, unit_price: float, gst_slab: float) -> LineGST:
    """
    Compute GST for a single bill line item.

    Args:
        qty: Quantity sold
        unit_price: Price per unit (MRP, inclusive)
        gst_slab: GST percentage (0, 5, 12, or 18)

    Returns:
        LineGST named tuple with all computed values
    """
    subtotal = round(qty * unit_price, 2)
    # GST is calculated on the base price (MRP is assumed to be inclusive of GST)
    # Base price = MRP / (1 + gst_slab/100)
    if gst_slab > 0:
        base = round(subtotal / (1 + gst_slab / 100), 2)
        gst_amount = round(subtotal - base, 2)
    else:
        base = subtotal
        gst_amount = 0.0

    cgst = round(gst_amount / 2, 2)
    sgst = round(gst_amount / 2, 2)
    line_total = subtotal  # MRP already includes GST

    return LineGST(
        subtotal=base,
        gst_amount=gst_amount,
        cgst=cgst,
        sgst=sgst,
        line_total=line_total,
    )


def compute_bill_totals(lines: list[dict]) -> BillTotals:
    """
    Compute totals for a full bill.

    Args:
        lines: List of dicts with keys: qty, unit_price, gst_slab

    Returns:
        BillTotals named tuple
    """
    total_base = 0.0
    total_cgst = 0.0
    total_sgst = 0.0
    slab_breakup: dict = {}

    for line in lines:
        lg = compute_line_gst(line["qty"], line["unit_price"], line["gst_slab"])
        total_base += lg.subtotal
        total_cgst += lg.cgst
        total_sgst += lg.sgst

        slab = line["gst_slab"]
        if slab not in slab_breakup:
            slab_breakup[slab] = {"base": 0.0, "cgst": 0.0, "sgst": 0.0}
        slab_breakup[slab]["base"] += lg.subtotal
        slab_breakup[slab]["cgst"] += lg.cgst
        slab_breakup[slab]["sgst"] += lg.sgst

    total_gst = round(total_cgst + total_sgst, 2)
    grand_total = round(total_base + total_gst, 2)

    # Round to nearest rupee
    grand_total = round(grand_total)

    return BillTotals(
        subtotal=round(total_base, 2),
        total_cgst=round(total_cgst, 2),
        total_sgst=round(total_sgst, 2),
        total_gst=total_gst,
        grand_total=grand_total,
        slab_breakup=slab_breakup,
    )


def format_gst_breakup(slab_breakup: dict) -> str:
    """Format GST slab breakup as a readable string for display."""
    if not slab_breakup:
        return "No GST applicable."
    lines = []
    for slab, vals in sorted(slab_breakup.items()):
        if slab == 0:
            continue
        lines.append(
            f"  GST @{int(slab)}%: Base ₹{vals['base']:.2f} | "
            f"CGST ₹{vals['cgst']:.2f} | SGST ₹{vals['sgst']:.2f}"
        )
    return "\n".join(lines) if lines else "0% GST (exempt items only)"
