"""Yearly holiday-sheet PDF — 12 mini-month grids on A4 portrait."""
from __future__ import annotations

import calendar
from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
)

PEACH = colors.HexColor("#F4B68A")
PEACH_DARK = colors.HexColor("#E89A66")
TITLE_BLUE = colors.HexColor("#1a3a8c")
GRID_LINE = colors.HexColor("#1a1a1a")

LEAVE_FILL = {
    "AL":      colors.HexColor("#C2185B"),
    "TRN":     colors.HexColor("#B71C1C"),
    "OFF_REQ": colors.HexColor("#5A8A4A"),
}
LEAVE_TEXT = colors.white
HOL_FILL = colors.HexColor("#A8C5E0")  # public holiday band

DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_NAMES = list(calendar.month_name)


def render_holiday_pdf(
    year: int,
    leave_rows: list[dict],
    public_holidays: list[dict],
    home_name: str = "Grizedale",
    theme: str = "paper",
) -> bytes:
    """leave_rows = [{staff_initials, date, type, ...}, ...]
       public_holidays = [{date, name}, ...]
       theme = "paper" | "modern" — picks chrome palette only.
    """
    # Theme-aware chrome (shift / leave colours stay the same).
    if theme == "modern":
        peach = colors.HexColor("#E2E8F0")        # slate-200
        title_colour = colors.HexColor("#0F172A")  # slate-900
        title_font = "Helvetica-Bold"
    else:
        peach = PEACH
        title_colour = TITLE_BLUE
        title_font = "Times-BoldItalic"
    by_date: dict[str, list[dict]] = {}
    for row in leave_rows:
        by_date.setdefault(row["date"], []).append(row)
    hol_dates = {h["date"] for h in (public_holidays or [])}

    title_style = ParagraphStyle(
        "yh-title", fontName=title_font, fontSize=14,
        textColor=title_colour, alignment=1, spaceAfter=6,
    )
    foot_style = ParagraphStyle(
        "yh-foot", fontName="Helvetica", fontSize=7,
        textColor=colors.HexColor("#555"), alignment=0,
    )
    month_title_style = ParagraphStyle(
        "yh-mt", fontName="Helvetica-Bold", fontSize=9,
        textColor=colors.HexColor("#1a1a1a"), alignment=1, spaceAfter=2,
    )

    flow: list = [
        Paragraph(
            f"{home_name} Annual Holiday Sheet {year}".upper(),
            title_style,
        ),
        Spacer(1, 4),
    ]

    # Build 12 mini-month tables in a 4×3 grid (rows of months).
    cal = calendar.Calendar(firstweekday=0)  # Monday-first

    def _build_month(month_idx: int):
        weeks = cal.monthdayscalendar(year, month_idx)
        rows = [DOW]
        for wk in weeks:
            row = []
            for d in wk:
                if d == 0:
                    row.append("")
                else:
                    iso = f"{year}-{month_idx:02d}-{d:02d}"
                    initials = [r["staff_initials"] for r in by_date.get(iso, [])]
                    cell_text = str(d)
                    if initials:
                        cell_text += "\n" + ",".join(sorted(set(initials))[:3])
                    rows.append  # appease lint
                    row.append(cell_text)
            rows.append(row)

        col_w = 16
        row_h = [10] + [16] * (len(rows) - 1)
        t = Table(rows, colWidths=[col_w] * 7, rowHeights=row_h)
        st = TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.3, GRID_LINE),
            ("BACKGROUND", (0, 0), (-1, 0), peach),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 6),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
            ("FONT", (0, 1), (-1, -1), "Helvetica", 6),
            ("ALIGN", (0, 1), (-1, -1), "CENTER"),
            ("VALIGN", (0, 1), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 1), (-1, -1), 1),
        ])
        # Apply leave / holiday colours
        for ri, wk in enumerate(weeks, start=1):
            for ci, d in enumerate(wk):
                if d == 0:
                    continue
                iso = f"{year}-{month_idx:02d}-{d:02d}"
                rows_here = by_date.get(iso) or []
                # Pick the first leave type's colour for the cell. AL > TRN > OFF_REQ.
                fill = None
                for typ in ("AL", "TRN", "OFF_REQ"):
                    if any(r.get("type") == typ for r in rows_here):
                        fill = LEAVE_FILL[typ]
                        break
                if fill:
                    st.add("BACKGROUND", (ci, ri), (ci, ri), fill)
                    st.add("TEXTCOLOR", (ci, ri), (ci, ri), LEAVE_TEXT)
                elif iso in hol_dates:
                    st.add("BACKGROUND", (ci, ri), (ci, ri), HOL_FILL)
                # Weekend tint (if no leave)
                elif ci >= 5:
                    st.add("BACKGROUND", (ci, ri), (ci, ri), colors.HexColor("#F8E5D2"))
        t.setStyle(st)
        return t

    for grid_row_start in range(1, 13, 4):
        cells = []
        for m in range(grid_row_start, grid_row_start + 4):
            inner = Table(
                [[Paragraph(MONTH_NAMES[m], month_title_style)], [_build_month(m)]],
                colWidths=[112],
            )
            inner.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            cells.append(inner)
        outer = Table([cells], colWidths=[125] * 4)
        outer.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(outer)
        flow.append(Spacer(1, 8))

    # Legend
    legend = Table([[
        " AL ", "Annual Leave", " T ", "Training", "  ", "Public Holiday",
    ]], colWidths=[16, 60, 16, 60, 16, 70], rowHeights=[12])
    legend.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica-Bold", 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (0, 0), LEAVE_FILL["AL"]),
        ("TEXTCOLOR", (0, 0), (0, 0), colors.white),
        ("BACKGROUND", (2, 0), (2, 0), LEAVE_FILL["TRN"]),
        ("TEXTCOLOR", (2, 0), (2, 0), colors.white),
        ("BACKGROUND", (4, 0), (4, 0), HOL_FILL),
        ("BOX", (0, 0), (0, 0), 0.4, GRID_LINE),
        ("BOX", (2, 0), (2, 0), 0.4, GRID_LINE),
        ("BOX", (4, 0), (4, 0), 0.4, GRID_LINE),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    flow.append(legend)

    flow.append(Spacer(1, 6))
    flow.append(Paragraph(
        f"Generated {datetime.utcnow().strftime('%d %b %Y %H:%M UTC')} · {home_name} Care Home Rota Builder",
        foot_style,
    ))

    buf = BytesIO()
    margin = 12 * mm
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin,
        title=f"{home_name} Annual Holiday Sheet {year}",
    )
    doc.build(flow)
    return buf.getvalue()
