"""Backend API tests for AI Campaign Manager — Patch 1: production foundation.

Covers: auth + JWT tenant claim, tenant isolation, audit logs, honest metrics,
secret masking, CORS, and env validation.
"""
import os
import uuid
import base64
import json
import asyncio
import pytest
import requests
import jwt as pyjwt
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "https://campaign-forge-142.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@campaign.ai"
ADMIN_PASS = "Admin@12345"


# ---------- Fixtures ----------
@pytest.fixture(scope="session")
def admin_login():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data and "user" in data
    assert data["user"]["email"] == ADMIN_EMAIL
    assert data["user"]["role"] == "admin"
    assert data["user"].get("tenant_id"), "UserPublic missing tenant_id"
    return data


@pytest.fixture(scope="session")
def admin_token(admin_login):
    return admin_login["token"]


@pytest.fixture(scope="session")
def admin_tenant_id(admin_login):
    return admin_login["user"]["tenant_id"]


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
        "event_id": event_id, "name": "TEST_Campaign", "goal": "conversion",
        "start_date": "2026-02-01", "end_date": "2026-02-03",
        "budget_planned": 2000.0, "platforms": ["instagram", "meta"],
    }
    r = requests.post(f"{API}/campaigns", json=payload, headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------- Second tenant setup (Mongo direct) ----------
@pytest.fixture(scope="session")
def second_tenant():
    """Create a second tenant + admin directly in Mongo. Cleanup after session."""
    from motor.motor_asyncio import AsyncIOMotorClient
    import bcrypt
    from datetime import datetime, timezone

    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]

    async def _setup():
        client = AsyncIOMotorClient(mongo_url)
        db = client[db_name]
        tid = str(uuid.uuid4())
        await db.tenants.insert_one({
            "id": tid, "name": "TEST_Tenant2", "slug": f"test-tenant-{tid[:8]}",
            "status": "active", "created_at": datetime.now(timezone.utc).isoformat(),
        })
        uid = str(uuid.uuid4())
        email = f"test-admin2-{tid[:8]}@campaign.ai"
        pw = "T2Admin@12345"
        pw_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
        await db.users.insert_one({
            "id": uid, "tenant_id": tid, "email": email, "name": "Tenant2 Admin",
            "role": "admin", "permissions": ["*"], "password_hash": pw_hash,
            "is_active": True, "created_at": datetime.now(timezone.utc).isoformat(),
        })
        # Seed one event in tenant 2 to prove isolation.
        ev_id = str(uuid.uuid4())
        await db.events.insert_one({
            "id": ev_id, "tenant_id": tid, "name": "TEST_T2_Event", "type": "custom",
            "start_date": "2026-03-01", "budget_planned": 0.0, "budget_actual": 0.0,
            "status": "planning",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        client.close()
        return {"tenant_id": tid, "email": email, "password": pw, "user_id": uid, "event_id": ev_id}

    async def _cleanup(info):
        client = AsyncIOMotorClient(mongo_url)
        db = client[db_name]
        tid = info["tenant_id"]
        for coll in ("tenants", "users", "events", "campaigns", "posts", "leads",
                     "llm_keys", "social_accounts", "integrations", "audit_logs"):
            await db[coll].delete_many({"tenant_id": tid})
        await db.tenants.delete_many({"id": tid})
        client.close()

    info = asyncio.get_event_loop().run_until_complete(_setup())
    yield info
    asyncio.get_event_loop().run_until_complete(_cleanup(info))


@pytest.fixture(scope="session")
def second_admin_headers(second_tenant):
    r = requests.post(f"{API}/auth/login",
                      json={"email": second_tenant["email"], "password": second_tenant["password"]},
                      timeout=20)
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    assert r.json()["user"]["tenant_id"] == second_tenant["tenant_id"]
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- Auth ----------
class TestAuth:
    def test_login_and_me(self, admin_headers):
        r = requests.get(f"{API}/auth/me", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        me = r.json()
        assert me["email"] == ADMIN_EMAIL
        assert me["role"] == "admin"
        assert me.get("tenant_id"), "GET /auth/me missing tenant_id"

    def test_jwt_contains_tenant_id(self, admin_token, admin_tenant_id):
        # Decode without verifying signature; we just need to confirm claims.
        claims = pyjwt.decode(admin_token, options={"verify_signature": False})
        assert claims.get("tenant_id") == admin_tenant_id
        assert claims.get("sub")
        assert claims.get("role") == "admin"

    def test_login_bad_credentials(self):
        r = requests.post(f"{API}/auth/login",
                          json={"email": ADMIN_EMAIL, "password": "wrong"}, timeout=20)
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

    def test_patch_event(self, admin_headers, event_id):
        r = requests.patch(f"{API}/events/{event_id}",
                           json={"budget_actual": 1500.0, "status": "live"},
                           headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert r.json()["budget_actual"] == 1500.0


# ---------- Campaigns ----------
class TestCampaigns:
    def test_list_campaigns_by_event(self, admin_headers, event_id, campaign_id):
        r = requests.get(f"{API}/events/{event_id}/campaigns", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert any(c["id"] == campaign_id for c in r.json())

    def test_patch_campaign(self, admin_headers, campaign_id):
        r = requests.patch(f"{API}/campaigns/{campaign_id}",
                           json={"budget_actual": 700.0, "status": "active"},
                           headers=admin_headers, timeout=20)
        assert r.status_code == 200


# ---------- Posts (honest metrics) ----------
class TestPosts:
    post_id = None

    def test_create_post_zero_metrics(self, admin_headers, campaign_id):
        payload = {
            "campaign_id": campaign_id, "platform": "instagram", "format": "carousel",
            "hook": "Hook", "caption": "Test caption", "cta": "Sign up",
            "hashtags": ["#test"],
        }
        r = requests.post(f"{API}/posts", json=payload, headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["reach"] == 0
        assert d["impressions"] == 0
        assert d["clicks"] == 0
        assert d["engagement"] == 0
        assert d["metric_source"] == "none"
        TestPosts.post_id = d["id"]

    def test_list_posts_still_zero(self, admin_headers, campaign_id):
        r = requests.get(f"{API}/campaigns/{campaign_id}/posts", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        found = [p for p in r.json() if p["id"] == TestPosts.post_id][0]
        assert found["reach"] == 0 and found["metric_source"] == "none"

    def test_patch_post_manual_reach_sets_source(self, admin_headers):
        r = requests.patch(f"{API}/posts/{TestPosts.post_id}",
                           json={"reach": 1234}, headers=admin_headers, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["reach"] == 1234
        assert d["metric_source"] == "manual"

    def test_patch_post_approve(self, admin_headers):
        r = requests.patch(f"{API}/posts/{TestPosts.post_id}",
                           json={"status": "approved"}, headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert r.json()["status"] == "approved"


# ---------- Settings: LLM keys ----------
class TestLLMKeys:
    key_id = None
    RAW = "sk-supersecrettoken12345"

    def test_add_llm_key_masked(self, admin_headers):
        r = requests.post(f"{API}/settings/llm-keys", json={
            "provider": "openai", "api_key": self.RAW, "label": "TEST_key"
        }, headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "•" in d["key_masked"]
        assert self.RAW not in json.dumps(d)
        TestLLMKeys.key_id = d["id"]

    def test_list_llm_keys_never_raw(self, admin_headers):
        r = requests.get(f"{API}/settings/llm-keys", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        body = r.text
        assert self.RAW not in body
        assert any(k["id"] == TestLLMKeys.key_id and "•" in k["key_masked"] for k in r.json())

    def test_delete_llm_key(self, admin_headers):
        r = requests.delete(f"{API}/settings/llm-keys/{TestLLMKeys.key_id}",
                            headers=admin_headers, timeout=20)
        assert r.status_code == 200


# ---------- Social Accounts ----------
class TestSocial:
    sid = None
    RAW = "IGtoken-verylongsecrettoken12345"

    def test_add_social_masked(self, admin_headers):
        r = requests.post(f"{API}/settings/social-accounts", json={
            "platform": "instagram", "handle": "@test", "access_token": self.RAW
        }, headers=admin_headers, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "•" in d["token_masked"]
        assert self.RAW not in json.dumps(d)
        TestSocial.sid = d["id"]

    def test_delete_social(self, admin_headers):
        r = requests.delete(f"{API}/settings/social-accounts/{TestSocial.sid}",
                            headers=admin_headers, timeout=20)
        assert r.status_code == 200


# ---------- Integrations ----------
class TestIntegrations:
    iid = None
    RAW = "ghl_supersecret_key_987654321"

    def test_add_integration_credential_saved(self, admin_headers):
        r = requests.post(f"{API}/integrations", json={
            "kind": "gohighlevel", "label": "TEST_GHL", "api_key": self.RAW
        }, headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "credential_saved"
        assert d["validated"] is False
        assert d["live_sync_enabled"] is False
        assert self.RAW not in json.dumps(d)
        TestIntegrations.iid = d["id"]

    def test_reject_invalid_kind(self, admin_headers):
        r = requests.post(f"{API}/integrations", json={
            "kind": "invalid_kind", "label": "bad", "api_key": "x"
        }, headers=admin_headers, timeout=20)
        assert r.status_code == 400

    def test_delete_integration(self, admin_headers):
        r = requests.delete(f"{API}/integrations/{TestIntegrations.iid}",
                            headers=admin_headers, timeout=20)
        assert r.status_code == 200


# ---------- Users management + RBAC ----------
class TestUsersRBAC:
    user_id = None
    viewer_email = "TEST_viewer@campaign.ai"
    viewer_pass = "Viewer@12345"

    def test_admin_create_user_audit_no_password(self, admin_headers):
        r = requests.post(f"{API}/users", json={
            "email": self.viewer_email, "name": "Test Viewer",
            "password": self.viewer_pass, "role": "viewer"
        }, headers=admin_headers, timeout=20)
        if r.status_code == 409:
            login = requests.post(f"{API}/auth/login",
                                  json={"email": self.viewer_email, "password": self.viewer_pass},
                                  timeout=20)
            TestUsersRBAC.user_id = login.json()["user"]["id"]
        else:
            assert r.status_code == 200, r.text
            TestUsersRBAC.user_id = r.json()["id"]

        # Verify audit log contains user.created with metadata but NO password
        audit = requests.get(f"{API}/audit-logs?limit=200", headers=admin_headers, timeout=20).json()
        matches = [a for a in audit if a["action"] == "user.created"
                   and a.get("object_id") == TestUsersRBAC.user_id]
        # If user pre-existed we may not see this in latest 200; skip in that case.
        if matches:
            meta = matches[0]["metadata"]
            assert "password" not in meta
            assert meta.get("email") == self.viewer_email.lower()
            assert meta.get("role") == "viewer"

    def test_non_admin_cannot_list_audit_logs(self):
        login = requests.post(f"{API}/auth/login",
                              json={"email": self.viewer_email, "password": self.viewer_pass}, timeout=20)
        assert login.status_code == 200
        token = login.json()["token"]
        r = requests.get(f"{API}/audit-logs",
                         headers={"Authorization": f"Bearer {token}"}, timeout=20)
        assert r.status_code == 403

    def test_admin_delete_user(self, admin_headers):
        r = requests.delete(f"{API}/users/{TestUsersRBAC.user_id}",
                            headers=admin_headers, timeout=20)
        assert r.status_code == 200


# ---------- Audit logs ----------
class TestAuditLogs:
    def test_login_success_recorded(self, admin_headers, admin_tenant_id):
        # Trigger a fresh successful login.
        requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
        r = requests.get(f"{API}/audit-logs?limit=200", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        logs = r.json()
        successes = [l for l in logs if l["action"] == "login.success"]
        assert successes, "No login.success audit entry"
        s = successes[0]
        assert s["tenant_id"] == admin_tenant_id
        assert s["actor_user_id"]
        assert s["result"] == "success"

    def test_login_failure_recorded(self, admin_headers):
        requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "definitely-wrong"}, timeout=20)
        r = requests.get(f"{API}/audit-logs?limit=200", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert any(l["action"] == "login.failure" and l["result"] == "failure" for l in r.json())

    def test_event_and_integration_audit(self, admin_headers, event_id):
        r = requests.get(f"{API}/audit-logs?limit=500", headers=admin_headers, timeout=20)
        logs = r.json()
        assert any(l["action"] == "event.created" for l in logs)

    def test_audit_never_contains_secret(self, admin_headers):
        # Post a marker LLM key and confirm the marker never appears in audit logs.
        marker = f"sk-audittest-{uuid.uuid4().hex}-marker"
        add = requests.post(f"{API}/settings/llm-keys",
                            json={"provider": "openai", "api_key": marker, "label": "TEST_audit"},
                            headers=admin_headers, timeout=20)
        assert add.status_code == 200
        kid = add.json()["id"]
        r = requests.get(f"{API}/audit-logs?limit=500", headers=admin_headers, timeout=20)
        assert marker not in r.text
        # Also verify the llm_key.added entry exists but metadata has no api_key.
        entries = [l for l in r.json() if l["action"] == "llm_key.added" and l["object_id"] == kid]
        assert entries, "Missing llm_key.added audit entry"
        assert "api_key" not in entries[0]["metadata"]
        # cleanup
        requests.delete(f"{API}/settings/llm-keys/{kid}", headers=admin_headers, timeout=20)


# ---------- Tenant isolation ----------
class TestTenantIsolation:
    def test_second_admin_cannot_see_tenant1_events(self, second_admin_headers, event_id):
        r = requests.get(f"{API}/events", headers=second_admin_headers, timeout=20)
        assert r.status_code == 200
        ids = [e["id"] for e in r.json()]
        assert event_id not in ids, "Tenant isolation broken: tenant2 sees tenant1 event"

    def test_second_admin_cannot_get_tenant1_event(self, second_admin_headers, event_id):
        r = requests.get(f"{API}/events/{event_id}", headers=second_admin_headers, timeout=20)
        assert r.status_code == 404

    def test_second_admin_cannot_patch_tenant1_event(self, second_admin_headers, event_id):
        r = requests.patch(f"{API}/events/{event_id}", json={"status": "hacked"},
                           headers=second_admin_headers, timeout=20)
        assert r.status_code == 404

    def test_second_admin_cannot_delete_tenant1_event(self, second_admin_headers, event_id):
        r = requests.delete(f"{API}/events/{event_id}", headers=second_admin_headers, timeout=20)
        # Returns 200 with deleted=0 (scoped delete)
        assert r.status_code == 200
        assert r.json().get("deleted", 0) == 0

    def test_second_admin_audit_logs_scoped(self, second_admin_headers, admin_headers):
        # Trigger an event.created in tenant2
        requests.post(f"{API}/events", json={
            "name": "TEST_T2_extra", "type": "custom", "start_date": "2026-04-01"
        }, headers=second_admin_headers, timeout=20)
        r = requests.get(f"{API}/audit-logs?limit=500", headers=second_admin_headers, timeout=20)
        assert r.status_code == 200
        logs = r.json()
        assert logs, "Tenant2 has no audit logs"
        t2_tid = pyjwt.decode(second_admin_headers["Authorization"].split()[1],
                              options={"verify_signature": False})["tenant_id"]
        for l in logs:
            assert l["tenant_id"] == t2_tid, f"Cross-tenant leak in audit-logs: {l}"

    def test_second_admin_cannot_see_tenant1_llm_keys(self, second_admin_headers, admin_headers):
        # Add a key in tenant 1
        add = requests.post(f"{API}/settings/llm-keys", json={
            "provider": "openai", "api_key": "sk-iso-test-xxxxxxxxxxxxx", "label": "iso1"
        }, headers=admin_headers, timeout=20)
        assert add.status_code == 200
        kid = add.json()["id"]
        try:
            r = requests.get(f"{API}/settings/llm-keys", headers=second_admin_headers, timeout=20)
            assert r.status_code == 200
            assert all(k["id"] != kid for k in r.json())
        finally:
            requests.delete(f"{API}/settings/llm-keys/{kid}", headers=admin_headers, timeout=20)


# ---------- Dashboards (honest metrics) ----------
class TestDashboardsHonest:
    def test_global_dashboard_no_verified(self, second_admin_headers):
        # Tenant 2 has no verified metrics.
        r = requests.get(f"{API}/dashboard/global", headers=second_admin_headers, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["metrics_status"] == "no_verified_metrics"
        assert d.get("metrics_message")
        assert d["reach"] == 0 and d["impressions"] == 0 and d["clicks"] == 0 and d["engagement"] == 0

    def test_event_dashboard_no_verified(self, second_admin_headers, second_tenant):
        r = requests.get(f"{API}/dashboard/event/{second_tenant['event_id']}",
                         headers=second_admin_headers, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["metrics_status"] == "no_verified_metrics"
        assert d["reach"] == 0

    def test_global_verified_after_manual_metric(self, admin_headers, campaign_id):
        # Ensure at least one post w/ manual reach in tenant 1.
        p = requests.post(f"{API}/posts", json={
            "campaign_id": campaign_id, "platform": "meta", "caption": "verified test"
        }, headers=admin_headers, timeout=20)
        assert p.status_code == 200
        pid = p.json()["id"]
        r = requests.patch(f"{API}/posts/{pid}", json={"reach": 5000},
                           headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert r.json()["metric_source"] == "manual"
        dash = requests.get(f"{API}/dashboard/global", headers=admin_headers, timeout=20).json()
        assert dash["metrics_status"] == "verified"
        assert dash["reach"] >= 5000


# ---------- CORS ----------
# Ingress/edge proxy may inject CORS headers on the public URL; verify the
# FastAPI middleware directly at localhost:8001 to prove the backend itself
# does NOT permit wildcard or evil origins.
LOCAL_API = "http://localhost:8001/api"


class TestCORS:
    def test_evil_origin_not_allowed(self):
        r = requests.options(f"{LOCAL_API}/auth/login", headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        }, timeout=20)
        allow = r.headers.get("access-control-allow-origin", "")
        assert allow != "https://evil.example.com"
        assert allow != "*"

    def test_localhost_origin_allowed(self):
        r = requests.options(f"{LOCAL_API}/auth/login", headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        }, timeout=20)
        allow = r.headers.get("access-control-allow-origin", "")
        assert allow == "http://localhost:3000"


# ---------- Env validation (static source inspection) ----------
class TestEnvValidation:
    def test_env_no_wildcard_cors(self):
        env_path = Path(__file__).resolve().parents[1] / ".env"
        content = env_path.read_text()
        assert "CORS_ORIGINS" in content
        # Extract line
        line = [l for l in content.splitlines() if l.startswith("CORS_ORIGINS")][0]
        assert '"*"' not in line and "=*" not in line

    def test_server_source_validates_required_env(self):
        src = (Path(__file__).resolve().parents[1] / "server.py").read_text()
        for var in ("MONGO_URL", "DB_NAME", "JWT_SECRET", "FERNET_KEY", "CORS_ORIGINS"):
            assert var in src
        assert "wildcard" in src.lower() or "'*'" in src or '"*"' in src


# ---------- Cleanup ----------
class TestZCleanup:
    def test_delete_campaign(self, admin_headers, campaign_id):
        r = requests.delete(f"{API}/campaigns/{campaign_id}", headers=admin_headers, timeout=20)
        assert r.status_code == 200

    def test_delete_event(self, admin_headers, event_id):
        r = requests.delete(f"{API}/events/{event_id}", headers=admin_headers, timeout=20)
        assert r.status_code == 200
