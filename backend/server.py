"""AI Campaign Manager — FastAPI backend.

Production foundation:
- Multi-tenant (workspace) isolation on every business collection.
- Audit log for all sensitive mutations.
- Honest metrics: no random production data. `metric_source` explicit.
- Fail-fast environment validation on boot.
- No wildcard CORS fallback.
"""
from __future__ import annotations

import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, APIRouter, Depends, HTTPException, status, Body
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr, ConfigDict
import jwt as pyjwt
import bcrypt

from crypto_utils import encrypt, decrypt, mask
import llm_service
import ghl_client


# ---------------------------------------------------------------------------
# Environment validation (fail-fast)
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

REQUIRED_ENV = ("MONGO_URL", "DB_NAME", "JWT_SECRET", "FERNET_KEY", "CORS_ORIGINS")
_missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
if _missing:
    raise RuntimeError(
        f"Missing required environment variables: {', '.join(_missing)}. "
        "Backend will not start until all are provided."
    )

# Validate FERNET_KEY at startup — fail fast rather than at first encrypt.
try:
    from cryptography.fernet import Fernet as _Fernet
    _Fernet(os.environ["FERNET_KEY"].encode())
except Exception as _e:
    raise RuntimeError(f"Invalid FERNET_KEY: {_e}")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
CORS_ORIGINS = [o.strip() for o in os.environ["CORS_ORIGINS"].split(",") if o.strip()]
if not CORS_ORIGINS:
    raise RuntimeError("CORS_ORIGINS must resolve to at least one explicit origin.")
if any(o == "*" for o in CORS_ORIGINS):
    raise RuntimeError(
        "CORS_ORIGINS='*' is not permitted. Provide explicit, comma-separated origins."
    )

JWT_ALG = "HS256"
JWT_EXP_HOURS = 24 * 7
DEFAULT_TENANT_SLUG = "default"
DEFAULT_TENANT_NAME = "Default Workspace"

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="AI Campaign Manager")
api = APIRouter(prefix="/api")
bearer = HTTPBearer(auto_error=False)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("campaign")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(doc: Optional[dict]) -> Optional[dict]:
    if doc is None:
        return doc
    doc.pop("_id", None)
    return doc


# --- Audit log helper ------------------------------------------------------
_SECRET_KEY_HINTS = (
    "password", "api_key", "access_token", "secret", "token",
    "key_enc", "fernet", "authorization",
)


def _sanitize_metadata(meta: Optional[dict]) -> dict:
    """Strip anything that even looks like a secret before persistence."""
    if not meta:
        return {}
    out: dict = {}
    for k, v in meta.items():
        lower = str(k).lower()
        if any(h in lower for h in _SECRET_KEY_HINTS):
            out[k] = "[redacted]"
        else:
            out[k] = v
    return out


async def audit(
    *,
    tenant_id: Optional[str],
    actor_user_id: Optional[str],
    action: str,
    object_type: str,
    object_id: Optional[str] = None,
    result: str = "success",
    metadata: Optional[dict] = None,
) -> None:
    """Persist an audit entry. Never store raw secrets in metadata."""
    entry = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "actor_user_id": actor_user_id,
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
        "result": result,  # success | failure | blocked
        "metadata": _sanitize_metadata(metadata),
        "created_at": _now_iso(),
    }
    try:
        await db.audit_logs.insert_one(entry)
    except Exception:
        log.exception("Failed to write audit log for action=%s", action)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
ROLES = ("admin", "marketing", "sales", "social", "viewer")
PERMISSIONS_BY_ROLE = {
    "admin": ["*"],
    "marketing": ["events.read", "events.write", "campaigns.write", "posts.write", "ai.generate", "dashboard.read", "planner.write"],
    "sales": ["events.read", "leads.write", "dashboard.read", "planner.sales"],
    "social": ["events.read", "content.write", "dark_ads.write", "dashboard.read"],
    "viewer": ["events.read", "dashboard.read"],
}
VALID_INTEGRATION_KINDS = ("gohighlevel", "zapier", "webhook")
METRIC_SOURCES = ("none", "manual", "imported", "connector")

# GHL vocabularies
GHL_MAPPING_TYPES = ("tag", "pipeline_stage")
GHL_MAPPING_TARGET_TYPES = ("lead_status", "lead_temperature")
GHL_MAPPING_DIRECTIONS = ("inbound", "outbound", "bidirectional")
LEAD_STATUS_VALUES = (
    "new", "form_filled", "booked", "purchased",
    "no_show", "lost", "follow_up_needed",
)
LEAD_TEMPERATURE_VALUES = ("cold", "warm", "hot", "buyer")

# Event KPI record schema (verified analytics layer — no external calls).
KPI_CHANNELS = (
    "meta", "instagram", "youtube", "whatsapp", "email",
    "organic", "dark_ad", "referral", "manual", "other",
)
KPI_SOURCE_TYPES = ("manual", "csv_import", "connector")
KPI_INT_FIELDS = (
    "reach", "impressions", "interactions", "clicks",
    "form_completions", "leads", "meetings_booked",
    "meetings_attended", "no_shows", "purchases",
)
KPI_FLOAT_FIELDS = ("spend", "revenue")
KPI_NUMERIC_FIELDS = KPI_INT_FIELDS + KPI_FLOAT_FIELDS


class BaseDoc(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)


