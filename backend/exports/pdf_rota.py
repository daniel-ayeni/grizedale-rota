"""Rota PDF renderer — ReportLab-based.

Produces an A3-landscape PDF that mirrors the on-screen Paper-theme
grid: italic blue title, peach orange headers, coloured shift cells,
a footer with generation metadata, and a horizontal legend strip.

Returns the PDF as raw bytes so the FastAPI endpoint can stream it.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether,
)

# ── Paper-theme colour map (matches index.css cells exactly) ────────
SHIFT_FILL = {
    "D":   colors.HexColor("#5A8A4A"),  # solid green
    "D*":  colors.HexColor("#E8C547"),  # mustard yellow
    "N":   colors.white,
    "*":   colors.HexColor("#F4D03F"),  # bright yellow
    "AL":  colors.HexColor("#C2185B"),  # pink/magenta
    "TRN": colors.HexColor("#B71C1C"),  # red
    "OFF": colors.HexColor("#F4ECE0"),  # cream off
    "":    colors.white,
}
SHIFT_TEXT = {
    "D": colors.white, "D*": colors.HexColor("#1a1a1a"),
    "N": colors.HexColor("#1a1a1a"),
    "*": colors.HexColor("#1a1a1a"),
    "AL": colors.white, "TRN": colors.white,
    "OFF": colors.HexColor("#777"), "": colors.white,
}
# Display label override for AL/TRN to keep cells compact.
SHIFT_LABEL = {"D": "D", "D*": "D*", "N": "N", "*": "*", "OFF": "", "": "", "AL": "AL", "TRN": "T"}

DOW_LETTERS = ["M", "T", "W", "T", "F", "S", "S"]
DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PEACH = colors.HexColor("#F4B68A")
PEACH_DARK = colors.HexColor("#E89A66")
WEEK_DIVIDER = colors.HexColor("#1a1a1a")
TITLE_BLUE = colors.HexColor("#1a3a8c")
GRID_LINE = colors.HexColor("#1a1a1a")


def _parse(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def render_rota_pdf(
    rota: dict,
    staff: list[dict],
    home_name: str = "Grizedale",
) -> bytes:
    """Render a 4-week (or N-week) rota as a single-page A3 landscape PDF.

    `rota` is the persisted rota document with fields {start_date, weeks,
    assignments[], on_call[], status, title}. `staff` is the list of staff
    docs currently active.
    """
    start = _parse(rota["start_date"])
    weeks = int(rota.get("weeks", 4))
    days: list[date] = [start + timedelta(days=i) for i in range(weeks * 7)]
    end = days[-1]

    # Build an O(1) lookup of (date_str, initials) -> shift
    asg = {(a["date"], a["staff_initials"]): a for a in (rota.get("assignments") or [])}
    on_call_by_date = {oc["date"]: oc.get("staff_initials") for oc in (rota.get("on_call") or [])}

    # ── Title row ──────────────────────────────────────────────────
    title_style = ParagraphStyle(
        "rota-title",
        fontName="Times-BoldItalic",
        fontSize=16,
        textColor=TITLE_BLUE,
        alignment=1,  # center
        spaceAfter=4,
    )
    title_text = (
        f"{home_name.upper()} MONTHLY {start.strftime('%-d %b %Y')}"
        f" ----- {end.strftime('%-d %b %Y')} ROTA"
    )

    # Build table data: 3 header rows + N staff rows.
    # Row 1: corner "WEEK" + 4 week-band headers (each spans 7 columns)
    # Row 2: corner spacer + 28 day-letter cells
    # Row 3: corner spacer + 28 date-number cells
    # Body : (identity cell) + 28 shift cells per staff
    # Row 1 — week bands. We'll merge the 7 cells visually with SPAN.
    row_week = ["WEEK"]
    for w in range(weeks):
        row_week.extend([f"WEEK {w + 1}"] + [""] * 6)
    # Row 2 — day letter
    row_dow = [""] + [DOW_LETTERS[d.weekday()] for d in days]
    # Row 3 — date number
    row_date = [""] + [str(d.day) for d in days]

    body_rows: list[list[str]] = []
    for s in staff:
        ident = f"{(s.get('role') or '').upper()}\n{s['initials']}  {s.get('target_weekly_hours', '')}h"
        row = [ident]
        for d in days:
            cell = asg.get((d.isoformat(), s["initials"]), {})
            sh = cell.get("shift", "")
            label = SHIFT_LABEL.get(sh, sh)
            on_call = on_call_by_date.get(d.isoformat()) == s["initials"]
            if on_call and label:
                label = f"{label}\n[oc]"
            elif on_call and not label:
                label = "oc"
            row.append(label)
        body_rows.append(row)

    table_data = [row_week, row_dow, row_date, *body_rows]

    # Column widths: identity column wider, day columns equal share.
    page_w, _page_h = landscape(A3)
    margin = 12 * mm
    avail_w = page_w - 2 * margin
    ident_w = 95
    day_w = (avail_w - ident_w) / len(days)
    col_widths = [ident_w] + [day_w] * len(days)

    # Row heights — keep grid compact so the whole rota fits on one page.
    row_heights = [12, 12, 12] + [22] * len(staff)

    table = Table(table_data, colWidths=col_widths, rowHeights=row_heights, repeatRows=3)

    style = TableStyle([
        # Outer border + grid lines
        ("GRID", (0, 0), (-1, -1), 0.5, GRID_LINE),
        ("BOX",  (0, 0), (-1, -1), 1.2, GRID_LINE),
        # Header row 1 (week bands)
        ("BACKGROUND", (0, 0), (-1, 0), PEACH_DARK),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.HexColor("#1a1a1a")),
        ("FONT",       (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("ALIGN",      (0, 0), (-1, 0), "CENTER"),
        ("VALIGN",     (0, 0), (-1, 0), "MIDDLE"),
        # Header row 2 (day letters)
        ("BACKGROUND", (0, 1), (-1, 1), PEACH),
        ("FONT",       (0, 1), (-1, 1), "Helvetica-Bold", 9),
        ("ALIGN",      (0, 1), (-1, 1), "CENTER"),
        ("VALIGN",     (0, 1), (-1, 1), "MIDDLE"),
        # Header row 3 (dates)
        ("BACKGROUND", (0, 2), (-1, 2), PEACH),
        ("FONT",       (0, 2), (-1, 2), "Helvetica", 8),
        ("ALIGN",      (0, 2), (-1, 2), "CENTER"),
        ("VALIGN",     (0, 2), (-1, 2), "MIDDLE"),
        # Identity column styling
        ("BACKGROUND", (0, 3), (0, -1), colors.HexColor("#F8E5D2")),
        ("FONT",       (0, 3), (0, -1), "Helvetica-Bold", 7),
        ("ALIGN",      (0, 3), (0, -1), "LEFT"),
        ("VALIGN",     (0, 3), (0, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 3), (0, -1), 6),
        # Default cell styling for body
        ("FONT",  (1, 3), (-1, -1), "Helvetica-Bold", 9),
        ("ALIGN", (1, 3), (-1, -1), "CENTER"),
        ("VALIGN", (1, 3), (-1, -1), "MIDDLE"),
    ])

    # Merge week-band cells (each spans 7 day columns)
    for w in range(weeks):
        c0 = 1 + w * 7
        c1 = c0 + 6
        style.add("SPAN", (c0, 0), (c1, 0))

    # Weekend tint on Sat/Sun headers + body cells
    for di, d in enumerate(days):
        col = di + 1
        if d.weekday() >= 5:  # Sat/Sun
            style.add("BACKGROUND", (col, 1), (col, 2), PEACH_DARK)
        # Week divider (3px right border at end of each week except last)
        if (di + 1) % 7 == 0 and di < len(days) - 1:
            style.add("LINEAFTER", (col, 0), (col, -1), 1.5, WEEK_DIVIDER)

    # Per-cell shift colour fill + text colour (body only)
    for row_i, s in enumerate(staff):
        body_row = row_i + 3  # offset by 3 header rows
        for di, d in enumerate(days):
            col = di + 1
            cell = asg.get((d.isoformat(), s["initials"]), {})
            sh = cell.get("shift", "")
            fill = SHIFT_FILL.get(sh, colors.white)
            txt = SHIFT_TEXT.get(sh, colors.HexColor("#1a1a1a"))
            style.add("BACKGROUND", (col, body_row), (col, body_row), fill)
            style.add("TEXTCOLOR",  (col, body_row), (col, body_row), txt)
            if cell.get("locked"):
                # Locked cells get a thicker border to mimic the on-screen
                # "lock" indicator without showing the icon (which would
                # need an embedded image asset).
                style.add("BOX", (col, body_row), (col, body_row), 1.5, colors.HexColor("#B71C1C"))

    table.setStyle(style)

    # ── Legend strip ───────────────────────────────────────────────
    legend_items = [
        ("D", "Day shift",     SHIFT_FILL["D"],   colors.white),
        ("D*", "Day + Sleepover", SHIFT_FILL["D*"], colors.HexColor("#1a1a1a")),
        ("N", "Waking Night",  colors.white,      colors.HexColor("#1a1a1a")),
        ("*", "Sleep-in only", SHIFT_FILL["*"],   colors.HexColor("#1a1a1a")),
        ("AL", "Annual Leave",  SHIFT_FILL["AL"],  colors.white),
        ("T", "Training",       SHIFT_FILL["TRN"], colors.white),
    ]
    legend_row = []
    for sh, label, _bg, _fg in legend_items:
        legend_row.extend([sh, label])
    legend_table = Table(
        [legend_row],
        colWidths=[18, 70] * len(legend_items),
        rowHeights=[14],
    )
    leg_style = TableStyle([
        ("FONT",  (0, 0), (-1, -1), "Helvetica-Bold", 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",  (0, 0), (-1, -1), "CENTER"),
    ])
    for i, (sh, _label, bg, fg) in enumerate(legend_items):
        c = i * 2
        leg_style.add("BACKGROUND", (c, 0), (c, 0), bg)
        leg_style.add("TEXTCOLOR",  (c, 0), (c, 0), fg)
        leg_style.add("BOX",        (c, 0), (c, 0), 0.5, GRID_LINE)
        leg_style.add("ALIGN",      (c + 1, 0), (c + 1, 0), "LEFT")
        leg_style.add("LEFTPADDING", (c + 1, 0), (c + 1, 0), 4)
    legend_table.setStyle(leg_style)

    # ── Footer paragraph ───────────────────────────────────────────
    footer_style = ParagraphStyle(
        "footer", fontName="Helvetica", fontSize=7,
        textColor=colors.HexColor("#555"), alignment=0,
    )
    generated = datetime.utcnow().strftime("%d %b %Y %H:%M UTC")
    status = (rota.get("status") or "draft").upper()
    footer_text = (
        f"Generated {generated} &nbsp;·&nbsp; status: <b>{status}</b>"
        f" &nbsp;·&nbsp; {home_name} Care Home Rota Builder"
    )

    # ── Build the doc ──────────────────────────────────────────────
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A3),
        leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin,
        title=f"{home_name} Rota {start.isoformat()} - {end.isoformat()}",
    )
    flow: list[Any] = [
        Paragraph(title_text, title_style),
        Spacer(1, 4),
        table,
        Spacer(1, 6),
        legend_table,
        Spacer(1, 4),
        Paragraph(footer_text, footer_style),
    ]
    doc.build([KeepTogether(flow)])
    return buf.getvalue()
