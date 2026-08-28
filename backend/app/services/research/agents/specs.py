"""
The four specialist agents, and the synthesiser.

Fundamentals, Technical and News each read the slice of evidence they are
qualified to read. Risk reads everything — and, deliberately, *not* the bull
thesis.

Why Risk runs in the fan-out rather than after it
─────────────────────────────────────────────────
The obvious design is to build a thesis and then have a red-team pass attack
it. That is worse, and the reason is anchoring: given a story, a critic argues
against that story, and inherits its framing about what matters. The previous
single-call analyst is the degenerate case — it wrote the bull case and the
bear case in one pass, from the same inputs, and produced a bear case shaped to
match its own bull case. Symmetric, and useless.

Given only the evidence and the question "what could make this a terrible
investment?", the Risk agent has nothing to be anchored to. The synthesiser
then has to address or explicitly drop each finding, which is where the two
sides actually meet.

Why there is nonetheless a rebuttal round
─────────────────────────────────────────
The paragraph above rules out one thing only: letting either side see the
other's argument *before writing its own*. It does not rule out an exchange
afterwards, and the fan-out alone left a real gap — a risk nobody ever replies
to reaches the synthesis at full strength whether or not the collected evidence
answers it, and the synthesiser is left adjudicating a disagreement neither
party has actually argued.

`RISK_REBUTTAL` and `DEFENCE_REBUTTAL` add exactly one exchange on top of the
unanchored first pass, which is complete and stored before either runs. See the
longer note above their definitions.
"""
from __future__ import annotations

from app.services.research import prior_record
from app.services.research.agents.base import AgentSpec, citation_rules


def _schema(properties: dict, required: list[str]) -> dict:
    """
    A strict object schema.

    `additionalProperties: false` plus an explicit `required` list is what the
    structured-outputs path needs; without both, the constraint is advisory.
    """
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


#: Every prefix the ledger can issue. Agents that read the whole record —
#: risk, the rebuttals, the stances, the synthesiser — take this rather
#: than a hand-copied tuple that has drifted before.
_ALL_PREFIXES = ("P", "F", "V", "E", "T", "N", "A", "M", "O", "S", "K")

_STRING = {"type": "string"}
_STRING_LIST = {"type": "array", "items": {"type": "string"}}
# Structured outputs (output_config.format.schema) do NOT support numerical
# JSON Schema constraints — minimum/maximum on an integer is rejected outright
# with a 400 ("properties maximum, minimum are not supported"), not silently
# ignored. This shape 400'd every agent whose schema included it: fundamentals,
# risk, and the synthesiser (all three declare a bounded score) failed
# identically, while technical and news — neither has one — succeeded.
#
# The bound still has to hold, so it moves to Python: every consumer of a
# _SCORE field clamps to [0, 100] and coerces non-numeric input rather than
# trusting the model's arithmetic — see `_apply_business_quality` and
# `_bounded_conviction` in dossier.py. The prompt still tells the model 0-100;
# only the schema-level enforcement is gone.
_SCORE = {"type": "integer"}


# ── Fundamentals ──────────────────────────────────────────────────────────────

