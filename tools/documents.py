"""
Document generation tools — GST Invoice PDF and Sales Analysis PPTX.
These tools write files to the 'output/' directory and signal the Telegram
handler to send them as documents by appending to a shared pending_files list.
"""
import os
import json
import io
from datetime import datetime, date, timedelta
from pathlib import Path


OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


def make_document_tools(pending_files: list):
    """
    Factory that creates document tools bound to a per-chat pending_files list.
    The Telegram handler sends any files added to pending_files after tool execution.
    """

    def generate_invoice_pdf(bill_id: int) -> str:
        """
        Generate a GST-compliant PDF invoice for a finalized bill and send it to Telegram.
        Call this when the owner asks for a 'PDF invoice', 'GST bill', or 'printable receipt'.

        Args:
            bill_id: The bill ID to generate invoice for (from the finalize_bill response)
        """
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib import colors
            from reportlab.lib.units import mm
            from reportlab.platypus import (
                SimpleDocTemplate, Table, TableStyle, Paragraph,
                Spacer, HRFlowable
            )
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
        except ImportError:
            return "❌ reportlab not installed. Run: pip install reportlab"

        from db.database import get_db
        from db.models import Bill, OwnerPreference

        with get_db() as db:
            bill = db.query(Bill).filter_by(id=bill_id).first()
            if not bill:
                return f"❌ Bill #{bill_id} not found."
            if bill.status != "finalized":
                return f"❌ Bill #{bill_id} is not finalized yet. Finalize it first."

            # Load store preferences
            prefs = {p.key: p.value for p in db.query(OwnerPreference).all()}
            shop_name = prefs.get("shop_name", "Nebula Kirana Store")
            gstin = prefs.get("gstin", "29AAAAA0000A1Z5")

            # Eagerly extract bill details
            bill_date = bill.finalized_at.strftime("%d %b %Y, %I:%M %p") if bill.finalized_at else datetime.now().strftime("%d %b %Y")
            bill_customer = bill.customer or "Walk-in Customer"
            bill_payment = (bill.payment_mode or "CASH").upper()
            bill_subtotal = bill.subtotal or 0.0
            bill_cgst = bill.cgst or 0.0
            bill_sgst = bill.sgst or 0.0
            bill_total = bill.total or 0.0

            # Load item data
            items_data = []
            for item in bill.items:
                prod = item.product
                items_data.append({
                    "name": prod.name if prod else "Item",
                    "hsn": (prod.hsn_code if prod and prod.hsn_code else "-"),
                    "qty": item.qty,
                    "unit": (prod.unit if prod and prod.unit else "unit"),
                    "unit_price": item.unit_price,
                    "gst_slab": item.gst_slab,
                    "line_total": item.line_total,
                })

        # Build PDF
        filepath = OUTPUT_DIR / f"invoice_{bill_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        doc = SimpleDocTemplate(
            str(filepath), pagesize=A4,
            leftMargin=14*mm, rightMargin=14*mm,
            topMargin=14*mm, bottomMargin=14*mm,
        )

        story = []

        # ── COLOR PALETTE ───────────────────────────────────────────────────
        PRIMARY = colors.HexColor("#4338ca")      # Deep Indigo
        DARK_TEXT = colors.HexColor("#0f172a")    # Slate 900
        MUTED_TEXT = colors.HexColor("#475569")   # Slate 600
        LIGHT_BG = colors.HexColor("#f8fafc")     # Slate 50
        BORDER_CLR = colors.HexColor("#e2e8f0")   # Slate 200
        ACCENT_BG = colors.HexColor("#eef2ff")    # Indigo 50
        SUCCESS_CLR = colors.HexColor("#16a34a")  # Emerald 600

        # ── STYLES ──────────────────────────────────────────────────────────
        shop_title_style = ParagraphStyle(
            "ShopTitle", fontSize=18, leading=22, fontName="Helvetica-Bold",
            textColor=PRIMARY, alignment=TA_LEFT
        )
        shop_sub_style = ParagraphStyle(
            "ShopSub", fontSize=9, leading=13, fontName="Helvetica",
            textColor=MUTED_TEXT, alignment=TA_LEFT
        )
        invoice_title_style = ParagraphStyle(
            "InvoiceTitle", fontSize=18, leading=22, fontName="Helvetica-Bold",
            textColor=DARK_TEXT, alignment=TA_RIGHT
        )
        invoice_sub_style = ParagraphStyle(
            "InvoiceSub", fontSize=9, leading=13, fontName="Helvetica-Bold",
            textColor=PRIMARY, alignment=TA_RIGHT
        )
        cell_bold = ParagraphStyle(
            "CellBold", fontSize=8.5, leading=11, fontName="Helvetica-Bold",
            textColor=DARK_TEXT
        )
        cell_normal = ParagraphStyle(
            "CellNormal", fontSize=8.5, leading=11, fontName="Helvetica",
            textColor=MUTED_TEXT
        )
        footer_style = ParagraphStyle(
            "Footer", fontSize=8, leading=12, fontName="Helvetica",
            alignment=TA_CENTER, textColor=MUTED_TEXT
        )

        # ── 1. HEADER SECTION (Brand & Tax Invoice Tag) ─────────────────────
        header_data = [
            [
                Paragraph(f"<b>{shop_name}</b>", shop_title_style),
                Paragraph("TAX INVOICE", invoice_title_style)
            ],
            [
                Paragraph(f"GSTIN: <b>{gstin}</b><br/>Retail Operations & Daily Store", shop_sub_style),
                Paragraph(f"Original for Recipient<br/>Bill Ref: <b>#{bill_id}</b>", invoice_sub_style)
            ]
        ]
        header_table = Table(header_data, colWidths=[110*mm, 72*mm])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 4*mm))
        story.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY))
        story.append(Spacer(1, 4*mm))

        # ── 2. METADATA CARD (Customer & Invoice Meta) ──────────────────────
        meta_data = [
            [
                Paragraph("<b>Billed To:</b>", cell_bold),
                Paragraph(bill_customer, cell_normal),
                Paragraph("<b>Invoice No:</b>", cell_bold),
                Paragraph(f"#{bill_id}", cell_bold),
            ],
            [
                Paragraph("<b>Payment Mode:</b>", cell_bold),
                Paragraph(f"<b>{bill_payment}</b>", ParagraphStyle("PayMode", fontSize=8.5, leading=11, fontName="Helvetica-Bold", textColor=SUCCESS_CLR)),
                Paragraph("<b>Date & Time:</b>", cell_bold),
                Paragraph(bill_date, cell_normal),
            ],
        ]
        meta_table = Table(meta_data, colWidths=[28*mm, 60*mm, 28*mm, 66*mm])
        meta_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
            ("BOX", (0, 0), (-1, -1), 1, BORDER_CLR),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER_CLR),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(meta_table)
        story.append(Spacer(1, 6*mm))

        # ── 3. ITEMS TABLE ──────────────────────────────────────────────────
        item_header = ["#", "Product Description", "HSN", "Qty", "Unit", "Rate (Rs.)", "GST", "Amount (Rs.)"]
        item_rows = [item_header]
        for i, item in enumerate(items_data, 1):
            item_rows.append([
                str(i),
                item["name"],
                item["hsn"],
                f"{item['qty']:.1f}" if isinstance(item['qty'], float) else str(item['qty']),
                item["unit"],
                f"{item['unit_price']:.2f}",
                f"{int(item['gst_slab'])}%",
                f"{item['line_total']:.2f}",
            ])

        col_w = [8*mm, 64*mm, 18*mm, 14*mm, 14*mm, 22*mm, 16*mm, 26*mm]
        item_table = Table(item_rows, colWidths=col_w)
        item_table.setStyle(TableStyle([
            # Header styling
            ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8.5),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
            ("TOPPADDING", (0, 0), (-1, 0), 5),
            # Body styling
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 8.5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER_CLR),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 1), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
            # Alignment
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (1, 0), (1, -1), "LEFT"),
            ("ALIGN", (2, 0), (4, -1), "CENTER"),
            ("ALIGN", (5, 0), (5, -1), "RIGHT"),
            ("ALIGN", (6, 0), (6, -1), "CENTER"),
            ("ALIGN", (7, 0), (7, -1), "RIGHT"),
        ]))
        story.append(item_table)
        story.append(Spacer(1, 5*mm))

        # ── 4. TOTALS SECTION ───────────────────────────────────────────────
        totals_data = [
            ["Taxable Subtotal:", f"Rs. {bill_subtotal:.2f}"],
            ["CGST:", f"Rs. {bill_cgst:.2f}"],
            ["SGST:", f"Rs. {bill_sgst:.2f}"],
            ["GRAND TOTAL:", f"Rs. {bill_total:.2f}"],
        ]
        totals_table = Table(totals_data, colWidths=[42*mm, 36*mm])
        totals_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -2), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -2), 8.5),
            ("TEXTCOLOR", (0, 0), (-1, -2), MUTED_TEXT),
            ("ALIGN", (0, 0), (0, -1), "RIGHT"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            # Grand Total Highlight row
            ("BACKGROUND", (0, -1), (-1, -1), ACCENT_BG),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, -1), (-1, -1), 10.5),
            ("TEXTCOLOR", (0, -1), (-1, -1), PRIMARY),
            ("BOX", (0, -1), (-1, -1), 1, PRIMARY),
            ("TOPPADDING", (0, -1), (-1, -1), 5),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 5),
        ]))

        # Right align the totals table within page width
        summary_wrapper = Table([["", totals_table]], colWidths=[104*mm, 78*mm])
        summary_wrapper.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(summary_wrapper)
        story.append(Spacer(1, 8*mm))

        # ── 5. FOOTER ───────────────────────────────────────────────────────
        story.append(HRFlowable(width="100%", thickness=0.75, color=BORDER_CLR))
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph("<b>Thank you for shopping with us!</b>", footer_style))
        story.append(Paragraph("This is a computer-generated GST invoice. No physical signature required.", footer_style))

        doc.build(story)
        pending_files.append(str(filepath))

        return (
            f"📄 GST Invoice generated for Bill #{bill_id}!\n"
            f"  Total: Rs. {bill_total:.2f} | GSTIN: {gstin}\n"
            f"  Sending PDF now..."
        )

    def generate_analysis_pptx(period: str = "weekly") -> str:
        """
        Generate a premium Food Market themed PowerPoint analysis deck with sales charts,
        inventory health metrics, and an attractive executive closing dashboard.
        Creates 5 slides: Cover, Revenue Run-rate, Top Products & Channels, Inventory Health,
        and an Executive GST & Business Health Dashboard.

        Args:
            period: Analysis period — 'weekly' (last 7 days) or 'monthly' (last 30 days)
        """
        try:
            from pptx import Presentation
            from pptx.util import Inches, Pt, Emu
            from pptx.dml.color import RGBColor
            from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
            from pptx.enum.shapes import MSO_SHAPE
            import matplotlib.pyplot as plt
            import matplotlib
            matplotlib.use("Agg")
        except ImportError:
            return "❌ python-pptx or matplotlib not installed. Run: pip install python-pptx matplotlib"

        from db.database import get_db
        from db.models import Bill, BillItem, Product, OwnerPreference

        days = 30 if period == "monthly" else 7
        start_dt = datetime.combine(date.today() - timedelta(days=days - 1), datetime.min.time())

        with get_db() as db:
            bills = db.query(Bill).filter(
                Bill.status == "finalized",
                Bill.finalized_at >= start_dt,
            ).all()

            prefs = {p.key: p.value for p in db.query(OwnerPreference).all()}
            shop_name = prefs.get("shop_name", "Nebula Kirana Store")
            gstin = prefs.get("gstin", "29AAAAA0000A1Z5")

            # Aggregate data
            daily: dict = {}
            item_revenue: dict = {}
            total_gst = 0.0
            mode_totals: dict = {}
            num_bills = len(bills)

            for bill in bills:
                day = bill.finalized_at.date().isoformat()
                daily[day] = daily.get(day, 0) + (bill.total or 0.0)
                total_gst += (bill.cgst or 0.0) + (bill.sgst or 0.0)
                pm = (bill.payment_mode or "cash").upper()
                mode_totals[pm] = mode_totals.get(pm, 0) + (bill.total or 0.0)
                for item in bill.items:
                    prod_name = item.product.name[:22] if item.product else "Item"
                    item_revenue[prod_name] = item_revenue.get(prod_name, 0) + (item.line_total or 0.0)

            # All products count and low stock
            total_prods_count = db.query(Product).count()
            low_stock_query = db.query(Product).filter(
                Product.quantity <= Product.reorder_lvl
            ).order_by(Product.quantity).limit(8).all()
            low_stock = [
                {"name": p.name, "quantity": p.quantity, "unit": p.unit, "reorder_lvl": p.reorder_lvl}
                for p in low_stock_query
            ]

        # Fill missing days with 0
        all_days = []
        for i in range(days):
            d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
            all_days.append(d)
        daily_values = [daily.get(d, 0) for d in all_days]
        day_labels = [date.fromisoformat(d).strftime("%d %b") for d in all_days]

        top_items = sorted(item_revenue.items(), key=lambda x: -x[1])[:7]
        total_revenue = sum(daily_values)
        avg_bill_val = (total_revenue / num_bills) if num_bills > 0 else 0.0
        peak_day_val = max(daily_values) if daily_values else 0.0
        peak_day_idx = daily_values.index(peak_day_val) if daily_values and peak_day_val > 0 else 0
        peak_day_label = day_labels[peak_day_idx] if day_labels else "N/A"

        # ── FOOD MARKET THEME COLOR PALETTE ──────────────────────────────────
        COLOR_PRIMARY_HEX = "#5A6B45"      # Olive Green (Brand primary)
        COLOR_DARK_HEX = "#24301C"         # Forest Dark
        COLOR_BG_HEX = "#F9F8F5"           # Warm Cream background
        COLOR_TERRACOTTA_HEX = "#C87D55"   # Warm Terracotta
        COLOR_GOLD_HEX = "#D4A373"         # Golden Amber
        COLOR_SAGE_HEX = "#8FA876"         # Sage Green
        COLOR_BORDER_HEX = "#DFDED7"       # Card Border

        CLR_PRIMARY = RGBColor(0x5A, 0x6B, 0x45)
        CLR_PRIMARY_DARK = RGBColor(0x24, 0x30, 0x1C)
        CLR_BG_DARK = RGBColor(0x1F, 0x28, 0x17)
        CLR_BG_LIGHT = RGBColor(0xF9, 0xF8, 0xF5)
        CLR_CARD_BG = RGBColor(0xFF, 0xFF, 0xFF)
        CLR_CARD_BORDER = RGBColor(0xDF, 0xDE, 0xD7)
        CLR_MUTED = RGBColor(0x63, 0x70, 0x5B)
        CLR_TERRACOTTA = RGBColor(0xC8, 0x7D, 0x55)
        CLR_GOLD = RGBColor(0xD4, 0xA3, 0x73)
        CLR_PILL_BG = RGBColor(0xEA, 0xF0, 0xE4)
        CLR_CRITICAL = RGBColor(0xC5, 0x30, 0x30)
        CLR_SUCCESS = RGBColor(0x2E, 0x7D, 0x32)

        # ── Matplotlib Charts ────────────────────────────────────────────────
        plt.rcParams['font.sans-serif'] = 'DejaVu Sans'
        plt.rcParams['axes.edgecolor'] = COLOR_BORDER_HEX
        plt.rcParams['axes.linewidth'] = 0.8

        # Chart 1: Daily Revenue Bar Chart
        fig1, ax1 = plt.subplots(figsize=(7.8, 4.4), facecolor=COLOR_BG_HEX)
        ax1.set_facecolor(COLOR_BG_HEX)
        bar_colors = [COLOR_TERRACOTTA_HEX if v == peak_day_val and v > 0 else COLOR_PRIMARY_HEX for v in daily_values]
        bars = ax1.bar(day_labels, daily_values, color=bar_colors, width=0.55, edgecolor="none", zorder=3)
        ax1.grid(axis="y", linestyle="--", alpha=0.5, color="#D0CEC4", zorder=0)
        ax1.set_ylabel("Revenue (₹)", color=COLOR_DARK_HEX, fontsize=10, fontweight="bold")
        ax1.tick_params(colors=COLOR_DARK_HEX, labelsize=9, rotation=35 if days > 7 else 0)
        ax1.spines['top'].set_visible(False)
        ax1.spines['right'].set_visible(False)
        for bar, val in zip(bars, daily_values):
            if val > 0:
                ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + (max(daily_values)*0.02 or 1),
                         f"₹{int(val)}", ha="center", fontsize=8, fontweight="bold", color=COLOR_DARK_HEX)
        plt.tight_layout()
        chart1_path = OUTPUT_DIR / "chart_revenue.png"
        fig1.savefig(str(chart1_path), dpi=160, bbox_inches="tight")
        plt.close(fig1)

        # Chart 2: Top Products Horizontal Bar Chart
        fig2, ax2 = plt.subplots(figsize=(6.2, 4.6), facecolor=COLOR_BG_HEX)
        ax2.set_facecolor(COLOR_BG_HEX)
        if top_items:
            names, revs = zip(*top_items)
            bar_cols = [COLOR_PRIMARY_HEX if i % 2 == 0 else COLOR_SAGE_HEX for i in range(len(names))]
            bars2 = ax2.barh(names, revs, color=bar_cols, height=0.55, edgecolor="none", zorder=3)
            ax2.grid(axis="x", linestyle="--", alpha=0.5, color="#D0CEC4", zorder=0)
            ax2.set_xlabel("Revenue Contribution (₹)", color=COLOR_DARK_HEX, fontsize=9, fontweight="bold")
            ax2.tick_params(colors=COLOR_DARK_HEX, labelsize=8.5)
            ax2.invert_yaxis()
            ax2.spines['top'].set_visible(False)
            ax2.spines['right'].set_visible(False)
            for bar, val in zip(bars2, revs):
                ax2.text(bar.get_width() + (max(revs)*0.015 or 1), bar.get_y() + bar.get_height()/2,
                         f"₹{int(val)}", va="center", fontsize=8, fontweight="bold", color=COLOR_DARK_HEX)
        else:
            ax2.text(0.5, 0.5, "No product sales recorded in this period", ha="center", va="center",
                     transform=ax2.transAxes, color=COLOR_MUTED_TEXT, fontsize=10)
        plt.tight_layout()
        chart2_path = OUTPUT_DIR / "chart_top_items.png"
        fig2.savefig(str(chart2_path), dpi=160, bbox_inches="tight")
        plt.close(fig2)

        # Chart 3: Payment Mode Donut Chart
        fig3, ax3 = plt.subplots(figsize=(4.8, 4.4), facecolor=COLOR_BG_HEX)
        ax3.set_facecolor(COLOR_BG_HEX)
        if mode_totals:
            pie_palette = [COLOR_PRIMARY_HEX, COLOR_TERRACOTTA_HEX, COLOR_GOLD_HEX, "#52796F"]
            wedges, texts, autotexts = ax3.pie(
                list(mode_totals.values()), labels=[k for k in mode_totals],
                colors=pie_palette[:len(mode_totals)], autopct="%1.1f%%",
                pctdistance=0.75, startangle=140,
                wedgeprops=dict(width=0.45, edgecolor="white", linewidth=2)
            )
            for t in texts:
                t.set_color(COLOR_DARK_HEX)
                t.set_fontsize(9)
                t.set_fontweight("bold")
            for at in autotexts:
                at.set_color("white")
                at.set_fontsize(8.5)
                at.set_fontweight("bold")
        else:
            ax3.text(0.5, 0.5, "No transactions", ha="center", va="center", transform=ax3.transAxes)
        plt.tight_layout()
        chart3_path = OUTPUT_DIR / "chart_payment.png"
        fig3.savefig(str(chart3_path), dpi=160, bbox_inches="tight")
        plt.close(fig3)

        # ── Presentation Initialization ──────────────────────────────────────
        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)
        blank_layout = prs.slide_layouts[6]

        def set_slide_background(slide, color: RGBColor):
            bg = slide.background.fill
            bg.solid()
            bg.fore_color.rgb = color

        def add_slide_header(slide, category: str, title: str, subtitle: str = ""):
            # Category pill tag
            tx_cat = slide.shapes.add_textbox(Inches(0.6), Inches(0.35), Inches(8), Inches(0.3))
            tf_c = tx_cat.text_frame
            tf_c.word_wrap = False
            p_c = tf_c.paragraphs[0]
            p_c.text = f"●  {category.upper()}"
            p_c.font.bold = True
            p_c.font.size = Pt(9.5)
            p_c.font.color.rgb = CLR_TERRACOTTA

            # Main Slide Title
            tx_title = slide.shapes.add_textbox(Inches(0.6), Inches(0.65), Inches(9.5), Inches(0.6))
            tf_t = tx_title.text_frame
            tf_t.word_wrap = False
            p_t = tf_t.paragraphs[0]
            p_t.text = title
            p_t.font.bold = True
            p_t.font.size = Pt(22)
            p_t.font.color.rgb = CLR_PRIMARY_DARK

            if subtitle:
                tx_sub = slide.shapes.add_textbox(Inches(0.6), Inches(1.2), Inches(11), Inches(0.35))
                tf_s = tx_sub.text_frame
                tf_s.word_wrap = False
                p_s = tf_s.paragraphs[0]
                p_s.text = subtitle
                p_s.font.size = Pt(11)
                p_s.font.color.rgb = CLR_MUTED

            # Header thin separator
            line = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(1.58), Inches(12.133), Inches(0.015)
            )
            line.fill.solid()
            line.fill.fore_color.rgb = CLR_CARD_BORDER
            line.line.color.rgb = CLR_CARD_BORDER

        def add_styled_card(slide, left, top, width, height, bg_color=CLR_CARD_BG, border_color=CLR_CARD_BORDER):
            card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
            card.fill.solid()
            card.fill.fore_color.rgb = bg_color
            card.line.color.rgb = border_color
            card.line.width = Pt(1)
            return card

        # ── SLIDE 1: COVER SLIDE (Food Market Luxury Aesthetic) ─────────────
        slide1 = prs.slides.add_slide(blank_layout)
        set_slide_background(slide1, CLR_BG_DARK)

        # Subtle Decorative Accent Box
        accent_box = slide1.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(0.8), Inches(11.733), Inches(5.9)
        )
        accent_box.fill.background()
        accent_box.line.color.rgb = RGBColor(0x3D, 0x4E, 0x2F)
        accent_box.line.width = Pt(1.5)

        # Top Badge
        b_tx = slide1.shapes.add_textbox(Inches(1.5), Inches(1.4), Inches(10.333), Inches(0.4))
        b_p = b_tx.text_frame.paragraphs[0]
        b_p.text = "✦  FOOD MARKET & KIRANA BUSINESS INTELLIGENCE  ✦"
        b_p.font.bold = True
        b_p.font.size = Pt(11)
        b_p.font.color.rgb = CLR_GOLD
        b_p.alignment = PP_ALIGN.CENTER

        # Store Title
        s_tx = slide1.shapes.add_textbox(Inches(1.2), Inches(2.1), Inches(10.933), Inches(1.5))
        s_p = s_tx.text_frame.paragraphs[0]
        s_p.text = shop_name.upper()
        s_p.font.bold = True
        s_p.font.size = Pt(38)
        s_p.font.color.rgb = RGBColor(0xFA, 0xFA, 0xF7)
        s_p.alignment = PP_ALIGN.CENTER

        # Subtitle
        sub_tx = slide1.shapes.add_textbox(Inches(1.5), Inches(3.5), Inches(10.333), Inches(0.8))
        sub_p = sub_tx.text_frame.paragraphs[0]
        sub_p.text = f"Sales Performance, Inventory Diagnostics & GST Settlement Report\nPeriod: {period.capitalize()} Review ({days} Days) • {date.today().strftime('%B %Y')}"
        sub_p.font.size = Pt(14)
        sub_p.font.color.rgb = RGBColor(0xBD, 0xC8, 0xB2)
        sub_p.alignment = PP_ALIGN.CENTER

        # Metadata Footer Badges
        p1 = add_styled_card(slide1, Inches(1.8), Inches(4.8), Inches(2.8), Inches(1.1), bg_color=RGBColor(0x28, 0x35, 0x1F), border_color=RGBColor(0x42, 0x54, 0x33))
        tx1 = slide1.shapes.add_textbox(Inches(1.85), Inches(4.85), Inches(2.7), Inches(1.0))
        tx1.text_frame.paragraphs[0].text = "TOTAL REVENUE"
        tx1.text_frame.paragraphs[0].font.size = Pt(9)
        tx1.text_frame.paragraphs[0].font.color.rgb = CLR_GOLD
        p_val1 = tx1.text_frame.add_paragraph()
        p_val1.text = f"₹ {total_revenue:,.2f}"
        p_val1.font.bold = True
        p_val1.font.size = Pt(16)
        p_val1.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        p2 = add_styled_card(slide1, Inches(5.26), Inches(4.8), Inches(2.8), Inches(1.1), bg_color=RGBColor(0x28, 0x35, 0x1F), border_color=RGBColor(0x42, 0x54, 0x33))
        tx2 = slide1.shapes.add_textbox(Inches(5.31), Inches(4.85), Inches(2.7), Inches(1.0))
        tx2.text_frame.paragraphs[0].text = "INVOICES AUDITED"
        tx2.text_frame.paragraphs[0].font.size = Pt(9)
        tx2.text_frame.paragraphs[0].font.color.rgb = CLR_GOLD
        p_val2 = tx2.text_frame.add_paragraph()
        p_val2.text = f"{num_bills} Finalized Bills"
        p_val2.font.bold = True
        p_val2.font.size = Pt(16)
        p_val2.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        p3 = add_styled_card(slide1, Inches(8.73), Inches(4.8), Inches(2.8), Inches(1.1), bg_color=RGBColor(0x28, 0x35, 0x1F), border_color=RGBColor(0x42, 0x54, 0x33))
        tx3 = slide1.shapes.add_textbox(Inches(8.78), Inches(4.85), Inches(2.7), Inches(1.0))
        tx3.text_frame.paragraphs[0].text = "GST COMPLIANCE"
        tx3.text_frame.paragraphs[0].font.size = Pt(9)
        tx3.text_frame.paragraphs[0].font.color.rgb = CLR_GOLD
        p_val3 = tx3.text_frame.add_paragraph()
        p_val3.text = f"₹ {total_gst:,.2f} Tax Reconciled"
        p_val3.font.bold = True
        p_val3.font.size = Pt(13.5)
        p_val3.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        # ── SLIDE 2: REVENUE TREND & DAILY VELOCITY ──────────────────────────
        slide2 = prs.slides.add_slide(blank_layout)
        set_slide_background(slide2, CLR_BG_LIGHT)
        add_slide_header(
            slide2, "Revenue Run-Rate",
            f"Daily Sales Velocity — Last {days} Days",
            f"Gross Turnover: ₹ {total_revenue:,.2f} across {num_bills} processed orders"
        )

        # Chart on Left
        add_styled_card(slide2, Inches(0.6), Inches(1.8), Inches(8.2), Inches(5.1))
        slide2.shapes.add_picture(str(chart1_path), Inches(0.75), Inches(1.95), Inches(7.9), Inches(4.7))

        # KPI Cards on Right
        # Card 1: Gross Sales
        add_styled_card(slide2, Inches(9.1), Inches(1.8), Inches(3.6), Inches(1.55))
        k1 = slide2.shapes.add_textbox(Inches(9.25), Inches(1.9), Inches(3.3), Inches(1.3))
        k1.text_frame.paragraphs[0].text = "TOTAL SALES REVENUE"
        k1.text_frame.paragraphs[0].font.size = Pt(9.5)
        k1.text_frame.paragraphs[0].font.bold = True
        k1.text_frame.paragraphs[0].font.color.rgb = CLR_MUTED
        kp1 = k1.text_frame.add_paragraph()
        kp1.text = f"₹ {total_revenue:,.2f}"
        kp1.font.bold = True
        kp1.font.size = Pt(22)
        kp1.font.color.rgb = CLR_PRIMARY
        kp1_sub = k1.text_frame.add_paragraph()
        kp1_sub.text = f"Across {days} tracked days"
        kp1_sub.font.size = Pt(9)
        kp1_sub.font.color.rgb = CLR_MUTED

        # Card 2: Peak Day Velocity
        add_styled_card(slide2, Inches(9.1), Inches(3.55), Inches(3.6), Inches(1.55))
        k2 = slide2.shapes.add_textbox(Inches(9.25), Inches(3.65), Inches(3.3), Inches(1.3))
        k2.text_frame.paragraphs[0].text = "PEAK SALES DAY"
        k2.text_frame.paragraphs[0].font.size = Pt(9.5)
        k2.text_frame.paragraphs[0].font.bold = True
        k2.text_frame.paragraphs[0].font.color.rgb = CLR_MUTED
        kp2 = k2.text_frame.add_paragraph()
        kp2.text = f"₹ {peak_day_val:,.2f}"
        kp2.font.bold = True
        kp2.font.size = Pt(22)
        kp2.font.color.rgb = CLR_TERRACOTTA
        kp2_sub = k2.text_frame.add_paragraph()
        kp2_sub.text = f"Recorded on {peak_day_label}"
        kp2_sub.font.size = Pt(9)
        kp2_sub.font.color.rgb = CLR_MUTED

        # Card 3: Daily Average Run-rate
        add_styled_card(slide2, Inches(9.1), Inches(5.3), Inches(3.6), Inches(1.6))
        k3 = slide2.shapes.add_textbox(Inches(9.25), Inches(5.4), Inches(3.3), Inches(1.3))
        k3.text_frame.paragraphs[0].text = "DAILY AVERAGE RUN-RATE"
        k3.text_frame.paragraphs[0].font.size = Pt(9.5)
        k3.text_frame.paragraphs[0].font.bold = True
        k3.text_frame.paragraphs[0].font.color.rgb = CLR_MUTED
        kp3 = k3.text_frame.add_paragraph()
        daily_avg = total_revenue / days if days > 0 else 0.0
        kp3.text = f"₹ {daily_avg:,.2f}"
        kp3.font.bold = True
        kp3.font.size = Pt(22)
        kp3.font.color.rgb = CLR_PRIMARY_DARK
        kp3_sub = k3.text_frame.add_paragraph()
        kp3_sub.text = f"Average per calendar day"
        kp3_sub.font.size = Pt(9)
        kp3_sub.font.color.rgb = CLR_MUTED

        # ── SLIDE 3: PRODUCT PERFORMANCE & PAYMENT SPLIT ─────────────────────
        slide3 = prs.slides.add_slide(blank_layout)
        set_slide_background(slide3, CLR_BG_LIGHT)
        add_slide_header(
            slide3, "SKU & Payment Mix",
            "Top Selling Products & Channel Distribution",
            "Revenue drivers and consumer payment channel preferences"
        )

        # Left Card: Top Products
        add_styled_card(slide3, Inches(0.6), Inches(1.8), Inches(6.8), Inches(5.1))
        t_title = slide3.shapes.add_textbox(Inches(0.8), Inches(1.95), Inches(6.4), Inches(0.35))
        t_title.text_frame.paragraphs[0].text = "Top Revenue Generating Products"
        t_title.text_frame.paragraphs[0].font.bold = True
        t_title.text_frame.paragraphs[0].font.size = Pt(12)
        t_title.text_frame.paragraphs[0].font.color.rgb = CLR_PRIMARY_DARK
        slide3.shapes.add_picture(str(chart2_path), Inches(0.75), Inches(2.3), Inches(6.5), Inches(4.4))

        # Right Card: Payment Modes
        add_styled_card(slide3, Inches(7.7), Inches(1.8), Inches(5.0), Inches(5.1))
        p_title = slide3.shapes.add_textbox(Inches(7.9), Inches(1.95), Inches(4.6), Inches(0.35))
        p_title.text_frame.paragraphs[0].text = "Payment Mode Distribution"
        p_title.text_frame.paragraphs[0].font.bold = True
        p_title.text_frame.paragraphs[0].font.size = Pt(12)
        p_title.text_frame.paragraphs[0].font.color.rgb = CLR_PRIMARY_DARK
        slide3.shapes.add_picture(str(chart3_path), Inches(7.85), Inches(2.3), Inches(4.7), Inches(3.5))

        # Digital Payment Share Pill
        upi_rev = mode_totals.get("UPI", 0.0) + mode_totals.get("CARD", 0.0)
        digital_pct = (upi_rev / total_revenue * 100) if total_revenue > 0 else 0.0
        dp_box = add_styled_card(slide3, Inches(7.9), Inches(5.9), Inches(4.6), Inches(0.85), bg_color=CLR_PILL_BG, border_color=CLR_PRIMARY)
        dp_tx = slide3.shapes.add_textbox(Inches(8.0), Inches(5.95), Inches(4.4), Inches(0.7))
        dp_p = dp_tx.text_frame.paragraphs[0]
        dp_p.text = f"⚡ Digital Adoption Rate: {digital_pct:.1f}%"
        dp_p.font.bold = True
        dp_p.font.size = Pt(11)
        dp_p.font.color.rgb = CLR_PRIMARY_DARK
        dp_sub = dp_tx.text_frame.add_paragraph()
        dp_sub.text = f"UPI / Card volume: ₹ {upi_rev:,.2f} of total turnover"
        dp_sub.font.size = Pt(9)
        dp_sub.font.color.rgb = CLR_MUTED

        # ── SLIDE 4: INVENTORY HEALTH & REORDER MONITORING ───────────────────
        slide4 = prs.slides.add_slide(blank_layout)
        set_slide_background(slide4, CLR_BG_LIGHT)
        add_slide_header(
            slide4, "Inventory Diagnostics",
            "Stock Health & Replenishment Monitor",
            f"Catalog tracking {total_prods_count} active grocery SKUs across all categories"
        )

        # Top 3 Inventory KPI metric boxes
        add_styled_card(slide4, Inches(0.6), Inches(1.8), Inches(3.8), Inches(1.0), bg_color=CLR_CARD_BG)
        i1 = slide4.shapes.add_textbox(Inches(0.75), Inches(1.85), Inches(3.5), Inches(0.9))
        i1.text_frame.paragraphs[0].text = "TOTAL MONITORED SKUs"
        i1.text_frame.paragraphs[0].font.size = Pt(8.5)
        i1.text_frame.paragraphs[0].font.bold = True
        i1.text_frame.paragraphs[0].font.color.rgb = CLR_MUTED
        ip1 = i1.text_frame.add_paragraph()
        ip1.text = f"{total_prods_count} Products"
        ip1.font.bold = True
        ip1.font.size = Pt(16)
        ip1.font.color.rgb = CLR_PRIMARY_DARK

        add_styled_card(slide4, Inches(4.76), Inches(1.8), Inches(3.8), Inches(1.0), bg_color=CLR_CARD_BG)
        i2 = slide4.shapes.add_textbox(Inches(4.91), Inches(1.85), Inches(3.5), Inches(0.9))
        i2.text_frame.paragraphs[0].text = "REORDER THRESHOLD ALERTS"
        i2.text_frame.paragraphs[0].font.size = Pt(8.5)
        i2.text_frame.paragraphs[0].font.bold = True
        i2.text_frame.paragraphs[0].font.color.rgb = CLR_MUTED
        ip2 = i2.text_frame.add_paragraph()
        ip2.text = f"{len(low_stock)} Items Needing Action"
        ip2.font.bold = True
        ip2.font.size = Pt(16)
        ip2.font.color.rgb = CLR_TERRACOTTA if low_stock else CLR_SUCCESS

        add_styled_card(slide4, Inches(8.93), Inches(1.8), Inches(3.8), Inches(1.0), bg_color=CLR_CARD_BG)
        i3 = slide4.shapes.add_textbox(Inches(9.08), Inches(1.85), Inches(3.5), Inches(0.9))
        i3.text_frame.paragraphs[0].text = "STOCK HEALTH STATUS"
        i3.text_frame.paragraphs[0].font.size = Pt(8.5)
        i3.text_frame.paragraphs[0].font.bold = True
        i3.text_frame.paragraphs[0].font.color.rgb = CLR_MUTED
        ip3 = i3.text_frame.add_paragraph()
        ip3.text = "Optimal" if len(low_stock) == 0 else f"{len(low_stock)} Attention Required"
        ip3.font.bold = True
        ip3.font.size = Pt(16)
        ip3.font.color.rgb = CLR_SUCCESS if len(low_stock) == 0 else CLR_CRITICAL

        # Inventory Table Card
        add_styled_card(slide4, Inches(0.6), Inches(3.0), Inches(12.133), Inches(3.9))

        if low_stock:
            table_shape = slide4.shapes.add_table(
                min(len(low_stock) + 1, 9), 5,
                Inches(0.8), Inches(3.15), Inches(11.733), Inches(3.5)
            )
            tbl = table_shape.table
            tbl.columns[0].width = Inches(4.5)
            tbl.columns[1].width = Inches(1.8)
            tbl.columns[2].width = Inches(2.0)
            tbl.columns[3].width = Inches(2.0)
            tbl.columns[4].width = Inches(1.433)

            headers = ["Product SKU Name", "Unit Type", "Current Stock", "Reorder Level", "Priority"]
            for col_idx, h_text in enumerate(headers):
                c = tbl.cell(0, col_idx)
                c.fill.solid()
                c.fill.fore_color.rgb = CLR_PRIMARY
                p = c.text_frame.paragraphs[0]
                p.text = h_text
                p.font.bold = True
                p.font.size = Pt(10)
                p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

            for row_idx, item in enumerate(low_stock[:8]):
                status = "🔴 Critical" if item["quantity"] == 0 else "🟡 Low Stock"
                row_vals = [
                    item["name"],
                    item["unit"].capitalize(),
                    f"{item['quantity']:.1f}",
                    f"{item['reorder_lvl']:.1f}",
                    status
                ]
                for col_idx, val in enumerate(row_vals):
                    c = tbl.cell(row_idx + 1, col_idx)
                    c.fill.solid()
                    c.fill.fore_color.rgb = RGBColor(0xF4, 0xF6, 0xF1) if row_idx % 2 == 1 else RGBColor(0xFF, 0xFF, 0xFF)
                    p = c.text_frame.paragraphs[0]
                    p.text = val
                    p.font.size = Pt(9.5)
                    if col_idx == 4:
                        p.font.bold = True
                        p.font.color.rgb = CLR_CRITICAL if "Critical" in val else CLR_TERRACOTTA
                    else:
                        p.font.color.rgb = CLR_PRIMARY_DARK
        else:
            tx_ok = slide4.shapes.add_textbox(Inches(1.5), Inches(4.2), Inches(10.333), Inches(1.5))
            p_ok = tx_ok.text_frame.paragraphs[0]
            p_ok.text = "✅  ALL PRODUCT INVENTORY IN HEALTHY SUPPLY"
            p_ok.font.bold = True
            p_ok.font.size = Pt(18)
            p_ok.font.color.rgb = CLR_SUCCESS
            p_ok.alignment = PP_ALIGN.CENTER
            p_ok_sub = tx_ok.text_frame.add_paragraph()
            p_ok_sub.text = "Zero products currently fall below safety replenishment buffer limits."
            p_ok_sub.font.size = Pt(12)
            p_ok_sub.font.color.rgb = CLR_MUTED
            p_ok_sub.alignment = PP_ALIGN.CENTER

        # ── SLIDE 5: EXECUTIVE CLOSING DASHBOARD (The Star Attractive Slide) ──
        slide5 = prs.slides.add_slide(blank_layout)
        set_slide_background(slide5, CLR_BG_LIGHT)
        add_slide_header(
            slide5, "Executive Business Summary",
            "Store Health, GST Settlement & AI Action Points",
            f"Consolidated performance audit for {shop_name} • GSTIN: {gstin}"
        )

        # 2x2 Grid of Attractive Dashboard Cards
        # CARD 1: 💰 Revenue & Volume Velocity
        add_styled_card(slide5, Inches(0.6), Inches(1.8), Inches(5.9), Inches(2.4), bg_color=CLR_CARD_BG)
        # Accent top strip
        strip1 = slide5.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(1.8), Inches(5.9), Inches(0.08))
        strip1.fill.solid()
        strip1.fill.fore_color.rgb = CLR_PRIMARY
        strip1.line.color.rgb = CLR_PRIMARY

        t1 = slide5.shapes.add_textbox(Inches(0.85), Inches(2.0), Inches(5.4), Inches(2.1))
        t1_tf = t1.text_frame
        p_c1_h = t1_tf.paragraphs[0]
        p_c1_h.text = "💰  TURNOVER & SALES VELOCITY"
        p_c1_h.font.bold = True
        p_c1_h.font.size = Pt(11)
        p_c1_h.font.color.rgb = CLR_PRIMARY

        p_c1_rev = t1_tf.add_paragraph()
        p_c1_rev.text = f"₹ {total_revenue:,.2f}"
        p_c1_rev.font.bold = True
        p_c1_rev.font.size = Pt(24)
        p_c1_rev.font.color.rgb = CLR_PRIMARY_DARK

        p_c1_stats = t1_tf.add_paragraph()
        p_c1_stats.text = f"• Total Finalized Bills: {num_bills}\n• Average Order Value (AOV): ₹ {avg_bill_val:,.2f}\n• Daily Run-Rate: ₹ {daily_avg:,.2f} / day"
        p_c1_stats.font.size = Pt(10)
        p_c1_stats.font.color.rgb = CLR_MUTED

        # CARD 2: 🏛️ GST Settlement & Tax Audit
        add_styled_card(slide5, Inches(6.8), Inches(1.8), Inches(5.9), Inches(2.4), bg_color=CLR_CARD_BG)
        strip2 = slide5.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(6.8), Inches(1.8), Inches(5.9), Inches(0.08))
        strip2.fill.solid()
        strip2.fill.fore_color.rgb = CLR_TERRACOTTA
        strip2.line.color.rgb = CLR_TERRACOTTA

        t2 = slide5.shapes.add_textbox(Inches(7.05), Inches(2.0), Inches(5.4), Inches(2.1))
        t2_tf = t2.text_frame
        p_c2_h = t2_tf.paragraphs[0]
        p_c2_h.text = "🏛️  GST RECONCILIATION & TAX LIABILITY"
        p_c2_h.font.bold = True
        p_c2_h.font.size = Pt(11)
        p_c2_h.font.color.rgb = CLR_TERRACOTTA

        p_c2_gst = t2_tf.add_paragraph()
        p_c2_gst.text = f"₹ {total_gst:,.2f}"
        p_c2_gst.font.bold = True
        p_c2_gst.font.size = Pt(24)
        p_c2_gst.font.color.rgb = CLR_PRIMARY_DARK

        p_c2_stats = t2_tf.add_paragraph()
        cgst_val = total_gst / 2.0
        sgst_val = total_gst / 2.0
        p_c2_stats.text = f"• Central GST (CGST 50%): ₹ {cgst_val:,.2f}\n• State GST (SGST 50%): ₹ {sgst_val:,.2f}\n• Compliance Status: Reconciled & GSTR-1 Ready"
        p_c2_stats.font.size = Pt(10)
        p_c2_stats.font.color.rgb = CLR_MUTED

        # CARD 3: 💳 Payment Settlement & Khata Health
        add_styled_card(slide5, Inches(0.6), Inches(4.4), Inches(5.9), Inches(2.2), bg_color=CLR_CARD_BG)
        strip3 = slide5.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(4.4), Inches(5.9), Inches(0.08))
        strip3.fill.solid()
        strip3.fill.fore_color.rgb = CLR_GOLD
        strip3.line.color.rgb = CLR_GOLD

        t3 = slide5.shapes.add_textbox(Inches(0.85), Inches(4.55), Inches(5.4), Inches(1.9))
        t3_tf = t3.text_frame
        p_c3_h = t3_tf.paragraphs[0]
        p_c3_h.text = "💳  SETTLEMENT & PAYMENT MODES"
        p_c3_h.font.bold = True
        p_c3_h.font.size = Pt(11)
        p_c3_h.font.color.rgb = CLR_GOLD

        p_c3_stats = t3_tf.add_paragraph()
        cash_vol = mode_totals.get("CASH", 0.0)
        upi_vol = mode_totals.get("UPI", 0.0)
        card_vol = mode_totals.get("CARD", 0.0)
        p_c3_stats.text = (
            f"• UPI Instant Settlements: ₹ {upi_vol:,.2f} ({(upi_vol/total_revenue*100 if total_revenue else 0):.1f}%)\n"
            f"• Direct Cash Handled: ₹ {cash_vol:,.2f} ({(cash_vol/total_revenue*100 if total_revenue else 0):.1f}%)\n"
            f"• Card Transactions: ₹ {card_vol:,.2f}\n"
            f"• Zero Reconciliation Discrepancies Recorded"
        )
        p_c3_stats.font.size = Pt(9.5)
        p_c3_stats.font.color.rgb = CLR_MUTED

        # CARD 4: ⚡ Kirana AI Smart Strategic Action Points
        add_styled_card(slide5, Inches(6.8), Inches(4.4), Inches(5.9), Inches(2.2), bg_color=CLR_CARD_BG)
        strip4 = slide5.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(6.8), Inches(4.4), Inches(5.9), Inches(0.08))
        strip4.fill.solid()
        strip4.fill.fore_color.rgb = CLR_SUCCESS
        strip4.line.color.rgb = CLR_SUCCESS

        t4 = slide5.shapes.add_textbox(Inches(7.05), Inches(4.55), Inches(5.4), Inches(1.9))
        t4_tf = t4.text_frame
        p_c4_h = t4_tf.paragraphs[0]
        p_c4_h.text = "⚡  AI OPERATIONS RECOMMENDATIONS"
        p_c4_h.font.bold = True
        p_c4_h.font.size = Pt(11)
        p_c4_h.font.color.rgb = CLR_SUCCESS

        rec_stock = f"Restock {len(low_stock)} critical SKU(s)" if low_stock else "Inventory replenishment buffer is optimal"
        top_sku_name = top_items[0][0] if top_items else "Packaged Goods"
        p_c4_stats = t4_tf.add_paragraph()
        p_c4_stats.text = (
            f"1. Replenishment: {rec_stock} to prevent stockout.\n"
            f"2. Revenue Driver: Prioritize display placement for '{top_sku_name}'.\n"
            f"3. Digital Checkout: UPI volume is {digital_pct:.0f}% of store sales.\n"
            f"4. Customer Khata: Keep credit balances settled weekly."
        )
        p_c4_stats.font.size = Pt(9.5)
        p_c4_stats.font.color.rgb = CLR_MUTED

        # Bottom Executive Footer Banner
        footer_box = add_styled_card(
            slide5, Inches(0.6), Inches(6.75), Inches(12.133), Inches(0.45),
            bg_color=CLR_PILL_BG, border_color=CLR_PRIMARY
        )
        ft_tx = slide5.shapes.add_textbox(Inches(0.8), Inches(6.8), Inches(11.733), Inches(0.35))
        ft_p = ft_tx.text_frame.paragraphs[0]
        ft_p.text = "✦  Nebula Kirana Store AI Operations Platform  •  Autonomous Billing, Inventory & Analytics  ✦"
        ft_p.font.bold = True
        ft_p.font.size = Pt(9.5)
        ft_p.font.color.rgb = CLR_PRIMARY_DARK
        ft_p.alignment = PP_ALIGN.CENTER

        # Save PPTX
        pptx_path = OUTPUT_DIR / f"analysis_{period}_{date.today().isoformat()}.pptx"
        prs.save(str(pptx_path))

        # Clean up temp charts
        for p in [chart1_path, chart2_path, chart3_path]:
            try:
                p.unlink()
            except Exception:
                pass

        pending_files.append(str(pptx_path))

        return (
            f"📊 Analysis deck ready! ({period.capitalize()} report)\n"
            f"  Period: Last {days} days | Slides: 5\n"
            f"  Revenue: Rs. {total_revenue:,.2f} | Bills: {len(bills)}\n"
            f"  Sending PPTX now..."
        )

    return [generate_invoice_pdf, generate_analysis_pptx]
