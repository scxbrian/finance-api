# senti-api

The backend of **Senti**, a personal finance tracker for Kenyan shillings: an
append-only ledger of income, spending, and transfers across M-Pesa, bank, and
cash, powered by real-time Android SMS webhook ingestion, receipt parsing, and
monthly analysis. It is built with FastAPI, SQLAlchemy, and PostgreSQL 18, and
runs in Docker Compose behind Tailscale Funnel.

The frontend lives in its own repository: `senti-web`.

**Status:** live ingestion active. Core ledger, authentication, CLI tooling,
and automated SMS parsers for `MPESA`, `CoopBank`, `ZIIDI`, and `ETICALTD` are
deployed and covered by 279 automated `pytest` checks.

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
two clients: the `senti-web` browser interface (authenticated via secure
HTTP-only session cookies) and an Android SMS forwarder running on the user's
phone (authenticated via per-device `fin_` Bearer tokens).

    Android phone (Sms Forwarder)
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
    │   ├── config.py        # Typed environment settings
    │   ├── db.py            # SQLAlchemy engine and session lifecycle
    │   ├── cli.py           # User and ingest token administration CLI
    │   ├── models/          # SQLAlchemy ORM models (users, accounts, ledger, tokens)
    │   ├── schemas/         # Pydantic request/response contracts
    │   ├── routers/         # auth, overview, transactions, accounts, ingest, health
    │   ├── parsers/         # MPESA, CoopBank, ZIIDI, ETICALTD, and OTP filters
    │   └── services/        # Ledger invariants, balance math, query aggregation
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

| Setting              | Meaning                                                                 |
| -------------------- | ----------------------------------------------------------------------- |
| `DATABASE_URL`       | PostgreSQL 18 connection string (`postgresql+psycopg://...`).           |
| `SECRET_KEY`         | Cryptographic key for signing session cookies and hashing tokens.       |
| `APP_ORIGINS`        | Comma-separated allowed frontend origins (e.g. `https://...vercel.app`). |
| `COOKIE_SECURE`      | `true` in production over HTTPS; `false` only for local HTTP testing.   |
| `COOKIE_SAMESITE`    | `none` when frontend (Vercel) and API (Tailscale) are cross-site.       |

Nothing secret lives in `docker-compose.yml` or source files. Credentials,
database passwords, and signing keys belong strictly in `.env`.

## Administration CLI

There is no public self-registration endpoint. Accounts and phone ingest
tokens are provisioned directly on the server via `app.cli` inside the running
`api` container:

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
      "received_at": "1732721280000"
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

### Append-only ledger

Posted transactions are immutable. Corrections and reversals are recorded as
explicit offsetting entries rather than mutating historical rows, preserving a
complete audit trail for balance reconciliation.

### Raw SMS retention for audit and parser recovery

Incoming financial messages store their raw SMS body, sender ID, and receipt
timestamp alongside the parsed ledger entry. If a carrier changes an SMS
template or a parser bug is discovered, historical messages can be re-evaluated
without losing data.

### Per-device Bearer tokens decoupled from user passwords

The Android SMS forwarder authenticates with a scoped `fin_` token rather than
a user password or browser cookie. If a phone is lost or replaced, revoking that
single token cuts off ingestion immediately without locking out browser sessions.

### Cross-origin cookie discipline

Because `senti-web` is hosted on Vercel and `senti-api` is self-hosted on a
Tailscale Funnel domain, `APP_ORIGINS` is explicitly allowlisted and session
cookies use `HttpOnly`, `Secure`, and `SameSite=None`.

## Trade-offs and known limitations

- **Single-user / invite-only onboarding:** Accounts are created via CLI rather
  than self-serve signup to keep the attack surface minimal on a self-hosted box.
- **Carrier template sensitivity:** Kenyan mobile-money and bank SMS formats
  occasionally change wording; unrecognized formats are logged for parser
  updates rather than guessed.
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

3. Verify `tailscale serve status` shows `https://server.tail24046f.ts.net:8443`
   proxying to `http://127.0.0.1:8001`.

## Testing checklist

- [x] Full `pytest` suite (279 checks) passes cleanly against `finance_test`.
- [x] `GET /api/health` returns `200 OK` over Tailscale Funnel HTTPS.
- [x] `POST /api/ingest/sms` rejects missing/invalid tokens with `401`.
- [x] OTP messages return `{"status": "discarded", "reason": "otp"}` without DB writes.
- [x] Live `MPESA`, `CoopBank`, `ZIIDI`, and `ETICALTD` rules forward cleanly from Android.
- [x] `senti-web` authenticates cross-origin from Vercel and loads overview + ledger data.

## Roadmap

- Retroactive opening balance computation from reported M-Pesa balances stored on each SMS.
- Balance mismatch detection flagging any message whose reported balance disagrees with the running ledger.
- Ziidi daily interest posting parser and automated entry creation.
- Receipt OCR ingestion endpoint and manual transaction entry support.