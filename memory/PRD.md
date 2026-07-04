# Campaign OS — AI-Powered Social Media Campaign Manager
_Last updated: 2026-07-04_

## Original Problem Statement (summary)
Build an AI-powered social media campaign platform with:
1. Admin Panel — securely store social accounts + LLM API keys (GPT / Claude / Gemini)
2. AI post planning — topic/content suggestions, edit/approve/reject flow
3. Multi-platform posting, audience targeting, algorithm-tuned reach
4. Event & campaign management with planned-vs-actual budget tracking
5. 360° KPI dashboard, per-event sub-dashboards (Motaz Live, Excellence Camp, Business Camp, Virtual Ramadan)
6. User management with role-based permissions
7. GoHighLevel CRM integration + external connectors page
8. Bilingual UI (EN / AR RTL) with toggle

## User Personas
- **Admin** — owner; manages users, LLM keys, social accounts, integrations
- **Marketing Manager (Amro)** — plans events/campaigns, generates AI content, monitors KPIs
- **Sales** — manages leads, updates stages (form_filled → booked → purchased)
- **Viewer** — read-only dashboards

## Architecture
- **Backend**: FastAPI + Motor (MongoDB), JWT auth (bcrypt), Fernet encryption for stored secrets, Emergent LLM key via `emergentintegrations`
- **Frontend**: React 19 + React Router 7 + Tailwind + Recharts + sonner (toasts)
- **AI**: Emergent Universal LLM Key with pluggable provider (OpenAI GPT-5.2 default, Claude Sonnet 4.6, Gemini 3 Flash)
- **i18n**: In-memory dictionary + `<html dir="rtl|ltr">` toggle, CSS logical properties

## What's Been Implemented (MVP — 2026-07-04)
### Backend (`/app/backend/server.py`)
- Auth: `/api/auth/login`, `/api/auth/me` (JWT 7-day expiry)
- Users (admin): CRUD, activate/disable, role assignment (`admin/marketing/sales/viewer`)
- LLM keys (admin): CRUD, encrypted at rest, list returns masked keys
- Social accounts (admin): CRUD, encrypted at rest
- Integrations: GoHighLevel / Zapier / Webhook CRUD
- Events: CRUD (`motaz_live/excellence_camp/business_camp/virtual_ramadan/custom`)
- Campaigns: CRUD scoped to an event, with goal / platforms / audience
- Posts: CRUD + `/api/posts/generate` (real LLM call producing hook/caption/cta/hashtags/reasoning per platform)
- Leads: CRUD scoped to event, stage funnel (new → form_filled → booked → purchased → no_show)
- Dashboards: `/api/dashboard/global` (KPIs + 14-day trend), `/api/dashboard/event/{id}` (funnel, revenue, ROI, platform breakdown)

### Frontend (`/app/frontend/src`)
- Login (bilingual, admin credentials pre-filled)
- Sidebar layout (RTL-aware, language toggle)
- Global Dashboard — KPIs + 14-day area chart + event quick list
- Events list + create modal (with Motaz/Excellence/Business/Ramadan types + cover images)
- Event Detail — hero + funnel KPIs + budget bar + platform pie + campaigns + leads table + AI-Builder shortcut
- AI Builder — two-pane: audience/strategy config + streaming-quality idea cards with per-card approve/reject/edit and save-as-post
- Users (admin) — CRUD + activate toggle
- Settings (admin) — tabs for LLM Keys / Social Accounts, encrypted storage
- Integrations — catalog (GoHighLevel, Zapier, Webhook) + connected list

### Testing
- 43/43 backend tests passing after Patch 1 (production foundation — tenant isolation, audit log, honest metrics, secret masking, CORS, env validation)
- Seed data cleanup implemented

## Patch 1 — Production Foundation (2026-07-04)
Additions to backend/server.py without touching UI design:
- **Tenants** — `tenants` collection + `default` tenant seeded on startup. `tenant_id` on every user + JWT + every business doc. Legacy pre-tenant docs auto-backfilled.
- **Tenant isolation** — all list/get/patch/delete filter by caller's `tenant_id`; cross-tenant reads/writes return 404.
- **Audit log** — new `audit_logs` collection + `audit()` helper wired into login (success/failure), user/LLM key/social/integration/event/campaign/post/lead mutations. `GET /api/audit-logs` (admin, tenant-scoped). Metadata sanitizer strips any `password/api_key/token/secret/*` field.
- **Honest metrics** — post creation no longer seeds random reach/impressions/clicks/engagement. Defaults are `0` + `metric_source: none`. PATCH with metric values sets `metric_source: manual`. Dashboards return `metrics_status: no_verified_metrics` + `metrics_message` when nothing is verified.
- **Env validation** — MONGO_URL, DB_NAME, JWT_SECRET, FERNET_KEY, CORS_ORIGINS all required at boot (RuntimeError otherwise). FERNET_KEY validated at boot. Wildcard `*` in CORS_ORIGINS rejected.
- **Integrations** — `kind` whitelist enforced (400 on invalid). Response fields renamed to reality: `status: credential_saved`, `validated: false`, `live_sync_enabled: false`.
- **Frontend labels only** — Dashboard + Event dashboard show "Verified metrics pending" banner when backend returns `no_verified_metrics`. Integrations page replaces green "Connected" pill with `Credential saved • Not validated • Live sync off`.

