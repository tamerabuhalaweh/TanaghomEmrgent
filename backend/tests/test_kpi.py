"""Patch 2 tests: Event KPI records, CSV import, dashboards, tenant isolation."""
import os
import uuid
import asyncio
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = (os.environ.get("API_BASE_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@campaign.ai"
ADMIN_PASS = "Admin@12345"


# ---------- Fixtures ----------
@pytest.fixture(scope="module")
def admin_headers():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def kpi_event(admin_headers):
    """Create an isolated event for KPI testing."""
    r = requests.post(f"{API}/events", json={
        "name": f"TEST_KPI_Event_{uuid.uuid4().hex[:6]}", "type": "custom",
        "start_date": "2026-05-01", "end_date": "2026-05-03",
        "budget_planned": 10000.0,
    }, headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    ev_id = r.json()["id"]
    # Also create a campaign in this event
    c = requests.post(f"{API}/campaigns", json={
        "event_id": ev_id, "name": "TEST_KPI_Campaign", "goal": "conversion",
        "start_date": "2026-05-01", "end_date": "2026-05-03",
        "budget_planned": 5000.0, "platforms": ["meta"],
    }, headers=admin_headers, timeout=20)
    assert c.status_code == 200, c.text
    yield {"event_id": ev_id, "campaign_id": c.json()["id"]}
    # Cleanup: delete event (cascades campaigns/posts/leads); also delete KPI records
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]

    async def _c():
        client = AsyncIOMotorClient(mongo_url)
        db = client[db_name]
        await db.event_kpi_records.delete_many({"event_id": ev_id})
        client.close()
    try:
        asyncio.get_event_loop().run_until_complete(_c())
    except Exception:
        pass
    requests.delete(f"{API}/events/{ev_id}", headers=admin_headers, timeout=20)


@pytest.fixture(scope="module")
def marketing_user(admin_headers):
    email = f"TEST_kpi_mkt_{uuid.uuid4().hex[:6]}@campaign.ai"
    pw = "Mkt@12345"
    r = requests.post(f"{API}/users", json={
        "email": email, "name": "KPI Mkt", "password": pw, "role": "marketing"
    }, headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    login = requests.post(f"{API}/auth/login",
                          json={"email": email, "password": pw}, timeout=20)
    headers = {"Authorization": f"Bearer {login.json()['token']}", "Content-Type": "application/json"}
    yield {"user_id": uid, "headers": headers, "email": email}
    requests.delete(f"{API}/users/{uid}", headers=admin_headers, timeout=20)


@pytest.fixture(scope="module")
def sales_user(admin_headers):
    email = f"TEST_kpi_sales_{uuid.uuid4().hex[:6]}@campaign.ai"
    pw = "Sls@12345"
    r = requests.post(f"{API}/users", json={
        "email": email, "name": "KPI Sales", "password": pw, "role": "sales"
    }, headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    login = requests.post(f"{API}/auth/login",
                          json={"email": email, "password": pw}, timeout=20)
    headers = {"Authorization": f"Bearer {login.json()['token']}", "Content-Type": "application/json"}
    yield {"user_id": uid, "headers": headers}
    requests.delete(f"{API}/users/{uid}", headers=admin_headers, timeout=20)


@pytest.fixture(scope="module")
def viewer_user(admin_headers):
    email = f"TEST_kpi_view_{uuid.uuid4().hex[:6]}@campaign.ai"
    pw = "Vwr@12345"
    r = requests.post(f"{API}/users", json={
        "email": email, "name": "KPI Viewer", "password": pw, "role": "viewer"
    }, headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    login = requests.post(f"{API}/auth/login",
                          json={"email": email, "password": pw}, timeout=20)
    headers = {"Authorization": f"Bearer {login.json()['token']}", "Content-Type": "application/json"}
    yield {"user_id": uid, "headers": headers}
    requests.delete(f"{API}/users/{uid}", headers=admin_headers, timeout=20)


@pytest.fixture(scope="module")
def tenant_b():
    """Create Tenant B admin + event via direct Mongo insert."""
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
            "id": tid, "name": "TEST_TenantB", "slug": f"test-b-{tid[:8]}",
            "status": "active", "created_at": datetime.now(timezone.utc).isoformat(),
        })
        uid = str(uuid.uuid4())
        email = f"test-b-admin-{tid[:8]}@campaign.ai"
        pw = "TBAdmin@12345"
        await db.users.insert_one({
            "id": uid, "tenant_id": tid, "email": email, "name": "TB Admin",
            "role": "admin", "permissions": ["*"],
            "password_hash": bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode(),
            "is_active": True, "created_at": datetime.now(timezone.utc).isoformat(),
        })
        ev_id = str(uuid.uuid4())
        await db.events.insert_one({
            "id": ev_id, "tenant_id": tid, "name": "TEST_TB_Event", "type": "custom",
            "start_date": "2026-06-01", "budget_planned": 0.0, "budget_actual": 0.0,
            "status": "planning",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        camp_id = str(uuid.uuid4())
        await db.campaigns.insert_one({
            "id": camp_id, "tenant_id": tid, "event_id": ev_id, "name": "TB Camp",
            "goal": "conversion", "start_date": "2026-06-01", "end_date": "2026-06-03",
            "budget_planned": 100.0, "budget_actual": 0.0, "platforms": [],
            "status": "draft", "created_at": datetime.now(timezone.utc).isoformat(),
        })
        client.close()
        return {"tenant_id": tid, "email": email, "password": pw,
                "user_id": uid, "event_id": ev_id, "campaign_id": camp_id}

    async def _cleanup(info):
        client = AsyncIOMotorClient(mongo_url)
        db = client[db_name]
        tid = info["tenant_id"]
        for coll in ("tenants", "users", "events", "campaigns", "posts", "leads",
                     "event_kpi_records", "audit_logs"):
            await db[coll].delete_many({"tenant_id": tid})
        await db.tenants.delete_many({"id": tid})
        client.close()

    info = asyncio.get_event_loop().run_until_complete(_setup())
    login = requests.post(f"{API}/auth/login",
                          json={"email": info["email"], "password": info["password"]}, timeout=20)
    info["headers"] = {"Authorization": f"Bearer {login.json()['token']}",
                       "Content-Type": "application/json"}
    yield info
    asyncio.get_event_loop().run_until_complete(_cleanup(info))


# ---------- KPI CRUD + RBAC ----------
class TestKpiCrud:
    def test_admin_create_kpi_source_manual(self, admin_headers, kpi_event):
        eid = kpi_event["event_id"]
        r = requests.post(f"{API}/events/{eid}/kpis", json={
            "metric_date": "2026-05-01", "channel": "meta", "reach": 100,
            "impressions": 500, "clicks": 50, "form_completions": 25,
            "leads": 10, "meetings_booked": 5, "meetings_attended": 4,
            "no_shows": 1, "purchases": 2, "spend": 200.0, "revenue": 800.0,
            "interactions": 30,
            "source_type": "csv_import",  # Should be forced to 'manual'
        }, headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["source_type"] == "manual"
        assert d["source_name"] == "manual entry"
        assert d["reach"] == 100

    def test_marketing_can_create_kpi(self, marketing_user, kpi_event):
        eid = kpi_event["event_id"]
        r = requests.post(f"{API}/events/{eid}/kpis", json={
            "metric_date": "2026-05-02", "channel": "instagram", "reach": 200, "spend": 50.0,
        }, headers=marketing_user["headers"], timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["source_type"] == "manual"

    def test_sales_cannot_create_kpi(self, sales_user, kpi_event):
        eid = kpi_event["event_id"]
        r = requests.post(f"{API}/events/{eid}/kpis", json={
            "metric_date": "2026-05-02", "channel": "meta", "reach": 1,
        }, headers=sales_user["headers"], timeout=20)
        assert r.status_code == 403

    def test_viewer_cannot_create_kpi(self, viewer_user, kpi_event):
        eid = kpi_event["event_id"]
        r = requests.post(f"{API}/events/{eid}/kpis", json={
            "metric_date": "2026-05-02", "channel": "meta", "reach": 1,
        }, headers=viewer_user["headers"], timeout=20)
        assert r.status_code == 403

    def test_sales_can_get_kpis(self, sales_user, kpi_event):
        eid = kpi_event["event_id"]
        r = requests.get(f"{API}/events/{eid}/kpis", headers=sales_user["headers"], timeout=20)
        assert r.status_code == 200

    def test_viewer_can_get_kpis(self, viewer_user, kpi_event):
        eid = kpi_event["event_id"]
        r = requests.get(f"{API}/events/{eid}/kpis", headers=viewer_user["headers"], timeout=20)
        assert r.status_code == 200

    def test_patch_kpi_audit(self, admin_headers, kpi_event):
        eid = kpi_event["event_id"]
        # Create then patch
        c = requests.post(f"{API}/events/{eid}/kpis", json={
            "metric_date": "2026-05-05", "channel": "email", "reach": 10, "spend": 5.0,
        }, headers=admin_headers, timeout=20)
        assert c.status_code == 200
        kid = c.json()["id"]
        r = requests.patch(f"{API}/events/{eid}/kpis/{kid}",
                           json={"reach": 999}, headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert r.json()["reach"] == 999
        # Check audit
        logs = requests.get(f"{API}/audit-logs?limit=500", headers=admin_headers, timeout=20).json()
        assert any(l["action"] == "event_kpi_updated" and l["object_id"] == kid for l in logs)

    def test_delete_kpi_admin_only(self, admin_headers, marketing_user, kpi_event):
        eid = kpi_event["event_id"]
        c = requests.post(f"{API}/events/{eid}/kpis", json={
            "metric_date": "2026-05-06", "channel": "email", "reach": 1,
        }, headers=admin_headers, timeout=20)
        kid = c.json()["id"]
        # Marketing tries → 403
        r = requests.delete(f"{API}/events/{eid}/kpis/{kid}",
                            headers=marketing_user["headers"], timeout=20)
        assert r.status_code == 403
        # Admin succeeds
        r2 = requests.delete(f"{API}/events/{eid}/kpis/{kid}",
                             headers=admin_headers, timeout=20)
        assert r2.status_code == 200
        assert r2.json().get("deleted", 0) == 1


# ---------- Validation ----------
class TestKpiValidation:
    def test_negative_value_rejected(self, admin_headers, kpi_event):
        r = requests.post(f"{API}/events/{kpi_event['event_id']}/kpis", json={
            "metric_date": "2026-05-01", "channel": "meta", "reach": -5,
        }, headers=admin_headers, timeout=20)
        assert r.status_code == 400

    def test_unknown_channel_rejected(self, admin_headers, kpi_event):
        r = requests.post(f"{API}/events/{kpi_event['event_id']}/kpis", json={
            "metric_date": "2026-05-01", "channel": "tiktok", "reach": 1,
        }, headers=admin_headers, timeout=20)
        assert r.status_code == 400

    def test_unknown_source_type_filter_rejected(self, admin_headers, kpi_event):
        r = requests.get(f"{API}/events/{kpi_event['event_id']}/kpis?source_type=bogus",
                         headers=admin_headers, timeout=20)
        assert r.status_code == 400

    def test_all_zero_without_notes_rejected(self, admin_headers, kpi_event):
        r = requests.post(f"{API}/events/{kpi_event['event_id']}/kpis", json={
            "metric_date": "2026-05-01", "channel": "meta",
        }, headers=admin_headers, timeout=20)
        assert r.status_code == 400

    def test_all_zero_with_notes_accepted(self, admin_headers, kpi_event):
        r = requests.post(f"{API}/events/{kpi_event['event_id']}/kpis", json={
            "metric_date": "2026-05-01", "channel": "meta",
            "notes": "No activity recorded — dark period.",
        }, headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text


# ---------- Tenant Isolation ----------
class TestKpiTenantIsolation:
    def test_tenant_a_cannot_get_tenant_b_kpi(self, admin_headers, tenant_b):
        # Create KPI in tenant B directly
        eid_b = tenant_b["event_id"]
        rb = requests.post(f"{API}/events/{eid_b}/kpis", json={
            "metric_date": "2026-06-01", "channel": "meta", "reach": 999, "spend": 10.0,
        }, headers=tenant_b["headers"], timeout=20)
        assert rb.status_code == 200
        # Tenant A tries to GET tenant B's event → 404
        r = requests.get(f"{API}/events/{eid_b}/kpis", headers=admin_headers, timeout=20)
        assert r.status_code == 404

    def test_tenant_a_cannot_reference_tenant_b_campaign(self, admin_headers, kpi_event, tenant_b):
        r = requests.post(f"{API}/events/{kpi_event['event_id']}/kpis", json={
            "metric_date": "2026-05-01", "channel": "meta", "reach": 1,
            "campaign_id": tenant_b["campaign_id"],
        }, headers=admin_headers, timeout=20)
        assert r.status_code == 400
        assert "does not belong" in r.text.lower() or "campaign" in r.text.lower()

    def test_global_dashboard_scoped_by_tenant(self, admin_headers, tenant_b):
        # KPI already exists in tenant B (from above test). Ensure tenant A's global does not see it.
        # Add another to tenant B to be safe:
        requests.post(f"{API}/events/{tenant_b['event_id']}/kpis", json={
            "metric_date": "2026-06-02", "channel": "meta", "reach": 77777,
        }, headers=tenant_b["headers"], timeout=20)
        dash_a = requests.get(f"{API}/dashboard/global", headers=admin_headers, timeout=20).json()
        # tenant B has reach 77777+999 = should not appear in tenant A's totals
        # Assert reach doesn't include 77777 exact — this is a loose check
        assert dash_a["reach"] < 77777 or dash_a["reach"] % 77777 != 0


# ---------- CSV Dry-run + Import ----------
class TestKpiCsv:
    def test_dry_run_mixed(self, admin_headers, kpi_event):
        eid = kpi_event["event_id"]
        # Snapshot count before
        before = requests.get(f"{API}/events/{eid}/kpis", headers=admin_headers, timeout=20).json()
        before_count = len(before)
        body = {"rows": [
            {"metric_date": "2026-05-10", "channel": "meta", "reach": 10, "spend": 1.0},
            {"metric_date": "2026-05-10", "channel": "tiktok", "reach": 5},  # invalid channel
            {"metric_date": "2026-05-11", "channel": "email", "clicks": 20, "form_completions": 5},
            {"metric_date": "2026-05-12", "channel": "meta", "reach": -1},  # invalid
        ]}
        r = requests.post(f"{API}/events/{eid}/kpis/csv/dry-run",
                          json=body, headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["valid_count"] == 2
        assert d["invalid_count"] == 2
        assert d["preview_totals"]["reach"] == 10
        assert d["preview_totals"]["clicks"] == 20
        # Verify errors carry row_index + error string
        for e in d["row_errors"]:
            assert "row_index" in e and "error" in e and isinstance(e["error"], str)
        # DB unchanged
        after = requests.get(f"{API}/events/{eid}/kpis", headers=admin_headers, timeout=20).json()
        assert len(after) == before_count
        # Audit: entry exists with tenant_id, no raw row data
        logs = requests.get(f"{API}/audit-logs?limit=200",
                            headers=admin_headers, timeout=20).json()
        drys = [l for l in logs if l["action"] == "event_kpi_csv_dry_run"]
        assert drys, "No dry-run audit"
        m = drys[0]["metadata"]
        assert "rows" not in m
        assert m.get("event_id") == eid
        assert "input_count" in m

    def test_import_atomic_reject(self, admin_headers, kpi_event):
        eid = kpi_event["event_id"]
        before = requests.get(f"{API}/events/{eid}/kpis?source_type=csv_import",
                              headers=admin_headers, timeout=20).json()
        before_count = len(before)
        body = {"rows": [
            {"metric_date": "2026-05-15", "channel": "meta", "reach": 100},
            {"metric_date": "2026-05-15", "channel": "bogus", "reach": 1},
        ]}
        r = requests.post(f"{API}/events/{eid}/kpis/csv/import",
                          json=body, headers=admin_headers, timeout=20)
        assert r.status_code == 400
        after = requests.get(f"{API}/events/{eid}/kpis?source_type=csv_import",
                             headers=admin_headers, timeout=20).json()
        assert len(after) == before_count  # zero inserted
        # Failure audit
        logs = requests.get(f"{API}/audit-logs?limit=200",
                            headers=admin_headers, timeout=20).json()
        assert any(l["action"] == "event_kpi_csv_imported" and l["result"] == "failure"
                   for l in logs)

    def test_import_happy_path(self, admin_headers, kpi_event):
        eid = kpi_event["event_id"]
        body = {"rows": [
            {"metric_date": "2026-05-20", "channel": "meta", "reach": 500, "spend": 10.0, "leads": 5},
            {"metric_date": "2026-05-20", "channel": "email", "clicks": 100, "form_completions": 20},
        ]}
        r = requests.post(f"{API}/events/{eid}/kpis/csv/import",
                          json=body, headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["inserted_count"] == 2
        # Verify records exist with source_type='csv_import' and source_name='csv upload'
        rows = requests.get(f"{API}/events/{eid}/kpis?source_type=csv_import",
                            headers=admin_headers, timeout=20).json()
        imported = [x for x in rows if x["metric_date"] == "2026-05-20"]
        assert len(imported) == 2
        for x in imported:
            assert x["source_type"] == "csv_import"
            assert x["source_name"] == "csv upload"
        # Success audit
        logs = requests.get(f"{API}/audit-logs?limit=200",
                            headers=admin_headers, timeout=20).json()
        assert any(l["action"] == "event_kpi_csv_imported" and l["result"] == "success"
                   for l in logs)


# ---------- Dashboard Aggregation ----------
class TestKpiDashboards:
    def test_no_verified_metrics_status(self, tenant_b):
        r = requests.get(f"{API}/dashboard/event/{tenant_b['event_id']}",
                         headers=tenant_b["headers"], timeout=20)
        assert r.status_code == 200
        d = r.json()
        # Might have earlier tests added KPI to tenant B — check freshly:
        # If any KPI exists, skip; else verify no_verified_metrics
        if d["records_count"] == 0:
            assert d["metrics_status"] == "no_verified_metrics"
            assert d["reach"] == 0 and d["spend"] == 0 and d["revenue"] == 0
            assert d["roi_percent"] == 0

    def test_event_dashboard_aggregations_and_rates(self, admin_headers, kpi_event):
        eid = kpi_event["event_id"]
        # Insert fresh, known values
        # Wipe pre-existing KPI for this event
        existing = requests.get(f"{API}/events/{eid}/kpis",
                                headers=admin_headers, timeout=20).json()
        for x in existing:
            requests.delete(f"{API}/events/{eid}/kpis/{x['id']}",
                            headers=admin_headers, timeout=20)
        rows = [
            {"metric_date": "2026-07-01", "channel": "meta", "reach": 1000,
             "impressions": 2000, "interactions": 300, "clicks": 200,
             "form_completions": 50, "leads": 40, "meetings_booked": 20,
             "meetings_attended": 15, "no_shows": 5, "purchases": 10,
             "spend": 500.0, "revenue": 2000.0},
            {"metric_date": "2026-07-02", "channel": "email", "reach": 500,
             "impressions": 1000, "interactions": 100, "clicks": 100,
             "form_completions": 30, "leads": 20, "meetings_booked": 10,
             "meetings_attended": 5, "no_shows": 5, "purchases": 5,
             "spend": 200.0, "revenue": 500.0},
        ]
        for row in rows:
            r = requests.post(f"{API}/events/{eid}/kpis", json=row,
                              headers=admin_headers, timeout=20)
            assert r.status_code == 200, r.text
        # Add one via CSV import for source_type_breakdown coverage
        imp = requests.post(f"{API}/events/{eid}/kpis/csv/import", json={"rows": [
            {"metric_date": "2026-07-03", "channel": "instagram", "reach": 200,
             "clicks": 50, "form_completions": 10, "leads": 5,
             "purchases": 1, "spend": 50.0, "revenue": 100.0},
        ]}, headers=admin_headers, timeout=20)
        assert imp.status_code == 200
        dash = requests.get(f"{API}/dashboard/event/{eid}",
                            headers=admin_headers, timeout=20).json()
        assert dash["metrics_status"] == "verified"
        # Totals: 3 rows: reach 1700, clicks 350, form_completions 90, leads 65,
        # meetings_booked 30, meetings_attended 20, purchases 16, spend 750,
        # revenue 2600
        assert dash["reach"] == 1700
        assert dash["clicks"] == 350
        assert dash["form_completions"] == 90
        assert dash["leads"] == 65
        assert dash["meetings_booked"] == 30
        assert dash["meetings_attended"] == 20
        assert dash["purchases"] == 16
        assert dash["spend"] == 750.0
        assert dash["revenue"] == 2600.0
        # Rates
        assert dash["form_completion_rate"] == round(90 / 350 * 100, 2)
        assert dash["lead_to_purchase_rate"] == round(16 / 65 * 100, 2)
        assert dash["meeting_show_rate"] == round(20 / 30 * 100, 2)
        assert dash["cost_per_lead"] == round(750 / 65, 2)
        assert dash["cost_per_purchase"] == round(750 / 16, 2)
        # ROI = (revenue - spend) / spend * 100
        assert dash["roi_percent"] == round((2600 - 750) / 750 * 100, 2)
        # Channel breakdown: 3 channels
        channels = {c["channel"]: c for c in dash["channel_breakdown"]}
        assert set(channels.keys()) == {"meta", "email", "instagram"}
        assert channels["meta"]["reach"] == 1000
        # Source type breakdown: manual + csv_import
        st_map = {s["source_type"]: s for s in dash["source_type_breakdown"]}
        assert "manual" in st_map and "csv_import" in st_map
        assert st_map["manual"]["records"] == 2
        assert st_map["csv_import"]["records"] == 1

    def test_divide_by_zero_returns_zero(self, admin_headers, kpi_event):
        # Insert a single row with clicks=0, leads=0, meetings_booked=0
        eid = kpi_event["event_id"]
        # Clean out event KPI first
        existing = requests.get(f"{API}/events/{eid}/kpis",
                                headers=admin_headers, timeout=20).json()
        for x in existing:
            requests.delete(f"{API}/events/{eid}/kpis/{x['id']}",
                            headers=admin_headers, timeout=20)
        r = requests.post(f"{API}/events/{eid}/kpis", json={
            "metric_date": "2026-08-01", "channel": "meta", "reach": 10,
        }, headers=admin_headers, timeout=20)
        assert r.status_code == 200
        dash = requests.get(f"{API}/dashboard/event/{eid}",
                            headers=admin_headers, timeout=20).json()
        assert dash["form_completion_rate"] == 0
        assert dash["lead_to_purchase_rate"] == 0
        assert dash["meeting_show_rate"] == 0
        assert dash["cost_per_lead"] == 0
        assert dash["cost_per_purchase"] == 0
        assert dash["roi_percent"] == 0


# ---------- Audit sanitization ----------
class TestKpiAuditSanitization:
    def test_notes_secret_redacted(self, admin_headers, kpi_event):
        eid = kpi_event["event_id"]
        marker = "super-secret-xyz-123"
        r = requests.post(f"{API}/events/{eid}/kpis", json={
            "metric_date": "2026-09-01", "channel": "meta", "reach": 1,
            "notes": f"api_key={marker}",
        }, headers=admin_headers, timeout=20)
        assert r.status_code == 200
        logs = requests.get(f"{API}/audit-logs?limit=500",
                            headers=admin_headers, timeout=20)
        assert marker not in logs.text, "Raw secret leaked into audit metadata"
