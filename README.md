# NAS Core API (Phase 1–2)

FastAPI backend for a personal NAS: JWT auth, device onboarding, local file storage with MongoDB metadata, basic RBAC, disk status, **standard JSON envelopes**, dashboard aggregates, and ranged media streaming — tuned for Raspberry Pi (small pool, chunked uploads).

## Prerequisites

- Python 3.10+
- MongoDB ([Atlas](https://www.mongodb.com/atlas) or local)
- Writable directory for `STORAGE_PATH` (on Pi, mount HDD/SSD and point env there)

## Quick start (scripts)

From the `backend/` directory:

| Command | When to use |
|--------|-------------|
| `./setup.sh` | After cloning, or whenever you change `requirements.txt` |
| `./run.sh` | Start the API (expects `setup.sh` to have been run once) |
| `./setup_and_run.sh` | Install deps then start the server in one go |

Ensure `.env` exists (copy from `.env.example` if needed): `MONGO_URI`, `JWT_SECRET`, `STORAGE_PATH`, `MAX_UPLOAD_SIZE`, `ENVIRONMENT` (`development` | `production`). **CORS:** with `DEBUG=true`, `ENVIRONMENT=development`, or `NAS_CORS_DEV=true`, the API uses **`Access-Control-Allow-Origin: *`** and **`Access-Control-Allow-Credentials: false`**. That avoids browser preflight failures that happen when credentials are `true` but the allowed origin list does not match exactly. JWT in the `Authorization` header still works (no cross-origin cookies required). For **production**, set `DEBUG=false`, `ENVIRONMENT=production`, `NAS_CORS_DEV=false`, and a strict `CORS_ORIGINS` with `allow_credentials` behavior as needed. If your URI has no database name (e.g. ends with `.net/` or `host:27017`), either add one in the URI (`.../nas`) or set `MONGO_DB_NAME=nas`.

If MongoDB fails at startup, the process prints a **short banner** to stderr (instead of a long PyMongo stack) plus one line in the log. For Atlas TLS issues on macOS/Python 3.12+, run `./setup.sh` so `certifi` is installed; `mongodb+srv` connections use `tlsCAFile=certifi.where()` automatically.

Startup lines use the **`nas` logger** format `[HH:MM:SS.mmm] INFO (pid): …` (similar to other services). `run.sh` reads only `API_HOST` and `API_PORT` from `.env` (it does not `source` the file, so values with spaces — e.g. `APP_NAME=NAS Core API` — stay safe).

## Setup (manual)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # optional if .env is missing
# Edit .env: MONGO_URI, JWT_SECRET, STORAGE_PATH, MAX_UPLOAD_SIZE
```

## Run (manual)

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) for interactive testing.

## Seed admin user

```bash
cd backend
python scripts/seed_admin.py --email admin@nas.local --password 'your-secure-password'
```

Regular signups default to role `member`.

## JSON response shape (Phase 2)

Most endpoints return:

```json
{ "success": true, "message": "…", "data": { } }
```

Errors use the same keys with `success: false` and appropriate HTTP status (`400` validation, `401`, `403`, `404`, `409`, `413`, `500`). **Exceptions:** raw bytes for `GET /files/download/{id}`, `GET /files/preview/{id}`, and `GET /files/stream/{id}` (Range / video).

## Health

`GET /health` is unauthenticated and returns plain JSON (not the API envelope):

```json
{ "status": "ok", "checks": { "app": "ok", "mongo": "ok", "storage/config": "ok" }, "timestamp": "…Z" }
```

When `AGENT_URL` is set (e.g. serverless control plane), the `storage/config` check is replaced by an `agent` reachability probe against the edge host’s `GET /health`.

## Agent delegation (`AGENT_URL`)

For a split deployment (API in the cloud, disks on a home Pi), set `AGENT_URL` to the agent’s base URL (no trailing slash). File and disk routes in `files.py`, `files_browse.py`, and disk-related `storage.py` handlers forward to the agent over HTTP (`httpx`) instead of local `app/services/*` disk logic. Service modules are unchanged; routes use lazy imports for local mode only.

| Variable | Purpose |
|----------|---------|
| `AGENT_URL` | Base URL of the Pi / edge NAS API (optional; unset = all disk I/O local) |
| `AGENT_TOKEN` | Optional shared secret sent as `X-Agent-Token` on delegated calls |

The caller’s `Authorization: Bearer …` JWT is forwarded to the agent. On Lambda or similar, **`AGENT_URL` is required** for upload, download, browse, and storage status/device routes; Mongo-backed auth still runs on the control plane.

**Agent REST contract** (same paths as this API on the agent host):

| Method | Path |
|--------|------|
| GET | `/health` |
| POST | `/files/upload` |
| GET | `/files`, `/files/browse`, `/files/{id}`, `/files/folders/tree` |
| GET | `/files/download/{id}`, `/files/preview/{id}`, `/files/stream/{id}` |
| DELETE | `/files/{id}` |
| POST | `/files/folders`, `/files/move`, `/files/copy`, `/files/rename`, `/files/folders/rename` |
| GET | `/storage/status`, `/storage/devices`, `/storage/browse` |
| POST | `/storage/devices/config`, `/storage/mount`, `/storage/unmount`, `/storage/format` |

If the agent is down or misconfigured, delegated routes return `503` / `504` with a clear message. The edge agent implementation may land in a separate repo; until then, point `AGENT_URL` at a full NAS API instance on the Pi.

## API overview

| Area | Endpoints |
|------|-----------|
| Health | `GET /health` (plain JSON, no auth — for probes) |
| Auth | `POST /auth/signup`, `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me` |
| User | `GET /users/me` (alias; same envelope) |
| Devices | `POST /devices/register`, `GET /devices`, `PATCH /devices/{id}/heartbeat`, `GET /devices/{id}`, `DELETE /devices/{id}` |
| Files | `POST /files/upload`, `GET /files?limit&offset&sort`, `GET /files/preview/{id}`, `GET /files/stream/{id}`, `GET /files/download/{id}`, `GET /files/{id}`, `DELETE /files/{id}` |
| Health | `GET /health` |
| Storage | `GET /storage/status` |
| Dashboard | `GET /dashboard/overview` |
| Realtime (stub) | WebSocket `WS /ws` |

## RBAC (Phase 1)

- **admin**: all files/devices; optional `user_id` filter on list endpoints
- **member**: full CRUD on own files; read access to `shared_with` (populate in DB when you add sharing)
- **guest**: read-only files (list/get/download); no upload/delete

## Project layout

- `app/core/` — settings, security, small utils
- `app/db/` — Motor client lifecycle + indexes
- `app/models/` — Pydantic schemas
- `app/routes/` — routers
- `app/services/` — business logic
- `app/middleware/rbac.py` — `require_roles` dependency
- `app/ai/` — placeholder for future AI modules
- `app/core/tasks.py` — placeholder for background jobs

## Pi notes

- Keep `maxPoolSize` low in `app/db/mongo.py` if memory is tight.
- Prefer a dedicated ext4 mount for `STORAGE_PATH` and ensure the `pi` user can write to it.

## CI/CD

GitHub Actions workflow: [`.github/workflows/ci-cd.yml`](.github/workflows/ci-cd.yml).

| Trigger | What runs |
|---------|-----------|
| Pull request → `master` | Build Lambda zip artifact only |
| Push → `master` | Build, deploy Lambda, ensure HTTP API (v2) + optional custom domain |

**Handler:** set the function handler to `lambda_handler.handler` (Mangum wraps `app.main:app`).

### GitHub configuration

| Kind | Name | Purpose |
|------|------|---------|
| Variable | `AWS_REGION` | Region for deploy (e.g. `ap-south-1`) |
| Variable | `AWS_ROLE_ARN` | IAM role ARN for OIDC (`aws-actions/configure-aws-credentials`) |
| Variable | `LAMBDA_FUNCTION_NAME` | Lambda function to update |
| Variable | `HTTP_API_ID` | Optional. Existing API Gateway HTTP API id; workflow also resolves `nas-system-api` by name |
| Variable | `API_DOMAIN` | Optional custom domain (e.g. `api.example.com`); leave empty to use the default `execute-api` URL |
| Variable | `ACM_CERTIFICATE_ARN` | Optional regional ACM cert in `AWS_REGION` (required when `API_DOMAIN` is set) |

After a successful deploy, the workflow writes the invoke URL to the job **Summary** (`https://{api-id}.execute-api.{region}.amazonaws.com/` or your custom domain).

### IAM permissions (deploy role)

The OIDC role needs at least `lambda:UpdateFunctionCode`, `lambda:AddPermission`, and API Gateway HTTP API (v2) management (`apigateway:GET`, `POST`, `PATCH`, `DELETE` on `apigatewayv2` resources). The **NovaSafe** role in this project is configured with admin access for deploy.

### OIDC setup (recommended)

1. Add GitHub OIDC provider in IAM (`token.actions.githubusercontent.com`).
2. Create a role trusted by your repo/branch with the permissions above on the target function and API.
3. Set `AWS_ROLE_ARN` to that role.

### Access-key fallback

If OIDC is not available, replace the credentials step with `aws-access-key-id` / `aws-secret-access-key` from repository secrets (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) per [configure-aws-credentials](https://github.com/aws-actions/configure-aws-credentials) docs. Prefer OIDC for production.

### Local zip build (same as CI)

```bash
mkdir -p package
pip install -r requirements.txt -t package
cp -r app package/
cp lambda_handler.py package/
cd package && zip -r9 ../lambda-deployment.zip .
```
