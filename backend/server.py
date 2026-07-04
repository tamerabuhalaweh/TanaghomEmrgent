"""AI Campaign Manager — FastAPI backend.

All endpoints are prefixed with /api. MongoDB is accessed through motor.
"""
from __future__ import annotations

import os
import uuid
import logging
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, Annotated, Any

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
# Setup
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALG = "HS256"
JWT_EXP_HOURS = 24 * 7

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="AI Campaign Manager")
api = APIRouter(prefix="/api")
bearer = HTTPBearer(auto_error=False)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("campaign")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaseDoc(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=_now_iso)


# --- Auth / User -----------------------------------------------------------
ROLES = ("admin", "marketing", "sales", "viewer")

PERMISSIONS_BY_ROLE = {
    "admin": ["*"],
    "marketing": ["events.read", "events.write", "campaigns.write", "posts.write", "ai.generate", "dashboard.read"],
    "sales": ["events.read", "leads.write", "dashboard.read"],
    "viewer": ["events.read", "dashboard.read"],
}


class UserPublic(BaseModel):
    id: str
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


# --- LLM keys / social / integrations --------------------------------------
class LLMKeyIn(BaseModel):
    provider: str  # openai | anthropic | gemini
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
    platform: str  # meta | instagram | youtube | tiktok | linkedin | x
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
    kind: str  # gohighlevel | zapier | webhook
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
    status: str = "connected"
    created_at: str


# --- Events / Campaigns / Posts / Leads ------------------------------------
EVENT_TYPES = ("motaz_live", "excellence_camp", "business_camp", "virtual_ramadan", "custom")


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
    goal: str = "max_reach"  # max_reach | conversion | engagement
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
    status: str = "draft"  # draft | approved | rejected | scheduled
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
    # simulated metrics
    reach: int = 0
    impressions: int = 0
    clicks: int = 0
    engagement: int = 0


class PostUpdate(BaseModel):
    status: Optional[str] = None
    caption: Optional[str] = None
    hook: Optional[str] = None
    cta: Optional[str] = None
    hashtags: Optional[List[str]] = None
    scheduled_at: Optional[str] = None


class LeadIn(BaseModel):
    event_id: str
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    source: str = "form"  # form | ad | referral | manual
    stage: str = "new"    # new | form_filled | booked | purchased | no_show
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


def make_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
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
        email=user["email"],
        name=user["name"],
        role=user["role"],
        permissions=user.get("permissions") or PERMISSIONS_BY_ROLE.get(user["role"], []),
        is_active=user.get("is_active", True),
        created_at=user["created_at"],
    )


# ---------------------------------------------------------------------------
# Routes: Auth & Users
# ---------------------------------------------------------------------------
@api.post("/auth/login", response_model=AuthResponse)
async def login(body: LoginBody):
    user = await db.users.find_one({"email": body.email.lower()}, {"_id": 0})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not user.get("is_active", True):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
    token = make_token(user["id"], user["role"])
    return AuthResponse(token=token, user=to_public(user))


@api.get("/auth/me", response_model=UserPublic)
async def me(user: dict = Depends(current_user)):
    return to_public(user)


@api.get("/users", response_model=List[UserPublic])
async def list_users(_: dict = Depends(require_role("admin"))):
    docs = await db.users.find({}, {"_id": 0}).to_list(500)
    return [to_public(d) for d in docs]


@api.post("/users", response_model=UserPublic)
async def create_user(body: UserCreate, _: dict = Depends(require_role("admin"))):
    if body.role not in ROLES:
        raise HTTPException(400, "Invalid role")
    existing = await db.users.find_one({"email": body.email.lower()})
    if existing:
        raise HTTPException(409, "Email already exists")
    doc = {
        "id": str(uuid.uuid4()),
        "email": body.email.lower(),
        "name": body.name,
        "role": body.role,
        "permissions": body.permissions or PERMISSIONS_BY_ROLE[body.role],
        "password_hash": hash_password(body.password),
        "is_active": True,
        "created_at": _now_iso(),
    }
    await db.users.insert_one(doc)
    return to_public(doc)


