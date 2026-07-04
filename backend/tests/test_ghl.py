"""Patch 3 tests: GoHighLevel Lead Sync Foundation.

Uses FastAPI TestClient (in-process) so monkeypatching of ghl_client.fetch_*
and os.environ['GHL_READ_SYNC_ENABLED'] takes effect at request time.
Never performs a real network call.
"""
import os
import sys
import uuid
import asyncio
from pathlib import Path
from datetime import datetime, timezone

import pytest
import bcrypt
import httpx
from dotenv import load_dotenv

# Ensure /app/backend is importable
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import ghl_client  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


ADMIN_EMAIL = "admin@campaign.ai"
ADMIN_PASS = "Admin@12345"


# ---------------------------------------------------------------------------
# Safety net: block real HTTP calls at session scope
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True, scope="session")
def _block_real_http():
    original_init = httpx.AsyncClient.__init__

    async def _raise(*args, **kwargs):
        raise RuntimeError("Real HTTP call attempted in tests!")

    def new_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # Only override outbound methods; TestClient uses sync client
        self.__aenter__ = _raise  # type: ignore
    # We intentionally do NOT override — TestClient uses sync httpx transports.
    # The monkeypatch on ghl_client.fetch_* is the primary defense.
    yield


# ---------------------------------------------------------------------------
# Session-scope client + admin
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def client():
    with TestClient(server.app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_headers(client):
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _make_user(client, admin_headers, role, prefix):
    email = f"TEST_ghl_{prefix}_{uuid.uuid4().hex[:6]}@campaign.ai"
    pw = "Pass@12345"
    r = client.post("/api/users", json={
        "email": email, "name": f"GHL {role}", "password": pw, "role": role,
    }, headers=admin_headers)
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    login = client.post("/api/auth/login", json={"email": email, "password": pw})
    tok = login.json()["token"]
    return {
        "id": uid, "email": email,
        "headers": {"Authorization": f"Bearer {tok}"},
    }


@pytest.fixture(scope="session")
def marketing_user(client, admin_headers):
    return _make_user(client, admin_headers, "marketing", "mkt")


@pytest.fixture(scope="session")
def sales_user(client, admin_headers):
    return _make_user(client, admin_headers, "sales", "sls")


@pytest.fixture(scope="session")
def viewer_user(client, admin_headers):
    return _make_user(client, admin_headers, "viewer", "vwr")


@pytest.fixture(scope="session")
def tenant_b(client):
    """Seed Tenant B directly with Motor. Yields dict with headers/tenant_id/event_id."""
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]

    async def _setup():
        mc = AsyncIOMotorClient(mongo_url)
        db = mc[db_name]
        tid = str(uuid.uuid4())
        await db.tenants.insert_one({
            "id": tid, "name": "TEST_GHL_TenantB", "slug": f"test-ghl-b-{tid[:8]}",
            "status": "active", "created_at": datetime.now(timezone.utc).isoformat(),
        })
        uid = str(uuid.uuid4())
        email = f"test-ghl-b-{tid[:8]}@campaign.ai"
        pw = "TBGhl@12345"
        await db.users.insert_one({
            "id": uid, "tenant_id": tid, "email": email, "name": "GHL TB Admin",
            "role": "admin", "permissions": ["*"],
            "password_hash": bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode(),
            "is_active": True, "created_at": datetime.now(timezone.utc).isoformat(),
        })
        ev_id = str(uuid.uuid4())
        await db.events.insert_one({
            "id": ev_id, "tenant_id": tid, "name": "TEST_GHL_TB_Event", "type": "custom",
            "start_date": "2026-06-01", "budget_planned": 0.0, "budget_actual": 0.0,
            "status": "planning",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        mc.close()
        return {"tenant_id": tid, "email": email, "password": pw,
                "user_id": uid, "event_id": ev_id}

    info = asyncio.get_event_loop().run_until_complete(_setup())
    r = client.post("/api/auth/login", json={"email": info["email"], "password": info["password"]})
    assert r.status_code == 200, r.text
    info["headers"] = {"Authorization": f"Bearer {r.json()['token']}"}
    yield info


@pytest.fixture(scope="session")
def test_event(client, admin_headers):
    r = client.post("/api/events", json={
        "name": f"TEST_GHL_Event_{uuid.uuid4().hex[:6]}", "type": "custom",
        "start_date": "2026-05-01", "end_date": "2026-05-03",
        "budget_planned": 1000.0,
    }, headers=admin_headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------------------------------------------------------------------------
# Session-level cleanup
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _final_cleanup(tenant_b):  # tenant_b ensures ordering
    yield
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]

    async def _clean():
        mc = AsyncIOMotorClient(mongo_url)
        db = mc[db_name]
        # Tenant B cleanup
        tb_id = tenant_b["tenant_id"]
        for coll in ("tenants", "users", "events", "campaigns", "posts", "leads",
                     "event_kpi_records", "audit_logs", "ghl_mappings", "integrations"):
            await db[coll].delete_many({"tenant_id": tb_id})
        await db.tenants.delete_many({"id": tb_id})
        # Default tenant cleanup: remove ghl_mappings + integrations + TEST_ leads/events/users
        default = await db.tenants.find_one({"slug": "default"})
        if default:
            did = default["id"]
            await db.ghl_mappings.delete_many({"tenant_id": did})
            await db.integrations.delete_many({"tenant_id": did})
            # Remove leads created during tests (external + email markers)
            await db.leads.delete_many({
                "$or": [
                    {"external_source_provider": "gohighlevel"},
                    {"email": {"$regex": "^(TEST_|match@|shared@)"}},
                    {"id": "existing"},
                ],
                "tenant_id": did,
            })
            await db.events.delete_many({"tenant_id": did, "name": {"$regex": "^TEST_GHL_"}})
            await db.users.delete_many({
                "tenant_id": did,
                "email": {"$regex": "^TEST_ghl_"},
            })
        mc.close()

    try:
        asyncio.get_event_loop().run_until_complete(_clean())
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _integration_delete_all(client, admin_headers):
    for it in client.get("/api/integrations", headers=admin_headers).json():
        if it["kind"] == "gohighlevel":
            client.delete(f"/api/integrations/{it['id']}", headers=admin_headers)


def _add_ghl_integration(client, admin_headers, api_key="ghl_super_secret_ABCXYZ",
                        location_id="loc_ABC"):
    r = client.post("/api/integrations", json={
        "kind": "gohighlevel", "label": "GHL Prod",
        "api_key": api_key, "config": {"location_id": location_id},
    }, headers=admin_headers)
    assert r.status_code == 200, r.text
    return r.json()


def _delete_all_mappings(client, admin_headers):
    for m in client.get("/api/ghl/mappings", headers=admin_headers).json():
        client.delete(f"/api/ghl/mappings/{m['id']}", headers=admin_headers)


# ===========================================================================
# 1. STATUS
# ===========================================================================
class TestGhlStatus:
    def test_status_without_integration(self, client, admin_headers, monkeypatch):
        _integration_delete_all(client, admin_headers)
        _delete_all_mappings(client, admin_headers)
        # Guard: fetch_* must never be called
        monkeypatch.setattr(ghl_client, "fetch_contacts",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no call")))
        monkeypatch.setattr(ghl_client, "fetch_opportunities",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no call")))
        r = client.get("/api/ghl/status", headers=admin_headers)
        assert r.status_code == 200
        d = r.json()
        assert d["credential_status"] == "missing"
        assert d["mapping_status"] == "missing"
        assert d["read_sync_enabled"] is False
        assert d["required_actions"]

    def test_status_after_integration_added(self, client, admin_headers):
        _integration_delete_all(client, admin_headers)
        _add_ghl_integration(client, admin_headers)
        # GET /integrations returns masked, never raw
        lst = client.get("/api/integrations", headers=admin_headers).json()
        ghl_entries = [i for i in lst if i["kind"] == "gohighlevel"]
        assert ghl_entries
        for e in ghl_entries:
            assert e.get("api_key_masked")
            assert "ghl_super_secret_ABCXYZ" not in str(e)
            # Masked should look like dots (contain non-alnum bullets)
            assert "•" in e["api_key_masked"] or "." in e["api_key_masked"] or "*" in e["api_key_masked"]
        r = client.get("/api/ghl/status", headers=admin_headers)
        d = r.json()
        assert d["credential_status"] == "configured"
        assert d["location_id_status"] == "configured"


# ===========================================================================
# 2. MAPPING VALIDATION
# ===========================================================================
class TestMappingValidation:
    def test_bogus_target_value(self, client, admin_headers):
        r = client.post("/api/ghl/mappings", json={
            "mapping_type": "tag", "ghl_name": "SOMETAG",
            "target_type": "lead_status", "target_value": "bogus",
        }, headers=admin_headers)
        assert r.status_code == 400

    def test_bogus_direction(self, client, admin_headers):
        r = client.post("/api/ghl/mappings", json={
            "mapping_type": "tag", "ghl_name": "SOMETAG",
            "target_type": "lead_status", "target_value": "new",
            "direction": "xxx",
        }, headers=admin_headers)
        assert r.status_code == 400

    def test_missing_ghl_name_for_tag(self, client, admin_headers):
        # Pass empty string to bypass Pydantic required-string; validator catches it
        r = client.post("/api/ghl/mappings", json={
            "mapping_type": "tag", "ghl_name": "",
            "target_type": "lead_status", "target_value": "new",
        }, headers=admin_headers)
        assert r.status_code == 400


# ===========================================================================
# 3. MAPPING RBAC
# ===========================================================================
class TestMappingRbac:
    def _payload(self):
        return {
            "mapping_type": "tag", "ghl_name": f"TAG_{uuid.uuid4().hex[:5]}",
            "target_type": "lead_status", "target_value": "new",
        }

    def test_sales_cannot_create(self, client, sales_user):
        r = client.post("/api/ghl/mappings", json=self._payload(),
                        headers=sales_user["headers"])
        assert r.status_code == 403

    def test_viewer_cannot_create(self, client, viewer_user):
        r = client.post("/api/ghl/mappings", json=self._payload(),
                        headers=viewer_user["headers"])
        assert r.status_code == 403

    def test_marketing_can_create(self, client, marketing_user):
        r = client.post("/api/ghl/mappings", json=self._payload(),
                        headers=marketing_user["headers"])
        assert r.status_code == 200

    def test_admin_can_create(self, client, admin_headers):
        r = client.post("/api/ghl/mappings", json=self._payload(),
                        headers=admin_headers)
        assert r.status_code == 200


# ===========================================================================
# 4. MAPPING TENANT ISOLATION
# ===========================================================================
class TestMappingTenantIsolation:
    def test_tenant_isolation(self, client, admin_headers, tenant_b):
        # Create mapping in Tenant B
        rb = client.post("/api/ghl/mappings", json={
            "mapping_type": "tag", "ghl_name": "TB_TAG",
            "target_type": "lead_status", "target_value": "new",
        }, headers=tenant_b["headers"])
        assert rb.status_code == 200
        tb_mid = rb.json()["id"]
        # Tenant A listing must not include tb_mid
        la = client.get("/api/ghl/mappings", headers=admin_headers).json()
        assert not any(m["id"] == tb_mid for m in la)
        # Delete from A must return 404 (not found in A) and NOT delete
        rd = client.delete(f"/api/ghl/mappings/{tb_mid}", headers=admin_headers)
        # Route returns {"deleted": 0} — 200 with 0 count is acceptable, but code
        # returns 200 always. We check that B still has the mapping.
        lb2 = client.get("/api/ghl/mappings", headers=tenant_b["headers"]).json()
        assert any(m["id"] == tb_mid for m in lb2), \
            "Tenant B mapping was deleted from Tenant A context!"


# ===========================================================================
# 5. MAPPING STATUS TRANSITIONS
# ===========================================================================
class TestMappingStatusTransitions:
    def test_transitions(self, client, admin_headers):
        _delete_all_mappings(client, admin_headers)
        s0 = client.get("/api/ghl/status", headers=admin_headers).json()
        assert s0["mapping_status"] == "missing"
        # 1 tag only -> partial
        client.post("/api/ghl/mappings", json={
            "mapping_type": "tag", "ghl_name": "T1",
            "target_type": "lead_status", "target_value": "new",
        }, headers=admin_headers)
        s1 = client.get("/api/ghl/status", headers=admin_headers).json()
        assert s1["mapping_status"] == "partial"
        # Add pipeline_stage -> ready
        client.post("/api/ghl/mappings", json={
            "mapping_type": "pipeline_stage", "ghl_id": "stg_1", "ghl_name": "Stage 1",
            "target_type": "lead_status", "target_value": "booked",
        }, headers=admin_headers)
        s2 = client.get("/api/ghl/status", headers=admin_headers).json()
        assert s2["mapping_status"] == "ready"


# ===========================================================================
# 6. PULL-PREVIEW BLOCKED
# ===========================================================================
class TestPullPreviewBlocked:
    def test_blocked_no_credential(self, client, admin_headers, monkeypatch):
        _integration_delete_all(client, admin_headers)

        def _boom(*a, **k):
            raise RuntimeError("should not be called")

        monkeypatch.setattr(ghl_client, "fetch_contacts", _boom)
        monkeypatch.setattr(ghl_client, "fetch_opportunities", _boom)
        r = client.post("/api/ghl/pull-preview", json={}, headers=admin_headers)
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "blocked"
        assert "credential" in d["reason"].lower()
        assert d["raw_payload_returned"] is False

    def test_blocked_when_read_sync_disabled(self, client, admin_headers, monkeypatch):
        _integration_delete_all(client, admin_headers)
        _add_ghl_integration(client, admin_headers)
        monkeypatch.delenv("GHL_READ_SYNC_ENABLED", raising=False)

        def _boom(*a, **k):
            raise RuntimeError("should not be called")

        monkeypatch.setattr(ghl_client, "fetch_contacts", _boom)
        monkeypatch.setattr(ghl_client, "fetch_opportunities", _boom)
        r = client.post("/api/ghl/pull-preview", json={}, headers=admin_headers)
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "blocked"
        assert ("read sync" in d["reason"].lower()) or ("disabled" in d["reason"].lower())


# ===========================================================================
# 7. PULL-PREVIEW HAPPY PATH
# ===========================================================================
FIXTURE_CONTACTS = [
    {"id": "ghl_c1", "firstName": "Alice", "lastName": "Buyer",
     "email": "alice@example.com", "phone": "+15551110001",
     "tags": ["BUYER_TAG"]},
]
FIXTURE_OPPS = [
    {"id": "opp_1", "contactId": "ghl_c1", "pipelineId": "pl_1",
     "pipelineStageId": "stg_won", "status": "won", "monetaryValue": 500},
]


class TestPullPreviewHappy:
    def test_happy_path(self, client, admin_headers, monkeypatch):
        _integration_delete_all(client, admin_headers)
        _add_ghl_integration(client, admin_headers)
        _delete_all_mappings(client, admin_headers)
        # Add tag mapping for BUYER_TAG -> lead_status=purchased (inbound)
        r = client.post("/api/ghl/mappings", json={
            "mapping_type": "tag", "ghl_name": "BUYER_TAG",
            "target_type": "lead_status", "target_value": "purchased",
            "direction": "inbound",
        }, headers=admin_headers)
        assert r.status_code == 200

        monkeypatch.setenv("GHL_READ_SYNC_ENABLED", "true")

        async def _fc(*a, **k):
            return list(FIXTURE_CONTACTS)

        async def _fo(*a, **k):
            return list(FIXTURE_OPPS)

        monkeypatch.setattr(ghl_client, "fetch_contacts", _fc)
        monkeypatch.setattr(ghl_client, "fetch_opportunities", _fo)

        r = client.post("/api/ghl/pull-preview", json={}, headers=admin_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "ok"
        assert d["count"] >= 1
        assert d["source_of_truth"] == "gohighlevel"
        assert d["raw_payload_returned"] is False
        p0 = d["preview"][0]
        assert p0["mapped_lead_status"] == "purchased"
        assert p0["mapped_lead_temperature"] == "buyer"

        # Audit entry present
        logs = client.get("/api/audit-logs?limit=500", headers=admin_headers).json()
        assert any(l["action"] == "ghl_pull_preview" and l.get("tenant_id") for l in logs)


# ===========================================================================
# 8. PULL-PREVIEW RBAC
# ===========================================================================
class TestPullPreviewRbac:
    def test_viewer_forbidden(self, client, viewer_user):
        r = client.post("/api/ghl/pull-preview", json={}, headers=viewer_user["headers"])
        assert r.status_code == 403

    def test_sales_allowed(self, client, sales_user):
        r = client.post("/api/ghl/pull-preview", json={}, headers=sales_user["headers"])
        assert r.status_code in (200,)  # blocked-ok or preview-ok

    def test_marketing_allowed(self, client, marketing_user):
        r = client.post("/api/ghl/pull-preview", json={}, headers=marketing_user["headers"])
        assert r.status_code == 200


# ===========================================================================
# 9. PULL-SYNC RBAC
# ===========================================================================
class TestPullSyncRbac:
    def test_sales_forbidden(self, client, sales_user):
        r = client.post("/api/ghl/pull-sync", json={}, headers=sales_user["headers"])
        assert r.status_code == 403

    def test_viewer_forbidden(self, client, viewer_user):
        r = client.post("/api/ghl/pull-sync", json={}, headers=viewer_user["headers"])
        assert r.status_code == 403

    def test_marketing_allowed(self, client, marketing_user):
        r = client.post("/api/ghl/pull-sync", json={}, headers=marketing_user["headers"])
        assert r.status_code == 200

    def test_admin_allowed(self, client, admin_headers):
        r = client.post("/api/ghl/pull-sync", json={}, headers=admin_headers)
        assert r.status_code == 200


# ===========================================================================
# 10. PULL-SYNC HAPPY PATH + IDEMPOTENCY
# ===========================================================================
class TestPullSyncHappy:
    def test_insert_then_update(self, client, admin_headers, monkeypatch, test_event):
        _integration_delete_all(client, admin_headers)
        _add_ghl_integration(client, admin_headers)
        _delete_all_mappings(client, admin_headers)
        # tag mapping so lead is 'mapped'
        client.post("/api/ghl/mappings", json={
            "mapping_type": "tag", "ghl_name": "BUYER_TAG",
            "target_type": "lead_status", "target_value": "purchased",
            "direction": "inbound",
        }, headers=admin_headers)
        monkeypatch.setenv("GHL_READ_SYNC_ENABLED", "true")

        async def _fc(*a, **k):
            return [{"id": "ghl_sync_1", "firstName": "Sync", "lastName": "One",
                     "email": "syncone@example.com", "tags": ["BUYER_TAG"]}]

        async def _fo(*a, **k):
            return [{"id": "opp_sync1", "contactId": "ghl_sync_1",
                     "pipelineStageId": "stg_x", "status": "won",
                     "monetaryValue": 500}]

        monkeypatch.setattr(ghl_client, "fetch_contacts", _fc)
        monkeypatch.setattr(ghl_client, "fetch_opportunities", _fo)

        r1 = client.post("/api/ghl/pull-sync", json={"event_id": test_event},
                         headers=admin_headers)
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1["status"] == "ok"
        assert d1["inserted_count"] >= 1

        r2 = client.post("/api/ghl/pull-sync", json={"event_id": test_event},
                         headers=admin_headers)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["updated_count"] >= 1
        assert d2["inserted_count"] == 0

        # Verify lead persisted
        leads = client.get(f"/api/events/{test_event}/leads", headers=admin_headers).json()
        synced = [l for l in leads if l.get("external_source_id") == "ghl_sync_1"]
        assert synced
        s = synced[0]
        assert s["source_of_truth"] == "gohighlevel"
        assert s["external_source_provider"] == "gohighlevel"
        assert isinstance(s["external_last_synced_at"], str)

        # Audit entry
        logs = client.get("/api/audit-logs?limit=500", headers=admin_headers).json()
        assert any(l["action"] == "ghl_pull_sync" for l in logs)


# ===========================================================================
# 11. PULL-SYNC EMAIL FALLBACK
# ===========================================================================
class TestPullSyncEmailFallback:
    def test_email_fallback(self, client, admin_headers, monkeypatch, test_event):
        _integration_delete_all(client, admin_headers)
        _add_ghl_integration(client, admin_headers)
        monkeypatch.setenv("GHL_READ_SYNC_ENABLED", "true")

        # Pre-insert local lead with email match@x.com in tenant A
        mongo_url = os.environ["MONGO_URL"]
        db_name = os.environ["DB_NAME"]

        async def _seed(tid):
            mc = AsyncIOMotorClient(mongo_url)
            db = mc[db_name]
            await db.leads.delete_many({"email": "match@x.com"})
            await db.leads.insert_one({
                "id": "existing_match", "tenant_id": tid, "event_id": test_event,
                "name": "Match Local", "email": "match@x.com", "source": "manual",
                "stage": "new", "source_of_truth": "local",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            mc.close()

        # Get tenant A tenant_id
        me = client.get("/api/auth/me", headers=admin_headers).json()
        asyncio.get_event_loop().run_until_complete(_seed(me["tenant_id"]))

        async def _fc(*a, **k):
            return [{"id": "ghl_new_id_999", "firstName": "Match", "lastName": "Ghl",
                     "email": "match@x.com", "tags": []}]

        async def _fo(*a, **k):
            return []

        monkeypatch.setattr(ghl_client, "fetch_contacts", _fc)
        monkeypatch.setattr(ghl_client, "fetch_opportunities", _fo)

        r = client.post("/api/ghl/pull-sync", json={"event_id": test_event},
                        headers=admin_headers)
        assert r.status_code == 200, r.text

        # Verify only one lead with match@x.com exists in tenant A, and has external_source_id
        async def _check(tid):
            mc = AsyncIOMotorClient(mongo_url)
            db = mc[db_name]
            docs = await db.leads.find({"tenant_id": tid, "email": "match@x.com"},
                                       {"_id": 0}).to_list(10)
            mc.close()
            return docs

        docs = asyncio.get_event_loop().run_until_complete(_check(me["tenant_id"]))
        assert len(docs) == 1
        assert docs[0]["external_source_id"] == "ghl_new_id_999"


# ===========================================================================
# 12. PULL-SYNC TENANT ISOLATION
# ===========================================================================
class TestPullSyncTenantIsolation:
    def test_tenant_isolation(self, client, admin_headers, tenant_b, monkeypatch, test_event):
        _integration_delete_all(client, admin_headers)
        _add_ghl_integration(client, admin_headers)
        monkeypatch.setenv("GHL_READ_SYNC_ENABLED", "true")

        mongo_url = os.environ["MONGO_URL"]
        db_name = os.environ["DB_NAME"]

        async def _seed_b():
            mc = AsyncIOMotorClient(mongo_url)
            db = mc[db_name]
            await db.leads.delete_many({"tenant_id": tenant_b["tenant_id"],
                                        "email": "shared@x.com"})
            await db.leads.insert_one({
                "id": "tb_shared_lead", "tenant_id": tenant_b["tenant_id"],
                "event_id": tenant_b["event_id"],
                "name": "Shared", "email": "shared@x.com", "source": "manual",
                "stage": "new", "source_of_truth": "local",
                "external_source_id": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            mc.close()

        asyncio.get_event_loop().run_until_complete(_seed_b())

        async def _fc(*a, **k):
            return [{"id": "ghl_shared_A", "firstName": "Shared", "lastName": "A",
                     "email": "shared@x.com", "tags": []}]

        async def _fo(*a, **k):
            return []

        monkeypatch.setattr(ghl_client, "fetch_contacts", _fc)
        monkeypatch.setattr(ghl_client, "fetch_opportunities", _fo)

        r = client.post("/api/ghl/pull-sync", json={"event_id": test_event},
                        headers=admin_headers)
        assert r.status_code == 200, r.text

        # Tenant B lead unchanged
        async def _check_b():
            mc = AsyncIOMotorClient(mongo_url)
            db = mc[db_name]
            doc = await db.leads.find_one({"id": "tb_shared_lead"}, {"_id": 0})
            mc.close()
            return doc

        b_doc = asyncio.get_event_loop().run_until_complete(_check_b())
        assert b_doc is not None
        assert b_doc.get("external_source_id") in (None, "")
        assert b_doc.get("source_of_truth") == "local"


# ===========================================================================
# 13. PULL-SYNC PURCHASE OVERRIDE
# ===========================================================================
class TestPullSyncPurchaseOverride:
    def test_purchase_override(self, client, admin_headers, monkeypatch, test_event):
        _integration_delete_all(client, admin_headers)
        _add_ghl_integration(client, admin_headers)
        _delete_all_mappings(client, admin_headers)  # no tag mapping
        monkeypatch.setenv("GHL_READ_SYNC_ENABLED", "true")

        async def _fc(*a, **k):
            return [{"id": "ghl_purch_1", "firstName": "P", "lastName": "One",
                     "email": "purch1@example.com", "tags": []}]

        async def _fo(*a, **k):
            return [{"id": "opp_p1", "contactId": "ghl_purch_1",
                     "pipelineStageId": "stg_p", "status": "won",
                     "monetaryValue": 777}]

        monkeypatch.setattr(ghl_client, "fetch_contacts", _fc)
        monkeypatch.setattr(ghl_client, "fetch_opportunities", _fo)

        r = client.post("/api/ghl/pull-sync", json={"event_id": test_event},
                        headers=admin_headers)
        assert r.status_code == 200, r.text

        leads = client.get(f"/api/events/{test_event}/leads", headers=admin_headers).json()
        synced = [l for l in leads if l.get("external_source_id") == "ghl_purch_1"]
        assert synced
        s = synced[0]
        assert s["stage"] == "purchased"
        assert s["lead_temperature"] == "buyer"
        assert s.get("purchase_amount") == 777


# ===========================================================================
# 14. WRITE-BACK-PREVIEW BLOCKED
# ===========================================================================
class TestWriteBackBlocked:
    def test_blocked_no_credential(self, client, admin_headers, monkeypatch, test_event):
        # Seed a lead first (needs external_source_id to reach cred check normally,
        # but code checks cred first)
        _integration_delete_all(client, admin_headers)
        # Create any lead
        rl = client.post("/api/leads", json={
            "event_id": test_event, "name": "WB Lead", "email": "wb@x.com",
            "source": "manual", "stage": "new",
        }, headers=admin_headers)
        assert rl.status_code == 200, rl.text
        lid = rl.json()["id"]

        monkeypatch.setattr(ghl_client, "fetch_contacts",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope")))
        monkeypatch.setattr(ghl_client, "fetch_opportunities",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope")))

        r = client.post("/api/ghl/write-back-preview", json={"lead_id": lid},
                        headers=admin_headers)
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "blocked"
        assert "credential" in d["reason"].lower()

    def test_blocked_when_lead_is_local(self, client, admin_headers, test_event):
        _integration_delete_all(client, admin_headers)
        _add_ghl_integration(client, admin_headers)
        rl = client.post("/api/leads", json={
            "event_id": test_event, "name": "Local Only", "email": "local-only@x.com",
            "source": "manual", "stage": "new",
        }, headers=admin_headers)
        lid = rl.json()["id"]
        r = client.post("/api/ghl/write-back-preview", json={"lead_id": lid},
                        headers=admin_headers)
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "blocked"
        assert "ghl-linked" in d["reason"].lower() or "not ghl" in d["reason"].lower()


# ===========================================================================
# 15. WRITE-BACK-PREVIEW HAPPY PATH
# ===========================================================================
class TestWriteBackHappy:
    def test_happy_path(self, client, admin_headers, monkeypatch, test_event):
        _integration_delete_all(client, admin_headers)
        _add_ghl_integration(client, admin_headers)
        _delete_all_mappings(client, admin_headers)
        # Outbound tag mapping
        client.post("/api/ghl/mappings", json={
            "mapping_type": "tag", "ghl_name": "BUYER_TAG",
            "target_type": "lead_status", "target_value": "purchased",
            "direction": "outbound",
        }, headers=admin_headers)
        monkeypatch.setenv("GHL_READ_SYNC_ENABLED", "true")

        async def _fc(*a, **k):
            return [{"id": "ghl_wb_1", "firstName": "WB", "lastName": "One",
                     "email": "wb1@x.com", "tags": ["BUYER_TAG"]}]

        async def _fo(*a, **k):
            return [{"id": "opp_wb1", "contactId": "ghl_wb_1",
                     "status": "won", "monetaryValue": 100}]

        monkeypatch.setattr(ghl_client, "fetch_contacts", _fc)
        monkeypatch.setattr(ghl_client, "fetch_opportunities", _fo)

        # Sync first to get a GHL-linked lead
        s = client.post("/api/ghl/pull-sync", json={"event_id": test_event},
                        headers=admin_headers)
        assert s.status_code == 200, s.text

        leads = client.get(f"/api/events/{test_event}/leads", headers=admin_headers).json()
        synced = [l for l in leads if l.get("external_source_id") == "ghl_wb_1"]
        assert synced
        lid = synced[0]["id"]
        assert synced[0]["stage"] == "purchased"

        r = client.post("/api/ghl/write-back-preview", json={"lead_id": lid},
                        headers=admin_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "preview"
        would = d["would_send"]
        # tags contain buyer_tag case-insensitively
        tags_lower = [t.lower() for t in would.get("tags", [])]
        assert "buyer_tag" in tags_lower
        assert would["custom_fields"]["local_lead_status"] == "purchased"
        assert d["raw_payload_returned"] is False

        logs = client.get("/api/audit-logs?limit=500", headers=admin_headers).json()
        assert any(l["action"] == "ghl_write_back_preview" for l in logs)


# ===========================================================================
# 16. SECRET SANITIZATION + Dashboards
# ===========================================================================
class TestSecretSanitizationAndDashboards:
    def test_secret_never_in_audit_or_integrations(self, client, admin_headers):
        logs = client.get("/api/audit-logs?limit=500", headers=admin_headers)
        assert "ghl_super_secret_ABCXYZ" not in logs.text

        lst = client.get("/api/integrations", headers=admin_headers).json()
        for e in lst:
            assert "ghl_super_secret_ABCXYZ" not in str(e)
            if e["kind"] == "gohighlevel" and e.get("api_key_masked"):
                # Mask contains no alnum from the raw key beyond first/last few
                assert "super_secret" not in e["api_key_masked"]

    def test_dashboards_include_ghl_fields(self, client, admin_headers, test_event):
        g = client.get("/api/dashboard/global", headers=admin_headers).json()
        assert "leads_by_source" in g
        assert isinstance(g["leads_by_source"], dict)
        assert "gohighlevel" in g["leads_by_source"]
        assert "local" in g["leads_by_source"]
        assert "leads_by_temperature" in g
        for k in ("cold", "warm", "hot", "buyer"):
            assert k in g["leads_by_temperature"]
        assert isinstance(g["ghl_mirrored_leads_count"], int)

        e = client.get(f"/api/dashboard/event/{test_event}", headers=admin_headers).json()
        assert "ghl_status" in e
        assert "leads_by_source" in e
        assert "leads_by_temperature" in e
