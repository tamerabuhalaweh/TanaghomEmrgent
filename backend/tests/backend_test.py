"""Backend API tests for AI Campaign Manager."""
import os
import pytest
import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else "https://campaign-forge-142.preview.emergentagent.com"
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@campaign.ai"
ADMIN_PASS = "Admin@12345"


# ---------- Fixtures ----------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data and "user" in data
    assert data["user"]["email"] == ADMIN_EMAIL
    assert data["user"]["role"] == "admin"
    return data["token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def event_id(admin_headers):
    payload = {
        "name": "TEST_MotazLive",
        "type": "motaz_live",
        "start_date": "2026-02-01",
        "end_date": "2026-02-03",
        "budget_planned": 5000.0,
        "ticket_price": 100.0,
    }
    r = requests.post(f"{API}/events", json=payload, headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture(scope="session")
def campaign_id(admin_headers, event_id):
    payload = {
        "event_id": event_id,
        "name": "TEST_Campaign",
        "goal": "conversion",
        "start_date": "2026-02-01",
        "end_date": "2026-02-03",
        "budget_planned": 2000.0,
        "platforms": ["instagram", "meta"],
    }
    r = requests.post(f"{API}/campaigns", json=payload, headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------- Auth ----------
class TestAuth:
    def test_login_and_me(self, admin_headers):
        r = requests.get(f"{API}/auth/me", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        me = r.json()
        assert me["email"] == ADMIN_EMAIL
        assert me["role"] == "admin"

    def test_login_bad_credentials(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"}, timeout=20)
        assert r.status_code == 401

    def test_me_without_token(self):
        r = requests.get(f"{API}/auth/me", timeout=20)
        assert r.status_code == 401


# ---------- Events CRUD ----------
class TestEvents:
    def test_list_events(self, admin_headers, event_id):
        r = requests.get(f"{API}/events", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert any(e["id"] == event_id for e in r.json())

    def test_get_event(self, admin_headers, event_id):
        r = requests.get(f"{API}/events/{event_id}", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert r.json()["id"] == event_id
        assert r.json()["name"] == "TEST_MotazLive"

    def test_patch_event(self, admin_headers, event_id):
        r = requests.patch(f"{API}/events/{event_id}", json={"budget_actual": 1500.0, "status": "live"},
                           headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert r.json()["budget_actual"] == 1500.0
        assert r.json()["status"] == "live"


# ---------- Campaigns ----------
class TestCampaigns:
    def test_list_campaigns_by_event(self, admin_headers, event_id, campaign_id):
        r = requests.get(f"{API}/events/{event_id}/campaigns", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert any(c["id"] == campaign_id for c in r.json())

    def test_patch_campaign(self, admin_headers, campaign_id):
        r = requests.patch(f"{API}/campaigns/{campaign_id}", json={"budget_actual": 700.0, "status": "active"},
                           headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert r.json()["budget_actual"] == 700.0


# ---------- Posts ----------
class TestPosts:
    post_id = None

    def test_create_post(self, admin_headers, campaign_id):
        payload = {
            "campaign_id": campaign_id,
            "platform": "instagram",
            "format": "carousel",
            "hook": "Hook line",
            "caption": "Test caption",
            "cta": "Sign up",
            "hashtags": ["#test", "#ai"],
        }
        r = requests.post(f"{API}/posts", json=payload, headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["campaign_id"] == campaign_id
        assert data["caption"] == "Test caption"
        assert data["reach"] > 0
        TestPosts.post_id = data["id"]

    def test_list_posts(self, admin_headers, campaign_id):
        r = requests.get(f"{API}/campaigns/{campaign_id}/posts", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert any(p["id"] == TestPosts.post_id for p in r.json())

    def test_patch_post_approve(self, admin_headers):
        r = requests.patch(f"{API}/posts/{TestPosts.post_id}", json={"status": "approved"},
                           headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert r.json()["status"] == "approved"


# ---------- LLM generation (real Emergent LLM call) ----------
class TestLLMGenerate:
    def test_generate_post_ideas(self, admin_headers):
        payload = {
            "prompt": "Promote a 2-day live event about AI in marketing for Arab entrepreneurs",
            "platforms": ["instagram", "linkedin"],
            "goal": "max_reach",
            "provider": "openai",
            "model": None,
            "n": 2,
            "language": "en",
        }
        r = requests.post(f"{API}/posts/generate", json=payload, headers=admin_headers, timeout=120)
        assert r.status_code == 200, f"LLM generate failed: {r.status_code} {r.text}"
        data = r.json()
        assert "ideas" in data
        ideas = data["ideas"]
        assert isinstance(ideas, list) and len(ideas) >= 1, f"No ideas returned: {data}"
        idea = ideas[0]
        # Basic shape checks (missing fields OK if server sets defaults)
        for key in ("platform", "caption"):
            assert key in idea, f"Missing key {key} in idea: {idea}"


# ---------- Settings: LLM keys ----------
class TestLLMKeys:
    key_id = None

    def test_add_llm_key(self, admin_headers):
        r = requests.post(f"{API}/settings/llm-keys", json={
            "provider": "openai", "api_key": "sk-testkey-abcdefghij1234567890", "label": "TEST_key"
        }, headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["provider"] == "openai"
        assert "sk-testkey" not in data["key_masked"] or "*" in data["key_masked"]  # masked
        TestLLMKeys.key_id = data["id"]

    def test_list_llm_keys(self, admin_headers):
        r = requests.get(f"{API}/settings/llm-keys", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert any(k["id"] == TestLLMKeys.key_id for k in r.json())

    def test_delete_llm_key(self, admin_headers):
        r = requests.delete(f"{API}/settings/llm-keys/{TestLLMKeys.key_id}", headers=admin_headers, timeout=20)
        assert r.status_code == 200


# ---------- Social Accounts ----------
class TestSocial:
    sid = None

    def test_add_social(self, admin_headers):
        r = requests.post(f"{API}/settings/social-accounts", json={
            "platform": "instagram", "handle": "@test", "access_token": "IGtoken-verylongstring12345"
        }, headers=admin_headers, timeout=20)
        assert r.status_code == 200
        TestSocial.sid = r.json()["id"]
        assert "•" in r.json()["token_masked"]

    def test_list_social(self, admin_headers):
        r = requests.get(f"{API}/settings/social-accounts", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert any(s["id"] == TestSocial.sid for s in r.json())

    def test_delete_social(self, admin_headers):
        r = requests.delete(f"{API}/settings/social-accounts/{TestSocial.sid}", headers=admin_headers, timeout=20)
        assert r.status_code == 200


# ---------- Integrations ----------
class TestIntegrations:
    iid = None

    def test_add_integration(self, admin_headers):
        r = requests.post(f"{API}/integrations", json={
            "kind": "gohighlevel", "label": "TEST_GHL", "api_key": "ghl_key_123456789"
        }, headers=admin_headers, timeout=20)
        assert r.status_code == 200
        TestIntegrations.iid = r.json()["id"]
        assert r.json()["kind"] == "gohighlevel"

    def test_list_integrations(self, admin_headers):
        r = requests.get(f"{API}/integrations", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert any(i["id"] == TestIntegrations.iid for i in r.json())

    def test_delete_integration(self, admin_headers):
        r = requests.delete(f"{API}/integrations/{TestIntegrations.iid}", headers=admin_headers, timeout=20)
        assert r.status_code == 200


# ---------- Users management + RBAC ----------
class TestUsersRBAC:
    user_id = None
    user_token = None

    def test_admin_create_user(self, admin_headers):
        r = requests.post(f"{API}/users", json={
            "email": "TEST_viewer@campaign.ai", "name": "Test Viewer",
            "password": "Viewer@12345", "role": "viewer"
        }, headers=admin_headers, timeout=20)
        # Allow re-run: 409 if already exists — clean up first via login
        if r.status_code == 409:
            login = requests.post(f"{API}/auth/login", json={"email": "TEST_viewer@campaign.ai", "password": "Viewer@12345"}, timeout=20)
            TestUsersRBAC.user_token = login.json()["token"]
            TestUsersRBAC.user_id = login.json()["user"]["id"]
            return
        assert r.status_code == 200, r.text
        TestUsersRBAC.user_id = r.json()["id"]

    def test_list_users_as_admin(self, admin_headers):
        r = requests.get(f"{API}/users", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_non_admin_cannot_list_users(self):
        # Login as viewer
        login = requests.post(f"{API}/auth/login", json={"email": "TEST_viewer@campaign.ai", "password": "Viewer@12345"}, timeout=20)
        assert login.status_code == 200
        token = login.json()["token"]
        r = requests.get(f"{API}/users", headers={"Authorization": f"Bearer {token}"}, timeout=20)
        assert r.status_code == 403

    def test_admin_patch_user(self, admin_headers):
        r = requests.patch(f"{API}/users/{TestUsersRBAC.user_id}", json={"name": "Updated Viewer"},
                           headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert r.json()["name"] == "Updated Viewer"

    def test_admin_delete_user(self, admin_headers):
        r = requests.delete(f"{API}/users/{TestUsersRBAC.user_id}", headers=admin_headers, timeout=20)
        assert r.status_code == 200


# ---------- Leads ----------
class TestLeads:
    lead_id = None

    def test_create_lead(self, admin_headers, event_id):
        r = requests.post(f"{API}/leads", json={
            "event_id": event_id, "name": "TEST_Lead", "email": "lead@x.com",
            "source": "form", "stage": "form_filled"
        }, headers=admin_headers, timeout=20)
        assert r.status_code == 200
        TestLeads.lead_id = r.json()["id"]

    def test_list_leads(self, admin_headers, event_id):
        r = requests.get(f"{API}/events/{event_id}/leads", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert any(l["id"] == TestLeads.lead_id for l in r.json())

    def test_patch_lead(self, admin_headers):
        r = requests.patch(f"{API}/leads/{TestLeads.lead_id}", json={"stage": "purchased"},
                           headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert r.json()["stage"] == "purchased"


# ---------- Dashboards ----------
class TestDashboard:
    def test_global(self, admin_headers):
        r = requests.get(f"{API}/dashboard/global", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        data = r.json()
        for k in ("events_count", "reach", "impressions", "trend", "total_leads"):
            assert k in data, f"Missing key {k}"
        assert isinstance(data["trend"], list) and len(data["trend"]) == 14

    def test_event_dashboard(self, admin_headers, event_id):
        r = requests.get(f"{API}/dashboard/event/{event_id}", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        data = r.json()
        for k in ("event", "reach", "revenue", "roi_percent", "platform_breakdown"):
            assert k in data
        assert isinstance(data["platform_breakdown"], list)


# ---------- Cleanup (runs last) ----------
class TestZCleanup:
    def test_delete_campaign(self, admin_headers, campaign_id):
        r = requests.delete(f"{API}/campaigns/{campaign_id}", headers=admin_headers, timeout=20)
        assert r.status_code == 200

    def test_delete_event(self, admin_headers, event_id):
        r = requests.delete(f"{API}/events/{event_id}", headers=admin_headers, timeout=20)
        assert r.status_code == 200
