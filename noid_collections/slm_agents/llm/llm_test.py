"""Tests for slm:llm-agent — mocks the ollama client to avoid needing a running server."""
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from noid.core.bus import Bus
from noid_collections.slm_agents.llm.llm import LLMAgentOid


async def test_llm_agent_publishes_output() -> None:
    bus = Bus()
    received = []
    bus.subscribe("slm/llm/output", lambda t, m: received.append(m))

    comp = LLMAgentOid(bus=bus)
    await comp.start()

    fake_response = {"message": {"content": "The answer is 42."}}
    fake_client = MagicMock()
    fake_client.chat.return_value = fake_response

    with patch("ollama.Client", return_value=fake_client):
        await bus.publish("slm/llm/output", {"content": "What is the answer?"})

    # Trigger via the raw handler (subscribe wired separately in test)
    comp2 = LLMAgentOid(
        bus=bus,
        subscribe="test/llm/in~input",
    )
    await comp2.start()

    with patch("ollama.Client", return_value=fake_client):
        await bus.publish("test/llm/in", {"content": "What is the answer?"})

    assert len(received) >= 1
    assert received[-1]["content"] == "The answer is 42."
    assert received[-1]["model"] == "llama3.2"

    await comp.stop()
    await comp2.stop()


async def test_llm_agent_model_configurable() -> None:
    bus = Bus()
    comp = LLMAgentOid(bus=bus, properties={"model": "mistral"})
    await comp.start()
    assert comp.model == "mistral"
    await comp.stop()


async def test_llm_render_template() -> None:
    rendered = LLMAgentOid._render_template(
        "Q: {question} Context: {input}", "some text", "What year?", {}
    )
    assert rendered == "Q: What year? Context: some text"


async def test_ollama_missing_raises_runtime_error() -> None:
    bus = Bus()
    comp = LLMAgentOid(bus=bus, subscribe="test/missing~input")
    await comp.start()

    with patch.dict(sys.modules, {"ollama": None}):
        with pytest.raises(RuntimeError, match="ollama package"):
            await comp.handle_input("input", {"content": "hi"})

    await comp.stop()
