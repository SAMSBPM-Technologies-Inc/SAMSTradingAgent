"""
Create a new user account in the trading tool database.

Usage (from the backend/ directory with .venv active):
    python scripts/create_user.py --email you@example.com --password secret --name "Your Name"

The script reads MONGODB_URL and MONGODB_DB_NAME from .env (same as the app).
"""
import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from any working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
from app.config import get_settings
from app.services.auth import hash_password


async def create_user(email: str, password: str, name: str) -> None:
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.mongodb_db_name]

    existing = await db["users"].find_one({"email": email})
    if existing:
        print(f"ERROR: A user with email '{email}' already exists.")
        client.close()
        sys.exit(1)

    user = {
        "email": email,
        "password_hash": hash_password(password),
        "display_name": name or email.split("@")[0],
        "created_at": datetime.now(tz=timezone.utc),
        "scoring_weights": None,   # will use global defaults until the user sets their own
    }
    result = await db["users"].insert_one(user)
    client.close()
    print(f"User created successfully.")
    print(f"  ID    : {result.inserted_id}")
    print(f"  Email : {email}")
    print(f"  Name  : {user['display_name']}")
    print(f"\nThe user can now log in at their subdomain and set personal scoring weights from their profile.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a new user account")
    parser.add_argument("--email",    required=True, help="User's email address")
    parser.add_argument("--password", required=True, help="Login password")
    parser.add_argument("--name",     default="",    help="Display name (defaults to email prefix)")
    args = parser.parse_args()

    asyncio.run(create_user(args.email, args.password, args.name))


if __name__ == "__main__":
    main()
