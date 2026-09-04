"""
Check the `stocks_signal_history` index migration against a real MongoDB.

This is startup-path index code and a stubbed database cannot check it — a
stubbed Mongo let an index bug reach production once already. The failure mode
is silent in the worst direction: the superseded unique index rejects the second
verdict of an hour, and `_append_history` swallows the error in its own
try/except.

Two modes.

    # Read-only. Reports what the live collection actually carries. Safe to
    # point at production; opens no write and creates no database.
    MONGODB_URL='...' python scripts/verify_history_index.py --inspect

    # The migration test. Recreates the OLD index in a scratch database, runs
    # the real `_ensure_indexes`, and asserts the outcome. Writes.
    MONGODB_URL=mongodb://localhost:27017 python scripts/verify_history_index.py

The write mode refuses a `mongodb+srv://` URL — that is what a hosted cluster
looks like — unless `--allow-remote` is passed. It only ever touches a scratch
database it also drops, but "only a scratch database" is exactly what every
script says before it is pointed at the wrong cluster at the wrong hour.

Why the migration is safe on existing data, independent of this script: the new
unique key `(ticker, hour_bucket, signal)` is a **superset** of the old unique
key `(ticker, hour_bucket)`. If no two documents collided on the old key, none
can collide on the new one, so the unique build cannot fail on duplicates. The
new index is created *before* the old one is dropped, and if the create raises,
`_ensure_indexes` exits before the drop and the old index stays in place.

Exits non-zero on failure.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

DB_NAME = "trading_agent_index_check"
COLL = "stocks_signal_history"


async def inspect(client) -> int:
    """Read-only. What the live collection carries right now."""
    from app.config import get_settings

    name = get_settings().mongodb_db_name
    db = client[name]
    print(f"database: {name}")

    info = await db[COLL].index_information()
    print(f"  {COLL} indexes:")
    for index_name, spec in sorted(info.items()):
        flags = " unique" if spec.get("unique") else ""
        partial = " partial" if spec.get("partialFilterExpression") else ""
        print(f"    {index_name}: {spec.get('key')}{flags}{partial}")

    total = await db[COLL].estimated_document_count()
    print(f"  rows: ~{total:,}")

    old_present = "ticker_1_hour_bucket_1" in info
    new_present = "ticker_1_hour_bucket_1_signal_1" in info
    print()
    if new_present and not old_present:
        print("  state: MIGRATED")
    elif old_present and not new_present:
        print("  state: NOT YET MIGRATED — the next deploy performs it")
        print("  note:  the new key is a superset of the old unique key, so no")
        print("         existing row can violate it; the build cannot fail on")
        print("         duplicates.")
    elif old_present and new_present:
        print("  state: BOTH PRESENT — the old unique index still rejects a")
        print("         second verdict in one hour. Drop ticker_1_hour_bucket_1.")
    else:
        print("  state: NEITHER — collection may be empty or never initialised")
    return 0


async def main() -> int:
    url = os.environ.get("MONGODB_URL", "mongodb://localhost:27017")
    inspect_only = "--inspect" in sys.argv

    # Decided on the string alone, BEFORE a client is constructed: building one
    # against an SRV URL resolves DNS immediately, so a guard placed after it
    # has already reached out to the cluster it was meant to refuse.
    remote = url.startswith("mongodb+srv://") or "mongodb.net" in url
    if remote and not inspect_only and "--allow-remote" not in sys.argv:
        print("REFUSED: MONGODB_URL points at a hosted cluster.")
        print("  This mode writes. Use --inspect for a read-only report, or")
        print("  --allow-remote if you really mean to build a scratch database")
        print("  on that cluster.")
        return 2

    client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000)
    await client.admin.command("ping")

    if inspect_only:
        return await inspect(client)

    await client.drop_database(DB_NAME)
    db = client[DB_NAME]

    # 1. Recreate the OLD state: the two-key unique index this migration drops.
    await db[COLL].create_index(
        [("ticker", 1), ("hour_bucket", 1)],
        unique=True,
        partialFilterExpression={"hour_bucket": {"$type": "date"}},
        background=True,
    )
    before = set(await db[COLL].index_information())
    assert "ticker_1_hour_bucket_1" in before, before
    print(f"  old index present: {sorted(before)}")

    # 2. Run the real migration — the actual startup function, not a copy of
    #    it. `_ensure_indexes` resolves its handle through `get_db`, so that is
    #    what gets pointed at the scratch database.
    import app.db as appdb

    async def _scratch_db():
        return db

    appdb.get_db = _scratch_db
    await appdb._ensure_indexes()

    after = await db[COLL].index_information()
    names = set(after)
    print(f"  after migration:   {sorted(names)}")

    ok = True
    if "ticker_1_hour_bucket_1" in names:
        print("  FAIL: the superseded two-key unique index was not dropped")
        ok = False
    new_name = "ticker_1_hour_bucket_1_signal_1"
    if new_name not in names:
        print(f"  FAIL: {new_name} was not created")
        ok = False
    elif not after[new_name].get("unique"):
        print(f"  FAIL: {new_name} is not unique")
        ok = False

    # 3. The behaviour the key change exists for: a verdict flip inside one
    #    hour must produce two rows, and a repeat must not.
    hour = datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc)
    for signal in ("HOLD", "SELL", "HOLD"):
        await db[COLL].update_one(
            {"ticker": "EXMP", "hour_bucket": hour, "signal": signal},
            {"$setOnInsert": {"ticker": "EXMP", "hour_bucket": hour,
                              "signal": signal},
             "$set": {"hour_bucket": hour}},
            upsert=True,
        )
    rows = await db[COLL].count_documents({"ticker": "EXMP"})
    if rows != 2:
        print(f"  FAIL: expected 2 rows for a HOLD/SELL/HOLD hour, got {rows}")
        ok = False
    else:
        print("  flip inside one hour writes 2 rows; the repeat dedupes")

    await client.drop_database(DB_NAME)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