@api.patch("/users/{user_id}", response_model=UserPublic)
async def update_user(user_id: str, body: UserUpdate, _: dict = Depends(require_role("admin"))):
    update = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "password" in update:
        update["password_hash"] = hash_password(update.pop("password"))
    if not update:
        raise HTTPException(400, "Nothing to update")
    result = await db.users.find_one_and_update(
        {"id": user_id}, {"$set": update}, return_document=True
    )
    if not result:
        raise HTTPException(404, "User not found")
    result.pop("_id", None)
    return to_public(result)


@api.delete("/users/{user_id}")
async def delete_user(user_id: str, actor: dict = Depends(require_role("admin"))):
    if actor["id"] == user_id:
        raise HTTPException(400, "Cannot delete self")
    r = await db.users.delete_one({"id": user_id})
    return {"deleted": r.deleted_count}


# ---------------------------------------------------------------------------
# Routes: Settings — LLM keys, Social accounts, Integrations
# ---------------------------------------------------------------------------
@api.get("/settings/llm-keys", response_model=List[LLMKeyOut])
async def list_llm_keys(_: dict = Depends(require_role("admin"))):
    docs = await db.llm_keys.find({}, {"_id": 0}).to_list(200)
    return [
        LLMKeyOut(
            id=d["id"], provider=d["provider"], model=d.get("model"),
            label=d.get("label"), key_masked=mask(decrypt(d["api_key_enc"])),
            use_emergent=d.get("use_emergent", False), created_at=d["created_at"],
        )
        for d in docs
    ]


@api.post("/settings/llm-keys", response_model=LLMKeyOut)
async def add_llm_key(body: LLMKeyIn, _: dict = Depends(require_role("admin"))):
    if body.provider not in ("openai", "anthropic", "gemini"):
        raise HTTPException(400, "Unsupported provider")
    doc = {
        "id": str(uuid.uuid4()), "provider": body.provider, "model": body.model,
        "label": body.label, "api_key_enc": encrypt(body.api_key),
        "use_emergent": False, "created_at": _now_iso(),
    }
    await db.llm_keys.insert_one(doc)
    return LLMKeyOut(
        id=doc["id"], provider=doc["provider"], model=doc.get("model"),
        label=doc.get("label"), key_masked=mask(body.api_key),
        use_emergent=False, created_at=doc["created_at"],
    )


@api.delete("/settings/llm-keys/{key_id}")
async def delete_llm_key(key_id: str, _: dict = Depends(require_role("admin"))):
    r = await db.llm_keys.delete_one({"id": key_id})
    return {"deleted": r.deleted_count}


@api.get("/settings/social-accounts", response_model=List[SocialAccountOut])
async def list_social(_: dict = Depends(require_role("admin"))):
    docs = await db.social_accounts.find({}, {"_id": 0}).to_list(200)
    return [
        SocialAccountOut(
            id=d["id"], platform=d["platform"], handle=d["handle"],
            page_id=d.get("page_id"), token_masked=mask(decrypt(d["token_enc"])),
            created_at=d["created_at"],
        )
        for d in docs
    ]


@api.post("/settings/social-accounts", response_model=SocialAccountOut)
async def add_social(body: SocialAccountIn, _: dict = Depends(require_role("admin"))):
    doc = {
        "id": str(uuid.uuid4()), "platform": body.platform, "handle": body.handle,
        "page_id": body.page_id, "token_enc": encrypt(body.access_token),
        "created_at": _now_iso(),
    }
    await db.social_accounts.insert_one(doc)
    return SocialAccountOut(
        id=doc["id"], platform=doc["platform"], handle=doc["handle"],
        page_id=doc.get("page_id"), token_masked=mask(body.access_token),
        created_at=doc["created_at"],
    )


@api.delete("/settings/social-accounts/{sid}")
async def delete_social(sid: str, _: dict = Depends(require_role("admin"))):
    r = await db.social_accounts.delete_one({"id": sid})
    return {"deleted": r.deleted_count}


@api.get("/integrations", response_model=List[IntegrationOut])
async def list_integrations(_: dict = Depends(require_role("admin"))):
    docs = await db.integrations.find({}, {"_id": 0}).to_list(200)
    return [
        IntegrationOut(
            id=d["id"], kind=d["kind"], label=d["label"],
            api_key_masked=mask(decrypt(d["api_key_enc"])) if d.get("api_key_enc") else None,
            webhook_url=d.get("webhook_url"), config=d.get("config"),
            status=d.get("status", "connected"), created_at=d["created_at"],
        )
        for d in docs
    ]


