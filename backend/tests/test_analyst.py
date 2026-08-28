"""
Tests for the single-call analyst — the path that actually drives trades.

This module had **zero tests** from the day it was written until this file.
Not an oversight in discipline so much as a consequence of design: it built its
API client inline, so there was no seam to test through. `services/research/`
was written with an injectable client precisely because of that, and this file
exists because the analyst now shares its call machinery.

The gap mattered. This is the path that produces the BUY/SELL/HOLD written into
`stocks_signals` on the 5-minute cycle, that sets the HIGH/MEDIUM/LOW conviction
gating unattended execution, and that carried the `analyst_used` bug which made
a borderline name flip verdicts eight times in an hour. The deep-research path,
which cannot place an order and can only veto one, had 1,400 lines of tests
against it.

What is pinned here:

  * the schema is structured-outputs-legal — the same fence
    `test_research_schemas.py` puts around the agent schemas, after a 400 that
    failed three agents identically;
  * no markdown-fence stripping remains: the response shape is enforced
    server-side, not requested in prose and repaired afterwards;
  * a failed call returns None rather than a HOLD, because a fabricated verdict
    on an unreachable model is worse than no verdict;
  * the enum normalisation still holds, since `_conviction_to_confidence` and
    the trading path both key off exact strings.

Run with:  pytest backend/tests -q
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import analyst as A  # noqa: E402


# ── Fakes ─────────────────────────────────────────────────────────────────────

class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Usage:
    input_tokens = 800
    output_tokens = 400
    cache_read_input_tokens = 0


class _Message:
    stop_details = None

    def __init__(self, payload, stop_reason="end_turn"):
        self.content = [_Block(json.dumps(payload))] if payload is not None else []
        self.usage = _Usage()
        self.stop_reason = stop_reason


class FakeClient:
    def __init__(self, payload, stop_reason="end_turn", raises=None):
        self.calls = []

        class _M:
            async def create(_inner, **kwargs):
                self.calls.append(kwargs)
                if raises:
                    raise raises
                return _Message(payload, stop_reason)

        self.messages = _M()


def _output(**over):
    payload = {
        "signal": "BUY",
        "conviction": "HIGH",
        "price_target": 220.0,
        "stop_loss": 180.0,
        "time_horizon": "2-4 weeks",
        "thesis": "Margins are expanding into a strong tape.",
        "bull_case": "Operating leverage.",
        "bear_case": "The multiple is full.",
        "key_risks": ["Multiple compression"],
        "catalysts": ["Earnings on 2026-10-28"],
        "analyst_note": "A three paragraph note.",
    }
    payload.update(over)
    return payload


def _call(payload, **kw):
    return asyncio.run(
        A._call_claude("CONTEXT", api_key="", client=FakeClient(payload, **kw))
    )


# ── The schema ────────────────────────────────────────────────────────────────

def test_the_schema_is_structured_outputs_legal():
    """
    Numeric bounds, string length bounds and array bounds are rejected with a
    400 rather than ignored — the incident that failed fundamentals, risk and
    the synthesiser identically. Same fence as `test_research_schemas.py`.
    """
    banned = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
              "minLength", "maxLength", "minItems", "maxItems", "pattern"}

    def walk(node):
        if isinstance(node, dict):
            assert not (banned & set(node)), f"illegal constraint in {sorted(node)}"
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(A._RESPONSE_SCHEMA)


def test_the_schema_is_a_closed_object_with_every_field_required():
    schema = A._RESPONSE_SCHEMA
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


def test_the_prompt_no_longer_asks_for_json_in_prose():
    """
    The shape is enforced by the API. A prompt that also begs for it invites
    the model to spend tokens on an envelope it is not producing.
    """
    prompt = A._SYSTEM_PROMPT.lower()
    assert "no markdown fences" not in prompt
    assert "valid json only" not in prompt


def test_no_fence_stripping_remains_in_the_module():
    """
    Two regexes used to repair the response after the fact. A truncated or
    fenced reply failed to parse and wasted the call including its thinking
    tokens, which are most of the bill.
    """
    source = Path(A.__file__).read_text()
    for token in ('re.sub(r"^```', 'json.loads(raw_text)', "raw_text"):
        assert token not in source, f"{token!r} survived the rewrite"


# ── The call ──────────────────────────────────────────────────────────────────

def test_a_well_formed_response_is_returned_intact():
    got = _call(_output())
    assert got["signal"] == "BUY"
    assert got["conviction"] == "HIGH"
    assert got["price_target"] == 220.0


def test_the_schema_is_actually_sent_to_the_api():
    client = FakeClient(_output())
    asyncio.run(A._call_claude("CONTEXT", api_key="", client=client))
    sent = client.calls[0]["output_config"]["format"]["schema"]
    assert set(sent["required"]) == set(A._RESPONSE_SCHEMA["required"])


def test_a_refusal_raises_rather_than_reading_as_an_empty_report():
    """
    A model can return HTTP 200 with `stop_reason: refusal` and no content.
    Code reading `content[0]` unconditionally raises something unrelated-
    looking on that path.
    """
    with pytest.raises(ValueError):
        _call(None, stop_reason="refusal")


def test_a_truncated_response_raises_rather_than_half_parsing():
    with pytest.raises(ValueError):
        _call(None, stop_reason="max_tokens")


def test_a_lowercase_signal_is_normalised():
    assert _call(_output(signal="buy"))["signal"] == "BUY"


def test_an_unrecognised_signal_falls_back_to_hold_not_to_a_trade():
    """
    The safe direction. `_conviction_to_confidence` keys off exact strings, and
    a drift to "Buy" would route through the default and read as low conviction
    on a position it had just opened.
    """
    assert _call(_output(signal="STRONG BUY"))["signal"] == "HOLD"
    assert _call(_output(conviction="VERY HIGH"))["conviction"] == "LOW"


# ── run_analysis ──────────────────────────────────────────────────────────────

class _Coll:
    def __init__(self, doc=None):
        self._doc = doc
        self.replaced = []

    async def find_one(self, *_a, **_k):
        return self._doc

    async def replace_one(self, query, doc, upsert=False):
        self.replaced.append(doc)


class _Db:
    def __init__(self, feat, raw):
        self._c = {
            "stocks_features": _Coll(feat),
            "stocks_raw": _Coll(raw),
            "stocks_signals": _Coll(),
        }

    def __getitem__(self, name):
        return self._c.setdefault(name, _Coll())


FEATURES = {
    "ticker": "EXMP", "current_price": 200.0, "composite_score": 0.72,
    "technical_score": 0.7, "fundamental_score": 0.6, "sentiment_score": 0.55,
    "macro_score": 0.5, "volatility_score": 0.5, "catalyst_score": 0.4,
    "rsi_14": 58.0, "atr_14": 4.2, "volatility": 0.34,
}
RAW = {"ticker": "EXMP", "current_price": 200.0, "day_change_pct": 1.2,
       "news": [], "fetched_at": "2026-08-28T06:00:00+00:00"}


@pytest.fixture
def wired(monkeypatch):
    db = _Db(dict(FEATURES), dict(RAW))

    async def fake_get_db():
        return db

    monkeypatch.setattr(A, "get_db", fake_get_db)
    return db


def test_a_signal_doc_is_written_with_analyst_used_persisted(wired):
    """
    `analyst_used` on the *stored* document is what `pipeline` reads back to
    decide whether a cached signal exists. Setting it only on the in-memory
    dict made the 60-minute cache never hit once — Claude was re-called every
    cycle for every ticker past the gate, and each re-sampling is what flipped
    a borderline name eight times in an hour.
    """
    doc = asyncio.run(A.run_analysis("EXMP", client=FakeClient(_output())))
    assert doc["analyst_used"] is True
    assert wired["stocks_signals"].replaced[0]["analyst_used"] is True


def test_a_failed_call_returns_none_rather_than_a_fabricated_hold(wired):
    """
    A HOLD is a verdict. Manufacturing one when the model was unreachable
    would publish an opinion nobody formed, and the pipeline would cache it.
    """
    client = FakeClient(None, raises=RuntimeError("upstream down"))
    assert asyncio.run(A.run_analysis("EXMP", client=client)) is None
    assert wired["stocks_signals"].replaced == []


def test_missing_features_stop_the_call_before_it_is_paid_for(monkeypatch):
    db = _Db(None, None)

    async def fake_get_db():
        return db

    monkeypatch.setattr(A, "get_db", fake_get_db)
    client = FakeClient(_output())
    assert asyncio.run(A.run_analysis("EXMP", client=client)) is None
    assert client.calls == []


def test_conviction_maps_to_the_confidence_the_trading_path_reads():
    assert A._conviction_to_confidence("HIGH") == 0.85
    assert A._conviction_to_confidence("MEDIUM") == 0.55
    assert A._conviction_to_confidence("LOW") == 0.25
    # Anything unrecognised is treated as the least confident reading, never
    # the most — the failure direction that cannot open a position.
    assert A._conviction_to_confidence("SPECTACULAR") == 0.25
