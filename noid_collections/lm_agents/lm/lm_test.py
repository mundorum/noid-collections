"""Tests for lm:persistent-agent — mocks the ollama client to verify retries, timeouts, and fallbacks."""
import sys
import types
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from noid.core.bus import Bus
from noid_collections.lm_agents.lm.lm import LMAgentOid


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