class TenantOut(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    created_at: str


class UserPublic(BaseModel):
    id: str
    tenant_id: str
    email: EmailStr
    name: str
    role: str
    permissions: List[str] = []
    is_active: bool = True
    created_at: str


class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: str = "marketing"
    permissions: Optional[List[str]] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    permissions: Optional[List[str]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    token: str
    user: UserPublic


class LLMKeyIn(BaseModel):
    provider: str
    api_key: str
    model: Optional[str] = None
    label: Optional[str] = None


class LLMKeyOut(BaseModel):
    id: str
    provider: str
    model: Optional[str]
    label: Optional[str]
    key_masked: str
    use_emergent: bool = False
    created_at: str


class SocialAccountIn(BaseModel):
    platform: str
    handle: str
    access_token: str
    page_id: Optional[str] = None


class SocialAccountOut(BaseModel):
    id: str
    platform: str
    handle: str
    page_id: Optional[str]
    token_masked: str
    created_at: str


class IntegrationIn(BaseModel):
    kind: str
    label: str
    api_key: Optional[str] = None
    webhook_url: Optional[str] = None
    config: Optional[dict] = None


class IntegrationOut(BaseModel):
    id: str
    kind: str
    label: str
    api_key_masked: Optional[str]
    webhook_url: Optional[str]
    config: Optional[dict]
    status: str = "credential_saved"
    validated: bool = False
    live_sync_enabled: bool = False
    created_at: str


class EventIn(BaseModel):
    name: str
    type: str = "custom"
    description: Optional[str] = None
    start_date: str
    end_date: Optional[str] = None
    location: Optional[str] = None
    budget_planned: float = 0.0
    ticket_price: Optional[float] = None
    cover_image: Optional[str] = None


class EventOut(BaseDoc):
    name: str
    type: str
    description: Optional[str] = None
    start_date: str
    end_date: Optional[str] = None
    location: Optional[str] = None
    budget_planned: float = 0.0
    budget_actual: float = 0.0
    ticket_price: Optional[float] = None
    cover_image: Optional[str] = None
    status: str = "planning"


class CampaignIn(BaseModel):
    event_id: str
    name: str
    goal: str = "max_reach"
    start_date: str
    end_date: str
    budget_planned: float = 0.0
    platforms: List[str] = []
    audience: Optional[dict] = None


class CampaignOut(BaseDoc):
    event_id: str
    name: str
    goal: str
    start_date: str
    end_date: str
    budget_planned: float = 0.0
    budget_actual: float = 0.0
    platforms: List[str] = []
    audience: Optional[dict] = None
    status: str = "draft"


class PostGenerateIn(BaseModel):
    campaign_id: Optional[str] = None
    event_id: Optional[str] = None
    prompt: str
    platforms: List[str] = []
    audience: Optional[dict] = None
    goal: str = "max_reach"
    provider: str = "openai"
    model: Optional[str] = None
    n: int = 4
    language: str = "en"


class PostIn(BaseModel):
    campaign_id: str
    platform: str
    format: str = "text"
    hook: Optional[str] = None
    caption: str
    cta: Optional[str] = None
    hashtags: List[str] = []
    reasoning: Optional[str] = None
    status: str = "draft"
    scheduled_at: Optional[str] = None


class PostOut(BaseDoc):
    campaign_id: str
    platform: str
    format: str
    hook: Optional[str] = None
    caption: str
    cta: Optional[str] = None
    hashtags: List[str] = []
    reasoning: Optional[str] = None
    status: str = "draft"
    scheduled_at: Optional[str] = None
    # Real metrics only. Default 0 until manually recorded or imported.
    reach: int = 0
    impressions: int = 0
    clicks: int = 0
    engagement: int = 0
    metric_source: str = "none"  # none | manual | imported | connector


class PostUpdate(BaseModel):
    status: Optional[str] = None
    caption: Optional[str] = None
    hook: Optional[str] = None
    cta: Optional[str] = None
    hashtags: Optional[List[str]] = None
    scheduled_at: Optional[str] = None
    # Optional explicit metric overrides (marks metric_source='manual').
    reach: Optional[int] = None
    impressions: Optional[int] = None
    clicks: Optional[int] = None
    engagement: Optional[int] = None


class LeadIn(BaseModel):
    event_id: str
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    source: str = "form"
    stage: str = "new"
    tag: Optional[str] = None
    notes: Optional[str] = None
    lead_temperature: Optional[str] = None


class LeadOut(BaseDoc):
    event_id: Optional[str] = None
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    source: str
    stage: str
    tag: Optional[str] = None
    notes: Optional[str] = None
    # CRM-of-truth linkage
    source_of_truth: str = "local"  # local | gohighlevel
    lead_temperature: Optional[str] = None  # cold | warm | hot | buyer
    external_source_provider: Optional[str] = None  # e.g. "gohighlevel"
    external_source_id: Optional[str] = None
    external_opportunity_id: Optional[str] = None
    external_tags: List[str] = []
    external_stage_id: Optional[str] = None
    external_last_synced_at: Optional[str] = None
    purchase_amount: Optional[float] = None


# --- GHL models ------------------------------------------------------------
class GhlMappingIn(BaseModel):
    mapping_type: str  # tag | pipeline_stage
    ghl_id: Optional[str] = None
    ghl_name: str
    target_type: str   # lead_status | lead_temperature
    target_value: str
    direction: str = "inbound"


class GhlMappingUpdate(BaseModel):
    mapping_type: Optional[str] = None
    ghl_id: Optional[str] = None
    ghl_name: Optional[str] = None
    target_type: Optional[str] = None
    target_value: Optional[str] = None
    direction: Optional[str] = None


class GhlMappingOut(BaseDoc):
    mapping_type: str
    ghl_id: Optional[str] = None
    ghl_name: str
    target_type: str
    target_value: str
    direction: str = "inbound"
    updated_at: Optional[str] = None


class GhlPullIn(BaseModel):
    event_id: Optional[str] = None
    limit: int = 50


class GhlWriteBackIn(BaseModel):
    lead_id: str


class AuditLogOut(BaseModel):
    id: str
    tenant_id: Optional[str]
    actor_user_id: Optional[str]
    action: str
    object_type: str
    object_id: Optional[str] = None
    result: str
    metadata: dict = {}
    created_at: str


# --- Event KPI (verified metrics) ------------------------------------------
class KpiRowInput(BaseModel):
    """One KPI row as accepted from create/csv-import payloads."""
    metric_date: str
    channel: str
    campaign_id: Optional[str] = None
    reach: int = 0
    impressions: int = 0
    interactions: int = 0
    clicks: int = 0
    form_completions: int = 0
    leads: int = 0
    meetings_booked: int = 0
    meetings_attended: int = 0
    no_shows: int = 0
    purchases: int = 0
    spend: float = 0.0
    revenue: float = 0.0
    notes: Optional[str] = None


class KpiUpdate(BaseModel):
    metric_date: Optional[str] = None
    channel: Optional[str] = None
    campaign_id: Optional[str] = None
    reach: Optional[int] = None
    impressions: Optional[int] = None
    interactions: Optional[int] = None
    clicks: Optional[int] = None
    form_completions: Optional[int] = None
    leads: Optional[int] = None
    meetings_booked: Optional[int] = None
    meetings_attended: Optional[int] = None
    no_shows: Optional[int] = None
    purchases: Optional[int] = None
    spend: Optional[float] = None
    revenue: Optional[float] = None
    notes: Optional[str] = None


class KpiRecordOut(BaseDoc):
    event_id: str
    campaign_id: Optional[str] = None
    metric_date: str
    channel: str
    source_type: str
    source_name: Optional[str] = None
    reach: int = 0
    impressions: int = 0
    interactions: int = 0
    clicks: int = 0
    form_completions: int = 0
    leads: int = 0
    meetings_booked: int = 0
    meetings_attended: int = 0
    no_shows: int = 0
    purchases: int = 0
    spend: float = 0.0
    revenue: float = 0.0
    notes: Optional[str] = None
    created_by_user_id: Optional[str] = None
    updated_at: Optional[str] = None


class CsvRowsIn(BaseModel):
    rows: List[KpiRowInput]


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def make_token(user_id: str, role: str, tenant_id: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "tenant_id": tenant_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXP_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


async def current_user(cred: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> dict:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    try:
        payload = pyjwt.decode(cred.credentials, JWT_SECRET, algorithms=[JWT_ALG])
    except pyjwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
    if not user or not user.get("is_active", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or not found")
    if not user.get("tenant_id"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User has no tenant assignment")
    return user


def require_role(*roles: str):
    async def _dep(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user
    return _dep


def to_public(user: dict) -> UserPublic:
    return UserPublic(
        id=user["id"],
        tenant_id=user["tenant_id"],
        email=user["email"],
        name=user["name"],
        role=user["role"],
        permissions=user.get("permissions") or PERMISSIONS_BY_ROLE.get(user["role"], []),
        is_active=user.get("is_active", True),
        created_at=user["created_at"],
    )


def _tq(user: dict, extra: Optional[dict] = None) -> dict:
    """Build a Mongo query scoped to the caller's tenant_id."""
    q: dict = {"tenant_id": user["tenant_id"]}
    if extra:
        q.update(extra)
    return q


# ---------------------------------------------------------------------------
# Routes: Auth
# ---------------------------------------------------------------------------
@api.post("/auth/login", response_model=AuthResponse)
async def login(body: LoginBody):
    user = await db.users.find_one({"email": body.email.lower()}, {"_id": 0})
    if not user or not verify_password(body.password, user["password_hash"]):
        await audit(
            tenant_id=user.get("tenant_id") if user else None,
            actor_user_id=user.get("id") if user else None,
            action="login.failure", object_type="user",
            object_id=user.get("id") if user else None,
            result="failure", metadata={"email": body.email.lower()},
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not user.get("is_active", True):
        await audit(
            tenant_id=user["tenant_id"], actor_user_id=user["id"],
            action="login.failure", object_type="user",
            object_id=user["id"], result="blocked", metadata={"reason": "disabled"},
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
    if not user.get("tenant_id"):
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "User has no tenant")
    token = make_token(user["id"], user["role"], user["tenant_id"])
    await audit(
        tenant_id=user["tenant_id"], actor_user_id=user["id"],
        action="login.success", object_type="user", object_id=user["id"],
    )
    return AuthResponse(token=token, user=to_public(user))


@api.get("/auth/me", response_model=UserPublic)
async def me(user: dict = Depends(current_user)):
    return to_public(user)


# ---------------------------------------------------------------------------
# Routes: Users (tenant-scoped)
# ---------------------------------------------------------------------------
@api.get("/users", response_model=List[UserPublic])
async def list_users(user: dict = Depends(require_role("admin"))):
    docs = await db.users.find(_tq(user), {"_id": 0}).to_list(500)
    return [to_public(d) for d in docs]


@api.post("/users", response_model=UserPublic)
async def create_user(body: UserCreate, actor: dict = Depends(require_role("admin"))):
    if body.role not in ROLES:
        raise HTTPException(400, "Invalid role")
    existing = await db.users.find_one({"email": body.email.lower()})
    if existing:
        raise HTTPException(409, "Email already exists")
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": actor["tenant_id"],
        "email": body.email.lower(),
        "name": body.name,
        "role": body.role,
        "permissions": body.permissions or PERMISSIONS_BY_ROLE[body.role],
        "password_hash": hash_password(body.password),
        "is_active": True,
        "created_at": _now_iso(),
    }
    await db.users.insert_one(doc)
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="user.created", object_type="user", object_id=doc["id"],
        metadata={"email": doc["email"], "role": doc["role"]},
    )
    return to_public(doc)


@api.patch("/users/{user_id}", response_model=UserPublic)
async def update_user(user_id: str, body: UserUpdate, actor: dict = Depends(require_role("admin"))):
    update = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "password" in update:
        update["password_hash"] = hash_password(update.pop("password"))
    if not update:
        raise HTTPException(400, "Nothing to update")
    result = await db.users.find_one_and_update(
        _tq(actor, {"id": user_id}), {"$set": update}, return_document=True
    )
    if not result:
        raise HTTPException(404, "User not found")
    result.pop("_id", None)
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="user.updated", object_type="user", object_id=user_id,
        metadata={"fields": list(update.keys())},
    )
    return to_public(result)


@api.delete("/users/{user_id}")
async def delete_user(user_id: str, actor: dict = Depends(require_role("admin"))):
    if actor["id"] == user_id:
        raise HTTPException(400, "Cannot delete self")
    r = await db.users.delete_one(_tq(actor, {"id": user_id}))
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="user.deleted", object_type="user", object_id=user_id,
        result="success" if r.deleted_count else "failure",
    )
    return {"deleted": r.deleted_count}


# ---------------------------------------------------------------------------
# Routes: Settings — LLM keys, Social accounts, Integrations (tenant-scoped)
# ---------------------------------------------------------------------------
@api.get("/settings/llm-keys", response_model=List[LLMKeyOut])
async def list_llm_keys(user: dict = Depends(require_role("admin"))):
    docs = await db.llm_keys.find(_tq(user), {"_id": 0}).to_list(200)
    return [
        LLMKeyOut(
            id=d["id"], provider=d["provider"], model=d.get("model"),
            label=d.get("label"), key_masked=mask(decrypt(d["api_key_enc"])),
            use_emergent=d.get("use_emergent", False), created_at=d["created_at"],
        )
        for d in docs
    ]


@api.post("/settings/llm-keys", response_model=LLMKeyOut)
async def add_llm_key(body: LLMKeyIn, actor: dict = Depends(require_role("admin"))):
    if body.provider not in ("openai", "anthropic", "gemini"):
        raise HTTPException(400, "Unsupported provider")
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": actor["tenant_id"],
        "provider": body.provider, "model": body.model, "label": body.label,
        "api_key_enc": encrypt(body.api_key), "use_emergent": False,
        "created_at": _now_iso(),
    }
    await db.llm_keys.insert_one(doc)
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="llm_key.added", object_type="llm_key", object_id=doc["id"],
        metadata={"provider": body.provider, "label": body.label},
    )
    return LLMKeyOut(
        id=doc["id"], provider=doc["provider"], model=doc.get("model"),
        label=doc.get("label"), key_masked=mask(body.api_key),
        use_emergent=False, created_at=doc["created_at"],
    )


@api.delete("/settings/llm-keys/{key_id}")
async def delete_llm_key(key_id: str, actor: dict = Depends(require_role("admin"))):
    r = await db.llm_keys.delete_one(_tq(actor, {"id": key_id}))
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="llm_key.deleted", object_type="llm_key", object_id=key_id,
        result="success" if r.deleted_count else "failure",
    )
    return {"deleted": r.deleted_count}


@api.get("/settings/social-accounts", response_model=List[SocialAccountOut])
async def list_social(user: dict = Depends(require_role("admin"))):
    docs = await db.social_accounts.find(_tq(user), {"_id": 0}).to_list(200)
    return [
        SocialAccountOut(
            id=d["id"], platform=d["platform"], handle=d["handle"],
            page_id=d.get("page_id"), token_masked=mask(decrypt(d["token_enc"])),
            created_at=d["created_at"],
        )
        for d in docs
    ]


@api.post("/settings/social-accounts", response_model=SocialAccountOut)
async def add_social(body: SocialAccountIn, actor: dict = Depends(require_role("admin"))):
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": actor["tenant_id"],
        "platform": body.platform, "handle": body.handle, "page_id": body.page_id,
        "token_enc": encrypt(body.access_token), "created_at": _now_iso(),
    }
    await db.social_accounts.insert_one(doc)
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="social_account.added", object_type="social_account",
        object_id=doc["id"],
        metadata={"platform": body.platform, "handle": body.handle},
    )
    return SocialAccountOut(
        id=doc["id"], platform=doc["platform"], handle=doc["handle"],
        page_id=doc.get("page_id"), token_masked=mask(body.access_token),
        created_at=doc["created_at"],
    )


