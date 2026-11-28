# senti-api

The backend of **Senti**, a personal finance tracker for Kenyan shillings: an
append-only double-entry ledger of income, spending, and transfers across
M-Pesa, bank, money market funds, and cash, powered by real-time Android SMS
webhook ingestion, statement/receipt parsing, and monthly analysis. It is built
with FastAPI, SQLAlchemy, and PostgreSQL 18, and runs in Docker Compose behind
Tailscale Funnel.

The frontend lives in its own repository: `senti-web`.

**Status:** core ledger, authentication, CLI tooling, and automated SMS parsers
for `MPESA`, `CoopBank`, `ZIIDI`, and `ETICALTD` are deployed and covered by
279 automated `pytest` checks.

## Contents

1. How it works
2. Repository layout
3. Running it locally
4. Configuration
5. Administration CLI
6. The API contract and SMS ingestion
7. Design decisions
8. Trade-offs and known limitations
9. Deploying and exposing via Tailscale Funnel
10. Testing checklist
11. Roadmap

## How it works

The service is a single FastAPI application backed by PostgreSQL 18. It serves
two clients: the `senti-web` browser interface (authenticated via `HttpOnly`
first-party session cookies proxied through Vercel) and an Android SMS
forwarder running on the user's phone (authenticated via per-device `fin_`
Bearer tokens).

    Android phone (SMS Forwarder)
      |
      `-- POST /api/ingest/sms (Bearer fin_...) --+
                                                  |--> Tailscale Funnel (:8443) --> senti-api (:8001) --> PostgreSQL 18
    browser (senti-web on Vercel)                 |
      |                                           |
      `-- fetch /api/... (session cookie) --------+

Incoming SMS payloads pass through sender-specific parsers (`MPESA`,
`CoopBank`, `ZIIDI`, `ETICALTD`). Login and verification OTPs are acknowledged
and discarded before touching the database; financial messages are normalized
into integer minor units (cents) and written to an append-only ledger.

## Repository layout

    senti-api/
    ├── app/
    │   ├── main.py          # FastAPI app factory, CORS, middleware, routers
    │   ├── cli.py           # User and ingest token administration CLI
    │   ├── api/
    │   │   ├── deps.py      # Session cookie, Bearer token, and Origin dependencies
    │   │   └── routers/     # auth, health, ingest, overview (reads & reconcile)
    │   ├── core/
    │   │   ├── clock.py     # Africa/Nairobi timezone helpers
    │   │   ├── config.py    # Typed environment settings
    │   │   ├── db.py        # SQLAlchemy engine and session lifecycle
    │   │   ├── errors.py    # Standard { "error": { ... } } exception handlers
    │   │   ├── middleware.py# Cache-Control: no-store and security headers
    │   │   └── security.py  # Argon2id password hashing and SHA-256 token hashing
    │   ├── parsers/         # MPESA, CoopBank, ZIIDI, ETICALTD, tariff check, OTP filter
    │   ├── schemas/         # Pydantic request/response contracts
    │   └── services/        # Chart of accounts, intake, posting, reconcile, overview
    ├── migrations/          # Alembic database schema revisions
    ├── tests/               # 279 pytest checks (parsers, ledger, auth, ingestion)
    ├── alembic.ini
    ├── docker-compose.yml
    ├── Dockerfile
    ├── requirements.txt
    └── README.md

## Running it locally

### 1. Start the database and API with Docker Compose

    docker compose up -d --build --wait

The API listens on `127.0.0.1:8001` and exposes `GET /api/health`.

### 2. Run the automated test suite

Activate the virtual environment and run `pytest` against a dedicated test
database so development data is never touched:

    source .venv/bin/activate
    TEST_DATABASE_URL="postgresql+psycopg://finance:PASSWORD@127.0.0.1:5433/finance_test" pytest

## Configuration

All runtime settings are loaded from `.env` (never committed to Git):

| Setting         | Meaning                                                                                   |
| --------------- | ----------------------------------------------------------------------------------------- |
| `APP_ENV`       | `development` or `production` (disables interactive `/api/docs` when `production`).       |
| `DATABASE_URL`  | PostgreSQL 18 connection string (`postgresql+psycopg://...`).                             |
| `APP_ORIGINS`   | Comma-separated allowed browser origins (`Origin` header check on state-changing routes). |
| `CORS_ORIGINS`  | Comma-separated CORS origins for local dev only; leave empty in production.               |
| `COOKIE_SECURE` | Defaults to `true` in `production` (`__Host-session`); set `false` only for plain HTTP.   |

Nothing secret lives in `docker-compose.yml` or source files. Credentials and
database passwords belong strictly in `.env`.

## Administration CLI

