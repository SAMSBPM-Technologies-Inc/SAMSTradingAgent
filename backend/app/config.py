"""
Application configuration loaded from environment variables / .env file.
All settings have sensible defaults so the app runs locally without a .env.
"""
from functools import lru_cache
from typing import List

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Placeholder value shipped in the repo. Anyone who reads the source can forge
#: a token signed with it, which grants every endpoint including order
#: placement — so it is named here and checked at startup rather than left as a
#: default that silently works.
DEFAULT_JWT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── MongoDB ──────────────────────────────────────────────────────────────
    mongodb_url: str = Field(
        default="mongodb://localhost:27017",
        description="Full MongoDB connection URI",
    )
    mongodb_db_name: str = Field(default="trading_agent")

    # ── App ──────────────────────────────────────────────────────────────────
    app_env: str = Field(default="development")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    log_level: str = Field(default="INFO")
    # Comma-separated allowed CORS origins. Use "*" for dev, explicit domains for prod.
    cors_origins: str = Field(default="*")

    # ── Scheduler ────────────────────────────────────────────────────────────
    ingestion_interval_minutes: int = Field(default=5)

    # ── Tickers to watch ─────────────────────────────────────────────────────
    default_tickers: str = Field(default="PLTR,AAPL,TSLA,NVDA,MSFT")

    @property
    def ticker_list(self) -> List[str]:
        return [t.strip().upper() for t in self.default_tickers.split(",") if t.strip()]

    # ── Encryption ────────────────────────────────────────────────────────────
    # Fernet symmetric key for encrypting IBKR credentials at rest.
    # Generate with: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # NEVER rotate without first re-encrypting all existing ibkr_password_enc values.
    encryption_key: str = Field(default="", description="Base64-encoded Fernet key for IBKR credential encryption")

    # ── Broker recovery ───────────────────────────────────────────────────────
    #: Allow the UI to restart the IB Gateway container.
    #:
    #: OFF by default, and it should stay off unless you want it. Restarting
    #: another container requires mounting the host Docker socket into the API,
    #: which is effectively root on the host — anything that compromises the API
    #: process inherits it. The safe endpoint (`/trading/broker/reconnect`) needs
    #: none of this and fixes a stale session; a restart is only necessary when
    #: the gateway itself is unauthenticated, e.g. after IBKR's weekend
    #: maintenance window.
    allow_gateway_restart: bool = Field(
        default=False,
        description="Let the API restart the IB Gateway container via the "
                    "filtered Docker proxy — see docker-compose.prod.yml",
    )
    gateway_container_name: str = Field(default="trading_ibgateway")
    #: Filtered Docker API. The api container never sees the host socket; the
    #: `dockerproxy` sidecar holds it read-only and answers only the container
    #: endpoints. Empty disables the restart path regardless of the flag above.
    docker_proxy_url: str = Field(default="http://dockerproxy:2375")
    #: Alert when the broker has been disconnected for at least this long.
    #: Longer than the reconnect backoff ceiling (300s) so a routine blip that
    #: the loop recovers from on its own never pages anyone.
    broker_alert_after_minutes: int = Field(default=15)

    # ── Auth / JWT ────────────────────────────────────────────────────────────
    jwt_secret_key: str = Field(
        default=DEFAULT_JWT_SECRET,
        description="Secret key for signing JWTs — set a strong random value in production",
    )
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_hours: int = Field(default=24)

    # ── External API keys (all optional — services degrade gracefully if absent) ─
    finnhub_api_key: str = Field(default="", description="Finnhub.io API key for real news sentiment")
    fred_api_key: str = Field(default="", description="FRED API key for macro data")
    anthropic_api_key: str = Field(default="", description="Anthropic API key for AI analyst (Claude)")

    # ── Fundamentals providers ────────────────────────────────────────────────
    # yfinance 429s from this host, which left fundamental_score pinned at its
    # 0.5 fallback for every ticker. Massive (Polygon.io) supplies raw financial
    # statements; Alpha Vantage supplies ready-made ratios and analyst consensus.
    # BOTH cap at ~5 requests/minute and Alpha Vantage at 25/day, so neither can
    # be called per pipeline cycle — see fundamentals.py for the cache.
    massive_api_key: str = Field(default="", description="Massive (Polygon.io) API key for fundamentals")
    #: Where OHLCV bars come from. "yahoo" hits an undocumented endpoint with a
    #: browser User-Agent — fine for development, not licensed for commercial
    #: use. "polygon" is the licensed path and needs MASSIVE_API_KEY on a plan
    #: that includes aggregates. See services/price_providers.py.
    price_provider: str = Field(
        default="yahoo",
        description="OHLCV source: 'yahoo' (dev only, unlicensed) or 'polygon' (licensed)",
    )
    alphavantage_api_key: str = Field(default="", description="Alpha Vantage API key for fundamentals")
    #: What every realised return is measured against. Without this the engine
    #: had no way to distinguish a +6% signal in a +8% market from skill, and
    #: every threshold argued from that record was argued from the wrong
    #: number. Read through `services/benchmark.py`, which fails to `None`
    #: rather than to zero when the series cannot be fetched.
    benchmark_ticker: str = Field(
        default="SPY",
        description="Ticker realised returns are measured against for alpha",
    )
    # Fundamentals move quarterly; a day-old figure is not meaningfully staler
    # than a fresh one, and the rate limits make anything shorter unworkable.
    fundamentals_cache_hours: int = Field(default=24, description="Hours a cached fundamentals doc stays valid")
    # Alpha Vantage's free tier allows 25 calls/day. Held below that so an
    # ad-hoc refresh does not exhaust the budget the scheduled job needs.
    #
    # NOTE this budget now covers TWO call types — OVERVIEW and EARNINGS — and
    # a ~29-ticker watchlist cannot have both every day. That is why earnings
    # are cached for a week rather than a day: they change four times a year,
    # so a seven-day-old surprise history is not meaningfully staler than a
    # fresh one, and spacing the refreshes keeps both inside one budget. The
    # exception is a ticker about to report, which is exactly when the figure
    # stops being static — see `alphavantage_earnings_eager_days`.
    alphavantage_daily_budget: int = Field(default=22, description="Max Alpha Vantage calls per day")
    alphavantage_earnings_cache_days: int = Field(
        default=7,
        description="Days a cached earnings history stays valid before refresh",
    )
    alphavantage_earnings_eager_days: int = Field(
        default=7,
        description="Refresh earnings regardless of cache age when a report is this close",
    )
    # A newly watched ticker has no cached fundamentals until the daily job next
    # runs, so up to 24h of its scores carry a flat 0.5 for 0.15 of the
    # composite. ADBE was added on 21 Aug 2026 and scored with 0 of 5
    # fundamental components present — a mega-cap whose P/E, revenue growth and
    # cash flow are all public. The backfill closes that window without
    # reinstating per-read fetching, which is what produced the 429 storms.
    fundamentals_cold_start_backfill: bool = Field(
        default=True,
        description="Fetch fundamentals in the background the first time a ticker is seen with an empty cache",
    )
    # Providers legitimately have nothing for some symbols. Without a cooldown a
    # permanently empty ticker would re-fetch on every 5-minute pipeline run.
    fundamentals_cold_start_retry_minutes: int = Field(
        default=60,
        description="Minimum gap between cold-start backfill attempts for the same ticker",
    )

    # ── Broker / Automated Trading ────────────────────────────────────────────
    # Execution venue. "ibkr" = IB Gateway over TCP, "alpaca" = REST (no gateway).
    broker_provider: str = Field(default="ibkr", description="Execution venue: ibkr | alpaca")

    # IBKR port selection — READ THIS BEFORE CHANGING:
    #   Running IB Gateway in the ghcr.io/gnzsnz/ib-gateway container, IB Gateway
    #   binds its API to 127.0.0.1 ONLY (4001 live / 4002 paper). The image runs
    #   socat to republish those on 0.0.0.0 as 4003 (live) / 4004 (paper).
    #   → From another container or host, connect to 4003/4004. Using 4001/4002
    #     is refused and is the classic silent "never connects" failure.
    #   Bare-metal IB Gateway on the same host: 4001 live / 4002 paper.
    #   TWS instead of Gateway: 7496 live / 7497 paper.
    # CIRO NOTE: API-based automated trading is only permitted for US-listed securities.
    ibkr_host: str = Field(default="127.0.0.1")
    ibkr_port: int = Field(default=4004)          # 4004=paper relay, 4003=live relay
    ibkr_client_id: int = Field(default=1)
    ibkr_account_id: str = Field(default="")     # optional; leave empty for default account

    # Which IB Gateway session the container actually launched. This is the
    # ground truth about which account orders reach, and it selects the
    # credential pair and relay port at deploy time.
    # Distinct from auto_trade_live_allowed, which is a user-facing permission
    # gate — do not infer one from the other.
    trading_mode: str = Field(default="paper", description="IB Gateway session: paper | live")

    @property
    def is_live_trading(self) -> bool:
        return self.trading_mode.strip().lower() == "live"

    # ── Email (trade execution notifications) ─────────────────────────────────
    # Plain SMTP so any provider works (Google Workspace, Fastmail, SES, Resend's
    # SMTP bridge) without adding a dependency or tying the app to one vendor.
    # Leave smtp_host empty to disable email entirely — every other channel and
    # the trading path itself are unaffected.
    smtp_host: str = Field(default="", description="SMTP server hostname; empty disables email")
    smtp_port: int = Field(default=587, description="587 = STARTTLS, 465 = implicit TLS")
    smtp_username: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_from: str = Field(default="", description="From address; defaults to smtp_username")
    smtp_use_tls: bool = Field(default=True, description="STARTTLS on 587; ignored when port is 465")

    # Where the public contact form delivers. Separate from smtp_from: mail is
    # *sent* by the app's own mailbox and *addressed* here, so the reply-to on
    # a visitor's message is the visitor, and the From stays an address the
    # SMTP provider will actually authenticate.
    contact_email: str = Field(
        default="contact@samsbpm.com",
        description="Recipient for landing-page contact submissions",
    )

    # ── Access tiers ─────────────────────────────────────────────────────────
    #
    # Who the operator is, and how many tickers each tier may watch.
    #
    # `admin_email` is deliberately NOT injected by the deploy workflow, for
    # exactly the reason CONTACT_EMAIL is not: `_set_key` writes `KEY=` for an
    # unset variable, and an empty admin address means nobody can reach /admin
    # at all. It is defaulted here instead, and `main._check_admin_email`
    # reports a mismatch loudly on startup — being silently locked out of
    # provisioning is worse than being loudly locked out.
    admin_email: str = Field(
        default="sudheer.samudrala@samsbpm.com",
        description="Operator address(es), comma-separated; empty means nobody is admin",
    )

    # The ticker cap is the real cost control in this system, not a token
    # budget. Every watched ticker joins the union that `market_pipeline` runs
    # every five minutes on the deployment's own key, with an analyst call per
    # ticker — and `stocks_signals` is one shared document per ticker, so that
    # spend cannot be attributed to a user. Bounding the list at the point of
    # entry is what bounds the bill, which is why BASIC is capped too.
    tier_watchlist_cap_basic: int = Field(default=5, ge=0)
    tier_watchlist_cap_pro: int = Field(default=15, ge=0)

    # The one path where a PRO user spends the *server's* key: `force_refresh`
    # runs the pipeline, whose analyst call has no user_id and writes a shared
    # document. It cannot be moved onto the user's own key without restructuring
    # the pipeline, so it gets a quota instead of an entitlement.
    analysis_runs_per_day: int = Field(
        default=25, ge=1,
        description="Full-analysis runs per user per day (force_refresh)",
    )

    # Where a password-reset link points. The API and the web client are on
    # different hosts, so the server cannot derive this from the request — a
    # Host header is attacker-controlled, and building a reset link out of one
    # is how a reset email ends up pointing at somebody else's site.
    public_base_url: str = Field(
        default="https://sta.samsbpm.com",
        description="Public origin of the web client; used to build reset links",
    )

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_username and self.smtp_password)

    # ── Which capabilities this deployment actually has ──────────────────────
    #
    # "Is this key set" is decided here and nowhere else. The status endpoint,
    # the ticker page's source panel and the document all read these, so a
    # provider cannot be reported as configured in one place and absent in
    # another — which is exactly how the source panel came to claim Finnhub was
    # live on a server that had never held a Finnhub key.

    @property
    def finnhub_enabled(self) -> bool:
        return bool(self.finnhub_api_key)

    @property
    def fred_enabled(self) -> bool:
        return bool(self.fred_api_key)

    @property
    def fundamentals_enabled(self) -> bool:
        """Either provider is enough — they cover different fields."""
        return bool(self.massive_api_key or self.alphavantage_api_key)

    @property
    def analyst_enabled(self) -> bool:
        """
        Both halves are required, and the flag alone is the confusing state:
        `ENABLE_AI_ANALYST=true` with no key skips the analyst branch silently.
        """
        return bool(self.enable_ai_analyst and self.anthropic_api_key)

    @property
    def price_provider_licensed(self) -> bool:
        """
        Whether the price feed is licensed for production use.

        yfinance and the Yahoo chart API are licensed for personal and
        development use only. This is a legal question wearing the clothes of a
        configuration one, which is why it is answered here rather than by a
        badge hardcoded in a component.
        """
        return (self.price_provider or "yahoo").lower() != "yahoo"

    @property
    def email_from(self) -> str:
        return self.smtp_from or self.smtp_username

    # ── Funding limits ────────────────────────────────────────────────────────
    # Position size is a fraction of EQUITY, which says nothing about whether the
    # cash to pay for it exists. Sizing several positions off the same equity
    # figure silently borrows: eight 8% positions on a $1M account overshot into
    # roughly -$86k of margin. When false, entries are sized against settled cash
    # instead, so the agent cannot open a position it cannot pay for.
    allow_margin: bool = Field(
        default=False, description="Permit entries funded by margin rather than settled cash"
    )
    # Cash held back from sizing, as a fraction of equity. Absorbs commissions
    # and the slippage between a limit price and the actual fill, either of which
    # can otherwise tip a fully-deployed account into borrowing.
    cash_reserve_pct: float = Field(
        default=0.05, ge=0.0, le=0.50, description="Fraction of equity kept unspent"
    )

    # ── Protective exits ──────────────────────────────────────────────────────
    # Entries are submitted as bracket orders: the entry limit plus a take-profit
    # limit and a stop-loss, linked so that filling one cancels the other.
    # This matters because protection then lives at the broker: it survives this
    # app crashing, the gateway dropping, or the host going down. An unbracketed
    # position has no automatic exit at all — the app never sells on its own
    # outside of a SELL signal, and a SELL signal requires the app to be running.
    enable_bracket_orders: bool = Field(
        default=True, description="Submit entries as bracket orders (entry + stop + target)"
    )
    # Adding to a holding rather than refusing the signal. Off means the old
    # behaviour: a BUY on something already held is skipped.
    #
    # This is safe only because it is *one* bracket covering the whole position.
    # The refusal it replaces was never about owning the stock — it was that a
    # second entry attached a second, independent stop, and `execute_exit`
    # cancels every working order for a ticker while closing only the one
    # record it loads, so an exit left the remainder held and unprotected.
    # Scale-in cancels the working legs, submits the add with legs sized to the
    # combined holding, and updates the single position record in place.
    enable_scale_in: bool = Field(
        default=True, description="Allow a BUY on a held ticker to add to the position"
    )
    # ── Fee drag ──────────────────────────────────────────────────────────────
    # Commission is charged per order, not per share, so a small order is
    # arithmetically a bad order however good the signal behind it is. On
    # 25 Aug 2026 NVDA took eight orders in one morning, seven of them for one
    # or two shares — the position had reached its cap and the agent was
    # spending the sliver of room that rising equity freed up each cycle.
    #
    # Seven of those eight were *adds*, and that is the distinction the limits
    # below are built on.
    #
    # An opening entry has no alternative: refuse it and there is no position at
    # all, so the commission is simply the cost of participating, and a flat
    # dollar floor on entries just silences a small account entirely. An add
    # always has an alternative — do nothing, and the position carries on
    # unchanged — so an add has to justify its own ticket.
    #
    # Hence: no floor on entries by default, and the floor that does apply to
    # adds is a *fraction of the position* rather than a dollar figure, so it
    # scales with the account instead of needing to be re-tuned as it grows.
    # An add worth less than this share of what is already held moves the
    # position too little to be worth a commission.
    min_add_fraction: float = Field(
        default=0.25, ge=0.0, le=1.0,
        description="An add must be at least this fraction of the held position's cost",
    )
    # Absolute floor across every entry path, adds included. Off by default: at
    # a few thousand dollars of equity a $500 minimum refuses *every* order and
    # the agent does nothing at all, which looks like a broken tool rather than
    # a deliberate refusal. Worth setting once the account is large enough that
    # `position_size_pct` of it clears the floor comfortably — until then
    # `min_add_fraction` is doing the real work.
    min_order_notional: float = Field(
        default=0.0, ge=0.0,
        description="Absolute smallest order value; 0 disables. Refused, never rounded up",
    )
    # How far under the position's blended cost an add has to be. Without this
    # the only price condition on scaling in was "above the stop", so a standing
    # BUY bought into strength every cycle — the opposite of the dip-buying this
    # system exists to do. Measured against blended entry, which falls after
    # each add, so successive adds are self-spacing without needing a timer.
    scale_in_dip_pct: float = Field(
        default=0.02, ge=0.0, le=0.50,
        description="Price must be this far below blended entry before adding to a position",
    )
    # Hard ceiling on adds per position. The dip gate bounds *where* adds
    # happen; this bounds how many times you can pay commission to find out.
    max_scale_ins: int = Field(
        default=2, ge=0, le=10,
        description="Maximum number of adds allowed on one position",
    )
    # ── Selling the rip: moving a stop up as a position works ─────────────────
    #
    # Every automated exit here is decided BEFORE the position moves: the
    # bracket's stop and target are set at entry and, apart from a scale-in,
    # nothing revises them. So a name that ran 9% and reversed gave the whole
    # move back and stopped out at −5%, and the record could not even say that
    # had happened. `high_water_price` now records it; this decides what to do
    # about it.
    #
    # OFF BY DEFAULT, deliberately. A trailing stop trades a worse average exit
    # on winners for a smaller give-back, and which of those is the better deal
    # is an empirical question this deployment cannot answer yet — no closed
    # trade carries an excursion. Switch it on once `mfe_pct` and `gave_back_pct`
    # over a real sample say it is worth it. That is the same discipline as
    # `RESEARCH_VETO_ENABLED`: the measurement ships first and the behaviour is
    # argued from it.
    trailing_stop_enabled: bool = Field(
        default=False,
        description="Raise the stop as a position makes new highs. Never lowers one",
    )
    # Distance below the high-water mark. Wider than `bracket_stop_loss_pct`
    # because it is measured from the peak rather than from entry: an 8% trail
    # on a name up 20% still locks in ~10%, while a 5% trail sits inside the
    # daily range of most things this system watches and converts a winner into
    # a scratch on noise.
    trailing_stop_pct: float = Field(
        default=0.08, ge=0.01, le=0.50,
        description="Trailing stop distance below the high-water mark",
    )
    # The trail does not engage until the position has actually made money.
    # Without this it would tighten the stop on a position that never rose,
    # which is not trailing — it is just a tighter stop, and the entry already
    # chose one.
    trailing_stop_activate_pct: float = Field(
        default=0.06, ge=0.0, le=1.0,
        description="Gain above entry (at the peak) before the trail engages",
    )
    # Move the stop to cost once the position is up this much. Separate from the
    # trail and usually reached first — it is the cheapest risk reduction there
    # is, and unlike the trail it can never give back a profit it had. 0
    # disables it. Note this is break-even on PRICE, not net of commission:
    # rounding the stop up to cover fees would put it above the level the
    # position was sized against, and `commission_paid` is not knowable at the
    # time this runs.
    breakeven_trigger_pct: float = Field(
        default=0.04, ge=0.0, le=1.0,
        description="Gain above entry before the stop moves to cost; 0 disables",
    )
    # An order costs money to place and reconciliation runs every two minutes,
    # so a trail with no step limit is a cancel-and-replace pair every pass for
    # as long as a position keeps ticking up. This is the same rate-limiting
    # instinct as `MIN_ADD_FRACTION` on the entry side: the stop only moves when
    # the move is worth an order.
    trailing_stop_min_step_pct: float = Field(
        default=0.01, ge=0.0, le=0.20,
        description="Smallest upward stop move worth cancelling and replacing for",
    )

    # Fallbacks used when the AI analyst supplies no usable level, or supplies
    # one that fails validation (stop above entry, target below entry, etc).
    bracket_stop_loss_pct: float = Field(
        default=0.05, ge=0.005, le=0.50, description="Stop distance below entry, as a fraction"
    )
    bracket_take_profit_pct: float = Field(
        default=0.10, ge=0.005, le=2.00, description="Target distance above entry, as a fraction"
    )

    # ── Alpaca (alternative venue; used when BROKER_PROVIDER=alpaca) ──────────
    alpaca_api_key: str = Field(default="")
    alpaca_api_secret: str = Field(default="")
    # Leave empty to derive from paper/live automatically.
    alpaca_base_url: str = Field(default="", description="Override Alpaca API base URL")
    auto_trade_enabled: bool = Field(default=False, description="Global kill-switch for automated trading")
    auto_trade_live_allowed: bool = Field(default=False, description="Allow live (non-paper) trading")

    # ── Feature flags ─────────────────────────────────────────────────────────
    enable_ml_model: bool = Field(default=False)
    enable_backtesting: bool = Field(default=False)
    enable_ai_analyst: bool = Field(default=False, description="Use Claude AI analyst instead of rule-based signal")
    # Sonnet 5 reaches near-Opus quality on this kind of structured analysis at
    # $3/$15 per MTok against Opus's $5/$25. Output dominates the bill here
    # (thinking tokens are billed as output), so the output rate is what matters.
    analyst_model: str = Field(default="claude-sonnet-5", description="Claude model for AI analyst")
    # Adaptive thinking: Claude decides how hard to think per request rather than
    # spending a fixed budget on every call. Depth is steered by analyst_effort.
    analyst_extended_thinking: bool = Field(default=True, description="Enable Claude adaptive thinking for AI analyst")
    # low | medium | high | xhigh | max. medium is roughly Sonnet 4.6 at high and
    # is ample for a note written from data already assembled for the model.
    analyst_effort: str = Field(default="medium", description="Thinking/effort level for the AI analyst")

    # ── Analyst call gating ───────────────────────────────────────────────────
    # A Claude call is only worth making where its judgment can change the
    # outcome. BUY fires above 0.70 and SELL below 0.30, so a ticker sitting at
    # 0.47 produces the same HOLD whether or not a research note is written —
    # and that described nearly every call: 592 of 602 recorded signals were
    # HOLD. Away from the thresholds the rule-based path is used instead.
    #
    # The margin is measured from the live thresholds in signal_generator rather
    # than as an absolute band, so the two cannot drift apart. At the default,
    # Claude is called when score >= 0.62 or <= 0.38.
    analyst_gate_enabled: bool = Field(default=True, description="Only call Claude near a decision boundary")
    analyst_gate_margin: float = Field(
        default=0.08,
        description="How close to the BUY/SELL threshold a score must be to justify a Claude call",
    )
    # Open positions are analysed at any score. This is the larger share of the
    # remaining spend, and it is the share worth paying: once capital is
    # committed the exit decision is the most consequential call the analyst
    # makes. Set false to gate holdings on the margin like everything else.
    analyst_always_analyse_holdings: bool = Field(
        default=True,
        description="Always analyse tickers with an open position, regardless of score",
    )

    # Analysis caching — Claude is only re-called when one of these triggers fires:
    #   1. Last analysis is older than analyst_cache_minutes
    #   2. Price has moved >= analyst_price_change_pct since last analysis
    #   3. Composite score has shifted >= analyst_score_change_threshold
    #   4. VIX is >= analyst_vix_spike_threshold (fear spike → re-evaluate everything)
    analyst_cache_minutes: int = Field(default=60, description="Minutes before Claude re-analyzes a ticker unconditionally")
    # The analyst is called on every open position because "the exit decision is
    # worth paying for at any score". It was never TOLD a position was open — no
    # holding flag, no cost basis, no working levels — so it answered "would I
    # buy this?" and its SELL meant "this is a bad name to own" rather than
    # "take the profit". On a rip, where the company still looks excellent and
    # only the price is extended, that is exactly the wrong question.
    analyst_position_context: bool = Field(
        default=True,
        description="Tell the analyst when a position is open, and at what cost",
    )
    analyst_price_change_pct: float = Field(default=0.03, description="Price move threshold (fraction) that triggers re-analysis")
    analyst_score_change_threshold: float = Field(default=0.12, description="Composite score shift that triggers re-analysis")
    analyst_vix_spike_threshold: float = Field(default=30.0, description="VIX level that forces re-analysis of all tickers")

    # ── Relative scoring ──────────────────────────────────────────────────────
    # Judge a score against the rest of the watchlist rather than against a
    # fixed cutoff. See `services/cross_section.py` for the arithmetic; the
    # short version is that coverage weighting, a common-mode macro factor and
    # a zeroed volatility weight leave the composite clustered near 0.567 with
    # a realistic ceiling around 0.75, against a BUY threshold of 0.70. An
    # absolute cutoff on that distribution mostly selects for how much data
    # happened to be available.
    #
    # **Off by default, and it should be turned on deliberately.** It changes
    # which names the agent buys on a system that places real orders, and the
    # honest position is that nothing has yet measured whether the relative
    # rule ranks outcomes better than the absolute one —
    # `/performance/calibration` is what will answer that, and it needs about
    # twenty trading days of settled history under the new rule before it can.
    #
    # The thresholds themselves are NOT here. `signal_generator` owns every
    # threshold in this system and everything else imports them; a second copy
    # in config is exactly how `compute_personalized_score` ended up scoring
    # users against a rule the pipeline had stopped using.
    enable_rank_signals: bool = Field(
        default=False,
        description="Classify on percentile within the watchlist, not an absolute cutoff",
    )

    # ── Signal stability ──────────────────────────────────────────────────────
    # A verdict is published only once it holds. HXL alerted eight times in an
    # hour on 24 Aug 2026 — BUY/HOLD/BUY/HOLD at an unchanged score of 0.61 —
    # because every single evaluation went straight to the user's phone. A
    # borderline score genuinely does flip; broadcasting each flip converts an
    # honest "we don't know" into eight confident-looking contradictions.
    #
    # See services/signal_stability.py. SELL is exempt from both settings:
    # delaying an exit costs money, delaying an entry costs an opportunity, and
    # those are not the same price.
    signal_confirmations: int = Field(
        default=2, ge=1, le=10,
        description="Consecutive fresh evaluations agreeing before a new verdict is published",
    )
    # Measured against the *published* verdict, so this is the floor on how
    # often a ticker can change its mind in public. At the default a ticker
    # cannot flip more than once an hour no matter what the analyst says.
    signal_min_dwell_minutes: int = Field(
        default=60, ge=0, le=1440,
        description="Minutes a published verdict must stand before it can be replaced",
    )

    # ── Technical stance ──────────────────────────────────────────────────────
    # mean_reversion | momentum | blended
    #
    # Previously implicit. The original component weights blended two opposing
    # philosophies without declaring either: RSI/Bollinger/Stochastic score
    # higher as price weakens, MACD/MA-cross score higher as it strengthens, and
    # at 60/40 the mean-reversion side silently held the majority. The model was
    # a dip-buyer by accident rather than by decision.
    #
    # Defaults to mean_reversion because that is what the product already
    # assumes — the watchlist's ENTRY trigger is a dip-buy setup (see
    # services/setup_scan.py). Under `momentum` the mean-reversion components
    # are inverted, not merely reweighted, and those thresholds would need to
    # invert with them.
    technical_stance: str = Field(
        default="mean_reversion",
        description="How technical signals are read: mean_reversion | momentum | blended",
    )

    # ── Deep research (agent orchestrator) ────────────────────────────────────
    # A second, slower analysis path, separate from the 5-minute pipeline. It
    # fans out four scoped agents over one shared evidence ledger and then
    # synthesises them, so a dossier costs five calls rather than one. That is
    # affordable on demand and once a day; it is not affordable per cycle, and
    # nothing in the fast path may come to depend on it.
    research_agents_enabled: bool = Field(
        default=False, description="Enable the deep-research agent orchestrator"
    )
    # Judgement-heavy roles — the adversarial risk pass and the synthesis — run
    # on the stronger model. The three descriptive specialists do not need it,
    # and running all five on the top model is most of the cost for little of
    # the benefit.
    research_orchestrator_model: str = Field(
        default="claude-opus-5",
        description="Model for the risk agent and the synthesiser",
    )
    research_specialist_model: str = Field(
        default="claude-sonnet-5",
        description="Model for the fundamentals, technical and news agents",
    )
    research_effort: str = Field(
        default="high", description="Thinking/effort level for research agents"
    )
    research_extended_thinking: bool = Field(
        default=True, description="Enable adaptive thinking for research agents"
    )
    # How long a dossier stays fresh before the UI marks it stale and the veto
    # stops trusting it. A day, matching the scheduled refresh.
    research_dossier_ttl_hours: int = Field(
        default=24, description="Hours before a dossier is considered stale"
    )
    research_daily_refresh_hour: int = Field(
        default=6, description="Local-time hour for the daily dossier refresh job"
    )

    # ── Research veto (entry guard) ───────────────────────────────────────────
    # Research may block a BUY. It may never create one, enlarge one, or touch
    # an exit — see `_prepare_entry`. Off by default: a guard that can stop
    # trades has to be switched on deliberately, having been measured first.
    # ── Rebuttal ──────────────────────────────────────────────────────────────
    # One exchange between the risk agent and the evidence, after both sides
    # have already written independently. Costs two orchestrator calls per
    # dossier — roughly +40% on the deep path — and is on by default because it
    # is the step that changes the verdict: a risk nobody ever replies to is
    # carried into the synthesis at full strength whether or not the evidence
    # answers it.
    #
    # Capped at one in practice. Successive rounds converge on agreement, each
    # side softening toward the other, which reads as resolution and is not.
    research_debate_rounds: int = Field(
        default=1,
        description="Rebuttal exchanges between the risk agent and the evidence (0 disables)",
    )

    # ── Sentiment breadth ─────────────────────────────────────────────────────
    # Retail chatter and funded probabilities, as research *evidence* only.
    # Deliberately not wired into the composite score: adding a factor would
    # change every published signal and invalidate the settled history the
    # calibration work reads. Both sources are development-grade — undocumented
    # endpoints, no licence, no SLA — and both fail to absent rather than to a
    # neutral reading.
    social_sentiment_enabled: bool = Field(
        default=False,
        description="Collect StockTwits and Reddit chatter as research evidence",
    )
    prediction_markets_enabled: bool = Field(
        default=False,
        description="Collect Polymarket macro probabilities as research evidence",
    )

    # ── Risk stance panel ─────────────────────────────────────────────────────
    # Three temperaments reading the *trade* rather than the company. Purely
    # advisory: nothing in the trading guard chain reads the output, and no
    # order quantity moves because of it. Off by default — three more calls per
    # dossier for a reading that currently informs a human and nothing else.
    research_stance_panel_enabled: bool = Field(
        default=False,
        description="Run the advisory aggressive/conservative/neutral stance panel",
    )

    # ── Outcome memory ────────────────────────────────────────────────────────
    # How long after a dossier is written before it is graded, and how much of
    # that record is shown to the next reading of the same name. Nothing here
    # can raise a conviction: the derived anchor is computed from company data
    # alone and the synthesiser is still clamped to +/-15 of it, so a lesson can
    # temper a reading and can never manufacture one.
    research_outcome_horizon_days: int = Field(
        default=20,
        description="Days after a dossier is written before its outcome is settled",
    )
    research_memory_same_ticker: int = Field(
        default=5, description="Resolved prior readings of this ticker shown to agents"
    )
    research_memory_cross_ticker: int = Field(
        default=3, description="Resolved readings of other tickers shown to agents"
    )

    research_veto_enabled: bool = Field(
        default=False, description="Allow a research dossier to block a BUY"
    )
    research_veto_min_conviction: float = Field(
        default=35.0,
        description="Block a BUY when dossier conviction is below this (0-100)",
    )
    # A stale dossier never vetoes. Fail-open is the deliberate choice: the
    # alternative is that a scheduler outage silently stops all trading, which
    # is a worse failure than trading without the extra check.
    research_veto_max_age_hours: int = Field(
        default=48, description="Ignore dossiers older than this when vetoing"
    )

    # ── Scoring weights (7 base weights must sum to 1.0) ──────────────────────
    #
    # weight_volatility defaults to 0.0 — volatility is priced at the risk gate,
    # not in the alpha score.
    #
    # It used to be counted twice. `volatility_score` took 0.10 of the composite
    # (quieter = higher), and volatility separately supplies up to 7 of the 10
    # risk points, where risk_score >= 6 vetoes a BUY outright. A high-beta name
    # was marked down in the ranking and then blocked at the gate for the same
    # fact. The two are not redundant by accident: the gate is the correct place
    # for it, because it answers "is this too dangerous to hold", whereas the
    # composite answers "is this the better opportunity" — and a stock is not a
    # better opportunity for being quiet. Scoring it as one imported a standing
    # bias toward low-volatility names that says nothing about expected return.
    #
    # The freed 0.10 goes to the two dimensions that do express opportunity:
    # +0.05 technical (the timing edge, now that the trend gate makes it
    # discriminate) and +0.05 fundamental (quality). The knob is kept rather than
    # deleted so the behaviour stays recoverable, and per-user tuning is
    # unaffected — that lives in users.scoring_weights, not here.
    weight_technical:    float = Field(default=0.30)
    weight_fundamental:  float = Field(default=0.20)
    weight_sentiment:    float = Field(default=0.20)
    weight_macro:        float = Field(default=0.15)
    weight_volatility:   float = Field(default=0.00)
    weight_catalyst:     float = Field(default=0.15)
    # weight_momentum defaults to 0.0 — the factor is computed and stored on
    # every cycle, and contributes nothing until somebody raises this.
    #
    # See services/momentum.py. The short version: under
    # `technical_stance=mean_reversion` trend enters `_technical_score` only as
    # a multiplier capped at 1.0, so momentum could never add a point, and an
    # extended market leader scored 0.037 technically against a falling knife's
    # 0.391. There is no other rate-of-change or relative-strength term in the
    # composite, which is why the engine cannot express "this is working".
    #
    # It ships at 0.00 for the reason `enable_rank_signals` ships off and
    # `RESEARCH_VETO_ENABLED` ships off: it changes which names an agent with
    # real money buys, and nothing has measured whether it ranks outcomes
    # better yet. `/performance/calibration` answers that, and needs about
    # twenty trading days of settled history under it first.
    #
    # Raising it requires taking the weight from somewhere — the sum check
    # below enforces that. `weight_macro` is the candidate worth considering
    # first: it is market-wide by construction, so it shifts every ticker in
    # the watchlist by the same amount and cannot rank any two against each
    # other. Momentum is the opposite by construction, since the benchmark leg
    # removes exactly the common mode macro is made of.
    weight_momentum:     float = Field(default=0.00)
    # Alternative data weight: additive modifier applied on top of the 6-weight
    # base score, so it does NOT participate in the sum-to-1.0 constraint.
    # score = base_score + weight_alt * (alt_score - 0.5)
    # A value of 0.10 means alt data can shift the composite by ±0.05.
    weight_alternative_data: float = Field(default=0.10)

    @model_validator(mode="after")
    def validate_weights_sum(self) -> "Settings":
        total = (
            self.weight_technical
            + self.weight_fundamental
            + self.weight_sentiment
            + self.weight_macro
            + self.weight_volatility
            + self.weight_catalyst
            + self.weight_momentum
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Scoring weights must sum to 1.0, got {total:.6f}. "
                "Check weight_technical, weight_fundamental, weight_sentiment, "
                "weight_macro, weight_volatility, weight_catalyst, "
                "weight_momentum in .env"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton Settings instance."""
    return Settings()
