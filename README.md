# TradeVault

A mobile-first screenshot journal for traders, built with Python, Flask, Jinja, HTML, CSS and a small amount of progressive-enhancement JavaScript. Keep chart screenshots, add gentle private reflections, return to a trading day, and download one image or a selected ZIP.

## What’s included

- Email/password signup and sign-in, logout, password changes, and expiring single-use email password-recovery links.
- Guided first-use onboarding and responsive journal navigation.
- Screenshot upload and per-entry details, soft removal, and reflection notes that autosave after a short pause.
- Search by symbol, market, notes and filename; filter by date; chronological day grouping.
- Same-day visual-similarity groupings using an average image hash and a configurable Hamming distance. Similarity is for finding screenshots, not a trading signal.
- In-app notifications and notification preferences.
- Individual downloads and selected batch downloads (up to 12 items and 64 MB per ZIP).
- CSRF-protected forms, hashed passwords, authenticated ownership checks, private cache headers and an unauthenticated deployment health route.

## Run locally

Python 3.11+ is recommended.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app app:app db upgrade
TRADEVAULT_COOKIE_SECURE=false flask --app app:app run --host 127.0.0.1 --port 3000
```

For local development, the app creates a local-only session signing key and uses SQLite plus files beneath `instance/uploads/`. This fallback is convenient for a single developer but **is not durable storage for a deployed multi-instance app**. A production process refuses to use local screenshot storage. Keep `instance/` out of Git and the deployment ZIP. Start with `http://127.0.0.1:3000`.

## Deployment on Manus WebDev

This WebDev project is configured for a server container with database access, the root `Dockerfile`, and `/_app/health` as its health path. Those project-level WebDev settings are not embedded in the ZIP; when importing it into a different WebDev project, declare `features.server=true`, `features.database=true`, `deploy.dockerfilePath=Dockerfile`, `deploy.healthPath=/_app/health`, and runtime port `3000` before deploying. WebDev supplies the managed MySQL `DATABASE_URL`, `MANUS_API_URL`, and `MANUS_API_KEY` at runtime. `tradevault/storage.py` uses the platform presign endpoints and stores only owner-scoped object keys in MySQL. Do not expose storage credentials in browser code.

Set these runtime values before enabling password recovery:

| Variable | Purpose |
| --- | --- |
| `TRADEVAULT_SECRET_KEY` | Stable, random application session signing key; required in production. |
| `APP_BASE_URL` | Public HTTPS origin for recovery URLs; use the actual published app URL. |
| `MAIL_SERVER`, `MAIL_PORT` | Your SMTP provider host and port. |
| `MAIL_USE_TLS`, `MAIL_USE_SSL` | SMTP transport choice; normally TLS on port 587. Do not enable both. |
| `MAIL_USERNAME`, `MAIL_PASSWORD` | SMTP account credentials. |
| `MAIL_DEFAULT_SENDER` | Sender address verified with that provider. |
| `DATABASE_URL` | Managed MySQL connection URL supplied by WebDev. Do not commit it. |
| `MANUS_API_URL`, `MANUS_API_KEY` | Server-only platform storage API runtime credentials supplied by WebDev. |

Use your WebDev protected secret-input flow for `TRADEVAULT_SECRET_KEY` and `MAIL_PASSWORD`; configure the other values as runtime environment settings supported by your deployment workflow. **Password-reset email delivery is not active until a working SMTP sender and `APP_BASE_URL` are configured.** Requests use generic copy to avoid revealing whether an email exists, and no reset token is shown in the app or logs. When SMTP is missing, the recovery form shows the same setup-required notice for every entered address.

Database migrations run at container startup with `flask db upgrade` before Gunicorn binds to `PORT` (3000 by default). The health endpoint is `/_app/health`. The application sets a `SameSite=None; Secure; HttpOnly` session cookie for public HTTPS/Preview; when explicitly configured with `TRADEVAULT_COOKIE_SECURE=false` for plain-HTTP local development, it uses `SameSite=Lax`. It does not emit frame-denying headers. Use only HTTPS publicly.

## Other hosting providers

This ZIP contains a deployable Docker/Flask app, but its managed MySQL and screenshot adapter assume Manus WebDev’s supplied database and object-storage API variables. For a different host, set a compatible `DATABASE_URL`, configure SMTP, and adapt `tradevault/storage.py` to that host’s durable object store before production use. Do not turn on local filesystem uploads as a substitute for durable storage in a multi-instance deployment.

## Database and schema changes

The first schema is under `migrations/versions/0001_initial.py`. After changing models, create and review a migration, then commit it:

```bash
flask --app app:app db migrate -m "describe the change"
flask --app app:app db upgrade
```

Development and production share the managed database in WebDev. Treat schema changes and development writes as production-impacting; do not use destructive migrations casually.

## Privacy and storage notes

- Each screenshot record is scoped to its account. Image reads and downloads require a valid app session and ownership match before a short-lived signed download redirect is issued.
- Deleting an entry hides it from the journal. The platform runtime object-storage API has no object-delete call, so the app does not claim to erase screenshot bytes. Arrange storage lifecycle cleanup separately if physical erasure is required.
- Runtime data under `instance/` (the SQLite database, uploads, session key and other generated files) is excluded from the source ZIP; only `.gitkeep` may preserve the empty directory.
- There is no trading advice, performance scoring, email verification, or external-market integration.
