"""Tests for lm:ner — mocks the transformers pipeline to avoid downloading models."""
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from noid.core.bus import Bus
import noid_collections.lm_agents.ner.ner as ner_module
from noid_collections.lm_agents.ner.ner import NERAgentOid


def _fake_pipeline_output(text: str):
    return [
        {"word": "Alice", "entity_group": "PER", "start": 0, "end": 5, "score": 0.99},
        {"word": "London", "entity_group": "LOC", "start": 10, "end": 16, "score": 0.98},
    ]


async def test_ner_publishes_entities() -> None:
    bus = Bus()
    results = []
    bus.subscribe("slm/ner/output", lambda t, m: results.append(m))

    comp = NERAgentOid(bus=bus, subscribe="test/text~text")
    await comp.start()

    fake_pipeline = MagicMock(side_effect=_fake_pipeline_output)

    ner_module._pipeline_cache.clear()
    with patch("transformers.pipeline", return_value=fake_pipeline):
        await bus.publish("test/text", {"content": "Alice lives in London."})

    assert len(results) == 1
    assert results[0]["text"] == "Alice lives in London."
    entities = results[0]["entities"]
    assert len(entities) == 2
    assert entities[0]["entity_type"] == "PER"
    assert entities[1]["entity_type"] == "LOC"

    await comp.stop()


async def test_ner_model_configurable() -> None:
    bus = Bus()
    comp = NERAgentOid(bus=bus, properties={"model": "samrawal/bert-base-uncased_clinical-ner"})
    await comp.start()
    assert comp.model == "samrawal/bert-base-uncased_clinical-ner"
    await comp.stop()


async def test_ner_plain_string_message() -> None:
    bus = Bus()
    results = []
    bus.subscribe("slm/ner/output", lambda t, m: results.append(m))

    comp = NERAgentOid(bus=bus, subscribe="test/plain~text")
    await comp.start()

    fake_pipeline = MagicMock(return_value=[
        {"word": "Bob", "entity_group": "PER", "start": 0, "end": 3, "score": 0.95}
    ])

    ner_module._pipeline_cache.clear()
    with patch("transformers.pipeline", return_value=fake_pipeline):
        await bus.publish("test/plain", "Bob went to Paris.")

    assert results[0]["text"] == "Bob went to Paris."
    await comp.stop()


async def test_ner_missing_transformers_raises() -> None:
    bus = Bus()
    comp = NERAgentOid(bus=bus, subscribe="test/err~text")
    await comp.start()

    ner_module._pipeline_cache.clear()
    with patch.dict(sys.modules, {"transformers": None}):
        with pytest.raises(RuntimeError, match="transformers package"):
            await comp.handle_text("text", {"content": "test"})

    await comp.stop()
