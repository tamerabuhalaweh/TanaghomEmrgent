# Deployment Guide

This repo is deployable as three services:

- MongoDB
- FastAPI backend
- React frontend served by Nginx

## Required Environment

Create deployment secrets from `.env.example`.

Required backend values:

- `MONGO_URL`
- `DB_NAME`
- `JWT_SECRET`
- `FERNET_KEY`
- `CORS_ORIGINS`

Generate `FERNET_KEY`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`CORS_ORIGINS` must be explicit. `*` is rejected at startup.

Optional:

- `UNIVERSAL_LLM_KEY`
- `EMERGENT_LLM_KEY` only for backward compatibility with older environments
- `GHL_READ_SYNC_ENABLED=false`

Keep `GHL_READ_SYNC_ENABLED=false` until the tenant has a real GHL API key, location ID, mappings, and business approval to read CRM data.

## Local Docker Run

```bash
cp .env.example .env
# Fill JWT_SECRET, FERNET_KEY, and CORS_ORIGINS.
docker compose up --build
```

Frontend:

```text
http://localhost:3000
```

Backend:

```text
http://localhost:8001/api
```

## Backend Manual Run

```bash
cd backend
python -m pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001
```

## Frontend Manual Run

```bash
cd frontend
npm ci
VITE_API_BASE_URL=http://localhost:8001 npm run build
```

## Production Notes

- Use a managed MongoDB instance or a backed-up MongoDB volume.
- Put secrets in the hosting provider secret manager.
- Do not commit `.env`.
- Configure HTTPS at the ingress/load balancer.
- Configure `CORS_ORIGINS` to the exact frontend domain.
- Add uptime checks for `/api/auth/me`; HTTP 401/403 is acceptable and proves the API is reachable.
