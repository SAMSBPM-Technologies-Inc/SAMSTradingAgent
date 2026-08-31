"""
Source Health
─────────────
What each data source actually did, last time the pipeline asked it.

**Observed, never probed.** Nothing here makes a network call. Every fetch on
the fast path already reports what it did — `news.py` returns `no_api_key`,
`macro.py` returns `error`, `fundamentals_providers.py` returns
`massive+alphavantage` — and `stocks_raw` has been carrying those sentinels
since the pipeline was written. This module reads them and remembers the answer.

That is a deliberate refusal, not a shortcut, and it should survive the next
person who wants a "check now" button:

  * **A probe would spend the budget it is reporting on.** Alpha Vantage allows
    25 calls a day and `ALPHAVANTAGE_DAILY_BUDGET` is 22 against it. A status
    endpoint that verified Alpha Vantage on every page load would become the
    cause of the degradation it displays.
  * **A probe answers the wrong question.** "Can this container reach FRED at
    14:32" is not "did the macro factor behind the BUY on your screen come from
    FRED". A probe can be green while the 09:35 score was built on a fallback
    after a transient 429. Passive health *is* provenance, and provenance is
    what a trader is actually asking about.

The one legitimate live check in the system is the broker session, because it is
a property of this process right now rather than of a past fetch, and
`ibkr.is_connected()` is free. It already has an endpoint. It is not duplicated
here.

**Recording must never be able to fail a cycle.** Every write path swallows its
own exceptions, the same rule `_append_history` follows: losing a health record
costs a row on a status page, and losing a pipeline run costs a trading cycle.
"""
import re
from datetime import datetime, timezone

from app.db import COLL_SOURCE_HEALTH, get_db
from app.utils.helpers import utcnow
from app.utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "OK", "STALE", "DEGRADED", "FAILED", "NOT_CONFIGURED", "NEVER_RUN",
    "SOURCES", "classify", "observe", "flush", "record_subsystem",
    "record_attempt", "read_all", "scrub", "aware",
]

#: The source answered and the data is current.
OK = "ok"
#: A real provider answer, served from a cache past its freshness window. Still
#: data about the company, just not today's.
STALE = "stale"
#: Answering, but with less than it should — one provider of two, a cold cache
#: being backfilled, a budget already spent.
DEGRADED = "degraded"
#: Configured and erroring.
FAILED = "failed"
#: No key. **Not a fault** — it is a deliberate absence, and rendering it as one
#: is how a status page becomes something people stop looking at. The same
#: distinction `ResearchVetoStatus` draws between `enabled` and `would_block`.
NOT_CONFIGURED = "not_configured"
#: Nothing has been recorded yet — a fresh deployment, or a source that has not
#: been reached since the last restart.
NEVER_RUN = "never_run"

#: The data sources this module observes, in the order a reader should meet
#: them: the one that can stop a cycle first, then the weighted factors.
SOURCES = ("price", "sentiment", "macro", "fundamentals", "alternative")

#: Sentinels meaning the key is absent, per source. Everything else that is not
#: a known-good value is a failure.
_NOT_CONFIGURED = frozenset({"no_api_key"})

#: Sentinels that are a real answer even though they carry no data.
#:
#: `no_articles` is Finnhub replying "there is no news this week", which is a
#: measurement and a true one. `pending` is a cold fundamentals cache with a
#: backfill already scheduled — the system knows what it is missing and is
#: fetching it, which is a different state from a provider that failed.
_ANSWERED_EMPTY = {"no_articles": OK, "pending": DEGRADED, "none": DEGRADED}

_FAILURE_SENTINELS = frozenset({"error", "exception", "unavailable"})


def classify(source: str | None, *, stale: bool = False) -> str:
    """The health reading behind one `source` sentinel."""
    if not source or source == "unknown":
        return NEVER_RUN
    if source in _NOT_CONFIGURED:
        return NOT_CONFIGURED
    if source in _FAILURE_SENTINELS:
        return FAILED
    if source in _ANSWERED_EMPTY:
        return _ANSWERED_EMPTY[source]
    return STALE if stale else OK


