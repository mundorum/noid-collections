"""Tests for data:csv-writer."""
import csv
import os
import tempfile

from noid.core.bus import Bus
from noid_collections.data.csv_writer.csv_writer import CsvWriterOid


def _read_csv(path: str) -> tuple[list, list]:
    """Return (columns, rows) from a CSV file."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        columns = list(reader.fieldnames or [])
        rows = [dict(r) for r in reader]
    return columns, rows


def _tmp_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    os.unlink(path)
    return path


async def test_complete_table_dict_format() -> None:
    bus = Bus()
    done = []
    bus.subscribe("csv/done", lambda t, m: done.append(m))

    path = _tmp_path()
    try:
        comp = CsvWriterOid(
            bus=bus,
            subscribe="test/table~table;test/done~done",
            properties={"output_file": path},
        )
        await comp.start()

        await bus.publish("test/table", {
            "columns": ["name", "age"],
            "rows":    [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}],
        })
        await bus.publish("test/done", {})

        assert done == [{"file": path}]
        columns, rows = _read_csv(path)
        assert columns == ["name", "age"]
        assert rows == [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}]
        assert not os.path.exists(f"{path}.tmp")
        await comp.stop()
    finally:
        if os.path.exists(path):
            os.unlink(path)


async def test_complete_table_list_format() -> None:
    bus = Bus()
    path = _tmp_path()
    try:
        comp = CsvWriterOid(
            bus=bus,
            subscribe="test/table~table;test/done~done",
            properties={"output_file": path, "format": "list"},
        )
        await comp.start()

        await bus.publish("test/table", {
            "columns": ["name", "age"],
            "rows":    [["Alice", "30"], ["Bob", "25"]],
        })
        await bus.publish("test/done", {})

        columns, rows = _read_csv(path)
        assert columns == ["name", "age"]
        assert rows == [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}]
        await comp.stop()
    finally:
        if os.path.exists(path):
            os.unlink(path)


async def test_row_by_row_dict_format() -> None:
    bus = Bus()
    done = []
    bus.subscribe("csv/done", lambda t, m: done.append(m))

    path = _tmp_path()
    try:
        comp = CsvWriterOid(
            bus=bus,
            subscribe="test/schema~schema;test/row~row;test/done~done",
            properties={"output_file": path},
        )
        await comp.start()

        await bus.publish("test/schema", {"columns": ["x", "y"]})
        await bus.publish("test/row",    {"row": {"x": "1", "y": "2"}})
        await bus.publish("test/row",    {"row": {"x": "3", "y": "4"}})
        await bus.publish("test/done",   {})

        assert done == [{"file": path}]
        columns, rows = _read_csv(path)
        assert columns == ["x", "y"]
        assert rows == [{"x": "1", "y": "2"}, {"x": "3", "y": "4"}]
        await comp.stop()
    finally:
        if os.path.exists(path):
            os.unlink(path)


async def test_row_by_row_list_format() -> None:
    bus = Bus()
    path = _tmp_path()
    try:
        comp = CsvWriterOid(
            bus=bus,
            subscribe="test/schema~schema;test/row~row;test/done~done",
            properties={"output_file": path, "format": "list"},
        )
        await comp.start()

        await bus.publish("test/schema", {"columns": ["x", "y"]})
        await bus.publish("test/row",    {"row": ["1", "2"]})
        await bus.publish("test/row",    {"row": ["3", "4"]})
        await bus.publish("test/done",   {})

        columns, rows = _read_csv(path)
        assert columns == ["x", "y"]
        assert rows == [{"x": "1", "y": "2"}, {"x": "3", "y": "4"}]
        await comp.stop()
    finally:
        if os.path.exists(path):
            os.unlink(path)


async def test_schema_resets_row_buffer() -> None:
    bus = Bus()
    path = _tmp_path()
    try:
        comp = CsvWriterOid(
            bus=bus,
            subscribe="test/schema~schema;test/row~row;test/done~done",
            properties={"output_file": path},
        )
        await comp.start()

        await bus.publish("test/schema", {"columns": ["a"]})
        await bus.publish("test/row",    {"row": {"a": "old"}})
        # schema again resets
        await bus.publish("test/schema", {"columns": ["x", "y"]})
        await bus.publish("test/row",    {"row": {"x": "1", "y": "2"}})
        await bus.publish("test/done",   {})

        columns, rows = _read_csv(path)
        assert columns == ["x", "y"]
        assert rows == [{"x": "1", "y": "2"}]
        await comp.stop()
    finally:
        if os.path.exists(path):
            os.unlink(path)


async def test_done_without_data_publishes_done() -> None:
    bus = Bus()
    written = []
    done = []
    bus.subscribe("csv/written", lambda t, m: written.append(m))
    bus.subscribe("csv/done", lambda t, m: done.append(m))

    path = _tmp_path()
    comp = CsvWriterOid(
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


async def test_table_replaces_previous_buffer() -> None:
    bus = Bus()
    path = _tmp_path()
    try:
        comp = CsvWriterOid(
            bus=bus,
            subscribe="test/table~table;test/done~done",
            properties={"output_file": path},
        )
        await comp.start()

        await bus.publish("test/table", {
            "columns": ["a"], "rows": [{"a": "old"}],
        })
        await bus.publish("test/table", {
            "columns": ["x", "y"], "rows": [{"x": "1", "y": "2"}],
        })
        await bus.publish("test/done", {})

        columns, rows = _read_csv(path)
        assert columns == ["x", "y"]
        assert rows == [{"x": "1", "y": "2"}]
        await comp.stop()
    finally:
        if os.path.exists(path):
            os.unlink(path)


async def test_label_and_index_in_row_payload_ignored() -> None:
    bus = Bus()
    path = _tmp_path()
    try:
        comp = CsvWriterOid(
            bus=bus,
            subscribe="test/schema~schema;test/row~row;test/done~done",
            properties={"output_file": path},
        )
        await comp.start()

        await bus.publish("test/schema", {"label": "people", "columns": ["name"]})
        await bus.publish("test/row",    {"label": "people", "index": 1, "row": {"name": "Alice"}})
        await bus.publish("test/done",   {})

        columns, rows = _read_csv(path)
        assert columns == ["name"]
        assert rows == [{"name": "Alice"}]
        await comp.stop()
    finally:
        if os.path.exists(path):
            os.unlink(path)


async def test_written_fires_once_per_schema_and_row() -> None:
    bus = Bus()
    written = []
    bus.subscribe("csv/written", lambda t, m: written.append(m))

    path = _tmp_path()
    try:
        comp = CsvWriterOid(
            bus=bus,
            subscribe="test/schema~schema;test/row~row;test/done~done",
            properties={"output_file": path},
        )
        await comp.start()

        await bus.publish("test/schema", {"columns": ["x"]})
        await bus.publish("test/row",    {"row": {"x": "1"}})
        await bus.publish("test/row",    {"row": {"x": "2"}})
        assert written == [{}, {}, {}]  # schema + 2 rows, one per physical write
        await bus.publish("test/done", {})
        await comp.stop()
    finally:
        if os.path.exists(path):
            os.unlink(path)


async def test_custom_delimiter() -> None:
    bus = Bus()
    path = _tmp_path()
    try:
        comp = CsvWriterOid(
            bus=bus,
            subscribe="test/table~table;test/done~done",
            properties={"output_file": path, "delimiter": "\t"},
        )
        await comp.start()

        await bus.publish("test/table", {
            "columns": ["name", "age"],
            "rows":    [{"name": "Alice", "age": "30"}],
        })
        await bus.publish("test/done", {})

        with open(path, newline="", encoding="utf-8") as f:
            content = f.read()
        assert content == "name\tage\r\nAlice\t30\r\n"
        await comp.stop()
    finally:
        if os.path.exists(path):
            os.unlink(path)


async def test_pre_existing_output_file_is_overwritten() -> None:
    bus = Bus()
    path = _tmp_path()
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([["old"], ["stale"]])

        comp = CsvWriterOid(
            bus=bus,
            subscribe="test/schema~schema;test/row~row;test/done~done",
            properties={"output_file": path},
        )
        await comp.start()

        await bus.publish("test/schema", {"columns": ["name"]})
        await bus.publish("test/row",    {"row": {"name": "Bob"}})
        await bus.publish("test/done",   {})

        columns, rows = _read_csv(path)
        assert columns == ["name"]
        assert rows == [{"name": "Bob"}]
        await comp.stop()
    finally:
        if os.path.exists(path):
            os.unlink(path)