@api.post("/integrations", response_model=IntegrationOut)
async def add_integration(body: IntegrationIn, _: dict = Depends(require_role("admin"))):
    doc = {
        "id": str(uuid.uuid4()), "kind": body.kind, "label": body.label,
        "api_key_enc": encrypt(body.api_key) if body.api_key else None,
        "webhook_url": body.webhook_url, "config": body.config,
        "status": "connected", "created_at": _now_iso(),
    }
    await db.integrations.insert_one(doc)
    return IntegrationOut(
        id=doc["id"], kind=doc["kind"], label=doc["label"],
        api_key_masked=mask(body.api_key) if body.api_key else None,
        webhook_url=doc.get("webhook_url"), config=doc.get("config"),
        status=doc["status"], created_at=doc["created_at"],
    )


@api.delete("/integrations/{iid}")
async def delete_integration(iid: str, _: dict = Depends(require_role("admin"))):
    r = await db.integrations.delete_one({"id": iid})
    return {"deleted": r.deleted_count}


# ---------------------------------------------------------------------------
# Routes: Events
# ---------------------------------------------------------------------------
def _clean(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


@api.get("/events", response_model=List[EventOut])
async def list_events(_: dict = Depends(current_user)):
    docs = await db.events.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return [EventOut(**d) for d in docs]


@api.post("/events", response_model=EventOut)
async def create_event(body: EventIn, _: dict = Depends(require_role("admin", "marketing"))):
    doc = EventOut(**body.model_dump()).model_dump()
    await db.events.insert_one(doc)
    return EventOut(**_clean(doc))


@api.get("/events/{event_id}", response_model=EventOut)
async def get_event(event_id: str, _: dict = Depends(current_user)):
    d = await db.events.find_one({"id": event_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Event not found")
    return EventOut(**d)


@api.patch("/events/{event_id}", response_model=EventOut)
async def update_event(event_id: str, body: dict, _: dict = Depends(require_role("admin", "marketing"))):
    body.pop("id", None); body.pop("_id", None); body.pop("created_at", None)
    d = await db.events.find_one_and_update({"id": event_id}, {"$set": body}, return_document=True)
    if not d:
        raise HTTPException(404, "Event not found")
    return EventOut(**_clean(d))


@api.delete("/events/{event_id}")
async def delete_event(event_id: str, _: dict = Depends(require_role("admin"))):
    r = await db.events.delete_one({"id": event_id})
    await db.campaigns.delete_many({"event_id": event_id})
    await db.posts.delete_many({"event_id": event_id})
    await db.leads.delete_many({"event_id": event_id})
    return {"deleted": r.deleted_count}


# ---------------------------------------------------------------------------
# Routes: Campaigns
# ---------------------------------------------------------------------------
@api.get("/events/{event_id}/campaigns", response_model=List[CampaignOut])
async def list_campaigns(event_id: str, _: dict = Depends(current_user)):
    docs = await db.campaigns.find({"event_id": event_id}, {"_id": 0}).to_list(500)
    return [CampaignOut(**d) for d in docs]


@api.post("/campaigns", response_model=CampaignOut)
async def create_campaign(body: CampaignIn, _: dict = Depends(require_role("admin", "marketing"))):
    doc = CampaignOut(**body.model_dump()).model_dump()
    await db.campaigns.insert_one(doc)
    return CampaignOut(**_clean(doc))


@api.patch("/campaigns/{cid}", response_model=CampaignOut)
async def update_campaign(cid: str, body: dict, _: dict = Depends(require_role("admin", "marketing"))):
    body.pop("id", None); body.pop("_id", None); body.pop("created_at", None)
    d = await db.campaigns.find_one_and_update({"id": cid}, {"$set": body}, return_document=True)
    if not d:
        raise HTTPException(404, "Campaign not found")
    return CampaignOut(**_clean(d))


@api.delete("/campaigns/{cid}")
async def delete_campaign(cid: str, _: dict = Depends(require_role("admin", "marketing"))):
    r = await db.campaigns.delete_one({"id": cid})
    await db.posts.delete_many({"campaign_id": cid})
    return {"deleted": r.deleted_count}


# ---------------------------------------------------------------------------
# Routes: Posts (AI-generation + CRUD)
# ---------------------------------------------------------------------------
@api.post("/posts/generate")
async def ai_generate_posts(body: PostGenerateIn, _: dict = Depends(require_role("admin", "marketing"))):
    try:
        ideas = await llm_service.generate_post_ideas(
            prompt=body.prompt,
            provider=body.provider,
            model=body.model,
            platforms=body.platforms,
            audience=body.audience,
            goal=body.goal,
            n=max(1, min(body.n, 8)),
            language=body.language,
        )
    except Exception as e:
        log.exception("AI generation failed")
        raise HTTPException(500, f"AI generation failed: {e}")
    return {"ideas": ideas}


@api.get("/campaigns/{cid}/posts", response_model=List[PostOut])
async def list_posts(cid: str, _: dict = Depends(current_user)):
    docs = await db.posts.find({"campaign_id": cid}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return [PostOut(**d) for d in docs]


@api.post("/posts", response_model=PostOut)
async def create_post(body: PostIn, _: dict = Depends(require_role("admin", "marketing"))):
    doc = PostOut(**body.model_dump()).model_dump()
    # simulated engagement seeds
    doc["reach"] = random.randint(500, 20000)
    doc["impressions"] = int(doc["reach"] * random.uniform(1.1, 2.5))
    doc["clicks"] = int(doc["reach"] * random.uniform(0.01, 0.08))
    doc["engagement"] = int(doc["reach"] * random.uniform(0.02, 0.15))
    await db.posts.insert_one(doc)
    return PostOut(**_clean(doc))


@api.patch("/posts/{pid}", response_model=PostOut)
async def update_post(pid: str, body: PostUpdate, _: dict = Depends(require_role("admin", "marketing"))):
    update = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not update:
        raise HTTPException(400, "Nothing to update")
    d = await db.posts.find_one_and_update({"id": pid}, {"$set": update}, return_document=True)
    if not d:
        raise HTTPException(404, "Post not found")
    return PostOut(**_clean(d))


@api.delete("/posts/{pid}")
async def delete_post(pid: str, _: dict = Depends(require_role("admin", "marketing"))):
    r = await db.posts.delete_one({"id": pid})
    return {"deleted": r.deleted_count}


# ---------------------------------------------------------------------------
# Routes: Leads
# ---------------------------------------------------------------------------
@api.get("/events/{event_id}/leads", response_model=List[LeadOut])
async def list_leads(event_id: str, _: dict = Depends(current_user)):
    docs = await db.leads.find({"event_id": event_id}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return [LeadOut(**d) for d in docs]


@api.post("/leads", response_model=LeadOut)
async def create_lead(body: LeadIn, _: dict = Depends(require_role("admin", "marketing", "sales"))):
    doc = LeadOut(**body.model_dump()).model_dump()
    await db.leads.insert_one(doc)
    return LeadOut(**_clean(doc))


@api.patch("/leads/{lid}", response_model=LeadOut)
async def update_lead(lid: str, body: dict, _: dict = Depends(require_role("admin", "marketing", "sales"))):
    body.pop("id", None); body.pop("_id", None); body.pop("created_at", None)
    d = await db.leads.find_one_and_update({"id": lid}, {"$set": body}, return_document=True)
    if not d:
        raise HTTPException(404, "Lead not found")
    return LeadOut(**_clean(d))


# ---------------------------------------------------------------------------
# Routes: Dashboards
# ---------------------------------------------------------------------------
async def _campaign_metrics(event_id: Optional[str] = None) -> dict:
    q = {"event_id": event_id} if event_id else {}
    campaigns = await db.campaigns.find(q, {"_id": 0}).to_list(500)
    campaign_ids = [c["id"] for c in campaigns]
    posts_q = {"campaign_id": {"$in": campaign_ids}} if campaign_ids else {}
    posts = await db.posts.find(posts_q, {"_id": 0}).to_list(2000)
    total_reach = sum(p.get("reach", 0) for p in posts)
    total_impressions = sum(p.get("impressions", 0) for p in posts)
    total_engagement = sum(p.get("engagement", 0) for p in posts)
    total_clicks = sum(p.get("clicks", 0) for p in posts)
    budget_planned = sum(c.get("budget_planned", 0) for c in campaigns)
    budget_actual = sum(c.get("budget_actual", 0) for c in campaigns)
    return {
        "reach": total_reach, "impressions": total_impressions,
        "engagement": total_engagement, "clicks": total_clicks,
        "budget_planned": budget_planned, "budget_actual": budget_actual,
        "posts_count": len(posts), "campaigns_count": len(campaigns),
    }


async def _lead_metrics(event_id: Optional[str] = None) -> dict:
    q = {"event_id": event_id} if event_id else {}
    leads = await db.leads.find(q, {"_id": 0}).to_list(5000)
    stages = {"new": 0, "form_filled": 0, "booked": 0, "purchased": 0, "no_show": 0}
    for l in leads:
        s = l.get("stage", "new")
        if s in stages:
            stages[s] += 1
    return {"total_leads": len(leads), **{f"leads_{k}": v for k, v in stages.items()}}


@api.get("/dashboard/global")
async def dashboard_global(_: dict = Depends(current_user)):
    events = await db.events.find({}, {"_id": 0}).to_list(500)
    c = await _campaign_metrics()
    l = await _lead_metrics()
    # Trend: last 14 days simulated based on posts distribution
    trend = []
    today = datetime.now(timezone.utc).date()
    for i in range(13, -1, -1):
        day = today - timedelta(days=i)
        seed = (hash(day.isoformat()) & 0xFFFF) / 0xFFFF
        trend.append({
            "date": day.isoformat(),
            "reach": int((c["reach"] / 14) * (0.5 + seed)),
            "engagement": int((c["engagement"] / 14) * (0.5 + seed)),
            "leads": int((l["total_leads"] / 14) * (0.5 + seed)),
        })
    return {
        "events_count": len(events),
        **c, **l,
        "trend": trend,
    }


@api.get("/dashboard/event/{event_id}")
async def dashboard_event(event_id: str, _: dict = Depends(current_user)):
    event = await db.events.find_one({"id": event_id}, {"_id": 0})
    if not event:
        raise HTTPException(404, "Event not found")
    c = await _campaign_metrics(event_id)
    l = await _lead_metrics(event_id)
    # revenue estimate
    price = event.get("ticket_price") or 0
    revenue = price * l["leads_purchased"]
    roi = ((revenue - c["budget_actual"]) / c["budget_actual"] * 100) if c["budget_actual"] else 0

    # platform breakdown
    campaigns = await db.campaigns.find({"event_id": event_id}, {"_id": 0}).to_list(500)
    campaign_ids = [x["id"] for x in campaigns]
    posts = await db.posts.find({"campaign_id": {"$in": campaign_ids}}, {"_id": 0}).to_list(2000)
    by_platform: dict[str, dict] = {}
    for p in posts:
        pl = p.get("platform", "other")
        by_platform.setdefault(pl, {"platform": pl, "reach": 0, "engagement": 0, "posts": 0})
        by_platform[pl]["reach"] += p.get("reach", 0)
        by_platform[pl]["engagement"] += p.get("engagement", 0)
        by_platform[pl]["posts"] += 1

    return {
        "event": event, **c, **l,
        "revenue": revenue, "roi_percent": roi,
        "platform_breakdown": list(by_platform.values()),
    }


# ---------------------------------------------------------------------------
# Startup: seed admin
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def seed_admin():
    admin_email = "admin@campaign.ai"
    exists = await db.users.find_one({"email": admin_email})
    if not exists:
        doc = {
            "id": str(uuid.uuid4()),
            "email": admin_email,
            "name": "Platform Admin",
            "role": "admin",
            "permissions": ["*"],
            "password_hash": hash_password("Admin@12345"),
            "is_active": True,
            "created_at": _now_iso(),
        }
        await db.users.insert_one(doc)
        log.info("Seeded admin user %s", admin_email)


# Register router + CORS
app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def _shutdown():
    client.close()
