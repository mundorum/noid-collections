"""Tests for basic:console-display."""
import json

import pytest

from noid.core.bus import Bus
from noid_collections.basic.console_display.console_display import ConsoleDisplayOid


async def test_console_display_prints_dict(capsys) -> None:
    bus = Bus()
    comp = ConsoleDisplayOid(
        bus=bus,
        subscribe="test/show~show",
        properties={"label": "Out"},
    )
    await comp.start()
    await bus.publish("test/show", {"content": "hello"})

    captured = capsys.readouterr()
    assert "[Out]" in captured.out
    assert "hello" in captured.out
    await comp.stop()


async def test_console_display_no_label(capsys) -> None:
    bus = Bus()
    comp = ConsoleDisplayOid(bus=bus, subscribe="test/raw~show")
    await comp.start()
    await bus.publish("test/raw", {"x": 1})

    captured = capsys.readouterr()
    assert captured.out.strip().startswith("{")
    await comp.stop()


async def test_console_display_plain_string(capsys) -> None:
    bus = Bus()
    comp = ConsoleDisplayOid(
        bus=bus,
        subscribe="test/str~show",
        properties={"pretty": False},
    )
    await comp.start()
    await bus.publish("test/str", "plain text")

    captured = capsys.readouterr()
    assert "plain text" in captured.out
    await comp.stop()
