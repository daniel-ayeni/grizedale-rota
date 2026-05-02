"""Phase test: De-hardcoded solver + role-flag chips + override-conflict dialog.

Covers every item in the review_request for iteration 7.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

ADMIN_EMAIL = "manager@grizedale.local"
ADMIN_PASSWORD = "ChangeMe123!"


@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data and isinstance(data["token"], str) and len(data["token"]) > 10
    assert data["user"]["email"] == ADMIN_EMAIL
    return data["token"]


@pytest.fixture(scope="session")
def client(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}",
                      "Content-Type": "application/json"})
    return s


# =====================================================================
# 1. Solver de-hardcoding regression
# =====================================================================
class TestSolverDehardcoded:
    def test_solver_generate_default_seed(self, client):
        t0 = time.time()
        r = client.post(f"{BASE_URL}/api/solver/generate", json={}, timeout=30)
        elapsed = time.time() - t0
        assert r.status_code == 200, f"solver failed: {r.status_code} {r.text[:300]}"
        data = r.json()
        assert data.get("success") is True, f"expected success=True, got {data}"
        assert elapsed < 15, f"solver too slow: {elapsed:.1f}s"

    def test_no_hardcoded_initials_in_solver_files(self):
        import re, pathlib
        pat = re.compile(r'"(J\.C\.|L\.M\.|L\.D\.|D\.A\.|T\.D\.|C\.E\.|A\.A\.|J\.R\.)')
        hits = []
        for f in ["rota_solver.py", "rota_validator.py", "rule_definitions.py"]:
            p = pathlib.Path("/app/backend/solver") / f
            for i, line in enumerate(p.read_text().splitlines(), 1):
                if pat.search(line):
                    hits.append(f"{f}:{i}: {line.strip()}")
        assert not hits, "Found hardcoded initials:\n" + "\n".join(hits)


# =====================================================================
# 2. Staff endpoints — flags + references
# =====================================================================
class TestStaffFlags:
    def test_staff_list_returns_eight_with_flags(self, client):
        r = client.get(f"{BASE_URL}/api/staff", timeout=10)
        assert r.status_code == 200
        staff = r.json()
        assert isinstance(staff, list) and len(staff) == 8, f"expected 8, got {len(staff)}"
        by = {s["initials"]: s for s in staff}
        # Required initials present
        for init in ["J.C.", "L.M.", "L.D.", "D.A.", "T.D.", "C.E.", "A.A.", "J.R."]:
            assert init in by, f"missing {init}"
            for flag in ["is_manager", "is_deputy", "is_senior", "is_flexi", "is_night"]:
                assert flag in by[init], f"{init} missing flag {flag}"
        # Specific assertions
        assert by["J.C."]["is_manager"] is True
        assert by["L.M."]["is_deputy"] is True
        assert by["L.M."]["is_senior"] is True
        assert by["L.D."]["is_senior"] is True
        assert by["D.A."]["is_flexi"] is True
        assert by["T.D."]["is_flexi"] is True
        assert by["C.E."]["is_night"] is True
        assert by["A.A."]["is_night"] is True
        assert by["J.R."]["is_night"] is True

    def test_staff_put_toggles_flag_and_persists(self, client):
        r = client.get(f"{BASE_URL}/api/staff", timeout=10)
        staff = [s for s in r.json() if s["initials"] == "A.A."][0]
        sid = staff["id"]
        original = bool(staff.get("is_senior", False))
        try:
            # toggle
            r2 = client.put(f"{BASE_URL}/api/staff/{sid}",
                            json={"is_senior": not original}, timeout=10)
            assert r2.status_code == 200, r2.text
            assert r2.json().get("is_senior") == (not original)
            # verify via GET
            r3 = client.get(f"{BASE_URL}/api/staff/{sid}", timeout=10)
            assert r3.status_code == 200
            assert r3.json().get("is_senior") == (not original)
        finally:
            client.put(f"{BASE_URL}/api/staff/{sid}",
                       json={"is_senior": original}, timeout=10)

    def test_staff_references_endpoint(self, client):
        staff = client.get(f"{BASE_URL}/api/staff", timeout=10).json()
        lm = [s for s in staff if s["initials"] == "L.M."][0]
        r = client.get(f"{BASE_URL}/api/staff/{lm['id']}/references", timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        for key in ["leave_count", "assignments_count", "requests_count",
                    "active_tokens_count", "rule_references"]:
            assert key in data, f"missing {key}"
        assert isinstance(data["rule_references"], list)
        for rr in data["rule_references"]:
            assert "rule_id" in rr and "mode" in rr


# =====================================================================
# 3. Override conflict flow — /api/requests PATCH
# =====================================================================
@pytest.fixture
def conflict_scenario(client):
    """Create a DA AL + a TD pending OFF request on the same date.
    Cleans up both after the test.
    """
    date_str = "2026-07-13"  # Monday in a clean range
    created = {"leave_id": None, "req_id": None}

    # 1. Create D.A. AL
    r = client.post(f"{BASE_URL}/api/leave",
                    json={"staff_initials": "D.A.", "dates": [date_str],
                          "type": "AL", "notes": "TEST conflict scenario"},
                    timeout=10)
    assert r.status_code in (200, 201), f"leave create: {r.status_code} {r.text}"
    body = r.json()
    # endpoint may return {created:[...]} or a list; capture an id if present
    if isinstance(body, dict) and body.get("created"):
        created["leave_id"] = body["created"][0].get("id")
    elif isinstance(body, list) and body:
        created["leave_id"] = body[0].get("id")
    else:
        created["leave_id"] = body.get("id") if isinstance(body, dict) else None
    created["date"] = date_str
    created["staff"] = "D.A."

    # 2. Create T.D. pending OFF request on same date
    r = client.post(f"{BASE_URL}/api/requests",
                    json={"staff_initials": "T.D.", "date": date_str,
                          "shift_preference": "OFF",
                          "notes": "TEST override flow",
                          "status": "pending"},
                    timeout=10)
    assert r.status_code in (200, 201), f"request create: {r.status_code} {r.text}"
    created["req_id"] = r.json().get("id")

    yield {"date": date_str, **created}

    # Cleanup
    if created["req_id"]:
        try:
            client.patch(f"{BASE_URL}/api/requests/{created['req_id']}",
                         json={"status": "rejected",
                               "resolution_note": "TEST cleanup"}, timeout=10)
            client.delete(f"{BASE_URL}/api/requests/{created['req_id']}", timeout=10)
        except Exception:
            pass
    if created["leave_id"]:
        try:
            client.delete(f"{BASE_URL}/api/leave/{created['leave_id']}", timeout=10)
        except Exception:
            pass
    else:
        # fallback: delete all TEST leave on that date for D.A.
        try:
            leaves = client.get(f"{BASE_URL}/api/leave",
                                params={"staff_initials": "D.A."},
                                timeout=10).json()
            for lv in (leaves if isinstance(leaves, list) else []):
                if lv.get("date") == date_str and "TEST" in (lv.get("notes") or ""):
                    client.delete(f"{BASE_URL}/api/leave/{lv['id']}", timeout=10)
        except Exception:
            pass
    # Also clean any OFF_REQ leave created by an accepted-override T.D. request
    try:
        leaves = client.get(f"{BASE_URL}/api/leave",
                            params={"staff_initials": "T.D."},
                            timeout=10).json()
        for lv in (leaves if isinstance(leaves, list) else []):
            if lv.get("date") == date_str and lv.get("type") == "OFF_REQ":
                client.delete(f"{BASE_URL}/api/leave/{lv['id']}", timeout=10)
    except Exception:
        pass


class TestOverrideConflict:
    def test_patch_accept_conflict_returns_409(self, client, conflict_scenario):
        rid = conflict_scenario["req_id"]
        r = client.patch(f"{BASE_URL}/api/requests/{rid}",
                         json={"status": "accepted"}, timeout=10)
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"
        detail = r.json().get("detail", {})
        if isinstance(detail, dict):
            assert detail.get("error") == "conflict"
            assert "reason" in detail
            assert "existing_leave" in detail

    def test_override_without_reason_returns_422(self, client, conflict_scenario):
        rid = conflict_scenario["req_id"]
        r = client.patch(f"{BASE_URL}/api/requests/{rid}",
                         json={"status": "accepted", "override_conflict": True},
                         timeout=10)
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"

    def test_override_with_reason_succeeds_and_audits(self, client, conflict_scenario):
        rid = conflict_scenario["req_id"]
        reason = "TEST override — both Flexi off by mgr discretion"
        r = client.patch(f"{BASE_URL}/api/requests/{rid}",
                         json={"status": "accepted",
                               "override_conflict": True,
                               "override_reason": reason},
                         timeout=10)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("status") == "accepted"

        # Audit log should have an override_conflict entry
        r2 = client.get(f"{BASE_URL}/api/audit-log?action=override_conflict",
                        timeout=10)
        assert r2.status_code == 200, r2.text
        rows = r2.json()
        assert isinstance(rows, list) and len(rows) > 0
        # reverse-chron: latest first
        ts_list = [row.get("timestamp") for row in rows if row.get("timestamp")]
        assert ts_list == sorted(ts_list, reverse=True), "audit rows not reverse-chron"
        # Latest row matches our reason + actor
        top = rows[0]
        assert top.get("actor_email") == ADMIN_EMAIL
        assert top.get("action") == "override_conflict"
        details = top.get("details") or {}
        assert reason in (details.get("reason") or "")
        assert details.get("request_id") == rid


# =====================================================================
# 4. Bulk accept with mixed conflicts
# =====================================================================
class TestBulkAccept:
    def test_bulk_skip_conflicts(self, client):
        import random
        # Use random future dates to avoid leftover OFF_REQ leave from prior runs
        day_a = random.randint(1, 14)
        day_b = day_a + 1
        clean_date = f"2026-09-{day_a:02d}"
        clash_date = f"2026-09-{day_b:02d}"
        leave_id = None
        req_clean = None
        req_clash = None
        try:
            # Setup: DA AL on clash_date
            r = client.post(f"{BASE_URL}/api/leave",
                            json={"staff_initials": "D.A.", "dates": [clash_date],
                                  "type": "AL", "notes": "TEST bulk"}, timeout=10)
            assert r.status_code in (200, 201)
            body = r.json()
            if isinstance(body, dict) and body.get("created"):
                leave_id = body["created"][0].get("id")
            elif isinstance(body, list) and body:
                leave_id = body[0].get("id")
            elif isinstance(body, dict):
                leave_id = body.get("id")

            # Create two pending requests
            r1 = client.post(f"{BASE_URL}/api/requests",
                             json={"staff_initials": "A.A.",
                                   "date": clean_date,
                                   "shift_preference": "OFF",
                                   "status": "pending",
                                   "notes": "TEST clean"}, timeout=10)
            assert r1.status_code in (200, 201), r1.text
            req_clean = r1.json()["id"]
            r2 = client.post(f"{BASE_URL}/api/requests",
                             json={"staff_initials": "T.D.",
                                   "date": clash_date,
                                   "shift_preference": "OFF",
                                   "status": "pending",
                                   "notes": "TEST clash"}, timeout=10)
            assert r2.status_code in (200, 201), r2.text
            req_clash = r2.json()["id"]

            # bulk accept without override
            r = client.post(f"{BASE_URL}/api/requests/bulk",
                            json={"ids": [req_clean, req_clash],
                                  "status": "accepted"}, timeout=15)
            assert r.status_code == 200, r.text
            body = r.json()
            assert "updated" in body and "skipped_conflicts" in body
            upd_ids = [u.get("id") for u in body["updated"]]
            sk_ids = [s.get("request_id") for s in body["skipped_conflicts"]]
            assert req_clean in upd_ids
            assert req_clash in sk_ids

            # bulk with override_conflict pushes all through
            reason = "TEST bulk override"
            r = client.post(f"{BASE_URL}/api/requests/bulk",
                            json={"ids": [req_clash],
                                  "status": "accepted",
                                  "override_conflict": True,
                                  "override_reason": reason}, timeout=15)
            assert r.status_code == 200, r.text
            body = r.json()
            upd_ids = [u.get("id") for u in body.get("updated", [])]
            assert req_clash in upd_ids, f"clash should be accepted via override: {body}"
        finally:
            for rid in [req_clean, req_clash]:
                if rid:
                    try:
                        client.patch(f"{BASE_URL}/api/requests/{rid}",
                                     json={"status": "rejected",
                                           "resolution_note": "TEST cleanup"},
                                     timeout=10)
                        client.delete(f"{BASE_URL}/api/requests/{rid}", timeout=10)
                    except Exception:
                        pass
            # Clean any OFF_REQ leaves created by accepted OFF requests
            for (staff_i, d) in [("A.A.", clean_date), ("T.D.", clash_date)]:
                try:
                    leaves = client.get(f"{BASE_URL}/api/leave",
                                        params={"staff_initials": staff_i},
                                        timeout=10).json()
                    for lv in (leaves if isinstance(leaves, list) else []):
                        if lv.get("date") == d and lv.get("type") in ("OFF_REQ",):
                            client.delete(f"{BASE_URL}/api/leave/{lv['id']}", timeout=10)
                except Exception:
                    pass
            if leave_id:
                try:
                    client.delete(f"{BASE_URL}/api/leave/{leave_id}", timeout=10)
                except Exception:
                    pass


# =====================================================================
# 5. Public request-link check (regression)
# =====================================================================
class TestPublicCheck:
    def test_public_check_endpoint(self, client):
        # create a token for T.D.
        token_id = None
        try:
            r = client.post(f"{BASE_URL}/api/request-tokens",
                            json={"staff_initials": "T.D.",
                                  "note": "TEST public check"}, timeout=10)
            assert r.status_code in (200, 201), r.text
            token_id = r.json().get("token")
            assert token_id
            date_str = "2026-07-15"
            r = requests.get(
                f"{BASE_URL}/api/public/request-link/{token_id}/check",
                params={"date": date_str, "preference": "OFF"}, timeout=10)
            assert r.status_code == 200, r.text
            data = r.json()
            assert "slot_open" in data
            assert "reason" in data
            assert "existing_leave" in data
        finally:
            if token_id:
                try:
                    client.post(f"{BASE_URL}/api/request-tokens/{token_id}/revoke",
                                timeout=10)
                except Exception:
                    pass
