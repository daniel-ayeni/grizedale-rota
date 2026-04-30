"""Phase 3 backend tests — POST /api/rotas/{id}/generate + Overtime rule.

Covers:
  - Fresh draft rota generates 224 assignments, 0 hard violations
  - Locked cells preserved through /generate
  - AL/TRN cells preserved through /generate
  - Over-constrained → HTTP 422 + INFEASIBLE
  - Flexi auto-detect (D.A. + T.D.) absorb overtime
  - GET /api/rules has applies_to_role='Flexi', no preferred_staff_initials
  - PUT /api/rules round-trips applies_to_role + staff_initials_override
"""
import os
import time
import pytest
import requests

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


def _create_rota(auth, start_date, title):
    r = auth.post(f"{BASE_URL}/api/rotas", json={"start_date": start_date, "weeks": 4, "title": title}, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _delete_rota(auth, rid):
    auth.delete(f"{BASE_URL}/api/rotas/{rid}", timeout=15)


def _delete_leave_for(auth, staff, dates):
    """Remove any test leave for given (staff, date) pairs."""
    r = auth.get(f"{BASE_URL}/api/leave", params={"staff": staff}, timeout=15).json()
    for L in r:
        if L.get("date") in dates:
            auth.delete(f"{BASE_URL}/api/leave/{L['id']}", timeout=15)


# ---------- 1. Fresh /generate ------------------------------------------
class TestGenerateFresh:
    def test_generate_fresh_draft(self, auth):
        rota = _create_rota(auth, "2026-04-20", "TEST_phase3_fresh")
        rid = rota["id"]
        try:
            t0 = time.time()
            r = auth.post(f"{BASE_URL}/api/rotas/{rid}/generate", timeout=30)
            dt_ms = (time.time() - t0) * 1000
            assert r.status_code == 200, f"status {r.status_code}: {r.text}"
            d = r.json()
            assert d["success"] is True
            assert d["assignments_count"] == 224, f"expected 224, got {d['assignments_count']}"
            assert d["validation_report"]["summary"]["hard"] == 0, d["validation_report"]["summary"]
            assert d["locked_preserved"] >= 0
            assert d["leave_preserved"] >= 0
            assert d["solve_time_ms"] < 15000
            assert dt_ms < 20000
            assert d["solver_status"] in {"OPTIMAL", "FEASIBLE"}
        finally:
            _delete_rota(auth, rid)


# ---------- 2. Locked preservation --------------------------------------
class TestLockedPreserved:
    def test_locked_cell_preserved(self, auth):
        rota = _create_rota(auth, "2026-04-20", "TEST_phase3_locked")
        rid = rota["id"]
        try:
            # Lock J.C. on 2026-04-20 to OFF
            r = auth.patch(
                f"{BASE_URL}/api/rotas/{rid}/cell",
                json={"date": "2026-04-20", "staff_initials": "J.C.", "shift": "OFF", "locked": True},
                timeout=15,
            )
            assert r.status_code == 200, r.text

            r = auth.post(f"{BASE_URL}/api/rotas/{rid}/generate", timeout=30)
            assert r.status_code == 200, r.text
            assert r.json()["locked_preserved"] >= 1

            full = auth.get(f"{BASE_URL}/api/rotas/{rid}", timeout=15).json()
            cell = next(
                (a for a in full["assignments"] if a["date"] == "2026-04-20" and a["staff_initials"] == "J.C."),
                None,
            )
            assert cell is not None, "J.C. cell missing on 2026-04-20"
            assert cell["shift"] == "OFF", f"expected OFF, got {cell['shift']}"
            assert cell["locked"] is True
        finally:
            _delete_rota(auth, rid)


# ---------- 3. AL/TRN preservation --------------------------------------
class TestLeavePreserved:
    def test_al_preserved(self, auth):
        rota = _create_rota(auth, "2026-08-03", "TEST_phase3_al")
        rid = rota["id"]
        try:
            r = auth.post(
                f"{BASE_URL}/api/leave",
                json={"staff_initials": "A.A.", "dates": ["2026-08-03"], "type": "AL"},
                timeout=15,
            )
            assert r.status_code in (200, 201), r.text

            r = auth.post(f"{BASE_URL}/api/rotas/{rid}/generate", timeout=30)
            assert r.status_code == 200, r.text
            assert r.json()["leave_preserved"] >= 1

            full = auth.get(f"{BASE_URL}/api/rotas/{rid}", timeout=15).json()
            cell = next(
                (a for a in full["assignments"] if a["date"] == "2026-08-03" and a["staff_initials"] == "A.A."),
                None,
            )
            assert cell is not None
            assert cell["shift"] == "AL", f"expected AL got {cell['shift']}"
        finally:
            _delete_leave_for(auth, "A.A.", ["2026-08-03"])
            _delete_rota(auth, rid)


# ---------- 4. Over-constrained → 422 -----------------------------------
class TestInfeasible:
    def test_overconstrained_returns_422(self, auth):
        rota = _create_rota(auth, "2026-09-07", "TEST_phase3_infeasible")
        rid = rota["id"]
        staff_off = ["J.C.", "L.M.", "L.D.", "D.A.", "T.D.", "C.E."]
        try:
            for s in staff_off:
                r = auth.post(
                    f"{BASE_URL}/api/leave",
                    json={"staff_initials": s, "dates": ["2026-09-07"], "type": "AL"},
                    timeout=15,
                )
                assert r.status_code in (200, 201), f"{s}: {r.text}"

            r = auth.post(f"{BASE_URL}/api/rotas/{rid}/generate", timeout=30)
            assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"
            d = r.json()
            assert d["success"] is False
            assert "blocking_constraints" in d
            assert isinstance(d["blocking_constraints"], list)
            assert d.get("solver_status") == "INFEASIBLE"
        finally:
            for s in staff_off:
                _delete_leave_for(auth, s, ["2026-09-07"])
            _delete_rota(auth, rid)


# ---------- 5. Flexi overtime absorption --------------------------------
class TestFlexiOvertime:
    def test_da_and_td_absorb_overtime(self, auth):
        # Use a fresh rota so no leftover state
        rota = _create_rota(auth, "2026-04-20", "TEST_phase3_flexi")
        rid = rota["id"]
        try:
            r = auth.post(f"{BASE_URL}/api/rotas/{rid}/generate", timeout=30)
            assert r.status_code == 200, r.text

            full = auth.get(f"{BASE_URL}/api/rotas/{rid}", timeout=15).json()
            staff_list = auth.get(f"{BASE_URL}/api/staff", timeout=15).json()
            targets = {s["initials"]: s.get("target_weekly_hours", 36) for s in staff_list}

            hours_by_staff: dict[str, float] = {}
            for a in full["assignments"]:
                hours_by_staff[a["staff_initials"]] = hours_by_staff.get(a["staff_initials"], 0) + SHIFT_HOURS.get(
                    a["shift"], 0
                )

            for init in ("D.A.", "T.D."):
                target_4w = targets.get(init, 36) * 4
                actual = hours_by_staff.get(init, 0)
                assert actual > target_4w, (
                    f"{init} expected actual ({actual}) > target_4w ({target_4w}) — flexi should absorb overtime"
                )
        finally:
            _delete_rota(auth, rid)


# ---------- 6. GET /api/rules has applies_to_role -----------------------
class TestRulesShape:
    def test_rules_overtime_uses_applies_to_role(self, auth):
        r = auth.get(f"{BASE_URL}/api/rules", timeout=15)
        assert r.status_code == 200, r.text
        rules = r.json().get("rules") or {}
        assert "overtime_prefer_flexi" in rules, list(rules.keys())
        params = rules["overtime_prefer_flexi"].get("params", {})
        assert params.get("applies_to_role") == "Flexi", f"expected applies_to_role=Flexi, got {params}"
        assert "preferred_staff_initials" not in params, (
            f"legacy preferred_staff_initials should not be present: {params}"
        )


# ---------- 7. PUT /api/rules round-trip --------------------------------
class TestRulesRoundTrip:
    def test_put_rules_round_trip(self, auth):
        # Read existing rules
        cur = auth.get(f"{BASE_URL}/api/rules", timeout=15).json()
        rules = cur.get("rules") or {}
        original = rules.get("overtime_prefer_flexi", {}).copy()

        new_block = {
            "mode": "soft",
            "weight": 15,
            "params": {
                "applies_to_role": "Flexi",
                "staff_initials_override": ["D.A."],
                "weekly_cap": 48,
            },
        }
        rules["overtime_prefer_flexi"] = new_block
        try:
            r = auth.put(f"{BASE_URL}/api/rules", json={"rules": rules}, timeout=15)
            assert r.status_code == 200, r.text

            back = auth.get(f"{BASE_URL}/api/rules", timeout=15).json()["rules"]["overtime_prefer_flexi"]
            assert back["mode"] == "soft"
            assert back["weight"] == 15
            assert back["params"]["applies_to_role"] == "Flexi"
            assert back["params"]["staff_initials_override"] == ["D.A."]
            assert back["params"]["weekly_cap"] == 48
        finally:
            # restore
            if original:
                rules["overtime_prefer_flexi"] = original
                auth.put(f"{BASE_URL}/api/rules", json={"rules": rules}, timeout=15)
