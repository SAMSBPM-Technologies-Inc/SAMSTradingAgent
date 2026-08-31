"""
Create a new user account in the trading tool database.

Usage (from the backend/ directory with .venv active):
    python scripts/create_user.py --email you@example.com --password secret \
        --name "Your Name" --tier TRADER

The script reads MONGODB_URL and MONGODB_DB_NAME from .env (same as the app).

`POST /admin/users` does the same job over HTTP and is the usual route now;
this stays for the first account, when there is no admin to sign in as yet.
Both build the document through `services.auth.new_user_document`, so the two
cannot drift — a field one writes and the other forgets would show up as an
account with silently less access than was granted.
"""
import argparse
import asyncio
import sys
from pathlib import Path

# Allow running from any working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
from app.config import get_settings
from app.models.user import AccessTier
from app.services.auth import new_user_document


async def create_user(email: str, password: str, name: str, tier: str,
                      ticker_cap: int | None, research_daily: bool) -> None:
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.mongodb_db_name]

    existing = await db["users"].find_one({"email": email})
    if existing:
        print(f"ERROR: A user with email '{email}' already exists.")
        client.close()
        sys.exit(1)

    user = new_user_document(
        email=email,
        password=password,
        display_name=name,
        access_tier=AccessTier(tier),
        watchlist_cap=ticker_cap,
        research_daily_allowed=research_daily,
    )
    result = await db["users"].insert_one(user)
    client.close()

    cap = user.get("watchlist_cap")
    print("User created successfully.")
    print(f"  ID    : {result.inserted_id}")
    print(f"  Email : {email}")
    print(f"  Name  : {user['display_name']}")
    print(f"  Plan  : {user['access_tier']}")
    print(f"  Cap   : {cap if cap is not None else 'the default for this plan'}")
    if user["access_tier"] != AccessTier.TRADER.value:
        print("\nNote: this account has no trading or broker access.")
    print("\nThe user can now sign in. Change their plan later with "
          "PATCH /admin/users/{id}, or from the Admin page.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a new user account")
    parser.add_argument("--email",    required=True, help="User's email address")
    parser.add_argument("--password", required=True, help="Login password")
    parser.add_argument("--name",     default="",    help="Display name (defaults to email prefix)")
    # Choices come from the enum rather than a literal list, so this script
    # cannot drift from the model the API validates against.
    parser.add_argument(
        "--tier", default=AccessTier.BASIC.value,
        choices=[t.value for t in AccessTier],
        help="Access plan. Defaults to BASIC — the smallest thing that is "
             "useful. Your own account wants --tier TRADER.",
    )
    parser.add_argument(
        "--ticker-cap", type=int, default=None,
        help="Watchlist cap for this account. Omit to use the plan's default, "
             "which then keeps applying if that default is ever retuned.",
    )
    parser.add_argument(
        "--research-daily", action="store_true",
        help="Let a PRO account enrol in the nightly research job. Five to "
             "seven model calls per ticker per day, unattended.",
    )
    args = parser.parse_args()

    asyncio.run(create_user(args.email, args.password, args.name,
                            args.tier, args.ticker_cap, args.research_daily))


if __name__ == "__main__":
    main()