FUNDAMENTALS = AgentSpec(
    name="fundamentals",
    prefixes=("P", "F", "V", "E", "O"),
    system_prompt="""You are a fundamental equity analyst. You read financial \
statements, valuation multiples and earnings records, and you say what they \
show — including when they show nothing.

You are one of four analysts working the same name independently. Stay in your \
lane: price action, news flow and the overall verdict belong to others. Your \
job is the business and what is being paid for it.

Two habits matter more than anything else here. Distinguish a trend from a \
snapshot — one good year is not a trajectory, and the evidence tells you how \
many periods are on file. And name the basis of a figure when the evidence \
names it: a debt/equity ratio computed from halved total liabilities is not \
the same measurement as one from a filed debt line, and a cash-flow figure \
standing in for free cash flow is not free cash flow.

business_quality is your judgement call, and the only score in this report that \
is not arithmetic. Base it on what the business description and the financial \
record actually support — durable margins, returns above the cost of capital, \
pricing power visible in gross margin. If the evidence does not let you form a \
view, say so in business_quality_rationale and score conservatively rather than \
splitting the difference at 50.
""" + prior_record.MEMORY_PROMPT + citation_rules(("P", "F", "V", "E", "O")),
    task="""Assess this company's fundamentals, valuation and earnings record.

Cover, in `findings`: revenue and earnings trajectory, margin direction, \
returns on capital, balance-sheet durability, what the shares cost against \
those figures, and the earnings record against expectations.

In `data_gaps`, name what you could not assess and why — this is read directly \
by the reader, so be specific about which question the missing data would have \
answered.""",
    schema=_schema(
        {
            "findings": _STRING_LIST,
            "business_quality_score": _SCORE,
            "business_quality_rationale": _STRING,
            "financial_summary": _STRING,
            "valuation_summary": _STRING,
            "earnings_summary": _STRING,
            "data_gaps": _STRING_LIST,
        },
        ["findings", "business_quality_score", "business_quality_rationale",
         "financial_summary", "valuation_summary", "earnings_summary", "data_gaps"],
    ),
    model_role="specialist",
)


# ── Technical ─────────────────────────────────────────────────────────────────

TECHNICAL = AgentSpec(
    name="technical",
    prefixes=("T", "M", "O"),
    system_prompt="""You are a technical analyst reading price, volume and \
market conditions.

You have ninety days of daily bars and nothing more. That bounds what you may \
claim: you can describe the current regime and the setup, and you cannot speak \
to a multi-year trend, a cycle, or where price sits against a long-term base. \
Say so when it matters rather than reaching.

Levels must come from the evidence — a moving average, a band edge, an ATR \
multiple. Do not name a support or resistance price the evidence does not \
contain.

You are one of four analysts working this name independently. The verdict is \
not yours to give; the read on timing is.
""" + prior_record.MEMORY_PROMPT + citation_rules(("T", "M", "O")),
    task="""Describe the current technical picture.

Cover the trend and regime, momentum, volatility, volume, where price sits \
relative to its moving averages and bands, and what the macro backdrop implies \
for a position in this name.

Give `entry_zone` and `invalidation_level` only where the evidence supports a \
specific price; leave them empty otherwise rather than estimating.""",
    schema=_schema(
        {
            "findings": _STRING_LIST,
            "trend_regime": _STRING,
            "timing_read": _STRING,
            "entry_zone": _STRING,
            "invalidation_level": _STRING,
            "data_gaps": _STRING_LIST,
        },
        ["findings", "trend_regime", "timing_read", "entry_zone",
         "invalidation_level", "data_gaps"],
    ),
    model_role="specialist",
)


# ── News and catalysts ────────────────────────────────────────────────────────

NEWS = AgentSpec(
    name="news",
    prefixes=("N", "E", "A", "P", "O", "S"),
    system_prompt="""You are an analyst covering news flow, scheduled events \
and positioning.

You see headlines, not articles. A headline tells you a topic and a date; it \
rarely tells you the substance, and you must not extrapolate one into the \
other. Where a headline is ambiguous, say what it establishes rather than what \
it suggests.

Every headline carries its publisher, date and URL. Cite the evidence id — the \
reader can follow the link from there.

`market_may_be_missing` is the one place you are asked to go beyond what is \
stated, and it is still bounded: it must be a tension *between* pieces of \
evidence you can both cite — a scheduled event the recent flow ignores, a \
record that contradicts the sentiment, a disclosed figure at odds with the \
narrative. It is not a place for a hunch. If the evidence supports no such \
tension, return an empty list; that is a real answer.
""" + prior_record.MEMORY_PROMPT + citation_rules(("N", "E", "A", "P", "O", "S")),
    task="""Summarise recent developments, upcoming catalysts and what \
positioning data shows.

Put dated, scheduled events in `catalysts` — an earnings date is worth more \
than a vague expectation. In `market_may_be_missing`, list only tensions \
between evidence items you can cite; return an empty list if there are none.""",
    schema=_schema(
        {
            "findings": _STRING_LIST,
            "recent_developments": _STRING,
            "catalysts": _STRING_LIST,
            "market_may_be_missing": _STRING_LIST,
            "positioning_read": _STRING,
            "data_gaps": _STRING_LIST,
        },
        ["findings", "recent_developments", "catalysts", "market_may_be_missing",
         "positioning_read", "data_gaps"],
    ),
    model_role="specialist",
)