There is currently no public self-registration endpoint. Accounts and phone
ingest tokens are provisioned directly on the server via `app.cli` inside the
running `api` container:

    # List all accounts and their status
    docker compose exec api python -m app.cli list-users

    # Create a new user account (prompts interactively for password)
    docker compose exec api python -m app.cli create-user --email user@example.com --name "Name"

    # Reset a user's password and revoke all active browser sessions
    docker compose exec api python -m app.cli reset-password --email user@example.com

    # Generate an ingest token for a phone (printed once; store immediately)
    docker compose exec api python -m app.cli create-token --email user@example.com --name "Phone"

    # Revoke a lost or compromised phone token
    docker compose exec api python -m app.cli revoke-token --email user@example.com --name "Phone"

## The API contract and SMS ingestion

All endpoints live under `/api` and mirror `docs/api-contract.md` in
`senti-web`.

### SMS Webhook (`POST /api/ingest/sms`)

Authenticated with `Authorization: Bearer fin_<token>`:

    {
      "sender": "MPESA",
      "body": "Raw SMS text",
      "received_at": "2026-11-28T00:05:00+03:00"
    }

- **Idempotency:** Duplicate webhook retries with the same transaction code or
  message fingerprint are safely ignored without double-posting.
- **OTP discarding:** Messages matching login/verification patterns return
  `200 OK` with `{"status": "discarded", "transaction_id": null, "reason": "otp"}`.

### Smoke test

    curl -s -X POST https://server.tail24046f.ts.net:8443/api/ingest/sms \
      -H "Authorization: Bearer fin_YOUR_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"sender":"ETICALTD","body":"<#> Please use 123456 as your login code","received_at":"2026-11-28T00:05:00+03:00"}'

## Design decisions

### Money is never a float

Every transaction amount, fee, and reported account balance is parsed from
text using `Decimal` and stored as an integer in minor units (cents). Floating-point
arithmetic never touches currency values anywhere in the stack.

### Append-only double-entry ledger

Database triggers enforce at commit time that every transaction has at least
two entries summing to zero, and block edits or deletes on posted entries.
Corrections are recorded as offsetting reversals rather than mutating history.

### Short-lived unrecognised SMS retention

OTP codes and non-financial messages are discarded before storage. Parsed
messages keep only their SHA-256 fingerprint and structured facts; raw SMS text
is retained temporarily only for unrecognised formats so parsers can be improved
and is purged automatically after review or 30 days.

### Per-device Bearer tokens decoupled from user passwords

The Android SMS forwarder authenticates with a scoped `fin_` token (stored
only as a SHA-256 hash) rather than a user password or browser cookie. If a
phone is lost or replaced, revoking that single token cuts off ingestion
immediately without locking out browser sessions.

### Same-origin proxy and cookie discipline

In production, Vercel proxies `/api/*` to `senti-api`, so browser requests are
first-party and same-origin. Session cookies use `__Host-session` with
`HttpOnly`, `Secure`, and `SameSite=Lax`, backed by an explicit `Origin` header
check (`APP_ORIGINS`) on all state-changing browser endpoints.

## Trade-offs and known limitations

- **Invite-only onboarding (v1):** Accounts are created via CLI rather than
  self-serve signup while core ledger writes and privacy controls are finalized.
- **Carrier template sensitivity:** Kenyan mobile-money and bank SMS formats
  occasionally change wording; unrecognised formats are stored in a review
  queue rather than guessed.
- **Compose project naming:** Docker Compose prefixes volume names with the
  directory name (`senti-api_finance_pgdata`). Renaming the host directory
  creates a fresh volume unless `external: true` or explicit volume names are
  configured.

## Deploying and exposing via Tailscale Funnel

1. Build and start the stack on the Debian homelab server:

       docker compose up -d --build --wait

2. Expose local port `8001` over HTTPS via Tailscale Funnel so Vercel and the
   Android forwarder can reach `/api`:

       tailscale funnel --bg --https=8443 127.0.0.1:8001

3. Verify `tailscale serve status` shows your `.ts.net:8443` host proxying to
   `http://127.0.0.1:8001`.

## Testing checklist

- [x] Full `pytest` suite (279 checks) passes cleanly against `finance_test`.
- [x] `GET /api/health` returns `200 OK` over Tailscale Funnel HTTPS.
- [x] `POST /api/ingest/sms` rejects missing/invalid tokens with `401`.
- [x] OTP messages return `{"status": "discarded", "reason": "otp"}` without DB writes.
- [ ] Live `MPESA`, `CoopBank`, `ZIIDI`, and `ETICALTD` rules forward cleanly from Android into the Ledger.
- [x] `senti-web` authenticates via Vercel proxy and loads overview + ledger data.

## Roadmap

- Retroactive opening balance computation (`POST /api/reconcile/opening`) and balance mismatch alerts.
- Manual transaction entry, reversals, and category reassignment with repeat-payment rules.
- Unrecognised SMS review queue plus Fuliza, Pochi, and agent withdrawal parsers.
- Ephemeral in-memory M-Pesa PDF statement import with zero disk retention.
- Self-service sign-up, data export, and 1-tap account purge.