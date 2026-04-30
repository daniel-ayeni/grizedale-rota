"""Phase 2 backend API regression tests for Grizedale Rota Builder.

Covers:
- Rotas list/create/get/copy-from-previous/cell PATCH (incl. lock)/validate
- Leave create/list/delete
- Requests create/patch (auto-leave on OFF accept)/bulk
- Request tokens + public link (no auth) flow + revoke
- Overtime rule (overtime_prefer_flexi) presence + behaviour in solver
- C.E. first_aider migration
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://care-rota-engine.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "manager@grizedale.local"
ADMIN_PASSWORD = "ChangeMe123!"


# ---------- Fixtures ----------
@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_headers(session):
    r = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


# Track resources for cleanup
_created = {"rotas": [], "leave": [], "requests": [], "tokens": []}


@pytest.fixture(scope="session", autouse=True)
def cleanup(session, admin_headers):
    yield
    # Cleanup created resources
    for rid in _created["rotas"]:
        session.delete(f"{API}/rotas/{rid}", headers=admin_headers)
    for lid in _created["leave"]:
        session.delete(f"{API}/leave/{lid}", headers=admin_headers)
    for tid in _created["tokens"]:
        session.post(f"{API}/request-tokens/{tid}/revoke", headers=admin_headers)


# ---------- Health/auth quickcheck ----------
class TestHealthAuth:
    def test_health(self, session):
        r = session.get(f"{API}/health")
        assert r.status_code == 200

    def test_docs(self, session):
        r = session.get(f"{API}/docs")
        assert r.status_code == 200

    def test_auth_required(self, session):
        r = session.get(f"{API}/rotas")
        assert r.status_code == 401


# ---------- Rotas ----------
class TestRotas:
    def test_list_seed_rota(self, session, admin_headers):
        r = session.get(f"{API}/rotas", headers=admin_headers)
        assert r.status_code == 200
        rotas = r.json()
        assert len(rotas) >= 1
        # Find seeded prior rota
        seed = next((x for x in rotas if x.get("start_date") == "2026-03-23"), None)
        assert seed is not None, "Seeded prior rota with start_date 2026-03-23 not found"
        assert seed.get("status") == "published"

    def test_create_rota(self, session, admin_headers):
        r = session.post(
            f"{API}/rotas",
            json={"start_date": "2026-04-20", "weeks": 4, "title": "TEST_phase2_new_rota"},
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        rota = r.json()
        assert "id" in rota
        assert rota["start_date"] == "2026-04-20"
        assert rota["status"] == "draft"
        _created["rotas"].append(rota["id"])

    def test_get_rota_includes_validation(self, session, admin_headers):
        # Use seeded rota
        rotas = session.get(f"{API}/rotas", headers=admin_headers).json()
        seed = next(x for x in rotas if x.get("start_date") == "2026-03-23")
        r = session.get(f"{API}/rotas/{seed['id']}", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert "assignments" in body
        assert "on_call" in body
        assert "validation_report" in body
        report = body["validation_report"]
        assert "violations" in report
        assert "summary" in report
        assert {"total", "hard", "soft"}.issubset(report["summary"].keys())


# ---------- Copy-from-previous ----------
class TestCopyFromPrevious:
    @pytest.fixture(scope="class")
    def new_rota_id(self, session, admin_headers):
        # create empty rota
        r = session.post(
            f"{API}/rotas",
            json={"start_date": "2026-04-20", "weeks": 4, "title": "TEST_copy_target"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        rid = r.json()["id"]
        _created["rotas"].append(rid)
        return rid

    def test_copy_from_previous(self, session, admin_headers, new_rota_id):
        r = session.post(
            f"{API}/rotas/{new_rota_id}/copy-from-previous", headers=admin_headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("success") is True
        assert body["copied_from"]["start_date"] == "2026-03-23"
        # 8 staff x 28 days = 224 (allow tolerance for leave overlay)
        assert body["assignments_count"] >= 200
        report = body.get("validation_report", {})
        summary = report.get("summary", {})
        assert {"total", "hard", "soft"}.issubset(summary.keys())

        # Verify cells were actually copied
        rota = session.get(f"{API}/rotas/{new_rota_id}", headers=admin_headers).json()
        non_blank = [c for c in rota.get("assignments", []) if c.get("shift")]
        assert len(non_blank) > 0, "No non-blank cells after copy"


# ---------- Cell PATCH + lock ----------
class TestCellPatch:
    @pytest.fixture(scope="class")
    def rota_id(self, session, admin_headers):
        r = session.post(
            f"{API}/rotas",
            json={"start_date": "2026-04-20", "weeks": 4, "title": "TEST_cell_patch"},
            headers=admin_headers,
        )
        rid = r.json()["id"]
        _created["rotas"].append(rid)
        # populate via copy-from-previous so capability rules can fire
        session.post(f"{API}/rotas/{rid}/copy-from-previous", headers=admin_headers)
        return rid

    def test_cell_patch_returns_validation(self, session, admin_headers, rota_id):
        r = session.patch(
            f"{API}/rotas/{rota_id}/cell",
            json={"date": "2026-04-20", "staff_initials": "L.M.", "shift": "D"},
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "cell" in body and "validation_report" in body
        assert body["cell"]["shift"] == "D"

    def test_capability_violation_for_ld_nights(self, session, admin_headers, rota_id):
        # L.D. has can_do_nights=false (per test_phase1 fixtures)
        r = session.patch(
            f"{API}/rotas/{rota_id}/cell",
            json={"date": "2026-04-21", "staff_initials": "L.D.", "shift": "N"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        violations = r.json()["validation_report"]["violations"]
        cap_viols = [v for v in violations if v.get("rule_id") == "capability_flags"]
        assert len(cap_viols) > 0, f"Expected capability_flags violation, got: {[v.get('rule_id') for v in violations]}"

    def test_lock_semantics(self, session, admin_headers, rota_id):
        date = "2026-04-22"
        staff = "T.D."
        # First set + lock
        r = session.patch(
            f"{API}/rotas/{rota_id}/cell",
            json={"date": date, "staff_initials": staff, "shift": "D", "locked": True},
            headers=admin_headers,
        )
        assert r.status_code == 200
        assert r.json()["cell"]["locked"] is True

        # Try to change without unlocking → 409
        r2 = session.patch(
            f"{API}/rotas/{rota_id}/cell",
            json={"date": date, "staff_initials": staff, "shift": "N"},
            headers=admin_headers,
        )
        assert r2.status_code == 409, f"Expected 409, got {r2.status_code} {r2.text}"

        # Unlock + change → success
        r3 = session.patch(
            f"{API}/rotas/{rota_id}/cell",
            json={"date": date, "staff_initials": staff, "shift": "OFF", "locked": False},
            headers=admin_headers,
        )
        assert r3.status_code == 200
        assert r3.json()["cell"]["shift"] == "OFF"
        assert r3.json()["cell"]["locked"] is False


# ---------- Validate ----------
class TestValidate:
    def test_validate_endpoint(self, session, admin_headers):
        rotas = session.get(f"{API}/rotas", headers=admin_headers).json()
        seed = next(x for x in rotas if x.get("start_date") == "2026-03-23")
        r = session.post(f"{API}/rotas/{seed['id']}/validate", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert "violations" in body and "summary" in body
        # rule_ids should come from definitions
        valid_rule_ids = {
            "day_cover", "night_cover", "no_n_to_d", "no_dstar_to_dstar",
            "med_competent_required", "first_aider_required", "no_male_pair_alone",
            "manager_no_shifts", "contracted_hours_min", "capability_flags",
            "overtime_prefer_flexi",
        }
        for v in body["violations"]:
            assert v.get("rule_id") in valid_rule_ids, f"Unknown rule_id: {v.get('rule_id')}"


# ---------- Leave ----------
class TestLeave:
    def test_create_list_delete(self, session, admin_headers):
        d1 = "2026-05-10"
        d2 = "2026-05-11"
        r = session.post(
            f"{API}/leave",
            json={"staff_initials": "T.D.", "dates": [d1, d2], "type": "AL"},
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        created = r.json()
        assert len(created) == 2
        for c in created:
            _created["leave"].append(c["id"])

        # GET filtered
        r2 = session.get(
            f"{API}/leave",
            params={"from": d1, "to": d2, "staff": "T.D."},
            headers=admin_headers,
        )
        assert r2.status_code == 200
        leaves = r2.json()
        dates = {leave["date"] for leave in leaves if leave["staff_initials"] == "T.D."}
        assert d1 in dates and d2 in dates

        # DELETE one
        first_id = created[0]["id"]
        r3 = session.delete(f"{API}/leave/{first_id}", headers=admin_headers)
        assert r3.status_code == 200
        _created["leave"].remove(first_id)


# ---------- Requests ----------
class TestRequests:
    def test_create_accept_off_creates_leave(self, session, admin_headers):
        target_date = "2026-06-15"
        # create
        r = session.post(
            f"{API}/requests",
            json={"staff_initials": "A.A.", "date": target_date, "shift_preference": "OFF",
                  "notes": "TEST_phase2"},
            headers=admin_headers,
        )
        assert r.status_code == 200
        req_id = r.json()["id"]
        _created["requests"].append(req_id)

        # accept
        r2 = session.patch(
            f"{API}/requests/{req_id}",
            json={"status": "accepted"},
            headers=admin_headers,
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "accepted"

        # verify auto-created OFF_REQ leave entry
        r3 = session.get(
            f"{API}/leave",
            params={"from": target_date, "to": target_date, "staff": "A.A."},
            headers=admin_headers,
        )
        assert r3.status_code == 200
        off_req = [leave for leave in r3.json() if leave.get("type") == "OFF_REQ"]
        assert len(off_req) >= 1, f"Expected OFF_REQ entry for A.A. on {target_date}: {r3.json()}"
        for leave in off_req:
            _created["leave"].append(leave["id"])

    def test_bulk_reject(self, session, admin_headers):
        ids = []
        for i in range(2):
            r = session.post(
                f"{API}/requests",
                json={"staff_initials": "T.D.", "date": f"2026-07-1{i}",
                      "shift_preference": "OFF", "notes": "TEST_bulk"},
                headers=admin_headers,
            )
            ids.append(r.json()["id"])
            _created["requests"].append(r.json()["id"])

        r2 = session.post(
            f"{API}/requests/bulk",
            json={"ids": ids, "status": "rejected"},
            headers=admin_headers,
        )
        assert r2.status_code == 200
        body = r2.json()
        assert len(body["updated"]) == 2
        for u in body["updated"]:
            assert u["status"] == "rejected"


# ---------- Request tokens + public link ----------
class TestRequestTokens:
    def test_create_token_get_submit_revoke(self, session, admin_headers):
        # Create token
        r = session.post(
            f"{API}/request-tokens",
            json={"staff_initials": "L.M.", "expires_in_days": 30},
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        token = body["token"]
        token_id = body["id"]
        assert body["url"].startswith("/r/")
        _created["tokens"].append(token_id)

        # Public GET (no auth)
        public_session = requests.Session()
        r2 = public_session.get(f"{API}/public/request-link/{token}")
        assert r2.status_code == 200
        public_body = r2.json()
        assert public_body["staff_initials"] == "L.M."
        assert "name" in public_body
        assert "current_rota_window" in public_body
        assert "from" in public_body["current_rota_window"]
        assert "to" in public_body["current_rota_window"]

        # Public submit
        r3 = public_session.post(
            f"{API}/public/request-link/{token}/submit",
            json={"requests": [{"date": "2026-08-01", "shift_preference": "OFF",
                                "notes": "TEST_publiclink"}]},
        )
        assert r3.status_code == 200
        assert r3.json()["created"] == 1

        # Verify it appears in pending with source=staff_link
        r4 = session.get(f"{API}/requests", params={"status": "pending"}, headers=admin_headers)
        assert r4.status_code == 200
        matches = [
            req for req in r4.json()
            if req.get("staff_initials") == "L.M."
            and req.get("source") == "staff_link"
            and req.get("date") == "2026-08-01"
        ]
        assert len(matches) >= 1
        for m in matches:
            _created["requests"].append(m["id"])

        # Revoke
        r5 = session.post(f"{API}/request-tokens/{token_id}/revoke", headers=admin_headers)
        assert r5.status_code == 200

        # Public GET after revoke → 410
        r6 = public_session.get(f"{API}/public/request-link/{token}")
        assert r6.status_code == 410


# ---------- Overtime rule ----------
class TestOvertimeRule:
    def test_overtime_prefer_flexi_rule_present(self, session, admin_headers):
        r = session.get(f"{API}/rules", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        rules = body.get("rules", body)
        assert "overtime_prefer_flexi" in rules, f"Rule missing. Keys: {list(rules.keys())}"
        rule = rules["overtime_prefer_flexi"]
        # Could be string mode or dict with mode/weight/params
        if isinstance(rule, dict):
            assert rule.get("mode") == "soft"
            assert rule.get("weight") == 15
            params = rule.get("params", {})
            assert params.get("preferred_staff_initials") == "D.A."
            assert params.get("weekly_cap") == 48
        else:
            # string-only mode — params live in rule_definitions; just verify it's soft
            assert rule == "soft"

    def test_solver_da_gets_extra_hours_capped_at_48(self, session, admin_headers):
        t0 = time.time()
        r = session.post(f"{API}/solver/generate", json={}, headers=admin_headers)
        elapsed_ms = (time.time() - t0) * 1000
        assert r.status_code == 200, r.text
        assert elapsed_ms < 30000, f"Solve took {elapsed_ms:.0f}ms"
        body = r.json()
        assert body.get("success") is True

        # Extract days (rota may be {days:[...]}, list, or top-level days)
        rota = body.get("rota")
        if isinstance(rota, dict):
            days = rota.get("days") or []
        elif isinstance(rota, list):
            days = rota
        else:
            days = body.get("days") or []
        assert len(days) == 28

        # Compute D.A. hours per week
        # Approx hours: D=12, D*=14, N=12, *=0
        shift_hours = {"D": 12, "D*": 14, "N": 12, "*": 0}
        weekly_hours = [0, 0, 0, 0]
        for i, day in enumerate(days):
            week_idx = i // 7
            assignments = day.get("assignments")
            if isinstance(assignments, dict):
                shift = assignments.get("D.A.")
            elif isinstance(assignments, list):
                shift = next((a.get("shift") for a in assignments
                              if a.get("staff") == "D.A." or a.get("staff_initials") == "D.A."), None)
            else:
                shift = None
            weekly_hours[week_idx] += shift_hours.get(shift, 0)

        # Verify cap
        for w, h in enumerate(weekly_hours):
            assert h <= 48, f"D.A. week {w} = {h}h exceeds 48h cap"

        # Verify D.A. averages MORE than her contracted 28h (bonus active)
        avg = sum(weekly_hours) / 4
        assert avg > 28, f"D.A. avg {avg}h/wk not exceeding contracted 28h (overtime bonus inactive)"


# ---------- C.E. migration ----------
class TestCEFirstAider:
    def test_ce_first_aider_true(self, session, admin_headers):
        r = session.get(f"{API}/staff", headers=admin_headers)
        assert r.status_code == 200
        ce = next((s for s in r.json() if s["initials"] == "C.E."), None)
        assert ce is not None
        assert ce.get("first_aider") is True, f"C.E. first_aider should be True: {ce}"
