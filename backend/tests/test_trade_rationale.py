"""
Tests for the few words every trade carries to justify itself.

A trade row that says `BUY 57 HXL @ 41.20` asks a person to trust a decision
whose reasoning was discarded at the moment it was made. `trade_rationale`
writes that reasoning down — and the whole value of it rests on the sentence
being *checkable*, so these tests are mostly about what it refuses to say:

  * It names a factor only when that factor actually moved the score away from
    neutral, and only when the weights are what produced the score at all.
  * It concedes what argued against the trade, rather than listing agreement.
  * It never claims the engine chose an order a person chose.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.signal_generator import BUY_THRESHOLD, SELL_THRESHOLD  # noqa: E402
from app.services.trade_rationale import (  # noqa: E402
    MATERIAL_LIFT, entry_rationale, exit_rationale, score_drivers,
)

#: Weights that make the arithmetic in these tests readable: one dominant
#: factor, one secondary, the rest small but non-zero.
WEIGHTS = {
    "technical": 0.40,
    "fundamental": 0.20,
    "sentiment": 0.20,
    "macro": 0.10,
    "volatility": 0.00,
    "catalyst": 0.10,
    "alternative_data": 0.10,
}


def feat(**overrides) -> dict:
    """A feature document sitting at dead neutral, before overrides."""
    base = {
        "ticker": "AVGO",
        "technical_score": 0.5,
        "fundamental_score": 0.5,
        "sentiment_score": 0.5,
        "macro_score": 0.5,
        "volatility_score": 0.5,
        "catalyst_score": 0.5,
        "alternative_data_score": 0.5,
        "scoring_method": "weighted",
    }
    base.update(overrides)
    return base


# ── What moved the score ──────────────────────────────────────────────────────

def test_a_factor_is_named_for_its_lift_not_its_weight():
    """
    The heaviest weight must not top every reason ever written.

    Technical carries twice sentiment's weight, but sits at exactly neutral: it
    contributed 0.20 to the composite and decided nothing. Sentiment is what
    made this score what it is, so sentiment is what the sentence names.
    """
    supporting, opposing, attributable = score_drivers(
        feat(sentiment_score=0.95), WEIGHTS
    )
    assert attributable
    assert supporting == ["positive news sentiment"]
    assert opposing == []


def test_drivers_are_ranked_strongest_first():
    supporting, _, _ = score_drivers(
        feat(technical_score=0.90, sentiment_score=0.80), WEIGHTS
    )
    # technical: 0.40 × 0.40 = 0.160; sentiment: 0.20 × 0.30 = 0.060.
    assert supporting == ["strong technicals", "positive news sentiment"]


def test_a_factor_below_the_material_threshold_is_not_named():
    """A nudge is not a reason. Naming one beside a real driver misleads."""
    # macro weight 0.10 × lift 0.05 = 0.005, well under MATERIAL_LIFT.
    supporting, _, _ = score_drivers(feat(macro_score=0.55), WEIGHTS)
    assert supporting == []

    # The same factor, moved just past the threshold, is named. What separates
    # the two cases is the lift, not the factor.
    past_threshold = 0.5 + (MATERIAL_LIFT * 1.05) / WEIGHTS["macro"]
    supporting, _, _ = score_drivers(feat(macro_score=past_threshold), WEIGHTS)
    assert supporting == ["a supportive macro backdrop"]


def test_alternative_data_competes_on_the_same_footing():
    supporting, _, _ = score_drivers(feat(alternative_data_score=1.0), WEIGHTS)
    assert supporting == ["supportive options and insider flow"]


def test_the_xgboost_path_attributes_nothing():
    """
    The weights did not produce that number, so no decomposition of it is true.

    Same refusal `scoring.explain_score` makes with `attributable: false` — a
    weighted story told about a model output is a fabrication, however
    plausible it reads.
    """
    supporting, opposing, attributable = score_drivers(
        feat(technical_score=0.98, scoring_method="xgboost"), WEIGHTS
    )
    assert (supporting, opposing, attributable) == ([], [], False)


def test_no_feature_document_attributes_nothing():
    assert score_drivers(None, WEIGHTS) == ([], [], False)
    assert score_drivers({}, WEIGHTS) == ([], [], False)


# ── The entry sentence ────────────────────────────────────────────────────────

def test_a_buy_quotes_the_score_against_the_bar_it_had_to_clear():
    text = entry_rationale(signal_score=0.82, feat=feat(), user_weights=WEIGHTS)
    assert "82/100" in text
    assert str(round(BUY_THRESHOLD * 100)) in text


def test_a_buy_concedes_what_argued_against_it():
    """
    A reason that only ever lists agreement reads as marketing. The trader
    already knows no setup is unanimous; the concession is what earns the trust.
    """
    text = entry_rationale(
        signal_score=0.78,
        feat=feat(technical_score=0.92, fundamental_score=0.10),
        user_weights=WEIGHTS,
        conviction="HIGH",
    )
    assert "strong technicals" in text
    assert "despite weak fundamentals" in text


def test_conviction_is_labelled_as_the_analysts():
    """
    Research carries a 0–100 number under the same word. A bare "conviction"
    in a sentence a trader reads would be the two measures collapsed into one.
    """
    text = entry_rationale(
        signal_score=0.80, feat=feat(technical_score=0.9),
        user_weights=WEIGHTS, conviction="high",
    )
    assert "Analyst conviction HIGH" in text


def test_the_xgboost_path_says_so_rather_than_naming_a_driver():
    text = entry_rationale(
        signal_score=0.88,
        feat=feat(technical_score=0.98, scoring_method="xgboost"),
        user_weights=WEIGHTS,
    )
    assert "88/100" in text
    assert "ML model" in text
    for phrase in ("strong technicals", "solid fundamentals", "positive news sentiment"):
        assert phrase not in text


def test_a_manual_order_is_not_attributed_to_the_engine():
    """
    The human is the signal. A sentence claiming the score bought it would be
    false, and performance keeps these buckets apart for the same reason.
    """
    text = entry_rationale(
        signal_score=0.55, feat=feat(technical_score=0.9),
        user_weights=WEIGHTS, source="MANUAL",
    )
    assert text.startswith("Your order")
    assert "55/100" not in text
    # And no drivers clause: naming what the engine likes right now would read
    # as the engine endorsing an order it had no part in.
    assert "strong technicals" not in text


def test_an_approved_proposal_credits_both_parties():
    text = entry_rationale(
        signal_score=0.81, feat=feat(technical_score=0.9),
        user_weights=WEIGHTS, source="PROPOSAL_APPROVED",
    )
    assert "approved" in text.lower()
    assert "strong technicals" in text


def test_an_add_reads_as_an_add_not_as_a_fresh_entry():
    text = entry_rationale(
        signal_score=0.80, feat=feat(technical_score=0.9),
        user_weights=WEIGHTS, is_add=True,
    )
    assert text.startswith("Added to the position")


def test_a_reason_is_never_empty_however_little_is_known():
    """A blank justification is worse than a modest one."""
    for kwargs in (
        {"signal_score": None},
        {"signal_score": 0.8},
        {"signal_score": 0.8, "feat": {}},
        {"signal_score": None, "source": "MANUAL"},
    ):
        text = entry_rationale(**kwargs)
        assert text and text.endswith(".") and " " in text


def test_a_score_from_the_middle_of_every_factor_says_so():
    text = entry_rationale(signal_score=0.72, feat=feat(), user_weights=WEIGHTS)
    assert "no single factor stood out" in text


# ── The exit sentence ─────────────────────────────────────────────────────────

def test_a_sell_signal_names_what_broke_down():
    text = exit_rationale(
        "SELL_SIGNAL", 0.24,
        feat=feat(technical_score=0.05, sentiment_score=0.10),
        user_weights=WEIGHTS,
    )
    assert "24/100" in text
    assert str(round(SELL_THRESHOLD * 100)) in text
    assert "weak technicals" in text
    assert "negative news sentiment" in text


def test_an_exit_the_score_did_not_decide_is_not_dressed_in_factors():
    """
    The setup scan and the Close button decided these. Attaching a factor
    decomposition would credit arithmetic that had no part in the decision.
    """
    for trigger in ("EXIT_ALERT", "MANUAL_CLOSE"):
        text = exit_rationale(
            trigger, 0.24,
            feat=feat(technical_score=0.05), user_weights=WEIGHTS,
        )
        assert "weak technicals" not in text
        assert text and " " in text


# ── The reason reaches the record ─────────────────────────────────────────────
#
# The sentence is only worth writing if it is stored. These cover the wiring:
# a justification that exists in a log line and not on the trade document is
# unavailable to the person reading their order history six weeks later.

import asyncio  # noqa: E402

from app.models.trade import TradeStatus  # noqa: E402
from app.services.trade_manager import EntryPlan  # noqa: E402


class _StubBroker:
    def __init__(self):
        self.orders = []

    async def place_limit_order(self, ticker, action, qty, price, **kw):
        self.orders.append((ticker, action, qty, price, kw))
        return "ORD-1"

    def is_connected(self):
        return True


def _plan(**overrides) -> EntryPlan:
    base = dict(
        ticker="AVGO", qty=10, limit_price=100.0, stop_price=90.0,
        target_price=120.0, account_id="DU123", size_basis_equity=50_000.0,
    )
    base.update(overrides)
    return EntryPlan(**base)


def _patch_submit(monkeypatch, *, feature=None):
    """Wire `_submit_entry`'s collaborators to fakes. Returns (module, sink)."""
    import app.services.trade_manager as tm

    sink: dict = {"logged": [], "updates": []}

    async def _log(record):
        sink["logged"].append(record)
        return "trade-1"

    async def _update(trade_id, update):
        sink["updates"].append((trade_id, update))

    async def _context(user_id, ticker):
        return (feature if feature is not None else feat(technical_score=0.92)), WEIGHTS

    async def _notify(user_id, **kwargs):
        sink["notified"] = kwargs

    monkeypatch.setattr(tm, "ibkr", _StubBroker())
    monkeypatch.setattr(tm, "_log_trade", _log)
    monkeypatch.setattr(tm, "_update_trade", _update)
    monkeypatch.setattr(tm, "_rationale_context", _context)
    monkeypatch.setattr(tm, "_notify_trade", _notify)
    return tm, sink


