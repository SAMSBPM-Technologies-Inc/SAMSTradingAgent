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


class FactorInput(BaseModel):
    """
    What one factor of a score was built from.

    `coverage` is the share of that factor's own inputs that arrived, and
    `state` is the reading of it: `measured` (all of it), `partial` (some, with
    the rest already blended toward 0.5 by the sub-score itself), `fallback`
    (none — the factor is the flat neutral and says nothing about the company).
    """
    key: str
    label: str
    state: Literal["measured", "partial", "fallback"]
    coverage: float = Field(..., ge=0.0, le=1.0)


class SignalInputs(BaseModel):
    """
    How much of this score was measured, and how much of it is a placeholder.

    Every external source degrades to a neutral 0.5 rather than failing the
    cycle. That is the right trade — a verdict on four factors beats no verdict
    — but it meant a composite assembled from three fallbacks was
    indistinguishable in the API from one assembled from live data. This is
    that distinction, and it is the only thing that makes the six-factor
    breakdown beside it readable: a 0.50 sub-score can mean "measured, and
    genuinely neutral" or "we never found out", and those are not the same fact.

    `completeness` is weighted by *the caller's* weights, because a factor
    weighted at zero is not part of their score and its coverage is not part of
    their completeness. Coverage figures are weight-independent facts and are
    the same for everyone.
    """
    factors: list[FactorInput] = []
    completeness: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Weighted share of the composite that came from measured "
                    "data. None for signals generated before this was recorded "
                    "— an absent figure, never a flattering default.",
    )
    #: Weighted factors carrying no measured data at all, heaviest first.
    fallback_factors: list[str] = []


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
    # Which provider actually supplied each input, and how much of each factor
    # was measured. `data_sources` has been written to every signal document
    # since the pipeline was built and returned by no endpoint until now.
    data_sources: Optional[dict] = None
    inputs: Optional[SignalInputs] = None


class QuoteResponse(BaseModel):
    """
    What a name is worth right now — and nothing else.

    Deliberately separate from `AnalyzeResponse`. The analysis is a stored
    judgement that can be hours old and still be the right thing to read; the
    price is only useful if it is current. Fusing them is what forced a full
    pipeline run just to see whether a stock had moved.

    `source` says which of the two the reader is looking at: `live` is a quote
    fetched now, `stored` is the last price the pipeline wrote — served with the
    time it was written rather than an error, because a quote provider being
    down must not blank the ticker page.
    """
    ticker: str
    price: Optional[float] = None
    day_change_pct: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    prev_close: Optional[float] = None
    #: When this price was true. For `stored`, when the pipeline last wrote it.
    as_of: Optional[datetime] = None
    source: Literal["live", "stored", "unavailable"] = "unavailable"
    #: Why the live quote was not used, when it was not. Never an exception
    #: string — this reaches a UI.
    note: Optional[str] = None


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


class EvidenceItem(BaseModel):
    """
    One attributable fact from the research ledger.

    The `id` is what the report's prose cites. Any claim in a dossier that does
    not reference one of these was removed before storage — see
    `services/research/evidence.py`.
    """

    id: str
    claim: str
    value: str
    source: str
    as_of: Optional[str] = None
    url: Optional[str] = None


class DimensionScore(BaseModel):
    """
    One of the six 0-100 report dimensions.

    `higher is better` on all six, risk included — there it means safer. Five
    are computed in Python from the evidence; `model_judged` marks the one that
    is not, so a reader can see which score is a different kind of claim.
    `thin` marks a dimension built from too few inputs to be worth much, the
    same warning the calibration page gives an under-sampled bucket.
    """

    key: str
    label: str
    score: Optional[float] = None
    coverage: float = 0.0
    thin: bool = False
    model_judged: bool = False
    components: list[dict] = []
    note: Optional[str] = None


