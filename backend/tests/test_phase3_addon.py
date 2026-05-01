"""Phase 3 ADD-ON backend tests — 4 new solver/rule items.

Covers:
  1. Fresh /generate on 2026-04-20 (weeks=4) → OPTIMAL/FEASIBLE, solve<15s, hard==0.
  2. senior_weekend_cover (HARD): L.M. or L.D. on D/D* every Sat & Sun.
  3. senior_weekend_rotation (SOFT nudge): default rotation honored >=6/8 weekend days.
  4. Rotation FALLBACK: L.M. AL in week 3 → L.D. covers that weekend.
  5. PER-WEEK contracted_hours_min for each non-J.C. staff.
  6. PER-WEEK non_flexi_overage cap (+8h).
  7. avoid_pair_seniors (SOFT w=40): <=2/28 days with both L.M. and L.D. on D/D*.
  8. Flexi redistribution BUG FIX: D.A. AL all week 2 → T.D. week 2 hrs > weeks 1/3 and >=34h.
  9. GET /api/rules exposes senior_weekend_cover (hard, immovable) and avoid_pair_seniors (soft, w=40).
 10. GET /api/settings exposes senior_weekend_rotation array (len=4, weeks 1-4, L.M./L.D.).
 11. PUT /api/settings round-trips mutated rotation and subsequent /generate respects it.
"""
import os
import time
import pytest
import requests
from datetime import date, timedelta

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
EMAIL = "manager@grizedale.local"
PASSWORD = "ChangeMe123!"

SHIFT_HOURS = {"D": 12, "D*": 14, "N": 12, "*": 0, "OFF": 0, "AL": 0, "TRN": 0, "": 0}


@pytest.fixture(scope="module")
def auth():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


