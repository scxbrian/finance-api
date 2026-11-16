"""Posting rules: what a parsed message means for the ledger.

Parsers say what a message SAYS. This module decides what it MEANS for one user's money:
spending, income, or a move between their own accounts. Sign convention is debit-positive
(see the first migration): assets and expenses grow positive, income grows negative.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.parsers import Parsed
from app.services import chart


class NeedsReview(Exception):
    """A message that parsed fine but cannot be posted safely without a human."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Plan:
    kind: str  # income | expense | transfer
    title: str
    entries: tuple[tuple[UUID, int], ...]  # (ledger account, signed amount)
    note: str | None = None

    def __post_init__(self) -> None:
        if sum(amount for _, amount in self.entries) != 0:  # a bug here must never reach the database
            raise ValueError(f"plan for {self.title!r} does not sum to zero")

    def totals(self) -> dict[UUID, int]:
        """Net effect per account. Two plans with equal totals describe the same event."""
        out: dict[UUID, int] = {}
        for account, amount in self.entries:
            out[account] = out.get(account, 0) + amount
        return {account: amount for account, amount in out.items() if amount != 0}


# Counterparties that are the user's OWN money, not another person. Extend as new
# message shapes are seen (the M-Pesa side of an Etica withdrawal is not known yet).
OWN_FUNDS = {"ziidi": "ziidi"}

_SPENDING = {"mpesa.sent", "mpesa.paybill", "mpesa.till", "mpesa.airtime"}
_RECEIVING_IN_MPESA = {"mpesa.received", "coop.mpesa_received_notice"}


def build_plan(db: Any, user_id: UUID, p: Parsed) -> Plan:
    def asset(provider: str) -> UUID:
        return chart.provider_account(db, user_id, provider)

    def category(kind: str, name: str) -> UUID:
        return chart.get_or_create_account(db, user_id, name, kind)

    amount = p.amount_minor

    if p.kind in _SPENDING:
        # The fee is part of the same transaction on its own line, so "what did M-Pesa
        # fees cost me this month" is a plain sum over the Fees account.
        is_airtime = p.kind == "mpesa.airtime"
        entries = [
            (asset("mpesa"), -(amount + p.fee_minor)),
            (category("expense", chart.AIRTIME if is_airtime else chart.UNCATEGORISED), amount),
        ]
        if p.fee_minor:
            entries.append((category("expense", chart.FEES), p.fee_minor))
        title = {
            "mpesa.sent": f"Sent to {p.counterparty}",
            "mpesa.paybill": p.counterparty,
            "mpesa.till": p.counterparty,
            "mpesa.airtime": "Airtime",
        }[p.kind]
        note = f"Account: {p.counterparty_ref}" if p.kind == "mpesa.paybill" and p.counterparty_ref else None
        return Plan("expense", title or "M-Pesa payment", tuple(entries), note)

    if p.kind in _RECEIVING_IN_MPESA:
        fund = OWN_FUNDS.get((p.counterparty or "").strip().lower())
        if fund:
            return Plan(
                "transfer", f"From {chart.provider_name(fund)}",
                ((asset(fund), -amount), (asset("mpesa"), amount)),
            )
        return Plan(
            "income", f"Received from {p.counterparty}",
            ((asset("mpesa"), amount), (category("income", chart.UNCATEGORISED_INCOME), -amount)),
        )

    if p.kind == "ziidi.invested":
        return Plan("transfer", "Invested in Ziidi", ((asset("mpesa"), -amount), (asset("ziidi"), amount)))
    if p.kind == "ziidi.withdrawn":
        return Plan("transfer", "Withdrawn from Ziidi", ((asset("ziidi"), -amount), (asset("mpesa"), amount)))
    if p.kind == "etica.withdrawal_completed":
        return Plan("transfer", "Withdrawn from Etica", ((asset("etica"), -amount), (asset("mpesa"), amount)))

    if p.kind == "coop.card_purchase":
        if p.currency != "KES":
            # Co-op reports only the foreign amount; the KES figure is unknown until the statement.
            raise NeedsReview("foreign_currency")
        return Plan(
            "expense", p.counterparty or "Card payment",
            ((asset("coop"), -amount), (category("expense", chart.UNCATEGORISED), amount)),
        )
    if p.kind == "coop.till_payment":
        return Plan(
            "expense", p.counterparty or "Till payment",
            ((asset("coop"), -amount), (category("expense", chart.UNCATEGORISED), amount)),
            f"Till {p.counterparty_ref}" if p.counterparty_ref else None,
        )
    if p.kind == "coop.deposit_from_mpesa":
        return Plan("transfer", "M-Pesa to Co-op Bank", ((asset("mpesa"), -amount), (asset("coop"), amount)))

    raise NeedsReview("no_posting_rule")