@api.delete("/settings/social-accounts/{sid}")
async def delete_social(sid: str, actor: dict = Depends(require_role("admin"))):
    r = await db.social_accounts.delete_one(_tq(actor, {"id": sid}))
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="social_account.deleted", object_type="social_account",
        object_id=sid, result="success" if r.deleted_count else "failure",
    )
    return {"deleted": r.deleted_count}


@api.get("/integrations", response_model=List[IntegrationOut])
async def list_integrations(user: dict = Depends(require_role("admin"))):
    docs = await db.integrations.find(_tq(user), {"_id": 0}).to_list(200)
    return [
        IntegrationOut(
            id=d["id"], kind=d["kind"], label=d["label"],
            api_key_masked=mask(decrypt(d["api_key_enc"])) if d.get("api_key_enc") else None,
            webhook_url=d.get("webhook_url"), config=d.get("config"),
            status=d.get("status", "credential_saved"),
            validated=d.get("validated", False),
            live_sync_enabled=d.get("live_sync_enabled", False),
            created_at=d["created_at"],
        )
        for d in docs
    ]


@api.post("/integrations", response_model=IntegrationOut)
async def add_integration(body: IntegrationIn, actor: dict = Depends(require_role("admin"))):
    if body.kind not in VALID_INTEGRATION_KINDS:
        raise HTTPException(
            400, f"Unsupported integration kind. Allowed: {', '.join(VALID_INTEGRATION_KINDS)}"
        )
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": actor["tenant_id"],
        "kind": body.kind, "label": body.label,
        "api_key_enc": encrypt(body.api_key) if body.api_key else None,
        "webhook_url": body.webhook_url, "config": body.config,
        "status": "credential_saved",
        "validated": False,
        "live_sync_enabled": False,
        "created_at": _now_iso(),
    }
    await db.integrations.insert_one(doc)
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="integration.added", object_type="integration",
        object_id=doc["id"], metadata={"kind": body.kind, "label": body.label},
    )
    return IntegrationOut(
        id=doc["id"], kind=doc["kind"], label=doc["label"],
        api_key_masked=mask(body.api_key) if body.api_key else None,
        webhook_url=doc.get("webhook_url"), config=doc.get("config"),
        status=doc["status"], validated=False, live_sync_enabled=False,
        created_at=doc["created_at"],
    )


@api.delete("/integrations/{iid}")
async def delete_integration(iid: str, actor: dict = Depends(require_role("admin"))):
    r = await db.integrations.delete_one(_tq(actor, {"id": iid}))
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="integration.deleted", object_type="integration",
        object_id=iid, result="success" if r.deleted_count else "failure",
    )
    return {"deleted": r.deleted_count}


# ---------------------------------------------------------------------------
# Routes: Events (tenant-scoped)
# ---------------------------------------------------------------------------
@api.get("/events", response_model=List[EventOut])
async def list_events(user: dict = Depends(current_user)):
    docs = await db.events.find(_tq(user), {"_id": 0}).sort("created_at", -1).to_list(500)
    return [EventOut(**d) for d in docs]


@api.post("/events", response_model=EventOut)
async def create_event(body: EventIn, actor: dict = Depends(require_role("admin", "marketing"))):
    doc = EventOut(**body.model_dump(), tenant_id=actor["tenant_id"]).model_dump()
    await db.events.insert_one(doc)
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="event.created", object_type="event", object_id=doc["id"],
        metadata={"name": doc["name"], "type": doc["type"]},
    )
    return EventOut(**_clean(doc))


@api.get("/events/{event_id}", response_model=EventOut)
async def get_event(event_id: str, user: dict = Depends(current_user)):
    d = await db.events.find_one(_tq(user, {"id": event_id}), {"_id": 0})
    if not d:
        raise HTTPException(404, "Event not found")
    return EventOut(**d)


@api.patch("/events/{event_id}", response_model=EventOut)
async def update_event(event_id: str, body: dict, actor: dict = Depends(require_role("admin", "marketing"))):
    for reserved in ("id", "_id", "created_at", "tenant_id"):
        body.pop(reserved, None)
    d = await db.events.find_one_and_update(
        _tq(actor, {"id": event_id}), {"$set": body}, return_document=True
    )
    if not d:
        raise HTTPException(404, "Event not found")
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="event.updated", object_type="event", object_id=event_id,
        metadata={"fields": list(body.keys())},
    )
    return EventOut(**_clean(d))


@api.delete("/events/{event_id}")
async def delete_event(event_id: str, actor: dict = Depends(require_role("admin"))):
    r = await db.events.delete_one(_tq(actor, {"id": event_id}))
    await db.campaigns.delete_many(_tq(actor, {"event_id": event_id}))
    await db.posts.delete_many(_tq(actor, {"event_id": event_id}))
    await db.leads.delete_many(_tq(actor, {"event_id": event_id}))
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="event.deleted", object_type="event", object_id=event_id,
        result="success" if r.deleted_count else "failure",
    )
    return {"deleted": r.deleted_count}


# ---------------------------------------------------------------------------
# Routes: Campaigns (tenant-scoped)
# ---------------------------------------------------------------------------
@api.get("/events/{event_id}/campaigns", response_model=List[CampaignOut])
async def list_campaigns(event_id: str, user: dict = Depends(current_user)):
    docs = await db.campaigns.find(_tq(user, {"event_id": event_id}), {"_id": 0}).to_list(500)
    return [CampaignOut(**d) for d in docs]


@api.post("/campaigns", response_model=CampaignOut)
async def create_campaign(body: CampaignIn, actor: dict = Depends(require_role("admin", "marketing"))):
    ev = await db.events.find_one(_tq(actor, {"id": body.event_id}), {"_id": 0})
    if not ev:
        raise HTTPException(404, "Event not found in your workspace")
    doc = CampaignOut(**body.model_dump(), tenant_id=actor["tenant_id"]).model_dump()
    await db.campaigns.insert_one(doc)
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="campaign.created", object_type="campaign", object_id=doc["id"],
        metadata={"name": doc["name"], "event_id": doc["event_id"]},
    )
    return CampaignOut(**_clean(doc))


@api.patch("/campaigns/{cid}", response_model=CampaignOut)
async def update_campaign(cid: str, body: dict, actor: dict = Depends(require_role("admin", "marketing"))):
    for reserved in ("id", "_id", "created_at", "tenant_id"):
        body.pop(reserved, None)
    d = await db.campaigns.find_one_and_update(
        _tq(actor, {"id": cid}), {"$set": body}, return_document=True
    )
    if not d:
        raise HTTPException(404, "Campaign not found")
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="campaign.updated", object_type="campaign", object_id=cid,
        metadata={"fields": list(body.keys())},
    )
    return CampaignOut(**_clean(d))


@api.delete("/campaigns/{cid}")
async def delete_campaign(cid: str, actor: dict = Depends(require_role("admin", "marketing"))):
    r = await db.campaigns.delete_one(_tq(actor, {"id": cid}))
    await db.posts.delete_many(_tq(actor, {"campaign_id": cid}))
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="campaign.deleted", object_type="campaign", object_id=cid,
        result="success" if r.deleted_count else "failure",
    )
    return {"deleted": r.deleted_count}


# ---------------------------------------------------------------------------
# Routes: Posts (honest metrics)
# ---------------------------------------------------------------------------
@api.post("/posts/generate")
async def ai_generate_posts(body: PostGenerateIn, actor: dict = Depends(require_role("admin", "marketing"))):
    try:
        ideas = await llm_service.generate_post_ideas(
            prompt=body.prompt, provider=body.provider, model=body.model,
            platforms=body.platforms, audience=body.audience, goal=body.goal,
            n=max(1, min(body.n, 8)), language=body.language,
        )
    except Exception as e:
        log.exception("AI generation failed")
        await audit(
            tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
            action="post.generated", object_type="post",
            result="failure",
            metadata={"provider": body.provider, "error": str(e)[:200]},
        )
        raise HTTPException(500, f"AI generation failed: {e}")
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="post.generated", object_type="post",
        metadata={
            "provider": body.provider, "n": len(ideas or []),
            "platforms": body.platforms, "campaign_id": body.campaign_id,
        },
    )
    return {"ideas": ideas}


@api.get("/campaigns/{cid}/posts", response_model=List[PostOut])
async def list_posts(cid: str, user: dict = Depends(current_user)):
    docs = await db.posts.find(
        _tq(user, {"campaign_id": cid}), {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return [PostOut(**d) for d in docs]


@api.post("/posts", response_model=PostOut)
async def create_post(body: PostIn, actor: dict = Depends(require_role("admin", "marketing"))):
    camp = await db.campaigns.find_one(_tq(actor, {"id": body.campaign_id}), {"_id": 0})
    if not camp:
        raise HTTPException(404, "Campaign not found in your workspace")
    doc = PostOut(**body.model_dump(), tenant_id=actor["tenant_id"]).model_dump()
    # HONEST METRICS: no random seeding. All metrics start at 0, source='none'.
    doc["reach"] = 0
    doc["impressions"] = 0
    doc["clicks"] = 0
    doc["engagement"] = 0
    doc["metric_source"] = "none"
    await db.posts.insert_one(doc)
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="post.created", object_type="post", object_id=doc["id"],
        metadata={
            "platform": doc["platform"], "campaign_id": doc["campaign_id"],
            "status": doc["status"],
        },
    )
    if doc["status"] == "approved":
        await audit(
            tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
            action="post.approved", object_type="post", object_id=doc["id"],
        )
    return PostOut(**_clean(doc))


@api.patch("/posts/{pid}", response_model=PostOut)
async def update_post(pid: str, body: PostUpdate, actor: dict = Depends(require_role("admin", "marketing"))):
    update = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not update:
        raise HTTPException(400, "Nothing to update")
    metric_fields = {"reach", "impressions", "clicks", "engagement"}
    if any(k in update for k in metric_fields):
        # Explicit manual override marks source clearly.
        update["metric_source"] = "manual"
    d = await db.posts.find_one_and_update(
        _tq(actor, {"id": pid}), {"$set": update}, return_document=True
    )
    if not d:
        raise HTTPException(404, "Post not found")
    action = "post.updated"
    if body.status == "approved":
        action = "post.approved"
    elif body.status == "rejected":
        action = "post.rejected"
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action=action, object_type="post", object_id=pid,
        metadata={"fields": list(update.keys())},
    )
    return PostOut(**_clean(d))


@api.delete("/posts/{pid}")
async def delete_post(pid: str, actor: dict = Depends(require_role("admin", "marketing"))):
    r = await db.posts.delete_one(_tq(actor, {"id": pid}))
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="post.deleted", object_type="post", object_id=pid,
        result="success" if r.deleted_count else "failure",
    )
    return {"deleted": r.deleted_count}


