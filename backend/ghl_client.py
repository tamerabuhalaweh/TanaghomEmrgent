"""GoHighLevel (LeadConnector) client adapter.

Isolated from server.py for testability and clean mocking:
- Pure normalization functions
- Pure mapping helpers
- Thin async HTTP wrappers

No hardcoded credentials. Callers pass in tenant-owned config + api_key.
"""
from __future__ import annotations

from typing import Any, Optional
import httpx


DEFAULT_BASE_URL = "https://services.leadconnectorhq.com"
DEFAULT_API_VERSION = "2021-07-28"

# Lead status/temperature vocabularies (kept in sync with server.py enums).
LEAD_STATUS_VALUES = (
    "new", "form_filled", "booked", "purchased",
    "no_show", "lost", "follow_up_needed",
)
LEAD_TEMPERATURE_VALUES = ("cold", "warm", "hot", "buyer")

# Opportunity status hints that indicate a purchase.
PURCHASE_OPPORTUNITY_STATUSES = ("won", "closed_won", "purchased")


# ---------------------------------------------------------------------------
# Config / headers
# ---------------------------------------------------------------------------
def ghl_headers(api_key: str, api_version: str = DEFAULT_API_VERSION) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Version": api_version,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _resolve_config(config: Optional[dict]) -> dict:
    cfg = dict(config or {})
    cfg.setdefault("base_url", DEFAULT_BASE_URL)
    cfg.setdefault("api_version", DEFAULT_API_VERSION)
    return cfg


# ---------------------------------------------------------------------------
# Normalization (robust to varying GHL response shapes)
# ---------------------------------------------------------------------------
def _pick_list(payload: Any, keys: tuple) -> list:
    """Return the first list found under one of the given keys (nested or flat)."""
    if not isinstance(payload, dict):
        return payload if isinstance(payload, list) else []
    for k in keys:
        if isinstance(payload.get(k), list):
            return payload[k]
    data = payload.get("data")
    if isinstance(data, dict):
        for k in keys:
            if isinstance(data.get(k), list):
                return data[k]
    if isinstance(data, list):
        return data
    return []


def extract_contacts(raw: Any) -> list:
    return _pick_list(raw, ("contacts", "items", "results"))


def extract_opportunities(raw: Any) -> list:
    return _pick_list(raw, ("opportunities", "items", "results"))


def normalize_ghl_contact(raw: dict) -> dict:
    """Return only the fields we surface to the local layer."""
    if not isinstance(raw, dict):
        return {}
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    email = raw.get("email") or raw.get("emailAddress")
    phone = raw.get("phone") or raw.get("phoneNumber")
    name = (
        raw.get("contactName")
        or raw.get("fullName")
        or " ".join(x for x in (raw.get("firstName"), raw.get("lastName")) if x).strip()
        or (email or phone or "Unknown")
    )
    return {
        "ghl_contact_id": raw.get("id") or raw.get("contactId"),
        "name": name,
        "email": email,
        "phone": phone,
        "tags": [str(t).strip() for t in tags if str(t).strip()],
    }


def normalize_ghl_opportunity(raw: dict) -> dict:
    if not isinstance(raw, dict):
        return {}
    contact = raw.get("contact") or {}
    contact_id = (
        raw.get("contactId")
        or contact.get("id")
        or raw.get("contact_id")
    )
    status = raw.get("status") or raw.get("opportunityStatus") or ""
    return {
        "ghl_opportunity_id": raw.get("id"),
        "ghl_contact_id": contact_id,
        "pipeline_id": raw.get("pipelineId") or raw.get("pipeline_id"),
        "stage_id": raw.get("pipelineStageId") or raw.get("stageId") or raw.get("stage_id"),
        "opportunity_status": str(status).lower() if status else "",
        "monetary_value": float(raw.get("monetaryValue") or raw.get("monetary_value") or 0),
    }


# ---------------------------------------------------------------------------
# Mapping — apply tenant tag/pipeline-stage mappings to a GHL contact
# ---------------------------------------------------------------------------
def _index_mappings(mappings: list) -> dict:
    """Split mappings by mapping_type/target_type for O(1) lookup."""
    idx: dict = {
        "tag_status": {},          # ghl_name -> lead_status
        "tag_temperature": {},     # ghl_name -> lead_temperature
        "stage_status_by_id": {},  # ghl_id -> lead_status
        "stage_status_by_name": {},
        "stage_temperature_by_id": {},
        "stage_temperature_by_name": {},
    }
    for m in mappings or []:
        mt = m.get("mapping_type")
        tt = m.get("target_type")
        tv = m.get("target_value")
        gid = m.get("ghl_id")
        gname = (m.get("ghl_name") or "").strip()
        if mt == "tag":
            key = "tag_status" if tt == "lead_status" else "tag_temperature"
            if gname:
                idx[key][gname.lower()] = tv
        elif mt == "pipeline_stage":
            if tt == "lead_status":
                if gid:
                    idx["stage_status_by_id"][gid] = tv
                if gname:
                    idx["stage_status_by_name"][gname.lower()] = tv
            else:
                if gid:
                    idx["stage_temperature_by_id"][gid] = tv
                if gname:
                    idx["stage_temperature_by_name"][gname.lower()] = tv
    return idx


