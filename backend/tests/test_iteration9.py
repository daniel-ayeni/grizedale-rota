"""
Iteration 9 — Grizedale Rota Builder
Tests for the 8-item fix batch (cover counts, avoid_staff_pairs, weekend_off_per_rota,
senior auto-extension, export formatting, requests conflicts + inspect, rules seed).
Schema-accurate after live probing.
"""
import os
import io
import time
import copy
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://care-rota-engine.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
ADMIN_EMAIL = "manager@grizedale.local"
ADMIN_PASSWORD = "ChangeMe123!"


@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def auth(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session", autouse=True)
def _baseline_settings(auth):
    """Capture and restore settings around the full session."""
    r = auth.get(f"{API}/settings")
    original = copy.deepcopy(r.json()) if r.status_code == 200 else {}
    yield original
    # restore critical fields
    restore = {
        "day_cover_count": original.get("day_cover_count", 2),
        "night_cover_count": original.get("night_cover_count", 2),
        "cover_overrides": original.get("cover_overrides", []),
        "senior_weekend_rotation": original.get("senior_weekend_rotation", []),
    }
    auth.put(f"{API}/settings", json=restore)


@pytest.fixture(scope="session")
def staff_list(auth):
    r = auth.get(f"{API}/staff")
    assert r.status_code == 200
    return r.json()


# ---------- Basics ----------
class TestBasics:
    def test_health(self):
        r = requests.get(f"{API}/health", timeout=10)
        assert r.status_code == 200

    def test_solver_generate_default(self, auth):
        # ensure baseline state before
        auth.put(f"{API}/settings", json={"day_cover_count": 2, "night_cover_count": 2, "cover_overrides": []})
        t0 = time.time()
        r = auth.post(f"{API}/solver/generate", json={})
        elapsed = time.time() - t0
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("success") is True, data
        assert elapsed < 25


# ---------- Item 5: cover counts ----------
class TestCoverCounts:
    def test_defaults_present(self, auth):
        r = auth.get(f"{API}/settings")
        d = r.json()
        assert d.get("day_cover_count") == 2
        assert d.get("night_cover_count") == 2
        assert isinstance(d.get("cover_overrides"), list)

    def test_put_day_cover_count_persists(self, auth):
        r = auth.put(f"{API}/settings", json={"day_cover_count": 3})
        assert r.status_code == 200
        # readback
        got = auth.get(f"{API}/settings").json()
        assert got["day_cover_count"] == 3
        # revert to avoid INFEASIBLE in later tests
        auth.put(f"{API}/settings", json={"day_cover_count": 2})

    def test_cover_override_per_date(self, auth):
        override_date = "2026-04-22"
        # ensure baseline first
        auth.put(f"{API}/settings", json={"day_cover_count": 2, "night_cover_count": 2})
        r = auth.put(f"{API}/settings", json={
            "cover_overrides": [{"date": override_date, "day_count": 3, "night_count": 2}],
        })
        assert r.status_code == 200
        g = auth.post(f"{API}/solver/generate", json={})
        assert g.status_code == 200, g.text
        gd = g.json()
        if not gd.get("success"):
            pytest.fail(f"solver infeasible with single-day override: {gd}")
        rotas = auth.get(f"{API}/rotas").json()
        rota = auth.get(f"{API}/rotas/{rotas[0]['id']}").json()
        # build day→assignments map
        by_date = {}
        for a in rota.get("assignments", []):
            by_date.setdefault(a["date"], []).append(a)
        if override_date not in by_date:
            pytest.skip(f"{override_date} not in rota span")
        day_count = sum(1 for a in by_date[override_date] if a.get("shift") in ("D", "D*"))
        assert day_count == 3, f"expected 3 day staff on {override_date}, got {day_count}"
        auth.put(f"{API}/settings", json={"cover_overrides": []})


# ---------- Item 6: senior auto-extend ----------
class TestSeniorAutoExtend:
    def test_promote_da_extends_rotation(self, auth, staff_list):
        da = next((s for s in staff_list if s.get("initials") == "D.A."), None)
        assert da is not None
        auth.put(f"{API}/settings", json={"senior_weekend_rotation": []})
        orig_is_senior = da.get("is_senior", False)
        r = auth.put(f"{API}/staff/{da['id']}", json={"is_senior": True})
        assert r.status_code == 200
        try:
            # verify settings.senior_weekend_rotation (after input builder round-robin)
            g = auth.post(f"{API}/solver/generate", json={})
            assert g.status_code == 200
            rota_list = auth.get(f"{API}/rotas").json()
            rota = auth.get(f"{API}/rotas/{rota_list[0]['id']}").json()
            from datetime import date
            da_weekend_working = 0
            for a in rota.get("assignments", []):
                if a.get("staff_initials") != "D.A.":
                    continue
                dt = date.fromisoformat(a["date"])
                if dt.weekday() in (5, 6) and a.get("shift") in ("D", "D*", "N"):
                    da_weekend_working += 1
            assert da_weekend_working >= 1, "D.A. got no weekend working shift after senior promotion"
        finally:
            auth.put(f"{API}/staff/{da['id']}", json={"is_senior": bool(orig_is_senior)})


# ---------- Item 1: exports ----------
class TestExports:
    @pytest.fixture(scope="class")
    def rota_id(self, auth):
        r = auth.get(f"{API}/rotas")
        rotas = r.json()
        assert rotas, "no rotas exist"
        return rotas[0]["id"]

    def test_pdf(self, auth, rota_id):
        r = auth.get(f"{API}/rotas/{rota_id}/export.pdf")
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"

    def test_xlsx(self, auth, rota_id):
        import openpyxl
        r = auth.get(f"{API}/rotas/{rota_id}/export.xlsx")
        assert r.status_code == 200
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        ws = wb["Rota"] if "Rota" in wb.sheetnames else wb.active
        # col A = initials only (no role separator '·')
        initials_rows = 0
        for row_idx in range(4, min(15, ws.max_row + 1)):
            val = ws.cell(row=row_idx, column=1).value
            if val and isinstance(val, str):
                assert "·" not in val, f"row {row_idx} A: {val!r} contains role separator"
                if "." in val and len(val) <= 6:
                    initials_rows += 1
        assert initials_rows >= 2, "no initials-only values in column A"
        # row_height 36 on body row
        assert ws.row_dimensions[4].height == 36
        # landscape fit-to-width
        assert ws.page_setup.orientation == "landscape"
        assert ws.page_setup.fitToWidth == 1
        # print_area references Rota sheet, starting at A1
        # print_area like "'Rota'!$A$1:$AC$11"
        assert ws.print_area and "Rota" in ws.print_area and "$A$1" in ws.print_area
        # print_title_rows
        assert ws.print_title_rows in ("1:3", "$1:$3")
        # col A width
        col_a = ws.column_dimensions.get("A")
        if col_a and col_a.width is not None:
            assert col_a.width <= 12, f"col A width {col_a.width} > 12"


# ---------- Items 9-11: /requests enrichment + inspect ----------
class TestRequests:
    @pytest.fixture(scope="class")
    def pending_request(self, auth):
        # Find a staff that isn't already on AL that date
        staff_r = auth.get(f"{API}/staff").json()
        victim = next((s for s in staff_r if s.get("initials") == "D.A."), staff_r[0])
        payload = {
            "staff_initials": victim["initials"],
            "date": "2026-06-15",
            "shift_preference": "AL",
            "notes": "TEST_iter9",
            "source": "manager",
        }
        r = auth.post(f"{API}/requests", json=payload)
        if r.status_code not in (200, 201):
            pytest.skip(f"cannot seed request: {r.status_code} {r.text[:200]}")
        req = r.json()
        yield req
        try:
            auth.patch(f"{API}/requests/{req['id']}", json={"status": "rejected", "resolution_note": "cleanup"})
        except Exception:
            pass

    def test_list_has_staff_role(self, auth):
        r = auth.get(f"{API}/requests")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) > 0
        for row in rows[:10]:
            assert "staff_role" in row, f"missing staff_role: {list(row.keys())}"
            # staff_role should be populated (non-empty for real staff)
        populated = sum(1 for r_ in rows if r_.get("staff_role"))
        assert populated > 0, "no rows have populated staff_role"

    def test_list_has_conflicts_on_pending(self, auth, pending_request):
        rows = auth.get(f"{API}/requests").json()
        pend = next((r for r in rows if r["id"] == pending_request["id"]), None)
        assert pend is not None
        if pend.get("status") != "pending":
            pytest.skip("seeded request not pending")
        c = pend.get("conflicts")
        assert c is not None, f"pending row missing conflicts: {pend}"
        assert any(k in c for k in ("slot_status", "slot_open"))
        assert "existing_leave" in c

    def test_inspect_endpoint(self, auth, pending_request):
        r = auth.get(f"{API}/requests/{pending_request['id']}/inspect")
        assert r.status_code == 200, r.text
        d = r.json()
        for key in ("request", "staff_role", "staff_full_name", "day_leave", "day_assignments"):
            assert key in d, f"inspect missing {key}: {list(d.keys())}"


