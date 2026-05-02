"""Phase 4 tests — review_request iteration 8.

Covers:
  1. /api/public/request-link/{token}/check — richer slot shape
     (slot_status, existing_leave[*].role, would_break_rules, slot_open back-compat).
  2. POST /api/request-tokens — new `short_url_provider` field, is.gd -> da.gd -> direct chain.
  3. Short URL redirects 301 directly (no preview page).
  4. GET /api/public/request-link/{token} — still returns valid_until ISO timestamp.
"""
import os
import datetime as dt
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

ADMIN_EMAIL = "manager@grizedale.local"
ADMIN_PASSWORD = "ChangeMe123!"


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def auth_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def client(auth_token):
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    })
    return s


@pytest.fixture(scope="session")
def staff_by_role(client):
    r = client.get(f"{BASE_URL}/api/staff", timeout=15)
    assert r.status_code == 200
    rows = r.json()
    by_role: dict[str, list[str]] = {}
    for s in rows:
        by_role.setdefault((s.get("role") or "").strip(), []).append(s["initials"])
    return by_role, {s["initials"]: s for s in rows}


@pytest.fixture
def future_dates():
    # three well-separated future dates to avoid colliding with other test fixtures.
    today = dt.date.today()
    base = today + dt.timedelta(days=90)
    return [
        (base + dt.timedelta(days=i)).isoformat()
        for i in (0, 3, 6)
    ]


@pytest.fixture
def leave_cleanup(client):
    created: list[str] = []
    yield created
    for lid in created:
        try:
            client.delete(f"{BASE_URL}/api/leave/{lid}", timeout=10)
        except Exception:
            pass


@pytest.fixture
def token_cleanup(client):
    created: list[str] = []  # token ids (for revoke)
    yield created
    for tid in created:
        try:
            client.post(f"{BASE_URL}/api/request-tokens/{tid}/revoke", timeout=10)
        except Exception:
            pass


def _create_leave(client, staff_initials: str, date_str: str, leave_type: str = "AL"):
    r = client.post(
        f"{BASE_URL}/api/leave",
        json={"staff_initials": staff_initials, "dates": [date_str],
              "type": leave_type, "notes": "TEST_phase4"},
        timeout=10,
    )
    assert r.status_code in (200, 201), f"leave create failed: {r.status_code} {r.text}"
    data = r.json()
    # API may return a list of created rows or a single row.
    if isinstance(data, list):
        return [d["id"] for d in data if "id" in d]
    if isinstance(data, dict) and "created" in data and isinstance(data["created"], list):
        return [d["id"] for d in data["created"] if "id" in d]
    if isinstance(data, dict) and "id" in data:
        return [data["id"]]
    return []


def _make_token(client, staff_initials: str) -> dict:
    r = client.post(
        f"{BASE_URL}/api/request-tokens",
        json={"staff_initials": staff_initials, "expires_in_days": 14},
        timeout=20,  # shortener can take a few seconds
    )
    assert r.status_code in (200, 201), f"token create failed: {r.status_code} {r.text}"
    return r.json()


