"""Tests for data:csv-source."""
import os
import tempfile

from noid.core.bus import Bus
from noid_collections.data.csv_source.csv_source import CsvSourceOid

CSV = "name,age,city\nAlice,30,SP\nBob,25,RJ\nCarol,35,BH"


async def test_load_publishes_all_rows() -> None:
    bus = Bus()
    tables = []
    bus.subscribe("data/csv/table", lambda t, m: tables.append(m))

    comp = CsvSourceOid(
        bus=bus,
        subscribe="test/load~load",
        properties={"content": CSV, "label": "people"},
    )
    await comp.start()
    await bus.publish("test/load", {})

    assert len(tables) == 1
    assert tables[0]["label"] == "people"
    assert tables[0]["columns"] == ["name", "age", "city"]
    assert len(tables[0]["rows"]) == 3
    assert tables[0]["rows"][0] == {"name": "Alice", "age": "30", "city": "SP"}
    await comp.stop()


async def test_first_publishes_schema_and_row() -> None:
    bus = Bus()
    schemas, rows = [], []
    bus.subscribe("data/csv/schema", lambda t, m: schemas.append(m))
    bus.subscribe("data/csv/row",    lambda t, m: rows.append(m))

    comp = CsvSourceOid(
        bus=bus,
        subscribe="test/first~first",
        properties={"content": CSV, "label": "people"},
    )
    await comp.start()
    await bus.publish("test/first", {})

    assert schemas == [{"label": "people", "columns": ["name", "age", "city"]}]
    assert len(rows) == 1
    assert rows[0] == {"label": "people", "index": 0, "row": {"name": "Alice", "age": "30", "city": "SP"}}
    await comp.stop()


async def test_next_iterates_rows() -> None:
    bus = Bus()
    rows, exhausted = [], []
    bus.subscribe("data/csv/row",       lambda t, m: rows.append(m))
    bus.subscribe("data/csv/exhausted", lambda t, m: exhausted.append(m))

    comp = CsvSourceOid(
        bus=bus,
        subscribe="test/first~first;test/next~next",
        properties={"content": CSV, "label": "people"},
    )
    await comp.start()

    await bus.publish("test/first", {})   # row 0
    await bus.publish("test/next",  {})   # row 1
    await bus.publish("test/next",  {})   # row 2
    await bus.publish("test/next",  {})   # exhausted

    assert len(rows) == 3
    assert rows[0]["index"] == 0
    assert rows[1]["index"] == 1
    assert rows[2]["index"] == 2
    assert len(exhausted) == 1
    await comp.stop()


async def test_empty_csv_exhausted_on_first() -> None:
    bus = Bus()
    exhausted = []
    bus.subscribe("data/csv/exhausted", lambda t, m: exhausted.append(m))

    comp = CsvSourceOid(
        bus=bus,
        subscribe="test/first~first",
        properties={"content": "name,age\n", "label": "empty"},
    )
    await comp.start()
    await bus.publish("test/first", {})

    assert len(exhausted) == 1
    await comp.stop()


async def test_load_from_file() -> None:
    bus = Bus()
    tables = []
    bus.subscribe("data/csv/table", lambda t, m: tables.append(m))

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(CSV)
        path = f.name

    try:
        comp = CsvSourceOid(
            bus=bus,
            subscribe="test/load~load",
            properties={"file": path, "label": "people"},
        )
        await comp.start()
        await bus.publish("test/load", {})

        assert len(tables) == 1
        assert tables[0]["columns"] == ["name", "age", "city"]
        assert len(tables[0]["rows"]) == 3
        await comp.stop()
    finally:
        os.unlink(path)


async def test_file_takes_precedence_over_content() -> None:
    bus = Bus()
    tables = []
    bus.subscribe("data/csv/table", lambda t, m: tables.append(m))

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write("x,y\n1,2")
        path = f.name

    try:
        comp = CsvSourceOid(
            bus=bus,
            subscribe="test/load~load",
            properties={"content": CSV, "file": path, "label": "src"},
        )
        await comp.start()
        await bus.publish("test/load", {})

        assert tables[0]["columns"] == ["x", "y"]
        assert len(tables[0]["rows"]) == 1
        await comp.stop()
    finally:
        os.unlink(path)
