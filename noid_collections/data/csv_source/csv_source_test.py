"""Tests for data:csv-source."""
import os
import tempfile

from noid.core.bus import Bus
from noid_collections.data.csv_source.csv_source import CsvSourceOid

CSV = "name,age,city\nAlice,30,SP\nBob,25,RJ\nCarol,35,BH"


async def test_load_publishes_all_rows() -> None:
    bus = Bus()
    tables = []
    bus.subscribe("csv/table", lambda t, m: tables.append(m))

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


async def test_load_compact_format() -> None:
    bus = Bus()
    tables = []
    bus.subscribe("csv/table", lambda t, m: tables.append(m))

    comp = CsvSourceOid(
        bus=bus,
        subscribe="test/load~load",
        properties={"content": CSV, "label": "people", "format": "list"},
    )
    await comp.start()
    await bus.publish("test/load", {})

    assert len(tables) == 1
    assert tables[0]["columns"] == ["name", "age", "city"]
    assert tables[0]["rows"] == [
        ["Alice", "30", "SP"],
        ["Bob",   "25", "RJ"],
        ["Carol", "35", "BH"],
    ]
    await comp.stop()


async def test_first_publishes_schema_and_row() -> None:
    bus = Bus()
    schemas, rows = [], []
    bus.subscribe("csv/schema", lambda t, m: schemas.append(m))
    bus.subscribe("csv/row",    lambda t, m: rows.append(m))

    comp = CsvSourceOid(
        bus=bus,
        subscribe="test/first~first",
        properties={"content": CSV, "label": "people"},
    )
    await comp.start()
    await bus.publish("test/first", {})

    assert schemas == [{"label": "people", "columns": ["name", "age", "city"]}]
    assert len(rows) == 1
    assert rows[0] == {
        "label": "people", "index": 1,
        "row": {"name": "Alice", "age": "30", "city": "SP"},
    }
    await comp.stop()


async def test_first_non_eager_publishes_schema_only() -> None:
    bus = Bus()
    schemas, rows = [], []
    bus.subscribe("csv/schema", lambda t, m: schemas.append(m))
    bus.subscribe("csv/row",    lambda t, m: rows.append(m))

    comp = CsvSourceOid(
        bus=bus,
        subscribe="test/first~first;test/next~next",
        properties={"content": CSV, "label": "people", "eager_first_row": False},
    )
    await comp.start()
    await bus.publish("test/first", {})

    assert schemas == [{"label": "people", "columns": ["name", "age", "city"]}]
    assert rows == []

    await bus.publish("test/next", {})
    assert len(rows) == 1
    assert rows[0] == {
        "label": "people", "index": 1,
        "row": {"name": "Alice", "age": "30", "city": "SP"},
    }
    await comp.stop()


async def test_next_iterates_rows() -> None:
    bus = Bus()
    rows, exhausted = [], []
    bus.subscribe("csv/row",       lambda t, m: rows.append(m))
    bus.subscribe("csv/exhausted", lambda t, m: exhausted.append(m))

    comp = CsvSourceOid(
        bus=bus,
        subscribe="test/first~first;test/next~next",
        properties={"content": CSV, "label": "people"},
    )
    await comp.start()

    await bus.publish("test/first", {})   # row 1
    await bus.publish("test/next",  {})   # row 2
    await bus.publish("test/next",  {})   # row 3
    await bus.publish("test/next",  {})   # exhausted

    assert len(rows) == 3
    assert rows[0]["index"] == 1
    assert rows[1]["index"] == 2
    assert rows[2]["index"] == 3
    assert len(exhausted) == 1
    await comp.stop()


