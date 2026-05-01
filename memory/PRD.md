# Grizedale Rota Builder — PRD

## Original problem statement
Build a rota builder web app for Grizedale (UK care home). Tech: FastAPI + React + MongoDB.

## User personas
- **Manager (J.C.)** — produces & signs off the 4-week rota.
- **Deputy (L.M.)** — reviews, edits, covers admin.
- **Care staff** — submit requests via anonymous link; read shifts.

## Core requirements (static)
- 4-week rota window (28 days, Mon→Sun), 8 staff, 7 service users.
- Shift types: D, D*, N, *, OFF, AL, TRN.
- Daily cover: 2D or D+D* on day side; D*+N or *+N on night.
- Per-shift med-competent + first-aider required.
- No-male-pair-alone, capability flags, N→D and D*→D* forbidden, locked cells preserved.
- Manager (J.C.) hard rule: no working shifts unless explicitly locked.
- Contracted-hours min: ≥ target − leave/training − 2h.
- Non-flexi cap: ≤ target + 8h (hard, mode-toggleable in /rules).
- Overtime preference: D.A. flexi rewarded for hours above target up to 48h/week cap.
- Prefer D*+N over *+N for night cover.

## What's been implemented
- **2026-04-30 — Phase 0**: CP-SAT solver, 3 endpoints, test_runner.
- **2026-04-30 — Phase 1**: JWT auth, MongoDB persistence, full CRUD, Rules/Settings/Admins UI, Paper/Modern theme.
- **2026-04-30 — Phase 2**:
  - **Solver**: Phase 2 fixes — J.R. nights-only (`can_do_sleepover=false`), C.E. permanent FA, non_flexi_overage hard cap target+8, prefer_dstar_over_star (weight 200) → result is **all D*+N nights, zero `*` shifts** in the optimal solution; overtime_prefer_flexi reward+penalty split capped at 48h/week.
  - **Backend**: rota_validator.py (shared rule_definitions); endpoints — `/api/rotas` CRUD + `/copy-from-previous` + `/cell` PATCH + `/validate`; `/api/leave` filter/bulk; `/api/requests` + bulk + accept-creates-leave-OFF_REQ; `/api/request-tokens`; `/api/public/request-link/{token}` (no auth) + submit.
  - **DB seeder**: idempotent seed + migrations for C.E. FA, J.R. sleepover, new rule entries, weight bumps.
  - **Frontend**: 4 new routes — `/rotas`, `/rotas/:id` (4-week grid editor), `/holidays` (year+month), `/requests` (tabs + bulk + manage staff links), public `/r/:token`.
  - **Grid editor (Paper)** matches the original photo: italic blue centered title, two-row peach header (M/T/W/T/F/S/S + dates 20→17), peach left identity column (role + initials + hours), white body cells with **Caveat handwriting font** for D/D*/N letters, full-yellow `*`, full-pink AL, full-red TRN, OFF=blank, on-call blue corner chip, lavender flag on first-Friday med-cycle Friday, blue/grey/red dots on date row for holiday/pay-cut-off/pending-request markers, thick black week dividers, horizontal legend strip below the grid.
  - **Click-cycle** (blank→D→D*→N→\*→OFF→AL→TRN→blank), **right-click popover** with shift picker + Lock toggle + Mark-on-call switch (L.M./J.C./L.D. only) + Reason input, **real-time validator** (red 2px ring on hard violations).
  - **Cell PATCH performance** ~50–200 ms; full validate <300 ms.
  - **Modern theme** stays distinct (slate/teal/Inter, no peach, no handwriting font, plain headers).
