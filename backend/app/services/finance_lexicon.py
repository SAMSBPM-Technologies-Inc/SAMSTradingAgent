"""
Financial vocabulary for VADER.

VADER is trained on social media and general English. It has no idea that
"beats", "raises guidance", "buyback" or "halts production" carry direction in a
market context, and scores them at exactly zero. Measured on ten unambiguous
headlines, four came back 0.000:

    Apple beats Q3 estimates, raises guidance      +0.000
    Microsoft announces $60bn buyback              +0.000
    Meta stock jumps 12% on ad revenue surge       +0.000
    Boeing halts 737 production amid FAA probe     +0.000

Averaging then compressed what survived: that basket, containing strongly
directional news, stored as 0.458 — indistinguishable from neutral. Sentiment
carried 0.20 of the composite on that.

This module supplies the missing vocabulary. Two mechanisms, because headline
tone lives in both single words and short phrases:

  * `LEXICON_TERMS` extends VADER's word-level dictionary directly.
  * `PHRASES` matches multi-word constructions VADER cannot see, since it scores
    token by token — "raises guidance" and "cuts guidance" share every word that
    matters except the verb, and "profit warning" is bearish despite "profit".

Valences are on VADER's scale, roughly -4.0 to +4.0. They are deliberately
moderate: most sit between 1.2 and 2.6, because a single headline word should
colour a score, not decide it. Sources are the Loughran-McDonald financial
sentiment word lists, which exist precisely because general-purpose lexicons
misread financial text, plus the reporting conventions of earnings coverage.

Not a replacement for a finance-tuned transformer. FinBERT would read context
this cannot — negation, attribution, forward-looking hedges. This is the
zero-dependency step that fixes the observed failures today.
"""
from typing import Iterable

#: Single tokens VADER lacks or scores wrongly in a market context.
#: Keys must be lowercase; VADER lowercases before lookup.
LEXICON_TERMS: dict[str, float] = {
    # ── Earnings outcomes ────────────────────────────────────────────────────
    "beats": 2.2, "beat": 1.8, "topped": 1.8, "outperformed": 2.0,
    "misses": -2.2, "missed": -1.8, "shortfall": -2.2, "underperformed": -2.0,
    "guidance": 0.0,          # neutral alone; direction comes from PHRASES
    "upside": 1.8, "downside": -1.8,
    # ── Analyst actions ──────────────────────────────────────────────────────
    "upgrade": 2.4, "upgrades": 2.4, "upgraded": 2.4,
    "downgrade": -2.4, "downgrades": -2.4, "downgraded": -2.4,
    "reiterated": 0.4, "initiated": 0.6,
    "overweight": 1.8, "underweight": -1.8,
    "outperform": 2.0, "underperform": -2.0,
    # ── Capital returns and structure ────────────────────────────────────────
    "buyback": 1.8, "buybacks": 1.8, "repurchase": 1.6,
    "dividend": 1.2, "dividends": 1.2,
    "dilution": -2.0, "dilutive": -1.8, "offering": -1.2, "secondary": -1.0,
    "accretive": 1.6,
    # ── Price and volume action ──────────────────────────────────────────────
    "surge": 2.2, "surges": 2.2, "surged": 2.2, "soars": 2.4, "soared": 2.4,
    "jumps": 1.8, "jumped": 1.8, "rallies": 2.0, "rallied": 2.0,
    "climbs": 1.4, "rebounds": 1.6, "outpaces": 1.6,
    "plunge": -2.4, "plunges": -2.4, "plunged": -2.4,
    "tumbles": -2.2, "tumbled": -2.2, "slumps": -2.0, "slumped": -2.0,
    "slides": -1.6, "sinks": -2.0, "sank": -2.0, "cratered": -2.8,
    "selloff": -2.0, "rout": -2.4,
    # ── Operations and legal ─────────────────────────────────────────────────
    "recall": -2.2, "recalls": -2.2, "recalled": -2.2,
    "probe": -1.8, "investigation": -1.8, "subpoena": -2.2,
    "lawsuit": -1.8, "litigation": -1.6, "fined": -2.0, "penalty": -1.8,
    "halts": -1.6, "halted": -1.6, "suspends": -1.6, "suspended": -1.6,
    "restated": -2.4, "restatement": -2.4,
    "bankruptcy": -3.4, "insolvency": -3.4, "delisting": -3.0,
    "default": -2.8, "downsizing": -1.6, "layoffs": -1.2,
    # ── Growth and demand ────────────────────────────────────────────────────
    "record": 1.8, "expansion": 1.4, "momentum": 1.2,
    "backlog": 1.0, "bookings": 1.0,
    "demand": 0.8, "headwind": -1.6, "headwinds": -1.6,
    "tailwind": 1.6, "tailwinds": 1.6,
    "slowdown": -1.8, "contraction": -1.8, "weakness": -1.6,
    "writedown": -2.2, "impairment": -2.0,
    # ── Deals ────────────────────────────────────────────────────────────────
    "acquisition": 1.0, "merger": 1.0, "partnership": 1.2,
    "approval": 1.8, "approved": 1.8, "cleared": 1.4,
    "rejected": -2.0, "blocked": -1.8, "terminated": -1.8,
}

