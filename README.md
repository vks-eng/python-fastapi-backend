<div align="center">

# TaskForge API: Production-Ready FastAPI Task Management Backend

**A production-ready, async Task Management REST API built with FastAPI, SQLAlchemy 2.0 and PostgreSQL.**

JWT auth with refresh-token rotation and reuse detection · Argon2 password hashing · RBAC · rate limiting · structured logging · fully tested CI

[![CI](https://github.com/vks-eng/python-fastapi-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/vks-eng/python-fastapi-backend/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy_2.0-D71F00?logo=sqlalchemy&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## ✨ Highlights

- **Secure authentication**: short-lived JWT access tokens plus opaque refresh tokens that **rotate on every use**. Replaying an already-used refresh token is treated as theft and **revokes the whole session**.
- **Argon2id password hashing**, password-strength validation, and optional admin-gated account activation.
- **Role-based access control**: users can only see their own tasks, and admins can manage users and see every task.
- **Production-grade querying**: pagination, multi-value filtering, multi-field sorting, case-insensitive search and due-date ranges.
- **Clean architecture**: routers → services → repositories → models. Route handlers contain no business logic.
- **Fully async**: FastAPI, SQLAlchemy 2.0 async ORM and asyncpg.
- **Observability**: JSON structured logs, a `X-Request-ID` on every request and response, and `/health` and `/ready` probes.
- **Rate limiting** on login, register and refresh. It uses Redis when available, with an in-process fallback.
- **Consistent error envelope** with machine-readable codes and request IDs, and no stack traces leaked.
- **Alembic migrations**, Docker multi-stage build, GitHub Actions CI with lint, tests, coverage and dependency audit.

## 📑 Table of Contents

- [Why this project](#-why-this-project)
- [Architecture](#-architecture)
- [Features](#-features)
- [Tech Stack](#-tech-stack)
- [Quick Start](#-quick-start)
- [Make targets](#make-targets)
- [Configuration](#-configuration)
- [Database & Migrations](#-database--migrations)
- [API Reference](#-api-reference)
- [Testing](#-testing)
- [Deployment](#-deployment)
- [Security Considerations](#-security-considerations)
- [Project Structure](#-project-structure)
- [Screenshots](#-screenshots)
- [Roadmap](#-roadmap)
- [Skills Demonstrated](#-skills-demonstrated)
- [License](#-license)
- [Author](#-author)

## 💡 Why this project

Most "todo API" examples stop at CRUD. TaskForge shows what a backend actually needs before it can go to production: secure session handling with token rotation, authorization at the data layer, predictable errors, observability hooks, database migrations, and a CI pipeline that enforces quality. It's a template I'd be comfortable handing to a client as the foundation of a real product.

## 🏗 Architecture

```mermaid
flowchart LR
    Client([Client / Swagger UI / Postman]) -->|HTTPS + Bearer JWT| MW

    subgraph API["FastAPI application"]
        MW["Middleware<br/>Request ID · CORS · Error handling"] --> R["Routers<br/>/auth · /users · /tasks · /health"]
        R --> D["Dependencies<br/>auth context · rate limiter · services"]
        D --> S["Services<br/>AuthService · UserService · TaskService"]
        S --> Repo["Repositories<br/>User · AuthSession · Task"]
    end

    Repo -->|SQLAlchemy 2.0 async / asyncpg| PG[(PostgreSQL)]
    D -.->|optional| RD[(Redis<br/>rate limiting)]
    Alembic[[Alembic migrations]] --> PG
```

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for request lifecycles, the token-rotation design, ER diagram and design trade-offs.

## 🧩 Features

| Area | Capabilities |
|---|---|
| **Authentication** | Register, login, access + refresh tokens, refresh-token rotation with reuse detection, logout (current session or all devices) |
| **Users** | Get/update own profile, change password (requires current password), admin: list/search users, activate/deactivate, change role |
| **Tasks** | Create, read, partial update, delete; status (`todo`, `in_progress`, `done`, `cancelled`), priority (`low` → `urgent`), due dates, automatic `completed_at` |
| **Querying** | `page`/`page_size`, repeatable `status` & `priority` filters, `q` search, `due_before`/`due_after`, `sort=-priority,due_date` |
| **Authorization** | Owner-only access to tasks; admins may filter by `owner_id`; cross-user access returns `404` (no existence leaks) |
| **Security** | Argon2id, JWT `iss`/`aud`/`exp` validation, rate limits, CORS allow-list, production config guards |
| **Observability** | JSON logs, request IDs, liveness `/health`, readiness `/ready` (checks the database) |
| **Ops** | Alembic migrations, CLI for creating admins and seeding demo data, Docker, GitHub Actions |

## 🛠 Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Web framework | FastAPI, Uvicorn |
| Validation | Pydantic v2, pydantic-settings |
| Database | PostgreSQL, SQLAlchemy 2.0 (async), asyncpg |
| Migrations | Alembic |
| Auth | PyJWT, argon2-cffi |
| Rate limiting | Redis (optional) with in-memory fallback |
| Testing | Pytest, pytest-asyncio, HTTPX, pytest-cov |
| Quality | Ruff (lint + format), pip-audit |
| Packaging / tooling | uv, Docker, Docker Compose, GitHub Actions |

## 🚀 Quick Start

### Option A: Docker Compose (recommended)

```bash
git clone https://github.com/vks-eng/python-fastapi-backend.git
cd python-fastapi-backend
cp .env.example .env            # set JWT_SECRET_KEY (>= 32 chars) and POSTGRES_PASSWORD
docker compose up --build       # or: make up
```

The API is available at **http://localhost:8000**, and interactive docs at **http://localhost:8000/docs**.
Compose starts PostgreSQL 16 and Redis 7, runs `alembic upgrade head` in a one-shot `migrate` service, and only then starts the API (as a non-root user). Load demo data with `make seed-docker`.

### Option B: Local development

Requires Python 3.12+ and a running PostgreSQL instance.

```bash
# Path 1: uv (recommended, uses uv.lock)
uv sync                          # runtime + dev deps;  `uv sync --no-dev` for runtime only

# Path 2: pip (requirements*.txt are exported from uv.lock)
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt       # runtime only
pip install -r requirements-dev.txt   # runtime + test/lint tools

cp .env.example .env            # set DATABASE_URL and JWT_SECRET_KEY
alembic upgrade head
uvicorn app.main:app --reload
```

### Demo data (local only)

```bash
python -m app.cli seed
python -m app.cli create-admin --email you@example.com   # password read from ADMIN_PASSWORD or prompted
```

| Role | Email | Password |
|---|---|---|
| Admin | `admin@example.com` | `Admin-Demo-2026!` |
| User | `demo@example.com` | `Demo-User-2026!` |

> ⚠️ These demo credentials are for **local development only**. The `seed` command refuses to run when `ENVIRONMENT=production`.

### Postman

Import **[postman_collection.json](postman_collection.json)** (16 requests in Auth / Users / Tasks / System). Run **Auth → Register** and **Auth → Login** first (or set the `email`/`password` collection variables to the demo user). The collection stores the access/refresh tokens and the created task ID in collection variables automatically.

### Make targets

| Target | What it does |
|---|---|
| `make install` / `make dev` | `uv sync` runtime deps / runtime + dev deps and pre-commit hooks |
| `make lint` / `make format` | Ruff lint + format check (same as CI) / auto-fix and format |
| `make test` / `make cov` | Run tests / run tests with coverage (fails under 85%) |
| `make migrate` / `make revision MSG="..."` | `alembic upgrade head` / autogenerate a new migration |
| `make run` | Local dev server with auto-reload |
| `make up` / `make down` / `make logs` | Docker Compose stack: start (build + migrate) / stop / tail API logs |
| `make seed` / `make seed-docker` | Load demo users and tasks locally / inside the Compose stack |
| `make requirements` | Re-export `requirements*.txt` from `uv.lock` |
| `make clean` | Remove caches and coverage artefacts |

## ⚙️ Configuration

All settings come from environment variables (or `.env`). See [`.env.example`](.env.example).

| Variable | Default | Description |
|---|---|---|
| `ENVIRONMENT` | `development` | `development`, `test`, `staging` or `production` |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/taskdb` | PostgreSQL URL (`postgres://` is normalised to asyncpg) |
| `JWT_SECRET_KEY` | **required** | HMAC signing secret, minimum 32 characters |
| `JWT_ALGORITHM` | `HS256` | `HS256`, `HS384` or `HS512` |
| `JWT_ISSUER` / `JWT_AUDIENCE` | `taskforge-api` | Validated on every token |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `14` | Refresh token lifetime |
| `REQUIRE_ACCOUNT_ACTIVATION` | `false` | New accounts stay inactive until an admin activates them |
| `CORS_ORIGINS` | *(empty)* | Comma-separated or JSON list. Wildcard is rejected in production |
| `CORS_ALLOW_CREDENTIALS` | `false` | Cannot be combined with a wildcard origin |
| `REDIS_URL` | *(unset)* | Optional. Enables shared rate limiting across instances |
| `RATE_LIMIT_ENABLED` | `true` | Toggle rate limiting |
| `LOGIN_RATE_LIMIT` / `_WINDOW_SECONDS` | `5` / `60` | Login attempts per IP per window |
| `REGISTER_RATE_LIMIT` / `_WINDOW_SECONDS` | `10` / `3600` | Registrations per IP per window |
| `REFRESH_RATE_LIMIT` / `_WINDOW_SECONDS` | `30` / `60` | Refreshes per IP per window |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `10` | Connection pool sizing |
| `DB_POOL_TIMEOUT` / `DB_POOL_RECYCLE` | `30` / `1800` | Pool timeout (s) / connection recycle (s) |
| `DB_STATEMENT_TIMEOUT_MS` | `15000` | Server-side statement timeout |
| `DOCS_ENABLED` | `true` | Serve Swagger UI / ReDoc |
| `MAX_REQUEST_BODY_BYTES` | `1048576` | Larger request bodies are rejected with `413 payload_too_large` |
| `DB_ECHO` | `false` | Log every SQL statement (debugging only) |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `true` | Logging verbosity / JSON output (`false` = human-readable) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `taskforge` / **required** / `taskforge` | Docker Compose only: database container credentials, also used to build the API's `DATABASE_URL` |
| `API_PORT` | `8000` | Docker Compose only: host port for the API |
| `WEB_CONCURRENCY` | `1` (`.env.example`: `2`) | Uvicorn worker processes in the container |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxy IPs trusted for `X-Forwarded-For` (affects the client IP used for rate limiting) |
| `ADMIN_PASSWORD` | *(unset)* | Read by `python -m app.cli create-admin`; prompted for if unset |

## 🗄 Database & Migrations

```bash
alembic upgrade head                                   # apply all migrations
alembic revision --autogenerate -m "add task labels"   # create a new migration
alembic downgrade -1                                   # roll back one revision
alembic history                                        # list revisions
```

Schema: `users`, `auth_sessions`, `refresh_tokens`, `tasks`, with foreign keys, `ON DELETE CASCADE`, a check constraint and composite indexes tuned for the owner-scoped queries.
A generated reference DDL is in **[database_schema.sql](database_schema.sql)**. Alembic remains the source of truth.

## 📡 API Reference

Interactive documentation: **Swagger UI** at `/docs`, **ReDoc** at `/redoc`, OpenAPI JSON at `/openapi.json`. Full reference with request/response examples and error codes: **[docs/API.md](docs/API.md)**.

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/v1/auth/register` | — | Register a new account (rate-limited) |
| `POST` | `/api/v1/auth/login` | — | Get an access + refresh token pair (rate-limited) |
| `POST` | `/api/v1/auth/refresh` | — | Rotate the refresh token (reuse revokes the session) |
| `POST` | `/api/v1/auth/logout` | Bearer | Revoke the current session (`?all_sessions=true` for every device) |
| `GET` | `/api/v1/users/me` | Bearer | Current user's profile |
| `PATCH` | `/api/v1/users/me` | Bearer | Update profile / change password |
| `GET` | `/api/v1/users` | Admin | List and search users |
| `GET` | `/api/v1/users/{user_id}` | Admin | Get a user |
| `PATCH` | `/api/v1/users/{user_id}` | Admin | Activate/deactivate or change role |
| `POST` | `/api/v1/tasks` | Bearer | Create a task |
| `GET` | `/api/v1/tasks` | Bearer | List tasks (pagination, filters, sort, search) |
| `GET` | `/api/v1/tasks/{task_id}` | Bearer | Get a task |
| `PATCH` | `/api/v1/tasks/{task_id}` | Bearer | Partially update a task |
| `DELETE` | `/api/v1/tasks/{task_id}` | Bearer | Delete a task |
| `GET` | `/health` | — | Liveness probe |
| `GET` | `/ready` | — | Readiness probe (checks PostgreSQL) |

### Examples

```bash
# Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@example.com","password":"Str0ng-Passw0rd!","full_name":"Jane Doe"}'

# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@example.com","password":"Str0ng-Passw0rd!"}'
# → {"access_token":"…","refresh_token":"…","token_type":"bearer","expires_in":900,"refresh_expires_in":1209600}

TOKEN="<access_token>"

# Create a task
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"Ship v1","priority":"high","due_date":"2026-12-01T17:00:00Z"}'

# List: high/urgent open tasks, most urgent first
curl "http://localhost:8000/api/v1/tasks?status=todo&status=in_progress&priority=high&priority=urgent&sort=-priority,due_date&page=1&page_size=20" \
  -H "Authorization: Bearer $TOKEN"

# Rotate tokens
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" -d '{"refresh_token":"<refresh_token>"}'
```

### Response shapes

```jsonc
// Paginated list
{ "items": [ { "id": "…", "title": "Ship v1", "status": "todo", "priority": "high", … } ],
  "meta":  { "page": 1, "page_size": 20, "total": 1, "pages": 1 } }

// Error envelope (every 4xx/5xx)
{ "error": { "code": "validation_error", "message": "Request validation failed",
             "details": [ { "field": "title", "location": "body", "message": "Field required", "type": "missing" } ],
             "request_id": "b3c1…" } }
```

## 🧪 Testing

Tests run against a **real PostgreSQL** database. No SQLite shortcuts.

```bash
# Locally: an embedded throwaway PostgreSQL (pgserver) is started automatically
uv run pytest --cov --cov-report=term-missing      # or: make cov

# Against your own database (used by CI)
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/taskforge_test uv run pytest

# Lint & format
uv run ruff check . && uv run ruff format --check .
```

The test suite covers registration, login, token expiry, refresh rotation and reuse detection, logout, profile updates, task CRUD, pagination, filtering, sorting, validation, admin authorization, cross-user access prevention, error handling, health/readiness and the CLI.

| Metric | Result |
|---|---|
| Tests | **119 passed** (about 40 s, real PostgreSQL 16) |
| Coverage | **96%** line + branch (CI gate: ≥ 85%) |
| Lint | `ruff check` + `ruff format --check`: clean |
| Dependencies | `pip-audit`: no known vulnerabilities at time of writing |

Each test runs inside a transaction that is rolled back afterwards (the services' commits become SAVEPOINTs), and the schema is built by running the real Alembic migrations (upgrade → downgrade → upgrade) once per test session.

## ☁️ Deployment

1. Build the image: `docker build -t taskforge-api .`
2. Provide `DATABASE_URL`, `JWT_SECRET_KEY` and `ENVIRONMENT=production` through your platform's secret manager (AWS Secrets Manager / SSM, Azure Key Vault, GitHub Environments…).
3. Run `alembic upgrade head` as a one-off release task before rolling out new containers (Compose does this with its `migrate` service).
4. Point load-balancer health checks at `/health` (liveness) and `/ready` (readiness).
5. Set `REDIS_URL` when running more than one replica so rate limits are shared.
6. Restrict `CORS_ORIGINS` to your front-end domains and consider `DOCS_ENABLED=false`.

Works on any container platform: AWS ECS/Fargate + RDS, Azure Container Apps, Google Cloud Run + Cloud SQL, Render, Fly.io or a plain VM with Docker Compose. Step-by-step guides and a production checklist: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

## 🔐 Security Considerations

- Passwords are hashed with **Argon2id**. Plain-text passwords are never stored or logged.
- Refresh tokens are random opaque values stored only as **SHA-256 hashes**. Each one is single-use. Reusing a rotated token revokes the entire session family.
- Access tokens are short-lived and validated for signature, `exp`, `iss`, `aud` and that the session is still active.
- Task access is enforced in the service and repository layers. Requests for another user's task return **404**, so the API doesn't reveal that the task exists.
- Rate limiting on authentication endpoints mitigates credential stuffing and brute force.
- Secrets come only from the environment. The JWT secret length is enforced at startup.
- Production guards reject wildcard CORS and credentials-with-wildcard combinations.
- Unhandled exceptions return a generic error with a `request_id`. Details go to the logs, not the client. Database outages return `503` with `Retry-After`.
- Request bodies reject unknown fields (`extra="forbid"`), which blocks mass assignment such as sending `role` or `owner_id`.
- Security headers (`nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`) on every response; the container runs as a non-root user.
- CI runs `pip-audit`; CodeQL and Dependabot watch the code and dependencies.

See [SECURITY.md](SECURITY.md) for how to report a vulnerability.

## 📁 Project Structure

```text
python-fastapi-backend/
├── app/
│   ├── api/              # routers (v1: auth, users, tasks) + health, dependencies
│   ├── core/             # config, security (JWT/Argon2), logging, rate limiting, exceptions
│   ├── db/               # declarative base, async engine & session management
│   ├── middleware/       # request-ID / request-context middleware
│   ├── models/           # SQLAlchemy models: User, AuthSession, RefreshToken, Task
│   ├── repositories/     # data access, query building, pagination
│   ├── schemas/          # Pydantic request/response models, error envelope
│   ├── services/         # business logic: auth, users, tasks
│   ├── cli.py            # create-admin, seed
│   └── main.py           # app factory
├── alembic/              # migration environment + versions
├── tests/                # pytest suite (auth, users, tasks, health, cli, unit)
├── docs/                 # API.md, DEPLOYMENT.md, screenshots/
├── .github/              # CI + CodeQL workflows, Dependabot, CODEOWNERS, issue/PR templates
├── Dockerfile · docker-compose.yml · Makefile · .env.example
├── alembic.ini
├── database_schema.sql   # generated reference DDL
├── postman_collection.json
├── pyproject.toml / uv.lock
├── requirements.txt / requirements-dev.txt
├── ARCHITECTURE.md · PROJECT_SUMMARY.md · CHANGELOG.md
├── SECURITY.md · CONTRIBUTING.md · CODE_OF_CONDUCT.md
└── LICENSE
```

## 🖼 Screenshots

| Swagger UI | Example request |
|---|---|
| ![Swagger UI](docs/screenshots/swagger-ui.png) | ![Postman](docs/screenshots/postman-login.png) |

> Screenshots live in [`docs/screenshots/`](docs/screenshots/); see [its README](docs/screenshots/README.md) for the capture list.

## 🗺 Roadmap

- [ ] Email verification and password-reset flow
- [ ] Task labels, comments and attachments
- [ ] Team workspaces with shared tasks
- [ ] OpenTelemetry tracing and Prometheus metrics
- [ ] Background reminders for upcoming due dates
- [ ] Cursor-based pagination for very large datasets

## 🎯 Skills Demonstrated

`FastAPI` · `Async Python` · `SQLAlchemy 2.0` · `PostgreSQL` · `Alembic` · `JWT auth & token rotation` · `Argon2` · `RBAC` · `REST API design` · `Clean Architecture` · `Pytest` · `Docker` · `GitHub Actions CI/CD` · `Secure coding (OWASP API Top 10)` · `Observability`

## 📄 License

Released under the [MIT License](LICENSE).

## 👤 Author

**Built by vks-eng · GitHub: https://github.com/vks-eng**

Python backend, cloud & DevSecOps engineer.
Available for freelance work. Check my GitHub profile for more projects and contact links.