### Still deferred (out of Patch 1 scope)
- Real GoHighLevel / Meta / YouTube API calls (validation + live sync)
- Actual analytics import connectors (post metric ingestion)
- Multi-workspace UI (tenants are foundation only — no create-workspace UI yet)

## Patch 2 — Verified Event KPI Import (2026-07-04)
Adds the verified-metrics data layer. No external API calls yet.

### Backend
- New `event_kpi_records` collection with strict validation (`_validate_kpi_row`):
  - channels: `meta / instagram / youtube / whatsapp / email / organic / dark_ad / referral / manual / other`
  - source_type: `manual / csv_import / connector`
  - non-negative integers/floats; `metric_date` must be `YYYY-MM-DD`
  - all-zero rows only accepted when `source_type=manual` AND `notes` is non-empty
- Endpoints (tenant-scoped, audited):
  - `GET /api/events/{id}/kpis` with optional filters `channel`, `source_type`, `start_date`, `end_date`
  - `POST /api/events/{id}/kpis` (admin+marketing; server forces `source_type=manual`)
  - `PATCH /api/events/{id}/kpis/{kpi_id}` (admin+marketing; re-validates merged state)
  - `DELETE /api/events/{id}/kpis/{kpi_id}` (admin only)
  - `POST /api/events/{id}/kpis/csv/dry-run` (validate + preview_totals, no writes)
  - `POST /api/events/{id}/kpis/csv/import` (atomic: reject whole payload if any row invalid; else insert with `source_type=csv_import`)
- Audit actions added: `event_kpi_created / updated / deleted`, `event_kpi_csv_dry_run`, `event_kpi_csv_imported` — metadata only contains counts/event_id + a redacted notes preview (never the raw rows).
- Dashboards rewritten (`_kpi_aggregate` + `_lead_metrics` + `_campaign_budget`):
  - Global + per-event now aggregate from `event_kpi_records` only. Post metrics no longer feed the dashboard.
  - Returns real totals for reach / impressions / interactions / clicks / form_completions / leads / meetings_booked / meetings_attended / no_shows / purchases / spend / revenue.
  - Derived: `roi_percent`, `form_completion_rate`, `lead_to_purchase_rate`, `meeting_show_rate`, `cost_per_lead`, `cost_per_purchase`, `budget_variance`.
  - `channel_breakdown`, `source_type_breakdown`, and `trend` (grouped by `metric_date`).
  - `metrics_status: no_verified_metrics` when zero KPI records exist.

### Frontend
- `EventKpiPanel.jsx` (new) — Verified KPI Records table (empty state, delete row), Add KPI Record modal (all 12 numeric fields + channel + notes), CSV Import Preview panel (textarea for JSON rows, `Validate Import` → dry-run preview totals + row errors, `Import Valid Rows` enabled only if zero errors, "No external platform is called" callout).
- `EventDetail.jsx` — panel wired in above Campaigns section; shows green "Verified KPI data" banner or orange "Verified metrics pending" banner based on `metrics_status`.
- `Dashboard.jsx` — same verified/pending banner treatment; text now says "Add manual KPI data or import a CSV to populate performance metrics." (removed language implying live social sync).

### Testing
- **66/66 backend tests passing** (43 pre-existing + 23 new for Patch 2).
- Covers: KPI CRUD + RBAC (marketing/sales/viewer/admin), validation (negatives / unknown channel / unknown source_type / all-zero with & without notes / bad date), tenant isolation (cross-tenant KPI, cross-tenant campaign_id → 400, global dashboard tenant-scoped), CSV dry-run (no writes, per-row errors, audit counts only), CSV import (atomic reject, happy-path insert with `source_type=csv_import`), dashboard aggregation + derived rates + divide-by-zero, secret sanitization (notes with `api_key=…` redacted to `[redacted-notes]`).

### Still deferred (out of Patch 2)
- Real GoHighLevel / Meta / YouTube / Formaloo / WhatsApp connectors
- File-upload CSV parsing (front end currently uses a JSON textarea — good enough for verified dry-run/import; a proper CSV-file uploader ships in a later patch)
- Splitting `server.py` (1679 lines) into per-domain routers
- `@app.on_event` → FastAPI `lifespan` migration
- Frontend "Import Valid Rows" respecting per-row invalid dropping (currently import is atomic on the whole payload — matches the backend contract)

## Backlog
### P0 — after MVP feedback
- Streaming SSE for AI generation (currently non-streaming)
- Real GoHighLevel API integration (currently stores credentials only)
- Meta Ads / YouTube Ads OAuth + real reach/impressions ingest (currently simulated)

### P1 — feature depth
- Post scheduling with cron-style dispatch, calendar view
- WhatsApp / email campaign designer with FOMO templates
- Lead auto-tagging + workflow builder (GHL-parity)
- Dark Ads support (upload to Meta as page-hidden)
- Formaloo replacement — form builder + submission collector

### P2 — polish
- Multi-tenant workspaces
- Full audit log
- LLM cost tracking per generation
- Export dashboards to PDF/PNG

## Test Credentials
See `/app/memory/test_credentials.md`. Default admin: `admin@campaign.ai / Admin@12345`.
