"""
Analytics tools — daily close, weekly summary for business insights.
"""
from datetime import datetime, date, timedelta
from db.database import get_db
from db.models import Bill, BillItem, Product, StockLog
from sqlalchemy import func


def daily_close(query_date: str = "") -> str:
    """
    Get the daily sales summary — total revenue, tax collected, payment breakdown,
    and top-selling items. Use at end of day or when owner asks 'aaj ka hisaab'.

    Args:
        query_date: Date in YYYY-MM-DD format. Defaults to today if blank.
    """
    try:
        target = date.fromisoformat(query_date) if query_date else date.today()
    except ValueError:
        return f"❌ Invalid date format. Use YYYY-MM-DD (e.g. {date.today()})."

    day_start = datetime.combine(target, datetime.min.time())
    day_end = datetime.combine(target, datetime.max.time())

    with get_db() as db:
        bills = (
            db.query(Bill)
            .filter(
                Bill.status == "finalized",
                Bill.finalized_at >= day_start,
                Bill.finalized_at <= day_end,
            )
            .all()
        )

        if not bills:
            return f"📊 No sales recorded on {target.strftime('%d %b %Y')}."

        total_sales = sum(b.total for b in bills)
        total_cgst = sum(b.cgst for b in bills)
        total_sgst = sum(b.sgst for b in bills)
        total_gst = total_cgst + total_sgst

        # Payment mode breakdown
        mode_totals: dict = {}
        for b in bills:
            mode_totals[b.payment_mode] = mode_totals.get(b.payment_mode, 0) + b.total

        # Top 5 items by revenue
        item_revenue: dict = {}
        for bill in bills:
            for item in bill.items:
                name = item.product.name
                item_revenue[name] = item_revenue.get(name, 0) + item.line_total

        top_items = sorted(item_revenue.items(), key=lambda x: -x[1])[:5]

        lines = [
            f"📊 Daily Report — {target.strftime('%d %b %Y')}",
            f"{'═'*35}",
            f"  Bills: {len(bills)}",
            f"  Gross Sales: ₹{total_sales:.2f}",
            f"  GST Collected: ₹{total_gst:.2f} (CGST: ₹{total_cgst:.2f} + SGST: ₹{total_sgst:.2f})",
            f"",
            f"  Payment Breakdown:",
        ]
        for mode, amt in mode_totals.items():
            lines.append(f"    {mode.upper()}: ₹{amt:.2f}")

        lines.append(f"\n  Top Items:")
        for name, rev in top_items:
            lines.append(f"    • {name}: ₹{rev:.2f}")

        return "\n".join(lines)


def weekly_summary(start_date: str = "") -> str:
    """
    Get a 7-day sales summary for the week. Used to generate the analysis PowerPoint deck.
    Returns daily revenue, total GST, and top products for the period.

    Args:
        start_date: Start date in YYYY-MM-DD format. Defaults to 7 days ago if blank.
    """
    try:
        if start_date:
            start = date.fromisoformat(start_date)
        else:
            start = date.today() - timedelta(days=6)
    except ValueError:
        return f"❌ Invalid date. Use YYYY-MM-DD."

    end = start + timedelta(days=6)
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time())

    with get_db() as db:
        bills = (
            db.query(Bill)
            .filter(
                Bill.status == "finalized",
                Bill.finalized_at >= start_dt,
                Bill.finalized_at <= end_dt,
            )
            .all()
        )

        if not bills:
            return f"📊 No sales between {start} and {end}."

        # Daily breakdown
        daily: dict = {}
        item_revenue: dict = {}
        total_gst = 0.0

        for bill in bills:
            day = bill.finalized_at.date().isoformat()
            daily[day] = daily.get(day, 0) + bill.total
            total_gst += bill.cgst + bill.sgst
            for item in bill.items:
                name = item.product.name
                item_revenue[name] = item_revenue.get(name, 0) + item.line_total

        top_items = sorted(item_revenue.items(), key=lambda x: -x[1])[:10]
        total_revenue = sum(daily.values())

        lines = [
            f"📊 Weekly Report: {start.strftime('%d %b')} – {end.strftime('%d %b %Y')}",
            f"{'═'*40}",
            f"  Total Revenue: ₹{total_revenue:.2f}",
            f"  Total Bills: {len(bills)}",
            f"  GST Collected: ₹{total_gst:.2f}",
            f"\n  Daily Breakdown:",
        ]
        for day, rev in sorted(daily.items()):
            d = date.fromisoformat(day).strftime("%a %d %b")
            lines.append(f"    {d}: ₹{rev:.2f}")

        lines.append(f"\n  Top 10 Products:")
        for name, rev in top_items:
            lines.append(f"    • {name}: ₹{rev:.2f}")

        # Include raw data for PPTX generation
        lines.append(f"\n[WEEKLY_DATA_JSON]")
        import json
        lines.append(json.dumps({
            "period": f"{start} to {end}",
            "daily": daily,
            "top_items": dict(top_items),
            "total_revenue": total_revenue,
            "total_gst": total_gst,
            "total_bills": len(bills),
        }))

        return "\n".join(lines)