def test_an_opening_entry_stores_its_justification(monkeypatch):
    tm, sink = _patch_submit(monkeypatch)
    trade_id, status, order_id = asyncio.run(tm._submit_entry(
        "u1", _plan(), signal_score=0.84, signal_type="BUY",
        trigger="BUY signal", conviction="HIGH",
    ))
    assert (trade_id, status, order_id) == ("trade-1", TradeStatus.PENDING, "ORD-1")
    record = sink["logged"][0]
    assert "84/100" in record["entry_reason"]
    assert "strong technicals" in record["entry_reason"]
    assert "Analyst conviction HIGH" in record["entry_reason"]
    # Conviction still lands as its own field — the sentence is for reading,
    # the field is what `may_auto_execute` and the UI badge branch on.
    assert record["conviction"] == "HIGH"


def test_the_notification_carries_the_same_words_as_the_record(monkeypatch):
    """
    An order alert on a phone is where the question "why?" is actually asked.
    It must not answer it differently from the row it points at.
    """
    tm, sink = _patch_submit(monkeypatch)
    asyncio.run(tm._submit_entry(
        "u1", _plan(), signal_score=0.84, signal_type="BUY", trigger="BUY signal",
    ))
    assert sink["notified"]["rationale"] == sink["logged"][0]["entry_reason"]


