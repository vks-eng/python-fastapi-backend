# TaskForge API: API Reference

Base URL (local): `http://localhost:8000`. Versioned endpoints live under `/api/v1`.
The live OpenAPI schema is served at `/openapi.json`, with Swagger UI at `/docs` and ReDoc at
`/redoc` (disable them with `DOCS_ENABLED=false`).

- [Conventions](#conventions)
- [Auth](#auth): register, login, refresh, logout
- [Users](#users): me, update me, admin list/get/update
- [Tasks](#tasks): create, list, get, update, delete
- [System](#system): health, ready
- [Error codes](#error-codes)

## Conventions

| Topic | Rule |
|---|---|
| Content type | JSON request and response bodies (`Content-Type: application/json`) |
| Authentication | `Authorization: Bearer <access_token>` from `/auth/login` or `/auth/refresh` |
| IDs | UUIDv4 strings. A malformed id in the path gives `422` |
| Timestamps | ISO-8601. Inputs (`due_date`, `due_before`, `due_after`) **must include a timezone offset** (`Z` or `+02:00`); outputs are UTC |
| Unknown fields | Request bodies reject unknown fields with `422` (blocks mass assignment of `role`, `owner_id`, ...) |
| Request IDs | Send `X-Request-ID` (`[A-Za-z0-9._-]{1,128}`) to correlate logs, otherwise one is generated. It is returned on every response |
| Pagination | `page` (>= 1, default 1), `page_size` (1-100, default 20). Lists return `{"items": [...], "meta": {...}}` |

Paginated response shape:

```json
{
  "items": [],
  "meta": { "page": 1, "page_size": 20, "total": 0, "pages": 0 }
}
```

Error response shape (every 4xx/5xx):

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "details": [
      { "field": "title", "location": "body", "message": "String should have at least 1 character", "type": "string_too_short" }
    ],
    "request_id": "d888ab0ffce944ef85008ff42f9774ab"
  }
}
```

`details` is `null` except for validation errors. Every response also carries the
`X-Content-Type-Options`, `X-Frame-Options` and `Referrer-Policy` security headers.

---

## Auth

### `POST /api/v1/auth/register`

Create an account. No authentication. Rate limited per client IP
(`REGISTER_RATE_LIMIT` per `REGISTER_RATE_LIMIT_WINDOW_SECONDS`, default 10/hour).

Request:

```json
{ "email": "Jane.Doe@example.com", "password": "Str0ng-Passw0rd!", "full_name": "Jane Doe" }
```

| Field | Rules |
|---|---|
| `email` | Valid e-mail; stored lower-cased; must be unique (case-insensitive) |
| `password` | 8-128 characters, at least one letter and one digit, no leading/trailing whitespace |
| `full_name` | Optional, 1-200 characters after trimming |

Response `201 Created`:

```json
{
  "id": "0327a58f-3a44-4c2a-b9e3-9582b3ee75c3",
  "email": "jane.doe@example.com",
  "full_name": "Jane Doe",
  "role": "user",
  "is_active": true,
  "created_at": "2026-11-10T09:00:00.123456Z",
  "updated_at": "2026-11-10T09:00:00.123456Z",
  "last_login_at": null
}
```

`is_active` is `false` when `REQUIRE_ACCOUNT_ACTIVATION=true` (an admin must activate the account).

Errors: `409 email_taken`, `422 validation_error`, `429 rate_limited`.

### `POST /api/v1/auth/login`

Exchange credentials for tokens. No authentication. Rate limited per client IP
(default 5 attempts/minute).

Request:

```json
{ "email": "jane.doe@example.com", "password": "Str0ng-Passw0rd!" }
```

Response `200 OK`:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "kH3c...64-character opaque value...",
  "token_type": "bearer",
  "expires_in": 900,
  "refresh_expires_in": 1209600
}
```

The access token is a JWT carrying `sub` (user id), `sid` (session id), `role`, `jti`,
`iss`, `aud`, `iat`, `nbf` and `exp`. The refresh token is opaque; only its SHA-256 hash is stored.

Errors: `401 invalid_credentials` (same response for unknown e-mail and wrong password),
`403 account_inactive`, `422 validation_error`, `429 rate_limited`.

### `POST /api/v1/auth/refresh`

Rotate a refresh token. No access token needed. Rate limited per IP (default 30/minute).

Request:

```json
{ "refresh_token": "kH3c..." }
```

Response `200 OK`: a new token pair (same shape as login). The presented refresh token is
now **used** and must not be sent again.

Errors:

| Status | `code` | Meaning |
|---|---|---|
| 401 | `invalid_refresh_token` | Unknown token |
| 401 | `refresh_token_reused` | Token was already rotated: treated as theft, **the whole session is revoked** (all its refresh and access tokens) |
| 401 | `session_revoked` | The session was logged out or revoked |
| 401 | `refresh_token_expired` | Older than `REFRESH_TOKEN_EXPIRE_DAYS` |
| 403 | `account_inactive` | The user was deactivated |
| 422 | `validation_error` | Missing or malformed token (16-256 characters) |
| 429 | `rate_limited` | Too many refreshes from this IP |

### `POST /api/v1/auth/logout`

Revoke the caller's session. Requires a Bearer token.

| Query | Default | Description |
|---|---|---|
| `all_sessions` | `false` | `true` revokes every session of the user (all devices) |

Response: `204 No Content`. The session's access tokens fail immediately with
`401 session_revoked`, and its refresh tokens can no longer be used.

Errors: `401` (missing/invalid token).

---

## Users

### `GET /api/v1/users/me`

Returns the caller's profile (same shape as the register response). Errors: `401`, `403 account_inactive`.

### `PATCH /api/v1/users/me`

Partial update of the caller's profile. At least one field is required.

```json
{ "full_name": "Jane Q. Doe", "email": "jane.q@example.com" }
```

Change the password (all *other* sessions are revoked; the current one stays valid):

```json
{ "current_password": "Str0ng-Passw0rd!", "new_password": "N3w-Passw0rd!" }
```

Response `200 OK`: the updated profile.

Errors: `400 invalid_password` (wrong `current_password`), `409 email_taken`,
`422 validation_error` (empty body, `email: null`, `new_password` without
`current_password`, unknown fields such as `role`).

### `GET /api/v1/users` (admin)

List users. Query: `page`, `page_size`, `role` (`user`|`admin`), `is_active` (`true`|`false`),
`q` (1-100 chars, case-insensitive search in e-mail and full name). Sorted newest first.

Response `200 OK`: paginated list of user profiles. Errors: `401`, `403 permission_denied`, `422`.

### `GET /api/v1/users/{user_id}` (admin)

Response `200 OK`: a user profile. Errors: `401`, `403 permission_denied`, `404 not_found`, `422`.

### `PATCH /api/v1/users/{user_id}` (admin)

Activate/deactivate an account, change its role or name. At least one field.

```json
{ "is_active": false }
```

```json
{ "role": "admin", "full_name": "Ops Lead" }
```

Deactivating a user revokes all of their sessions. Admins cannot deactivate or demote
themselves.

Response `200 OK`: the updated profile. Errors: `400 self_modification`, `401`,
`403 permission_denied`, `404 not_found`, `422 validation_error` (`null` values, unknown role).

---

## Tasks

Non-admins can only see and change **their own** tasks; another user's task id returns
`404 task_not_found` (existence is never confirmed). Admins can access every task.

Task object:

```json
{
  "id": "08f1bab7-fbc3-4dee-a479-91beae40f90c",
  "owner_id": "0327a58f-3a44-4c2a-b9e3-9582b3ee75c3",
  "title": "Prepare client demo",
  "description": "Slides + live API walkthrough",
  "status": "todo",
  "priority": "high",
  "due_date": "2030-01-15T17:00:00Z",
  "completed_at": null,
  "created_at": "2026-11-10T09:05:00.000000Z",
  "updated_at": "2026-11-10T09:05:00.000000Z"
}
```

| Field | Values / rules |
|---|---|
| `title` | Required, 1-200 characters after trimming |
| `description` | Optional, up to 5000 characters, `null` clears it |
| `status` | `todo` (default), `in_progress`, `done`, `cancelled`. Setting `done` stamps `completed_at`; leaving `done` clears it |
| `priority` | `low`, `medium` (default), `high`, `urgent` (sorted in this order) |
| `due_date` | Optional timezone-aware timestamp, `null` clears it |

### `POST /api/v1/tasks`

```json
{
  "title": "Prepare client demo",
  "description": "Slides + live API walkthrough",
  "status": "todo",
  "priority": "high",
  "due_date": "2030-01-15T17:00:00Z"
}
```

Response `201 Created`: the task (owned by the caller). Errors: `401`, `422 validation_error`
(empty/too long title, unknown enum value, naive datetime, unknown fields such as `owner_id`).

### `GET /api/v1/tasks`

| Query | Description |
|---|---|
| `page`, `page_size` | Pagination (1-10000, 1-100) |
| `status` | Repeatable: `?status=todo&status=in_progress` |
| `priority` | Repeatable: `?priority=high&priority=urgent` |
| `q` | Case-insensitive search in title and description (1-100 chars; `%` and `_` are literal) |
| `due_after` / `due_before` | Inclusive lower / exclusive upper bound on `due_date` (timezone required) |
| `owner_id` | Admin only. A non-admin may pass only their own id (others get `403`) |
| `sort` | Up to 3 comma-separated fields, `-` prefix for descending. Fields: `created_at`, `updated_at`, `due_date`, `priority`, `status`, `title`. Default `-created_at`. `NULL` due dates sort last |

Example:

```bash
curl "http://localhost:8000/api/v1/tasks?status=todo&priority=high&priority=urgent&sort=-priority,due_date&page_size=2" \
  -H "Authorization: Bearer $TOKEN"
```

Response `200 OK`: paginated tasks.

Errors: `400 validation_error` (bad `sort`, or `due_after` later than `due_before`;
`details[0].field` names the parameter), `401`, `403 permission_denied` (foreign `owner_id`),
`422 validation_error` (bad page values, enum values, dates, UUIDs).

### `GET /api/v1/tasks/{task_id}`

Response `200 OK`: the task. Errors: `401`, `404 task_not_found`, `422` (malformed id).

### `PATCH /api/v1/tasks/{task_id}`

Partial update; only provided fields change. `title`, `status` and `priority` cannot be `null`.

```json
{ "status": "done", "priority": "urgent" }
```

Response `200 OK`: the updated task. Errors: `401`, `404 task_not_found`, `422 validation_error`
(empty body, `null` for non-nullable fields, unknown fields).

### `DELETE /api/v1/tasks/{task_id}`

Response `204 No Content`. Errors: `401`, `404 task_not_found`, `422`.

---

## System

### `GET /health`

Liveness probe, no dependencies checked, no auth.

```json
{ "status": "ok", "version": "1.0.0" }
```

### `GET /ready`

Readiness probe: runs `SELECT 1` against PostgreSQL with a 3-second timeout.

`200 OK`:

```json
{ "status": "ready", "checks": { "database": "ok" } }
```

`503 Service Unavailable`:

```json
{ "status": "not_ready", "checks": { "database": "unavailable" } }
```

---

## Error codes

| Status | `code` | Raised when |
|---|---|---|
| 400 | `invalid_password` | `current_password` is wrong on password change |
| 400 | `self_modification` | An admin tries to deactivate or demote themselves |
| 400 | `validation_error` | Invalid `sort` or date range on `GET /tasks` |
| 401 | `not_authenticated` | No/non-Bearer `Authorization` header |
| 401 | `invalid_token` | Bad signature, wrong `iss`/`aud`/type, missing claims, unknown session |
| 401 | `token_expired` | Access token past `exp` |
| 401 | `session_revoked` | Session logged out, revoked by reuse detection, password change or deactivation |
| 401 | `invalid_credentials` | Wrong e-mail or password |
| 401 | `invalid_refresh_token` / `refresh_token_expired` / `refresh_token_reused` | See [refresh](#post-apiv1authrefresh) |
| 403 | `permission_denied` | Admin-only endpoint, or foreign `owner_id` filter |
| 403 | `account_inactive` | Account deactivated or awaiting activation |
| 404 | `not_found` / `task_not_found` | Unknown route or user / unknown or foreign task |
| 405 | `method_not_allowed` | Wrong HTTP method |
| 409 | `email_taken` | E-mail already registered |
| 422 | `validation_error` | Body, query or path validation failed (`details` lists each problem) |
| 429 | `rate_limited` | Rate limit hit; see the `Retry-After` header |
| 500 | `internal_error` | Unexpected error; details only in server logs (search by `request_id`) |
| 503 | `service_unavailable` | Database unreachable; retry after `Retry-After` seconds |

All `401` responses include `WWW-Authenticate: Bearer`.