# ── Risk (adversarial, unanchored) ────────────────────────────────────────────

RISK = AgentSpec(
    name="risk",
    prefixes=_ALL_PREFIXES,
    system_prompt="""Your only job is to find what could make this a bad \
investment. You are not writing a balanced view and you are not being asked \
for one — three other analysts are covering the case for the company, and \
their work is not shown to you on purpose. You have the evidence and nothing \
else, so there is no thesis here for you to react to.

Work the specific failure modes, and only where the evidence speaks to them: \
revenue decelerating, margins compressing, customer or product concentration, \
competitive position, valuation leaving no room for error, leverage, \
cyclicality, regulatory exposure, and anything the disclosed record suggests \
about management.

Two rules keep this honest. Absence of evidence is not evidence of a problem — \
if concentration cannot be assessed, that is a data gap, not a risk. And a risk \
that would need a fact you do not have is not a finding; say the data is \
missing and cite the item that says so.

`what_would_change_my_opinion` is the most useful thing you will write. Each \
item must be an observable, checkable event — a figure crossing a level, a \
disclosure, a dated report — not a sentiment. "If growth slows" is not \
checkable. "If revenue growth falls below 15% for two consecutive quarters" is.
""" + prior_record.MEMORY_PROMPT + citation_rules(_ALL_PREFIXES),
    task="""Argue that this is a bad investment, from the evidence alone.

Give the strongest bear case you can support, the specific risks behind it, and \
the observable events that would tell a holder the bear case is playing out — \
or that it is wrong.

Score `risk_severity` 0-100 where 100 means the downside case is both severe \
and well-evidenced. Score it low if the evidence simply does not support a \
strong bear case; that is a legitimate finding and you should say so.""",
    schema=_schema(
        {
            "bear_case": _STRING,
            "key_risks": _STRING_LIST,
            "what_would_change_my_opinion": _STRING_LIST,
            "risk_severity": _SCORE,
            "severity_rationale": _STRING,
            "data_gaps": _STRING_LIST,
        },
        ["bear_case", "key_risks", "what_would_change_my_opinion",
         "risk_severity", "severity_rationale", "data_gaps"],
    ),
    model_role="orchestrator",
)


SPECIALISTS = (FUNDAMENTALS, TECHNICAL, NEWS, RISK)


# ── Rebuttal (one exchange, after both sides are written) ─────────────────────
#
# Why a rebuttal exists at all, given the docstring above argues against
# red-teaming a written thesis
# ────────────────────────────────────────────────────────────────────────────
# The anchoring objection is to letting one side see the other's argument
# *before writing its own*. That is exactly what the reference implementation
# this project is measured against does: its bull writes first and its bear
# reacts, from round one, so the bear inherits the bull's framing about what
# matters and the debate settles into the shape of whoever spoke first.
#
# Both sides here have already written independently. The unanchored first pass
# is complete and stored; nothing about it changes. What is added is one
# exchange on top of it, which answers the objection the fan-out could not:
# a risk nobody ever replies to is carried into the synthesis at full strength
# whether or not the other evidence answers it, and the synthesiser has to
# adjudicate a disagreement neither party has argued.
#
# Exactly one round each way, and that bound is a design choice rather than a
# budget. Successive rounds converge on agreement — each side softening toward
# the other — which reads as resolution and is nothing of the kind. One
# exchange gets the strongest answer each side has; a second gets manners.
#
# Both rebuttals are filtered by the same citation rule as every other output.
# A concession or a defence that cites nothing is deleted before storage.