# ---------------------------------------------------------------------------
# Routes: Leads (tenant-scoped)
# ---------------------------------------------------------------------------
@api.get("/events/{event_id}/leads", response_model=List[LeadOut])
async def list_leads(event_id: str, user: dict = Depends(current_user)):
    docs = await db.leads.find(
        _tq(user, {"event_id": event_id}), {"_id": 0}
    ).sort("created_at", -1).to_list(1000)
    return [LeadOut(**d) for d in docs]


@api.post("/leads", response_model=LeadOut)
async def create_lead(body: LeadIn, actor: dict = Depends(require_role("admin", "marketing", "sales"))):
    ev = await db.events.find_one(_tq(actor, {"id": body.event_id}), {"_id": 0})
    if not ev:
        raise HTTPException(404, "Event not found in your workspace")
    doc = LeadOut(**body.model_dump(), tenant_id=actor["tenant_id"]).model_dump()
    await db.leads.insert_one(doc)
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="lead.created", object_type="lead", object_id=doc["id"],
        metadata={"event_id": doc["event_id"], "stage": doc["stage"]},
    )
    return LeadOut(**_clean(doc))


@api.patch("/leads/{lid}", response_model=LeadOut)
async def update_lead(lid: str, body: dict, actor: dict = Depends(require_role("admin", "marketing", "sales"))):
    for reserved in ("id", "_id", "created_at", "tenant_id"):
        body.pop(reserved, None)
    d = await db.leads.find_one_and_update(
        _tq(actor, {"id": lid}), {"$set": body}, return_document=True
    )
    if not d:
        raise HTTPException(404, "Lead not found")
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="lead.updated", object_type="lead", object_id=lid,
        metadata={"fields": list(body.keys())},
    )
    return LeadOut(**_clean(d))


# ---------------------------------------------------------------------------
# Routes: Event KPI records (verified metrics layer)
# ---------------------------------------------------------------------------
import re

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_kpi_row(row: dict) -> Optional[str]:
    """Return an error string or None. Applies structural + range rules."""
    if not row.get("metric_date"):
        return "metric_date is required"
    if not _DATE_RE.match(str(row.get("metric_date", ""))):
        return "metric_date must be YYYY-MM-DD"
    if row.get("channel") not in KPI_CHANNELS:
        return f"unknown channel: {row.get('channel')!r} (allowed: {', '.join(KPI_CHANNELS)})"
    for f in KPI_NUMERIC_FIELDS:
        v = row.get(f, 0)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return f"{f} must be numeric"
        if fv < 0:
            return f"{f} must be non-negative"
    # All-zero rule: only permitted if source_type=manual AND notes explain why.
    all_zero = all(float(row.get(f, 0) or 0) == 0 for f in KPI_NUMERIC_FIELDS)
    if all_zero:
        if row.get("source_type") not in (None, "manual"):
            return "all-zero rows are only allowed for source_type='manual'"
        if not (row.get("notes") or "").strip():
            return "all-zero row requires a non-empty 'notes' explanation"
    return None


async def _resolve_event_and_campaign(
    tenant_id: str, event_id: str, campaign_id: Optional[str]
) -> None:
    ev = await db.events.find_one({"tenant_id": tenant_id, "id": event_id}, {"_id": 0})
    if not ev:
        raise HTTPException(404, "Event not found in your workspace")
    if campaign_id:
        c = await db.campaigns.find_one(
            {"tenant_id": tenant_id, "id": campaign_id, "event_id": event_id}, {"_id": 0}
        )
        if not c:
            raise HTTPException(400, "campaign_id does not belong to this event/tenant")


def _kpi_notes_safe(notes: Optional[str]) -> Optional[str]:
    """Trim overly long notes and strip likely-secret substrings for audit metadata."""
    if not notes:
        return notes
    s = str(notes).strip()
    if len(s) > 120:
        s = s[:117] + "..."
    lower = s.lower()
    if any(h in lower for h in _SECRET_KEY_HINTS):
        return "[redacted-notes]"
    return s


@api.get("/events/{event_id}/kpis", response_model=List[KpiRecordOut])
async def list_kpis(
    event_id: str,
    channel: Optional[str] = None,
    source_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: dict = Depends(current_user),
):
    await _resolve_event_and_campaign(user["tenant_id"], event_id, None)
    q: dict = {"tenant_id": user["tenant_id"], "event_id": event_id}
    if channel:
        if channel not in KPI_CHANNELS:
            raise HTTPException(400, "unknown channel filter")
        q["channel"] = channel
    if source_type:
        if source_type not in KPI_SOURCE_TYPES:
            raise HTTPException(400, "unknown source_type filter")
        q["source_type"] = source_type
    if start_date or end_date:
        for s in (start_date, end_date):
            if s and not _DATE_RE.match(s):
                raise HTTPException(400, "start_date/end_date must be YYYY-MM-DD")
        date_q: dict = {}
        if start_date:
            date_q["$gte"] = start_date
        if end_date:
            date_q["$lte"] = end_date
        q["metric_date"] = date_q
    docs = await db.event_kpi_records.find(q, {"_id": 0}).sort("metric_date", -1).to_list(2000)
    return [KpiRecordOut(**d) for d in docs]


@api.post("/events/{event_id}/kpis", response_model=KpiRecordOut)
async def create_kpi(
    event_id: str,
    body: KpiRowInput,
    actor: dict = Depends(require_role("admin", "marketing")),
):
    await _resolve_event_and_campaign(actor["tenant_id"], event_id, body.campaign_id)
    row = body.model_dump()
    row["source_type"] = "manual"
    err = _validate_kpi_row(row)
    if err:
        raise HTTPException(400, err)
    doc = KpiRecordOut(
        **body.model_dump(),
        tenant_id=actor["tenant_id"],
        event_id=event_id,
        source_type="manual",
        source_name="manual entry",
        created_by_user_id=actor["id"],
        updated_at=_now_iso(),
    ).model_dump()
    await db.event_kpi_records.insert_one(doc)
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="event_kpi_created", object_type="event_kpi",
        object_id=doc["id"],
        metadata={
            "event_id": event_id, "channel": doc["channel"],
            "metric_date": doc["metric_date"],
            "notes_preview": _kpi_notes_safe(doc.get("notes")),
        },
    )
    return KpiRecordOut(**_clean(doc))


@api.patch("/events/{event_id}/kpis/{kpi_id}", response_model=KpiRecordOut)
async def update_kpi(
    event_id: str, kpi_id: str, body: KpiUpdate,
    actor: dict = Depends(require_role("admin", "marketing")),
):
    update = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not update:
        raise HTTPException(400, "Nothing to update")
    # Fetch current row to validate merged state (numeric non-negativity, channel).
    existing = await db.event_kpi_records.find_one(
        {"tenant_id": actor["tenant_id"], "event_id": event_id, "id": kpi_id}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(404, "KPI record not found")
    merged = {**existing, **update}
    if update.get("campaign_id") is not None:
        await _resolve_event_and_campaign(actor["tenant_id"], event_id, update["campaign_id"])
    err = _validate_kpi_row(merged)
    if err:
        raise HTTPException(400, err)
    update["updated_at"] = _now_iso()
    d = await db.event_kpi_records.find_one_and_update(
        {"tenant_id": actor["tenant_id"], "event_id": event_id, "id": kpi_id},
        {"$set": update}, return_document=True,
    )
    if not d:
        raise HTTPException(404, "KPI record not found")
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="event_kpi_updated", object_type="event_kpi", object_id=kpi_id,
        metadata={"event_id": event_id, "fields": list(update.keys())},
    )
    return KpiRecordOut(**_clean(d))


@api.delete("/events/{event_id}/kpis/{kpi_id}")
async def delete_kpi(
    event_id: str, kpi_id: str,
    actor: dict = Depends(require_role("admin")),
):
    r = await db.event_kpi_records.delete_one(
        {"tenant_id": actor["tenant_id"], "event_id": event_id, "id": kpi_id}
    )
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="event_kpi_deleted", object_type="event_kpi", object_id=kpi_id,
        result="success" if r.deleted_count else "failure",
        metadata={"event_id": event_id},
    )
    return {"deleted": r.deleted_count}


def _preview_totals(rows: List[dict]) -> dict:
    tot: dict = {f: 0 for f in KPI_NUMERIC_FIELDS}
    for r in rows:
        for f in KPI_NUMERIC_FIELDS:
            tot[f] += float(r.get(f, 0) or 0)
    # Coerce int fields back to int for readability
    for f in KPI_INT_FIELDS:
        tot[f] = int(tot[f])
    return tot


@api.post("/events/{event_id}/kpis/csv/dry-run")
async def csv_dry_run(
    event_id: str, body: CsvRowsIn,
    actor: dict = Depends(require_role("admin", "marketing")),
):
    await _resolve_event_and_campaign(actor["tenant_id"], event_id, None)
    row_errors: list = []
    valid_rows: list = []
    for i, r in enumerate(body.rows):
        d = r.model_dump()
        d["source_type"] = "csv_import"
        err = _validate_kpi_row(d)
        if err:
            row_errors.append({"row_index": i, "error": err})
        else:
            # Verify campaign belongs to event when supplied
            if d.get("campaign_id"):
                try:
                    await _resolve_event_and_campaign(
                        actor["tenant_id"], event_id, d["campaign_id"]
                    )
                except HTTPException as e:
                    row_errors.append({"row_index": i, "error": e.detail})
                    continue
            valid_rows.append(d)
    preview = _preview_totals(valid_rows)
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="event_kpi_csv_dry_run", object_type="event_kpi",
        result="success" if not row_errors else "failure",
        metadata={
            "event_id": event_id, "input_count": len(body.rows),
            "valid_count": len(valid_rows), "invalid_count": len(row_errors),
        },
    )
    return {
        "valid_count": len(valid_rows),
        "invalid_count": len(row_errors),
        "row_errors": row_errors,
        "preview_totals": preview,
    }