class ResearchReport(BaseModel):
    """The synthesised narrative. Every prose field has been citation-filtered."""

    assessment: Optional[str] = None          # BULLISH | NEUTRAL | BEARISH
    # Conviction is deliberately not repeated here. The model emits it inside
    # its report and the orchestrator clamps it there, but exposing the same
    # 0-100 number at two depths of one response invites a client to read the
    # unclamped one. `ResearchDossier.research_conviction` is the value.
    thesis: Optional[str] = None
    bull_case: Optional[str] = None
    bear_case: Optional[str] = None
    what_the_market_is_missing: Optional[str] = None
    key_catalysts: list[str] = []
    key_risks: list[str] = []
    #: Risks the risk agent raised that the synthesiser answered rather than
    #: carried. Surfaced so a dropped risk is visible as a decision, not a gap.
    risks_addressed: list[str] = []
    what_would_change_my_opinion: list[str] = []
    conclusion: Optional[str] = None
    conviction_rationale: Optional[str] = None


class CitationAudit(BaseModel):
    """
    What the citation filter actually did to a report.

    Every prose and list field in a synthesised report is checked against the
    evidence ledger before storage: an uncited claim is dropped, and a citation
    to an id the ledger never issued is dropped and recorded. This is the proof
    that happened, not just a claim that it did — without it, a client has no
    way to tell "nothing was caught" from "the check never ran and I can't see
    the difference".
    """

    #: Per-field count of items removed for citing nothing. A prose field that
    #: lost its only sentence counts as 1; a list field counts however many
    #: items were dropped whole.
    dropped: dict[str, int] = {}
    #: Citation ids the model referenced that do not exist in the evidence
    #: ledger. A non-empty list here is the case worth treating with the most
    #: suspicion: a fabricated id looks exactly like a real one to a reader
    #: skimming the prose, which is why it is stripped rather than merely
    #: flagged — but the same reason makes it worth surfacing here too.
    invented: list[str] = []

    @property
    def clean(self) -> bool:
        """Whether the filter found nothing to remove."""
        return not self.dropped and not self.invented


class ResearchVetoStatus(BaseModel):
    """
    What a dossier does to a BUY on its ticker.

    The veto was previously observable only by tripping it: attempt an entry,
    have it refused, and read the sentence afterwards on a SKIPPED trade row.
    A standing condition discoverable only by walking into it is one nobody can
    plan around, which is why this is reported before an order rather than
    after one.

    `blocking` and `would_block` are separate on purpose. `RESEARCH_VETO_ENABLED`
    is off by default, so on most deployments the honest statement is the
    second: research reads this name badly and *would* refuse the entry if the
    veto were switched on. Collapsing the two into one boolean would hide
    exactly the fact a user needs in order to decide whether to switch it on.
    """

    #: RESEARCH_VETO_ENABLED. False means nothing here can stop an order.
    enabled: bool = False
    #: The dossier exists and is fresh enough to be capable of vetoing.
    considered: bool = False
    #: The dossier meets a blocking trigger, whether or not the veto is on.
    would_block: bool = False
    #: `enabled and would_block` — the only field the guard chain acts on.
    blocking: bool = False
    #: The refusal a user would see. Present whenever `would_block`.
    reason: Optional[str] = None
    #: "bearish" | "low_conviction" | None.
    trigger: Optional[str] = None
    assessment: Optional[str] = None
    research_conviction: Optional[float] = None
    #: The floor conviction must clear, so a client can show the distance to
    #: the edge rather than a bare number with no scale.
    min_conviction: float = 0.0
    age_hours: Optional[float] = None
    max_age_hours: int = 0
    #: Why the dossier was not considered: "no_dossier" | "undated" | "stale".
    #: Each of these allows the trade, and each for a different reason worth
    #: telling apart — a missing dossier is a gap, a stale one is an outage.
    not_considered_reason: Optional[str] = None


class TradeStance(BaseModel):
    """
    One temperament's reading of the position, not of the company.

    `rationale` is None when nothing the model wrote cited real evidence. The
    stance still stands — it is a closed enum, not a claim — and the visible
    gap where the reasoning should be is the intended outcome: a
    recommendation nobody can check is worse than one with an obvious hole.
    """

    stance: Optional[str] = None       # SIZE_UP | HOLD_SIZE | SIZE_DOWN | WAIT
    rationale: Optional[str] = None
    what_would_change_it: Optional[str] = None


