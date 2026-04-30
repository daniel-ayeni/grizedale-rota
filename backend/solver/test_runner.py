"""
Phase 1 sanity test runner for the rota solver.

Loads `backend/seed/grizedale.json`, calls the solver, prints a readable
grid, and asserts:
    - every day has the required day + night cover
    - per-shift med-competent / first-aider rules (relaxed night med rule)
    - no N->D and no D*->D* across consecutive days
    - locked / AL / TRN cells preserved
    - capability flags honoured
    - **Manager (J.C.) never works a shift unless locked**
    - **D.A. on D*/*  =>  the N-staff on that day must be C.E. or J.R.
      (i.e. A.A. must NEVER end up on N when D.A. is the sleepover staff)**
    - **Every staff (target>0) hits contracted hours within -2h tolerance**
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from backend.solver.rota_solver import (  # noqa: E402
    DAY_COVER_SHIFTS,
    DEFAULT_SHIFT_HOURS,
    NIGHT_COVER_SHIFTS,
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
        for b in result.get("blocking_constraints", []):
            print(f"  - {b['day_of_week']} {b['date']}: {'; '.join(b['problems'])}")
        return

    rota = result["rota"]
    staff_inits = [s["initials"] for s in payload["staff"]]
    cell = {(d["date"], a["staff_initials"]): a["shift"] for d in rota for a in d["assignments"]}

    print("\n=== GRIZEDALE 4-WEEK ROTA ===")
    header = f"{'Date':<12}{'Day':<5}" + "".join(f"{s:>6}" for s in staff_inits)
    print(header)
    print("-" * len(header))
    for d in rota:
        line = f"{d['date']:<12}{d['day_of_week']:<5}"
        for s in staff_inits:
            line += f"{cell.get((d['date'], s), '?'):>6}"
        print(line)

    print("\n--- Hours summary ---")
    for s in payload["staff"]:
        init = s["initials"]
        total = sum(DEFAULT_SHIFT_HOURS[cell[(d['date'], init)]] for d in rota)
        target = s.get("target_weekly_hours", 0) * payload.get("weeks", 4)
        delta = total - target
        flag = "" if delta == 0 else f" (Δ {delta:+d}h)"
        print(f"  {init:<6} {total:>4}h / target {target}h{flag}")

    print(f"\nSoft-violations score: {result.get('soft_violations_score')}")
    print(f"Solve time: {result.get('solve_time_ms')} ms  ({result.get('solver_status')})")


def assert_rota_valid(payload: dict, result: dict) -> None:
    assert result.get("success"), f"solver failed: {result.get('reason')}"
    rota = result["rota"]
    staff_by = {s["initials"]: s for s in payload["staff"]}
    weeks = payload.get("weeks", 4)
    shift_hours = DEFAULT_SHIFT_HOURS

    forced = {}
    for e in payload.get("leave", []):
        forced[(e["date"], e["staff_initials"])] = e.get("type", "AL")
    for e in payload.get("locked_cells", []):
        forced[(e["date"], e["staff_initials"])] = e["shift"]

    cell = {(d["date"], a["staff_initials"]): a["shift"] for d in rota for a in d["assignments"]}

    # forced cells preserved
    for key, shift in forced.items():
        assert cell.get(key) == shift, f"forced cell {key} expected {shift}, got {cell.get(key)}"

    for day in rota:
        d = day["date"]
        sc = {t: 0 for t in SHIFT_TYPES}
        for a in day["assignments"]:
            sc[a["shift"]] += 1
        # cover
        assert sc["D"] + sc["D*"] == 2, f"{d} day cover != 2"
        assert sc["D*"] <= 1, f"{d} multiple D*"
        assert sc["N"] == 1, f"{d} night N != 1"
        assert sc["D*"] + sc["*"] == 1, f"{d} sleepover != 1"

        on_day = [a["staff_initials"] for a in day["assignments"] if a["shift"] in DAY_COVER_SHIFTS]
        on_night = [a["staff_initials"] for a in day["assignments"] if a["shift"] in NIGHT_COVER_SHIFTS]
        # day shift med (must be specifically on day side)
        assert any(staff_by[s].get("medication_competent") for s in on_day), f"{d} no med-comp on day"
        # night shift med (relaxed: any of N/D*/*)
        assert any(staff_by[s].get("medication_competent") for s in on_night), f"{d} no med-comp on night"
        assert any(staff_by[s].get("first_aider") for s in on_day), f"{d} no first-aider on day"
        assert any(staff_by[s].get("first_aider") for s in on_night), f"{d} no first-aider on night"

        # No-male-pair-alone
        males_day = [s for s in on_day if staff_by[s].get("gender") == "M"]
        females_day = [s for s in on_day if staff_by[s].get("gender") == "F"]
        if males_day:
            assert females_day, f"{d} day shift male-only"
        males_night = [s for s in on_night if staff_by[s].get("gender") == "M"]
        females_night = [s for s in on_night if staff_by[s].get("gender") == "F"]
        if males_night:
            assert females_night, f"{d} night shift male-only ({males_night})"

        # Capability
        for a in day["assignments"]:
            info = staff_by[a["staff_initials"]]
            sh = a["shift"]
            if sh in {"D", "D*"}:
                assert info.get("can_do_days"), f"{d} {a['staff_initials']} {sh} but cannot do days"
            if sh == "N":
                assert info.get("can_do_nights"), f"{d} {a['staff_initials']} N but cannot do nights"
            if sh in {"D*", "*"}:
                assert info.get("can_do_sleepover"), f"{d} {a['staff_initials']} {sh} but cannot sleepover"

        # Manager hard rule: J.C. never works a shift (unless locked override)
        for a in day["assignments"]:
            info = staff_by[a["staff_initials"]]
            if info.get("is_admin_only") and a["shift"] in WORKING_SHIFTS:
                # must be a locked override
                key = (a["staff_initials"], d)
                assert forced.get(key) == a["shift"], (
                    f"{d} admin-only staff {a['staff_initials']} working {a['shift']} "
                    "without locked override"
                )

        # === User-requested explicit pairing assertion =========================
        # If D.A. is on D* or *, the N-staff on that day must be C.E. or J.R.
        # (i.e. A.A. must NEVER pair as N with D.A. on D*/*).
        da_shift = cell.get((d, "D.A."))
        if da_shift in {"D*", "*"}:
            n_staff = next(
                (a["staff_initials"] for a in day["assignments"] if a["shift"] == "N"),
                None,
            )
            assert n_staff in {"C.E.", "J.R."}, (
                f"{d}: D.A. is on {da_shift} but N is {n_staff} — "
                "expected C.E. or J.R. (not A.A.)"
            )

    # Consecutive-day rules
    for s in staff_by:
        for i in range(len(rota) - 1):
            today = cell[(rota[i]["date"], s)]
            tomorrow = cell[(rota[i + 1]["date"], s)]
            if today == "N":
                assert tomorrow != "D", f"{s} N->D on {rota[i]['date']}->{rota[i+1]['date']}"
            if today == "D*":
                assert tomorrow != "D*", f"{s} D*->D* on {rota[i]['date']}->{rota[i+1]['date']}"

    # Contracted-hours hard rule (-2h tolerance)
    for s in payload["staff"]:
        init = s["initials"]
        target_total = s.get("target_weekly_hours", 0) * weeks
        if target_total <= 0:
            continue
        actual = 0
        al_count = 0
        trn_count = 0
        for day in rota:
            sh = cell[(day["date"], init)]
            actual += shift_hours[sh]
            if sh == "AL":
                al_count += 1
            if sh == "TRN":
                trn_count += 1
        min_required = target_total - 12 * al_count - 8 * trn_count - 2
        assert actual >= min_required, (
            f"{init}: only {actual}h vs required >= {min_required}h "
            f"(target {target_total}, AL {al_count}, TRN {trn_count})"
        )

    print("\n[OK] all hard-rule assertions passed")
    print("[OK] explicit D.A.+N pairing rule (D.A. on D*/* => N in {C.E., J.R.}) verified")
    print("[OK] contracted-hours hard rule verified (within -2h tolerance)")


def main() -> int:
    payload = json.loads(SEED_PATH.read_text())
    print(f"Loaded seed: {len(payload['staff'])} staff, "
          f"{payload['weeks']} weeks starting {payload['rota_start_date']}")
    result = solve_rota(payload, time_limit_s=10)
    print_rota_grid(payload, result)
    assert_rota_valid(payload, result)

    # =====================================================================
    # Forced-scenario test: when D.A. is locked on D* on specific dates,
    # the N-staff for those dates MUST be C.E. or J.R. (never A.A.).
    # This gives positive evidence for the no-male-pair-on-night rule —
    # we are explicitly forcing D.A. onto the night side and verifying
    # the solver picks a female N partner.
    #
    # NOTE: As of Phase 1 polish, C.E. is permanently flagged as
    # first_aider=true in the seed (resolves the night-FA gap), so this
    # test no longer needs the in-memory FA override.
    # =====================================================================
    print("\n=== FORCED-SCENARIO TEST: D.A. locked on D* ===")
    forced_payload = json.loads(SEED_PATH.read_text())
    forced_dates = ["2026-04-22", "2026-04-29"]
    forced_payload["locked_cells"] = [
        {"staff_initials": "D.A.", "date": d, "shift": "D*"} for d in forced_dates
    ]
    print(f"Locked: D.A. = D* on {', '.join(forced_dates)}")
    forced_result = solve_rota(forced_payload, time_limit_s=10)
    assert forced_result.get("success"), (
        f"forced-scenario solver failed: {forced_result.get('reason')}"
    )

    forced_cell = {
        (d["date"], a["staff_initials"]): a["shift"]
        for d in forced_result["rota"]
        for a in d["assignments"]
    }
    for d_str in forced_dates:
        assert forced_cell[(d_str, "D.A.")] == "D*", (
            f"{d_str}: D.A. should be locked on D*, got {forced_cell[(d_str, 'D.A.')]}"
        )
        n_staff = next(
            (a["staff_initials"] for a in next(d for d in forced_result["rota"] if d["date"] == d_str)["assignments"] if a["shift"] == "N"),
            None,
        )
        assert n_staff in {"C.E.", "J.R."}, (
            f"{d_str}: D.A. is locked on D* but N is {n_staff} — expected C.E. or J.R."
        )
        # And specifically NOT A.A.
        assert n_staff != "A.A.", (
            f"{d_str}: D.A. locked on D* and N=A.A. — male-pair-alone rule violated!"
        )
        print(f"  {d_str}: D.A.=D*, N={n_staff} -> OK (male-pair-on-night rule enforced; A.A. excluded)")

    # Run the full assertion suite on the forced result too
    assert_rota_valid(forced_payload, forced_result)
    print("[OK] forced-scenario hard-rule assertions passed")
    print(f"Forced solve time: {forced_result.get('solve_time_ms')} ms")

    # =====================================================================
    # Validator regression test: D* → * breaks day cover and L.D.'s `*`
    # cell MUST be flagged in `affected_cells`. (Bug repro: previously the
    # validator only flagged the surviving D-side cell, leaving the
    # cell the user just edited unmarked in the frontend.)
    # =====================================================================
    print("\n=== VALIDATOR REGRESSION: D* -> * day-cover break flags the `*` cell ===")
    # The validator imports `solver.rule_definitions` (no `backend.` prefix)
    # so we need /app/backend on sys.path before importing it.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from solver.rota_validator import (  # noqa: E402
        validate_rota,
        summarise_violations,
    )

    # Find the first date where L.D. is on D* in the unforced solver result
    target_date = None
    for day in result["rota"]:
        for a in day["assignments"]:
            if a["staff_initials"] == "L.D." and a["shift"] == "D*":
                target_date = day["date"]
                break
        if target_date:
            break
    assert target_date, "expected at least one D* assignment for L.D. in solver result"

    # Build a mutated rota: L.D.'s D* on target_date becomes *
    mutated_assignments = []
    for day in result["rota"]:
        for a in day["assignments"]:
            mutated = {
                "date": day["date"],
                "staff_initials": a["staff_initials"],
                "shift": a["shift"],
                "locked": False,
            }
            if mutated["date"] == target_date and mutated["staff_initials"] == "L.D.":
                mutated["shift"] = "*"
            mutated_assignments.append(mutated)
    mutated_rota = {
        "start_date": payload["rota_start_date"],
        "weeks": payload.get("weeks", 4),
        "assignments": mutated_assignments,
    }

    vlist = validate_rota(mutated_rota, payload["staff"], rules_config={})
    summary = summarise_violations(vlist)
    print(f"  validator returned {summary['hard']} hard / {summary['soft']} soft violations")

    day_cover_v = [
        v for v in vlist
        if v["rule_id"] == "day_cover" and v.get("date") == target_date and v["severity"] == "hard"
    ]
    assert day_cover_v, (
        f"expected a `day_cover` HARD violation on {target_date} after D*->*, "
        f"got: {[v['rule_id'] for v in vlist]}"
    )
    affected_inits = {c["staff_initials"] for v in day_cover_v for c in v["affected_cells"]}
    assert "L.D." in affected_inits, (
        f"L.D.'s `*` cell on {target_date} must be in affected_cells "
        f"(otherwise the frontend cannot red-border the cell the user just edited). "
        f"Got affected: {sorted(affected_inits)}"
    )
    print(
        f"  {target_date}: day_cover violation raised; "
        f"affected_cells = {sorted(affected_inits)} -> includes L.D. [OK]"
    )
    print("[OK] validator regression: `*` cell is flagged when day cover breaks")

    return 0


if __name__ == "__main__":
    sys.exit(main())
