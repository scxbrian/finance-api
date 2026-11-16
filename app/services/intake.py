"""Intake: one received SMS in, ledger entries out.

    parse -> store the message -> work out what it means -> post it, or attach it to the
    transaction another message already created for the same event.

The caller owns the database transaction and commits it. Nothing here commits, so a failure
half-way leaves no half-written ledger (and the database refuses unbalanced ones anyway).
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.parsers import Ignored, Parsed, Unrecognised, parse_message
from app.parsers.common import normalise
from app.services.posting import NeedsReview, Plan, build_plan

PARSER_VERSION = "1"  # bump when parser behaviour changes, so old messages can be re-read


@dataclass(frozen=True)
class Outcome:
    status: str  # created | merged | conflict | ignored | unrecognised | duplicate | discarded
    transaction_id: UUID | None = None
    message_id: UUID | None = None
    reason: str | None = None


def _json(value: Any) -> str:
    return json.dumps(value, default=lambda o: o.isoformat() if isinstance(o, datetime) else str(o))


def _store_message(db, user_id, sender, body, digest, received_at, status, reason, parsed) -> UUID | None:
    """Returns the new row's id, or None when this exact message was already stored."""
    return db.execute(
        text(
            "INSERT INTO source_messages (user_id, sender, body, body_sha256, received_at, parse_status,"
            " parse_reason, parser_version, parsed)"
            " VALUES (:u, :s, :b, :h, :at, :st, :r, :v, CAST(:p AS jsonb))"
            " ON CONFLICT (user_id, body_sha256, received_at) DO NOTHING RETURNING id"
        ),
        {"u": user_id, "s": sender, "b": body, "h": digest, "at": received_at, "st": status,
         "r": reason, "v": PARSER_VERSION, "p": _json(asdict(parsed)) if parsed else None},
    ).scalar_one_or_none()


def _flag_for_review(db, message_id: UUID, reason: str) -> None:
    db.execute(
        text("UPDATE source_messages SET parse_status = 'unrecognised', parse_reason = :r WHERE id = :m"),
        {"r": reason, "m": message_id},
    )


def _link(db, message_id: UUID, transaction_id: UUID) -> None:
    db.execute(
        text("UPDATE source_messages SET transaction_id = :t WHERE id = :m"),
        {"t": transaction_id, "m": message_id},
    )


def _existing_totals(db, transaction_id: UUID) -> dict[UUID, int]:
    rows = db.execute(
        text("SELECT ledger_account_id, sum(amount_minor) FROM entries WHERE transaction_id = :t GROUP BY 1"),
        {"t": transaction_id},
    ).all()
    return {account: int(total) for account, total in rows if total != 0}


def _post(db, user_id: UUID, parsed: Parsed, plan: Plan) -> tuple[UUID, bool]:
    """Create the transaction. Returns (id, created). created=False means the reference already
    belonged to a transaction, whose id is returned instead."""
    new_id = db.execute(
        text(
            "INSERT INTO transactions (user_id, occurred_at, kind, title, note, source, external_ref)"
            " VALUES (:u, :at, :k, :t, :n, 'sms', :ref)"
            " ON CONFLICT (user_id, external_ref) WHERE external_ref IS NOT NULL DO NOTHING RETURNING id"
        ),
        {"u": user_id, "at": parsed.occurred_at, "k": plan.kind, "t": plan.title, "n": plan.note,
         "ref": parsed.reference},
    ).scalar_one_or_none()

    if new_id is None:
        existing = db.execute(
            text("SELECT id FROM transactions WHERE user_id = :u AND external_ref = :r"),
            {"u": user_id, "r": parsed.reference},
        ).scalar_one()
        return existing, False

    db.execute(
        text("INSERT INTO entries (user_id, transaction_id, ledger_account_id, amount_minor) VALUES (:u, :t, :a, :m)"),
        [{"u": user_id, "t": new_id, "a": account, "m": amount} for account, amount in plan.entries],
    )
    return new_id, True


def ingest_sms(db: Any, user_id: UUID, sender: str, body: str, received_at: datetime) -> Outcome:
    """`db` is a SQLAlchemy Session or Connection. `received_at` must carry a timezone."""
    result = parse_message(sender, body, received_at)

    # A one-time code is a secret: it is not even written to the message log.
    if isinstance(result, Ignored) and not result.store_raw:
        return Outcome("discarded", reason=result.reason)

    digest = hashlib.sha256(normalise(body).encode("utf-8")).hexdigest()
    parsed = result if isinstance(result, Parsed) else None
    status = {Parsed: "parsed", Ignored: "ignored", Unrecognised: "unrecognised"}[type(result)]
    reason = getattr(result, "reason", None)

    message_id = _store_message(db, user_id, sender, body, digest, received_at, status, reason, parsed)
    if message_id is None:
        return Outcome("duplicate")  # the same message again, e.g. a forwarder retry

    if parsed is None:
        return Outcome(status, message_id=message_id, reason=reason)

    try:
        plan = build_plan(db, user_id, parsed)
    except NeedsReview as review:
        _flag_for_review(db, message_id, review.reason)
        return Outcome("unrecognised", message_id=message_id, reason=review.reason)

    transaction_id, created = _post(db, user_id, parsed, plan)
    if created:
        _link(db, message_id, transaction_id)
        return Outcome("created", transaction_id, message_id)

    # Another message already described this event. If it means the same thing, this one is
    # just a second witness. If it means something different, a person must decide: the
    # ledger is append-only, so we never silently rewrite what is already posted.
    if _existing_totals(db, transaction_id) == plan.totals():
        _link(db, message_id, transaction_id)
        return Outcome("merged", transaction_id, message_id)

    _flag_for_review(db, message_id, "conflicts_with_existing_transaction")
    return Outcome("conflict", transaction_id, message_id, "conflicts_with_existing_transaction")