def map_ghl_lead(contact: dict, opportunities: list, mappings: list) -> dict:
    """Combine a normalized contact with matching opportunities + mappings.

    Returns a preview dict — never a raw GHL payload.
    """
    idx = _index_mappings(mappings)
    matched_opps = [
        o for o in opportunities
        if o.get("ghl_contact_id") and o["ghl_contact_id"] == contact.get("ghl_contact_id")
    ]
    primary = matched_opps[0] if matched_opps else {}

    tags = contact.get("tags") or []
    mapped_status: Optional[str] = None
    mapped_temperature: Optional[str] = None

    # 1) Try tags first (higher intent signal)
    for t in tags:
        low = t.lower()
        if not mapped_status and low in idx["tag_status"]:
            mapped_status = idx["tag_status"][low]
        if not mapped_temperature and low in idx["tag_temperature"]:
            mapped_temperature = idx["tag_temperature"][low]

    # 2) Fall back to pipeline stage
    if primary:
        sid = primary.get("stage_id")
        if not mapped_status:
            mapped_status = idx["stage_status_by_id"].get(sid)
        if not mapped_temperature:
            mapped_temperature = idx["stage_temperature_by_id"].get(sid)

    # 3) Purchase override — always wins for status+temperature
    opp_status = (primary.get("opportunity_status") or "").lower()
    if opp_status in PURCHASE_OPPORTUNITY_STATUSES:
        mapped_status = "purchased"
        mapped_temperature = "buyer"

    return {
        "ghl_contact_id": contact.get("ghl_contact_id"),
        "ghl_opportunity_id": primary.get("ghl_opportunity_id"),
        "name": contact.get("name"),
        "email": contact.get("email"),
        "phone": contact.get("phone"),
        "tags": tags,
        "pipeline_id": primary.get("pipeline_id"),
        "stage_id": primary.get("stage_id"),
        "opportunity_status": opp_status,
        "monetary_value": float(primary.get("monetary_value") or 0),
        "mapped_lead_status": mapped_status,
        "mapped_lead_temperature": mapped_temperature,
        "source_of_truth": "gohighlevel",
    }


# ---------------------------------------------------------------------------
# HTTP calls — never called unless credential + env flag are both true
# ---------------------------------------------------------------------------
async def fetch_contacts(config: dict, api_key: str, limit: int = 50) -> list:
    cfg = _resolve_config(config)
    url = f"{cfg['base_url']}/contacts/search"
    body = {
        "locationId": cfg.get("location_id"),
        "pageLimit": max(1, min(int(limit), 200)),
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(url, headers=ghl_headers(api_key, cfg["api_version"]), json=body)
        resp.raise_for_status()
        return extract_contacts(resp.json())


async def fetch_opportunities(config: dict, api_key: str, limit: int = 50) -> list:
    cfg = _resolve_config(config)
    url = f"{cfg['base_url']}/opportunities/search"
    params = {
        "location_id": cfg.get("location_id"),
        "limit": max(1, min(int(limit), 200)),
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, headers=ghl_headers(api_key, cfg["api_version"]), params=params)
        resp.raise_for_status()
        return extract_opportunities(resp.json())


def build_write_back_payload(lead: dict, mappings: list) -> dict:
    """Compute a preview payload — does NOT call GHL."""
    idx = _index_mappings(mappings)
    tags_out = []
    for tag_name, target in idx["tag_status"].items():
        if target == lead.get("stage"):
            tags_out.append(tag_name)
    for tag_name, target in idx["tag_temperature"].items():
        if target == lead.get("lead_temperature"):
            tags_out.append(tag_name)
    return {
        "contact_id": lead.get("external_source_id"),
        "tags": sorted(set(tags_out)),
        "custom_fields": {
            "local_lead_status": lead.get("stage"),
            "local_lead_temperature": lead.get("lead_temperature"),
            "next_action": lead.get("notes"),
        },
    }
