# Security Policy

## Supported versions

Only the latest release receives security fixes. The project is complete and maintained on a
best-effort basis by a single person; there is no support commitment or response time.

| Version | Supported |
|---|---|
| Latest `1.x` release | Yes |
| Older releases | No |

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Use GitHub's private reporting: open the repository's **Security** tab and choose **Report a
vulnerability**. Include what you found, how to reproduce it, and the version or commit.

Please do not include real credentials, tokens or personal data in a report. If you find a secret
that was committed by mistake, say where it is and do not use it.

## Scope

In scope: the code in this repository (API, worker, frontend, scripts, workflows) and its
dependencies.

The application stores no personal data other than account emails and Argon2id password hashes.
AIS positions are public broadcasts; the repository never publishes them as live data to anonymous
visitors (ADR-0008, ADR-0020).

Out of scope: the AISStream service, the map tile providers, GitHub itself, and the static demo
(it has no backend and uses simulated data).

## What is already covered

- Authentication with short-lived access tokens and rotating refresh tokens, with reuse detection.
  Passwords are hashed with Argon2id.
- Deny-by-default endpoints, validated input, parameterised SQL, CORS with explicit origins, request
  size limits and rate limiting.
- A strict Content Security Policy in the frontend and a lint rule that forbids inserting HTML.
- Secret scanning with push protection, `gitleaks` in pre-commit and CI, and dependency audits
  (`pip-audit`, `npm audit`) in CI.

The reasoning and the results of the last full review are in
[`docs/SECURITY_REVIEW.md`](docs/SECURITY_REVIEW.md). The conventions are in
[`AGENTS.md`](AGENTS.md) section 8.

## Known limits

The project is delivered without a production environment (ADR-0017). A public deployment would
need a TLS reverse proxy, HSTS, per-IP limits, blocking `/metrics` from outside, and a repeat of the
review against the live environment. These are listed in `docs/SECURITY_REVIEW.md`.

---

## Política de seguridad (resumen en español)

Solo la última versión `1.x` recibe correcciones, sin plazos de respuesta: es un proyecto personal.
Para informar de una vulnerabilidad no abras un issue público: usa la pestaña **Security** del
repositorio y **Report a vulnerability**. No incluyas credenciales ni datos personales. El alcance, lo
que ya cubre el proyecto y sus límites conocidos están arriba y en
[`docs/SECURITY_REVIEW.md`](docs/SECURITY_REVIEW.md).