@api.post("/events/{event_id}/kpis/csv/import")
async def csv_import(
    event_id: str, body: CsvRowsIn,
    actor: dict = Depends(require_role("admin", "marketing")),
):
    await _resolve_event_and_campaign(actor["tenant_id"], event_id, None)
    row_errors: list = []
    prepared: list = []
    for i, r in enumerate(body.rows):
        d = r.model_dump()
        d["source_type"] = "csv_import"
        err = _validate_kpi_row(d)
        if err:
            row_errors.append({"row_index": i, "error": err})
            continue
        if d.get("campaign_id"):
            c = await db.campaigns.find_one(
                {"tenant_id": actor["tenant_id"], "id": d["campaign_id"], "event_id": event_id},
                {"_id": 0},
            )
            if not c:
                row_errors.append({"row_index": i, "error": "campaign_id does not belong to this event/tenant"})
                continue
        prepared.append(d)

    if row_errors:
        await audit(
            tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
            action="event_kpi_csv_imported", object_type="event_kpi",
            result="failure",
            metadata={
                "event_id": event_id, "input_count": len(body.rows),
                "invalid_count": len(row_errors),
            },
        )
        raise HTTPException(
            400,
            {"message": "One or more rows failed validation; nothing imported.",
             "row_errors": row_errors},
        )

    now = _now_iso()
    docs = []
    for d in prepared:
        d.pop("source_type", None)
        rec = KpiRecordOut(
            **d,
            tenant_id=actor["tenant_id"],
            event_id=event_id,
            source_type="csv_import",
            source_name="csv upload",
            created_by_user_id=actor["id"],
            updated_at=now,
        ).model_dump()
        docs.append(rec)
    if docs:
        await db.event_kpi_records.insert_many(docs)
    totals = _preview_totals(prepared)
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="event_kpi_csv_imported", object_type="event_kpi",
        result="success",
        metadata={
            "event_id": event_id, "inserted_count": len(docs),
        },
    )
    return {"inserted_count": len(docs), "totals": totals}


# ---------------------------------------------------------------------------
# Routes: GoHighLevel (source of truth for leads)
# ---------------------------------------------------------------------------
def _ghl_read_enabled() -> bool:
    return os.environ.get("GHL_READ_SYNC_ENABLED", "false").lower() == "true"


async def get_ghl_config_for_tenant(tenant_id: str) -> Optional[dict]:
    """Return the tenant's GHL integration doc with the decrypted key or None."""
    doc = await db.integrations.find_one(
        {"tenant_id": tenant_id, "kind": "gohighlevel"}, {"_id": 0}
    )
    if not doc:
        return None
    api_key = decrypt(doc["api_key_enc"]) if doc.get("api_key_enc") else None
    config = dict(doc.get("config") or {})
    return {
        "integration_id": doc["id"],
        "api_key": api_key,
        "config": config,
        "validated": doc.get("validated", False),
        "live_sync_enabled": doc.get("live_sync_enabled", False),
    }


def _validate_mapping_body(body: dict) -> Optional[str]:
    mt = body.get("mapping_type")
    tt = body.get("target_type")
    tv = body.get("target_value")
    direction = body.get("direction", "inbound")
    if mt not in GHL_MAPPING_TYPES:
        return f"mapping_type must be one of {GHL_MAPPING_TYPES}"
    if tt not in GHL_MAPPING_TARGET_TYPES:
        return f"target_type must be one of {GHL_MAPPING_TARGET_TYPES}"
    if direction not in GHL_MAPPING_DIRECTIONS:
        return f"direction must be one of {GHL_MAPPING_DIRECTIONS}"
    if tt == "lead_status" and tv not in LEAD_STATUS_VALUES:
        return f"target_value must be one of {LEAD_STATUS_VALUES}"
    if tt == "lead_temperature" and tv not in LEAD_TEMPERATURE_VALUES:
        return f"target_value must be one of {LEAD_TEMPERATURE_VALUES}"
    if mt == "pipeline_stage" and not (body.get("ghl_id") or body.get("ghl_name")):
        return "pipeline_stage mapping requires ghl_id or ghl_name"
    if mt == "tag" and not body.get("ghl_name"):
        return "tag mapping requires ghl_name"
    return None


@api.get("/ghl/mappings", response_model=List[GhlMappingOut])
async def list_ghl_mappings(user: dict = Depends(current_user)):
    docs = await db.ghl_mappings.find(_tq(user), {"_id": 0}).to_list(500)
    return [GhlMappingOut(**d) for d in docs]


@api.post("/ghl/mappings", response_model=GhlMappingOut)
async def create_ghl_mapping(
    body: GhlMappingIn, actor: dict = Depends(require_role("admin", "marketing")),
):
    err = _validate_mapping_body(body.model_dump())
    if err:
        raise HTTPException(400, err)
    doc = GhlMappingOut(
        **body.model_dump(),
        tenant_id=actor["tenant_id"],
        updated_at=_now_iso(),
    ).model_dump()
    await db.ghl_mappings.insert_one(doc)
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="ghl_mapping_created", object_type="ghl_mapping",
        object_id=doc["id"],
        metadata={
            "mapping_type": doc["mapping_type"], "target_type": doc["target_type"],
            "target_value": doc["target_value"],
        },
    )
    return GhlMappingOut(**_clean(doc))


@api.patch("/ghl/mappings/{mid}", response_model=GhlMappingOut)
async def update_ghl_mapping(
    mid: str, body: GhlMappingUpdate,
    actor: dict = Depends(require_role("admin", "marketing")),
):
    update = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not update:
        raise HTTPException(400, "Nothing to update")
    existing = await db.ghl_mappings.find_one(_tq(actor, {"id": mid}), {"_id": 0})
    if not existing:
        raise HTTPException(404, "Mapping not found")
    merged = {**existing, **update}
    err = _validate_mapping_body(merged)
    if err:
        raise HTTPException(400, err)
    update["updated_at"] = _now_iso()
    d = await db.ghl_mappings.find_one_and_update(
        _tq(actor, {"id": mid}), {"$set": update}, return_document=True,
    )
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="ghl_mapping_updated", object_type="ghl_mapping",
        object_id=mid, metadata={"fields": list(update.keys())},
    )
    return GhlMappingOut(**_clean(d))


@api.delete("/ghl/mappings/{mid}")
async def delete_ghl_mapping(
    mid: str, actor: dict = Depends(require_role("admin", "marketing")),
):
    r = await db.ghl_mappings.delete_one(_tq(actor, {"id": mid}))
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="ghl_mapping_deleted", object_type="ghl_mapping",
        object_id=mid, result="success" if r.deleted_count else "failure",
    )
    if r.deleted_count == 0:
        raise HTTPException(404, "Mapping not found")
    return {"deleted": r.deleted_count}


async def _compute_ghl_status(tenant_id: str) -> dict:
    cfg = await get_ghl_config_for_tenant(tenant_id)
    credential_status = "configured" if (cfg and cfg.get("api_key")) else "missing"
    location_id_status = (
        "configured"
        if (cfg and (cfg.get("config") or {}).get("location_id"))
        else "missing"
    )
    mappings = await db.ghl_mappings.find({"tenant_id": tenant_id}, {"_id": 0}).to_list(500)
    types_present = {m.get("mapping_type") for m in mappings}
    if not mappings:
        mapping_status = "missing"
    elif types_present >= {"tag", "pipeline_stage"}:
        mapping_status = "ready"
    else:
        mapping_status = "partial"

    required: list = []
    if credential_status == "missing":
        required.append("Provide GoHighLevel API key on the Integrations page.")
    if location_id_status == "missing":
        required.append("Provide GHL Location ID in the integration config.")
    if mapping_status != "ready":
        required.append("Add at least one tag mapping AND one pipeline stage mapping.")
    if not _ghl_read_enabled():
        required.append("Enable GHL_READ_SYNC_ENABLED=true in backend environment to allow API calls.")

    return {
        "credential_status": credential_status,
        "location_id_status": location_id_status,
        "mapping_status": mapping_status,
        "read_sync_enabled": _ghl_read_enabled(),
        "write_back_enabled": False,  # Not implemented in this patch
        "source_of_truth": "gohighlevel",
        "local_role": "operating_reporting_layer",
        "required_actions": required,
        "mappings_count": len(mappings),
    }


@api.get("/ghl/status")
async def ghl_status(user: dict = Depends(current_user)):
    return await _compute_ghl_status(user["tenant_id"])


def _sync_precheck(cfg: Optional[dict]) -> Optional[dict]:
    """Return a blocked-response dict if not ready, else None."""
    if not cfg or not cfg.get("api_key"):
        return {
            "status": "blocked",
            "reason": "GHL credential missing",
            "required_action": "Save a GoHighLevel API key in Integrations.",
            "raw_payload_returned": False,
        }
    if not (cfg.get("config") or {}).get("location_id"):
        return {
            "status": "blocked",
            "reason": "GHL location_id missing",
            "required_action": "Set location_id in the GHL integration config.",
            "raw_payload_returned": False,
        }
    if not _ghl_read_enabled():
        return {
            "status": "blocked",
            "reason": "GHL read sync is disabled",
            "required_action": "Set GHL_READ_SYNC_ENABLED=true in backend environment.",
            "raw_payload_returned": False,
        }
    return None


@api.post("/ghl/pull-preview")
async def ghl_pull_preview(
    body: GhlPullIn, actor: dict = Depends(require_role("admin", "marketing", "sales")),
):
    if body.event_id:
        ev = await db.events.find_one(_tq(actor, {"id": body.event_id}), {"_id": 0})
        if not ev:
            raise HTTPException(404, "Event not found in your workspace")

    cfg = await get_ghl_config_for_tenant(actor["tenant_id"])
    blocked = _sync_precheck(cfg)
    if blocked:
        await audit(
            tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
            action="ghl_pull_preview", object_type="ghl",
            result="blocked", metadata={"reason": blocked["reason"]},
        )
        return blocked

    try:
        raw_contacts = await ghl_client.fetch_contacts(cfg["config"], cfg["api_key"], body.limit)
        raw_opps = await ghl_client.fetch_opportunities(cfg["config"], cfg["api_key"], body.limit)
    except Exception as e:
        log.exception("GHL fetch failed")
        await audit(
            tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
            action="ghl_pull_preview", object_type="ghl",
            result="failure", metadata={"error": str(e)[:200]},
        )
        raise HTTPException(502, f"GHL fetch failed: {e}")

    normalized_contacts = [ghl_client.normalize_ghl_contact(c) for c in raw_contacts]
    normalized_opps = [ghl_client.normalize_ghl_opportunity(o) for o in raw_opps]
    mappings = await db.ghl_mappings.find(
        {"tenant_id": actor["tenant_id"]}, {"_id": 0}
    ).to_list(500)
    preview = [
        ghl_client.map_ghl_lead(c, normalized_opps, mappings)
        for c in normalized_contacts if c.get("ghl_contact_id")
    ]

    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="ghl_pull_preview", object_type="ghl",
        metadata={
            "contacts_count": len(normalized_contacts),
            "opportunities_count": len(normalized_opps),
            "event_id": body.event_id,
        },
    )
    return {
        "status": "ok",
        "count": len(preview),
        "preview": preview,
        "source_of_truth": "gohighlevel",
        "raw_payload_returned": False,
    }


