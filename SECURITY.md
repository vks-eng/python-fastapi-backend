# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x     | ✅        |
| < 1.0   | ❌        |

## Reporting a Vulnerability

Please **do not open a public issue** for security vulnerabilities.

Report them privately through GitHub's
[private vulnerability reporting](https://github.com/vks-eng/python-fastapi-backend/security/advisories/new)
(Security tab → *Report a vulnerability*).

Please include:

- A description of the vulnerability and its impact
- Steps to reproduce (proof-of-concept if possible)
- Affected version / commit
- Any suggested fix

You can expect an acknowledgement within **3 business days** and a status update
within **7 days**. Once a fix is released you will be credited in the changelog
unless you prefer to remain anonymous.

## Security Practices in TaskForge API

- Secrets are loaded from environment variables only — never committed. See `.env.example`.
- Passwords and credentials are hashed or encrypted at rest and never returned by the API or written to logs.
- Dependencies are audited in CI (`pip-audit`) and kept up to date with Dependabot.
- Static analysis (Ruff, CodeQL) runs on every pull request.