def _create_rota(auth, start_date, title, weeks=4):
    r = auth.post(f"{BASE_URL}/api/rotas", json={"start_date": start_date, "weeks": weeks, "title": title}, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _delete_rota(auth, rid):
    try:
        auth.delete(f"{BASE_URL}/api/rotas/{rid}", timeout=15)
    except Exception:
        pass


def _delete_leave_for(auth, staff, dates):
    try:
        r = auth.get(f"{BASE_URL}/api/leave", params={"staff": staff}, timeout=15).json()
        for L in r:
            if L.get("date") in dates:
                auth.delete(f"{BASE_URL}/api/leave/{L['id']}", timeout=15)
    except Exception:
        pass


def _week_index(d_str, start_str):
    d = date.fromisoformat(d_str)
    s = date.fromisoformat(start_str)
    return ((d - s).days // 7) + 1  # 1-based week index


def _hours_by_staff_week(assignments, start_date):
    """Return {staff: {week_index: hours}}."""
    out: dict = {}
    for a in assignments:
        init = a["staff_initials"]
        wk = _week_index(a["date"], start_date)
        hrs = SHIFT_HOURS.get(a["shift"], 0)
        out.setdefault(init, {}).setdefault(wk, 0)
        out[init][wk] += hrs
    return out


def _count_by_staff_week(assignments, start_date, shifts):
    out: dict = {}
    for a in assignments:
        if a["shift"] in shifts:
            init = a["staff_initials"]
            wk = _week_index(a["date"], start_date)
            out.setdefault(init, {}).setdefault(wk, 0)
            out[init][wk] += 1
    return out


# ---------- 1. Fresh /generate ------------------------------------------
class TestFreshGenerate:
    def test_fresh_generate_optimal(self, auth):
        rota = _create_rota(auth, "2026-04-20", "TEST_addon_fresh")
        rid = rota["id"]
        try:
            t0 = time.time()
            r = auth.post(f"{BASE_URL}/api/rotas/{rid}/generate", timeout=30)
            dt_ms = (time.time() - t0) * 1000
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["solver_status"] in {"OPTIMAL", "FEASIBLE"}
            assert d["solve_time_ms"] < 15000
            assert d["validation_report"]["summary"]["hard"] == 0, d["validation_report"]["summary"]
            assert dt_ms < 20000
        finally:
            _delete_rota(auth, rid)


# ---------- 2 & 3. Senior weekend cover + rotation ----------------------
class TestSeniorWeekend:
    def test_weekend_cover_and_rotation(self, auth):
        rota = _create_rota(auth, "2026-04-20", "TEST_addon_senior")
        rid = rota["id"]
        try:
            r = auth.post(f"{BASE_URL}/api/rotas/{rid}/generate", timeout=30)
            assert r.status_code == 200, r.text

            full = auth.get(f"{BASE_URL}/api/rotas/{rid}", timeout=15).json()
            assigns = full["assignments"]
            start = "2026-04-20"
            weekend_dates = []
            for w in range(4):
                sat = date.fromisoformat(start) + timedelta(days=7 * w + 5)
                sun = date.fromisoformat(start) + timedelta(days=7 * w + 6)
                weekend_dates.append((w + 1, sat.isoformat()))
                weekend_dates.append((w + 1, sun.isoformat()))

            # Get rotation from settings
            settings = auth.get(f"{BASE_URL}/api/settings", timeout=15).json()
            rotation = settings.get("settings", settings).get("senior_weekend_rotation", [])
            rot_by_week = {int(x["week_index"]): x["staff_initials"] for x in rotation}

            cover_ok = 0
            rotation_matches = 0
            for wk, d_str in weekend_dates:
                cells_on_day = [a for a in assigns if a["date"] == d_str]
                lm_on = any(a["staff_initials"] == "L.M." and a["shift"] in ("D", "D*") for a in cells_on_day)
                ld_on = any(a["staff_initials"] == "L.D." and a["shift"] in ("D", "D*") for a in cells_on_day)
                if lm_on or ld_on:
                    cover_ok += 1
                # Rotation check: assigned senior OR the other one stepping in
                expected = rot_by_week.get(wk)
                if expected == "L.M." and lm_on:
                    rotation_matches += 1
                elif expected == "L.D." and ld_on:
                    rotation_matches += 1
                elif (expected == "L.M." and ld_on) or (expected == "L.D." and lm_on):
                    # fallback — accept if assigned is on AL/TRN
                    assigned_cell = next((a for a in cells_on_day if a["staff_initials"] == expected), None)
                    if assigned_cell and assigned_cell["shift"] in ("AL", "TRN"):
                        rotation_matches += 1

            assert cover_ok == 8, f"senior weekend cover failed: {cover_ok}/8 weekends covered"
            assert rotation_matches >= 6, f"rotation matches {rotation_matches}/8 — expected >=6"
        finally:
            _delete_rota(auth, rid)


# ---------- 4. Rotation fallback when L.M. on AL week 3 -----------------
class TestRotationFallback:
    def test_lm_al_week3_ld_covers(self, auth):
        rota = _create_rota(auth, "2026-04-20", "TEST_addon_fallback")
        rid = rota["id"]
        week3_dates = [(date.fromisoformat("2026-05-04") + timedelta(days=i)).isoformat() for i in range(7)]
        try:
            # Put L.M. on AL for the whole of week 3
            r = auth.post(
                f"{BASE_URL}/api/leave",
                json={"staff_initials": "L.M.", "dates": week3_dates, "type": "AL"},
                timeout=15,
            )
            assert r.status_code in (200, 201), r.text

            r = auth.post(f"{BASE_URL}/api/rotas/{rid}/generate", timeout=30)
            assert r.status_code == 200, f"generate status {r.status_code}: {r.text}"

            full = auth.get(f"{BASE_URL}/api/rotas/{rid}", timeout=15).json()
            assigns = full["assignments"]
            sat_w3 = "2026-05-09"
            sun_w3 = "2026-05-10"
            for d_str in (sat_w3, sun_w3):
                cells = [a for a in assigns if a["date"] == d_str]
                ld_cover = any(a["staff_initials"] == "L.D." and a["shift"] in ("D", "D*") for a in cells)
                lm_cover = any(a["staff_initials"] == "L.M." and a["shift"] in ("D", "D*") for a in cells)
                assert ld_cover or lm_cover, f"{d_str}: neither LM nor LD on D/D* — cells: {cells}"
                # Confirm L.M. is NOT on D/D* (she's on AL)
                lm_cell = next((a for a in cells if a["staff_initials"] == "L.M."), None)
                assert lm_cell is not None and lm_cell["shift"] == "AL", (
                    f"L.M. should be AL on {d_str}, got {lm_cell}"
                )
                assert ld_cover, f"L.D. should step in on {d_str} since L.M. is AL"
        finally:
            _delete_leave_for(auth, "L.M.", week3_dates)
            _delete_rota(auth, rid)


# ---------- 5 & 6. Per-week contracted hours + non-flexi cap ------------
class TestPerWeekHours:
    def test_per_week_contracted_and_cap(self, auth):
        rota = _create_rota(auth, "2026-04-20", "TEST_addon_perweek")
        rid = rota["id"]
        try:
            r = auth.post(f"{BASE_URL}/api/rotas/{rid}/generate", timeout=30)
            assert r.status_code == 200, r.text

            full = auth.get(f"{BASE_URL}/api/rotas/{rid}", timeout=15).json()
            assigns = full["assignments"]
            staff_list = auth.get(f"{BASE_URL}/api/staff", timeout=15).json()
            targets = {s["initials"]: s.get("target_weekly_hours", 36) for s in staff_list}
            roles = {s["initials"]: s.get("role", "") for s in staff_list}

            hrs = _hours_by_staff_week(assigns, "2026-04-20")
            al_cnt = _count_by_staff_week(assigns, "2026-04-20", {"AL"})
            trn_cnt = _count_by_staff_week(assigns, "2026-04-20", {"TRN"})

            failures_min = []
            failures_cap = []
            for init, tgt in targets.items():
                if init == "J.C." or tgt == 0:
                    continue
                for wk in range(1, 5):
                    h = hrs.get(init, {}).get(wk, 0)
                    al = al_cnt.get(init, {}).get(wk, 0)
                    trn = trn_cnt.get(init, {}).get(wk, 0)
                    effective = h + 12 * al + 8 * trn
                    if effective < tgt - 2:
                        failures_min.append(f"{init} wk{wk}: {effective}h (tgt {tgt}-2={tgt - 2})")
                    # Cap only applies to non-flexi
                    if roles.get(init, "") != "Flexi":
                        if h > tgt + 8:
                            failures_cap.append(f"{init} wk{wk}: {h}h (cap {tgt}+8={tgt + 8})")

            assert not failures_min, "Per-week contracted min failures: " + "; ".join(failures_min)
            assert not failures_cap, "Per-week non-flexi cap failures: " + "; ".join(failures_cap)
        finally:
            _delete_rota(auth, rid)


# ---------- 7. avoid_pair_seniors ---------------------------------------
class TestAvoidPairSeniors:
    def test_pair_days_low(self, auth):
        rota = _create_rota(auth, "2026-04-20", "TEST_addon_pair")
        rid = rota["id"]
        try:
            r = auth.post(f"{BASE_URL}/api/rotas/{rid}/generate", timeout=30)
            assert r.status_code == 200, r.text
            full = auth.get(f"{BASE_URL}/api/rotas/{rid}", timeout=15).json()
            assigns = full["assignments"]
            days = {a["date"] for a in assigns}
            pair_days = 0
            for d_str in days:
                cells = [a for a in assigns if a["date"] == d_str]
                lm_on = any(a["staff_initials"] == "L.M." and a["shift"] in ("D", "D*") for a in cells)
                ld_on = any(a["staff_initials"] == "L.D." and a["shift"] in ("D", "D*") for a in cells)
                if lm_on and ld_on:
                    pair_days += 1
            assert pair_days <= 2, f"avoid_pair_seniors: {pair_days}/28 pair-days (expected <=2)"
        finally:
            _delete_rota(auth, rid)


# ---------- 8. Flexi redistribution bug fix -----------------------------
class TestFlexiRedistribution:
    def test_td_absorbs_da_al_week(self, auth):
        rota = _create_rota(auth, "2026-04-20", "TEST_addon_flexi_redist")
        rid = rota["id"]
        week2_dates = [(date.fromisoformat("2026-04-27") + timedelta(days=i)).isoformat() for i in range(7)]
        try:
            r = auth.post(
                f"{BASE_URL}/api/leave",
                json={"staff_initials": "D.A.", "dates": week2_dates, "type": "AL"},
                timeout=15,
            )
            assert r.status_code in (200, 201), r.text

            r = auth.post(f"{BASE_URL}/api/rotas/{rid}/generate", timeout=30)
            assert r.status_code == 200, f"generate: {r.text}"

            full = auth.get(f"{BASE_URL}/api/rotas/{rid}", timeout=15).json()
            hrs = _hours_by_staff_week(full["assignments"], "2026-04-20")
            td = hrs.get("T.D.", {})
            w1, w2, w3 = td.get(1, 0), td.get(2, 0), td.get(3, 0)
            assert w2 > w1, f"T.D. w2({w2}) should > w1({w1}) when D.A. on AL all week 2"
            assert w2 > w3, f"T.D. w2({w2}) should > w3({w3})"
            assert w2 >= 34, f"T.D. w2({w2}) should be >= 34 (weekly contract)"
        finally:
            _delete_leave_for(auth, "D.A.", week2_dates)
            _delete_rota(auth, rid)


# ---------- 9. GET /api/rules shape -------------------------------------
class TestRulesShape:
    def test_new_rules_present(self, auth):
        r = auth.get(f"{BASE_URL}/api/rules", timeout=15)
        assert r.status_code == 200
        rules = r.json().get("rules") or {}
        assert "senior_weekend_cover" in rules, list(rules.keys())
        swc = rules["senior_weekend_cover"]
        assert swc.get("mode") == "hard", swc
        assert swc.get("immovable") is True, swc

        assert "avoid_pair_seniors" in rules, list(rules.keys())
        aps = rules["avoid_pair_seniors"]
        assert aps.get("mode") == "soft", aps
        assert aps.get("weight") == 40, aps
        assert aps.get("immovable") in (False, None), aps


# ---------- 10. GET /api/settings senior_weekend_rotation ---------------
class TestSettingsRotation:
    def test_rotation_shape(self, auth):
        r = auth.get(f"{BASE_URL}/api/settings", timeout=15)
        assert r.status_code == 200
        body = r.json()
        settings = body.get("settings", body)
        rot = settings.get("senior_weekend_rotation")
        assert isinstance(rot, list) and len(rot) == 4, f"expected list of 4, got {rot}"
        weeks = sorted(int(x["week_index"]) for x in rot)
        assert weeks == [1, 2, 3, 4], weeks
        for x in rot:
            assert x["staff_initials"] in {"L.M.", "L.D."}, x


# ---------- 11. PUT /api/settings rotation round-trip + generate --------
class TestSettingsRotationPutAndGenerate:
    def test_mutate_rotation_and_generate(self, auth):
        cur = auth.get(f"{BASE_URL}/api/settings", timeout=15).json()
        settings = cur.get("settings", cur)
        original = [dict(x) for x in settings.get("senior_weekend_rotation", [])]
        mutated = [
            {"week_index": 1, "staff_initials": "L.D."},
            {"week_index": 2, "staff_initials": "L.M."},
            {"week_index": 3, "staff_initials": "L.D."},
            {"week_index": 4, "staff_initials": "L.M."},
        ]
        rid = None
        try:
            body = dict(settings)
            body["senior_weekend_rotation"] = mutated
            r = auth.put(f"{BASE_URL}/api/settings", json=body, timeout=15)
            assert r.status_code == 200, r.text

            back = auth.get(f"{BASE_URL}/api/settings", timeout=15).json()
            back_settings = back.get("settings", back)
            back_rot = {int(x["week_index"]): x["staff_initials"] for x in back_settings["senior_weekend_rotation"]}
            assert back_rot == {1: "L.D.", 2: "L.M.", 3: "L.D.", 4: "L.M."}, back_rot

            # Generate and verify rotation respected >=6/8
            rota = _create_rota(auth, "2026-04-20", "TEST_addon_rot_mut")
            rid = rota["id"]
            r = auth.post(f"{BASE_URL}/api/rotas/{rid}/generate", timeout=30)
            assert r.status_code == 200, r.text
            full = auth.get(f"{BASE_URL}/api/rotas/{rid}", timeout=15).json()
            assigns = full["assignments"]
            matches = 0
            for w in range(4):
                wk = w + 1
                for offset in (5, 6):
                    d_str = (date.fromisoformat("2026-04-20") + timedelta(days=7 * w + offset)).isoformat()
                    cells = [a for a in assigns if a["date"] == d_str]
                    expected = back_rot[wk]
                    assigned = next((a for a in cells if a["staff_initials"] == expected), None)
                    if assigned and assigned["shift"] in ("D", "D*"):
                        matches += 1
                    else:
                        # fallback acceptable if other senior covers + assigned on AL/TRN
                        other = "L.D." if expected == "L.M." else "L.M."
                        other_cell = next((a for a in cells if a["staff_initials"] == other), None)
                        if other_cell and other_cell["shift"] in ("D", "D*") and assigned and assigned["shift"] in ("AL", "TRN"):
                            matches += 1
            assert matches >= 6, f"mutated rotation matches {matches}/8"
        finally:
            if rid:
                _delete_rota(auth, rid)
            # restore original rotation
            body = dict(settings)
            body["senior_weekend_rotation"] = original
            auth.put(f"{BASE_URL}/api/settings", json=body, timeout=15)