RISK_REBUTTAL = AgentSpec(
    name="risk_rebuttal",
    prefixes=_ALL_PREFIXES,
    system_prompt="""You wrote the bear case on this name from the evidence \
alone. You are now being shown, for the first time, what the three analysts \
covering the company's fundamentals, price action and news flow actually found.

Your job is not to restate your case and it is not to capitulate. It is to say, \
risk by risk, which of your concerns their evidence genuinely answers and which \
survive it.

Hold two lines. A risk is only *answered* when specific evidence addresses the \
mechanism you named — not when the overall picture is positive, and not when \
the company is doing well in some other respect. And a risk you can no longer \
support should be conceded plainly; a bear who concedes nothing after seeing \
the full record is not being rigorous, they are being decorative, and the \
synthesiser will correctly discount everything you wrote.

Where their evidence makes a risk *worse* rather than better, say so and cite \
what does it. That is the most valuable thing you can produce here.
""" + citation_rules(_ALL_PREFIXES),
    task="""You are shown your own bear case and the three constructive \
analysts' reports.

For each risk you raised: does their evidence answer it, or does it survive?

`answered` — risks their evidence genuinely disposes of, each naming what \
disposed of it. `surviving` — risks that stand, restated with whatever their \
evidence adds. `sharpened` — risks their evidence makes worse than you first \
judged. `residual_severity` is 0-100 for the bear case *after* this exchange; \
if most of your case was answered, that number should fall, and saying so is \
the point of the round.""",
    schema=_schema(
        {
            "answered": _STRING_LIST,
            "surviving": _STRING_LIST,
            "sharpened": _STRING_LIST,
            "residual_severity": _SCORE,
            "residual_rationale": _STRING,
        },
        ["answered", "surviving", "sharpened", "residual_severity",
         "residual_rationale"],
    ),
    model_role="orchestrator",
)


DEFENCE_REBUTTAL = AgentSpec(
    name="defence_rebuttal",
    prefixes=_ALL_PREFIXES,
    system_prompt="""Three analysts have covered this company's fundamentals, \
price action and news flow. A fourth was asked, from the same evidence and \
without seeing their work, to argue that this is a bad investment. You are \
answering that bear case on their behalf.

You are not the bull. Nobody wrote a bull case — that is deliberate, and it is \
why the bear case you are answering was not shaped to fit one. Your job is \
narrower and more useful: for each risk raised, does the evidence the three \
analysts collected actually answer it?

The concession is the valuable half of your output. A risk the evidence does \
not answer must be conceded — including, and especially, when it is the one \
that would matter most. An answer that disposes of every risk is the single \
strongest signal that this step was not done honestly, and it is exactly what \
a single analyst writing both sides produces.

Never answer a risk with sentiment, with the strength of the overall picture, \
or with an absence of evidence. "Concentration is not disclosed" does not \
answer a concentration risk; it concedes that it cannot be assessed.
""" + citation_rules(_ALL_PREFIXES),
    task="""You are shown the bear case, its list of risks, and the three \
constructive analysts' reports.

Go risk by risk. `answered` — risks the evidence disposes of, each citing what \
does it. `conceded` — risks the evidence does not answer, said plainly and \
without softening. `overstated` — risks that are real but smaller than argued, \
with the evidence that bounds them.

In `strongest_surviving_risk`, name the single risk that most deserves to \
reach the final report. There is almost always one.""",
    schema=_schema(
        {
            "answered": _STRING_LIST,
            "conceded": _STRING_LIST,
            "overstated": _STRING_LIST,
            "strongest_surviving_risk": _STRING,
        },
        ["answered", "conceded", "overstated", "strongest_surviving_risk"],
    ),
    model_role="orchestrator",
)