#: Anything that could carry a credential. FRED and the fundamentals providers
#: put their keys in query strings, so an exception message that quotes the URL
#: it was fetching would write a live API key into a database row that a status
#: page then renders. Stripped before storage, not before display — a secret
#: that reached the database has already leaked.
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_KEYISH = re.compile(
    r"(?i)\b(api[_-]?key|apikey|token|secret|password)\b\s*[=:]\s*\S+"
)
_MAX_ERROR_CHARS = 200


def scrub(text: str | None) -> str | None:
    """An error message with any credential-bearing fragment removed."""
    if not text:
        return None
    cleaned = _URL.sub("[url]", str(text))
    cleaned = _KEYISH.sub("[redacted]", cleaned)
    return cleaned[:_MAX_ERROR_CHARS]


# ── Per-cycle accumulation ────────────────────────────────────────────────────
#
# One raw document per ticker carries every sentinel, so observing a cycle is a
# handful of dict reads rather than new plumbing threaded through five services.
# Repeats collapse in memory: thirteen tickers produce at most one write per
# source, not thirteen.

_pending: dict[str, dict] = {}


def observe(raw_doc: dict) -> None:
    """Record what each source did for one ticker. Pure, in-memory, free."""
    try:
        fund = raw_doc.get("fundamentals") or {}
        alt = raw_doc.get("alternative_data") or {}
        readings = {
            "price": (raw_doc.get("price_source"), False),
            "sentiment": ((raw_doc.get("sentiment_raw") or {}).get("source"), False),
            "macro": ((raw_doc.get("macro") or {}).get("source"), False),
            "fundamentals": (fund.get("source"), bool(fund.get("stale"))),
            "alternative": ((alt.get("options_flow") or {}).get("source"), False),
        }
        for source, (sentinel, stale) in readings.items():
            _accumulate(source, classify(sentinel, stale=stale), detail=sentinel)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("source_health_observe_failed", error=str(exc))


def _accumulate(source: str, status: str, *, detail: str | None = None) -> None:
    """
    Fold one reading into the pending record for *source*.

    The worst reading in a cycle wins. One ticker whose fundamentals came back
    empty is a real degradation even if twelve others were fine, and a record
    that reported the best of thirteen would be reassuring for the wrong reason.
    """
    entry = _pending.setdefault(
        source, {"status": OK, "ok": 0, "total": 0, "detail": detail}
    )
    entry["total"] += 1
    if status in (OK, STALE):
        entry["ok"] += 1
    if _SEVERITY[status] > _SEVERITY[entry["status"]]:
        entry["status"] = status
        entry["detail"] = detail


#: Ordering for "the worst reading wins". NEVER_RUN sits below OK: a source no
#: ticker reached is not evidence of a fault.
_SEVERITY = {
    NEVER_RUN: -1, OK: 0, STALE: 1, DEGRADED: 2, NOT_CONFIGURED: 3, FAILED: 4,
}


def _resolved(entry: dict) -> str:
    """
    The reading for a whole cycle, from the readings for each ticker.

    Worst-wins above decides *which* fault to name; this decides how bad it is,
    and the two are not the same question. A source that answered for twelve
    tickers and errored on the thirteenth has not failed — it degraded, which is
    the word `_accumulate`'s own docstring already uses for that case. Only a
    source nothing got an answer out of is `failed`.

    This is what left "Options and insider flow" permanently red. The option
    chain is unkeyed best-effort scraping of Yahoo and some symbol always
    misses, so one exception in thirteen was reporting the whole capability as
    down — which then set the banner to *degraded* on a server where every
    weighted factor was fine.
    """
    if entry["status"] == FAILED and entry["ok"] > 0:
        return DEGRADED
    return entry["status"]


def _update_for(source: str, status: str, now: datetime, *,
                detail: str | None = None, error: str | None = None,
                extra: dict | None = None) -> dict:
    """
    The Mongo update for one reading. Shared by the per-cycle flush and the
    per-attempt record so the two cannot disagree about what a status implies
    for `last_success_at`, `last_error` and the failure streak.
    """
    update: dict = {
        "$set": {
            "source": source,
            "last_status": status,
            "last_attempt_at": now,
            "last_detail": detail,
            **(extra or {}),
        },
    }
    if status == FAILED:
        # The streak counts whole-source outages, which is what the alerting
        # threshold is asking about. A cycle that answered for anybody breaks it.
        update["$inc"] = {"consecutive_failures": 1}
        update["$set"]["last_error_at"] = now
        update["$set"]["last_error"] = scrub(error if error is not None else detail)
    else:
        update["$set"]["consecutive_failures"] = 0
    return update


