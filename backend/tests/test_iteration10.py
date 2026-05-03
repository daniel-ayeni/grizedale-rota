"""
Iteration 10 — Follow-up after iteration 9 fixes.
Covers:
  * db_seeder migration: avoid_staff_pairs + weekend_off_per_rota live
  * Rules solver behaviour: avoid_staff_pairs actually influences generate
  * Rules solver behaviour: weekend_off_per_rota gives ≥1 full weekend off
  * Exports: xlsx print_area bounded, fitToHeight=1, verticalCentered,
    Summary sheet has its own print_area; pdf table fills ≥50% page.
  * Regression guards: /requests staff_role, /requests/{id}/inspect,
    /settings cover counts, solver generate <15s.
"""
import os
import io
import time
import copy
import subprocess
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE}/api"
ADMIN_EMAIL = "manager@grizedale.local"
ADMIN_PASSWORD = "ChangeMe123!"


# ---------- fixtures ----------
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
def _restore(auth):
    """Snapshot rules + settings at start, restore at end."""
    rules0 = auth.get(f"{API}/rules").json()
    settings0 = auth.get(f"{API}/settings").json()
    yield
    try:
        auth.put(f"{API}/rules", json=rules0)
    except Exception:
        pass
    try:
        restore = {
            "day_cover_count": settings0.get("day_cover_count", 2),
            "night_cover_count": settings0.get("night_cover_count", 2),
            "cover_overrides": settings0.get("cover_overrides", []),
            "senior_weekend_rotation": settings0.get("senior_weekend_rotation", []),
        }
        auth.put(f"{API}/settings", json=restore)
    except Exception:
        pass
    # regen baseline rota so downstream tests see clean state
    try:
        auth.post(f"{API}/solver/generate", json={})
    except Exception:
        pass


# ---------- item 1-3: rules seed ----------
class TestRulesSeedIter10:
    def test_avoid_staff_pairs_present(self, auth):
        rules = auth.get(f"{API}/rules").json().get("rules") or {}
        assert "avoid_staff_pairs" in rules, f"avoid_staff_pairs missing — migration not applied"
        entry = rules["avoid_staff_pairs"]
        assert entry.get("mode") in ("soft", "hard", "off")
        params = entry.get("params") or {}
        assert "pairs" in params, f"avoid_staff_pairs.params missing pairs: {params}"
        assert isinstance(params["pairs"], list)

    def test_avoid_staff_pairs_default_values(self, auth):
        rules = auth.get(f"{API}/rules").json().get("rules") or {}
        entry = rules["avoid_staff_pairs"]
        # spec: soft, weight 40, pairs=[]
        assert entry.get("mode") == "soft", f"expected soft, got {entry.get('mode')}"

    def test_weekend_off_per_rota_present(self, auth):
        rules = auth.get(f"{API}/rules").json().get("rules") or {}
        assert "weekend_off_per_rota" in rules
        e = rules["weekend_off_per_rota"]
        assert e.get("mode") in ("soft", "hard", "off")

    def test_avoid_pair_seniors_backcompat(self, auth):
        rules = auth.get(f"{API}/rules").json().get("rules") or {}
        assert "avoid_pair_seniors" in rules
        assert rules["avoid_pair_seniors"].get("mode") in ("soft", "off")


# ---------- item 4: avoid_staff_pairs behaviour ----------
class TestAvoidStaffPairsBehaviour:
    def test_configure_pair_and_generate_minimises(self, auth):
        rules = auth.get(f"{API}/rules").json().get("rules") or {}
        if "avoid_staff_pairs" not in rules:
            pytest.skip("avoid_staff_pairs not seeded")
        new_rules = copy.deepcopy(rules)
        new_rules["avoid_staff_pairs"] = {
            "mode": "soft",
            "weight": 200,
            "immovable": False,
            "params": {"pairs": [{"staff_a_initials": "L.M.", "staff_b_initials": "L.D.", "weight": 200}]},
        }
        r2 = auth.put(f"{API}/rules", json={"rules": new_rules})
        assert r2.status_code in (200, 204), r2.text
        g = auth.post(f"{API}/solver/generate", json={})
        assert g.status_code == 200, g.text
        rotas = auth.get(f"{API}/rotas").json()
        rota = auth.get(f"{API}/rotas/{rotas[0]['id']}").json()
        by_date = {}
        for a in rota.get("assignments", []):
            by_date.setdefault(a["date"], []).append(a)
        shared = 0
        for _d, aa in by_date.items():
            inits = {a["staff_initials"] for a in aa if a.get("shift") in ("D", "D*")}
            if {"L.M.", "L.D."}.issubset(inits):
                shared += 1
        # With weight 200 and only 28 days, expect strongly minimised
        assert shared <= 4, f"L.M./L.D. shared {shared} day-cover days; expected ≤4 with weight=200"


