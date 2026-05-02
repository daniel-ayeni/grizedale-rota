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

### 2026-05-02 (later) — Staff link UX overhaul
- **Slot check shape upgraded** (`/api/public/request-link/{t}/check`):
  returns `{slot_status: open|role_conflict|hard_limit, existing_leave:
  [{staff_initials, role, type}, ...], would_break_rules: [...]}` plus
  back-compat `slot_open + reason`. Surfaces ANY leave on the date so
  the public page can show an amber FYI chip when other staff (different
  role) are off — no longer reports "open" when in fact someone clashes.
- **Validity banner on /r/{token}**: "This link is valid until <Day, DD
  Month YYYY> · X days left" — turns amber when <3 days remain. Backed
  by existing `valid_until` field.
- **Modern/Paper theme toggle on the public page**: top-right header
  button, persists in `localStorage['grizedale_theme']` like the main
  app. Default Modern.
- **URL shortener swap (TinyURL → is.gd → da.gd → direct)**: removes
  the TinyURL "suspicious URL" preview interstitial. is.gd / da.gd both
  do clean 301 direct redirects. Token doc carries `short_url_provider`;
  Requests drawer renders "via <provider> · expanded: …".
- **3-state SlotBanner** on /r/{token}: red "Slot taken" with offending
  staff/role/reason · amber "FYI — others off this day" listing them ·
  green "Slot is open". Submit button stays enabled in every state —
  staff submit, manager decides.


### 2026-05-02 — De-hardcode solver, role-flag UI, override dialog
- **Solver fully de-hardcoded**: `rota_solver.py`, `rota_validator.py`, and
  `rule_definitions.py` contain ZERO staff-initial string literals. All
  "who's a senior/flexi/night/manager" lookups resolve via per-staff role
  flags (`is_manager`, `is_deputy`, `is_senior`, `is_flexi`, `is_night`).
  New helper `_derive_role_staff(staff_list, flag)`. Manager rule now
  fires on `is_admin_only OR is_manager`. Default rule params are empty
  templates; `default_rules_config(staff_list)` pre-populates role-derived
  initials at seed time. Grizedale seed JSON updated with flag values.
- **Role-flag chips on /staff**: color-coded inline chips (MGR red · DEP
  orange · SEN blue · FLX green · NGT purple) per staff row. Clicking a
  chip toggles `is_*` on the backend via PUT /api/staff/{id}. Staff sheet
  form also carries the chips so new staff start with correct roles.
- **Staff delete dialog with references**: new `StaffDeleteDialog`
  component fetches `/api/staff/{id}/references` and shows counts for
  rota assignments, leave, requests, active tokens, and a list of every
  rule that names the staff explicitly with its mode (SOFT/HARD). "I
  understand — delete and orphan references" ack checkbox required.
- **Override conflict dialog on /requests**: accepting a request that
  would break `max_one_per_role_on_al` opens `OverrideConflictDialog`.
  Manager must tick the ack checkbox AND type a reason; only then can
  they click "Accept with override". Bulk accept batches all clashing
  rows into a single override dialog. Non-clashing rows accept normally
  via `/api/requests/bulk`, which now returns `skipped_conflicts` when
  no override is supplied.
- **audit_log collection**: new backend collection capturing every
  override (`{actor_email, action:override_conflict, details, timestamp}`)
  plus `GET /api/audit-log` endpoint for manager review.
- **Backend endpoint additions**: PATCH `/api/requests/{id}` now returns
  409 when a conflict exists without override, 422 when override is
  requested without a reason, and 200 with audit-log row on full success.
  Bulk endpoint extended with `override_conflict`, `override_reason`,
  `skipped_conflicts` in the response.
- **Verification**: test_runner.py passes all 30 assertions. Dedicated
  pytest suite `test_phase_dehardcode.py` covers 10 cases — all pass.
  Grep for any of `"J.C.|"L.M.|"L.D.|"D.A.|"T.D.|"C.E.|"A.A.|"J.R.` in
  `rota_solver.py`, `rota_validator.py`, `rule_definitions.py` returns
  ZERO matches. Final status from testing subagent: backend 10/10,
  frontend 100% for Staff chip toggle, StaffDeleteDialog, Requests
  conflicts badge, OverrideConflictDialog, and audit trail end-to-end.


### 2026-05-01 — Consolidated batch (this session)
- **N cells GREEN per user spec**: Paper-theme online + PDF + Excel
  exports now render N cells with the same solid green (#5A8A4A) +
  white text as D cells. Modern theme online unchanged (clean palette).
- **Export theme picker**: clicking PDF / Excel / Holiday-PDF opens a
  small dialog "Which theme do you want the export to use?" with
  Paper (default) / Modern visual tiles. Selection passes
  `?theme=paper|modern` to the endpoint.
- **Locked-cell generate bug fix**: `/generate` now PRE-VALIDATES every
  locked cell against (a) staff capabilities and (b) existing leave on
  the same date — surfacing a clear, day-grouped 422 with the
  conflicting cells before even calling the solver. The solver call is
  also wrapped in try/except so any internal failure becomes a clean
  422 with a useful message instead of a 500. Frontend's blockers
  modal now triggers on ANY structured failure response (with `reason`,
  `success: false`, OR a populated `blocking_constraints` array) so
  the manager always sees the specific problem instead of a generic
  toast.
- **Export row order fix**: `display_order` field on every staff doc
  (J.C.=10 → J.R.=80) seeded from grizedale.json array index. PDF/Excel
  exports + `/api/staff` listing all sort by display_order. PDF + Excel
  rows now match the on-screen rota grid 1:1.
- **OFF blank in exports**: PDF and Excel both render OFF cells as
  empty (no literal "OFF" text) to match the on-screen Paper-theme
  behaviour.
- **What-If mode removed** from frontend per user feedback (didn't
  understand the use). Endpoints `/whatif` + `/apply-whatif` removed
  from server.py. State, banner, diff-dots, imports all gone.
- **Frozen staff column** with "Frozen / Unfrozen" toolbar toggle
  (default ON, persisted in localStorage). `position: sticky; left: 0`
  on the identity cells + corner cells, with subtle right-edge shadow
  when content scrolls behind.
- **Emergent watermark removed**: `<a id="emergent-badge">` block,
  `emergent-main.js` script and the `emergent.sh` description meta
  tag deleted from `frontend/public/index.html`. Page title now
  "Grizedale Care Home — Rota Builder".
- **Short request-token URL**: tokens are now 6-char base62 (e.g.
  `/r/vAYf67`) instead of 32-char UUIDs. Existing long tokens still
  resolve. `/requests` drawer shows the short path as a prominent
  clickable code chip with full URL beneath + "Copy link" button.
- **Default theme = Modern**: db_seeder bumps existing
  `theme_default: "paper"` settings doc to `"modern"` and ThemeContext
  defaults to "modern" for fresh visitors. localStorage preference
  still wins for returning users.
- **Delete rotas on /rotas**: trash-icon Delete button per row +
  "Select multiple" mode with bulk Delete. Confirmation dialog with
  count + warning. Published rotas can't be deleted (toast suggests
  unpublishing first).
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
