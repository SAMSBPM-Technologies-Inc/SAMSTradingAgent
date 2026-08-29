"""
Structured-outputs JSON Schema validity for the research agents.

`output_config.format.schema` is not full JSON Schema — a documented subset is
rejected outright with a 400, not silently ignored. This is what actually broke
the first real production run: `_SCORE` declared `{"type": "integer",
"minimum": 0, "maximum": 100}`, and every agent whose schema carried it —
fundamentals, risk, the synthesiser — failed identically against the live API
with "properties maximum, minimum are not supported". technical and news, with
no bounded-integer field, both succeeded. Four of the fake-client tests in
test_research_orchestrator.py exercised these exact schemas and could not have
caught this, because nothing in this codebase validates a schema against what
the API actually accepts — only a live call does, and by then it costs money
and fails opaquely.

This suite is the substitute for that live call: a static lint against the
documented unsupported-constructs list, run on every real schema in the
package. Add to the forbidden list below only when the docs change; do not
weaken an assertion to make a schema pass.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.research.agents import specs  # noqa: E402

#: Keys documented as unsupported by structured outputs, by the JSON type they
#: attach to. Presence of any of these on a schema node is a 400, not a
#: silent no-op — see shared/tool-use-concepts.md's Structured Outputs section.
_FORBIDDEN_NUMERIC = ("minimum", "maximum", "multipleOf")
_FORBIDDEN_STRING = ("minLength", "maxLength")
_FORBIDDEN_ARRAY = ("minItems", "maxItems", "uniqueItems")


def _walk(node: Any, path: str = "$"):
    """Yield (path, node) for every dict node in a JSON Schema, depth-first."""
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _walk(item, f"{path}[{i}]")


def _all_schemas():
    """
    Every schema that reaches a provider, not just the original four.

    The rebuttal and stance specs were added later and were not covered here —
    a real gap, since they carry the same `_SCORE` shape whose numeric bounds
    caused the incident this file documents. A schema that is not in this list
    is a schema nothing lints.
    """
    schemas = [(spec.name, spec.schema) for spec in specs.SPECIALISTS]
    schemas.append(("synthesiser", specs.SYNTHESISER_SCHEMA))
    schemas.append(("risk_rebuttal", specs.RISK_REBUTTAL.schema))
    schemas.append(("defence_rebuttal", specs.DEFENCE_REBUTTAL.schema))
    schemas.extend((spec.name, spec.schema) for spec in specs.STANCES)
    return schemas


@pytest.mark.parametrize("name,schema", _all_schemas())
def test_no_numeric_bounds_on_number_or_integer_fields(name, schema):
    for path, node in _walk(schema):
        if node.get("type") in ("integer", "number"):
            present = [k for k in _FORBIDDEN_NUMERIC if k in node]
            assert not present, (
                f"{name}: {path} declares {present} — rejected by the live API "
                f"with 'properties {', '.join(present)} are not supported'. "
                f"Enforce the bound in Python after parsing instead."
            )


@pytest.mark.parametrize("name,schema", _all_schemas())
def test_no_length_bounds_on_string_fields(name, schema):
    for path, node in _walk(schema):
        if node.get("type") == "string":
            present = [k for k in _FORBIDDEN_STRING if k in node]
            assert not present, f"{name}: {path} declares {present} (unsupported)"


@pytest.mark.parametrize("name,schema", _all_schemas())
def test_no_array_constraints(name, schema):
    for path, node in _walk(schema):
        if node.get("type") == "array":
            present = [k for k in _FORBIDDEN_ARRAY if k in node]
            assert not present, f"{name}: {path} declares {present} (unsupported)"


@pytest.mark.parametrize("name,schema", _all_schemas())
def test_every_object_is_closed(name, schema):
    """
    `additionalProperties` must be exactly `False` on every object node, or the
    structured-outputs constraint is advisory rather than enforced — the same
    class of "looks right, does nothing" failure as the bounds above, just
    without a 400 to catch it.
    """
    for path, node in _walk(schema):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, (
                f"{name}: {path} is an object schema without "
                f"additionalProperties: false"
            )


@pytest.mark.parametrize("name,schema", _all_schemas())
def test_no_recursive_refs(name, schema):
    """Recursive schemas are unsupported; $ref/$def have no place here at all."""
    for path, node in _walk(schema):
        assert "$ref" not in node, f"{name}: {path} uses $ref (unsupported)"
        assert "$def" not in node, f"{name}: {path} uses $def (unsupported)"


def test_every_agent_declares_a_json_schema_format():
    """
    Catches a spec built without going through `_schema()` at all — a raw dict
    missing `additionalProperties` or `required` would pass every check above
    by having nothing to flag, which is worse than failing loudly.
    """
    for name, schema in _all_schemas():
        assert schema.get("type") == "object", name
        assert isinstance(schema.get("required"), list) and schema["required"], name
        assert set(schema["required"]) <= set(schema.get("properties", {})), name


# ── Per-provider legality ─────────────────────────────────────────────────────
# Everything above lints against Anthropic's rules, which is what the schemas
# were authored for. A trader may now put a different provider on an agent, and
# the dialects genuinely differ — Gemini rejects `additionalProperties`, which
# appears on every object in every schema here. Each provider therefore owns a
# `normalise_schema`, and this section is the fence around it.
#
# The failure mode being prevented is the one the file already exists for: a
# 400 that takes out several agents identically and is only discoverable by
# spending money. A per-provider dialect makes that harder to spot, not easier.

from app.services.llm.registry import PROVIDERS  # noqa: E402

_GEMINI_FORBIDDEN = {"additionalProperties", "$schema", "const"}


def _keys_present(node: Any, found: set) -> set:
    if isinstance(node, dict):
        found.update(node.keys())
        for value in node.values():
            _keys_present(value, found)
    elif isinstance(node, list):
        for value in node:
            _keys_present(value, found)
    return found


@pytest.mark.parametrize("name,schema", _all_schemas())
def test_google_normalisation_removes_what_gemini_rejects(name, schema):
    """
    `responseSchema` is OpenAPI-flavoured and rejects these outright rather
    than ignoring them, so they must be gone before the request is built.
    """
    normalised = PROVIDERS["google"].normalise_schema(schema)
    present = _keys_present(normalised, set())
    assert not (present & _GEMINI_FORBIDDEN), (name, present & _GEMINI_FORBIDDEN)


@pytest.mark.parametrize("name,schema", _all_schemas())
def test_google_normalisation_keeps_the_structure(name, schema):
    """
    Stripping is not flattening. The properties and the required list are the
    contract; only the rejected keywords go.
    """
    normalised = PROVIDERS["google"].normalise_schema(schema)
    assert set(normalised.get("properties", {})) == set(schema.get("properties", {}))
    assert normalised.get("required") == schema.get("required")


@pytest.mark.parametrize("name,schema", _all_schemas())
def test_openai_strict_mode_accepts_our_schemas_unchanged(name, schema):
    """
    Strict mode's two hard requirements are `additionalProperties: false` and
    every property listed in `required` — both of which `_schema()` already
    emits. If this ever fails, the schemas drifted and the OpenAI adapter needs
    a real normalisation rather than an identity.
    """
    normalised = PROVIDERS["openai"].normalise_schema(schema)
    assert normalised == schema
    assert normalised.get("additionalProperties") is False
    assert set(normalised.get("required", [])) == set(normalised.get("properties", {}))


@pytest.mark.parametrize("name,schema", _all_schemas())
def test_normalisation_never_mutates_the_source_schema(name, schema):
    """
    The specs are module-level singletons shared by every dossier. A
    normalisation that edited one in place would silently change the schema
    every other provider sees, in call order.
    """
    import copy

    before = copy.deepcopy(schema)
    for provider in PROVIDERS.values():
        provider.normalise_schema(schema)
    assert schema == before
