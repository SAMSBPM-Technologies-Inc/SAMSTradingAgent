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
    schemas = [(spec.name, spec.schema) for spec in specs.SPECIALISTS]
    schemas.append(("synthesiser", specs.SYNTHESISER_SCHEMA))
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
