# Screenshots

Real captures from a local run of TaskForge: an embedded PostgreSQL, `alembic upgrade head`,
`python -m app.cli seed`, and uvicorn, driven through the built-in Swagger UI with Playwright
(Microsoft Edge, headless, 1440 px wide). The tokens visible in them came from a throwaway local
server whose secret and database were discarded afterwards.

| File | Shows |
|---|---|
| `swagger-ui.png` | `/docs`: the generated OpenAPI documentation |
| `swagger-login.png` | `POST /api/v1/auth/login` with the seeded demo user → `200` with an access/refresh token pair |
| `tasks-filtered.png` | `GET /api/v1/tasks?page_size=5&sort=-priority,due_date` (authorized) → `200` with `items` + `meta` |
| `refresh-reuse.png` | Replaying an already-rotated refresh token → `401 refresh_token_reused` (session revoked) |

To recapture, start the stack (`docker compose up`, then `docker compose exec api python -m app.cli seed`),
open http://localhost:8000/docs and repeat the requests above with the demo account `demo@example.com`.
