"""Tests for data:text-source."""
import os
import tempfile

from noid.core.bus import Bus
from noid_collections.data.text_source.text_source import TextSourceOid


async def test_text_source_publishes_on_load() -> None:
    bus = Bus()
    received = []
    bus.subscribe("data/text/output", lambda t, m: received.append(m))

    comp = TextSourceOid(
        bus=bus,
        subscribe="test/load~load",
        properties={"content": "Hello world", "label": "intro"},
    )
    await comp.start()
    await bus.publish("test/load", {})

    assert received == [{"label": "intro", "content": "Hello world"}]
    await comp.stop()


async def test_text_source_multiple_loads() -> None:
    bus = Bus()
    received = []
    bus.subscribe("data/text/output", lambda t, m: received.append(m))

    comp = TextSourceOid(
        bus=bus,
        subscribe="test/t~load",
        properties={"content": "Repeat", "label": "r"},
    )
    await comp.start()
    await bus.publish("test/t", {})
    await bus.publish("test/t", {})

    assert len(received) == 2
    await comp.stop()


async def test_text_source_loads_from_file() -> None:
    bus = Bus()
    received = []
    bus.subscribe("data/text/output", lambda t, m: received.append(m))

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("Content from file.")
        path = f.name

    try:
        comp = TextSourceOid(
            bus=bus,
            subscribe="test/load~load",
            properties={"input_file": path, "label": "file-src"},
        )
        await comp.start()
        await bus.publish("test/load", {})

        assert received == [{"label": "file-src", "content": "Content from file."}]
        await comp.stop()
    finally:
        os.unlink(path)


async def test_text_source_input_file_takes_precedence_over_content() -> None:
    bus = Bus()
    received = []
    bus.subscribe("data/text/output", lambda t, m: received.append(m))

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("From file.")
        path = f.name

    try:
        comp = TextSourceOid(
            bus=bus,
            subscribe="test/load~load",
            properties={"content": "Inline text.", "input_file": path, "label": "src"},
        )
        await comp.start()
        await bus.publish("test/load", {})

        assert received == [{"label": "src", "content": "From file."}]
        await comp.stop()
    finally:
        os.unlink(path)
