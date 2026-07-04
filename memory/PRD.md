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
- 33/33 backend tests passing (auth, RBAC, CRUD, dashboards, encrypted storage, real LLM generation)
- Seed data cleanup implemented

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
