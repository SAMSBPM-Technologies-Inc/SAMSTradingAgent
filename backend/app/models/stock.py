"""
Pydantic models / schemas shared across routes and services.

MongoDB documents are stored as plain dicts; these models handle
API request/response validation and serialisation.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ── Raw ingested price data ───────────────────────────────────────────────────

class PriceBar(BaseModel):
    """Single OHLCV bar as returned by yfinance."""
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class StockRaw(BaseModel):
    """Document stored in `stocks_raw` collection."""
    ticker: str
    ingested_at: datetime
    bars: list[PriceBar]
    current_price: float
    day_change_pct: float  # % change vs previous close


# ── Computed features ─────────────────────────────────────────────────────────

class StockFeatures(BaseModel):
    """Document stored in `stocks_features` collection."""
    ticker: str
    computed_at: datetime
    current_price: float

    # Technical indicators
    rsi_14: Optional[float] = None         # 0–100
    ma_20: Optional[float] = None
    ma_50: Optional[float] = None
    ma_cross_bullish: Optional[bool] = None  # ma_20 > ma_50
    volatility_20d: Optional[float] = None  # annualised std-dev of returns

    # Derived sub-scores (0–1 each)
    technical_score: float = 0.0
    sentiment_score: float = 0.0          # mocked until real feed exists
    volatility_score: float = 0.0         # inverse of volatility

    # Composite
    composite_score: float = 0.0          # weighted sum


# ── Risk assessment ───────────────────────────────────────────────────────────

class RiskAssessment(BaseModel):
    risk_score: float = Field(..., ge=0, le=10)
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    explanation: str


# ── Score attribution ─────────────────────────────────────────────────────────

class FactorContribution(BaseModel):
    """One sub-score and the share of the composite it supplied."""
    key: str
    label: str
    score: float = Field(..., description="Sub-score, 0–1")
    weight: float
    contribution: float = Field(
        ...,
        description="Points of the composite from this factor. Signed for the "
                    "alternative-data modifier, which can drag the score down.",
    )


class ScoreBreakdown(BaseModel):
    """
    Where the composite came from. The sub-scores were always computed and
    stored; nothing returned them until this model existed.
    """
    method: str = Field(..., description="'weighted' or 'xgboost'")
    attributable: bool = Field(
        ...,
        description="False on the XGBoost path, where the weights did not "
                    "produce the score and a weighted decomposition would be "
                    "a fabrication.",
    )
    personalized: bool = Field(..., description="Whether the user's own weights were applied")
    factors: list[FactorContribution]
    alternative_data: Optional[FactorContribution] = None
    base_total: float
    composite: float


class SignalGate(BaseModel):
    """
    The thresholds behind the verdict, so the UI can explain a signal instead of
    restating the rule in its own hardcoded copy.
    """
    buy_threshold: float
    sell_threshold: float
    risk_max_for_buy: float
    score_passes_buy: bool
    risk_passes_buy: bool


# ── Signal ────────────────────────────────────────────────────────────────────

SignalType = Literal["BUY", "SELL", "HOLD"]


class TradingSignal(BaseModel):
    """Document stored in `stocks_signals` collection + API response."""
    ticker: str
    generated_at: datetime

    # Scores
    score: float = Field(..., ge=0, le=1, description="Composite AI score 0–1")
    risk: RiskAssessment

    # Signal
    signal: SignalType
    confidence: float = Field(..., ge=0, le=1)
    entry_suggestion: Optional[str] = None
    exit_suggestion: Optional[str] = None
    explanation: str


# ── API response schemas ──────────────────────────────────────────────────────

class AnalyzeResponse(BaseModel):
    ticker: str
    score: float
    risk: RiskAssessment
    signal: SignalType
    confidence: float
    entry_suggestion: Optional[str] = None
    exit_suggestion: Optional[str] = None
    explanation: str
    generated_at: datetime
    # AI analyst fields (present when ENABLE_AI_ANALYST=true)
    conviction: Optional[str] = None
    price_target: Optional[float] = None
    stop_loss: Optional[float] = None
    time_horizon: Optional[str] = None
    thesis: Optional[str] = None
    analyst_note: Optional[str] = None
    bull_case: Optional[str] = None
    bear_case: Optional[str] = None
    key_risks: list[str] = []
    catalysts: list[str] = []
    # Alternative data
    alternative_data: Optional[dict] = None
    # Current price snapshot
    current_price: Optional[float] = None
    day_change_pct: Optional[float] = None
    # Provenance. The UI used to hardcode a model name in TSX and drifted from
    # what the server actually calls; these two carry the truth instead.
    # analyst_used is per-document (the analyst is gated and falls back to the
    # rule-based path), analyst_model is this server's configured model.
    analyst_used: bool = False
    analyst_model: Optional[str] = None
    # A verdict this ticker has produced but not yet earned. The stability layer
    # withholds a flip until it repeats, so without this field a ticker sitting
    # on a threshold would look settled when it is anything but — which is the
    # opposite of the honesty the debounce is there to buy. None when the
    # published verdict is the only one on the table.
    pending_signal: Optional[SignalType] = None
    # Score attribution and the gate behind the verdict. Optional because the
    # feature document is not always reachable (a signal can outlive the
    # features it was built from), and a missing breakdown is not an error.
    breakdown: Optional[ScoreBreakdown] = None
    gate: Optional[SignalGate] = None


class AnalystReport(BaseModel):
    """Full analyst report — returned by GET /report/{ticker}."""
    ticker: str
    score: float
    risk: RiskAssessment
    signal: SignalType
    confidence: float
    conviction: Optional[str] = None
    price_target: Optional[float] = None
    stop_loss: Optional[float] = None
    time_horizon: Optional[str] = None
    thesis: Optional[str] = None
    bull_case: Optional[str] = None
    bear_case: Optional[str] = None
    key_risks: list[str] = []
    catalysts: list[str] = []
    analyst_note: Optional[str] = None
    entry_suggestion: Optional[str] = None
    exit_suggestion: Optional[str] = None
    explanation: str
    generated_at: datetime


class SignalListResponse(BaseModel):
    count: int
    signals: list[AnalyzeResponse]


class SignalSummary(BaseModel):
    """Portfolio-level signal summary across all tracked tickers."""
    total_tickers: int
    buy_count: int
    sell_count: int
    hold_count: int
    avg_score: float
    avg_confidence: float
    high_conviction_tickers: list[str]   # conviction=HIGH or confidence≥0.75
    signals: list[AnalyzeResponse]


class WatchlistItem(BaseModel):
    """
    One watched ticker, carrying both projections that used to be split across
    /watchlist and /signals/dip-buy: the scored verdict (signal, conviction,
    thesis) and the timing setup (trigger + the indicators behind it).

    A ticker with no signal document yet is still returned, as signal="PENDING"
    with score 0 — the old /watchlist iterated the signals collection and so
    silently dropped freshly-added tickers until the pipeline caught up.
    """
    ticker: str
    signal: str
    score: float
    confidence: float
    conviction: Optional[str] = None
    current_price: Optional[float] = None
    day_change_pct: Optional[float] = None
    price_target: Optional[float] = None
    thesis: Optional[str] = None
    generated_at: datetime

    # ── Timing setup (formerly the Alpha Radar dip-buy scan) ──────────────────
    #: "ENTRY" | "EXIT_ALERT" | "NEUTRAL" | "PENDING" (no feature data yet)
    trigger: str = "PENDING"
    rsi_14: Optional[float] = None
    stoch_rsi: Optional[float] = None
    bb_pct: Optional[float] = None          # 0=lower band, 1=upper band
    ma_20: Optional[float] = None
    volume_anomaly: Optional[float] = None  # latest vol / 20d avg
    pct_from_ma20: Optional[float] = None   # (price - ma20) / ma20 * 100
    computed_at: Optional[datetime] = None  # when the indicators were computed


class WatchlistSetupCounts(BaseModel):
    """Trigger tallies for the filter bar, so the client needn't recount."""
    entry: int = 0
    exit_alert: int = 0
    neutral: int = 0
    pending: int = 0