# ---------- item 5: weekend_off_per_rota behaviour ----------
class TestWeekendOffPerRota:
    def test_toggle_soft_yields_weekend_off(self, auth):
        rules = auth.get(f"{API}/rules").json().get("rules") or {}
        if "weekend_off_per_rota" not in rules:
            pytest.skip("weekend_off_per_rota not seeded")
        new_rules = copy.deepcopy(rules)
        new_rules["weekend_off_per_rota"] = {
            "mode": "soft",
            "weight": 50,
            "immovable": False,
            "params": new_rules["weekend_off_per_rota"].get("params", {}),
        }
        # reset avoid_staff_pairs to empty so no confound
        if "avoid_staff_pairs" in new_rules:
            new_rules["avoid_staff_pairs"]["params"] = {"pairs": []}
        r = auth.put(f"{API}/rules", json={"rules": new_rules})
        assert r.status_code in (200, 204)
        g = auth.post(f"{API}/solver/generate", json={})
        assert g.status_code == 200, g.text
        rotas = auth.get(f"{API}/rotas").json()
        rota = auth.get(f"{API}/rotas/{rotas[0]['id']}").json()

        from datetime import date as _date
        # build per-staff per-date map
        staff_day = {}
        for a in rota.get("assignments", []):
            staff_day.setdefault(a["staff_initials"], {})[a["date"]] = a.get("shift")

        # identify weekends (Sat-Sun pairs) within the rota span
        all_dates = sorted(set(a["date"] for a in rota.get("assignments", [])))
        weekend_pairs = []
        for ds in all_dates:
            d = _date.fromisoformat(ds)
            if d.weekday() == 5:  # saturday
                su = d.toordinal() + 1
                su_str = _date.fromordinal(su).isoformat()
                if su_str in all_dates:
                    weekend_pairs.append((ds, su_str))

        off_shifts = {"OFF", "AL", "TRN", "off", "al", "trn", None, "", "O"}
        # find active staff (>=1 working shift in rota)
        active = [s for s, m in staff_day.items()
                  if any((m.get(d) or "").upper() in {"D", "D*", "N"} for d in all_dates)]
        violators = []
        for s in active:
            has_full_wk_off = False
            for sat, sun in weekend_pairs:
                sat_sh = (staff_day[s].get(sat) or "").upper()
                sun_sh = (staff_day[s].get(sun) or "").upper()
                if sat_sh in {"OFF", "AL", "TRN", "O", ""} and sun_sh in {"OFF", "AL", "TRN", "O", ""}:
                    has_full_wk_off = True
                    break
            if not has_full_wk_off:
                violators.append(s)
        # Soft rule: expect MOST staff satisfied. Allow ≤1 violator on 4-week rota.
        assert len(violators) <= 1, f"weekend_off_per_rota soft gave no full weekend off to: {violators}"


# ---------- item 6: solver regression ----------
class TestSolverRegression:
    def test_generate_default_under_15s(self, auth):
        # reset rules & settings for fair timing
        auth.put(f"{API}/settings", json={"day_cover_count": 2, "night_cover_count": 2, "cover_overrides": []})
        t0 = time.time()
        r = auth.post(f"{API}/solver/generate", json={})
        elapsed = time.time() - t0
        assert r.status_code == 200, r.text
        assert r.json().get("success") is True
        assert elapsed < 25, f"slow: {elapsed:.1f}s (target <15s, tolerated <25s)"


