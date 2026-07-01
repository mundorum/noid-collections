"""Tests for lm:lm-agent — mocks the ollama client to avoid needing a running server."""
import sys
import types
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from noid.core.bus import Bus
from noid_collections.lm_agents.lm.lm import LMAgentOid, _resolve_path, _set_path


@contextmanager
def _fake_ollama(reply: str):
    """Inject a fake ollama module that returns `reply` from client.chat."""
    fake_client = MagicMock()
    fake_client.chat.return_value = {"message": {"content": reply}}
    mod = types.ModuleType("ollama")
    mod.Client = MagicMock(return_value=fake_client)
    with patch.dict(sys.modules, {"ollama": mod}):
        yield fake_client


async def test_lm_agent_publishes_output() -> None:
    bus = Bus()
    received = []
    bus.subscribe("lm/output", lambda t, m: received.append(m))

    comp = LMAgentOid(bus=bus, subscribe="test/lm/in~input", publish="output~lm/output")
    await comp.start()

    with _fake_ollama("The answer is 42."):
        await bus.publish("test/lm/in", {"content": "What is the answer?"})

    assert len(received) == 1
    assert received[0]["content"] == "The answer is 42."
    assert received[0]["model"] == "llama3.2"

    await comp.stop()


async def test_lm_agent_model_configurable() -> None:
    bus = Bus()
    comp = LMAgentOid(bus=bus, properties={"model": "mistral"})
    await comp.start()
    assert comp.model == "mistral"
    await comp.stop()


async def test_lm_render_template() -> None:
    rendered = LMAgentOid._render_template(
        "Q: {question} Context: {input}", "some text", "What year?", {}
    )
    assert rendered == "Q: What year? Context: some text"


async def test_lm_render_template_dotted_path() -> None:
    message = {"index": 1, "row": {"name": "Rot Donnadd", "age": "43"}}
    rendered = LMAgentOid._render_template(
        "Patient: {row.name}, age {row.age}", "", "", message
    )
    assert rendered == "Patient: Rot Donnadd, age 43"


async def test_lm_render_template_flat_and_dotted() -> None:
    message = {"index": 2, "row": {"name": "Jane"}}
    rendered = LMAgentOid._render_template(
        "Record {index}: {row.name}", "", "", message
    )
    assert rendered == "Record 2: Jane"


async def test_lm_render_template_missing_path_is_empty() -> None:
    message = {"row": {"name": "Bob"}}
    rendered = LMAgentOid._render_template("{row.missing}", "", "", message)
    assert rendered == ""


async def test_lm_append_field_top_level() -> None:
    bus = Bus()
    received = []
    bus.subscribe("lm/output", lambda t, m: received.append(m))

    comp = LMAgentOid(
        bus=bus,
        subscribe="test/lm/in~input",
        publish="output~lm/output",
        properties={"append_field": "comment"},
    )
    await comp.start()

    with _fake_ollama("Great insight."):
        await bus.publish("test/lm/in", {"index": 1, "content": "Some text"})

    assert len(received) == 1
    assert received[0]["index"] == 1
    assert received[0]["comment"] == "Great insight."
    assert "model" not in received[0]

    await comp.stop()


async def test_lm_append_field_nested() -> None:
    bus = Bus()
    received = []
    bus.subscribe("lm/output", lambda t, m: received.append(m))

    comp = LMAgentOid(
        bus=bus,
        subscribe="test/lm/in~input",
        publish="output~lm/output",
        properties={"append_field": "row.comment"},
    )
    await comp.start()

    input_msg = {
        "index": 1,
        "row": {"name": "Rot Donnadd", "age": "43", "days_recovery": "9"},
    }
    with _fake_ollama("This is a strange name."):
        await bus.publish("test/lm/in", input_msg)

    assert len(received) == 1
    out = received[0]
    assert out["index"] == 1
    assert out["row"]["name"] == "Rot Donnadd"
    assert out["row"]["age"] == "43"
    assert out["row"]["days_recovery"] == "9"
    assert out["row"]["comment"] == "This is a strange name."

    await comp.stop()


async def test_lm_append_field_does_not_mutate_input() -> None:
    bus = Bus()
    received = []
    bus.subscribe("lm/output", lambda t, m: received.append(m))

    comp = LMAgentOid(
        bus=bus,
        subscribe="test/lm/in~input",
        publish="output~lm/output",
        properties={"append_field": "row.comment"},
    )
    await comp.start()

    original = {"index": 1, "row": {"name": "Alice"}}
    with _fake_ollama("reply"):
        await bus.publish("test/lm/in", original)

    assert "comment" not in original.get("row", {})

    await comp.stop()


async def test_ollama_missing_raises_runtime_error() -> None:
    bus = Bus()
    comp = LMAgentOid(bus=bus, subscribe="test/missing~input")
    await comp.start()

    with patch.dict(sys.modules, {"ollama": None}):
        with pytest.raises(RuntimeError, match="ollama package"):
            await comp.handle_input("input", {"content": "hi"})

    await comp.stop()


def test_resolve_path_nested() -> None:
    obj = {"row": {"name": "Alice", "age": "30"}}
    assert _resolve_path(obj, "row.name") == "Alice"
    assert _resolve_path(obj, "row.age") == "30"


def test_resolve_path_missing() -> None:
    obj = {"row": {"name": "Alice"}}
    assert _resolve_path(obj, "row.missing") == ""
    assert _resolve_path(obj, "other.field") == ""


def test_set_path_existing_nested() -> None:
    obj = {"row": {"name": "Alice"}}
    _set_path(obj, "row.comment", "hello")
    assert obj["row"]["comment"] == "hello"
    assert obj["row"]["name"] == "Alice"


def test_set_path_creates_intermediate() -> None:
    obj = {}
    _set_path(obj, "a.b.c", "value")
    assert obj["a"]["b"]["c"] == "value"
