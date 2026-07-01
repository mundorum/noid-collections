"""Tests for lm:lm-agent — mocks the ollama client to avoid needing a running server."""
import sys
import types
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from noid.core.bus import Bus
from noid_collections.lm_agents.lm.lm import LMAgentOid, _resolve_path


@contextmanager
def _fake_ollama(reply: str):
    """Inject a fake ollama module that returns `reply` from client.chat."""
    fake_client = MagicMock()
    fake_client.chat.return_value = {"message": {"content": reply}}
    mod = types.ModuleType("ollama")
    mod.Client = MagicMock(return_value=fake_client)
    with patch.dict(sys.modules, {"ollama": mod}):
        yield fake_client


async def test_lm_agent_publishes_document() -> None:
    bus = Bus()
    received = []
    bus.subscribe("lm/document", lambda t, m: received.append(m))

    comp = LMAgentOid(bus=bus, subscribe="test/lm/in~input", publish="document~lm/document")
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


async def test_lm_csv_field_document_mode() -> None:
    bus = Bus()
    received = []
    bus.subscribe("lm/document", lambda t, m: received.append(m))

    comp = LMAgentOid(
        bus=bus,
        subscribe="test/lm/in~input",
        publish="document~lm/document",
        properties={"csv_field": "comment"},
    )
    await comp.start()

    with _fake_ollama("Great insight."):
        await bus.publish("test/lm/in", {"index": 1, "content": "Some text"})

    assert len(received) == 1
    assert received[0]["index"] == 1
    assert received[0]["comment"] == "Great insight."
    assert "model" not in received[0]

    await comp.stop()


async def test_lm_csv_field_document_mode_does_not_mutate_input() -> None:
    bus = Bus()
    received = []
    bus.subscribe("lm/document", lambda t, m: received.append(m))

    comp = LMAgentOid(
        bus=bus,
        subscribe="test/lm/in~input",
        publish="document~lm/document",
        properties={"csv_field": "comment"},
    )
    await comp.start()

    original = {"index": 1, "content": "hi"}
    with _fake_ollama("reply"):
        await bus.publish("test/lm/in", original)

    assert "comment" not in original

    await comp.stop()


async def test_lm_schema_adds_csv_field_column() -> None:
    bus = Bus()
    received = []
    bus.subscribe("lm/schema", lambda t, m: received.append(m))

    comp = LMAgentOid(
        bus=bus,
        subscribe="test/lm/schema~schema",
        publish="schema~lm/schema",
        properties={"csv_field": "comment"},
    )
    await comp.start()

    await bus.publish("test/lm/schema", {"label": "patients", "columns": ["name", "age"]})

    assert received == [{"label": "patients", "columns": ["name", "age", "comment"]}]

    await comp.stop()


async def test_lm_schema_ignored_without_csv_field() -> None:
    bus = Bus()
    received = []
    bus.subscribe("lm/schema", lambda t, m: received.append(m))

    comp = LMAgentOid(bus=bus, subscribe="test/lm/schema~schema", publish="schema~lm/schema")
    await comp.start()

    await bus.publish("test/lm/schema", {"columns": ["name", "age"]})

    assert received == []

    await comp.stop()


async def test_lm_row_adds_reply_below_row() -> None:
    bus = Bus()
    received = []
    bus.subscribe("lm/row", lambda t, m: received.append(m))

    comp = LMAgentOid(
        bus=bus,
        subscribe="test/lm/row~row",
        publish="row~lm/row",
        properties={
            "csv_field": "comment",
            "prompt_template": "Patient: {row.name}, age {row.age}",
        },
    )
    await comp.start()

    row_msg = {
        "label": "patients",
        "index": 1,
        "row": {"name": "Rot Donnadd", "age": "43"},
    }
    with _fake_ollama("This is a strange name.") as client:
        await bus.publish("test/lm/row", row_msg)

    assert client.chat.call_args.kwargs["messages"][0]["content"] == (
        "Patient: Rot Donnadd, age 43"
    )

    assert len(received) == 1
    out = received[0]
    assert out["label"] == "patients"
    assert out["index"] == 1
    assert out["row"]["name"] == "Rot Donnadd"
    assert out["row"]["age"] == "43"
    assert out["row"]["comment"] == "This is a strange name."

    await comp.stop()


async def test_lm_row_does_not_mutate_input() -> None:
    bus = Bus()
    received = []
    bus.subscribe("lm/row", lambda t, m: received.append(m))

    comp = LMAgentOid(
        bus=bus,
        subscribe="test/lm/row~row",
        publish="row~lm/row",
        properties={"csv_field": "comment"},
    )
    await comp.start()

    original = {"index": 1, "row": {"name": "Alice"}}
    with _fake_ollama("reply"):
        await bus.publish("test/lm/row", original)

    assert "comment" not in original["row"]

    await comp.stop()


async def test_lm_row_ignored_without_csv_field() -> None:
    bus = Bus()
    received = []
    bus.subscribe("lm/row", lambda t, m: received.append(m))

    comp = LMAgentOid(bus=bus, subscribe="test/lm/row~row", publish="row~lm/row")
    await comp.start()

    with _fake_ollama("reply"):
        await bus.publish("test/lm/row", {"index": 1, "row": {"name": "Alice"}})

    assert received == []

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