class ResearchStances(BaseModel):
    """
    The advisory stance panel.

    **Nothing here moves an order.** Position sizing is arithmetic on a frozen
    equity basis, no part of the trading guard chain reads this, and three
    unanimous WAITs still leave the order the risk model sized. A client
    displaying these must not imply the quantity followed from them.

    They also do not see account exposure: a dossier is shared across users, so
    a per-user panel would multiply its cost by the user count. Each reads the
    synthesised report and the ticker's own risk profile.
    """

    aggressive: Optional[TradeStance] = None
    conservative: Optional[TradeStance] = None
    neutral: Optional[TradeStance] = None


class RebuttalSide(BaseModel):
    """One side of the exchange, after citation filtering."""

    #: Risks this side considers disposed of by the evidence.
    answered: list[str] = []
    #: Risk analyst only: risks that stand after seeing the evidence.
    surviving: list[str] = []
    #: Risk analyst only: risks the evidence makes *worse* than first judged.
    sharpened: list[str] = []
    #: Defence only: risks the evidence does not answer. The valuable half —
    #: an answer that disposes of every risk is the strongest signal the step
    #: was not done honestly.
    conceded: list[str] = []
    #: Defence only: real but smaller than argued.
    overstated: list[str] = []
    residual_severity: Optional[int] = None
    residual_rationale: Optional[str] = None
    strongest_surviving_risk: Optional[str] = None


class ResearchDebate(BaseModel):
    """
    The rebuttal round.

    Both sides wrote independently first and only then saw each other's work,
    which is what separates this from a debate whose second speaker inherits
    the first's framing. Either side may be `None` — its call failed — and that
    is not the same as a side that argued and found nothing.
    """

    rounds: int = 1
    risk_rebuttal: Optional[RebuttalSide] = None
    defence_rebuttal: Optional[RebuttalSide] = None


class ResearchReflection(BaseModel):
    """The written half of an outcome. Citation-filtered like any report prose."""

    #: None when nothing the model wrote cited a real evidence id. The numbers
    #: beside it still stand — the prose is the optional part, and an
    #: unattributable lesson must never be carried into a future prompt.
    lesson: Optional[str] = None
    what_held: list[str] = []
    what_failed: list[str] = []
    #: True when the whole lesson was dropped for citing nothing. Surfaced
    #: rather than hidden: "we reflected and it was unusable" and "we never
    #: reflected" are different facts about the loop's health.
    uncited: bool = False
    fabricated_citations: list[str] = []


class ResearchOutcome(BaseModel):
    """
    What actually happened after a dossier was written.

    `assessment_correct` is judged on **alpha**, not on the raw return: BULLISH
    on a name that rose 4% while the market rose 9% was not right, and grading
    it as a win is how a desk mistakes exposure for skill. It is `None` for a
    NEUTRAL reading and for a window whose benchmark could not be read — both
    are "cannot say", and a client must not render either as a miss.
    """

    settled_at: Optional[datetime] = None
    horizon_days: Optional[int] = None
    price_at_dossier: Optional[float] = None
    price_at_settlement: Optional[float] = None
    return_: Optional[float] = Field(default=None, alias="return")
    benchmark_ticker: Optional[str] = None
    benchmark_return: Optional[float] = None
    alpha: Optional[float] = None
    assessment: Optional[str] = None
    research_conviction: Optional[float] = None
    assessment_correct: Optional[bool] = None
    reflection: Optional[ResearchReflection] = None

    model_config = {"populate_by_name": True}


class ModelUsed(BaseModel):
    """One producer behind a dossier, and the agents it wrote."""

    provider: Optional[str] = None
    model: Optional[str] = None
    agents: list[str] = []


class PriorRecordCoverage(BaseModel):
    """How much of this desk's own track record the agents were shown."""

    same_ticker: int = 0
    cross_ticker: int = 0
    available: bool = False


