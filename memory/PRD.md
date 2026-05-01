# Grizedale Rota Builder — PRD

## Original problem
A UK care home (Grizedale) runs a 4-week rota for 8 staff covering 7 service users.
Currently done by hand on paper. Stacked, complex rules. We're building a constraint-
solver-backed web app (FastAPI + React + Mongo) that produces valid rotas.

## Personas
- **Manager (J.C.)** — primary user; logs in, edits the grid, locks cells, configures
  rules, generates rotas, reviews violations, publishes to staff.
- **Staff (J.R., L.M., L.D., D.A., T.D., C.E., A.A.)** — view-only via published
  rota / public request token (Phase 2).

## Tech stack
- Backend: FastAPI + Motor + OR-Tools CP-SAT
- Frontend: React (CRA) + TailwindCSS + shadcn/ui + lucide-react
- DB: MongoDB
- Auth: JWT (bcrypt password hashing)

## What's been implemented (latest first)

### 2026-05-01 — Consolidated batch (this session)
- **Phase 4 — Exports**:
  - `GET /api/rotas/{id}/export.pdf` — A3 landscape PDF rendered with
    ReportLab, mirrors the Paper-theme grid (italic blue title, peach
    headers, coloured shift cells, week dividers, locked-cell red
    borders, legend strip, footer with status + timestamp).
  - `GET /api/rotas/{id}/export.xlsx` — two-sheet workbook (openpyxl):
    "Rota" with coloured cells + frozen panes, "Summary" with per-staff
    totals (D, D*, N, *, AL, TRN, total hours, target, variance).
  - `GET /api/holidays/export.pdf?year=YYYY` — A4 portrait yearly grid
    (12 mini-month tables, AL/TRN coloured, public-holiday band,
    legend, footer).
  - Frontend buttons added to RotaEditor toolbar (PDF + Excel) and
    Holidays page header (Export PDF). Auth-aware blob download.
- **Phase 3b — What-If sandbox**:
  - `POST /api/rotas/{id}/whatif` — read-only solve over current rota +
    proposed shift edits + leave overrides. No DB write.
  - `POST /api/rotas/{id}/apply-whatif` — persists the proposed state
    as the new rota (and any leave overrides as fresh leave rows).
  - Frontend: "What-If OFF/ON" toggle in toolbar, teal banner with
    Re-solve / Apply / Discard actions, amber-dot diff indicator on
    every cell that differs from the saved state. Edits while sandbox
    is active route to local state, never to the API.
- **Week-lock UX polish (earlier in session)**: dedicated 3rd header
  row above day-letters with prominent pill-button chips per week;
  Tooltip shows the week's date range; toggle behavior; Escape clears
  selection; cells in active selection toggle out of the selection
  on click (curate-by-click); bulk toolbar pinned sticky-bottom.
- **AL exemption across all per-week / per-day rules**:
  `weekday_weekend_split`, `senior_weekend_cover` (hard), `senior_monday_cover`,
  `min_sleepover_per_week_for_seniors` (5→3 threshold + scaling),
  `pair_companion_on_day` all now skip rules when staff are forced AL/TRN.
- **Pair companion on day** soft rule (`pair_companion_on_day`): default `C.E.` on
  Wed must pair with `L.M.`/`L.D.`/`D.A.` on D/D*. Configurable in /rules.
- **Multi-cell selection / week-lock UX** on rota grid: shift+drag or shift+click
  to multi-select; "🔒W{n}" chip above each week selects the entire week × all
  staff. Floating bulk-action toolbar (Lock / Unlock / Clear) with 2-step confirm.
- **Bulk PATCH endpoint** `PATCH /api/rotas/{id}/cells` — atomic multi-update
  with single validation pass. Skips locked cells unless `force=true`.
- **Cell click cycle reorder**: blank → D → D* → N → * → blank only. AL/TRN
  removed from click cycle (only available via right-click popover, in their
  own "Leave" group).
- **Popover groupings**: Working / Off / Leave so AL is never the first option.
- **Paper theme font swap**: `Caveat` → `Patrick Hand` for shift cell letters
  (clean handwriting, more legible). Title keeps Lora italic 700; column
  headers Inter semibold; body Inter.
- **Row delete confirms** on multi-row rule editors: trash icon → "Confirm
  delete?" pill with 3-second arm window. Used on `max_sleepover_per_week`,
  `weekday_weekend_split`, `pair_companion_on_day`.
- **Reset to defaults** button at top of /rules → `POST /api/rules/reset`.
- **Bug fix — PREF dropdown**: `StaffIn` and `StaffPatch` Pydantic models were
  missing `shift_preference` and `accepts_overtime` fields. Pydantic silently
  stripped them, causing `update` dict to be empty → 400 "No fields provided".
  Fixed.
- **Leave persistence audit + logging**: confirmed nothing wipes `leave`. Added
  `LEAVE_INSERT/UPDATE/DELETE` INFO logs with caller email + timestamp on every
  mutation for forensic traceability.

### Earlier this session
- D.A. cap, min D* per senior, accepts_overtime, shift_preference,
  validation panel, Monday cover, *→N avoid, *→D avoid (with L.M./L.D.
  override), avoid_star_for_staff, dstar_count_per_week (L.M./L.D. min 2,
  T.D. exactly 1), fair_star_distribution, J.R. 24h target, J.R. weekday/
  weekend split.

### Phase 0–3
- OR-Tools CP-SAT solver, JWT auth, Staff/Holidays/Rules/Settings CRUD,
  4-week rota grid, Generate Rota, Validation Issues panel, paper theme
  exact-hex match, public request tokens.

## Backlog
### P0
- (none)

### P1
- **Phase 3b**: "What-If" mode (toggle staff to AL on the grid and re-solve
  in place without committing).
- Persist last-used cell shift per staff so popover defaults to that, not D
  (currently always D as fallback).

### P2
- **Phase 4**: PDF / Excel rota exports.
- Mobile rota viewer for staff.
- Notification flow when rota is published.

## Test artefacts
- `/app/backend/solver/test_runner.py` — 21+ regression blocks covering every
  hard + soft rule. Re-run after any solver/validator change.
- `/app/test_reports/` — testing-agent reports.

## Credentials
See `/app/memory/test_credentials.md`.