def test_an_add_updates_the_positions_reason_rather_than_writing_a_new_row(monkeypatch):
    """
    A scale-in adds to the record it already has. The justification follows the
    position, and the superseded wording stays with the add.
    """
    tm, sink = _patch_submit(monkeypatch)
    asyncio.run(tm._submit_entry(
        "u1", _plan(add_to_trade_id="pos-1", held_qty=450, blended_entry=98.0),
        signal_score=0.80, signal_type="BUY", trigger="BUY signal",
    ))
    assert sink["logged"] == []
    _, update = sink["updates"][-1]
    assert update["entry_reason"].startswith("Added to the position")
    assert update["pending_add"]["entry_reason"] == update["entry_reason"]


# ── The concession must survive a factor scoring exactly zero ─────────────────

def test_a_zero_scored_factor_is_conceded_not_dropped():
    """
    `float(feat.get(key, 0.5) or 0.5)` read a measured 0.0 as neutral, so the
    factor arguing hardest against the trade produced a lift of exactly 0.0 and
    fell out of `opposing` — deleting the concession precisely when it was
    strongest. A missing factor reads neutral; a measured zero does not.
    """
    feat = {
        "technical_score": 0.0, "fundamental_score": 0.90,
        "sentiment_score": 0.80, "macro_score": 0.50, "volatility_score": 0.50,
        "catalyst_score": 0.60, "momentum_score": 0.50,
        "alternative_data_score": 0.50,
    }
    supporting, opposing, attributable = score_drivers(feat, None)
    assert attributable
    assert "weak technicals" in opposing, (
        "a factor at 0.0 carries the largest negative lift there is and must "
        "be the first thing conceded"
    )


def test_every_scored_factor_has_a_name():
    """
    A factor absent from `_FACTOR_WORDS` is filtered out of both the supporting
    list and the concession, silently. `momentum` was missing for as long as its
    weight was 0.00 — which is exactly how long nobody would have noticed.
    """
    from app.services.scoring import ALT_FACTOR, FACTORS
    from app.services.trade_rationale import _FACTOR_WORDS
    known = {key for key, _, _ in FACTORS} | {ALT_FACTOR[0]}
    assert known <= set(_FACTOR_WORDS), (
        f"factors with no phrasing: {known - set(_FACTOR_WORDS)}"
    )
