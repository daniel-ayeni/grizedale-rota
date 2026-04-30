"""
Phase 2 FINAL pass tests for Grizedale Rota Builder.

Focus:
  - J.R. nights-only migration (can_do_sleepover=False)
  - New soft rules (overtime_prefer_flexi, prefer_dstar_over_star, non_flexi_overage)
  - Solver output quality (D.A. cap, others near contract, J.R. N-only, D*+N preference)
  - J.R. cell-level capability validation
  - Validator flags historical rota violations
  - pay_cut_off_date round-trip on rotas
  - Performance (cell PATCH <1s, solver <15s)
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "manager@grizedale.local"
ADMIN_PASSWORD = "ChangeMe123!"


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def client(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


# ---------- J.R. migration ----------
class TestJRMigration:
    def test_jr_can_do_sleepover_false(self, client):
        r = client.get(f"{BASE_URL}/api/staff", timeout=10)
        assert r.status_code == 200
        staff = r.json()
        jr = next((s for s in staff if s.get("initials") == "J.R."), None)
        assert jr is not None, "J.R. missing in staff list"
        assert jr.get("can_do_sleepover") is False, f"J.R. can_do_sleepover should be False, got {jr.get('can_do_sleepover')}"


# ---------- New overtime rules ----------
class TestOvertimeRulesPresent:
    def test_rules_include_three_new_soft_rules(self, client):
        r = client.get(f"{BASE_URL}/api/rules", timeout=10)
        assert r.status_code == 200
        body = r.json()
        rules = body.get("rules", body) if isinstance(body, dict) else {x["rule_id"]: x for x in body}

        # overtime_prefer_flexi
        assert "overtime_prefer_flexi" in rules, "overtime_prefer_flexi rule missing"
        opf = rules["overtime_prefer_flexi"]
        assert opf["mode"] == "soft"
        assert opf["weight"] == 15, f"overtime_prefer_flexi weight should be 15, got {opf['weight']}"
        params = opf.get("params", {}) or {}
        assert params.get("preferred_staff_initials") == "D.A.", f"preferred_staff_initials wrong: {params}"
        assert params.get("weekly_cap") == 48, f"weekly_cap wrong: {params}"

        # prefer_dstar_over_star (spec: weight=200)
        assert "prefer_dstar_over_star" in rules, "prefer_dstar_over_star rule missing"
        pd = rules["prefer_dstar_over_star"]
        assert pd["mode"] == "soft"
        assert pd["weight"] == 200, f"prefer_dstar_over_star weight should be 200 per spec, got {pd['weight']}"

        # non_flexi_overage (spec: weight=50)
        assert "non_flexi_overage" in rules, "non_flexi_overage rule missing"
        nfo = rules["non_flexi_overage"]
        assert nfo["mode"] == "soft"
        assert nfo["weight"] == 50, f"non_flexi_overage weight should be 50, got {nfo['weight']}"

    def test_rules_count_at_least_16(self, client):
        r = client.get(f"{BASE_URL}/api/rules", timeout=10)
        assert r.status_code == 200
        body = r.json()
        rules = body.get("rules", body) if isinstance(body, dict) else body
        assert len(rules) >= 16, f"Expected >=16 rules, got {len(rules)}"


# ---------- Solver output quality ----------
@pytest.fixture(scope="module")
def fresh_rota(client):
    """Generate one rota and reuse across tests. Solver returns per-day structure inline."""
    t0 = time.time()
    r = client.post(f"{BASE_URL}/api/solver/generate", json={}, timeout=30)
    elapsed = time.time() - t0
    assert r.status_code == 200, f"solver/generate failed: {r.status_code} {r.text[:500]}"
    assert elapsed < 15.0, f"solver took {elapsed:.2f}s (>15s)"
    data = r.json()
    # Flatten per-day into flat assignments list with date attached
    flat = []
    for day in data.get("rota", []):
        d = day.get("date")
        for a in day.get("assignments", []):
            flat.append({"date": d, "staff_initials": a["staff_initials"], "shift": a.get("shift")})
    return {"rota": data, "assignments": flat, "elapsed": elapsed, "warnings": data.get("warnings", [])}


def _assignments_by_staff(ctx):
    by = {}
    for a in ctx["assignments"]:
        by.setdefault(a["staff_initials"], []).append(a)
    return by


# Actual contracted target hours from seed DB (target_weekly_hours)
CONTRACTS = {
    "L.M.": 36,
    "L.D.": 40,
    "T.D.": 36,
    "D.A.": 28,
    "C.E.": 28,
    "A.A.": 28,
    "J.R.": 28,
}

# Shift hours per settings (D=12, D*=14, N=12, *=0 sleepover, AL/TRN/OFF=0)
SHIFT_HOURS = {"D": 12, "D*": 14, "N": 12, "*": 0, "AL": 0, "TRN": 0, "OFF": 0}


def _total_hours(assignments):
    return sum(SHIFT_HOURS.get(a.get("shift", "OFF"), 0) for a in assignments)


class TestSolverOutput:
    def test_solver_performance(self, fresh_rota):
        assert fresh_rota["elapsed"] < 15.0

    def test_da_hours_in_overtime_band(self, fresh_rota):
        by = _assignments_by_staff(fresh_rota)
        da_hours = _total_hours(by.get("D.A.", []))
        # 4-week target = 28*4 = 112, cap = 48*4 = 192
        assert 110 <= da_hours <= 192, f"D.A. total hours {da_hours} outside [110,192]"

    def test_other_staff_near_contract(self, fresh_rota):
        by = _assignments_by_staff(fresh_rota)
        weeks = 4
        problems = []
        for init in ["L.M.", "L.D.", "T.D.", "C.E.", "A.A.", "J.R."]:
            target = CONTRACTS[init] * weeks
            actual = _total_hours(by.get(init, []))
            # Allow ±2h per week tolerance => ±8h across 4 weeks, plus a little slack.
            if abs(actual - target) > 10:
                problems.append(f"{init}: target={target} actual={actual}")
        assert not problems, f"Non-flexi staff loaded with overtime: {problems}"

    def test_jr_no_star_or_dstar(self, fresh_rota):
        by = _assignments_by_staff(fresh_rota)
        jr = by.get("J.R.", [])
        bad = [a for a in jr if a.get("shift") in ("*", "D*")]
        assert not bad, f"J.R. has disallowed shifts (should only be N since can_do_sleepover=False): {bad[:5]}"

    def test_dstar_n_preferred_over_star_n(self, fresh_rota):
        """Across 28 nights, count nights with D*+N pairing vs *+N pairing.
        D*+N should be >= *+N due to prefer_dstar_over_star weight 200."""
        by_date = {}
        for a in fresh_rota["assignments"]:
            by_date.setdefault(a["date"], []).append(a.get("shift"))
        dstar_n = 0
        star_n = 0
        for date, shifts in by_date.items():
            if "N" not in shifts:
                continue
            if "D*" in shifts:
                dstar_n += 1
            elif "*" in shifts:
                star_n += 1
        assert dstar_n >= star_n, f"Expected D*+N ({dstar_n}) >= *+N ({star_n}) nights"


# ---------- Cell PATCH capability validation for J.R. ----------
class TestCellCapabilityValidation:
    def test_patch_jr_star_flags_capability(self, client):
        # Use the most recent draft rota or create one via PUT; fall back to seeded rota
        rotas = client.get(f"{BASE_URL}/api/rotas", timeout=10).json()
        if not rotas:
            pytest.skip("no rotas available")
        # Prefer a non-seeded draft to avoid mutating the seed prior rota
        target = next((r for r in rotas if r.get("status") == "draft"), rotas[0])
        rota_id = target["id"]
        # Pick a date inside the rota window
        date = target.get("start_date")

        t0 = time.time()
        r = client.patch(
            f"{BASE_URL}/api/rotas/{rota_id}/cell",
            json={"date": date, "staff_initials": "J.R.", "shift": "*"},
            timeout=10,
        )
        elapsed = time.time() - t0
        assert r.status_code in (200, 409), f"PATCH cell returned {r.status_code}: {r.text[:300]}"
        assert elapsed < 1.0, f"cell PATCH took {elapsed*1000:.0f}ms (target <1000ms)"
        body = r.json()
        vr = body.get("validation_report") or {}
        violations = vr.get("violations", [])
        rule_ids = [v.get("rule_id") for v in violations]
        assert "capability_flags" in rule_ids, f"capability_flags not in violations; got rule_ids={rule_ids}"


# ---------- Validator on seeded prior rota ----------
class TestValidatorOnPriorRota:
    def test_prior_rota_has_capability_violations(self, client):
        r = client.get(f"{BASE_URL}/api/rotas", timeout=10)
        assert r.status_code == 200
        rotas = r.json()
        # Find the seeded prior rota (start_date 2026-03-23) or earliest rota
        prior = next((x for x in rotas if x.get("start_date") == "2026-03-23"), None)
        if prior is None:
            # fallback: pick the earliest start_date rota that is published
            pubs = [x for x in rotas if x.get("status") == "published"]
            if not pubs:
                pytest.skip("no seeded prior rota found")
            prior = sorted(pubs, key=lambda x: x.get("start_date", ""))[0]
        vr = client.post(f"{BASE_URL}/api/rotas/{prior['id']}/validate", json={}, timeout=15)
        assert vr.status_code == 200
        report = vr.json()
        violations = report.get("violations", []) or report.get("hard_violations", [])
        rule_ids = [v.get("rule_id") for v in violations]
        assert "capability_flags" in rule_ids, (
            f"Expected capability_flags violation on prior rota for J.R. historical * cells; got rule_ids={set(rule_ids)}"
        )


# ---------- pay_cut_off_date on rotas ----------
class TestPayCutOffField:
    def test_pay_cut_off_round_trip(self, client):
        rotas = client.get(f"{BASE_URL}/api/rotas", timeout=10).json()
        if not rotas:
            pytest.skip("no rotas available")
        target = next((r for r in rotas if r.get("status") == "draft"), rotas[0])
        rota_id = target["id"]
        r = client.put(
            f"{BASE_URL}/api/rotas/{rota_id}",
            json={"pay_cut_off_date": "2026-04-25"},
            timeout=10,
        )
        assert r.status_code == 200, f"PUT rota failed: {r.status_code} {r.text[:300]}"
        g = client.get(f"{BASE_URL}/api/rotas/{rota_id}", timeout=10)
        assert g.status_code == 200
        assert g.json().get("pay_cut_off_date") == "2026-04-25"


# ---------- cleanup ----------
@pytest.fixture(scope="module", autouse=True)
def _cleanup(client):
    yield
    # delete any rotas created with status=draft (solver output) — keep published seed
    try:
        rotas = client.get(f"{BASE_URL}/api/rotas", timeout=10).json()
        for r in rotas:
            if r.get("status") == "draft" and r.get("start_date") != "2026-03-23":
                client.delete(f"{BASE_URL}/api/rotas/{r['id']}", timeout=10)
    except Exception as e:
        print(f"cleanup warning: {e}")
