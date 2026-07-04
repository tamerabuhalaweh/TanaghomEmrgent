"""Patch 4 tests: Event Strategy Planner + Sales Execution Workflow.

Uses `requests` against the live backend (same pattern as test_kpi.py) to avoid
event-loop conflicts with test_ghl.py's TestClient when xdist puts them in the
same worker. Never triggers external calls: no /send-* routes exist in Patch 4.

Covers 7 planner resources: content-requirements, email-plans, whatsapp-plans,
upsell-plans, budget-plans, dark-ad-plans, sales-tasks.
"""
import os
import sys
import uuid
import asyncio
from pathlib import Path
from datetime import datetime, timezone

import pytest
import requests
import bcrypt
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

# Import server ONLY for route-scan test (no TestClient use)
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


BASE_URL = (os.environ.get("API_BASE_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@campaign.ai"
ADMIN_PASS = "Admin@12345"


def _run(coro):
    """Run an async coroutine in a fresh event loop for Motor operations."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------- Minimal valid POST bodies ----------
def _body_content():
    return {"title": "T", "asset_type": "video", "platform": "instagram"}


def _body_email():
    return {"sequence_name": "Seq", "goal": "awareness"}


def _body_whatsapp():
    return {"goal": "reminder"}


def _body_upsell():
    return {"target_segment": "vip", "offer": "10% off", "planned_channel": "email"}


def _body_budget():
    return {"channel": "meta", "planned_budget": 100.0}


def _body_darkad():
    return {"campaign_name": "DA1", "platform": "meta",
            "creative_format": "video", "objective": "leads"}


def _body_sales():
    return {"title": "call lead", "task_type": "call"}


RESOURCES = [
    ("content-requirements", "content_requirement", _body_content),
    ("email-plans", "email_plan", _body_email),
    ("whatsapp-plans", "whatsapp_plan", _body_whatsapp),
    ("upsell-plans", "upsell_plan", _body_upsell),
    ("budget-plans", "budget_plan", _body_budget),
    ("dark-ad-plans", "dark_ad_plan", _body_darkad),
    ("sales-tasks", "sales_task", _body_sales),
]

WRITE_ROLES = {
    "content-requirements": {"admin", "marketing", "social"},
    "email-plans": {"admin", "marketing"},
    "whatsapp-plans": {"admin", "marketing", "sales"},
    "upsell-plans": {"admin", "marketing", "sales"},
    "budget-plans": {"admin", "marketing"},
    "dark-ad-plans": {"admin", "marketing", "social"},
    "sales-tasks": {"admin", "marketing", "sales"},
}


# ---------- Session fixtures ----------
def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_headers():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
    assert r.status_code == 200, r.text
    return _hdr(r.json()["token"])


def _make_user(admin_headers, role, prefix):
    email = f"TEST_planner_{prefix}_{uuid.uuid4().hex[:6]}@campaign.ai"
    pw = "Pass@12345"
    r = requests.post(f"{API}/users", json={
        "email": email, "name": f"Planner {role}", "password": pw, "role": role,
    }, headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    login = requests.post(f"{API}/auth/login",
                          json={"email": email, "password": pw}, timeout=20)
    assert login.status_code == 200, login.text
    return {"id": uid, "email": email, "role": role,
            "headers": _hdr(login.json()["token"])}


@pytest.fixture(scope="module")
def marketing_user(admin_headers):
    return _make_user(admin_headers, "marketing", "mkt")


@pytest.fixture(scope="module")
def sales_user(admin_headers):
    return _make_user(admin_headers, "sales", "sls")


@pytest.fixture(scope="module")
def social_user(admin_headers):
    return _make_user(admin_headers, "social", "soc")


@pytest.fixture(scope="module")
def viewer_user(admin_headers):
    return _make_user(admin_headers, "viewer", "vwr")


@pytest.fixture(scope="module")
def role_users(admin_headers, marketing_user, sales_user, social_user, viewer_user):
    return {
        "admin": {"headers": admin_headers, "role": "admin"},
        "marketing": marketing_user,
        "sales": sales_user,
        "social": social_user,
        "viewer": viewer_user,
    }


@pytest.fixture(scope="module")
def tenant_b():
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]

    async def _setup():
        mc = AsyncIOMotorClient(mongo_url)
        db = mc[db_name]
        tid = str(uuid.uuid4())
        await db.tenants.insert_one({
            "id": tid, "name": "TEST_PLANNER_TenantB",
            "slug": f"test-planner-b-{tid[:8]}",
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        uid = str(uuid.uuid4())
        email = f"test-planner-b-{tid[:8]}@campaign.ai"
        pw = "TBPln@12345"
        await db.users.insert_one({
            "id": uid, "tenant_id": tid, "email": email, "name": "TB Admin",
            "role": "admin", "permissions": ["*"],
            "password_hash": bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode(),
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        ev_id = str(uuid.uuid4())
        await db.events.insert_one({
            "id": ev_id, "tenant_id": tid,
            "name": f"TEST_PLANNER_TB_Event_{tid[:6]}", "type": "custom",
            "start_date": "2026-06-01", "budget_planned": 0.0, "budget_actual": 0.0,
            "status": "planning",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        mc.close()
        return {"tenant_id": tid, "email": email, "password": pw,
                "user_id": uid, "event_id": ev_id}

    info = _run(_setup())
    r = requests.post(f"{API}/auth/login",
                      json={"email": info["email"], "password": info["password"]},
                      timeout=20)
    assert r.status_code == 200, r.text
    info["headers"] = _hdr(r.json()["token"])
    return info


def _new_event(admin_headers, tag):
    r = requests.post(f"{API}/events", json={
        "name": f"TEST_PLANNER_{tag}_{uuid.uuid4().hex[:6]}", "type": "custom",
        "start_date": "2026-05-01", "end_date": "2026-05-03",
        "budget_planned": 1000.0,
    }, headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def event_id(admin_headers):
    return _new_event(admin_headers, "MAIN")


# ---------- Module-scope cleanup ----------
@pytest.fixture(scope="module", autouse=True)
def _cleanup(tenant_b):
    yield
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]

    async def _clean():
        mc = AsyncIOMotorClient(mongo_url)
        db = mc[db_name]
        tb_id = tenant_b["tenant_id"]
        planner_colls = [
            "event_content_requirements", "event_email_plans", "event_whatsapp_plans",
            "event_upsell_plans", "event_budget_plans", "event_dark_ad_plans",
            "event_sales_tasks",
        ]
        for coll in planner_colls + [
            "tenants", "users", "events", "campaigns", "posts", "leads",
            "event_kpi_records", "audit_logs",
        ]:
            await db[coll].delete_many({"tenant_id": tb_id})
        await db.tenants.delete_many({"id": tb_id})
        default = await db.tenants.find_one({"slug": "default"})
        if default:
            did = default["id"]
            evs = await db.events.find(
                {"tenant_id": did, "name": {"$regex": "^TEST_PLANNER_"}}
            ).to_list(1000)
            ev_ids = [e["id"] for e in evs]
            for coll in planner_colls:
                await db[coll].delete_many({"tenant_id": did})
            await db.event_kpi_records.delete_many(
                {"tenant_id": did, "event_id": {"$in": ev_ids}}
            )
            await db.events.delete_many(
                {"tenant_id": did, "name": {"$regex": "^TEST_PLANNER_"}}
            )
            await db.users.delete_many(
                {"tenant_id": did, "email": {"$regex": "^TEST_planner_"}}
            )
        mc.close()

    try:
        _run(_clean())
    except Exception:
        pass


# ===========================================================================
# 1. CRUD lifecycle for every resource (7 parametrized tests)
# ===========================================================================
@pytest.mark.parametrize("path,obj,body_fn", RESOURCES,
                        ids=[r[0] for r in RESOURCES])
def test_crud_lifecycle(admin_headers, event_id, path, obj, body_fn):
    base = f"{API}/events/{event_id}/{path}"
    r = requests.post(base, json=body_fn(), headers=admin_headers, timeout=20)
    assert r.status_code == 200, r.text
    doc = r.json()
    for k in ("id", "tenant_id", "event_id", "created_by", "created_at", "updated_at"):
        assert k in doc, f"missing {k} in {path} create response"
    assert doc["event_id"] == event_id
    item_id = doc["id"]

    lst = requests.get(base, headers=admin_headers, timeout=20).json()
    assert any(d["id"] == item_id for d in lst)

    r2 = requests.patch(f"{base}/{item_id}", json={"notes": "updated"},
                        headers=admin_headers, timeout=20)
    assert r2.status_code == 200, r2.text

    r3 = requests.delete(f"{base}/{item_id}", headers=admin_headers, timeout=20)
    assert r3.status_code == 200
    assert r3.json() == {"deleted": 1}

    r4 = requests.delete(f"{base}/{item_id}", headers=admin_headers, timeout=20)
    assert r4.status_code == 404


# ===========================================================================
# 2. RBAC WRITE matrix (parametrized: 7 resources)
# ===========================================================================
@pytest.mark.parametrize("path,obj,body_fn", RESOURCES,
                        ids=[r[0] for r in RESOURCES])
def test_rbac_write_matrix(admin_headers, event_id, role_users, path, obj, body_fn):
    allowed = WRITE_ROLES[path]
    base = f"{API}/events/{event_id}/{path}"
    for role, info in role_users.items():
        r = requests.post(base, json=body_fn(), headers=info["headers"], timeout=20)
        if role in allowed:
            assert r.status_code == 200, f"{role} POST {path} → {r.status_code} {r.text}"
            requests.delete(f"{base}/{r.json()['id']}",
                            headers=admin_headers, timeout=20)
        else:
            assert r.status_code == 403, f"{role} POST {path} → expected 403, got {r.status_code}"


# ===========================================================================
# 3. GET is open to ALL roles (viewer included)
# ===========================================================================
def test_get_all_roles_can_read(event_id, role_users):
    for role, info in role_users.items():
        for path, _, _ in RESOURCES:
            r = requests.get(f"{API}/events/{event_id}/{path}",
                             headers=info["headers"], timeout=20)
            assert r.status_code == 200, f"{role} GET {path} → {r.status_code}"
            assert isinstance(r.json(), list)


# ===========================================================================
# 4. Enum validation (POST + PATCH) — 4 tests
# ===========================================================================
def test_enum_content_asset_type_bogus(admin_headers, event_id):
    body = _body_content()
    body["asset_type"] = "bogus"
    r = requests.post(f"{API}/events/{event_id}/content-requirements",
                      json=body, headers=admin_headers, timeout=20)
    assert r.status_code == 400
    assert "asset_type" in r.text


def test_enum_email_goal_bogus(admin_headers, event_id):
    body = _body_email()
    body["goal"] = "bogus"
    r = requests.post(f"{API}/events/{event_id}/email-plans",
                      json=body, headers=admin_headers, timeout=20)
    assert r.status_code == 400
    assert "goal" in r.text


def test_enum_budget_channel_bogus(admin_headers, event_id):
    body = _body_budget()
    body["channel"] = "xxx"
    r = requests.post(f"{API}/events/{event_id}/budget-plans",
                      json=body, headers=admin_headers, timeout=20)
    assert r.status_code == 400
    assert "channel" in r.text


def test_enum_patch_email_approval_status(admin_headers, event_id):
    r = requests.post(f"{API}/events/{event_id}/email-plans",
                      json=_body_email(), headers=admin_headers, timeout=20)
    assert r.status_code == 200
    iid = r.json()["id"]
    p = requests.patch(f"{API}/events/{event_id}/email-plans/{iid}",
                       json={"approval_status": "invalid"},
                       headers=admin_headers, timeout=20)
    assert p.status_code == 400
    assert "approval_status" in p.text
    requests.delete(f"{API}/events/{event_id}/email-plans/{iid}",
                    headers=admin_headers, timeout=20)


def test_planner_patch_rejects_unknown_fields(admin_headers, event_id):
    cases = [
        ("content-requirements", _body_content),
        ("budget-plans", _body_budget),
        ("sales-tasks", _body_sales),
    ]
    for path, body_fn in cases:
        base = f"{API}/events/{event_id}/{path}"
        r = requests.post(base, json=body_fn(), headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        iid = r.json()["id"]

        p = requests.patch(
            f"{base}/{iid}",
            json={"unexpected_field": "must-not-persist"},
            headers=admin_headers,
            timeout=20,
        )
        assert p.status_code == 400
        assert "Unknown fields" in p.text

        rows = requests.get(base, headers=admin_headers, timeout=20).json()
        current = next(x for x in rows if x["id"] == iid)
        assert "unexpected_field" not in current

        requests.delete(f"{base}/{iid}", headers=admin_headers, timeout=20)


def test_planner_create_rejects_unknown_fields(admin_headers, event_id):
    r = requests.post(
        f"{API}/events/{event_id}/budget-plans",
        json={**_body_budget(), "unexpected_field": "must-not-persist"},
        headers=admin_headers,
        timeout=20,
    )
    assert r.status_code == 400
    assert "Unknown fields" in r.text


# ===========================================================================
# 5. Tenant isolation
# ===========================================================================
def test_tenant_isolation_cross_event(admin_headers, tenant_b):
    b_event = tenant_b["event_id"]
    for path, _, body_fn in RESOURCES:
        base = f"{API}/events/{b_event}/{path}"
        assert requests.get(base, headers=admin_headers, timeout=20).status_code == 404
        assert requests.post(base, json=body_fn(),
                             headers=admin_headers, timeout=20).status_code == 404
        assert requests.patch(f"{base}/nonexistent", json={"notes": "x"},
                              headers=admin_headers, timeout=20).status_code == 404
        assert requests.delete(f"{base}/nonexistent",
                               headers=admin_headers, timeout=20).status_code == 404


def test_tenant_isolation_list_does_not_leak(admin_headers, tenant_b, event_id):
    r = requests.post(f"{API}/events/{event_id}/content-requirements",
                      json=_body_content(), headers=admin_headers, timeout=20)
    assert r.status_code == 200
    a_doc_id = r.json()["id"]

    b_lst = requests.get(
        f"{API}/events/{tenant_b['event_id']}/content-requirements",
        headers=tenant_b["headers"], timeout=20,
    )
    assert b_lst.status_code == 200
    assert all(d["id"] != a_doc_id for d in b_lst.json())

    requests.delete(f"{API}/events/{event_id}/content-requirements/{a_doc_id}",
                    headers=admin_headers, timeout=20)


# ===========================================================================
# 6. Audit entries for all 7 resources (create/update/delete)
# ===========================================================================
def test_audit_entries_written(admin_headers, event_id):
    for path, obj, body_fn in RESOURCES:
        base = f"{API}/events/{event_id}/{path}"
        r = requests.post(base, json=body_fn(), headers=admin_headers, timeout=20)
        assert r.status_code == 200
        iid = r.json()["id"]
        requests.patch(f"{base}/{iid}", json={"notes": "u"},
                       headers=admin_headers, timeout=20)
        d = requests.delete(f"{base}/{iid}", headers=admin_headers, timeout=20)
        assert d.status_code == 200

    logs = requests.get(f"{API}/audit-logs?limit=500",
                        headers=admin_headers, timeout=20).json()
    actions = {l["action"] for l in logs}
    for obj in [r[1] for r in RESOURCES]:
        assert f"{obj}_created" in actions, f"missing {obj}_created"
        assert f"{obj}_updated" in actions, f"missing {obj}_updated"
        assert f"{obj}_deleted" in actions, f"missing {obj}_deleted"
    for l in logs[:50]:
        assert l.get("tenant_id"), "audit log missing tenant_id"


# ===========================================================================
# 7. Planner summary — content counts + overdue rule
# ===========================================================================
def test_summary_content_counts_and_overdue(admin_headers):
    ev = _new_event(admin_headers, "CNT")
    base = f"{API}/events/{ev}/content-requirements"
    r1 = requests.post(base, json={**_body_content(),
                                   "due_date": "2020-01-01", "status": "planned"},
                       headers=admin_headers, timeout=20)
    assert r1.status_code == 200
    r2 = requests.post(base, json={**_body_content(),
                                   "due_date": "2020-01-01", "status": "done"},
                       headers=admin_headers, timeout=20)
    assert r2.status_code == 200
    s = requests.get(f"{API}/events/{ev}/planner/summary",
                     headers=admin_headers, timeout=20).json()
    assert s["counts"]["content_requirements"] == 2
    assert s["counts"]["overdue_content"] == 1


# ===========================================================================
# 8. Planner summary — approved counts
# ===========================================================================
def test_summary_approved_counts(admin_headers):
    ev = _new_event(admin_headers, "APPR")
    for approval in ("draft", "draft", "approved"):
        assert requests.post(f"{API}/events/{ev}/email-plans",
                             json={**_body_email(), "approval_status": approval},
                             headers=admin_headers, timeout=20).status_code == 200
    for approval in ("approved", "draft"):
        assert requests.post(f"{API}/events/{ev}/whatsapp-plans",
                             json={**_body_whatsapp(), "approval_status": approval},
                             headers=admin_headers, timeout=20).status_code == 200
    for approval in ("approved", "pending_review"):
        assert requests.post(f"{API}/events/{ev}/upsell-plans",
                             json={**_body_upsell(), "approval_status": approval},
                             headers=admin_headers, timeout=20).status_code == 200
    s = requests.get(f"{API}/events/{ev}/planner/summary",
                     headers=admin_headers, timeout=20).json()
    assert s["counts"]["email_plans"] == 3
    assert s["counts"]["approved_email_plans"] == 1
    assert s["counts"]["whatsapp_plans"] == 2
    assert s["counts"]["approved_whatsapp_plans"] == 1
    assert s["counts"]["upsell_plans"] == 2
    assert s["counts"]["approved_upsell_plans"] == 1


# ===========================================================================
# 9. Planner summary — budget_by_channel (planned vs actual, sorted)
# ===========================================================================
def test_summary_budget_by_channel(admin_headers):
    ev = _new_event(admin_headers, "BDG")
    for ch, amt in [("meta", 1000), ("instagram", 500)]:
        assert requests.post(f"{API}/events/{ev}/budget-plans",
                             json={"channel": ch, "planned_budget": amt},
                             headers=admin_headers, timeout=20).status_code == 200
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]

    async def _seed_kpi():
        mc = AsyncIOMotorClient(mongo_url)
        db = mc[db_name]
        default = await db.tenants.find_one({"slug": "default"})
        await db.event_kpi_records.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": default["id"], "event_id": ev,
            "channel": "meta", "source_type": "manual",
            "metric_date": "2026-01-01", "spend": 300.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        mc.close()

    _run(_seed_kpi())
    s = requests.get(f"{API}/events/{ev}/planner/summary",
                     headers=admin_headers, timeout=20).json()
    rows = s["budget_by_channel"]
    assert [r["channel"] for r in rows] == ["instagram", "meta"]
    assert rows[0] == {"channel": "instagram", "planned": 500.0, "actual": 0.0, "variance": 500.0}
    assert rows[1] == {"channel": "meta", "planned": 1000.0, "actual": 300.0, "variance": 700.0}


def test_summary_budget_channel_only_in_kpi(admin_headers):
    ev = _new_event(admin_headers, "BDG2")
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]

    async def _seed():
        mc = AsyncIOMotorClient(mongo_url)
        db = mc[db_name]
        default = await db.tenants.find_one({"slug": "default"})
        await db.event_kpi_records.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": default["id"], "event_id": ev,
            "channel": "youtube", "source_type": "manual",
            "metric_date": "2026-01-01", "spend": 42.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        mc.close()

    _run(_seed())
    s = requests.get(f"{API}/events/{ev}/planner/summary",
                     headers=admin_headers, timeout=20).json()
    yt = [r for r in s["budget_by_channel"] if r["channel"] == "youtube"]
    assert yt and yt[0]["planned"] == 0.0 and yt[0]["actual"] == 42.0


# ===========================================================================
# 10. Sales-tasks counts / open / overdue
# ===========================================================================
def test_summary_sales_tasks(admin_headers):
    ev = _new_event(admin_headers, "SLS")
    base = f"{API}/events/{ev}/sales-tasks"
    requests.post(base, json={**_body_sales(), "status": "open",
                              "due_date": "2020-01-01"},
                  headers=admin_headers, timeout=20)
    requests.post(base, json={**_body_sales(), "status": "in_progress",
                              "due_date": "2099-01-01"},
                  headers=admin_headers, timeout=20)
    requests.post(base, json={**_body_sales(), "status": "done"},
                  headers=admin_headers, timeout=20)
    s = requests.get(f"{API}/events/{ev}/planner/summary",
                     headers=admin_headers, timeout=20).json()
    assert s["counts"]["sales_tasks"] == 3
    assert s["counts"]["open_sales_tasks"] == 2
    assert s["counts"]["overdue_sales_tasks"] == 1


# ===========================================================================
# 11. dark_ads_by_status
# ===========================================================================
def test_summary_dark_ads_by_status(admin_headers):
    ev = _new_event(admin_headers, "DA")
    base = f"{API}/events/{ev}/dark-ad-plans"
    for st in ("active", "planned", "planned"):
        r = requests.post(base, json={**_body_darkad(), "status": st},
                          headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
    s = requests.get(f"{API}/events/{ev}/planner/summary",
                     headers=admin_headers, timeout=20).json()
    assert s["dark_ads_by_status"] == {"active": 1, "planned": 2}


# ===========================================================================
# 12. Event dashboard includes 'planner' block; global does not
# ===========================================================================
def test_event_dashboard_includes_planner(admin_headers, event_id):
    r = requests.get(f"{API}/dashboard/event/{event_id}",
                     headers=admin_headers, timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert "planner" in body
    p = body["planner"]
    assert "counts" in p and "budget_by_channel" in p and "dark_ads_by_status" in p


def test_global_dashboard_excludes_planner(admin_headers):
    r = requests.get(f"{API}/dashboard", headers=admin_headers, timeout=20)
    if r.status_code == 200:
        assert "planner" not in r.json()


# ===========================================================================
# 13. No external send routes added in Patch 4
# ===========================================================================
def test_no_send_routes_added():
    forbidden = ("send-meta", "send-youtube", "send-whatsapp", "send-email",
                 "meta-send", "youtube-send", "whatsapp-send", "email-send")
    paths = [r.path for r in server.app.routes if hasattr(r, "path")]
    for p in paths:
        low = p.lower()
        for f in forbidden:
            assert f not in low, f"Unexpected send route: {p}"


# ===========================================================================
# 14. Empty planner summary → zeros
# ===========================================================================
def test_summary_empty_event(admin_headers):
    ev = _new_event(admin_headers, "EMPTY")
    s = requests.get(f"{API}/events/{ev}/planner/summary",
                     headers=admin_headers, timeout=20).json()
    c = s["counts"]
    for k in ("content_requirements", "overdue_content", "email_plans",
              "approved_email_plans", "whatsapp_plans", "approved_whatsapp_plans",
              "upsell_plans", "approved_upsell_plans", "budget_plans",
              "dark_ad_plans", "sales_tasks", "open_sales_tasks",
              "overdue_sales_tasks"):
        assert c[k] == 0, f"expected {k}=0"
    assert s["budget_by_channel"] == []
    assert s["dark_ads_by_status"] == {}


# ===========================================================================
# 15. Cross-tenant planner summary → 404
# ===========================================================================
def test_summary_cross_tenant_404(admin_headers, tenant_b):
    r = requests.get(
        f"{API}/events/{tenant_b['event_id']}/planner/summary",
        headers=admin_headers, timeout=20,
    )
    assert r.status_code == 404
