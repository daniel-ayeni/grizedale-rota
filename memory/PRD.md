# Grizedale Rota Builder — PRD

## Original problem statement
Build a rota builder web app for Grizedale (UK care home). Tech: FastAPI + React + MongoDB.
Phase 0 (this milestone): backend-only proof-of-concept of the OR-Tools CP-SAT
constraint solver. No frontend, no auth, no persistence yet.

## User personas
- **Manager (J.C.)** — produces the 4-week rota and signs it off.
- **Deputy (L.M.)** — reviews, edits, covers admin when needed.
- **Care staff (L.D., D.A., T.D., C.E., A.A., J.R.)** — read their assigned shifts.

## Core requirements (static)
- 4-week rota window (28 days)
- 8 staff, 7 service users
- Shift types: D, D*, N, *, OFF, AL, TRN
- Daily cover: 2 day staff (2D OR 1D+1D*) and 2 night staff (D*+N OR *+N)
- Per-shift med-competent + first-aider required
- No-male-pair-alone rule (when D.A./A.A. on shift, female required)
- Capability flags per staff (can_do_days/nights/sleepover)
- N→D forbidden, D*→D* forbidden, locked cells preserved
- Soft rules: hours target, manager-weekday-admin, preferred-off-days,
  avoid-pair, weekend fairness

## What's been implemented
- 2026-04-30 — Phase 0:
  - `backend/seed/grizedale.json` with 8 staff per agreed seed
  - `backend/solver/rota_solver.py` — full CP-SAT model with all hard
    rules + 5 soft-rule penalty terms
  - `backend/solver/test_runner.py` — loads seed, prints rota grid,
    asserts hard rules
  - `backend/server.py` endpoints:
    - `GET  /api/health`
    - `GET  /api/solver/seed`
    - `POST /api/solver/generate`
    - FastAPI docs at `/api/docs`
  - `ortools` added to `requirements.txt`
  - Verified: solver finds OPTIMAL solution in <100ms with the seed
  - Verified: over-constrained input returns `success:false` with a
    useful per-day blocking-constraint diagnosis

## Phase 0 known limitations / open items
- **J.R. ends up with 0h.** She is nights-only AND not med-competent AND
  not first-aider — with current seed flags only C.E. and A.A. can satisfy
  med+FA on a night, so J.R. is squeezed out. Needs input from user:
  should J.R. become med-competent or first-aider in the seed?
- **Sleepover hours.** D* counted as 14h, * counted as 0h. If real-world
  payroll counts sleepover differently, adjust SHIFT_HOURS map.
- **Weekend fairness** is approximated via per-staff target-weekend-work
  deviation rather than full pairwise variance.

## Prioritised backlog
- **P0 — Phase 1 frontend MVP**
  - Rota grid view (read-only) of solver output
  - Staff table (read from seed)
  - "Generate rota" button → POST /api/solver/generate → render grid
- **P1 — persistence**
  - Save rota / staff / leave / locked cells to MongoDB
  - Versioned rota history
- **P1 — staff CRUD UI**
- **P2 — auth** (manager-only access, deputy edit rights)
- **P2 — exports** (PDF / Excel)
- **P2 — soft-rule weight tuning UI** (sliders for hours / fairness etc.)

## Next tasks
1. Get user feedback on J.R. seed flags / sleepover hour accounting.
2. Phase 1 — design + build frontend MVP that consumes the solver API.
