# Grizedale Rota Builder — PRD

## Original problem statement
Build a rota builder web app for Grizedale (UK care home). Tech: FastAPI + React + MongoDB.
Phase 0: backend-only OR-Tools CP-SAT proof-of-concept.
Phase 1: foundation — auth, persistence, CRUD, solver corrections, theme system.
Phase 2 (next): interactive 4-week rota grid editor.
Phase 3: "Generate Rota" wired to UI + what-if mode.
Phase 4: PDF / Excel exports.

## User personas
- **Manager (J.C.)** — produces & signs off the 4-week rota.
- **Deputy (L.M.)** — reviews, edits, covers admin.
- **Care staff** — read their assigned shifts.

## Core requirements (static)
- 4-week rota window (28 days), 8 staff, 7 service users.
- Shift types: D, D*, N, *, OFF, AL, TRN.
- Daily cover: 2 day staff (2D OR 1D+1D*) and 2 night staff (D*+N OR *+N).
- Every shift: ≥1 med-competent + ≥1 first-aider.
- No-male-pair-alone rule (when D.A./A.A. on shift, female required).
- Capability flags per staff (can_do_days/nights/sleepover).
- N→D forbidden, D*→D* forbidden, locked cells preserved.
- Manager (J.C.) hard rule: never assigned a working shift unless explicitly locked.
- Contracted-hours hard rule: each staff hits target_weekly_hours×weeks − AL_days×12 − TRN_days×8 (−2h tolerance).
- Soft rules: D* preference for sleepover-capable, preferred-off-days, avoid-pairing, weekend fairness.

## What's been implemented
- **2026-04-30 — Phase 0**: CP-SAT solver, 3 endpoints, test_runner.
- **2026-04-30 — Phase 1**:
  - Solver corrections (manager hard, relaxed night-med, contracted-hours hard, D* preference, AL/TRN no-voluntary)
  - Explicit pairing assertion in test_runner.py: D.A. on D*/* ⇒ N must be C.E. or J.R.
  - JWT auth (HS256, 24h, Bearer + localStorage); bcrypt password hashing
  - Idempotent Mongo seed-on-boot (users, staff, service_users, rules_config, settings)
  - Full CRUD APIs: /api/staff, /api/service-users, /api/rules, /api/settings, /api/admins
  - /api/solver/generate now reads from Mongo by default; accepts override JSON
  - React frontend with 6 routes (Dashboard, Staff, Service Users, Rules, Settings, Admins) + Login
  - Two-theme system: **Paper** (cream + orange section bands, Lora display font) and **Modern** (slate + teal, Outfit display font); persisted in localStorage
  - All shadcn components used: Table, Sheet, Dialog, Tabs, Switch, Slider, Select, Tooltip, AlertDialog, DropdownMenu, Toast (sonner)
  - 31/31 backend tests pass; frontend verified end-to-end via testing agent + screenshots

## Phase 1 known limitations / open items
- Solver hard rule "manager_no_shifts" defaults to mode=hard. If a future seed wants J.C. on the rota voluntarily, the operator must flip this rule to soft OR add a locked cell.
- Email validation accepts any string with `@` (so `.local` works). Phase 2 may want stricter validation per environment.
- Sleepover hour accounting: D*=14h, *=0h. Editable from /settings shift hours table.

## Prioritised backlog
- **P0 — Phase 2**: read-only 4-week rota grid (consumes /api/solver/generate output) with paper-style coloured cells (D=cream, D*=yellow sleepover, N=blue, AL=pink, FA=green, TRN=dark blue, OFF=muted).
- **P0 — Phase 2**: locked-cells / leave editor on the grid (click a cell to set AL/locked).
- **P1 — Phase 3**: "Generate Rota" button wired up + what-if mode (toggle staff to AL/sick on grid, re-solve in place, highlight infeasibility reasons).
- **P1 — rota persistence**: save generated rota to Mongo with versioning.
- **P2 — Phase 4**: PDF & Excel exports.
- **P2**: forgot-password flow.
- **P2**: server-driven rule-config schema validation on PUT /api/rules.

## Next tasks
1. Phase 2 design pass — paper-style rota grid mockup.
2. Phase 2 implementation — read-only grid + cell editor (AL / lock).
3. Phase 3 — wire Generate Rota + what-if.
