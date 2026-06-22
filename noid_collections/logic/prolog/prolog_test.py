"""Tests for slm:prolog — mocks PySwip so SWI-Prolog need not be installed."""
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from noid.core.bus import Bus
from noid_collections.logic.prolog.prolog import (
    PrologAgentOid,
    _normalize_query,
    _clean_value,
)


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

def test_normalize_query_strips_prefix_and_dot() -> None:
    assert _normalize_query("?- member(X, [1,2,3]).") == "member(X, [1,2,3])"
    assert _normalize_query("  member(X, [1]).  ") == "member(X, [1])"


def test_clean_value_bytes() -> None:
    assert _clean_value(b"hello") == "hello"


def test_clean_value_nested() -> None:
    assert _clean_value({"a": b"x", "b": [b"y"]}) == {"a": "x", "b": ["y"]}


# ---------------------------------------------------------------------------
# Bus-level tests with mocked PySwip
# ---------------------------------------------------------------------------

def _make_fake_pyswip(solutions):
    """Return a fake pyswip module whose Prolog().query() yields solutions.

    _run_prolog calls query() twice: once for consult(), once for the goal.
    side_effect ensures the first call returns [] and the second returns solutions.
    """
    fake_prolog_instance = MagicMock()
    fake_prolog_instance.query.side_effect = [iter([]), iter(solutions)]
    FakeProlog = MagicMock(return_value=fake_prolog_instance)
    fake_module = ModuleType("pyswip")
    fake_module.Prolog = FakeProlog
    return fake_module


async def test_prolog_publishes_solutions() -> None:
    bus = Bus()
    results = []
    bus.subscribe("slm/prolog/result", lambda t, m: results.append(m))

    comp = PrologAgentOid(
        bus=bus,
        subscribe="test/prolog~query",
        properties={"facts_rules": "human(socrates). mortal(X) :- human(X)."},
    )
    await comp.start()

    solutions = [{"X": b"socrates"}]
    fake_mod = _make_fake_pyswip(solutions)

    with patch.dict(sys.modules, {"pyswip": fake_mod}):
        await bus.publish("test/prolog", {"query": "?- mortal(X)."})

    assert len(results) == 1
    assert results[0]["solution_count"] == 1
    assert results[0]["query"] == "mortal(X)"
    await comp.stop()


async def test_prolog_extra_facts_in_message() -> None:
    bus = Bus()
    results = []
    bus.subscribe("slm/prolog/result", lambda t, m: results.append(m))

    comp = PrologAgentOid(bus=bus, subscribe="test/prolog~query")
    await comp.start()

    solutions = [{"X": b"alice"}]
    fake_mod = _make_fake_pyswip(solutions)

    with patch.dict(sys.modules, {"pyswip": fake_mod}):
        await bus.publish("test/prolog", {
            "query": "mortal(X)",
            "facts_rules": "human(alice). mortal(X) :- human(X).",
        })

    assert results[0]["solution_count"] == 1
    await comp.stop()


async def test_prolog_plain_string_message() -> None:
    bus = Bus()
    results = []
    bus.subscribe("slm/prolog/result", lambda t, m: results.append(m))

    comp = PrologAgentOid(
        bus=bus,
        subscribe="test/prolog~query",
        properties={"facts_rules": "color(red). color(blue)."},
    )
    await comp.start()

    solutions = [{"X": b"red"}, {"X": b"blue"}]
    fake_mod = _make_fake_pyswip(solutions)

    with patch.dict(sys.modules, {"pyswip": fake_mod}):
        await bus.publish("test/prolog", "color(X)")

    assert results[0]["solution_count"] == 2
    await comp.stop()


async def test_prolog_missing_pyswip_publishes_error() -> None:
    bus = Bus()
    errors = []
    bus.subscribe("slm/prolog/error", lambda t, m: errors.append(m))

    comp = PrologAgentOid(bus=bus, subscribe="test/prolog~query")
    await comp.start()

    with patch.dict(sys.modules, {"pyswip": None}):
        await bus.publish("test/prolog", {"query": "foo(X)"})

    assert len(errors) == 1
    assert "pyswip" in errors[0]["message"].lower() or "prolog" in errors[0]["message"].lower()
    await comp.stop()