async def test_empty_csv_exhausted_on_first() -> None:
    bus = Bus()
    exhausted = []
    bus.subscribe("csv/exhausted", lambda t, m: exhausted.append(m))

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
    bus.subscribe("csv/table", lambda t, m: tables.append(m))

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(CSV)
        path = f.name

    try:
        comp = CsvSourceOid(
            bus=bus,
            subscribe="test/load~load",
            properties={"input_file": path, "label": "people"},
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
    bus.subscribe("csv/table", lambda t, m: tables.append(m))

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write("x,y\n1,2")
        path = f.name

    try:
        comp = CsvSourceOid(
            bus=bus,
            subscribe="test/load~load",
            properties={"content": CSV, "input_file": path, "label": "src"},
        )
        await comp.start()
        await bus.publish("test/load", {})

        assert tables[0]["columns"] == ["x", "y"]
        assert len(tables[0]["rows"]) == 1
        await comp.stop()
    finally:
        os.unlink(path)


async def test_sample_size_limits_load() -> None:
    bus = Bus()
    tables = []
    bus.subscribe("csv/table", lambda t, m: tables.append(m))

    comp = CsvSourceOid(
        bus=bus,
        subscribe="test/load~load",
        properties={"content": CSV, "label": "people", "sample_size": 2},
    )
    await comp.start()
    await bus.publish("test/load", {})

    assert len(tables[0]["rows"]) == 2
    assert tables[0]["rows"][0]["name"] == "Alice"
    assert tables[0]["rows"][1]["name"] == "Bob"
    await comp.stop()


async def test_sample_size_limits_row_by_row() -> None:
    bus = Bus()
    rows, exhausted = [], []
    bus.subscribe("csv/row",       lambda t, m: rows.append(m))
    bus.subscribe("csv/exhausted", lambda t, m: exhausted.append(m))

    comp = CsvSourceOid(
        bus=bus,
        subscribe="test/first~first;test/next~next",
        properties={"content": CSV, "label": "people", "sample_size": 2},
    )
    await comp.start()

    await bus.publish("test/first", {})  # row 1
    await bus.publish("test/next",  {})  # row 2
    await bus.publish("test/next",  {})  # exhausted (row 3 is beyond sample)

    assert len(rows) == 2
    assert rows[0]["row"]["name"] == "Alice"
    assert rows[1]["row"]["name"] == "Bob"
    assert len(exhausted) == 1
    await comp.stop()


async def test_sample_size_zero_means_no_limit() -> None:
    bus = Bus()
    tables = []
    bus.subscribe("csv/table", lambda t, m: tables.append(m))

    comp = CsvSourceOid(
        bus=bus,
        subscribe="test/load~load",
        properties={"content": CSV, "label": "people", "sample_size": 0},
    )
    await comp.start()
    await bus.publish("test/load", {})

    assert len(tables[0]["rows"]) == 3
    await comp.stop()


async def test_custom_delimiter() -> None:
    bus = Bus()
    tables = []
    bus.subscribe("csv/table", lambda t, m: tables.append(m))

    tsv = "name\tage\tcity\nAlice\t30\tSP\nBob\t25\tRJ"
    comp = CsvSourceOid(
        bus=bus,
        subscribe="test/load~load",
        properties={"content": tsv, "label": "people", "delimiter": "\t"},
    )
    await comp.start()
    await bus.publish("test/load", {})

    assert tables[0]["columns"] == ["name", "age", "city"]
    assert tables[0]["rows"][0] == {"name": "Alice", "age": "30", "city": "SP"}
    await comp.stop()


async def test_compact_row_by_row() -> None:
    bus = Bus()
    schemas, rows, exhausted = [], [], []
    bus.subscribe("csv/schema",    lambda t, m: schemas.append(m))
    bus.subscribe("csv/row",       lambda t, m: rows.append(m))
    bus.subscribe("csv/exhausted", lambda t, m: exhausted.append(m))

    comp = CsvSourceOid(
        bus=bus,
        subscribe="test/first~first;test/next~next",
        properties={"content": CSV, "label": "people", "format": "list"},
    )
    await comp.start()

    await bus.publish("test/first", {})
    await bus.publish("test/next",  {})
    await bus.publish("test/next",  {})
    await bus.publish("test/next",  {})

    assert schemas == [{"label": "people", "columns": ["name", "age", "city"]}]
    assert len(rows) == 3
    assert rows[0] == {"label": "people", "index": 1, "row": ["Alice", "30", "SP"]}
    assert rows[1] == {"label": "people", "index": 2, "row": ["Bob",   "25", "RJ"]}
    assert rows[2] == {"label": "people", "index": 3, "row": ["Carol", "35", "BH"]}
    assert len(exhausted) == 1
    await comp.stop()