- **2026-04-30 — Phase 3 (Generate Rota)**:
  - **Backend**: `POST /api/rotas/{id}/generate` runs CP-SAT on top of an existing draft, preserving locked cells + AL/TRN, accepting non-OFF requests as soft preferences, returns full validation_report. Over-constrained → HTTP 422 with blocking_constraints. ~500ms wall.
  - **Solver**: overtime_prefer_flexi rule auto-detects flexi staff by role match (default "Flexi") with optional override list; legacy `preferred_staff_initials` kept for backward compat. Verified: D.A. (+70h) and T.D. (+56h) both absorb overtime under the new rule.
  - **Frontend**: Dashboard "Generate Rota" dialog → pick draft / new date → navigate to /rotas/:id?generate=1 → editor auto-runs solver with success toast. RotaEditor top-bar "Generate Rota" button with AlertDialog confirmation. Blockers modal on 422 failure.
  - **Rules.jsx**: new `OvertimeParams` component — Auto-detect-by-role Select + Weekly-cap input + "Currently rewarding overtime to:" badges + override-staff Checkbox grid (8 staff × roles).
  - **Paper theme cells** (2026-05-01 — photo-accurate re-skin): D=green `#3F8C4D` (white text), D*=yellow `#F5D04A` (slate), N=white (slate, thin border), *=bright yellow `#FFE066`, AL=pink `#C9377C` (white text), TRN=red `#D33B3B` (cell shows "T" not "TRN", white text). On-call chip `#3461A8`, med-cycle flag `#A8C5E0`, pay-cut-off marker `#C8CCD0`, legend swatches updated to match.
  - **Bug fix — day-cover affected_cells**: when a user changes D\* → \* the validator now flags the `*` cell (not just the surviving D cell) as `affected`, so the cell the user just edited red-borders and the violations counter increments. Same widening applied to night_cover. Regression test in `test_runner.py` (D\* → \* on first L.D. D\* date asserts L.D. ∈ affected_cells of the day_cover violation).
  - **2026-05-01 — New immovable hard rule `no_sleepover_before_leave`**: D\* or \* today forbids AL/TRN tomorrow (sleepover extends into the morning of the next day, so staff can't start leave/training straight after). Encoded in solver as CP-SAT constraint + in validator with affected_cells flagging both the sleepover cell and the leave cell. Seeded in rules_config as immovable. Regression test in test_runner.py: locking D.A. on D\* Tue + AL Wed → solver correctly returns INFEASIBLE; validator correctly emits `no_sleepover_before_leave` hard violation.
  - **2026-05-01 — Senior weekend cover + per-week hours + flexi redistribution fix + min_sleepover rule**:
    - **`senior_weekend_cover` (hard, immovable)**: every Sat & Sun must have L.M. or L.D. on D/D\*. Soft rotation nudge honours `settings.senior_weekend_rotation` (week 1&3=L.M., week 2&4=L.D. by default). Automatic fallback: if the assigned senior is on AL/TRN, the OTHER senior steps in.
    - **`avoid_pair_seniors` (soft, weight 40)**: penalty per day L.M. and L.D. both on D/D\*. Solver result: 0/28 days paired in default seed — perfect split.
    - **`min_sleepover_per_week_for_seniors` (soft, weight 30)**: each of {L.M., L.D., T.D.} must have ≥1 D\* per week (configurable list + count). Solver per-week BoolVar penalty (skips weeks where staff has ≥5 AL/TRN days). Validator emits soft/hard violation per missing week.
    - **Contracted hours minimum — PER WEEK (not rota-aggregate)**: each week individually must hit target_weekly_hours − 12\*AL − 8\*TRN − 2. Same for non_flexi +8h cap.
    - **`non_flexi_overage` default flipped to soft (weight 50)**: previously `hard` caused infeasibility when one Flexi had multi-day AL. DB migration auto-flips existing settings.
    - **Flexi overtime reward — PER WEEK**: over_rewardable / over_above_cap split computed each week, so when one flexi has AL that week the OTHER flexi gets loaded up THAT week instead of the slack being spread across 4 weeks.
    - **Flexi bug fix verified end-to-end via HTTP**: with D.A. on AL all week 2, T.D. jumps from 42h baseline to 50h in week 2 (and C.E. bumps to 52h), absorbing D.A.'s slack — solver_status OPTIMAL, 0 hard violations.
    - **Settings UI** — new "Weekend Senior Rotation" section with 4 dropdowns (week 1-4, pick L.M. or L.D.).
    - **Rules UI** — both `senior_weekend_cover` (immovable) and `avoid_pair_seniors` listed; `min_sleepover_per_week_for_seniors` has new `MinSleepoverParams` editor (multi-select staff Checkbox grid + min-per-week number input). Params now visible in BOTH Soft and Hard mode (was previously soft-only, hiding the staff list when manager toggled to hard).

## Open items / not yet implemented
- "Generate Rota" button in Dashboard still disabled (Phase 3 will wire it up + what-if mode).
- PDF / Excel exports (Phase 4).
- Forgot-password flow.
- Multi-rota visualisation / comparison.

## Prioritised backlog
- **P0 — Phase 3**: wire "Generate Rota" in editor + Dashboard (calls /api/solver/generate, applies result to the active rota, surfaces violations).
- **P0 — Phase 3**: what-if mode (toggle staff to AL/sick, re-solve in place).
- **P1 — Phase 4**: PDF + Excel exports.
- **P1**: Soft-rule satisfaction reporting in validator output (currently focuses on hard rules).
- **P2**: Forgot-password + email notifications via Resend.
- **P2**: Service-user-level scheduling (1:1 staff-to-resident allocation).

## Next tasks
1. Phase 3: Generate Rota button + what-if mode.
2. Phase 4: exports.
