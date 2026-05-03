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

# ── Theme colour palettes ─────────────────────────────────────────
# Paper = the original handwritten-rota look (peach headers, italic blue
# title, Patrick Hand handwriting font). Modern = clean slate/teal
# palette with sans-serif throughout. The shift colour map is shared
# (per user spec: D and N green, D* mustard, * bright yellow, AL pink,
# TRN red) but chrome / typography differ.
SHIFT_FILL = {
    "D":   colors.HexColor("#5A8A4A"),  # solid green
    "D*":  colors.HexColor("#E8C547"),  # mustard yellow
    "N":   colors.HexColor("#5A8A4A"),  # GREEN — matches D per user req
    "*":   colors.HexColor("#F4D03F"),  # bright yellow
    "AL":  colors.HexColor("#C2185B"),  # pink/magenta
    "TRN": colors.HexColor("#B71C1C"),  # red
    "OFF": colors.HexColor("#F4ECE0"),  # cream off
    "":    colors.white,
}
SHIFT_TEXT = {
    "D": colors.white,
    "D*": colors.HexColor("#1a1a1a"),
    "N": colors.white,                    # green bg → white text
    "*": colors.HexColor("#1a1a1a"),
    "AL": colors.white,
    "TRN": colors.white,
    "OFF": colors.HexColor("#777"),
    "": colors.white,
}
# Display label override. AL/TRN keep their letters; OFF and "" render
# as a fully blank cell to match the on-screen Paper-theme behaviour.
SHIFT_LABEL = {"D": "D", "D*": "D*", "N": "N", "*": "*", "OFF": "", "": "", "AL": "AL", "TRN": "T"}

DOW_LETTERS = ["M", "T", "W", "T", "F", "S", "S"]
DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Paper palette (default, original handwritten look)
PAPER_PEACH = colors.HexColor("#F4B68A")
PAPER_PEACH_DARK = colors.HexColor("#E89A66")
PAPER_TITLE = colors.HexColor("#1a3a8c")
PAPER_GRID = colors.HexColor("#1a1a1a")
PAPER_IDENT_BG = colors.HexColor("#F8E5D2")
PAPER_TITLE_FONT = "Times-BoldItalic"

# Modern palette — clean slate/teal, no peach
MODERN_HEADER = colors.HexColor("#E2E8F0")     # slate-200
MODERN_HEADER_DARK = colors.HexColor("#CBD5E1")  # slate-300
MODERN_TITLE = colors.HexColor("#0F172A")       # slate-900
MODERN_GRID = colors.HexColor("#94A3B8")        # slate-400
MODERN_IDENT_BG = colors.HexColor("#F8FAFC")    # slate-50
MODERN_TITLE_FONT = "Helvetica-Bold"


def _theme(theme: str) -> dict:
    if theme == "modern":
        return {
            "name": "modern",
            "peach": MODERN_HEADER,
            "peach_dark": MODERN_HEADER_DARK,
            "title": MODERN_TITLE,
            "grid": MODERN_GRID,
            "ident_bg": MODERN_IDENT_BG,
            "title_font": MODERN_TITLE_FONT,
            "title_size": 14,
            "body_font": "Helvetica-Bold",
        }
    return {
        "name": "paper",
        "peach": PAPER_PEACH,
        "peach_dark": PAPER_PEACH_DARK,
        "title": PAPER_TITLE,
        "grid": PAPER_GRID,
        "ident_bg": PAPER_IDENT_BG,
        "title_font": PAPER_TITLE_FONT,
        "title_size": 16,
        "body_font": "Helvetica-Bold",
    }