@api.post("/ghl/pull-sync")
async def ghl_pull_sync(
    body: GhlPullIn, actor: dict = Depends(require_role("admin", "marketing")),
):
    if body.event_id:
        ev = await db.events.find_one(_tq(actor, {"id": body.event_id}), {"_id": 0})
        if not ev:
            raise HTTPException(404, "Event not found in your workspace")

    cfg = await get_ghl_config_for_tenant(actor["tenant_id"])
    blocked = _sync_precheck(cfg)
    if blocked:
        await audit(
            tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
            action="ghl_pull_sync", object_type="ghl",
            result="blocked", metadata={"reason": blocked["reason"]},
        )
        return blocked

    try:
        raw_contacts = await ghl_client.fetch_contacts(cfg["config"], cfg["api_key"], body.limit)
        raw_opps = await ghl_client.fetch_opportunities(cfg["config"], cfg["api_key"], body.limit)
    except Exception as e:
        log.exception("GHL fetch failed")
        await audit(
            tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
            action="ghl_pull_sync", object_type="ghl",
            result="failure", metadata={"error": str(e)[:200]},
        )
        raise HTTPException(502, f"GHL fetch failed: {e}")

    normalized_contacts = [ghl_client.normalize_ghl_contact(c) for c in raw_contacts]
    normalized_opps = [ghl_client.normalize_ghl_opportunity(o) for o in raw_opps]
    mappings = await db.ghl_mappings.find(
        {"tenant_id": actor["tenant_id"]}, {"_id": 0}
    ).to_list(500)

    inserted_count = 0
    updated_count = 0
    skipped_count = 0
    mapped_count = 0
    warnings: list = []
    now = _now_iso()

    for c in normalized_contacts:
        if not c.get("ghl_contact_id"):
            skipped_count += 1
            continue
        mapped = ghl_client.map_ghl_lead(c, normalized_opps, mappings)
        # Determine target: existing GHL-linked lead first, then email/phone within tenant.
        existing = await db.leads.find_one(
            {
                "tenant_id": actor["tenant_id"],
                "external_source_provider": "gohighlevel",
                "external_source_id": c["ghl_contact_id"],
            },
            {"_id": 0},
        )
        if not existing:
            fallback: dict = {"tenant_id": actor["tenant_id"]}
            if c.get("email"):
                fallback["email"] = c["email"]
                existing = await db.leads.find_one(fallback, {"_id": 0})
            if not existing and c.get("phone"):
                fallback = {"tenant_id": actor["tenant_id"], "phone": c["phone"]}
                existing = await db.leads.find_one(fallback, {"_id": 0})

        stage = mapped.get("mapped_lead_status") or (existing or {}).get("stage") or "new"
        temperature = mapped.get("mapped_lead_temperature") or (existing or {}).get("lead_temperature")
        purchase_amount = mapped.get("monetary_value") if stage == "purchased" else None
        common = {
            "tenant_id": actor["tenant_id"],
            "event_id": body.event_id or (existing or {}).get("event_id"),
            "name": c.get("name") or (existing or {}).get("name") or "Unknown",
            "email": c.get("email") or (existing or {}).get("email"),
            "phone": c.get("phone") or (existing or {}).get("phone"),
            "source": "ghl",
            "stage": stage,
            "lead_temperature": temperature,
            "notes": (existing or {}).get("notes"),
            "tag": (existing or {}).get("tag"),
            "source_of_truth": "gohighlevel",
            "external_source_provider": "gohighlevel",
            "external_source_id": c["ghl_contact_id"],
            "external_opportunity_id": mapped.get("ghl_opportunity_id"),
            "external_tags": c.get("tags") or [],
            "external_stage_id": mapped.get("stage_id"),
            "external_last_synced_at": now,
            "purchase_amount": purchase_amount,
        }

        if existing:
            await db.leads.update_one(
                {"id": existing["id"], "tenant_id": actor["tenant_id"]},
                {"$set": common},
            )
            updated_count += 1
        else:
            new_doc = LeadOut(**common).model_dump()
            await db.leads.insert_one(new_doc)
            inserted_count += 1

        if mapped.get("mapped_lead_status") or mapped.get("mapped_lead_temperature"):
            mapped_count += 1
        else:
            warnings.append({
                "ghl_contact_id": c["ghl_contact_id"],
                "reason": "no matching tag/stage mapping found",
            })

    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="ghl_pull_sync", object_type="ghl",
        metadata={
            "inserted": inserted_count, "updated": updated_count,
            "skipped": skipped_count, "mapped": mapped_count,
            "event_id": body.event_id,
        },
    )
    return {
        "status": "ok",
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "skipped_count": skipped_count,
        "mapped_count": mapped_count,
        "warnings": warnings[:50],
        "raw_payload_returned": False,
    }


@api.post("/ghl/write-back-preview")
async def ghl_write_back_preview(
    body: GhlWriteBackIn, actor: dict = Depends(require_role("admin", "marketing")),
):
    lead = await db.leads.find_one(_tq(actor, {"id": body.lead_id}), {"_id": 0})
    if not lead:
        raise HTTPException(404, "Lead not found")

    cfg = await get_ghl_config_for_tenant(actor["tenant_id"])
    if not cfg or not cfg.get("api_key"):
        await audit(
            tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
            action="ghl_write_back_preview", object_type="lead",
            object_id=body.lead_id, result="blocked",
            metadata={"reason": "GHL credential missing"},
        )
        return {
            "status": "blocked",
            "reason": "GHL credential missing",
            "required_action": "Save a GoHighLevel API key in Integrations.",
            "raw_payload_returned": False,
        }

    if not lead.get("external_source_id") or lead.get("external_source_provider") != "gohighlevel":
        await audit(
            tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
            action="ghl_write_back_preview", object_type="lead",
            object_id=body.lead_id, result="blocked",
            metadata={"reason": "Lead is not GHL-linked"},
        )
        return {
            "status": "blocked",
            "reason": "Lead is not GHL-linked",
            "required_action": "Import lead from GHL first, or link an existing GHL contact.",
            "raw_payload_returned": False,
        }

    mappings = await db.ghl_mappings.find(
        {
            "tenant_id": actor["tenant_id"],
            "direction": {"$in": ["outbound", "bidirectional"]},
        },
        {"_id": 0},
    ).to_list(500)
    payload = ghl_client.build_write_back_payload(lead, mappings)
    await audit(
        tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
        action="ghl_write_back_preview", object_type="lead",
        object_id=body.lead_id,
        metadata={
            "tags_to_apply_count": len(payload.get("tags", [])),
            "custom_fields_count": len(payload.get("custom_fields", {})),
        },
    )
    return {
        "status": "preview",
        "would_send": payload,
        "note": "This is a preview only. No call has been made to GoHighLevel.",
        "raw_payload_returned": False,
    }


# ---------------------------------------------------------------------------
# Planner (Execution Plan): 7 collections + summary
# ---------------------------------------------------------------------------
CONTENT_STATUS = ("planned", "in_progress", "pending_review", "approved", "blocked", "done")
CONTENT_ASSET_TYPES = ("video", "image", "carousel", "reel", "story", "landing_page", "email_copy", "whatsapp_copy", "other")
CONTENT_PLATFORMS = ("instagram", "meta", "youtube", "whatsapp", "email", "landing_page", "other")
PLAN_APPROVAL = ("draft", "pending_review", "approved", "changes_requested")
EMAIL_STATUS = ("planned", "active", "completed", "blocked")
EMAIL_GOALS = ("awareness", "nurture", "upsell", "reminder", "last_chance", "post_event")
WHATSAPP_GOALS = ("reminder", "nurture", "sales_follow_up", "urgency", "post_event")
WHATSAPP_CONTENT_TYPES = ("text", "image", "video", "link", "mixed")
UPSELL_CHANNELS = ("email", "whatsapp", "sales_call", "ghl_workflow", "mixed")
BUDGET_CHANNELS = ("meta", "instagram", "youtube", "whatsapp", "email", "organic", "dark_ad", "referral", "other")
DARK_AD_STATUS = ("planned", "active", "paused", "completed", "blocked")
DARK_AD_PLATFORMS = ("meta", "instagram", "youtube", "other")
DARK_AD_FORMATS = ("video", "image", "carousel", "reel", "story", "other")
DARK_AD_OBJECTIVES = ("leads", "conversions", "awareness", "retargeting")
SALES_TASK_STATUS = ("open", "in_progress", "done", "blocked")
SALES_TASK_TYPES = ("call", "whatsapp_reply", "meeting_follow_up", "no_show_follow_up", "payment_follow_up", "lead_review", "other")


class ContentReqIn(BaseModel):
    title: str
    asset_type: str
    platform: str
    description: Optional[str] = None
    due_date: Optional[str] = None
    owner_role: Optional[str] = None
    status: str = "planned"
    notes: Optional[str] = None


class EmailPlanIn(BaseModel):
    sequence_name: str
    audience_segment: Optional[str] = None
    email_count: int = 1
    planned_send_dates: List[str] = []
    subject_draft: Optional[str] = None
    body_draft: Optional[str] = None
    goal: str
    approval_status: str = "draft"
    status: str = "planned"


class WhatsappPlanIn(BaseModel):
    audience_segment: Optional[str] = None
    frequency: Optional[str] = None
    content_type: str = "text"
    message_draft: Optional[str] = None
    goal: str
    approval_status: str = "draft"
    status: str = "planned"


class UpsellPlanIn(BaseModel):
    target_segment: str
    offer: str
    fomo_angle: Optional[str] = None
    planned_channel: str
    expected_outcome: Optional[str] = None
    approval_status: str = "draft"
    status: str = "planned"


class BudgetPlanIn(BaseModel):
    channel: str
    planned_budget: float = 0.0
    expected_leads: int = 0
    expected_purchases: int = 0
    expected_revenue: float = 0.0
    notes: Optional[str] = None


class DarkAdPlanIn(BaseModel):
    campaign_name: str
    audience_definition: Optional[str] = None
    platform: str
    creative_format: str
    objective: str
    planned_budget: float = 0.0
    status: str = "planned"
    notes: Optional[str] = None


class SalesTaskIn(BaseModel):
    title: str
    task_type: str
    owner_role: Optional[str] = None
    related_lead_id: Optional[str] = None
    due_date: Optional[str] = None
    status: str = "open"
    notes: Optional[str] = None