# ---------- Item 4 + 7: rules seed ----------
class TestRulesSeed:
    def test_contains_new_rules(self, auth):
        """avoid_staff_pairs AND weekend_off_per_rota should be in live rules_config."""
        r = auth.get(f"{API}/rules")
        assert r.status_code == 200
        rules = r.json().get("rules") or {}
        missing = []
        for rid in ("avoid_staff_pairs", "weekend_off_per_rota"):
            if rid not in rules:
                missing.append(rid)
        assert not missing, f"rules_config missing new rule ids: {missing}. Migration in db_seeder.py must include them."

    def test_avoid_pair_seniors_present(self, auth):
        rules = auth.get(f"{API}/rules").json().get("rules") or {}
        assert "avoid_pair_seniors" in rules


# ---------- Item 4: avoid_staff_pairs soft rule behaviour ----------
class TestAvoidStaffPairs:
    def test_configure_pair_and_generate(self, auth):
        rules = auth.get(f"{API}/rules").json().get("rules") or {}
        if "avoid_staff_pairs" not in rules:
            pytest.skip("avoid_staff_pairs not seeded — covered by TestRulesSeed")
        # PUT preserving shape
        new_rules = copy.deepcopy(rules)
        new_rules["avoid_staff_pairs"] = {
            "mode": "soft",
            "weight": 80,
            "immovable": False,
            "params": {
                "pairs": [{"staff_a_initials": "L.M.", "staff_b_initials": "L.D.", "weight": 80}]
            },
        }
        r2 = auth.put(f"{API}/rules", json={"rules": new_rules})
        assert r2.status_code in (200, 204), r2.text
        g = auth.post(f"{API}/solver/generate", json={})
        assert g.status_code == 200
        rota_list = auth.get(f"{API}/rotas").json()
        rota = auth.get(f"{API}/rotas/{rota_list[0]['id']}").json()
        shared = 0
        by_date = {}
        for a in rota.get("assignments", []):
            by_date.setdefault(a["date"], []).append(a)
        for _d, aa in by_date.items():
            inits = {a["staff_initials"] for a in aa if a.get("shift") in ("D", "D*")}
            if {"L.M.", "L.D."}.issubset(inits):
                shared += 1
        assert shared <= 4, f"L.M./L.D. shared {shared} day-cover days; expected minimised"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
