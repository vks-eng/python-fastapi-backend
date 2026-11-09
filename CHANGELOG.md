# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-11-10

### Added

- **Authentication**: registration, login, JWT access tokens (HS256, `iss`/`aud`/`exp`/`nbf`
  validated), opaque refresh tokens stored as SHA-256 hashes, refresh-token rotation with
  reuse detection (replaying a rotated token revokes the whole session), logout of the
  current session or all sessions.
- **Passwords**: Argon2id hashing with transparent rehash on login, strength validation,
  password change that requires the current password and revokes other sessions.
- **Users**: `GET/PATCH /api/v1/users/me`; admin-only list/search, get, activate/deactivate
  and role change (`/api/v1/users`, `/api/v1/users/{user_id}`); optional admin-gated account
  activation (`REQUIRE_ACCOUNT_ACTIVATION`).
- **Tasks**: CRUD with status, priority, due dates and automatic `completed_at`; owner-only
  access (404 for other users' tasks); admins can see and manage all tasks.
- **Querying**: offset pagination with `meta`, repeatable `status`/`priority` filters,
  `due_before`/`due_after`, case-insensitive search with escaped wildcards, multi-field
  sorting with a deterministic tiebreaker.
- **Security**: per-IP rate limiting on register/login/refresh (Redis with in-memory
  fallback), CORS allow-list, production configuration guards, security headers,
  mass-assignment protection (`extra="forbid"`), uniform error envelope without stack traces,
  `503` for database outages.
- **Observability**: JSON structured logs, `X-Request-ID` propagation, access logs,
  `/health` liveness and `/ready` readiness (database check) probes.
- **Database**: PostgreSQL schema with enums, foreign keys (`ON DELETE CASCADE`), check
  constraint and composite indexes; async Alembic environment and initial migration `0001`.
- **Tooling**: management CLI (`create-admin`, `seed`), multi-stage non-root Dockerfile,
  Docker Compose (API + PostgreSQL + Redis + migration job), Makefile, pre-commit hooks.
- **Quality**: 119 pytest tests against real PostgreSQL (96% coverage), Ruff lint/format,
  GitHub Actions CI (lint, tests + coverage gate, migration drift check, pip-audit, Docker
  build), CodeQL, Dependabot.
- **Docs**: README, ARCHITECTURE, PROJECT_SUMMARY, API reference, deployment guide,
  Postman collection, generated schema reference.

[Unreleased]: https://github.com/vks-eng/python-fastapi-backend/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/vks-eng/python-fastapi-backend/releases/tag/v1.0.0
