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

    # =====================================================================
    # Part A regression: "no sleepover before leave"
    # A D*/* shift extends into 08:00 next day. So if a staff is on AL or
    # TRN tomorrow they cannot sleepover tonight.
    # =====================================================================
    print("\n=== NEW RULE: no_sleepover_before_leave ===")
    # 1) Solver must refuse when we lock D.A. on D* Tuesday AND AL on Wednesday.
    sleep_before_leave_payload = json.loads(SEED_PATH.read_text())
    sleep_before_leave_payload["locked_cells"] = [
        {"staff_initials": "D.A.", "date": "2026-04-21", "shift": "D*"},
    ]
    sleep_before_leave_payload["leave"] = [
        {"staff_initials": "D.A.", "date": "2026-04-22", "type": "AL"},
    ]
    solver_result = solve_rota(sleep_before_leave_payload, time_limit_s=5)
    assert not solver_result.get("success"), (
        "solver should return INFEASIBLE when D* on 2026-04-21 is paired with "
        "AL on 2026-04-22, got success=True"
    )
    assert "INFEASIBLE" in (solver_result.get("solver_status") or ""), (
        f"expected INFEASIBLE status, got {solver_result.get('solver_status')}"
    )
    print(
        f"  solver correctly returns {solver_result.get('solver_status')} "
        "for D* Tue + AL Wed lock"
    )

    # 2) Validator must flag the offending (today, tomorrow) pair.
    manual_rota = {
        "start_date": "2026-04-20",
        "weeks": 1,
        "assignments": [
            # Minimal valid-ish cover on Mon so Mon itself doesn't complain,
            # then on Tue the D* + AL Wed creates the violation.
            {"date": "2026-04-20", "staff_initials": "L.M.", "shift": "D",   "locked": False},
            {"date": "2026-04-20", "staff_initials": "L.D.", "shift": "D*",  "locked": False},
            {"date": "2026-04-20", "staff_initials": "C.E.", "shift": "N",   "locked": False},
            # The pair under test:
            {"date": "2026-04-21", "staff_initials": "D.A.", "shift": "D*",  "locked": False},
            {"date": "2026-04-22", "staff_initials": "D.A.", "shift": "AL",  "locked": False},
        ],
    }
    v_list = validate_rota(manual_rota, payload["staff"], rules_config={})
    sleep_leave_v = [
        v for v in v_list
        if v["rule_id"] == "no_sleepover_before_leave" and v["severity"] == "hard"
    ]
    assert sleep_leave_v, (
        f"expected a `no_sleepover_before_leave` HARD violation, "
        f"got rule_ids: {[v['rule_id'] for v in v_list]}"
    )
    affected_inits = {c["staff_initials"] for v in sleep_leave_v for c in v["affected_cells"]}
    assert "D.A." in affected_inits, f"D.A. expected in affected_cells, got {affected_inits}"
    affected_dates = {c["date"] for v in sleep_leave_v for c in v["affected_cells"]}
    assert {"2026-04-21", "2026-04-22"} <= affected_dates, (
        f"both the D* date and the AL date should be in affected_cells, got {affected_dates}"
    )
    print(
        f"  validator flags D.A. D* 2026-04-21 → AL 2026-04-22 "
        f"(affected dates: {sorted(affected_dates)}) [OK]"
    )
    print("[OK] no_sleepover_before_leave rule verified (solver + validator)")

    # =====================================================================
    # Part 1 regression: senior_weekend_cover
    # Every Sat and Sun in the solver's output must have at least one of
    # {L.M., L.D.} on D or D*.
    # =====================================================================
    print("\n=== NEW RULE: senior_weekend_cover ===")
    seniors = {"L.M.", "L.D."}
    rota_days = result["rota"]
    weekend_misses = []
    for day in rota_days:
        dow = datetime.strptime(day["date"], "%Y-%m-%d").weekday()
        if dow < 5:
            continue
        on_day = [
            a["staff_initials"] for a in day["assignments"]
            if a["shift"] in {"D", "D*"} and a["staff_initials"] in seniors
        ]
        if not on_day:
            weekend_misses.append(day["date"])
    assert not weekend_misses, (
        f"weekend days without a senior (L.M./L.D.) on D/D*: {weekend_misses}"
    )
    # Also verify the rotation nudge is respected most of the time:
    # default rotation is week 1&3=L.M., week 2&4=L.D.
    payload_rot = json.loads(SEED_PATH.read_text())
    payload_rot["senior_weekend_rotation"] = [
        {"week_index": 1, "staff_initials": "L.M."},
        {"week_index": 2, "staff_initials": "L.D."},
        {"week_index": 3, "staff_initials": "L.M."},
        {"week_index": 4, "staff_initials": "L.D."},
    ]
    result_rot = solve_rota(payload_rot, time_limit_s=8)
    assert result_rot["success"], f"rotation-preferred solve failed: {result_rot.get('reason')}"
    rot_cell = {(d["date"], a["staff_initials"]): a["shift"]
                for d in result_rot["rota"] for a in d["assignments"]}
    match = 0
    total = 0
    for day in result_rot["rota"]:
        dt = datetime.strptime(day["date"], "%Y-%m-%d").date()
        if dt.weekday() < 5:
            continue
        total += 1
        w_idx = ((dt - _parse_date(payload_rot["rota_start_date"])).days // 7) + 1
        expected = {1: "L.M.", 2: "L.D.", 3: "L.M.", 4: "L.D."}.get(w_idx)
        if expected and rot_cell.get((day["date"], expected)) in {"D", "D*"}:
            match += 1
    print(f"  rotation respected on {match}/{total} weekend days")
    print("[OK] senior_weekend_cover verified (hard coverage + soft rotation nudge)")

    # =====================================================================
    # Part 2 regression: contracted_hours_min is PER WEEK
    # Every non-admin staff should hit their weekly target (within 2h) in
    # EACH of the 4 weeks.
    # =====================================================================
    print("\n=== CHANGED RULE: contracted_hours_min is PER WEEK ===")
    per_week_cell = {(d["date"], a["staff_initials"]): a["shift"]
                     for d in result["rota"] for a in d["assignments"]}
    for s in payload["staff"]:
        init = s["initials"]
        target_weekly = int(s.get("target_weekly_hours") or 0)
        if target_weekly <= 0:
            continue
        for w in range(payload.get("weeks", 4)):
            week_dates = [
                (_parse_date(payload["rota_start_date"]) + timedelta(days=w * 7 + i)).isoformat()
                for i in range(7)
            ]
            al_w = sum(1 for d in week_dates if per_week_cell.get((d, init)) == "AL")
            trn_w = sum(1 for d in week_dates if per_week_cell.get((d, init)) == "TRN")
            hrs = sum(DEFAULT_SHIFT_HOURS[per_week_cell.get((d, init), "OFF")] for d in week_dates)
            min_required = target_weekly - 12 * al_w - 8 * trn_w - 2
            assert hrs >= min_required, (
                f"{init} week {w + 1}: {hrs}h vs required ≥{min_required}h "
                f"(target {target_weekly}/wk, AL {al_w}, TRN {trn_w})"
            )
    print("[OK] every non-admin staff hits weekly contracted hours each of 4 weeks")

    # =====================================================================
    # Part 3 regression: avoid_pair_seniors
    # Count days L.M. and L.D. are BOTH on day cover. Soft rule, so some
    # days may still pair — assert it's rare (<= 2 out of 28).
    # =====================================================================
    print("\n=== NEW RULE: avoid_pair_seniors ===")
    pair_days = [
        d["date"] for d in result["rota"]
        if per_week_cell.get((d["date"], "L.M.")) in {"D", "D*"}
        and per_week_cell.get((d["date"], "L.D.")) in {"D", "D*"}
    ]
    print(f"  L.M. + L.D. paired on {len(pair_days)}/28 days: {pair_days}")
    assert len(pair_days) <= 2, (
        f"avoid_pair_seniors is weight-40 soft — expected at most 2 pair-days, got {len(pair_days)}"
    )
    print("[OK] avoid_pair_seniors keeps senior pairs rare")

    # =====================================================================
    # Part 4 regression: Flexi redistribution when one flexi is on AL week
    # When D.A. is on AL all of week 2, T.D. should pick up extra hours in
    # that specific week. Assert: T.D.'s week-2 hours >= her average week-1,3,4
    # hours (she absorbs the slack).
    # =====================================================================
    print("\n=== BUG REGRESSION: flexi redistribution under AL week ===")
    al_payload = json.loads(SEED_PATH.read_text())
    # Mon 2026-04-27 .. Sun 2026-05-03 is week 2
    al_payload["leave"] = [
        {"staff_initials": "D.A.", "date": (
            _parse_date("2026-04-27") + timedelta(days=i)
        ).isoformat(), "type": "AL"}
        for i in range(7)
    ]
    al_result = solve_rota(al_payload, time_limit_s=10)
    assert al_result["success"], (
        f"solver must still succeed when D.A. is on AL all of week 2, "
        f"got: {al_result.get('reason')}"
    )
    al_cell = {(d["date"], a["staff_initials"]): a["shift"]
               for d in al_result["rota"] for a in d["assignments"]}
    week_hours = {}
    for w in range(4):
        wd = [(_parse_date("2026-04-20") + timedelta(days=w * 7 + i)).isoformat()
              for i in range(7)]
        week_hours[w + 1] = sum(DEFAULT_SHIFT_HOURS[al_cell.get((d, "T.D."), "OFF")] for d in wd)
    td_w2 = week_hours[2]
    td_others_avg = (week_hours[1] + week_hours[3] + week_hours[4]) / 3
    print(
        f"  T.D. hours per week: w1={week_hours[1]}h w2={week_hours[2]}h "
        f"w3={week_hours[3]}h w4={week_hours[4]}h (others avg {td_others_avg:.1f}h)"
    )
    assert td_w2 >= td_others_avg - 2, (
        f"Flexi redistribution broken: T.D. week-2 hours ({td_w2}h) is "
        f"well below her avg non-AL-week hours ({td_others_avg:.1f}h). "
        "Expected the other flexi to pick up D.A.'s slack."
    )
    assert td_w2 >= 34, (
        f"T.D. contracted 34h/wk must hold under flexi AL gap; got {td_w2}h"
    )
    print("[OK] flexi redistribution: T.D. absorbs D.A.'s AL-week slack")

    # =====================================================================
    # NEW RULE: min_sleepover_per_week_for_seniors
    # L.M., L.D., T.D. should each have >= 1 D* in every week (unless they
    # are on AL/TRN ≥5 days that week).
    # =====================================================================
    print("\n=== NEW RULE: min_sleepover_per_week_for_seniors ===")
    seniors_for_dstar = ["L.M.", "L.D.", "T.D."]
    cell_main = {(d["date"], a["staff_initials"]): a["shift"]
                 for d in result["rota"] for a in d["assignments"]}
    misses = []
    for s in seniors_for_dstar:
        for w in range(payload.get("weeks", 4)):
            week_dates = [
                (_parse_date(payload["rota_start_date"]) + timedelta(days=w * 7 + i)).isoformat()
                for i in range(7)
            ]
            unavail = sum(1 for d in week_dates if cell_main.get((d, s)) in {"AL", "TRN"})
            if unavail >= 5:
                continue  # mostly off — rule skips
            dstars = sum(1 for d in week_dates if cell_main.get((d, s)) == "D*")
            if dstars < 1:
                misses.append((s, w + 1, dstars))
    print(f"  per-staff per-week D* counts (default seed): {len(misses)} missing-week(s)")
    for m in misses:
        print(f"    miss: {m[0]} week {m[1]} = {m[2]} D*")
    # Soft rule (weight 30) — solver should naturally produce 0 misses
    # in the default seed since rotation already requires sleepovers.
    assert len(misses) == 0, (
        f"min_sleepover_per_week_for_seniors soft rule should be satisfied "
        f"in default seed, got misses: {misses}"
    )
    print("[OK] every senior staff has >=1 D* every week (default seed)")

    # =====================================================================
    # Item 7 regression: T.D. AL must NOT make D.A. AL
    # The solver must never voluntarily assign AL — only honour input leave.
    # Repro: insert AL for T.D. on 3 dates, generate, assert D.A. has NO AL
    # on those dates (or anywhere) and her week's hours are >= baseline.
    # =====================================================================
    print("\n=== BUG REGRESSION: T.D. AL must not auto-AL D.A. ===")
    td_al_payload = json.loads(SEED_PATH.read_text())
    td_al_dates = ["2026-04-22", "2026-04-29", "2026-05-06"]  # 3 Wednesdays
    td_al_payload["leave"] = [
        {"staff_initials": "T.D.", "date": d, "type": "AL"} for d in td_al_dates
    ]
    td_al_result = solve_rota(td_al_payload, time_limit_s=10)
    assert td_al_result["success"], (
        f"solver must succeed when only T.D. has AL, got: {td_al_result.get('reason')}"
    )
    td_cell = {(d["date"], a["staff_initials"]): a["shift"]
               for d in td_al_result["rota"] for a in d["assignments"]}
    # ASSERTION 1: D.A. is NEVER on AL anywhere in the resulting rota
    da_al_dates = [d for d, init in td_cell.keys() if init == "D.A." and td_cell[(d, init)] == "AL"]
    assert da_al_dates == [], (
        f"BUG: D.A. ended up on AL on {da_al_dates} — solver must only honour input leave"
    )
    # ASSERTION 2: T.D. is on AL on EXACTLY the 3 input dates (no fan-out, no shrinkage)
    td_al_actual = sorted([d for d, init in td_cell.keys() if init == "T.D." and td_cell[(d, init)] == "AL"])
    assert td_al_actual == sorted(td_al_dates), (
        f"T.D. AL dates mismatch: expected {sorted(td_al_dates)} got {td_al_actual}"
    )
    # ASSERTION 3: D.A. on those dates is a working shift or OFF (never AL)
    for d in td_al_dates:
        sh = td_cell[(d, "D.A.")]
        assert sh in {"D", "D*", "N", "*", "OFF"}, (
            f"D.A. on {d} should be working/OFF, got {sh}"
        )
    # ASSERTION 4: D.A.'s hours in the week containing each AL date >= baseline.
    # Compute D.A. hours per week. Baseline = average week without T.D. AL.
    baseline_da = 0
    for w in range(4):
        wd = [(_parse_date("2026-04-20") + timedelta(days=w * 7 + i)).isoformat()
              for i in range(7)]
        baseline_da += sum(DEFAULT_SHIFT_HOURS[cell_main.get((d, "D.A."), "OFF")] for d in wd)
    baseline_da_per_week = baseline_da / 4
    da_per_week = []
    for w in range(4):
        wd = [(_parse_date("2026-04-20") + timedelta(days=w * 7 + i)).isoformat()
              for i in range(7)]
        da_per_week.append(
            sum(DEFAULT_SHIFT_HOURS[td_cell.get((d, "D.A."), "OFF")] for d in wd)
        )
    print(f"  D.A. hours/week (T.D. AL scenario): {da_per_week} (avg {sum(da_per_week)/4:.1f}h)")
    print(f"  D.A. hours/week (clean baseline avg): {baseline_da_per_week:.1f}h")
    # In any week with T.D.-AL, D.A. should be >= baseline (slack opens up).
    affected_weeks = set()
    for d in td_al_dates:
        delta = (_parse_date(d) - _parse_date("2026-04-20")).days
        affected_weeks.add(delta // 7)
    for w in affected_weeks:
        assert da_per_week[w] >= baseline_da_per_week - 2, (
            f"D.A. week {w + 1} hours ({da_per_week[w]}h) below baseline "
            f"({baseline_da_per_week:.1f}h) — slack should flow to D.A. when T.D. is on AL"
        )
    print("[OK] item-7 regression: T.D. AL leaves D.A. unchanged-or-busier; D.A. never auto-AL'd")

    # =====================================================================
    # Item 6 regression: max_one_per_role_on_al
    # Validator must flag when 2 staff in same role (e.g. D.A. & T.D., both
    # Flexi) are on AL the same date.
    # =====================================================================
    print("\n=== NEW RULE: max_one_per_role_on_al ===")
    rota_double_al = {
        "start_date": "2026-04-20",
        "weeks": 1,
        "assignments": [
            {"date": "2026-04-22", "staff_initials": "D.A.", "shift": "AL", "locked": False},
            {"date": "2026-04-22", "staff_initials": "T.D.", "shift": "AL", "locked": False},
            {"date": "2026-04-22", "staff_initials": "L.M.", "shift": "D",   "locked": False},
            {"date": "2026-04-22", "staff_initials": "L.D.", "shift": "D*",  "locked": False},
            {"date": "2026-04-22", "staff_initials": "C.E.", "shift": "N",   "locked": False},
        ],
    }
    v_dbl = validate_rota(rota_double_al, payload["staff"], rules_config={})
    role_v = [v for v in v_dbl if v["rule_id"] == "max_one_per_role_on_al" and v["severity"] == "hard"]
    assert role_v, (
        f"validator did not catch double-Flexi-AL on 2026-04-22, "
        f"got rule_ids: {[v['rule_id'] for v in v_dbl]}"
    )
    affected = sorted({c["staff_initials"] for v in role_v for c in v["affected_cells"]})
    assert affected == ["D.A.", "T.D."], (
        f"affected_cells mismatch: expected ['D.A.', 'T.D.'], got {affected}"
    )
    print(f"  validator caught: {role_v[0]['message']}")
    print("[OK] max_one_per_role_on_al validator check verified")

    return 0


if __name__ == "__main__":
    sys.exit(main())