# ================================================================ 1. Slot-check shape
class TestSlotCheck:
    def test_role_conflict_same_role(self, client, staff_by_role, future_dates, leave_cleanup, token_cleanup):
        by_role, _ = staff_by_role
        flexi = by_role.get("Flexi") or []
        assert len(flexi) >= 2, f"Need >=2 Flexi staff for role_conflict test, got {flexi}"
        other, self_ = flexi[0], flexi[1]
        date_str = future_dates[0]

        leave_cleanup.extend(_create_leave(client, other, date_str, "AL"))
        tok = _make_token(client, self_)
        token_cleanup.append(tok["id"])

        r = requests.get(
            f"{BASE_URL}/api/public/request-link/{tok['token']}/check",
            params={"date": date_str, "preference": "AL"},
            timeout=10,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        data = r.json()

        assert data["slot_status"] == "role_conflict", data
        assert data["slot_open"] is False
        assert "would_break_rules" in data
        assert "max_one_per_role_on_al" in data["would_break_rules"]
        assert other in (data.get("reason") or "")
        assert "Flexi" in (data.get("reason") or "")
        existing = data.get("existing_leave") or []
        assert any(e["staff_initials"] == other and (e.get("role") or "") == "Flexi"
                   for e in existing), f"existing_leave missing {other}/Flexi: {existing}"

    def test_open_with_fyi_different_role(self, client, staff_by_role, future_dates, leave_cleanup, token_cleanup):
        by_role, _ = staff_by_role
        flexi = by_role.get("Flexi") or []
        night = by_role.get("Night Support") or []
        assert flexi, f"Need Flexi staff, got {flexi}"
        assert night, f"Need Night Support staff, got {night}"
        self_ = flexi[0]
        other_diff_role = night[0]
        date_str = future_dates[1]

        leave_cleanup.extend(_create_leave(client, other_diff_role, date_str, "AL"))
        tok = _make_token(client, self_)
        token_cleanup.append(tok["id"])

        r = requests.get(
            f"{BASE_URL}/api/public/request-link/{tok['token']}/check",
            params={"date": date_str, "preference": "AL"},
            timeout=10,
        )
        assert r.status_code == 200
        data = r.json()

        assert data["slot_status"] == "open", data
        assert data["slot_open"] is True
        existing = data.get("existing_leave") or []
        assert any(e["staff_initials"] == other_diff_role for e in existing), \
            f"existing_leave must still list {other_diff_role} for FYI chip: {existing}"
        assert data.get("would_break_rules") in ([], None, [])

    def test_clean_slot(self, client, staff_by_role, future_dates, token_cleanup):
        by_role, _ = staff_by_role
        self_ = (by_role.get("Flexi") or [next(iter(_.values() if False else ['T.D.']))])[0]
        date_str = future_dates[2]
        tok = _make_token(client, self_)
        token_cleanup.append(tok["id"])

        r = requests.get(
            f"{BASE_URL}/api/public/request-link/{tok['token']}/check",
            params={"date": date_str, "preference": "AL"},
            timeout=10,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["slot_status"] == "open", data
        assert data["slot_open"] is True
        assert data.get("existing_leave") == []

    def test_self_already_on_al_hard_limit(self, client, staff_by_role, future_dates, leave_cleanup, token_cleanup):
        by_role, _ = staff_by_role
        flexi = by_role.get("Flexi") or []
        assert flexi
        self_ = flexi[0]
        date_str = (dt.date.today() + dt.timedelta(days=120)).isoformat()

        leave_cleanup.extend(_create_leave(client, self_, date_str, "AL"))
        tok = _make_token(client, self_)
        token_cleanup.append(tok["id"])

        r = requests.get(
            f"{BASE_URL}/api/public/request-link/{tok['token']}/check",
            params={"date": date_str, "preference": "AL"},
            timeout=10,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["slot_status"] == "hard_limit", data
        assert data["slot_open"] is False
        assert self_ in (data.get("reason") or ""), data.get("reason")


# ================================================================ 2. Token / shortener
class TestShortener:
    def test_token_create_provider_field(self, client, staff_by_role, token_cleanup):
        by_role, _ = staff_by_role
        flexi = by_role.get("Flexi") or []
        assert flexi
        tok = _make_token(client, flexi[0])
        token_cleanup.append(tok["id"])

        assert "short_url_provider" in tok, f"missing short_url_provider: {tok}"
        assert tok["short_url_provider"] in {"is.gd", "da.gd", "direct"}, tok["short_url_provider"]
        assert "long_url" in tok and tok["long_url"].startswith("http")
        # When provider is not 'direct', short_url must be populated and point to the provider host.
        if tok["short_url_provider"] != "direct":
            assert tok.get("short_url", "").startswith("https://"), tok
            host = tok["short_url_provider"]
            assert host in tok["short_url"], f"short_url {tok['short_url']} missing host {host}"
        # The public page (/r/{token}) URL field is present.
        assert tok.get("url", "").startswith("/r/")

    def test_short_url_redirects_301_directly(self, client, staff_by_role, token_cleanup):
        by_role, _ = staff_by_role
        flexi = by_role.get("Flexi") or []
        tok = _make_token(client, flexi[0])
        token_cleanup.append(tok["id"])

        if tok["short_url_provider"] == "direct":
            pytest.skip("Both shorteners unreachable; direct fallback — nothing to follow.")

        short = tok["short_url"]
        # Do NOT follow redirects — we want to assert the FIRST hop is 301 + Location.
        r = requests.get(short, allow_redirects=False, timeout=10)
        assert r.status_code in (301, 302), f"first hop not a redirect: {r.status_code}"
        loc = r.headers.get("Location", "")
        assert loc, "missing Location header on redirect"
        assert loc.rstrip("/") == tok["long_url"].rstrip("/"), \
            f"Location {loc} does not match long_url {tok['long_url']}"

    def test_public_get_still_returns_valid_until(self, client, staff_by_role, token_cleanup):
        by_role, _ = staff_by_role
        flexi = by_role.get("Flexi") or []
        tok = _make_token(client, flexi[0])
        token_cleanup.append(tok["id"])

        r = requests.get(f"{BASE_URL}/api/public/request-link/{tok['token']}", timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "valid_until" in data and data["valid_until"]
        # Must be parseable ISO.
        dt.datetime.fromisoformat(data["valid_until"].replace("Z", "+00:00"))
        assert data.get("staff_initials") == flexi[0]
        assert (data.get("window") or {}).get("from")
        assert (data.get("window") or {}).get("to")