def _parse(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def render_rota_pdf(
    rota: dict,
    staff: list[dict],
    home_name: str = "Grizedale",
    theme: str = "paper",
) -> bytes:
    """Render an N-week rota as a single A3-landscape PDF.

    `theme` ∈ {"paper", "modern"} — picks the chrome palette (headers,
    title typography, identity column tint). The shift cell colours are
    shared across themes (D & N green, D* mustard, * bright yellow, AL
    pink, TRN red) per user spec.
    """
    pal = _theme(theme)
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
        fontName=pal["title_font"],
        fontSize=pal["title_size"],
        textColor=pal["title"],
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
        # Identity column — INITIALS ONLY per manager spec. Role + hours
        # are intentionally omitted: they're on the /staff page and were
        # cluttering the grid. Just the initials, centered.
        ident = s["initials"]
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

    # Column widths — sized to GUARANTEE the full 28-day grid fits a
    # single A3 landscape page. We deliberately leave 30pt headroom on
    # the right so ReportLab never auto-splits the table column-wise
    # under any rounding edge case (the user's previous regression
    # cut at day 20 because the table width just exceeded the page).
    page_w, page_h = landscape(A3)        # 1190 × 842 pt
    margin = 10 * mm                       # tighter than the 12mm default
    avail_w = page_w - 2 * margin          # ≈ 1133 pt
    avail_h = page_h - 2 * margin
    SAFETY_GUTTER = 30                     # right-edge breathing room
    ident_w = 50                           # narrower initials column
    day_w = (avail_w - ident_w - SAFETY_GUTTER) / len(days)
    col_widths = [ident_w] + [day_w] * len(days)

    # Row heights — SIZE THE TABLE TO FILL THE PAGE. The previous fixed
    # 22pt staff rows left the table at ~25% of the A3 landscape height
    # with huge white space (user called it "shrunken"). Instead budget
    # page height → header rows + title/legend/footer → split the rest
    # evenly across the staff rows. Yields ~50-60pt per staff row on
    # a typical 8-staff 4-week rota which prints at a comfortable size.
    header_h = 16                 # rows 1-3 combined → 3 × ~16pt
    # Reserve vertical space for title (~24pt), spacers (~14pt),
    # legend (~20pt), footer (~14pt) that flow before/after the table.
    CHROME_H = 24 + 14 + 20 + 14
    avail_table_h = max(avail_h - CHROME_H - (3 * header_h), 240)
    staff_row_h = max(28, min(62, int(avail_table_h / max(1, len(staff)))))
    row_heights = [header_h, header_h, header_h] + [staff_row_h] * len(staff)

    # `splitByRow=1, splitInRow=0` tell ReportLab: only ever split
    # vertically (between staff rows) and NEVER split inside a row /
    # mid-column. With our col-width math the table fits A3 landscape
    # in one page; this flag is the belt-and-braces guarantee against
    # any future width regression cropping the rota at week 3.
    table = Table(table_data, colWidths=col_widths, rowHeights=row_heights, repeatRows=3, splitByRow=1)

    style = TableStyle([
        # Outer border + grid lines
        ("GRID", (0, 0), (-1, -1), 0.5, pal["grid"]),
        ("BOX",  (0, 0), (-1, -1), 1.2, pal["grid"]),
        # Header row 1 (week bands)
        ("BACKGROUND", (0, 0), (-1, 0), pal["peach_dark"]),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.HexColor("#1a1a1a")),
        ("FONT",       (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("ALIGN",      (0, 0), (-1, 0), "CENTER"),
        ("VALIGN",     (0, 0), (-1, 0), "MIDDLE"),
        # Header row 2 (day letters)
        ("BACKGROUND", (0, 1), (-1, 1), pal["peach"]),
        ("FONT",       (0, 1), (-1, 1), "Helvetica-Bold", 10),
        ("ALIGN",      (0, 1), (-1, 1), "CENTER"),
        ("VALIGN",     (0, 1), (-1, 1), "MIDDLE"),
        # Header row 3 (dates)
        ("BACKGROUND", (0, 2), (-1, 2), pal["peach"]),
        ("FONT",       (0, 2), (-1, 2), "Helvetica", 9),
        ("ALIGN",      (0, 2), (-1, 2), "CENTER"),
        ("VALIGN",     (0, 2), (-1, 2), "MIDDLE"),
        # Identity column styling — initials only, centered + larger font.
        ("BACKGROUND", (0, 3), (0, -1), pal["ident_bg"]),
        ("FONT",       (0, 3), (0, -1), "Helvetica-Bold", 13),
        ("ALIGN",      (0, 3), (0, -1), "CENTER"),
        ("VALIGN",     (0, 3), (0, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 3), (0, -1), 2),
        ("RIGHTPADDING", (0, 3), (0, -1), 2),
        # Default cell styling for body — font sized up to match taller rows.
        ("FONT",  (1, 3), (-1, -1), pal["body_font"], 11),
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
            style.add("BACKGROUND", (col, 1), (col, 2), pal["peach_dark"])
        # Week divider (3px right border at end of each week except last)
        if (di + 1) % 7 == 0 and di < len(days) - 1:
            style.add("LINEAFTER", (col, 0), (col, -1), 1.5, pal["grid"])

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
        ("N", "Waking Night",  SHIFT_FILL["N"],   colors.white),
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
        leg_style.add("BOX",        (c, 0), (c, 0), 0.5, pal["grid"])
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
