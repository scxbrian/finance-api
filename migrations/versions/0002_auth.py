"""Sessions, API tokens and login attempts.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-17
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPGRADE = [
    # Only a hash of the session token is stored, so a leaked database cannot be replayed.
    """
    CREATE TABLE sessions (
        id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id      uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        token_hash   text NOT NULL UNIQUE,
        created_at   timestamptz NOT NULL DEFAULT now(),
        last_seen_at timestamptz NOT NULL DEFAULT now(),
        expires_at   timestamptz NOT NULL,
        revoked_at   timestamptz,
        user_agent   text
    )
    """,
    "CREATE INDEX sessions_user_idx ON sessions (user_id)",
    # Long-lived credentials for the phone's SMS forwarder. Scoped: an ingest token can post
    # messages and do nothing else.
    """
    CREATE TABLE api_tokens (
        id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id      uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        name         text NOT NULL CHECK (length(btrim(name)) > 0),
        token_hash   text NOT NULL UNIQUE,
        scope        text NOT NULL CHECK (scope IN ('ingest')),
        created_at   timestamptz NOT NULL DEFAULT now(),
        last_used_at timestamptz,
        revoked_at   timestamptz,
        UNIQUE (user_id, name)
    )
    """,
    """
    CREATE TABLE login_attempts (
        id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        email        text NOT NULL,
        attempted_at timestamptz NOT NULL DEFAULT now(),
        succeeded    boolean NOT NULL
    )
    """,
    "CREATE INDEX login_attempts_email_idx ON login_attempts (email, attempted_at DESC)",
]

DOWNGRADE = [
    "DROP TABLE login_attempts",
    "DROP TABLE api_tokens",
    "DROP TABLE sessions",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)