class WatchlistResponse(BaseModel):
    count: int
    items: list[WatchlistItem]
    setups: WatchlistSetupCounts = WatchlistSetupCounts()


class TickerAddRequest(BaseModel):
    ticker: str


class TickerAddResponse(BaseModel):
    ticker: str
    status: str
    message: str


class SignalPerformanceRecord(BaseModel):
    signal: str
    total: int
    settled: int          # records with realized return
    correct: int          # BUY that went up / SELL that went down
    win_rate: Optional[float] = None
    avg_return_20d: Optional[float] = None


class PerformanceResponse(BaseModel):
    total_signals: int
    settled_signals: int
    overall_win_rate: Optional[float] = None
    overall_avg_return_20d: Optional[float] = None
    by_signal: list[SignalPerformanceRecord]
    by_ticker: list[dict]


class HealthResponse(BaseModel):
    status: str
    db_connected: bool
    version: str = "1.5.0"
    #: True when JWT_SECRET_KEY is still the placeholder shipped in the repo,
    #: which means tokens can be forged. Surfaced here because it is otherwise
    #: invisible — the deployment works perfectly with a guessable signing key.
    #: Not gated behind auth deliberately: a forgeable signer makes auth
    #: meaningless anyway, and the operator needs to see it without logging in.
    auth_secret_is_default: bool = False


# ── Dip-buy scan ──────────────────────────────────────────────────────────────

class DipBuyCandidate(BaseModel):
    """A single stock matching dip-buy entry or exit-alert criteria."""
    ticker: str
    current_price: float
    rsi_14: Optional[float] = None
    stoch_rsi: Optional[float] = None
    bb_pct: Optional[float] = None          # 0=lower band, 1=upper band
    ma_20: Optional[float] = None
    volume_anomaly: Optional[float] = None  # latest vol / 20d avg
    technical_score: float = 0.0
    pct_from_ma20: Optional[float] = None   # (price - ma20) / ma20 * 100
    trigger: str                             # "ENTRY" or "EXIT_ALERT"
    computed_at: datetime


class DipBuyScanResponse(BaseModel):
    """Response from GET /signals/dip-buy."""
    entry_candidates: list[DipBuyCandidate]  # ranked by stoch_rsi asc (most oversold first)
    exit_alerts: list[DipBuyCandidate]       # positions to consider taking profit on
    neutral_tickers: list[DipBuyCandidate] = []   # watched tickers with data but no signal
    unanalyzed_tickers: list[str] = []            # watched tickers with no feature data yet
    scanned: int                             # total watched tickers evaluated
