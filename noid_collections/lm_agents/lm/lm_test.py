"""Tests for lm:persistent-agent — mocks the ollama client to verify retries, timeouts, and fallbacks."""
import sys
import types
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from noid.core.bus import Bus
from noid_collections.lm_agents.lm.lm import PersistentLMAgentOid


@contextmanager
def _fake_ollama_with_behavior(side_effects):
    """Inject a fake ollama module where client.chat has side_effects.

    side_effects is a list of return values or exceptions.
    Also returns a list of client initialization keyword arguments (e.g. timeout).
    """
    fake_client = MagicMock()
    fake_client.chat.side_effect = side_effects
    mod = types.ModuleType("ollama")

    client_calls = []

    def client_init(*args, **kwargs):
        client_calls.append(kwargs)
        return fake_client

    mod.Client = MagicMock(side_effect=client_init)
    with patch.dict(sys.modules, {"ollama": mod}):
        yield client_calls


async def test_persistent_agent_success_no_retries() -> None:
    bus = Bus()
    received = []
    bus.subscribe("lm/document", lambda t, m: received.append(m))

    comp = PersistentLMAgentOid(
        bus=bus, subscribe="test/lm/in~input", publish="document~lm/document"
    )
    await comp.start()

    chat_response = {"message": {"content": "Hello world"}}
    with _fake_ollama_with_behavior([chat_response]) as client_calls:
        await bus.publish("test/lm/in", {"content": "Hi"})

    assert len(received) == 1
    assert received[0]["content"] == "Hello world"
    assert len(client_calls) == 1
    assert client_calls[0]["timeout"] == 30.0
    await comp.stop()


async def test_persistent_agent_retries_and_succeeds() -> None:
    bus = Bus()
    received = []
    bus.subscribe("lm/document", lambda t, m: received.append(m))

    comp = PersistentLMAgentOid(
        bus=bus,
        subscribe="test/lm/in~input",
        publish="document~lm/document",
        properties={
            "retries": 3,
            "initial_timeout": 5.0,
            "timeout_multiplier": 2.0,
            "backoff_factor": 0.01,  # Keep it fast in tests
        },
    )
    await comp.start()

    chat_response = {"message": {"content": "Succeeded on attempt 3"}}
    side_effects = [
        TimeoutError("connection timed out"),
        RuntimeError("server error"),
        chat_response,
    ]
    with _fake_ollama_with_behavior(side_effects) as client_calls:
        await bus.publish("test/lm/in", {"content": "Hi"})

    assert len(received) == 1
    assert received[0]["content"] == "Succeeded on attempt 3"
    assert len(client_calls) == 3
    # Check that timeouts increased: 5.0 -> 10.0 -> 20.0
    assert client_calls[0]["timeout"] == 5.0
    assert client_calls[1]["timeout"] == 10.0
    assert client_calls[2]["timeout"] == 20.0
    await comp.stop()


async def test_persistent_agent_fails_and_returns_fallback() -> None:
    bus = Bus()
    received = []
    bus.subscribe("lm/document", lambda t, m: received.append(m))

    comp = PersistentLMAgentOid(
        bus=bus,
        subscribe="test/lm/in~input",
        publish="document~lm/document",
        properties={
            "retries": 2,
            "initial_timeout": 1.0,
            "timeout_multiplier": 1.5,
            "backoff_factor": 0.01,
            "error_mode": "fallback_value",
            "error_fallback_value": "FALLBACK_TXT",
        },
    )
    await comp.start()

    side_effects = [TimeoutError("timed out 1"), TimeoutError("timed out 2")]
    with _fake_ollama_with_behavior(side_effects) as client_calls:
        await bus.publish("test/lm/in", {"content": "Hi"})

    assert len(received) == 1
    assert received[0]["content"] == "FALLBACK_TXT"
    assert len(client_calls) == 2
    await comp.stop()


async def test_persistent_agent_fails_and_propagates() -> None:
    bus = Bus()
    comp = PersistentLMAgentOid(
        bus=bus,
        subscribe="test/lm/in~input",
        publish="document~lm/document",
        properties={
            "retries": 2,
            "initial_timeout": 1.0,
            "timeout_multiplier": 1.5,
            "backoff_factor": 0.01,
            "error_mode": "propagate",
        },
    )
    await comp.start()

    side_effects = [TimeoutError("timed out 1"), TimeoutError("timed out 2")]
    with _fake_ollama_with_behavior(side_effects) as client_calls:
        with pytest.raises(RuntimeError, match="Ollama call failed after 2 attempts"):
            await comp.handle_input("input", {"content": "Hi"})

    assert len(client_calls) == 2
    await comp.stop()


async def test_rendered_prompt_published_before_llm_call() -> None:
    bus = Bus()
    prompts, docs, skipped = [], [], []
    bus.subscribe("lm/rendered_prompt", lambda t, m: prompts.append(m))
    bus.subscribe("lm/document", lambda t, m: docs.append(m))
    bus.subscribe("lm/skipped", lambda t, m: skipped.append(m))

    comp = PersistentLMAgentOid(
        bus=bus,
        subscribe="test/lm/in~input",
        publish="document~lm/document;rendered_prompt~lm/rendered_prompt;skipped~lm/skipped",
        properties={"prompt_template": "Answer: {{input}}"},
    )
    await comp.start()

    with _fake_ollama_with_behavior([{"message": {"content": "42"}}]) as client_calls:
        await bus.publish("test/lm/in", {"content": "6x7"})

    assert prompts == [{"prompt": "Answer: 6x7", "model": "llama3.2", "dry_run": False}]
    assert skipped == []
    assert docs[0]["content"] == "42"
    assert len(client_calls) == 1
    await comp.stop()


async def test_dry_run_publishes_prompt_without_calling_llm() -> None:
    bus = Bus()
    prompts, rows, skipped = [], [], []
    bus.subscribe("lm/rendered_prompt", lambda t, m: prompts.append(m))
    bus.subscribe("lm/row", lambda t, m: rows.append(m))
    bus.subscribe("lm/skipped", lambda t, m: skipped.append(m))

    comp = PersistentLMAgentOid(
        bus=bus,
        subscribe="test/lm/row~row",
        publish="row~lm/row;rendered_prompt~lm/rendered_prompt;skipped~lm/skipped",
        properties={
            "prompt_template": "Name: {{row.name}}",
            "csv_field": "reply",
            "dry_run": True,
        },
    )
    await comp.start()

    with _fake_ollama_with_behavior([]) as client_calls:
        await bus.publish("test/lm/row", {"label": "people", "index": 3, "row": {"name": "Ana"}})

    assert prompts == [{
        "label": "people", "index": 3,
        "prompt": "Name: Ana", "model": "llama3.2", "dry_run": True,
    }]
    assert rows == []
    assert skipped == [{"label": "people", "index": 3, "row": {"name": "Ana"}}]
    assert client_calls == []
    await comp.stop()
