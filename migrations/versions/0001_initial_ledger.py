"""Initial ledger: users, accounts, transactions, entries, source messages.

Sign convention (debit-positive, the usual double-entry rule):
    asset and expense entries are positive when they grow;
    income, liability and equity entries are negative when they grow.
Every transaction's entries sum to exactly zero. Examples:
    spend 2,340 from M-Pesa on groceries:   M-Pesa -234000, Groceries +234000
    salary 65,000 into the bank:            Bank +6500000, Salary -6500000
    move 10,000 from Bank to an MMF:        Bank -1000000, MMF +1000000   (a transfer, not spending)

Revision ID: 0001
Revises:
Create Date: 2026-11-16
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UPGRADE = [
    # ------------------------------------------------------------------ users
    """
    CREATE TABLE users (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        email         text NOT NULL CHECK (length(btrim(email)) > 0),
        display_name  text NOT NULL,
        password_hash text NOT NULL,
        is_active     boolean NOT NULL DEFAULT true,
        created_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE UNIQUE INDEX users_email_lower_key ON users (lower(email))",
    # -------------------------------------------------------- ledger accounts
    # One table holds both "where money sits" (asset/liability) and "what it was for"
    # (income/expense categories). The UNIQUE (user_id, id) looks redundant next to the
    # primary key, but it is the target that lets other tables reference an account
    # TOGETHER with its owner, which is what makes cross-user references impossible.
    """
    CREATE TABLE ledger_accounts (
        id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id     uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
        name        text NOT NULL CHECK (length(btrim(name)) > 0),
        kind        text NOT NULL CHECK (kind IN ('asset', 'liability', 'income', 'expense', 'equity')),
        subtype     text,
        archived_at timestamptz,
        created_at  timestamptz NOT NULL DEFAULT now(),
        UNIQUE (user_id, id),
        UNIQUE (user_id, kind, name)
    )
    """,
    # Maps "Co-op account ending 0001" to a ledger account. Only the last digits are kept.
    """
    CREATE TABLE account_identifiers (
        id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id           uuid NOT NULL,
        ledger_account_id uuid NOT NULL,
        provider          text NOT NULL,
        suffix            text NOT NULL CHECK (length(suffix) BETWEEN 1 AND 4),
        FOREIGN KEY (user_id, ledger_account_id)
            REFERENCES ledger_accounts (user_id, id) ON DELETE RESTRICT,
        UNIQUE (user_id, provider, suffix)
    )
    """,
    # ----------------------------------------------------------- transactions
    # occurred_on is computed by the database from occurred_at, always in Nairobi time,
    # so the business day cannot be filed under the wrong date by any caller.
    """
    CREATE TABLE transactions (
        id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id     uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
        occurred_at timestamptz NOT NULL,
        occurred_on date GENERATED ALWAYS AS ((occurred_at AT TIME ZONE 'Africa/Nairobi')::date) STORED,
        kind        text NOT NULL CHECK (kind IN ('income', 'expense', 'fee', 'transfer', 'opening', 'adjustment')),
        title       text NOT NULL CHECK (length(btrim(title)) > 0),
        note        text,
        source      text NOT NULL CHECK (source IN ('manual', 'receipt', 'sms', 'import')),
        external_ref text,
        reversal_of uuid,
        created_at  timestamptz NOT NULL DEFAULT now(),
        UNIQUE (user_id, id),
        FOREIGN KEY (user_id, reversal_of) REFERENCES transactions (user_id, id) ON DELETE RESTRICT
    )
    """,
    # The same M-Pesa code can never create two transactions for one user...
    """
    CREATE UNIQUE INDEX transactions_user_external_ref_key
        ON transactions (user_id, external_ref) WHERE external_ref IS NOT NULL
    """,
    # ...and a transaction can be reversed at most once.
    """
    CREATE UNIQUE INDEX transactions_one_reversal_key
        ON transactions (user_id, reversal_of) WHERE reversal_of IS NOT NULL
    """,
    "CREATE INDEX transactions_user_day_idx ON transactions (user_id, occurred_on DESC)",
    # ---------------------------------------------------------------- entries
    """
    CREATE TABLE entries (
        id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id           uuid NOT NULL,
        transaction_id    uuid NOT NULL,
        ledger_account_id uuid NOT NULL,
        amount_minor      bigint NOT NULL CHECK (amount_minor <> 0),
        FOREIGN KEY (user_id, transaction_id)
            REFERENCES transactions (user_id, id) ON DELETE RESTRICT,
        FOREIGN KEY (user_id, ledger_account_id)
            REFERENCES ledger_accounts (user_id, id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX entries_transaction_idx ON entries (transaction_id)",
    "CREATE INDEX entries_account_idx ON entries (user_id, ledger_account_id)",
    # --------------------------------------------------------- source messages
    # Every SMS we keep, linked to the transaction it produced (several messages can
    # share one transaction). One-time codes are never inserted here at all.
    """
    CREATE TABLE source_messages (
        id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id        uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
        transaction_id uuid,
        sender         text NOT NULL,
        body           text NOT NULL,
        body_sha256    text NOT NULL CHECK (body_sha256 ~ '^[0-9a-f]{64}$'),
        received_at    timestamptz NOT NULL,
        parse_status   text NOT NULL CHECK (parse_status IN ('parsed', 'ignored', 'unrecognised')),
        parse_reason   text,
        parser_version text NOT NULL,
        parsed         jsonb,
        created_at     timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY (user_id, transaction_id)
            REFERENCES transactions (user_id, id) ON DELETE RESTRICT,
        UNIQUE (user_id, body_sha256, received_at)
    )
    """,
    "CREATE INDEX source_messages_transaction_idx ON source_messages (transaction_id) WHERE transaction_id IS NOT NULL",
    """
    CREATE INDEX source_messages_review_idx
        ON source_messages (user_id, received_at DESC) WHERE parse_status = 'unrecognised'
    """,
    # ------------------------------------------------- the rules the database enforces
    # 1. Every transaction has at least two entries and they sum to zero. The checks are
    #    DEFERRED to commit time, so a transaction and its entries can be inserted in any
    #    order inside one database transaction, but a half-written ledger can never commit.
    """
    CREATE FUNCTION assert_transaction_balanced(tx uuid) RETURNS void
    LANGUAGE plpgsql AS $$
    DECLARE
        n     integer;
        total bigint;
    BEGIN
        SELECT count(*), COALESCE(sum(amount_minor), 0) INTO n, total
        FROM entries WHERE transaction_id = tx;
        IF n < 2 THEN
            RAISE EXCEPTION 'transaction % must have at least two entries (has %)', tx, n
                USING ERRCODE = 'check_violation';
        END IF;
        IF total <> 0 THEN
            RAISE EXCEPTION 'transaction % is unbalanced: entries sum to %', tx, total
                USING ERRCODE = 'check_violation';
        END IF;
    END
    $$
    """,
    """
    CREATE FUNCTION entries_balance_trigger() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        PERFORM assert_transaction_balanced(NEW.transaction_id);
        RETURN NULL;
    END
    $$
    """,
    """
    CREATE FUNCTION transactions_balance_trigger() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        PERFORM assert_transaction_balanced(NEW.id);
        RETURN NULL;
    END
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER entries_balanced
        AFTER INSERT ON entries DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION entries_balance_trigger()
    """,
    """
    CREATE CONSTRAINT TRIGGER transactions_have_entries
        AFTER INSERT ON transactions DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION transactions_balance_trigger()
    """,
    # 2. The ledger is append-only. Mistakes are fixed by posting a reversal, so history
    #    is always an audit trail. (Relaxing this for recategorising is a later decision.)
    """
    CREATE FUNCTION forbid_change() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION '% on % is not allowed: the ledger is append-only, post a reversal instead',
            TG_OP, TG_TABLE_NAME USING ERRCODE = 'restrict_violation';
    END
    $$
    """,
    """
    CREATE TRIGGER entries_append_only BEFORE UPDATE OR DELETE ON entries
        FOR EACH ROW EXECUTE FUNCTION forbid_change()
    """,
    """
    CREATE TRIGGER transactions_no_delete BEFORE DELETE ON transactions
        FOR EACH ROW EXECUTE FUNCTION forbid_change()
    """,
    # 3. A transaction's facts are frozen; only the title and note may be edited, and an
    #    external reference may be attached once if there was none.
    """
    CREATE FUNCTION transactions_guard_update() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF (NEW.id, NEW.user_id, NEW.occurred_at, NEW.kind, NEW.source, NEW.reversal_of, NEW.created_at)
           IS DISTINCT FROM
           (OLD.id, OLD.user_id, OLD.occurred_at, OLD.kind, OLD.source, OLD.reversal_of, OLD.created_at) THEN
            RAISE EXCEPTION 'posted transactions cannot be changed: post a reversal instead'
                USING ERRCODE = 'restrict_violation';
        END IF;
        IF OLD.external_ref IS NOT NULL AND NEW.external_ref IS DISTINCT FROM OLD.external_ref THEN
            RAISE EXCEPTION 'external_ref is already set and cannot be changed'
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER transactions_guard BEFORE UPDATE ON transactions
        FOR EACH ROW EXECUTE FUNCTION transactions_guard_update()
    """,
]

DOWNGRADE = [
    "DROP TABLE source_messages",
    "DROP TABLE entries",
    "DROP TABLE transactions",
    "DROP TABLE account_identifiers",
    "DROP TABLE ledger_accounts",
    "DROP TABLE users",
    "DROP FUNCTION transactions_guard_update()",
    "DROP FUNCTION forbid_change()",
    "DROP FUNCTION transactions_balance_trigger()",
    "DROP FUNCTION entries_balance_trigger()",
    "DROP FUNCTION assert_transaction_balanced(uuid)",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)