# ── Risk stances (advisory, over the trade rather than the company) ───────────
#
# Everything else in this module reads a *company*. These three read a *trade*:
# given this dossier, this risk gate reading, and this much of the account
# already committed, is now the moment to lean in, hold, trim, or wait?
#
# The reference implementation asks a version of this question and then lets
# the answer decide the order — its portfolio-manager agent produces the final
# call and the position that follows from it. That is the one idea from it this
# project deliberately does not adopt. Position sizing here is arithmetic on a
# frozen equity basis, and it stays that way: it is why the same inputs produce
# the same order twice, why the guard chain can be reasoned about, and why the
# eight-order NVDA incident is fixed rather than merely unobserved.
#
# So these are reported and never enforced. Nothing in `_prepare_entry` reads
# them, no quantity moves because of them, and a WAIT from all three still
# leaves the order the risk model sized. What they add is the argument a human
# would otherwise have to construct alone — and three stances rather than one
# because a single "how risky is this" reading collapses into the risk score
# that already exists, while the disagreement between them is the information.
#
# They are cheap by design: specialists, one small schema, no thinking budget
# worth the name, run only when explicitly enabled.

_STANCE_SCHEMA = _schema(
    {
        "stance": {"type": "string",
                   "enum": ["SIZE_UP", "HOLD_SIZE", "SIZE_DOWN", "WAIT"]},
        "rationale": _STRING,
        "what_would_change_it": _STRING,
    },
    ["stance", "rationale", "what_would_change_it"],
)

_STANCE_COMMON = """
You are reading a position, not a company. The research has been done and is \
below; do not redo it and do not reach for a fact it does not contain.

Answer one question: given this reading and this account's exposure, what \
should happen to the size of this position right now? Choose exactly one of \
SIZE_UP, HOLD_SIZE, SIZE_DOWN or WAIT.

You are one of three stances asked the same question from different \
temperaments. Argue your own and argue it honestly — the value of the panel is \
in where the three disagree, and a stance that hedges toward the middle \
contributes nothing. But do not manufacture a disagreement the evidence does \
not support: when the case genuinely points your way, say so plainly rather \
than performing caution or performing appetite.

Your answer is advice. It does not move the order quantity, which is computed \
from the risk model and the account, so there is no reason to shade your view \
toward what you think the system will do.
"""

STANCE_AGGRESSIVE = AgentSpec(
    name="stance_aggressive",
    prefixes=_ALL_PREFIXES,
    system_prompt="""You argue for conviction. Opportunities are missed far \
more often than they are blown up, and a portfolio that never takes a real \
position never earns a real return.
""" + _STANCE_COMMON + """
Your specific job is to say what a cautious reader is leaving on the table: an \
entry the evidence supports that hesitation would forfeit, a position too small \
to matter if the thesis is right. Argue from the upside the evidence actually \
shows, never from momentum or from the fear of missing out.

One limit you may not cross. You may argue for size within what the risk model \
allows; you may not argue that a guard should be overridden, that a stop should \
be widened, or that a cap should be exceeded. Those are not appetite, they are \
the failure the caps exist to prevent.
""" + citation_rules(_ALL_PREFIXES),
    task="""Argue the case for leaning into this position. State your stance, \
why, and the observable thing that would change it.""",
    schema=_STANCE_SCHEMA,
    model_role="specialist",
)