async def flush() -> None:
    """
    Write the accumulated readings. One bulk write of at most five upserts.

    Never raises. A health record that cannot be written is a gap on a status
    page; an exception here would be a lost trading cycle.
    """
    if not _pending:
        return
    readings = dict(_pending)
    _pending.clear()

    now = utcnow()
    try:
        from pymongo import UpdateOne

        db = await get_db()
        ops = []
        for source, entry in readings.items():
            status = _resolved(entry)
            extra = {"tickers_ok": entry["ok"], "tickers_total": entry["total"]}
            if entry["ok"]:
                # Recorded off the ticker count rather than off the status, so a
                # partially-failing cycle still says when the source last
                # answered anybody. That timestamp is the whole difference
                # between "flaky" and "gone".
                extra["last_success_at"] = now
            ops.append(UpdateOne(
                {"source": source},
                _update_for(source, status, now,
                            detail=entry.get("detail"), extra=extra),
                upsert=True,
            ))
        if ops:
            await db[COLL_SOURCE_HEALTH].bulk_write(ops, ordered=False)
    except Exception as exc:
        logger.warning("source_health_flush_failed", error=str(exc))


async def record_subsystem(name: str, status: str, **fields) -> None:
    """
    Store the state of something `stocks_raw` cannot see.

    Used for the pipeline cycle itself, the scoring path that actually ran, the
    Alpha Vantage budget, and the broker session — whose up/down state lived in
    module globals and was therefore reset by every deploy, which is the one
    thing an outage record must not be.
    """
    try:
        db = await get_db()
        await db[COLL_SOURCE_HEALTH].update_one(
            {"source": name},
            {"$set": {
                "source": name, "last_status": status,
                "last_attempt_at": utcnow(), **fields,
            }},
            upsert=True,
        )
    except Exception as exc:
        logger.warning("source_health_record_failed", source=name, error=str(exc))


async def record_attempt(name: str, status: str, *, error: str | None = None,
                         detail: str | None = None,
                         succeeded: bool | None = None, **fields) -> None:
    """
    Record one observed attempt at a subsystem, with the success/failure
    bookkeeping `flush` does for the sources.

    This exists because the analyst and the deep-research module had **no
    writer at all**. Neither touches `stocks_raw`, so `observe` cannot see them,
    and nothing called `record_subsystem` for them either — so their rows read
    "No reading yet" permanently, on a server where both were working. A status
    page that cannot tell "never instrumented" from "never ran" is reporting on
    itself rather than on the system.

    `detail` is a human sentence rendered in place of the generic line for the
    state, for the cases the state alone gets wrong — chiefly research being
    switched on for the server while no account has opted into it. It is always
    written, including as `None`, so a resolved condition cannot leave its
    explanation behind on the row.

    `succeeded` separates "did this produce something" from the status word,
    because `DEGRADED` covers both a run that delivered less than it should and
    one that delivered nothing at all, and only the first should move
    `last_success_at`.
    """
    try:
        now = utcnow()
        if succeeded is None:
            succeeded = status in (OK, STALE)
        db = await get_db()
        await db[COLL_SOURCE_HEALTH].update_one(
            {"source": name},
            _update_for(name, status, now, detail=detail, error=error,
                        extra={"status_detail": detail,
                               **({"last_success_at": now} if succeeded else {}),
                               **fields}),
            upsert=True,
        )
    except Exception as exc:
        logger.warning("source_health_record_failed", source=name, error=str(exc))


async def read_all() -> dict[str, dict]:
    """Every stored record, keyed by source. `{}` if unreadable."""
    try:
        db = await get_db()
        docs = await db[COLL_SOURCE_HEALTH].find({}).to_list(length=100)
        return {d["source"]: d for d in docs if d.get("source")}
    except Exception as exc:
        logger.warning("source_health_read_failed", error=str(exc))
        return {}


def aware(value) -> datetime | None:
    """A stored timestamp as tz-aware UTC. Mongo returns naive datetimes."""
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
