"""Loads tests/fixtures/sms/*.txt. To cover a new message, add a block to a file: no test code needed.

Block format: "# sender:", "# received:", optional "# note:", then one "# expect:" line holding
JSON, then the message text (any number of lines), then a line containing only ---.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sms"


@dataclass(frozen=True)
class Case:
    id: str
    sender: str
    received: datetime
    body: str
    expect: dict


def load_cases() -> list[Case]:
    cases: list[Case] = []
    for path in sorted(FIXTURE_DIR.glob("*.txt")):
        header: dict[str, str] = {}
        body: list[str] = []
        number = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() == "---":
                if "expect" in header:
                    number += 1
                    cases.append(Case(
                        id=f"{path.stem}-{number}",
                        sender=header["sender"],
                        received=datetime.fromisoformat(header["received"]),
                        body="\n".join(body),
                        expect=json.loads(header["expect"]),
                    ))
                header, body = {}, []
            elif line.startswith("#") and not body:
                key, _, value = line[1:].partition(":")
                if key.strip() in ("sender", "received", "expect"):
                    header[key.strip()] = value.strip()
            elif header:
                body.append(line)
    return cases