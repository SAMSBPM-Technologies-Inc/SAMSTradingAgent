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
    # Fundamentals move quarterly; a day-old figure is not meaningfully staler
    # than a fresh one, and the rate limits make anything shorter unworkable.
    fundamentals_cache_hours: int = Field(default=24, description="Hours a cached fundamentals doc stays valid")
    # Alpha Vantage's free tier allows 25 calls/day. Held below that so an
    # ad-hoc refresh does not exhaust the budget the scheduled job needs.
    alphavantage_daily_budget: int = Field(default=22, description="Max Alpha Vantage calls per day")
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

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_username and self.smtp_password)

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
    analyst_price_change_pct: float = Field(default=0.03, description="Price move threshold (fraction) that triggers re-analysis")
    analyst_score_change_threshold: float = Field(default=0.12, description="Composite score shift that triggers re-analysis")
    analyst_vix_spike_threshold: float = Field(default=30.0, description="VIX level that forces re-analysis of all tickers")

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

    # ── Scoring weights (6 base weights must sum to 1.0) ──────────────────────
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
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Scoring weights must sum to 1.0, got {total:.6f}. "
                "Check weight_technical, weight_fundamental, weight_sentiment, "
                "weight_macro, weight_volatility, weight_catalyst in .env"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton Settings instance."""
    return Settings()