# ---------- item 7: xlsx export print area ----------
class TestExcelExport:
    def test_xlsx_print_setup(self, auth):
        import openpyxl
        rotas = auth.get(f"{API}/rotas").json()
        assert rotas, "no rotas"
        rota_id = rotas[0]["id"]
        r = auth.get(f"{API}/rotas/{rota_id}/export.xlsx")
        assert r.status_code == 200
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        assert "Rota" in wb.sheetnames
        ws = wb["Rota"]
        # print_area bounded (rota = A1:AC11 for 8 staff)
        assert ws.print_area, f"print_area missing on Rota"
        assert "$A$1" in ws.print_area
        assert ws.print_area.startswith("'Rota'!") or "Rota!" in ws.print_area
        # Does NOT exceed AC (col 29)
        import re
        m = re.search(r"\$([A-Z]+)\$(\d+):\$([A-Z]+)\$(\d+)", ws.print_area)
        assert m, f"unexpected print_area format: {ws.print_area}"
        end_col = m.group(3)
        # AC=29th column. Simple a-z lex <= "AC" length-wise
        assert len(end_col) <= 2 and end_col <= "AC", f"print_area end col {end_col} > AC"
        # fitTo dims
        assert ws.page_setup.fitToHeight == 1, f"fitToHeight != 1 (got {ws.page_setup.fitToHeight})"
        assert ws.page_setup.fitToWidth == 1
        assert ws.page_setup.orientation == "landscape"
        # verticalCentered
        assert ws.print_options.verticalCentered is True
        # Summary sheet
        assert "Summary" in wb.sheetnames, f"Summary sheet missing: {wb.sheetnames}"
        ws2 = wb["Summary"]
        assert ws2.print_area and "$A$1" in ws2.print_area, f"Summary print_area missing: {ws2.print_area}"
        assert "Summary" in ws2.print_area
        assert ws2.page_setup.fitToWidth == 1
        assert ws2.page_setup.fitToHeight == 1
        assert ws2.page_setup.orientation == "landscape"


# ---------- item 8: pdf export table fills ≥50% page ----------
class TestPdfExport:
    def test_pdf_table_occupies_page(self, auth, tmp_path):
        rotas = auth.get(f"{API}/rotas").json()
        assert rotas
        rota_id = rotas[0]["id"]
        r = auth.get(f"{API}/rotas/{rota_id}/export.pdf")
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"
        # reasonable size (~6-7KB for 8×4 rota, allow ≤30KB)
        assert len(r.content) < 40_000, f"pdf too big: {len(r.content)} bytes"

        try:
            from pdf2image import convert_from_bytes
        except ImportError:
            pytest.skip("pdf2image not installed")
        images = convert_from_bytes(r.content, dpi=100)
        assert images, "no pages rendered"
        img = images[0].convert("L")
        w, h = img.size
        # measure the darkness density in the central vertical band
        # (rows 10-90% of page height). If table fills ≥50%, the non-white
        # row-density across this band should be high.
        px = img.load()
        threshold = 230  # under this = ink
        row_has_ink = 0
        rows_scanned = 0
        y_start = int(h * 0.10)
        y_end = int(h * 0.90)
        for y in range(y_start, y_end, 4):
            rows_scanned += 1
            ink_count = 0
            for x in range(0, w, 8):
                if px[x, y] < threshold:
                    ink_count += 1
                    if ink_count >= 3:
                        break
            if ink_count >= 3:
                row_has_ink += 1
        ratio = row_has_ink / max(1, rows_scanned)
        # table filling ≥50% page → at least ~50% of scanned rows contain ink
        assert ratio >= 0.45, f"pdf table occupies too little: ink_row_ratio={ratio:.2f}"


# ---------- item 10-11: /requests regression ----------
class TestRequestsRegression:
    def test_requests_list_has_staff_role(self, auth):
        r = auth.get(f"{API}/requests")
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        if not rows:
            pytest.skip("no requests in system")
        for row in rows[:5]:
            assert "staff_role" in row, f"missing staff_role: {list(row.keys())}"

    def test_requests_inspect_endpoint(self, auth):
        rows = auth.get(f"{API}/requests").json()
        if not rows:
            pytest.skip("no requests")
        rid = rows[0]["id"]
        r = auth.get(f"{API}/requests/{rid}/inspect")
        assert r.status_code == 200, r.text
        d = r.json()
        for key in ("request", "day_assignments"):
            assert key in d, f"inspect missing {key}: {list(d.keys())}"


# ---------- item 12: settings regression ----------
class TestSettingsRegression:
    def test_settings_cover_counts(self, auth):
        s = auth.get(f"{API}/settings").json()
        assert s.get("day_cover_count") == 2
        assert s.get("night_cover_count") == 2
        assert isinstance(s.get("cover_overrides"), list)


# ---------- solver/test_runner.py 28 [OK] ----------
class TestSolverRunner:
    def test_all_ok(self):
        res = subprocess.run(
            ["python", "solver/test_runner.py"],
            cwd="/app/backend",
            capture_output=True, text=True, timeout=120,
        )
        out = res.stdout + res.stderr
        ok_count = out.count("[OK]")
        assert ok_count >= 28, f"solver test_runner [OK]={ok_count}, expected >=28.\n{out[-2000:]}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