PLANNER_RESOURCES = [
    {"path": "content-requirements", "coll": "event_content_requirements",
     "obj": "content_requirement", "model": ContentReqIn,
     "write_roles": ("admin", "marketing", "social"),
     "enums": {"asset_type": CONTENT_ASSET_TYPES, "platform": CONTENT_PLATFORMS, "status": CONTENT_STATUS}},
    {"path": "email-plans", "coll": "event_email_plans",
     "obj": "email_plan", "model": EmailPlanIn,
     "write_roles": ("admin", "marketing"),
     "enums": {"goal": EMAIL_GOALS, "approval_status": PLAN_APPROVAL, "status": EMAIL_STATUS}},
    {"path": "whatsapp-plans", "coll": "event_whatsapp_plans",
     "obj": "whatsapp_plan", "model": WhatsappPlanIn,
     "write_roles": ("admin", "marketing", "sales"),
     "enums": {"goal": WHATSAPP_GOALS, "content_type": WHATSAPP_CONTENT_TYPES,
               "approval_status": PLAN_APPROVAL, "status": EMAIL_STATUS}},
    {"path": "upsell-plans", "coll": "event_upsell_plans",
     "obj": "upsell_plan", "model": UpsellPlanIn,
     "write_roles": ("admin", "marketing", "sales"),
     "enums": {"planned_channel": UPSELL_CHANNELS, "approval_status": PLAN_APPROVAL, "status": EMAIL_STATUS}},
    {"path": "budget-plans", "coll": "event_budget_plans",
     "obj": "budget_plan", "model": BudgetPlanIn,
     "write_roles": ("admin", "marketing"),
     "enums": {"channel": BUDGET_CHANNELS}},
    {"path": "dark-ad-plans", "coll": "event_dark_ad_plans",
     "obj": "dark_ad_plan", "model": DarkAdPlanIn,
     "write_roles": ("admin", "marketing", "social"),
     "enums": {"platform": DARK_AD_PLATFORMS, "creative_format": DARK_AD_FORMATS,
               "objective": DARK_AD_OBJECTIVES, "status": DARK_AD_STATUS}},
    {"path": "sales-tasks", "coll": "event_sales_tasks",
     "obj": "sales_task", "model": SalesTaskIn,
     "write_roles": ("admin", "marketing", "sales"),
     "enums": {"task_type": SALES_TASK_TYPES, "status": SALES_TASK_STATUS}},
]


