# Contributing to TaskForge API

Thanks for your interest in improving TaskForge API! 🎉

## Getting Started

1. Fork the repository and clone your fork.
2. Follow the **Quick Start** section in [README.md](README.md) to set up the project locally.
3. Create a branch from `main`:
   ```bash
   git checkout -b feat/short-description
   ```

## Development Workflow

- **Code style:** Python is linted and formatted with [Ruff](https://docs.astral.sh/ruff/).
  Run `ruff check .` and `ruff format .` before committing.
- **Tests:** add or update tests for every change and make sure the full suite passes.
- **Migrations:** schema changes require an Alembic migration
  (`alembic revision --autogenerate -m "describe change"`) — review the generated file before committing.
- **Secrets:** never commit credentials, tokens or `.env` files.

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add task due-date reminders
fix: reject expired refresh tokens
docs: clarify docker setup
```

## Pull Requests

- Keep PRs focused on a single change.
- Fill in the pull request template.
- Make sure CI is green (lint, tests, security checks).
- Link any related issue (e.g. `Closes #12`).

## Reporting Bugs & Requesting Features

Use the [issue templates](https://github.com/vks-eng/python-fastapi-backend/issues/new/choose).
For security issues, follow [SECURITY.md](SECURITY.md) instead.
