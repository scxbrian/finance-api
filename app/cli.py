"""Administration commands. Run them inside the API container, for example:

    docker compose exec api python -m app.cli create-user --email you@example.com --name "Your Name"
    docker compose exec api python -m app.cli create-token --email you@example.com --name "Pixel 8"

There is no public sign-up. Accounts are made here, by whoever runs the server.
"""

import argparse
import getpass
import sys

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.db import get_sessionmaker
from app.services import auth


def _password_twice() -> str:
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat it: "):
        raise SystemExit("The two passwords differ.")
    return first


def _user_id(db, email: str):
    user_id = db.execute(
        text("SELECT id FROM users WHERE lower(email) = :e"), {"e": auth.normalise_email(email)}
    ).scalar_one_or_none()
    if user_id is None:
        raise SystemExit(f"No user with email {email!r}.")
    return user_id


def run(args: argparse.Namespace) -> None:
    with get_sessionmaker()() as db:
        if args.command == "create-user":
            auth.create_user(db, args.email, args.name, _password_twice())
            print(f"Created {args.email}.")
        elif args.command == "reset-password":
            auth.set_password(db, args.email, _password_twice())
            print("Password changed. Every existing session was signed out.")
        elif args.command == "create-token":
            token = auth.create_api_token(db, _user_id(db, args.email), args.name)
            print(f"\nToken for {args.name!r} (shown once, store it now):\n\n    {token}\n")
        elif args.command == "revoke-token":
            revoked = auth.revoke_api_token(db, _user_id(db, args.email), args.name)
            print("Revoked." if revoked else "No active token with that name.")
        elif args.command == "list-users":
            for email, name, active in db.execute(text("SELECT email, display_name, is_active FROM users ORDER BY email")):
                print(f"{email}\t{name}\t{'active' if active else 'DISABLED'}")
        db.commit()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-user", help="create an account")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    reset = sub.add_parser("reset-password", help="set a new password and sign the user out everywhere")
    reset.add_argument("--email", required=True)
    token = sub.add_parser("create-token", help="make an ingest token for a phone")
    token.add_argument("--email", required=True)
    token.add_argument("--name", required=True, help="a label such as the phone's name")
    revoke = sub.add_parser("revoke-token", help="disable a token, e.g. a lost phone")
    revoke.add_argument("--email", required=True)
    revoke.add_argument("--name", required=True)
    sub.add_parser("list-users", help="show every account")

    try:
        run(parser.parse_args(argv))
    except ValueError as problem:
        sys.exit(str(problem))
    except IntegrityError:
        sys.exit("That already exists (an account with that email, or a token with that name).")


if __name__ == "__main__":
    main()