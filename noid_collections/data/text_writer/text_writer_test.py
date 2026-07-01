"""Tests for data:text-writer."""
import os
import tempfile

from noid.core.bus import Bus
from noid_collections.data.text_writer.text_writer import TextWriterOid


def _tmp_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    os.unlink(path)
    return path


async def test_complete_document() -> None:
    bus = Bus()
    done = []
    bus.subscribe("file/done", lambda t, m: done.append(m))

    path = _tmp_path()
    try:
        comp = TextWriterOid(
            bus=bus,
            subscribe="test/document~document;test/done~done",
            properties={"output_file": path},
        )
        await comp.start()

        await bus.publish("test/document", {"content": "hello world"})
        await bus.publish("test/done", {})

        assert done == [{"file": path}]
        with open(path, encoding="utf-8") as f:
            assert f.read() == "hello world"
        assert not os.path.exists(f"{path}.tmp")
        await comp.stop()
    finally:
        if os.path.exists(path):
            os.unlink(path)


async def test_segment_by_segment() -> None:
    bus = Bus()
    path = _tmp_path()
    try:
        comp = TextWriterOid(
            bus=bus,
            subscribe="test/segment~segment;test/done~done",
            properties={"output_file": path},
        )
        await comp.start()

        await bus.publish("test/segment", {"content": "page one"})
        await bus.publish("test/segment", {"content": "page two"})
        await bus.publish("test/done", {})

        with open(path, encoding="utf-8") as f:
            assert f.read() == "page one\n\npage two"
        await comp.stop()
    finally:
        if os.path.exists(path):
            os.unlink(path)


async def test_custom_segment_separator() -> None:
    bus = Bus()
    path = _tmp_path()
    try:
        comp = TextWriterOid(
            bus=bus,
            subscribe="test/segment~segment;test/done~done",
            properties={"output_file": path, "segment_separator": " | "},
        )
        await comp.start()

        await bus.publish("test/segment", {"content": "a"})
        await bus.publish("test/segment", {"content": "b"})
        await bus.publish("test/done", {})

        with open(path, encoding="utf-8") as f:
            assert f.read() == "a | b"
        await comp.stop()
    finally:
        if os.path.exists(path):
            os.unlink(path)


async def test_document_resets_previous_content() -> None:
    bus = Bus()
    path = _tmp_path()
    try:
        comp = TextWriterOid(
            bus=bus,
            subscribe="test/document~document;test/done~done",
            properties={"output_file": path},
        )
        await comp.start()

        await bus.publish("test/document", {"content": "first"})
        await bus.publish("test/document", {"content": "second"})
        await bus.publish("test/done", {})

        with open(path, encoding="utf-8") as f:
            assert f.read() == "second"
        await comp.stop()
    finally:
        if os.path.exists(path):
            os.unlink(path)


async def test_done_without_data_publishes_done() -> None:
    bus = Bus()
    written = []
    done = []
    bus.subscribe("file/written", lambda t, m: written.append(m))
    bus.subscribe("file/done", lambda t, m: done.append(m))

    path = _tmp_path()
    comp = TextWriterOid(
        bus=bus,
        subscribe="test/done~done",
        properties={"output_file": path},
    )
    await comp.start()
    await bus.publish("test/done", {})

    assert written == []
    assert done == [{"file": path}]
    assert not os.path.exists(path)
    await comp.stop()


async def test_written_fires_once_per_segment() -> None:
    bus = Bus()
    written = []
    bus.subscribe("file/written", lambda t, m: written.append(m))

    path = _tmp_path()
    try:
        comp = TextWriterOid(
            bus=bus,
            subscribe="test/segment~segment;test/done~done",
            properties={"output_file": path},
        )
        await comp.start()

        await bus.publish("test/segment", {"content": "a"})
        await bus.publish("test/segment", {"content": "b"})
        assert written == [{}, {}]
        await bus.publish("test/done", {})
        await comp.stop()
    finally:
        if os.path.exists(path):
            os.unlink(path)


async def test_pre_existing_output_file_is_overwritten() -> None:
    bus = Bus()
    path = _tmp_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("stale content")

        comp = TextWriterOid(
            bus=bus,
            subscribe="test/document~document;test/done~done",
            properties={"output_file": path},
        )
        await comp.start()

        await bus.publish("test/document", {"content": "fresh"})
        await bus.publish("test/done", {})

        with open(path, encoding="utf-8") as f:
            assert f.read() == "fresh"
        await comp.stop()
    finally:
        if os.path.exists(path):
            os.unlink(path)
