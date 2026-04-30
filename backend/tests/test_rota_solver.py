"""Phase 0 backend tests for Grizedale rota solver API."""
import json
import os
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    # fallback to /app/frontend/.env
    env_path = Path("/app/frontend/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip()
                break
BASE_URL = BASE_URL.rstrip("/")
SEED_PATH = Path("/app/backend/seed/grizedale.json")


@pytest.fixture(scope="module")
def seed_payload():
    return json.loads(SEED_PATH.read_text())


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---- Health & Docs ----
class TestHealthAndDocs:
    def test_health(self, client):
        r = client.get(f"{BASE_URL}/api/health", timeout=15)
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_docs(self, client):
        r = client.get(f"{BASE_URL}/api/docs", timeout=15)
        assert r.status_code == 200
        assert "swagger" in r.text.lower() or "openapi" in r.text.lower()

    def test_openapi_paths(self, client):
        r = client.get(f"{BASE_URL}/api/openapi.json", timeout=15)
        assert r.status_code == 200
        spec = r.json()
        paths = spec.get("paths", {})
        assert "/api/health" in paths
        assert "/api/solver/seed" in paths
        assert "/api/solver/generate" in paths


# ---- Seed endpoint ----
class TestSeedEndpoint:
    def test_seed_payload(self, client):
        r = client.get(f"{BASE_URL}/api/solver/seed", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["rota_start_date"] == "2026-04-20"
        assert data["weeks"] == 4
        assert len(data["staff"]) == 8
        assert data["leave"] == []
        assert data["locked_cells"] == []
        assert data["avoid_pairs"] == []
        assert "rules" in data and isinstance(data["rules"], dict)


# ---- Solver generate ----
def _hard_rule_validation(rota, staff_by):
    for day in rota:
        sc = {"D": 0, "D*": 0, "N": 0, "*": 0, "OFF": 0, "AL": 0, "TRN": 0}
        for a in day["assignments"]:
            sc[a["shift"]] = sc.get(a["shift"], 0) + 1
        # Cover
        assert sc["D"] + sc["D*"] == 2, f"{day['date']} D+D* != 2"
        assert sc["D*"] <= 1, f"{day['date']} D* > 1"
        assert sc["N"] == 1, f"{day['date']} N != 1"
        assert sc["D*"] + sc["*"] == 1, f"{day['date']} sleepover != 1"

        on_day = [a["staff_initials"] for a in day["assignments"] if a["shift"] in {"D", "D*"}]
        on_night = [a["staff_initials"] for a in day["assignments"] if a["shift"] in {"D*", "*", "N"}]

        assert any(staff_by[s].get("medication_competent") for s in on_day), f"{day['date']} no med on day"
        assert any(staff_by[s].get("medication_competent") for s in on_night), f"{day['date']} no med on night"
        assert any(staff_by[s].get("first_aider") for s in on_day), f"{day['date']} no FA on day"
        assert any(staff_by[s].get("first_aider") for s in on_night), f"{day['date']} no FA on night"

        m_day = [s for s in on_day if staff_by[s].get("gender") == "M"]
        f_day = [s for s in on_day if staff_by[s].get("gender") == "F"]
        if m_day:
            assert f_day, f"{day['date']} male-only day"
        m_night = [s for s in on_night if staff_by[s].get("gender") == "M"]
        f_night = [s for s in on_night if staff_by[s].get("gender") == "F"]
        if m_night:
            assert f_night, f"{day['date']} male-only night"

        for a in day["assignments"]:
            info = staff_by[a["staff_initials"]]
            shift = a["shift"]
            if shift in {"D", "D*"}:
                assert info.get("can_do_days"), f"{a['staff_initials']} D/D* but no can_do_days"
            if shift == "N":
                assert info.get("can_do_nights"), f"{a['staff_initials']} N but no can_do_nights"
            if shift in {"D*", "*"}:
                assert info.get("can_do_sleepover"), f"{a['staff_initials']} sleepover but no flag"


class TestSolverGenerate:
    def test_generate_seed_default(self, client, seed_payload):
        r = client.post(f"{BASE_URL}/api/solver/generate", json=seed_payload, timeout=30)
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:500]}"
        data = r.json()
        assert data["success"] is True
        assert isinstance(data["rota"], list)
        assert len(data["rota"]) == 28
        assert data["solve_time_ms"] < 15000
        assert isinstance(data["soft_violations_score"], int)
        assert isinstance(data["warnings"], list)

        for day in data["rota"]:
            assert len(day["assignments"]) == 8

        staff_by = {s["initials"]: s for s in seed_payload["staff"]}
        _hard_rule_validation(data["rota"], staff_by)

    def test_capability_flags(self, client, seed_payload):
        r = client.post(f"{BASE_URL}/api/solver/generate", json=seed_payload, timeout=30)
        assert r.status_code == 200
        rota = r.json()["rota"]
        for day in rota:
            for a in day["assignments"]:
                init, shift = a["staff_initials"], a["shift"]
                if init == "J.R.":
                    assert shift not in {"D", "D*"}, f"J.R. got {shift}"
                if init in {"J.C.", "L.M.", "L.D.", "T.D."}:
                    assert shift not in {"N", "*"}, f"{init} got {shift}"
                if init == "J.C.":
                    assert shift != "D*", f"J.C. got D*"

    def test_consecutive_rules(self, client, seed_payload):
        r = client.post(f"{BASE_URL}/api/solver/generate", json=seed_payload, timeout=30)
        rota = r.json()["rota"]
        # build by staff
        by_staff = {}
        for day in rota:
            for a in day["assignments"]:
                by_staff.setdefault(a["staff_initials"], []).append((day["date"], a["shift"]))
        for s, seq in by_staff.items():
            for i in range(len(seq) - 1):
                t, n = seq[i][1], seq[i + 1][1]
                assert not (t == "N" and n == "D"), f"{s} N->D"
                assert not (t == "D*" and n == "D*"), f"{s} D*->D*"

    def test_locked_cell(self, client, seed_payload):
        payload = json.loads(json.dumps(seed_payload))
        payload["locked_cells"] = [
            {"staff_initials": "L.M.", "date": "2026-04-20", "shift": "OFF"}
        ]
        r = client.post(f"{BASE_URL}/api/solver/generate", json=payload, timeout=30)
        assert r.status_code == 200
        rota = r.json()["rota"]
        first = rota[0]
        assert first["date"] == "2026-04-20"
        lm = next(a for a in first["assignments"] if a["staff_initials"] == "L.M.")
        assert lm["shift"] == "OFF"

    def test_leave_AL_ce_seed_bottleneck(self, client, seed_payload):
        """C.E. is the ONLY med-competent night-capable staff in seed -> AL on
        any single day makes night shift med-coverage infeasible. We assert the
        solver returns 422 with a clear blocking reason (correct behaviour).
        Reported to main agent as a seed limitation, not a code bug."""
        payload = json.loads(json.dumps(seed_payload))
        payload["leave"] = [
            {"staff_initials": "C.E.", "date": "2026-04-22", "type": "AL"}
        ]
        r = client.post(f"{BASE_URL}/api/solver/generate", json=payload, timeout=30)
        assert r.status_code == 422
        body = r.json().get("detail", r.json())
        if isinstance(body, dict):
            assert "med" in body.get("reason", "").lower()

    def test_leave_AL_mechanism_works(self, client, seed_payload):
        """Verify AL mechanism by leaving D.A. (non-bottleneck staff)."""
        payload = json.loads(json.dumps(seed_payload))
        payload["leave"] = [
            {"staff_initials": "D.A.", "date": "2026-04-22", "type": "AL"}
        ]
        r = client.post(f"{BASE_URL}/api/solver/generate", json=payload, timeout=30)
        assert r.status_code == 200
        rota = r.json()["rota"]
        target_day = next(d for d in rota if d["date"] == "2026-04-22")
        da = next(a for a in target_day["assignments"] if a["staff_initials"] == "D.A.")
        assert da["shift"] == "AL"

    def test_over_constrained(self, client, seed_payload):
        payload = json.loads(json.dumps(seed_payload))
        payload["leave"] = [
            {"staff_initials": s, "date": "2026-04-25", "type": "AL"}
            for s in ["L.M.", "L.D.", "D.A.", "T.D.", "C.E.", "A.A."]
        ]
        r = client.post(f"{BASE_URL}/api/solver/generate", json=payload, timeout=30)
        assert r.status_code == 422
        data = r.json()
        body = data.get("detail", data)
        if isinstance(body, dict):
            assert body.get("success") is False
            assert body.get("blocking_constraints"), "expected non-empty blocking_constraints"
            assert "2026-04-25" in body.get("reason", "")
        else:
            # fallback: data itself is the body
            assert data["success"] is False
            assert data["blocking_constraints"]
            assert "2026-04-25" in data["reason"]

    def test_missing_staff_returns_400(self, client, seed_payload):
        payload = {"rota_start_date": "2026-04-20"}
        r = client.post(f"{BASE_URL}/api/solver/generate", json=payload, timeout=15)
        assert r.status_code == 400

    def test_missing_rota_start_date_returns_400(self, client, seed_payload):
        payload = {"staff": seed_payload["staff"]}
        r = client.post(f"{BASE_URL}/api/solver/generate", json=payload, timeout=15)
        assert r.status_code == 400

    def test_manager_no_weekday_work(self, client, seed_payload):
        from datetime import datetime
        r = client.post(f"{BASE_URL}/api/solver/generate", json=seed_payload, timeout=30)
        assert r.status_code == 200
        rota = r.json()["rota"]
        for day in rota:
            dt = datetime.strptime(day["date"], "%Y-%m-%d").date()
            if dt.weekday() < 5:
                jc = next(a for a in day["assignments"] if a["staff_initials"] == "J.C.")
                assert jc["shift"] not in {"D", "D*", "N", "*"}, (
                    f"J.C. assigned {jc['shift']} on weekday {day['date']}"
                )