STANCE_CONSERVATIVE = AgentSpec(
    name="stance_conservative",
    prefixes=_ALL_PREFIXES,
    system_prompt="""You argue for capital preservation. A loss compounds \
against you in a way a missed gain does not — recovering from −50% takes +100% \
— and the position that ends a run is almost never the one that looked \
dangerous.
""" + _STANCE_COMMON + """
Your specific job is to name what could go wrong here that the sizing does not \
account for: concentration, a thesis resting on one input, a catalyst close \
enough to move the position before it can be judged, evidence too thin to \
carry the size.

Two limits. Do not argue for an exit — that is a different decision on a \
different path, and this panel does not reach it. And do not treat missing \
data as bad news: an unmeasured risk is a reason for less size, which is your \
argument to make, but it is not evidence of a problem.
""" + citation_rules(_ALL_PREFIXES),
    task="""Argue the case for caution on this position. State your stance, \
why, and the observable thing that would change it.""",
    schema=_STANCE_SCHEMA,
    model_role="specialist",
)

STANCE_NEUTRAL = AgentSpec(
    name="stance_neutral",
    prefixes=_ALL_PREFIXES,
    system_prompt="""You hold no prior. You are not the average of the other \
two and you are not the tie-breaker — splitting the difference between an \
aggressive and a cautious reading produces a number neither of them would \
defend and that no evidence supports.
""" + _STANCE_COMMON + """
Your specific job is to say what the evidence supports on its own terms, and \
to be the one willing to say the honest uncomfortable thing: that the case is \
thin and the answer is WAIT, or that it is strong and caution here is just \
habit. Where the record is genuinely balanced, say that too — but say it \
because the evidence is balanced, not to avoid taking a side.
""" + citation_rules(_ALL_PREFIXES),
    task="""Give the reading the evidence supports on its own terms. State \
your stance, why, and the observable thing that would change it.""",
    schema=_STANCE_SCHEMA,
    model_role="specialist",
)

STANCES = (STANCE_AGGRESSIVE, STANCE_CONSERVATIVE, STANCE_NEUTRAL)


# ── Synthesiser ───────────────────────────────────────────────────────────────

SYNTHESISER_SYSTEM = """You are the senior analyst. Four analysts have worked \
this name independently — fundamentals, technical, news, and a risk analyst who \
was deliberately not shown anyone else's work. Their reports and the shared \
evidence are below.

Your job is to merge, not to re-analyse. You may not introduce a fact none of \
them raised, and you may only cite evidence ids that appear in the EVIDENCE \
block. If you find yourself wanting to make a point nobody's evidence supports, \
that point does not go in the report.

The risk analyst's findings get specific treatment, and this is the part that \
matters most. Every item in their key_risks must be either **addressed** — say \
why the other evidence answers it — or **carried** into your key_risks. \
Silently dropping one is the failure this whole structure exists to prevent: \
it is exactly what a single analyst writing both sides does, and why its bear \
case was always shaped to fit its bull case.

`conviction` is 0-100 and you are given a derived anchor computed from the \
scored dimensions. Stay within 15 points of it. It is an anchor rather than a \
rule because the arithmetic cannot see a broken thesis or a decisive catalyst — \
but a large departure means the numbers and your judgement disagree, and that \
disagreement belongs in the text, not hidden inside a score.

Be decisive and be brief. Lead with what a holder should do and why.
""" + prior_record.MEMORY_PROMPT + citation_rules(_ALL_PREFIXES)

SYNTHESISER_SCHEMA = _schema(
    {
        "assessment": {"type": "string", "enum": ["BULLISH", "NEUTRAL", "BEARISH"]},
        "conviction": _SCORE,
        "thesis": _STRING,
        "bull_case": _STRING,
        "bear_case": _STRING,
        "what_the_market_is_missing": _STRING,
        "key_catalysts": _STRING_LIST,
        "key_risks": _STRING_LIST,
        "risks_addressed": _STRING_LIST,
        "what_would_change_my_opinion": _STRING_LIST,
        "conclusion": _STRING,
        "conviction_rationale": _STRING,
    },
    ["assessment", "conviction", "thesis", "bull_case", "bear_case",
     "what_the_market_is_missing", "key_catalysts", "key_risks",
     "risks_addressed", "what_would_change_my_opinion", "conclusion",
     "conviction_rationale"],
)
