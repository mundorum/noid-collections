"""Tests for lm:ner — mocks the transformers pipeline to avoid downloading models."""
import json
import sys
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


async def test_ner_publishes_document() -> None:
    bus = Bus()
    results = []
    bus.subscribe("ner/document", lambda t, m: results.append(m))

    comp = NERAgentOid(bus=bus, subscribe="test/text~text", publish="document~ner/document")
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
    bus.subscribe("ner/document", lambda t, m: results.append(m))

    comp = NERAgentOid(bus=bus, subscribe="test/plain~text", publish="document~ner/document")
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


async def test_ner_csv_field_document_mode_serializes_json() -> None:
    bus = Bus()
    results = []
    bus.subscribe("ner/document", lambda t, m: results.append(m))

    comp = NERAgentOid(
        bus=bus,
        subscribe="test/text~text",
        publish="document~ner/document",
        properties={"csv_field": "entities_json"},
    )
    await comp.start()

    fake_pipeline = MagicMock(side_effect=_fake_pipeline_output)
    ner_module._pipeline_cache.clear()
    with patch("transformers.pipeline", return_value=fake_pipeline):
        await bus.publish("test/text", {"index": 1, "content": "Alice lives in London."})

    assert len(results) == 1
    out = results[0]
    assert out["index"] == 1
    assert out["content"] == "Alice lives in London."
    entities = json.loads(out["entities_json"])
    assert len(entities) == 2
    assert entities[0]["entity_type"] == "PER"

    await comp.stop()


async def test_ner_schema_adds_csv_field_column() -> None:
    bus = Bus()
    received = []
    bus.subscribe("ner/schema", lambda t, m: received.append(m))

    comp = NERAgentOid(
        bus=bus,
        subscribe="test/ner/schema~schema",
        publish="schema~ner/schema",
        properties={"csv_field": "entities_json"},
    )
    await comp.start()

    await bus.publish("test/ner/schema", {"label": "notes", "columns": ["content"]})

    assert received == [{"label": "notes", "columns": ["content", "entities_json"]}]

    await comp.stop()


async def test_ner_schema_ignored_without_csv_field() -> None:
    bus = Bus()
    received = []
    bus.subscribe("ner/schema", lambda t, m: received.append(m))

    comp = NERAgentOid(bus=bus, subscribe="test/ner/schema~schema", publish="schema~ner/schema")
    await comp.start()

    await bus.publish("test/ner/schema", {"columns": ["content"]})

    assert received == []

    await comp.stop()


async def test_ner_row_adds_entities_below_row() -> None:
    bus = Bus()
    received = []
    bus.subscribe("ner/row", lambda t, m: received.append(m))

    comp = NERAgentOid(
        bus=bus,
        subscribe="test/ner/row~row",
        publish="row~ner/row",
        properties={"csv_field": "entities_json"},
    )
    await comp.start()

    fake_pipeline = MagicMock(side_effect=_fake_pipeline_output)
    ner_module._pipeline_cache.clear()
    row_msg = {
        "label": "notes",
        "index": 1,
        "row": {"content": "Alice lives in London."},
    }
    with patch("transformers.pipeline", return_value=fake_pipeline):
        await bus.publish("test/ner/row", row_msg)

    assert len(received) == 1
    out = received[0]
    assert out["label"] == "notes"
    assert out["index"] == 1
    assert out["row"]["content"] == "Alice lives in London."
    entities = json.loads(out["row"]["entities_json"])
    assert len(entities) == 2

    await comp.stop()


async def test_ner_row_uses_text_field_property() -> None:
    bus = Bus()
    received = []
    bus.subscribe("ner/row", lambda t, m: received.append(m))

    comp = NERAgentOid(
        bus=bus,
        subscribe="test/ner/row~row",
        publish="row~ner/row",
        properties={"csv_field": "entities_json", "text_field": "note"},
    )
    await comp.start()

    fake_pipeline = MagicMock(side_effect=_fake_pipeline_output)
    ner_module._pipeline_cache.clear()
    row_msg = {"index": 1, "row": {"note": "Alice lives in London."}}
    with patch("transformers.pipeline", return_value=fake_pipeline):
        await bus.publish("test/ner/row", row_msg)

    entities = json.loads(received[0]["row"]["entities_json"])
    assert len(entities) == 2

    await comp.stop()


async def test_ner_row_ignored_without_csv_field() -> None:
    bus = Bus()
    received = []
    bus.subscribe("ner/row", lambda t, m: received.append(m))

    comp = NERAgentOid(bus=bus, subscribe="test/ner/row~row", publish="row~ner/row")
    await comp.start()

    await bus.publish("test/ner/row", {"index": 1, "row": {"content": "Alice lives in London."}})

    assert received == []

    await comp.stop()
