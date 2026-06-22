"""Tests for slm:text-source."""
import asyncio

from noid.core.bus import Bus
from noid_collections.slm_agents.text_source.text_source import TextSourceOid


async def test_text_source_publishes_on_trigger() -> None:
    bus = Bus()
    received = []
    bus.subscribe("slm/text/output", lambda t, m: received.append(m))

    comp = TextSourceOid(
        bus=bus,
        subscribe="test/trigger~trigger",
        properties={"text": "Hello world", "label": "intro"},
    )
    await comp.start()
    await bus.publish("test/trigger", {})

    assert received == [{"label": "intro", "content": "Hello world"}]
    await comp.stop()


async def test_text_source_auto_publish() -> None:
    bus = Bus()
    received = []
    bus.subscribe("slm/text/output", lambda t, m: received.append(m))

    comp = TextSourceOid(
        bus=bus,
        properties={"text": "Auto text", "label": "auto", "auto_publish": True},
    )
    await comp.start()
    # auto_publish fires via create_task — yield once to let the task run
    await asyncio.sleep(0)

    assert received == [{"label": "auto", "content": "Auto text"}]
    await comp.stop()


async def test_text_source_multiple_triggers() -> None:
    bus = Bus()
    received = []
    bus.subscribe("slm/text/output", lambda t, m: received.append(m))

    comp = TextSourceOid(
        bus=bus,
        subscribe="test/t~trigger",
        properties={"text": "Repeat", "label": "r"},
    )
    await comp.start()
    await bus.publish("test/t", {})
    await bus.publish("test/t", {})

    assert len(received) == 2
    await comp.stop()
