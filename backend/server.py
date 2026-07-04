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

from fastapi import FastAPI, APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr, ConfigDict
import jwt as pyjwt
import bcrypt

from crypto_utils import encrypt, decrypt, mask
import llm_service


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
ROLES = ("admin", "marketing", "sales", "viewer")
PERMISSIONS_BY_ROLE = {
    "admin": ["*"],
    "marketing": ["events.read", "events.write", "campaigns.write", "posts.write", "ai.generate", "dashboard.read"],
    "sales": ["events.read", "leads.write", "dashboard.read"],
    "viewer": ["events.read", "dashboard.read"],
}
VALID_INTEGRATION_KINDS = ("gohighlevel", "zapier", "webhook")
METRIC_SOURCES = ("none", "manual", "imported", "connector")


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


class LeadOut(BaseDoc):
    event_id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    source: str
    stage: str
    tag: Optional[str] = None
    notes: Optional[str] = None


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
# Routes: Dashboards (honest metrics)
# ---------------------------------------------------------------------------
async def _campaign_metrics(tenant_id: str, event_id: Optional[str] = None) -> dict:
    q: dict = {"tenant_id": tenant_id}
    if event_id:
        q["event_id"] = event_id
    campaigns = await db.campaigns.find(q, {"_id": 0}).to_list(500)
    campaign_ids = [c["id"] for c in campaigns]
    posts_q: dict = {"tenant_id": tenant_id}
    if campaign_ids:
        posts_q["campaign_id"] = {"$in": campaign_ids}
    else:
        posts_q["campaign_id"] = {"$in": []}
    posts = await db.posts.find(posts_q, {"_id": 0}).to_list(2000)
    verified = [p for p in posts if p.get("metric_source") and p["metric_source"] != "none"]
    return {
        "reach": sum(p.get("reach", 0) for p in verified),
        "impressions": sum(p.get("impressions", 0) for p in verified),
        "engagement": sum(p.get("engagement", 0) for p in verified),
        "clicks": sum(p.get("clicks", 0) for p in verified),
        "budget_planned": sum(c.get("budget_planned", 0) for c in campaigns),
        "budget_actual": sum(c.get("budget_actual", 0) for c in campaigns),
        "posts_count": len(posts),
        "verified_posts_count": len(verified),
        "campaigns_count": len(campaigns),
    }


async def _lead_metrics(tenant_id: str, event_id: Optional[str] = None) -> dict:
    q: dict = {"tenant_id": tenant_id}
    if event_id:
        q["event_id"] = event_id
    leads = await db.leads.find(q, {"_id": 0}).to_list(5000)
    stages = {"new": 0, "form_filled": 0, "booked": 0, "purchased": 0, "no_show": 0}
    for lead in leads:
        s = lead.get("stage", "new")
        if s in stages:
            stages[s] += 1
    return {"total_leads": len(leads), **{f"leads_{k}": v for k, v in stages.items()}}


def _metrics_status_block(c_metrics: dict) -> dict:
    if c_metrics["verified_posts_count"] == 0:
        return {
            "metrics_status": "no_verified_metrics",
            "metrics_message": "Connect analytics or import KPI data to populate performance metrics.",
        }
    return {"metrics_status": "verified", "metrics_message": None}


@api.get("/dashboard/global")
async def dashboard_global(user: dict = Depends(current_user)):
    tid = user["tenant_id"]
    events = await db.events.find(_tq(user), {"_id": 0}).to_list(500)
    c = await _campaign_metrics(tid)
    lm = await _lead_metrics(tid)
    status_block = _metrics_status_block(c)
    # Honest trend: only distribute verified data; otherwise flat zeros.
    trend: list = []
    today = datetime.now(timezone.utc).date()
    per_day_reach = (c["reach"] / 14) if c["verified_posts_count"] and c["reach"] else 0
    per_day_engagement = (c["engagement"] / 14) if c["verified_posts_count"] and c["engagement"] else 0
    for i in range(13, -1, -1):
        day = today - timedelta(days=i)
        trend.append({
            "date": day.isoformat(),
            "reach": int(per_day_reach),
            "engagement": int(per_day_engagement),
            "leads": 0,
        })
    return {"events_count": len(events), **c, **lm, "trend": trend, **status_block}


@api.get("/dashboard/event/{event_id}")
async def dashboard_event(event_id: str, user: dict = Depends(current_user)):
    tid = user["tenant_id"]
    event = await db.events.find_one(_tq(user, {"id": event_id}), {"_id": 0})
    if not event:
        raise HTTPException(404, "Event not found")
    c = await _campaign_metrics(tid, event_id)
    lm = await _lead_metrics(tid, event_id)
    status_block = _metrics_status_block(c)

    price = event.get("ticket_price") or 0
    revenue = price * lm["leads_purchased"]
    roi = ((revenue - c["budget_actual"]) / c["budget_actual"] * 100) if c["budget_actual"] else 0

    campaigns = await db.campaigns.find(_tq(user, {"event_id": event_id}), {"_id": 0}).to_list(500)
    campaign_ids = [x["id"] for x in campaigns] or [""]
    posts = await db.posts.find(
        {"tenant_id": tid, "campaign_id": {"$in": campaign_ids}}, {"_id": 0}
    ).to_list(2000)
    by_platform: dict = {}
    for p in posts:
        if not p.get("metric_source") or p["metric_source"] == "none":
            continue
        pl = p.get("platform", "other")
        by_platform.setdefault(pl, {"platform": pl, "reach": 0, "engagement": 0, "posts": 0})
        by_platform[pl]["reach"] += p.get("reach", 0)
        by_platform[pl]["engagement"] += p.get("engagement", 0)
        by_platform[pl]["posts"] += 1

    return {
        "event": event, **c, **lm,
        "revenue": revenue, "roi_percent": roi,
        "platform_breakdown": list(by_platform.values()),
        **status_block,
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