def _register_planner(spec: dict) -> None:
    path = spec["path"]
    coll = spec["coll"]
    obj = spec["obj"]
    Model = spec["model"]
    write_roles = spec["write_roles"]
    enums = spec.get("enums", {})

    def _check_enums(payload: dict) -> Optional[str]:
        for field, allowed in enums.items():
            v = payload.get(field)
            if v is not None and v not in allowed:
                return f"{field} must be one of {allowed}"
        return None

    @api.get(f"/events/{{event_id}}/{path}", name=f"list_{coll}")
    async def _list(event_id: str, user: dict = Depends(current_user)):
        await _resolve_event_and_campaign(user["tenant_id"], event_id, None)
        docs = await db[coll].find(
            _tq(user, {"event_id": event_id}), {"_id": 0}
        ).sort("created_at", -1).to_list(1000)
        return docs

    @api.post(f"/events/{{event_id}}/{path}", name=f"create_{coll}")
    async def _create(
        event_id: str,
        body: dict = Body(...),
        actor: dict = Depends(require_role(*write_roles)),
    ):
        try:
            parsed = Model(**body)
        except Exception as e:
            raise HTTPException(422, str(e))
        await _resolve_event_and_campaign(actor["tenant_id"], event_id, None)
        payload = parsed.model_dump()
        err = _check_enums(payload)
        if err:
            raise HTTPException(400, err)
        doc = {
            "id": str(uuid.uuid4()),
            "tenant_id": actor["tenant_id"],
            "event_id": event_id,
            **payload,
            "created_by": actor["id"],
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        await db[coll].insert_one(doc)
        await audit(
            tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
            action=f"{obj}_created", object_type=obj, object_id=doc["id"],
            metadata={"event_id": event_id},
        )
        doc.pop("_id", None)
        return doc

    @api.patch(f"/events/{{event_id}}/{path}/{{item_id}}", name=f"update_{coll}")
    async def _update(
        event_id: str, item_id: str, body: dict,
        actor: dict = Depends(require_role(*write_roles)),
    ):
        for r in ("id", "_id", "created_at", "tenant_id", "event_id", "created_by"):
            body.pop(r, None)
        existing = await db[coll].find_one(
            _tq(actor, {"id": item_id, "event_id": event_id}), {"_id": 0}
        )
        if not existing:
            raise HTTPException(404, f"{obj} not found")
        merged = {**existing, **body}
        err = _check_enums(merged)
        if err:
            raise HTTPException(400, err)
        body["updated_at"] = _now_iso()
        d = await db[coll].find_one_and_update(
            _tq(actor, {"id": item_id, "event_id": event_id}),
            {"$set": body}, return_document=True,
        )
        if not d:
            raise HTTPException(404, f"{obj} not found")
        await audit(
            tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
            action=f"{obj}_updated", object_type=obj, object_id=item_id,
            metadata={"event_id": event_id, "fields": list(body.keys())},
        )
        d.pop("_id", None)
        return d

    @api.delete(f"/events/{{event_id}}/{path}/{{item_id}}", name=f"delete_{coll}")
    async def _delete(
        event_id: str, item_id: str,
        actor: dict = Depends(require_role(*write_roles)),
    ):
        r = await db[coll].delete_one(
            _tq(actor, {"id": item_id, "event_id": event_id})
        )
        await audit(
            tenant_id=actor["tenant_id"], actor_user_id=actor["id"],
            action=f"{obj}_deleted", object_type=obj, object_id=item_id,
            result="success" if r.deleted_count else "failure",
        )
        if r.deleted_count == 0:
            raise HTTPException(404, f"{obj} not found")
        return {"deleted": r.deleted_count}


for _spec in PLANNER_RESOURCES:
    _register_planner(_spec)


async def _planner_summary(tenant_id: str, event_id: str) -> dict:
    q = {"tenant_id": tenant_id, "event_id": event_id}
    contents = await db.event_content_requirements.find(q, {"_id": 0}).to_list(1000)
    emails = await db.event_email_plans.find(q, {"_id": 0}).to_list(1000)
    whatsapps = await db.event_whatsapp_plans.find(q, {"_id": 0}).to_list(1000)
    upsells = await db.event_upsell_plans.find(q, {"_id": 0}).to_list(1000)
    budgets = await db.event_budget_plans.find(q, {"_id": 0}).to_list(1000)
    darks = await db.event_dark_ad_plans.find(q, {"_id": 0}).to_list(1000)
    tasks = await db.event_sales_tasks.find(q, {"_id": 0}).to_list(1000)
    kpi_docs = await db.event_kpi_records.find(q, {"_id": 0}).to_list(5000)

    today = datetime.now(timezone.utc).date().isoformat()

    overdue_content = [
        c for c in contents
        if c.get("due_date") and c["due_date"] < today and c.get("status") != "done"
    ]
    approved_emails = sum(1 for e in emails if e.get("approval_status") == "approved")
    approved_whatsapps = sum(1 for w in whatsapps if w.get("approval_status") == "approved")
    approved_upsells = sum(1 for u in upsells if u.get("approval_status") == "approved")

    planned_by_channel: dict = {}
    for b in budgets:
        ch = b.get("channel", "other")
        planned_by_channel[ch] = planned_by_channel.get(ch, 0.0) + float(b.get("planned_budget", 0) or 0)

    actual_by_channel: dict = {}
    for k in kpi_docs:
        ch = k.get("channel", "other")
        actual_by_channel[ch] = actual_by_channel.get(ch, 0.0) + float(k.get("spend", 0) or 0)

    channels = set(planned_by_channel) | set(actual_by_channel)
    budget_by_channel = []
    for ch in sorted(channels):
        p = planned_by_channel.get(ch, 0.0)
        a = actual_by_channel.get(ch, 0.0)
        budget_by_channel.append({
            "channel": ch, "planned": round(p, 2), "actual": round(a, 2),
            "variance": round(p - a, 2),
        })

    open_tasks = [t for t in tasks if t.get("status") in ("open", "in_progress")]
    overdue_tasks = [
        t for t in open_tasks
        if t.get("due_date") and t["due_date"] < today
    ]

    darks_by_status: dict = {}
    for d in darks:
        s = d.get("status", "planned")
        darks_by_status[s] = darks_by_status.get(s, 0) + 1

    return {
        "counts": {
            "content_requirements": len(contents),
            "overdue_content": len(overdue_content),
            "email_plans": len(emails),
            "approved_email_plans": approved_emails,
            "whatsapp_plans": len(whatsapps),
            "approved_whatsapp_plans": approved_whatsapps,
            "upsell_plans": len(upsells),
            "approved_upsell_plans": approved_upsells,
            "budget_plans": len(budgets),
            "dark_ad_plans": len(darks),
            "sales_tasks": len(tasks),
            "open_sales_tasks": len(open_tasks),
            "overdue_sales_tasks": len(overdue_tasks),
        },
        "budget_by_channel": budget_by_channel,
        "dark_ads_by_status": darks_by_status,
    }


@api.get("/events/{event_id}/planner/summary")
async def planner_summary(event_id: str, user: dict = Depends(current_user)):
    await _resolve_event_and_campaign(user["tenant_id"], event_id, None)
    return await _planner_summary(user["tenant_id"], event_id)


# ---------------------------------------------------------------------------
# Routes: Audit logs
# ---------------------------------------------------------------------------
@api.get("/audit-logs", response_model=List[AuditLogOut])
async def list_audit_logs(
    limit: int = 200,
    user: dict = Depends(require_role("admin")),
):
    docs = await db.audit_logs.find(
        _tq(user), {"_id": 0}
    ).sort("created_at", -1).to_list(max(1, min(limit, 500)))
    return [AuditLogOut(**d) for d in docs]


# ---------------------------------------------------------------------------
# Routes: Dashboards (verified KPI aggregation)
# ---------------------------------------------------------------------------
async def _kpi_aggregate(tenant_id: str, event_id: Optional[str] = None) -> dict:
    """Aggregate verified KPI records. Returns totals + per-channel + per-source + trend."""
    q: dict = {"tenant_id": tenant_id}
    if event_id:
        q["event_id"] = event_id
    docs = await db.event_kpi_records.find(q, {"_id": 0}).to_list(10000)
    totals: dict = {f: 0 for f in KPI_NUMERIC_FIELDS}
    channel_breakdown: dict = {}
    source_breakdown: dict = {}
    by_date: dict = {}
    for d in docs:
        for f in KPI_NUMERIC_FIELDS:
            totals[f] += float(d.get(f, 0) or 0)
        ch = d.get("channel", "other")
        cb = channel_breakdown.setdefault(ch, {"channel": ch, **{f: 0 for f in KPI_NUMERIC_FIELDS}})
        for f in KPI_NUMERIC_FIELDS:
            cb[f] += float(d.get(f, 0) or 0)
        st = d.get("source_type", "manual")
        sb = source_breakdown.setdefault(st, {"source_type": st, "records": 0, "spend": 0.0, "reach": 0, "leads": 0})
        sb["records"] += 1
        sb["spend"] += float(d.get("spend", 0) or 0)
        sb["reach"] += int(d.get("reach", 0) or 0)
        sb["leads"] += int(d.get("leads", 0) or 0)
        date_key = d.get("metric_date") or ""
        tk = by_date.setdefault(date_key, {"date": date_key, "reach": 0, "engagement": 0, "leads": 0, "spend": 0.0, "revenue": 0.0})
        tk["reach"] += int(d.get("reach", 0) or 0)
        tk["engagement"] += int(d.get("interactions", 0) or 0)
        tk["leads"] += int(d.get("leads", 0) or 0)
        tk["spend"] += float(d.get("spend", 0) or 0)
        tk["revenue"] += float(d.get("revenue", 0) or 0)
    for f in KPI_INT_FIELDS:
        totals[f] = int(totals[f])
    return {
        "records_count": len(docs),
        "totals": totals,
        "channel_breakdown": list(channel_breakdown.values()),
        "source_breakdown": list(source_breakdown.values()),
        "trend": sorted(by_date.values(), key=lambda x: x["date"]),
    }


async def _campaign_budget(tenant_id: str, event_id: Optional[str] = None) -> dict:
    q: dict = {"tenant_id": tenant_id}
    if event_id:
        q["event_id"] = event_id
    campaigns = await db.campaigns.find(q, {"_id": 0}).to_list(500)
    return {
        "campaigns_count": len(campaigns),
        "budget_planned": sum(c.get("budget_planned", 0) for c in campaigns),
    }


async def _lead_metrics(tenant_id: str, event_id: Optional[str] = None) -> dict:
    q: dict = {"tenant_id": tenant_id}
    if event_id:
        q["event_id"] = event_id
    leads = await db.leads.find(q, {"_id": 0}).to_list(5000)
    stages = {"new": 0, "form_filled": 0, "booked": 0, "purchased": 0, "no_show": 0}
    by_source = {"gohighlevel": 0, "local": 0}
    by_temperature = {"cold": 0, "warm": 0, "hot": 0, "buyer": 0}
    for lead in leads:
        s = lead.get("stage", "new")
        if s in stages:
            stages[s] += 1
        sot = lead.get("source_of_truth") or "local"
        by_source[sot] = by_source.get(sot, 0) + 1
        temp = lead.get("lead_temperature")
        if temp in by_temperature:
            by_temperature[temp] += 1
    return {
        "total_leads_collection": len(leads),
        **{f"leads_{k}": v for k, v in stages.items()},
        "leads_by_source": by_source,
        "leads_by_temperature": by_temperature,
    }


def _safe_ratio(num: float, denom: float) -> float:
    return round((num / denom) * 100, 2) if denom else 0.0


def _safe_div(num: float, denom: float) -> float:
    return round(num / denom, 2) if denom else 0.0


def _status_block(records_count: int) -> dict:
    if records_count == 0:
        return {
            "metrics_status": "no_verified_metrics",
            "metrics_message": "Connect analytics or import KPI data to populate performance metrics.",
        }
    return {"metrics_status": "verified", "metrics_message": None}


@api.get("/dashboard/global")
async def dashboard_global(user: dict = Depends(current_user)):
    tid = user["tenant_id"]
    events = await db.events.find(_tq(user), {"_id": 0}).to_list(500)
    kpi = await _kpi_aggregate(tid)
    lm = await _lead_metrics(tid)
    b = await _campaign_budget(tid)
    posts_count = await db.posts.count_documents({"tenant_id": tid})
    totals = kpi["totals"]
    spend = totals["spend"]
    revenue = totals["revenue"]
    roi = _safe_ratio(revenue - spend, spend)
    return {
        "events_count": len(events),
        "campaigns_count": b["campaigns_count"],
        "posts_count": posts_count,
        "records_count": kpi["records_count"],
        "budget_planned": b["budget_planned"],
        "budget_actual": spend,
        # Verified KPI totals
        "reach": totals["reach"],
        "impressions": totals["impressions"],
        "interactions": totals["interactions"],
        "engagement": totals["interactions"],  # alias for legacy frontend
        "clicks": totals["clicks"],
        "form_completions": totals["form_completions"],
        "leads": totals["leads"],
        "meetings_booked": totals["meetings_booked"],
        "meetings_attended": totals["meetings_attended"],
        "no_shows": totals["no_shows"],
        "purchases": totals["purchases"],
        "spend": spend,
        "revenue": revenue,
        "roi_percent": roi,
        # Legacy funnel counts from leads collection (unchanged)
        "total_leads": totals["leads"],
        "leads_new": lm["leads_new"],
        "leads_form_filled": lm["leads_form_filled"],
        "leads_booked": lm["leads_booked"],
        "leads_purchased": lm["leads_purchased"],
        "leads_no_show": lm["leads_no_show"],
        "trend": kpi["trend"],
        "channel_breakdown": kpi["channel_breakdown"],
        "source_type_breakdown": kpi["source_breakdown"],
        "leads_by_source": lm["leads_by_source"],
        "leads_by_temperature": lm["leads_by_temperature"],
        "ghl_mirrored_leads_count": lm["leads_by_source"].get("gohighlevel", 0),
        **_status_block(kpi["records_count"]),
    }


@api.get("/dashboard/event/{event_id}")
async def dashboard_event(event_id: str, user: dict = Depends(current_user)):
    tid = user["tenant_id"]
    event = await db.events.find_one(_tq(user, {"id": event_id}), {"_id": 0})
    if not event:
        raise HTTPException(404, "Event not found")
    kpi = await _kpi_aggregate(tid, event_id)
    lm = await _lead_metrics(tid, event_id)
    b = await _campaign_budget(tid, event_id)
    campaigns = await db.campaigns.find(_tq(user, {"event_id": event_id}), {"_id": 0}).to_list(500)
    campaign_ids = [c["id"] for c in campaigns]
    posts_in_event = await db.posts.count_documents(
        {"tenant_id": tid, "campaign_id": {"$in": campaign_ids or [""]}}
    )
    totals = kpi["totals"]
    spend = totals["spend"]
    revenue = totals["revenue"]
    planned = b["budget_planned"]
    roi = _safe_ratio(revenue - spend, spend)
    form_completion_rate = _safe_ratio(totals["form_completions"], totals["clicks"])
    lead_to_purchase_rate = _safe_ratio(totals["purchases"], totals["leads"])
    meeting_show_rate = _safe_ratio(totals["meetings_attended"], totals["meetings_booked"])
    cost_per_lead = _safe_div(spend, totals["leads"])
    cost_per_purchase = _safe_div(spend, totals["purchases"])
    budget_variance = planned - spend
    return {
        "event": event,
        "campaigns_count": len(campaigns),
        "posts_count": posts_in_event,
        "records_count": kpi["records_count"],
        # Budget
        "budget_planned": planned,
        "actual_spend": spend,
        "budget_actual": spend,  # legacy alias
        "budget_variance": budget_variance,
        # KPI totals
        "reach": totals["reach"],
        "impressions": totals["impressions"],
        "interactions": totals["interactions"],
        "engagement": totals["interactions"],
        "clicks": totals["clicks"],
        "form_completions": totals["form_completions"],
        "leads": totals["leads"],
        "meetings_booked": totals["meetings_booked"],
        "meetings_attended": totals["meetings_attended"],
        "no_shows": totals["no_shows"],
        "purchases": totals["purchases"],
        "spend": spend,
        "revenue": revenue,
        "roi_percent": roi,
        # Derived rates
        "form_completion_rate": form_completion_rate,
        "lead_to_purchase_rate": lead_to_purchase_rate,
        "meeting_show_rate": meeting_show_rate,
        "cost_per_lead": cost_per_lead,
        "cost_per_purchase": cost_per_purchase,
        # Legacy funnel from leads collection (unchanged)
        "total_leads": totals["leads"],
        "leads_new": lm["leads_new"],
        "leads_form_filled": lm["leads_form_filled"],
        "leads_booked": lm["leads_booked"],
        "leads_purchased": lm["leads_purchased"],
        "leads_no_show": lm["leads_no_show"],
        # Breakdowns
        "channel_breakdown": kpi["channel_breakdown"],
        "source_type_breakdown": kpi["source_breakdown"],
        # Legacy platform_breakdown shape kept for existing pie chart
        "platform_breakdown": [
            {"platform": ch["channel"], "reach": ch["reach"], "engagement": ch["interactions"], "posts": 0}
            for ch in kpi["channel_breakdown"]
        ],
        "trend": kpi["trend"],
        "leads_by_source": lm["leads_by_source"],
        "leads_by_temperature": lm["leads_by_temperature"],
        "ghl_status": await _compute_ghl_status(tid),
        "planner": await _planner_summary(tid, event_id),
        **_status_block(kpi["records_count"]),
    }


# ---------------------------------------------------------------------------
# Startup: seed default tenant + admin, backfill legacy docs
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def _startup_seed():
    tenant = await db.tenants.find_one({"slug": DEFAULT_TENANT_SLUG})
    if not tenant:
        tenant = {
            "id": str(uuid.uuid4()),
            "name": DEFAULT_TENANT_NAME,
            "slug": DEFAULT_TENANT_SLUG,
            "status": "active",
            "created_at": _now_iso(),
        }
        await db.tenants.insert_one(tenant)
        log.info("Seeded default tenant %s", tenant["id"])
    tenant_id = tenant["id"]

    admin_email = "admin@campaign.ai"
    admin = await db.users.find_one({"email": admin_email})
    if not admin:
        doc = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "email": admin_email,
            "name": "Platform Admin",
            "role": "admin",
            "permissions": ["*"],
            "password_hash": hash_password("Admin@12345"),
            "is_active": True,
            "created_at": _now_iso(),
        }
        await db.users.insert_one(doc)
        log.info("Seeded admin user %s in tenant %s", admin_email, tenant_id)
    elif not admin.get("tenant_id"):
        await db.users.update_one(
            {"id": admin["id"]}, {"$set": {"tenant_id": tenant_id}}
        )
        log.info("Backfilled tenant_id on existing admin %s", admin_email)

    # Backfill legacy data (from pre-tenant MVP) into the default tenant.
    legacy_collections = (
        "events", "campaigns", "posts", "leads",
        "llm_keys", "social_accounts", "integrations",
    )
    for coll in legacy_collections:
        try:
            res = await db[coll].update_many(
                {"tenant_id": {"$exists": False}}, {"$set": {"tenant_id": tenant_id}}
            )
            if res.modified_count:
                log.info("Backfilled tenant_id on %d %s docs", res.modified_count, coll)
        except Exception:
            log.exception("Backfill failed for %s", coll)


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=CORS_ORIGINS,  # explicit list; no wildcard fallback
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def _shutdown():
    client.close()
