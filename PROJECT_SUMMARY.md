# TaskForge API: Project Summary

> **Production-ready FastAPI backend** · Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · PostgreSQL · Docker · GitHub Actions
> Repository: https://github.com/vks-eng/python-fastapi-backend

## The problem

Many API projects work in a demo but are not ready for real users. Sessions can't be revoked, stolen refresh tokens stay valid, users can read each other's data by guessing IDs, errors leak stack traces, and nobody can trace a failing request in the logs. Fixing these after launch is expensive.

## The solution

TaskForge is a task-management REST API built the way a production backend should be from the start. It has secure, revocable authentication, data-level authorization, predictable errors, observability hooks, versioned database migrations, and an automated quality pipeline. The domain is simple (tasks) on purpose, so the engineering is easy to see.

## Key features

- **Authentication:** register, login, logout (single device or all devices), JWT access tokens, and **refresh-token rotation with reuse detection**. A replayed token revokes the whole session.
- **Security:** Argon2id password hashing, hashed refresh tokens, rate limiting on auth endpoints, CORS allow-list, production configuration guards.
- **RBAC:** users manage only their own tasks. Admins manage users (activate, deactivate, change role) and can view all tasks.
- **Task management:** CRUD with status, priority, due dates and automatic completion timestamps.
- **Rich querying:** pagination, repeatable filters, multi-field sorting, case-insensitive search, date ranges.
- **Operations:** JSON structured logs, request IDs, health/readiness probes, Alembic migrations, CLI for creating admins and seeding demo data, Docker.

## Technology

| | |
|---|---|
| **Backend** | Python 3.12, FastAPI, Pydantic v2, Uvicorn |
| **Data** | PostgreSQL, SQLAlchemy 2.0 async ORM, asyncpg, Alembic |
| **Security** | PyJWT, Argon2 (argon2-cffi), Redis-backed rate limiting (optional) |
| **Quality** | Pytest, HTTPX, pytest-cov, Ruff, pip-audit |
| **Delivery** | Docker (multi-stage, non-root), Docker Compose, GitHub Actions |

## Engineering practices

- **Clean architecture:** routers → services → repositories → models. No business logic in route handlers.
- **Tested against real PostgreSQL**, not SQLite, so enum, timezone and constraint behaviour matches production.
- **Security by default:** cross-user access returns 404, secrets come only from the environment, and errors are uniform with request IDs.
- **CI on every push:** lint and format checks, the test suite with a coverage gate, a migration drift check (`alembic check`), a dependency vulnerability audit (`pip-audit`), a Docker build smoke test, plus CodeQL and Dependabot.
- **Documented:** README, architecture guide with diagrams, API reference, deployment guide, generated schema reference, and a Postman collection.

## By the numbers

| | |
|---|---|
| REST endpoints | 16 (auth 4, users 5, tasks 5, system 2) |
| Database tables | 4, with foreign keys, enums, check constraint and 6 indexes |
| Automated tests | 365 (131 unit · 228 integration · 3 end-to-end · 3 contract), all passing against real PostgreSQL 16 |
| Test coverage | 97.6% line + branch (CI gate ≥ 85%) |

## What this demonstrates for a client

If you need a **new API, a backend for a web or mobile app, or an existing FastAPI service hardened for production**, this project shows how I work. I deliver secure authentication, clean and maintainable code, real tests, migrations, Docker, CI/CD, and documentation your team can pick up on day one.

---

### Upwork portfolio blurb

> **TaskForge API: Production-Ready FastAPI Backend.** An async REST API built with FastAPI, SQLAlchemy 2.0 and PostgreSQL, featuring JWT authentication with refresh-token rotation and reuse detection, Argon2 password hashing, role-based access control, rate limiting and structured logging. Delivered with Alembic migrations, Docker, a pytest suite running on real PostgreSQL, and a GitHub Actions CI pipeline.

### GitHub repo settings

- **Description:** Production-ready async Task Management REST API with FastAPI, SQLAlchemy 2.0 & PostgreSQL. JWT auth with refresh-token rotation, Argon2, RBAC, rate limiting, Alembic, Docker and CI.
- **Topics:** `fastapi` `python` `postgresql` `sqlalchemy` `alembic` `jwt-authentication` `rest-api` `docker` `pytest` `clean-architecture` `github-actions` `backend`
