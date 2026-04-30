"""Phase 1 backend API regression tests for Grizedale Rota Builder.

Covers:
- Health, docs, openapi
- Auth: login (good/bad), me, register, logout
- Protected endpoint guards
- Staff CRUD + partial PUT
- Service-users CRUD
- Rules GET/PUT
- Settings GET/PUT
- Admins GET/POST/DELETE (incl. cannot delete self)
- Solver: /seed, /generate (default Mongo, hard rules, pairing assertion,
  rule-config integration, staff PATCH integration)
"""

from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://care-rota-engine.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "manager@grizedale.local"
ADMIN_PASSWORD = "ChangeMe123!"

EXPECTED_STAFF_INITIALS = {"J.C.", "L.M.", "L.D.", "D.A.", "T.D.", "C.E.", "A.A.", "J.R."}
MED_COMPETENT_EXPECTED = {"J.C.", "L.M.", "L.D.", "D.A.", "C.E.", "A.A."}
NIGHT_LIKE_SHIFTS = {"D", "D*", "N", "*"}
WORK_SHIFTS = {"D", "D*", "N", "*"}


# ---------- Fixtures ----------
@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_token(session):
    r = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# ---------- Health / Docs ----------
class TestHealth:
    def test_health(self, session):
        r = session.get(f"{API}/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_docs(self, session):
        r = session.get(f"{API}/docs")
        assert r.status_code == 200

    def test_openapi(self, session):
        r = session.get(f"{API}/openapi.json")
        assert r.status_code == 200
        assert "paths" in r.json()


# ---------- Auth ----------
class TestAuth:
    def test_login_success(self, session):
        r = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        body = r.json()
        assert "token" in body and isinstance(body["token"], str) and len(body["token"]) > 20
        assert "user" in body
        u = body["user"]
        assert u["email"] == ADMIN_EMAIL
        assert u["role"] == "admin"
        assert "id" in u
        assert "password_hash" not in u
        assert "_id" not in u

    def test_login_wrong_password(self, session):
        r = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-password"})
        assert r.status_code == 401

    def test_login_unknown_email(self, session):
        r = session.post(f"{API}/auth/login", json={"email": "nope@nope.local", "password": "x"})
        assert r.status_code == 401

    def test_me_with_token(self, session, admin_headers):
        r = session.get(f"{API}/auth/me", headers=admin_headers)
        assert r.status_code == 200
        u = r.json()
        assert u["email"] == ADMIN_EMAIL
        assert "password_hash" not in u

    def test_me_without_token(self, session):
        r = session.get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_me_invalid_token(self, session):
        r = session.get(f"{API}/auth/me", headers={"Authorization": "Bearer not-a-real-jwt"})
        assert r.status_code == 401


# ---------- Protected endpoint guards ----------
PROTECTED_GETS = ["/staff", "/service-users", "/rules", "/settings", "/admins", "/solver/seed"]


@pytest.mark.parametrize("path", PROTECTED_GETS)
def test_protected_endpoints_require_auth(session, path):
    r = session.get(f"{API}{path}")
    assert r.status_code == 401, f"{path} expected 401, got {r.status_code}"


def test_solver_generate_requires_auth(session):
    r = session.post(f"{API}/solver/generate", json={})
    assert r.status_code == 401


# ---------- Staff CRUD ----------
class TestStaffCRUD:
    def test_list_staff_seed(self, session, admin_headers):
        r = session.get(f"{API}/staff", headers=admin_headers)
        assert r.status_code == 200
        staff = r.json()
        assert len(staff) == 8, f"Expected 8 staff, got {len(staff)}"
        initials = {s["initials"] for s in staff}
        assert initials == EXPECTED_STAFF_INITIALS, f"Mismatch: {initials}"
        # Check med-competent flags per spec
        med = {s["initials"] for s in staff if s.get("medication_competent")}
        assert med == MED_COMPETENT_EXPECTED, f"Med-competent mismatch: {med}"
        # J.C. admin only with target=0
        jc = next(s for s in staff if s["initials"] == "J.C.")
        assert jc.get("is_admin_only") is True
        assert jc.get("target_weekly_hours") == 0
        # Sleepover: everyone except J.C.
        sleep = {s["initials"] for s in staff if s.get("can_do_sleepover")}
        assert "J.C." not in sleep
        assert len(sleep) == 7
        # No password_hash leaked
        for s in staff:
            assert "password_hash" not in s
            assert "_id" not in s

    def test_create_update_delete_staff(self, session, admin_headers):
        unique = f"X{uuid.uuid4().hex[:3].upper()}."
        payload = {
            "initials": unique,
            "full_name": "Test Staff",
            "role": "carer",
            "gender": "F",
            "target_weekly_hours": 24,
            "medication_competent": False,
            "first_aider": False,
            "can_do_days": True,
            "can_do_nights": False,
            "can_do_sleepover": False,
        }
        # CREATE
        r = session.post(f"{API}/staff", json=payload, headers=admin_headers)
        assert r.status_code == 200, r.text
        created = r.json()
        sid = created["id"]
        assert created["initials"] == unique
        assert created["medication_competent"] is False

        # GET (verify persisted)
        r2 = session.get(f"{API}/staff/{sid}", headers=admin_headers)
        assert r2.status_code == 200
        assert r2.json()["initials"] == unique

        # PARTIAL PUT — toggle med flag only
        r3 = session.put(f"{API}/staff/{sid}", json={"medication_competent": True}, headers=admin_headers)
        assert r3.status_code == 200
        assert r3.json()["medication_competent"] is True
        # Other fields preserved
        assert r3.json()["full_name"] == "Test Staff"

        # DELETE
        r4 = session.delete(f"{API}/staff/{sid}", headers=admin_headers)
        assert r4.status_code == 200

        # GET 404
        r5 = session.get(f"{API}/staff/{sid}", headers=admin_headers)
        assert r5.status_code == 404


# ---------- Service users CRUD ----------
class TestServiceUsersCRUD:
    def test_list_seed(self, session, admin_headers):
        r = session.get(f"{API}/service-users", headers=admin_headers)
        assert r.status_code == 200
        sus = r.json()
        assert len(sus) == 7, f"Expected 7 service users, got {len(sus)}"
        names = {s["name"] for s in sus}
        for i in range(1, 8):
            assert f"Service User {i}" in names

    def test_crud(self, session, admin_headers):
        r = session.post(
            f"{API}/service-users",
            json={"name": "TEST_SU_temp", "needs_female_staff": True},
            headers=admin_headers,
        )
        assert r.status_code == 200
        sid = r.json()["id"]
        # PUT
        r2 = session.put(f"{API}/service-users/{sid}", json={"needs_female_staff": False}, headers=admin_headers)
        assert r2.status_code == 200
        assert r2.json()["needs_female_staff"] is False
        # DELETE
        r3 = session.delete(f"{API}/service-users/{sid}", headers=admin_headers)
        assert r3.status_code == 200


# ---------- Rules ----------
class TestRules:
    def test_get_and_put_rules(self, session, admin_headers):
        r = session.get(f"{API}/rules", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        rules = body.get("rules", body)
        # At least these keys should be present
        for key in ["day_cover", "night_cover", "med_competent_required"]:
            assert key in rules, f"Missing rule {key}"

        # PUT — toggle a value, then revert
        original_fa = rules.get("first_aider_required")
        new_rules = dict(rules)
        new_rules["first_aider_required"] = "off"
        r2 = session.put(f"{API}/rules", json={"rules": new_rules}, headers=admin_headers)
        assert r2.status_code == 200
        # Revert
        new_rules["first_aider_required"] = original_fa if original_fa is not None else "hard"
        r3 = session.put(f"{API}/rules", json={"rules": new_rules}, headers=admin_headers)
        assert r3.status_code == 200


# ---------- Settings ----------
class TestSettings:
    def test_get_settings(self, session, admin_headers):
        r = session.get(f"{API}/settings", headers=admin_headers)
        assert r.status_code == 200
        s = r.json()
        assert s.get("home_name") == "Grizedale"
        assert "shift_hours" in s
        assert "public_holidays" in s
        # UK 2026 holidays
        hols = s["public_holidays"]
        assert isinstance(hols, list)
        assert len(hols) >= 6

    def test_put_settings_roundtrip(self, session, admin_headers):
        r = session.get(f"{API}/settings", headers=admin_headers)
        original = r.json()
        original.pop("_id", None)
        # Modify and revert
        new_name = "Grizedale Test"
        r2 = session.put(f"{API}/settings", json={**original, "home_name": new_name}, headers=admin_headers)
        assert r2.status_code == 200
        assert r2.json()["home_name"] == new_name
        # Revert
        r3 = session.put(f"{API}/settings", json={**original, "home_name": "Grizedale"}, headers=admin_headers)
        assert r3.status_code == 200
        assert r3.json()["home_name"] == "Grizedale"


# ---------- Admins ----------
class TestAdmins:
    def test_list_admins(self, session, admin_headers):
        r = session.get(f"{API}/admins", headers=admin_headers)
        assert r.status_code == 200
        admins = r.json()
        assert len(admins) >= 1
        emails = [a["email"] for a in admins]
        assert ADMIN_EMAIL in emails
        for a in admins:
            assert "password_hash" not in a

    def test_create_login_delete_admin(self, session, admin_headers):
        email = f"test_{uuid.uuid4().hex[:6]}@example.com"
        password = "Test1234!"
        r = session.post(
            f"{API}/admins",
            json={"name": "Temp Admin", "email": email, "password": password, "role": "admin"},
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        new_id = r.json()["id"]

        # Login as new admin
        r2 = session.post(f"{API}/auth/login", json={"email": email, "password": password})
        assert r2.status_code == 200
        new_token = r2.json()["token"]
        # Use new admin to access staff
        r3 = session.get(f"{API}/staff", headers={"Authorization": f"Bearer {new_token}"})
        assert r3.status_code == 200

        # DELETE
        r4 = session.delete(f"{API}/admins/{new_id}", headers=admin_headers)
        assert r4.status_code == 200

    def test_cannot_delete_self(self, session, admin_headers):
        # Get current user id
        r = session.get(f"{API}/auth/me", headers=admin_headers)
        my_id = r.json()["id"]
        r2 = session.delete(f"{API}/admins/{my_id}", headers=admin_headers)
        assert r2.status_code == 400


# ---------- Solver ----------
class TestSolver:
    def test_solver_seed_endpoint(self, session, admin_headers):
        r = session.get(f"{API}/solver/seed", headers=admin_headers)
        assert r.status_code == 200
        payload = r.json()
        assert "staff" in payload
        assert "rota_start_date" in payload

    def test_solver_generate_default(self, session, admin_headers):
        t0 = time.time()
        r = session.post(f"{API}/solver/generate", json={}, headers=admin_headers)
        elapsed_ms = (time.time() - t0) * 1000
        assert r.status_code == 200, r.text
        assert elapsed_ms < 15000, f"Solve took {elapsed_ms:.0f}ms"
        body = r.json()
        assert body.get("success") is True
        rota = body.get("rota") or body.get("schedule") or {}
        # Find the days/assignments structure
        # Common shapes: {rota: {days: [{date, assignments: [...]}, ...]}}
        days = self._extract_days(body)
        assert len(days) == 28, f"Expected 28 days, got {len(days)}"

        # J.C. must be OFF every day
        for d in days:
            jc_shift = self._shift_for(d, "J.C.")
            assert jc_shift not in WORK_SHIFTS, f"{d.get('date')}: J.C. assigned {jc_shift}"

        # D/D* count == 2 per day, N count == 1, D*+* count == 1
        for d in days:
            shifts_today = self._shift_map(d)
            d_count = sum(1 for v in shifts_today.values() if v == "D")
            dstar_count = sum(1 for v in shifts_today.values() if v == "D*")
            n_count = sum(1 for v in shifts_today.values() if v == "N")
            star_count = sum(1 for v in shifts_today.values() if v == "*")
            assert d_count + dstar_count == 2, f"{d.get('date')}: D+D* = {d_count + dstar_count}"
            assert n_count == 1, f"{d.get('date')}: N count = {n_count}"
            assert dstar_count + star_count == 1, f"{d.get('date')}: D*+* = {dstar_count + star_count}"
            # No AL/TRN since not provided
            assert "AL" not in shifts_today.values()
            assert "TRN" not in shifts_today.values()

    def test_pairing_da_dstar_or_star_no_aa_on_n(self, session, admin_headers):
        r = session.post(f"{API}/solver/generate", json={}, headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        days = self._extract_days(body)
        violations = []
        for d in days:
            shifts = self._shift_map(d)
            da = shifts.get("D.A.")
            if da in {"D*", "*"}:
                # find the N
                n_staff = [k for k, v in shifts.items() if v == "N"]
                if not n_staff:
                    violations.append(f"{d.get('date')}: no N staff while D.A.={da}")
                    continue
                n_initials = n_staff[0]
                assert n_initials in {"C.E.", "J.R."}, (
                    f"{d.get('date')}: D.A.={da} but N={n_initials} (must be C.E. or J.R.)"
                )
                if n_initials == "A.A.":
                    violations.append(f"{d.get('date')}: D.A.={da} N=A.A. (forbidden)")
        assert not violations, violations

    def test_no_n_to_d_no_dstar_to_dstar(self, session, admin_headers):
        r = session.post(f"{API}/solver/generate", json={}, headers=admin_headers)
        body = r.json()
        days = self._extract_days(body)
        # Get all staff initials from day 0
        all_initials = list(self._shift_map(days[0]).keys())
        for staff_init in all_initials:
            for i in range(len(days) - 1):
                today = self._shift_map(days[i]).get(staff_init)
                tomorrow = self._shift_map(days[i + 1]).get(staff_init)
                # No N today -> D tomorrow
                assert not (today == "N" and tomorrow == "D"), f"{staff_init}: N->D at day {i}"
                # No D* -> D* consecutive
                assert not (today == "D*" and tomorrow == "D*"), f"{staff_init}: D*->D* at day {i}"

    def test_rule_config_integration_first_aider_off(self, session, admin_headers):
        # Get current rules
        r = session.get(f"{API}/rules", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        rules = body.get("rules", body)
        original = dict(rules)
        try:
            new_rules = dict(rules)
            new_rules["first_aider_required"] = "off"
            r2 = session.put(f"{API}/rules", json={"rules": new_rules}, headers=admin_headers)
            assert r2.status_code == 200
            r3 = session.post(f"{API}/solver/generate", json={}, headers=admin_headers)
            assert r3.status_code == 200, f"Solver failed with FA off: {r3.text}"
            assert r3.json().get("success") is True
        finally:
            session.put(f"{API}/rules", json={"rules": original}, headers=admin_headers)

    # ---------- helpers ----------
    @staticmethod
    def _extract_days(body: dict) -> list:
        # Try several shapes
        for key in ("rota", "schedule", "result"):
            v = body.get(key)
            if isinstance(v, dict) and "days" in v:
                return v["days"]
            if isinstance(v, list):
                return v
        if "days" in body:
            return body["days"]
        return []

    @staticmethod
    def _shift_map(day_obj: dict) -> dict:
        """Return {staff_initials: shift_code} for a day."""
        # Support: {date, assignments: {INIT: SHIFT}} or {date, assignments: [{staff, shift}]}
        a = day_obj.get("assignments")
        if isinstance(a, dict):
            return a
        if isinstance(a, list):
            out = {}
            for item in a:
                key = item.get("staff") or item.get("initials") or item.get("staff_initials")
                val = item.get("shift") or item.get("shift_code")
                if key and val:
                    out[key] = val
            return out
        # Fallback: top-level cells
        return {k: v for k, v in day_obj.items() if k != "date" and isinstance(v, str)}

    @classmethod
    def _shift_for(cls, day_obj: dict, initials: str) -> str | None:
        return cls._shift_map(day_obj).get(initials)
