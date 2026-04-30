"""
Phase 0 sanity test runner for the rota solver.

Loads `backend/seed/grizedale.json`, calls the solver, prints a readable
grid, and asserts:
    - every day has exactly the required cover (2 day, 2 night with valid combos)
    - per-shift med-competent / first-aider rules
    - no N->D and no D*->D* across consecutive days
    - locked / AL / TRN cells preserved
    - capability flags honoured

Run:    python -m backend.solver.test_runner
        (or)    python backend/solver/test_runner.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Make this script runnable both as a module and as a direct script.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from backend.solver.rota_solver import (  # noqa: E402
    DAY_COVER_SHIFTS,
    NIGHT_COVER_SHIFTS,
    SHIFT_HOURS,
    SHIFT_TYPES,
    WORKING_SHIFTS,
    solve_rota,
)


SEED_PATH = ROOT / "seed" / "grizedale.json"


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def print_rota_grid(payload: dict, result: dict) -> None:
    if not result.get("success"):
        print("\n=== SOLVER FAILED ===")
        print(f"Reason: {result.get('reason')}")
        print(f"Status: {result.get('solver_status')}  Time: {result.get('solve_time_ms')}ms")
        for b in result.get("blocking_constraints", []):
            print(f"  - {b['day_of_week']} {b['date']}: {'; '.join(b['problems'])}")
        return

    rota = result["rota"]
    staff_initials = [s["initials"] for s in payload["staff"]]
    by_date_staff: dict[tuple[str, str], str] = {}
    for day in rota:
        for a in day["assignments"]:
            by_date_staff[(day["date"], a["staff_initials"])] = a["shift"]

    # Print header
    print("\n=== GRIZEDALE 4-WEEK ROTA ===")
    header = f"{'Date':<12}{'Day':<5}" + "".join(f"{s:>6}" for s in staff_initials)
    print(header)
    print("-" * len(header))
    for day in rota:
        line = f"{day['date']:<12}{day['day_of_week']:<5}"
        for s in staff_initials:
            shift = by_date_staff.get((day["date"], s), "?")
            line += f"{shift:>6}"
        print(line)

    # Per-staff totals
    print("\n--- Hours summary ---")
    for s in payload["staff"]:
        init = s["initials"]
        total = 0
        for day in rota:
            for a in day["assignments"]:
                if a["staff_initials"] == init:
                    total += SHIFT_HOURS[a["shift"]]
        target = s.get("target_weekly_hours", 0) * payload.get("weeks", 4)
        delta = total - target
        flag = "" if delta == 0 else f" (Δ {delta:+d}h)"
        print(f"  {init:<6} {total:>4}h / target {target}h{flag}")

    print(f"\nSoft-violations score: {result.get('soft_violations_score')}")
    print(f"Solve time: {result.get('solve_time_ms')} ms  ({result.get('solver_status')})")
    if result.get("warnings"):
        print("Warnings:")
        for w in result["warnings"]:
            print(f"  - {w}")


def assert_rota_valid(payload: dict, result: dict) -> None:
    """Hard-rule assertions on the produced rota."""
    assert result.get("success"), f"solver failed: {result.get('reason')}"
    rota = result["rota"]
    staff_by = {s["initials"]: s for s in payload["staff"]}

    # forced cells
    forced = {}
    for e in payload.get("leave", []):
        forced[(e["staff_initials"], e["date"])] = e.get("type", "AL")
    for e in payload.get("locked_cells", []):
        forced[(e["staff_initials"], e["date"])] = e["shift"]

    # Index by (date, staff)
    cell: dict[tuple[str, str], str] = {}
    for day in rota:
        for a in day["assignments"]:
            cell[(day["date"], a["staff_initials"])] = a["shift"]

    # Forced-cells preserved
    for key, shift in forced.items():
        assert cell.get(key) == shift, f"forced cell {key} expected {shift}, got {cell.get(key)}"

    # Cover + per-shift requirements
    for day in rota:
        d = day["date"]
        assignments = day["assignments"]
        shift_count = {t: 0 for t in SHIFT_TYPES}
        for a in assignments:
            shift_count[a["shift"]] += 1

        # Day cover: D + D* == 2 and D* <= 1
        assert shift_count["D"] + shift_count["D*"] == 2, f"{d} day cover != 2"
        assert shift_count["D*"] <= 1, f"{d} multiple D*"

        # Night cover: N == 1, D* + * == 1
        assert shift_count["N"] == 1, f"{d} night cover N!=1"
        assert shift_count["D*"] + shift_count["*"] == 1, f"{d} sleepover != 1"

        on_day = [a["staff_initials"] for a in assignments if a["shift"] in DAY_COVER_SHIFTS]
        on_night = [a["staff_initials"] for a in assignments if a["shift"] in NIGHT_COVER_SHIFTS]

        # Med-competent + first-aider per shift
        assert any(staff_by[s].get("medication_competent") for s in on_day), f"{d} no med-comp on day"
        assert any(staff_by[s].get("medication_competent") for s in on_night), f"{d} no med-comp on night"
        assert any(staff_by[s].get("first_aider") for s in on_day), f"{d} no first-aider on day"
        assert any(staff_by[s].get("first_aider") for s in on_night), f"{d} no first-aider on night"

        # No-male-pair-alone
        males_on_day = [s for s in on_day if staff_by[s].get("gender") == "M"]
        females_on_day = [s for s in on_day if staff_by[s].get("gender") == "F"]
        if males_on_day:
            assert females_on_day, f"{d} day shift male-only (no female)"
        males_on_night = [s for s in on_night if staff_by[s].get("gender") == "M"]
        females_on_night = [s for s in on_night if staff_by[s].get("gender") == "F"]
        if males_on_night:
            assert females_on_night, f"{d} night shift male-only (no female)"

        # Capability checks
        for a in assignments:
            info = staff_by[a["staff_initials"]]
            shift = a["shift"]
            if shift in {"D", "D*"}:
                assert info.get("can_do_days"), f"{d} {a['staff_initials']} D/D* but cannot do days"
            if shift == "N":
                assert info.get("can_do_nights"), f"{d} {a['staff_initials']} N but cannot do nights"
            if shift in {"D*", "*"}:
                assert info.get("can_do_sleepover"), f"{d} {a['staff_initials']} sleep but cannot sleepover"

    # Consecutive-day: N->D forbidden, D*->D* forbidden
    for s in staff_by:
        for i in range(len(rota) - 1):
            today = cell[(rota[i]["date"], s)]
            tomorrow = cell[(rota[i + 1]["date"], s)]
            if today == "N":
                assert tomorrow != "D", f"{s} N->D on {rota[i]['date']}->{rota[i+1]['date']}"
            if today == "D*":
                assert tomorrow != "D*", f"{s} D*->D* on {rota[i]['date']}->{rota[i+1]['date']}"

    print("\n[OK] all hard-rule assertions passed")


def main() -> int:
    payload = json.loads(SEED_PATH.read_text())
    print(f"Loaded seed: {len(payload['staff'])} staff, "
          f"{payload['weeks']} weeks starting {payload['rota_start_date']}")

    result = solve_rota(payload, time_limit_s=10)
    print_rota_grid(payload, result)
    assert_rota_valid(payload, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