#: Multi-word constructions. Matched on the lowercased headline as substrings,
#: so ordering matters only in that longer phrases must precede the shorter ones
#: they contain — "raises guidance" before "guidance cut" would be wrong here.
#: Applied ADDITIVELY to VADER's compound, then the total is re-clamped.
PHRASES: tuple[tuple[str, float], ...] = (
    # Guidance — the single most direction-carrying construction in earnings news
    ("raises guidance", 2.6), ("raised guidance", 2.6), ("raises outlook", 2.4),
    ("raises forecast", 2.4), ("boosts guidance", 2.6), ("lifts guidance", 2.6),
    ("cuts guidance", -2.6), ("cut guidance", -2.6), ("lowers guidance", -2.6),
    ("lowered guidance", -2.6), ("slashes guidance", -3.0),
    ("cuts outlook", -2.4), ("lowers outlook", -2.4), ("cuts forecast", -2.4),
    ("withdraws guidance", -3.0), ("suspends guidance", -3.0),
    ("profit warning", -2.8), ("guides above", 2.2), ("guides below", -2.2),
    # Earnings framing
    ("tops estimates", 2.2), ("beats estimates", 2.2), ("beats expectations", 2.2),
    ("above estimates", 1.8), ("above consensus", 1.8),
    ("misses estimates", -2.2), ("missing estimates", -2.2),
    ("misses expectations", -2.2), ("below estimates", -1.8),
    ("below consensus", -1.8), ("falls short", -2.0),
    # Operational stops — VADER reads the nouns as neutral
    ("halts production", -2.4), ("production halt", -2.4),
    ("suspends production", -2.4), ("stop sale", -2.0),
    ("supply chain disruption", -2.0), ("safety probe", -2.2),
    # Regulatory
    ("fda approval", 2.6), ("fda approves", 2.6), ("fda rejects", -2.8),
    ("regulatory approval", 2.2), ("antitrust probe", -2.2),
    ("sec investigation", -2.6), ("class action", -2.0),
    # Capital
    ("share buyback", 2.0), ("share repurchase", 1.8),
    ("dividend increase", 1.8), ("raises dividend", 1.8),
    ("dividend cut", -2.6), ("cuts dividend", -2.6), ("suspends dividend", -2.8),
    ("secondary offering", -1.8), ("stock offering", -1.6),
    # Leadership
    ("ceo steps down", -1.6), ("ceo resigns", -1.8), ("cfo resigns", -2.0),
    ("abrupt departure", -2.0), ("names new ceo", 0.4),
    # Deals
    ("takeover bid", 2.4), ("acquisition target", 2.0), ("buyout offer", 2.4),
    ("deal collapses", -2.4), ("merger terminated", -2.2),
    # Demand
    ("record revenue", 2.4), ("record quarter", 2.4), ("record backlog", 2.2),
    ("demand slowdown", -2.2), ("weak demand", -2.2), ("soft demand", -2.0),
    ("inventory glut", -2.2), ("price war", -2.0),
)


def phrase_adjustment(text: str, phrases: Iterable[tuple[str, float]] = PHRASES) -> float:
    """
    Total valence of every phrase present in *text*, on VADER's compound scale.

    Each phrase contributes at most once however often it appears — a headline
    repeating a term is not twice the news. The caller is responsible for
    combining this with VADER's own compound and re-clamping to [-1, 1].
    """
    lowered = text.lower()
    return sum(valence for phrase, valence in phrases if phrase in lowered)


def build_analyzer():
    """
    A VADER analyser with the financial vocabulary merged in.

    Constructed per call rather than cached at import: SentimentIntensityAnalyzer
    holds mutable lexicon state, and a module-level singleton shared across the
    scheduler's threads would be a quiet correctness hazard for no real saving —
    construction is a dictionary load.
    """
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    analyzer = SentimentIntensityAnalyzer()
    analyzer.lexicon.update(LEXICON_TERMS)
    return analyzer
