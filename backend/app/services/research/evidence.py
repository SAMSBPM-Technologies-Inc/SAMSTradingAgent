"""
Evidence Ledger
───────────────
Every fact the research agents are allowed to reason from, each with an id, a
value, a source and a date — and the machinery that drops any sentence they
write which does not cite one.

Why this exists
───────────────
The previous analyst was handed roughly forty pre-computed numbers and eight
bare headlines as a formatted string, and asked for an institutional-grade
research note. It produced one. Nothing in the pipeline could tell which of its
sentences rested on a number in that string and which it had supplied itself,
because the prompt asked for no attribution and the schema had no field to put
one in — and the headline URLs, which were stored, were stripped before the
prompt was built, so citing was not merely unrequested but impossible.

The ledger inverts that. Facts get ids before the model sees them, the model is
required to cite ids, and `strip_uncited` removes what does not. The failure
mode this protects against is not a model that lies; it is a model that is
confidently vague, and a reader who cannot tell the difference.

**Dropping is the point.** An uncited sentence is removed rather than kept with
a caveat, because a caveat is something a reader skims past. A report that
comes back empty because the evidence was thin is a true report about thin
evidence. See `docs`-free precedent elsewhere in this codebase: `explain_score`
refuses to decompose an XGBoost score rather than fabricating a breakdown, and
`commission_complete` leaves P&L unnetted rather than folding in a zero.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, Optional

#: Inline citation form the agents are told to use: [F1], [T3], [N2].
_CITATION = re.compile(r"\[([A-Z]{1,2}\d{1,3})\]")

#: Sentence split that does not break on decimals ("12.4%"), initials, or the
#: abbreviations that turn up constantly in filings ("Inc.", "Q3 FY25").
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])")


@dataclass(frozen=True)
class Evidence:
    """
    One attributable fact.

    `meta` marks an item that describes *our data* rather than the company —
    a declared absence ("no earnings history collected") or a methodological
    caveat ("nearest expiry only"). Both belong in the ledger: an agent that
    cannot see the boundary of what it knows will fill the silence, and these
    are the items it cites when it says a question cannot be answered.

    But they are not evidence *about the company*, and the distinction decides
    whether an agent is worth calling at all. A slice of nothing but "not
    available" lines is a full model call to produce a paragraph saying so —
    which is what an AVGO dossier did on a cold cache before this existed.
    """

    id: str
    claim: str
    value: str
    source: str
    as_of: Optional[str] = None
    url: Optional[str] = None
    meta: bool = False

    def render(self) -> str:
        parts = [f"[{self.id}] {self.claim}: {self.value}"]
        provenance = [p for p in (self.source, self.as_of) if p]
        if provenance:
            parts.append(f"({' — '.join(provenance)})")
        if self.url:
            parts.append(self.url)
        return " ".join(parts)


@dataclass
class Ledger:
    """
    An ordered, id-addressed collection of facts, grouped by section.

    Ids are namespaced by section prefix (F for fundamentals, V valuation,
    E earnings, T technical, N news, A alternative data, P profile) so a reader
    can tell at a glance what kind of thing a citation points at without
    looking it up.
    """

    items: list[Evidence] = field(default_factory=list)
    _counters: dict[str, int] = field(default_factory=dict)

    def add(self, prefix: str, claim: str, value, source: str,
            as_of: Optional[str] = None, url: Optional[str] = None,
            meta: bool = False) -> Optional[str]:
        """
        Record a fact and return its citation id, or None if there is no fact.

        A `None` value is not recorded. This is the single most important line
        in the module: absent data must never enter the ledger as "unknown" or
        "N/A", because an agent will cite it and the citation will look exactly
        like a real one. If we do not have the number, the model does not get a
        way to talk about it.
        """
        if value is None or value == "":
            return None
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        item_id = f"{prefix}{self._counters[prefix]}"
        self.items.append(
            Evidence(
                id=item_id,
                claim=claim,
                value=str(value),
                source=source,
                as_of=as_of,
                url=url,
                meta=meta,
            )
        )
        return item_id

    def ids(self) -> set[str]:
        return {item.id for item in self.items}

    def by_prefix(self, prefixes: Iterable[str]) -> list[Evidence]:
        wanted = tuple(prefixes)
        return [i for i in self.items if i.id.rstrip("0123456789") in wanted]

    def substantive(self, prefixes: Optional[Iterable[str]] = None) -> list[Evidence]:
        """
        Items that say something about the company, excluding `meta` ones.

        This is what decides whether an agent gets called. Note it is not the
        same as what the agent is *shown* — a called agent still receives the
        meta items, because knowing the boundary of the evidence is what stops
        it reasoning past it.
        """
        items = self.items if prefixes is None else self.by_prefix(prefixes)
        return [item for item in items if not item.meta]

    def substantive_count(self, prefixes: Optional[Iterable[str]] = None) -> int:
        return len(self.substantive(prefixes))

    def render(self, prefixes: Optional[Iterable[str]] = None) -> str:
        """Render as a numbered table for the prompt."""
        items = self.items if prefixes is None else self.by_prefix(prefixes)
        if not items:
            return "(no evidence available)"
        return "\n".join(item.render() for item in items)

    def to_list(self) -> list[dict]:
        return [asdict(item) for item in self.items]

    def __len__(self) -> int:
        return len(self.items)


def cited_ids(text: str) -> set[str]:
    """Every citation id referenced in *text*."""
    return set(_CITATION.findall(text or ""))


def strip_uncited(text: Optional[str], valid: set[str]) -> Optional[str]:
    """
    Drop every sentence that does not cite a known evidence id.

    Returns None when nothing survives — the caller renders that as an absent
    section, not as an empty string, so a report with no supportable claims
    reads as having no claims rather than as having a blank field.

    A sentence citing an id we never issued is dropped too. That is the case
    worth being strict about: a fabricated citation is more dangerous than no
    citation, because it survives exactly the check a reader would make.
    """
    if not text:
        return None
    kept = [
        sentence for sentence in _SENTENCE_SPLIT.split(text.strip())
        if sentence.strip() and (cited_ids(sentence) & valid)
    ]
    return " ".join(kept) if kept else None


def strip_uncited_list(items: Optional[list], valid: set[str]) -> list[str]:
    """
    Filter a list of bullet-style claims down to the attributable ones.

    Applied whole-item rather than per-sentence: a risk or a catalyst is one
    claim, and half of one is not a smaller claim but a different one.
    """
    out: list[str] = []
    for item in items or []:
        text = str(item).strip()
        if text and (cited_ids(text) & valid):
            out.append(text)
    return out


def unknown_citations(text: Optional[str], valid: set[str]) -> set[str]:
    """Citation ids referenced by *text* that the ledger never issued."""
    return cited_ids(text or "") - valid
