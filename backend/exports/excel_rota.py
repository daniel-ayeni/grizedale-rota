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

# Shift cell colours, ARGB. D and N share solid green per user spec.
SHIFT_FILL = {
    "D":   "FF5A8A4A",
    "D*":  "FFE8C547",
    "N":   "FF5A8A4A",   # GREEN (matches D)
    "*":   "FFF4D03F",
    "AL":  "FFC2185B",
    "TRN": "FFB71C1C",
    "OFF": "FFF4ECE0",
    "":    "FFFFFFFF",
}
SHIFT_TEXT = {
    "D":   "FFFFFFFF",
    "D*":  "FF1A1A1A",
    "N":   "FFFFFFFF",   # green bg → white text
    "*":   "FF1A1A1A",
    "AL":  "FFFFFFFF",
    "TRN": "FFFFFFFF",
    "OFF": "FF777777",
    "":    "FF1A1A1A",
}
SHIFT_LABEL_OUT = {"D": "D", "D*": "D*", "N": "N", "*": "*", "AL": "AL", "TRN": "T", "OFF": "", "": ""}
SHIFT_HOURS = {"D": 12, "D*": 14, "N": 12, "*": 0, "OFF": 0, "AL": 0, "TRN": 0, "": 0}
DOW_LETTERS = ["M", "T", "W", "T", "F", "S", "S"]

# Theme palettes — only the chrome (headers, identity tint, title font)
# differs. Shift cell colours are shared.
THEMES = {
    "paper": {
        "header":     PatternFill(start_color="FFF4B68A", end_color="FFF4B68A", fill_type="solid"),
        "header_dark": PatternFill(start_color="FFE89A66", end_color="FFE89A66", fill_type="solid"),
        "ident":      PatternFill(start_color="FFF8E5D2", end_color="FFF8E5D2", fill_type="solid"),
        "title_font": Font(name="Times New Roman", size=14, bold=True, italic=True, color="FF1A3A8C"),
    },
    "modern": {
        "header":     PatternFill(start_color="FFE2E8F0", end_color="FFE2E8F0", fill_type="solid"),
        "header_dark": PatternFill(start_color="FFCBD5E1", end_color="FFCBD5E1", fill_type="solid"),
        "ident":      PatternFill(start_color="FFF8FAFC", end_color="FFF8FAFC", fill_type="solid"),
        "title_font": Font(name="Calibri", size=14, bold=True, color="FF0F172A"),
    },
}

PEACH_FILL = THEMES["paper"]["header"]      # legacy aliases used below
PEACH_DARK = THEMES["paper"]["header_dark"]
IDENT_FILL = THEMES["paper"]["ident"]
SUMMARY_HEADER = THEMES["paper"]["header_dark"]

THIN = Side(style="thin", color="FF1A1A1A")
THICK = Side(style="medium", color="FF1A1A1A")