class ResearchDossier(BaseModel):
    """
    A deep-research dossier. Separate from the 5-minute signal on purpose.

    `stale` and `age_hours` are always present because a dossier is served past
    its TTL rather than withheld — a day-old business assessment is still an
    assessment — but the reader and the trade veto both need to know.
    """

    ticker: str
    as_of: str
    stale: bool = False
    age_hours: Optional[float] = None
    #: 0-100, the research module's own conviction. Distinct from the analyst's
    #: HIGH/MEDIUM/LOW `conviction` on a signal or a trade: different scale,
    #: different producer, and a different gate — this one feeds the entry veto,
    #: that one decides whether the agent may execute unattended.
    research_conviction: Optional[float] = None
    #: The arithmetic anchor conviction was clamped to. Stored beside the final
    #: value so the two can be compared: a persistent gap means the numbers and
    #: the model's judgement disagree.
    derived_research_conviction: Optional[float] = None
    report: Optional[ResearchReport] = None
    dimensions: list[DimensionScore] = []
    evidence: list[EvidenceItem] = []
    evidence_count: int = 0
    data_gaps: list[str] = []
    #: Agents whose call failed. A dossier missing a section is still served;
    #: which section is missing changes how it should be read.
    agents_failed: list[str] = []
    #: Agents that were never run because their slice of the evidence held no
    #: facts about the company. Distinct from a failure: nothing broke, there
    #: was simply nothing to assess, and the reader should treat the questions
    #: that agent would have answered as unanswered rather than as neutral.
    agents_skipped: list[str] = []
    #: Set only when `report` is null and the merge call itself failed — as
    #: opposed to `report` being null because no specialist produced anything
    #: to merge. Distinguishes "nothing to synthesise" from "the synthesiser
    #: broke", the same way `agents_skipped` distinguishes a skip from a
    #: failure for the specialists.
    synthesis_error: Optional[str] = None
    #: What the citation filter removed from `report`, or None when there was
    #: no report to filter. Check `citation_audit.clean` before trusting a
    #: report's prose at face value — a non-clean audit means the model wrote
    #: at least one uncited or fabricated claim that this dossier no longer
    #: contains, which is a fact worth knowing even though the removal already
    #: happened.
    citation_audit: Optional[CitationAudit] = None
    #: What this dossier does to a BUY on this ticker, right now. Always
    #: present — a dossier that blocks nothing says so explicitly, because
    #: "no veto field" and "veto found nothing" are not the same claim.
    veto: Optional[ResearchVetoStatus] = None
    #: How this reading turned out, once enough time has passed to know.
    #: `None` on a dossier too recent to grade — which is the normal state for
    #: the one being displayed, since it was written today.
    outcome: Optional[ResearchOutcome] = None
    #: How many settled prior readings were in this dossier's evidence when it
    #: was built. Zero is the honest answer for every dossier written before
    #: outcome settlement existed, and for any name being read for the first
    #: time — both cases where the agents had no record to learn from.
    prior_record: Optional[PriorRecordCoverage] = None
    #: The rebuttal exchange, or None when the round did not run — off by
    #: config, or the risk agent did not report and there was nothing to argue.
    debate: Optional[ResearchDebate] = None
    #: Advisory stance panel, or None when it did not run. Never binding on an
    #: order — see `ResearchStances`.
    stances: Optional[ResearchStances] = None
    #: Which models produced this reading. A trader who can choose the model
    #: needs to know which one wrote which section — comparing two dossiers is
    #: the whole point of being able to choose, and it is not possible without
    #: this. Empty on dossiers written before provenance was recorded.
    models_used: list[ModelUsed] = []


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
    #: Alpha carries its own count. Records settled before benchmark
    #: measurement existed have a return and no alpha, so `settled` overstates
    #: how much evidence sits behind the alpha figure — a client showing one
    #: count against both numbers would present a handful of samples with the
    #: authority of hundreds.
    alpha_settled: int = 0
    avg_alpha_20d: Optional[float] = None


class PerformanceResponse(BaseModel):
    total_signals: int
    settled_signals: int
    overall_win_rate: Optional[float] = None
    overall_avg_return_20d: Optional[float] = None
    #: What alpha is measured against, so the client never has to name it.
    benchmark_ticker: Optional[str] = None
    alpha_settled_signals: int = 0
    overall_avg_alpha_20d: Optional[float] = None
    by_signal: list[SignalPerformanceRecord]
    by_ticker: list[dict]


class HealthResponse(BaseModel):
    status: str
    db_connected: bool
    version: str = "1.17.1"
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
