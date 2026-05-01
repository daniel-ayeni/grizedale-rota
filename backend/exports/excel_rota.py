"""Rota Excel renderer — openpyxl-based two-sheet workbook.

Sheet 1 ("Rota"): tabular layout. Rows = staff, columns = 28 days
with a 2-row header (date + day-letter). Cells are filled with a colour
matching the on-screen Paper theme. First column + first 2 rows are
frozen so the header & identity column stay visible while scrolling.

Sheet 2 ("Summary"): per-staff rollup of total D, D*, N, *, AL, TRN,
total hours, target hours, variance.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# Paper-theme cell colours, ARGB.
SHIFT_FILL = {
    "D":   "FF5A8A4A",
    "D*":  "FFE8C547",
    "N":   "FFFFFFFF",
    "*":   "FFF4D03F",
    "AL":  "FFC2185B",
    "TRN": "FFB71C1C",
    "OFF": "FFF4ECE0",
    "":    "FFFFFFFF",
}
SHIFT_TEXT = {
    "D":   "FFFFFFFF",
    "D*":  "FF1A1A1A",
    "N":   "FF1A1A1A",
    "*":   "FF1A1A1A",
    "AL":  "FFFFFFFF",
    "TRN": "FFFFFFFF",
    "OFF": "FF777777",
    "":    "FF1A1A1A",
}
SHIFT_HOURS = {"D": 12, "D*": 14, "N": 12, "*": 0, "OFF": 0, "AL": 0, "TRN": 0, "": 0}
DOW_LETTERS = ["M", "T", "W", "T", "F", "S", "S"]
PEACH_FILL = PatternFill(start_color="FFF4B68A", end_color="FFF4B68A", fill_type="solid")
PEACH_DARK = PatternFill(start_color="FFE89A66", end_color="FFE89A66", fill_type="solid")
IDENT_FILL = PatternFill(start_color="FFF8E5D2", end_color="FFF8E5D2", fill_type="solid")
SUMMARY_HEADER = PatternFill(start_color="FFE89A66", end_color="FFE89A66", fill_type="solid")

THIN = Side(style="thin", color="FF1A1A1A")
THICK = Side(style="medium", color="FF1A1A1A")


def _parse(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def render_rota_xlsx(rota: dict, staff: list[dict], home_name: str = "Grizedale") -> bytes:
    start = _parse(rota["start_date"])
    weeks = int(rota.get("weeks", 4))
    days: list[date] = [start + timedelta(days=i) for i in range(weeks * 7)]

    asg = {(a["date"], a["staff_initials"]): a for a in (rota.get("assignments") or [])}

    wb = Workbook()
    ws = wb.active
    ws.title = "Rota"

    # ── Title ─────────────────────────────────────────────────────
    ws.cell(row=1, column=1, value=(
        f"{home_name.upper()} MONTHLY {start.strftime('%d %b %Y')}"
        f" – {days[-1].strftime('%d %b %Y')} ROTA"
    ))
    title_cell = ws.cell(row=1, column=1)
    title_cell.font = Font(name="Times New Roman", size=14, bold=True, italic=True, color="FF1A3A8C")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=1 + len(days))
    ws.row_dimensions[1].height = 24

    # ── Header rows (rows 2 and 3) ────────────────────────────────
    # Row 2 = day letters; row 3 = date numbers
    ws.cell(row=2, column=1, value="STAFF").fill = PEACH_DARK
    ws.cell(row=3, column=1, value="").fill = PEACH_DARK
    for di, d in enumerate(days):
        col = di + 2
        is_we = d.weekday() >= 5
        c1 = ws.cell(row=2, column=col, value=DOW_LETTERS[d.weekday()])
        c2 = ws.cell(row=3, column=col, value=d.day)
        for c in (c1, c2):
            c.fill = PEACH_DARK if is_we else PEACH_FILL
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.font = Font(bold=True, size=10, color="FF1A1A1A")
            c.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    # Style identity header
    for r in (2, 3):
        c = ws.cell(row=r, column=1)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.font = Font(bold=True, size=10)
        c.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

    # ── Body rows (one row per staff, starting at row 4) ──────────
    for si, s in enumerate(staff):
        row = si + 4
        ident = ws.cell(row=row, column=1, value=(
            f"{s.get('role', '')} · {s['initials']} ({s.get('target_weekly_hours', '')}h)"
        ))
        ident.fill = IDENT_FILL
        ident.font = Font(bold=True, size=10)
        ident.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ident.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
        for di, d in enumerate(days):
            col = di + 2
            cell_doc = asg.get((d.isoformat(), s["initials"]), {})
            sh = cell_doc.get("shift", "")
            label = "T" if sh == "TRN" else sh
            cell = ws.cell(row=row, column=col, value=label or None)
            cell.fill = PatternFill(
                start_color=SHIFT_FILL.get(sh, "FFFFFFFF"),
                end_color=SHIFT_FILL.get(sh, "FFFFFFFF"),
                fill_type="solid",
            )
            cell.font = Font(bold=True, size=11, color=SHIFT_TEXT.get(sh, "FF1A1A1A"))
            cell.alignment = Alignment(horizontal="center", vertical="center")
            # Week-divider thicker right border at end of each week.
            right = THICK if (di + 1) % 7 == 0 and di < len(days) - 1 else THIN
            cell.border = Border(left=THIN, right=right, top=THIN, bottom=THIN)

    # ── Column widths + freeze panes ──────────────────────────────
    ws.column_dimensions["A"].width = 28
    for di in range(len(days)):
        ws.column_dimensions[get_column_letter(di + 2)].width = 4.5
    # Freeze first column + first 3 rows (title + day-letter + date)
    ws.freeze_panes = "B4"

    # ── Sheet 2: Summary ──────────────────────────────────────────
    ws2 = wb.create_sheet("Summary")
    headers = [
        "Initials", "Role", "Target hrs/wk", "Total D", "Total D*", "Total N", "Total *",
        "Total AL", "Total TRN", "Total hours (4w)", "Target hours (4w)", "Variance",
    ]
    for ci, h in enumerate(headers):
        c = ws2.cell(row=1, column=ci + 1, value=h)
        c.fill = SUMMARY_HEADER
        c.font = Font(bold=True, size=10)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    for si, s in enumerate(staff):
        row = si + 2
        cnt = {"D": 0, "D*": 0, "N": 0, "*": 0, "AL": 0, "TRN": 0}
        total_hours = 0
        for d in days:
            sh = asg.get((d.isoformat(), s["initials"]), {}).get("shift", "")
            if sh in cnt:
                cnt[sh] += 1
            total_hours += SHIFT_HOURS.get(sh, 0)
        target_4w = (s.get("target_weekly_hours") or 0) * weeks
        variance = total_hours - target_4w
        values = [
            s["initials"], s.get("role", ""), s.get("target_weekly_hours", ""),
            cnt["D"], cnt["D*"], cnt["N"], cnt["*"],
            cnt["AL"], cnt["TRN"], total_hours, target_4w, variance,
        ]
        for ci, v in enumerate(values):
            c = ws2.cell(row=row, column=ci + 1, value=v)
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
            if ci == 11 and isinstance(v, (int, float)) and v != 0:
                # Highlight non-zero variance: red if over, amber if under.
                fill_col = "FFFEE2E2" if v > 0 else "FFFFEDD5"
                c.fill = PatternFill(start_color=fill_col, end_color=fill_col, fill_type="solid")
                c.font = Font(bold=True, size=10)
    for ci, _ in enumerate(headers):
        ws2.column_dimensions[get_column_letter(ci + 1)].width = 15
    ws2.freeze_panes = "B2"

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