def _parse(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def render_rota_xlsx(rota: dict, staff: list[dict], home_name: str = "Grizedale", theme: str = "paper") -> bytes:
    pal = THEMES.get(theme, THEMES["paper"])
    header_fill = pal["header"]
    header_dark = pal["header_dark"]
    ident_fill = pal["ident"]
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
    title_cell.font = pal["title_font"]
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=1 + len(days))
    ws.row_dimensions[1].height = 24

    # ── Header rows (rows 2 and 3) ────────────────────────────────
    # Row 2 = day letters; row 3 = date numbers
    ws.cell(row=2, column=1, value="STAFF").fill = header_dark
    ws.cell(row=3, column=1, value="").fill = header_dark
    for di, d in enumerate(days):
        col = di + 2
        is_we = d.weekday() >= 5
        c1 = ws.cell(row=2, column=col, value=DOW_LETTERS[d.weekday()])
        c2 = ws.cell(row=3, column=col, value=d.day)
        for c in (c1, c2):
            c.fill = header_dark if is_we else header_fill
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
    # Staff identity column — INITIALS ONLY per manager spec. Role and
    # hours are intentionally omitted to match the PDF and keep the grid
    # professional.
    for si, s in enumerate(staff):
        row = si + 4
        ident = ws.cell(row=row, column=1, value=s["initials"])
        ident.fill = ident_fill
        ident.font = Font(bold=True, size=12)
        ident.alignment = Alignment(horizontal="center", vertical="center")
        ident.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
        # Taller staff rows so the 8-staff grid fills A4 landscape
        # vertically without scaling.
        ws.row_dimensions[row].height = 56
        for di, d in enumerate(days):
            col = di + 2
            cell_doc = asg.get((d.isoformat(), s["initials"]), {})
            sh = cell_doc.get("shift", "")
            # Map OFF and blank to an empty cell so the export matches the
            # on-screen Paper-theme behaviour (no literal "OFF" text).
            label = SHIFT_LABEL_OUT.get(sh, sh)
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

    # ── Column widths — sized so the NATURAL width fills A4 landscape
    # without ANY scaling. A4 landscape usable width with 0.4" margins
    # = ~277 mm. Excel units → ~1.85 mm per unit → ~149 units fit.
    # 1×12 (ident) + 28×4.9 (day) = 12 + 137.2 ≈ 149 units → table
    # touches both edges naturally; fit-to-page becomes a no-op.
    ws.column_dimensions["A"].width = 12     # initials only
    for di in range(len(days)):
        ws.column_dimensions[get_column_letter(di + 2)].width = 4.9
    # Row heights — fill the A4 landscape vertically too. Usable height
    # ≈ 190 mm = 538 pt. Title 30 + 2 headers × 28 + N staff × 56
    # ≈ 30 + 56 + 8×56 = 534 pt → table fills the page top-to-bottom.
    ws.row_dimensions[1].height = 30          # title
    ws.row_dimensions[2].height = 28
    ws.row_dimensions[3].height = 28
    # Staff body rows are set per-row below; bump from 36 → 56 so the
    # 8-staff grid fills the A4 landscape page without Excel having to
    # shrink anything.
    # Freeze first column + first 3 rows (title + day-letter + date)
    ws.freeze_panes = "B4"

    # ── Page setup — A4 landscape, NO scaling (natural size fills) ─
    # Earlier attempts with fit-to-page made Excel shrink the table
    # into ~55% of the page. Fix: column + row sizes above already fill
    # A4 landscape natively, so we ENABLE fit-to-1-wide as a SAFETY
    # only (kicks in if a future rota has more days). fit-to-height=0
    # so vertical sizing stays natural; centered on page; bounded
    # print_area so empty cells outside the rota are never printed.
    from openpyxl.worksheet.page import PageMargins
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins = PageMargins(
        left=0.4, right=0.4, top=0.4, bottom=0.4,
        header=0.2, footer=0.2,
    )
    ws.print_options.horizontalCentered = True
    ws.print_options.verticalCentered = True
    last_col = get_column_letter(1 + len(days))         # 29 → "AC"
    last_row = 3 + len(staff)                            # 3 headers + N staff
    ws.print_area = f"A1:{last_col}{last_row}"
    ws.print_title_rows = "1:3"

    # ── Sheet 2: Summary ──────────────────────────────────────────
    ws2 = wb.create_sheet("Summary")
    headers = [
        "Initials", "Role", "Target hrs/wk", "Total D", "Total D*", "Total N", "Total *",
        "Total AL", "Total TRN", "Total hours (4w)", "Target hours (4w)", "Variance",
    ]
    for ci, h in enumerate(headers):
        c = ws2.cell(row=1, column=ci + 1, value=h)
        c.fill = header_dark
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

    # ── Summary sheet print setup (bounded) ───────────────────────
    # So that File → Print > Entire Workbook gives a clean Summary
    # sheet too, not empty trailing cells.
    ws2.page_setup.orientation = ws2.ORIENTATION_LANDSCAPE
    ws2.page_setup.paperSize = ws2.PAPERSIZE_A4
    ws2.page_setup.fitToWidth = 1
    ws2.page_setup.fitToHeight = 1
    ws2.sheet_properties.pageSetUpPr.fitToPage = True
    ws2.page_margins = PageMargins(
        left=0.4, right=0.4, top=0.5, bottom=0.5,
        header=0.2, footer=0.2,
    )
    ws2.print_options.horizontalCentered = True
    sum_last_col = get_column_letter(len(headers))           # → "L" (12 cols)
    sum_last_row = 1 + len(staff)                             # header + N rows
    ws2.print_area = f"A1:{sum_last_col}{sum_last_row}"
    ws2.print_title_rows = "1:1"

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
