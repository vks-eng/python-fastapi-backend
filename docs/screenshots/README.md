# Screenshots

This folder holds the images referenced from the main [README](../README.md). They are
not checked in yet. Capture them from a local stack (`make up && make seed-docker`) and
save them here with **exactly** these filenames:

| File | What to capture | Referenced from |
|---|---|---|
| `swagger-ui.png` | `http://localhost:8000/docs` with the Auth, Users, Tasks and Health groups visible (ideally after clicking **Authorize**) | README → Screenshots |
| `postman-login.png` | Postman with **Auth → Login** sent: the 200 response with `access_token`/`refresh_token` and the passing test results | README → Screenshots |

Optional extras (not referenced yet; add them to the README table if you capture them):

| File | What to capture |
|---|---|
| `tasks-filtered.png` | `GET /api/v1/tasks?status=todo&sort=-priority,due_date` response showing `items` and `meta` |
| `refresh-reuse.png` | Replaying an old refresh token: `401 refresh_token_reused` |
| `json-logs.png` | `docker compose logs api` showing JSON log lines with `request_id` |
| `ci-green.png` | The GitHub Actions run with lint, tests, audit and Docker build passing |

Guidelines: PNG, about 1400 px wide, light theme, no real e-mail addresses or tokens
(use the seeded demo accounts; tokens expire after 15 minutes anyway).
