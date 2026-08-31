"""
System Status
─────────────
What is working, what is not, and what each answer costs the judgement.

This exists because of one sentence in `docs/10-due-diligence.md` §6.6:

    a degraded score still produces a verdict, and a composite assembled from
    three fallbacks at 0.5 looks identical in the API to one assembled from
    live data

Graceful degradation is the right design — a verdict on four factors beats no
verdict — but it is only defensible if the degradation is *visible*. Until now
it was not: the ticker page's own source panel asserted that Finnhub and FRED
were "Live" on a server that might hold neither key.

**The capability table below is the single source for both halves of the
answer.** `docs/12-how-a-trade-is-judged.md` explains what each system is worth;
this table states it in one line; the API serves it. The document and the page
therefore cannot drift, because the page is generated from the same strings the
document quotes.

**Three states are kept apart, and the third is the one that matters.**
`configured` (is there a key) is separate from `working` (did the last fetch
succeed), and a source with no key is **not broken** — it is a deliberate
absence, and painting it red is how a status page becomes something people stop
looking at. Same distinction `ResearchVetoStatus` draws between `enabled` and
`would_block`.

**Nothing here is probed.** See `services/source_health.py` for why.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.services import source_health as sh
from app.utils.helpers import is_market_hours, utcnow

__all__ = ["CAPABILITIES", "Capability", "build_status", "TIERS", "alters_scores"]

#: What losing a capability costs, worst first. The same three words the
#: document groups by and the status page renders as headings, so a reader
#: moving between them is never re-learning a vocabulary.
TIERS = ("stops", "behaviour", "quiet")

#: How long the last pipeline cycle may be silent before it is a problem —
#: measured only while the market is open, because the cycle deliberately does
#: not run outside it.
_CYCLE_STALE_AFTER = timedelta(minutes=20)


@dataclass(frozen=True)
class Capability:
    """
    One thing that can be working or not, and what it is worth.

    `impact` is the load-bearing field. A status row saying "FRED: failed"
    tells a trader nothing they can act on; "the macro factor is pinned to 0.50
    — 15% of every score" tells them exactly how much to discount the number in
    front of them. It is the same sentence the document uses.
    """

    id: str
    label: str
    tier: str
    #: The environment variable that switches this on, when one does.
    required_key: str | None
    #: What the system does *without* it. Present tense, plain words.
    impact: str
    #: The factor it feeds and that factor's default weight, where it feeds one.
    feeds: str | None = None
    #: Whether losing this changes a number the trader reads.
    #:
    #: Almost everything here does, and the one exception is the reason this
    #: field exists: alternative data is an *additive modifier centred on 0.50*,
    #: so an absent reading moves the composite by 0.00 rather than by a
    #: fallback. Its own `impact` line already says "costs exactly nothing" —
    #: and the banner was calling the whole system degraded on the strength of
    #: it, in a sentence that then claimed the factors it feeds had gone
    #: neutral. The row and the summary contradicted each other.
    #:
    #: This is the same judgement as refusing to paint an unset key red. A page
    #: that shouts about a failure which is arithmetically free is a page people
    #: stop opening, and then it is not there for the failure that matters.
    #: It suppresses the *banner and the alert*, never the row.
    alters_scores: bool = True


#: Ordered as a reader should meet them: what can stop trading, then what
#: changes the agent's behaviour, then what quietly thins a score.
CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        id="price", label="Price feed", tier="stops", required_key=None,
        impact="No bars, no cycle. Ingestion raises, so no score is written and "
               "no order is evaluated for that ticker — the previous verdict "
               "stays on screen and the agent does not act on it. Trading "
               "pauses rather than running on stale prices.",
        feeds="Technical and Volatility, and every price on the screen",
    ),
    Capability(
        id="database", label="Database", tier="stops", required_key="MONGODB_URL",
        impact="Nothing runs. Signals, trades, watchlists and settings all live "
               "here.",
    ),
    Capability(
        id="broker", label="Broker session", tier="stops",
        required_key="AUTO_TRADE_ENABLED",
        impact="Orders are refused, never silently lost. Entries retry on the "
               "next 5-minute cycle; a close you press reports the failure "
               "rather than claiming success. Reconciliation stops rather than "
               "reading an empty position list as a flat account.",
    ),
    Capability(
        id="analyst", label="AI analyst", tier="behaviour",
        required_key="ANTHROPIC_API_KEY",
        impact="Verdicts come from the rule-based path instead, which is a "
               "supported mode. But the analyst is what produces conviction, "
               "and without conviction a SEMI_AUTO account may not execute "
               "unattended — every entry becomes a proposal awaiting your "
               "approval. AUTO and MANUAL are unaffected.",
    ),
    Capability(
        id="scoring", label="Scoring model", tier="behaviour",
        required_key="ENABLE_ML_MODEL",
        impact="Scores come from the six weighted factors. The ML path is off "
               "by default and its model file does not ship, so this is the "
               "normal state — and the weighted path is the one whose numbers "
               "can be decomposed into a factor breakdown.",
    ),
    Capability(
        id="research", label="Deep research", tier="behaviour",
        required_key="RESEARCH_AGENTS_ENABLED",
        impact="No dossiers are built. The research veto has nothing to read "
               "and allows every entry — it fails open by design, because a "
               "guard that halts buying when a cron job misfires is a worse "
               "failure than one that occasionally lets a trade through.",
    ),
    Capability(
        id="sentiment", label="News sentiment", tier="quiet",
        required_key="FINNHUB_API_KEY",
        impact="The sentiment factor is pinned to 0.50 for every ticker — it "
               "stops distinguishing between names rather than scoring them "
               "badly. Headlines also disappear from the analyst's prompt.",
        feeds="Sentiment (0.20 of the composite by default)",
    ),
    Capability(
        id="macro", label="Macro environment", tier="quiet",
        required_key="FRED_API_KEY",
        impact="The macro factor is pinned to 0.50 market-wide, and the VIX "
               "spike that would otherwise force a fresh analyst read never "
               "fires.",
        feeds="Macro (0.15 of the composite by default)",
    ),
    Capability(
        id="fundamentals", label="Fundamentals", tier="quiet",
        required_key="MASSIVE_API_KEY / ALPHAVANTAGE_API_KEY",
        impact="The fundamental factor blends toward 0.50 in proportion to what "
               "is missing, so a thin read lands near neutral rather than "
               "scoring whatever happens to be available. Past the Alpha "
               "Vantage daily budget a ticker keeps Massive's cash-flow and "
               "balance-sheet fields but loses P/E, revenue growth and analyst "
               "consensus.",
        feeds="Fundamental (0.20) and part of Catalyst (0.15)",
    ),
    Capability(
        id="alternative", label="Options and insider flow", tier="quiet",
        required_key=None,
        impact="Costs exactly nothing. Alternative data is an additive modifier "
               "centred on 0.50, so an absent one moves the composite by 0.00 "
               "rather than by a fallback. The option chain is unkeyed "
               "best-effort scraping and misses a symbol regularly; that is "
               "shown here and is not worth a banner.",
        feeds="An additive ±0.05 modifier, not a weighted share",
        alters_scores=False,
    ),
)

_BY_ID = {c.id: c for c in CAPABILITIES}


def alters_scores(capability_id: str) -> bool:
    """
    Whether a failure in *capability_id* changes a number a trader reads.

    Exposed as a lookup rather than as a field on the served row so the flag
    stays a server-side judgement: both clients render `overall` and `summary`
    as given, and adding a boolean they could branch on is how web and mobile
    start disagreeing about what "degraded" means. Unknown ids answer `True` —
    a capability nobody classified is assumed to matter.
    """
    cap = _BY_ID.get(capability_id)
    return cap.alters_scores if cap else True


def _configured(cap: Capability, settings) -> bool:
    """
    Whether this deployment has switched the capability on.

    Read from computed properties on `Settings` rather than re-testing
    truthiness over `.env` here, so "is this key set" is decided in one place.
    """
    checks = {
        "sentiment": settings.finnhub_enabled,
        "macro": settings.fred_enabled,
        "fundamentals": settings.fundamentals_enabled,
        "analyst": settings.analyst_enabled,
        "research": settings.research_agents_enabled,
        "scoring": settings.enable_ml_model,
        "broker": settings.auto_trade_enabled,
    }
    return bool(checks.get(cap.id, True))


def _state_for(cap: Capability, record: dict | None, configured: bool) -> str:
    """The reading for one capability, from its stored record."""
    if cap.id == "database":
        # Answered by the fact that this call is happening. Reading the health
        # records required a successful query, so a row saying "no reading yet"
        # would be reporting an outage that provably is not occurring.
        return sh.OK
    if cap.id == "scoring":
        return _scoring_state(record, ml_on=configured)
    if not configured:
        # A deliberate absence. Never `failed` — see the module docstring.
        return sh.NOT_CONFIGURED
    if not record:
        return sh.NEVER_RUN
    return record.get("last_status") or sh.NEVER_RUN


def _scoring_state(record: dict | None, *, ml_on: bool) -> str:
    """
    Which scoring path is running, which is not the same as which is configured.

    Three cases and the third is the one worth surfacing. ML off is the normal,
    supported state and reads `ok`, not "not configured" — the weighted path is
    a first-class path, and calling it an absence would be false. ML on and
    genuinely running also reads `ok`. ML on while the weighted path is what
    actually produced the scores is `degraded`: the model file is gitignored
    and never reaches a deployed box, so this is what a server with
    ENABLE_ML_MODEL=true is really doing, and it used to be visible only in a
    log line nobody reads.
    """
    if not ml_on:
        return sh.OK
    method = (record or {}).get("method")
    if method is None:
        return sh.NEVER_RUN
    return sh.OK if method == "xgboost" else sh.DEGRADED


def build_status(
    settings,
    health: dict[str, dict],
    *,
    now: datetime | None = None,
    market_open: bool | None = None,
) -> dict:
    """
    The whole answer, as a plain dict. Pure — no I/O, no clock of its own.

    Written as a pure function over `(settings, health, now)` for the same
    reason `services/research/veto.py` is: the interesting cases are a missing
    key, a stale cycle at 3am, and a provider that failed twice, and none of
    them should need a database to test.

    `market_open` is injectable because the single most likely way to ship a
    status page nobody trusts is to report a total outage every night, when the
    pipeline is simply not scheduled to run.
    """
    now = now or utcnow()
    if market_open is None:
        market_open = is_market_hours()

    rows = []
    for cap in CAPABILITIES:
        configured = _configured(cap, settings)
        record = health.get(cap.id)
        state = _state_for(cap, record, configured)
        rows.append({
            "id": cap.id,
            "label": cap.label,
            "tier": cap.tier,
            "required_key": cap.required_key,
            "impact": cap.impact,
            "feeds": cap.feeds,
            "configured": configured,
            "state": state,
            "detail": _detail(cap, record, state),
            "last_success_at": sh.aware((record or {}).get("last_success_at")),
            "last_error": (record or {}).get("last_error"),
            "last_error_at": sh.aware((record or {}).get("last_error_at")),
            "consecutive_failures": int((record or {}).get("consecutive_failures") or 0),
        })

    cycle = _cycle(health.get("pipeline"), now=now, market_open=market_open)
    overall, summary = _verdict(rows, cycle, market_open=market_open)
    return {
        "overall": overall,
        "summary": summary,
        "checked_at": now,
        "market_open": market_open,
        "cycle": cycle,
        "capabilities": rows,
    }


def _detail(cap: Capability, record: dict | None, state: str) -> str:
    """One line naming what is actually happening, not what it would mean."""
    if cap.id == "database":
        return "Reachable — this reading came out of it."
    if cap.id == "scoring":
        method = (record or {}).get("method")
        if state == sh.DEGRADED:
            return ("ENABLE_ML_MODEL is on, but scores are coming from the "
                    "weighted path — the model file is not present on this "
                    "server.")
        if method == "xgboost":
            return "Scores are coming from the ML model."
        return "Scores are coming from the six weighted factors."

    # A sentence the writer supplied, for the states whose generic line gets it
    # wrong. "Deep research is switched on for this server but no account has
    # opted into it" is not something the status word can express, and it is the
    # difference between a fault and a setting. Always rewritten on the next
    # attempt, including to nothing, so it cannot outlive its condition.
    recorded = (record or {}).get("status_detail")
    if recorded:
        return recorded

    ok, total = (record or {}).get("tickers_ok"), (record or {}).get("tickers_total")
    if state == sh.NOT_CONFIGURED:
        if cap.required_key:
            return f"Not configured on this server — set {cap.required_key} to switch it on."
        return "Not configured on this server."
    if state == sh.NEVER_RUN:
        return "No reading yet — nothing has recorded a result for it."
    if state == sh.FAILED:
        failures = int((record or {}).get("consecutive_failures") or 0)
        suffix = f" ({failures} cycles in a row)" if failures > 1 else ""
        return f"Configured, and failing{suffix}."
    if state == sh.STALE:
        return "Serving a cached answer past its freshness window."
    if state == sh.DEGRADED:
        if total and ok:
            return (f"Answered for {ok} of {total} tickers on the last cycle. "
                    f"The rest fell back to neutral.")
        return "Answering, but with less than it should."
    if total:
        return f"Answered for {ok} of {total} tickers on the last cycle."
    return "Working."


def _cycle(record: dict | None, *, now: datetime, market_open: bool) -> dict:
    """
    Whether the pipeline itself is running.

    The precondition for reading anything else on the page: every source row
    describes the last cycle, so a cycle that has not happened for six hours
    makes all of them meaningless. Staleness is judged only while the market is
    open — outside it, silence is the design.
    """
    last = sh.aware((record or {}).get("last_cycle_at"))
    age_minutes = None if last is None else int((now - last).total_seconds() // 60)
    stale = bool(
        market_open and (last is None or now - last > _CYCLE_STALE_AFTER)
    )
    return {
        "last_run_at": last,
        "age_minutes": age_minutes,
        "stale": stale,
        "tickers_ok": (record or {}).get("tickers_ok"),
        "tickers_total": (record or {}).get("tickers_total"),
        "failed_tickers": (record or {}).get("failed_tickers") or [],
        "last_error": (record or {}).get("last_error"),
    }


def _names(rows: list[dict]) -> str:
    return ", ".join(r["label"] for r in rows)


def _verdict(rows: list[dict], cycle: dict, *, market_open: bool) -> tuple[str, str]:
    """
    One word and one sentence, decided on the server.

    Both clients render this rather than composing their own, so web and mobile
    cannot end up disagreeing about what "degraded" means — the same reasoning
    behind `restart_unavailable_reason`.

    **The headline word is decided on consequence, not on the count of red
    rows.** A failure that cannot change a number the trader reads is reported
    on its row and does not set the banner — see `Capability.alters_scores`.
    Not doing this is how the page came to say *degraded* while every weighted
    factor was live, on the strength of a Yahoo option chain that had missed one
    symbol; and the summary it generated then contradicted that row's own impact
    line by claiming the factors it fed had gone neutral.
    """
    failing = [r for r in rows if r["state"] == sh.FAILED]
    halting = [r for r in failing if r["tier"] == "stops"]

    if halting:
        return "halted", f"{_names(halting)} is not working. Trading is paused."
    if cycle["stale"]:
        age = cycle["age_minutes"]
        when = (
            f"the last analysis cycle ran {age} minutes ago"
            if age is not None else "no analysis cycle has run yet"
        )
        return "degraded", (
            f"The market is open but {when}. Everything below describes that "
            f"cycle."
        )

    material = [r for r in failing if alters_scores(r["id"])]
    if material:
        return "degraded", (
            f"{_names(material)} is failing. Scores still publish; the factors "
            f"it feeds are neutral placeholders until it recovers."
        )

    # Past this point the verdict is "ok". What is left still gets said — the
    # point is to stop it colouring the banner, not to hide it.
    free = [r for r in failing if not alters_scores(r["id"])]
    unconfigured = [r for r in rows
                    if r["state"] == sh.NOT_CONFIGURED and r["tier"] == "quiet"]

    parts = ["Everything that can move a score is working."
             if free else "Everything configured is working."]
    if free:
        parts.append(
            f"{_names(free)} is failing, which changes no score — it feeds an "
            f"additive modifier centred on neutral, so an absent reading moves "
            f"the composite by 0.00."
        )
    if unconfigured:
        plural = len(unconfigured) > 1
        parts.append(
            f"{_names(unconfigured)} {'are' if plural else 'is'} switched off "
            f"on this server, so the "
            f"{'factors they feed sit' if plural else 'factor it feeds sits'} "
            f"at neutral."
        )
    if len(parts) > 1:
        return "ok", " ".join(parts)
    if not market_open:
        return "ok", "Everything is working. The market is closed, so no cycle is due."
    return "ok", "Everything is working."
