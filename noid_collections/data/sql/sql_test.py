"""Tests for slm:sql — uses SQLite in-memory so no external dependency needed."""
import pytest

from noid.core.bus import Bus
from noid_collections.data.sql.sql import SqlAgentOid


async def test_sql_select_returns_rows() -> None:
    bus = Bus()
    results = []
    bus.subscribe("slm/sql/result", lambda t, m: results.append(m))

    comp = SqlAgentOid(
        bus=bus,
        subscribe="test/sql~query",
        properties={"driver": "sqlite", "connection": ":memory:"},
    )
    await comp.start()

    await bus.publish("test/sql", {
        "sql": "CREATE TABLE t (id INTEGER, name TEXT)"
    })
    await bus.publish("test/sql", {
        "sql": "INSERT INTO t VALUES (1, 'Alice'), (2, 'Bob')"
    })
    await bus.publish("test/sql", {"sql": "SELECT * FROM t ORDER BY id"})

    select_results = [r for r in results if r.get("row_count", 0) > 0]
    assert len(select_results) == 1
    assert select_results[0]["columns"] == ["id", "name"]
    assert select_results[0]["rows"] == [[1, "Alice"], [2, "Bob"]]
    assert select_results[0]["row_count"] == 2
    await comp.stop()


async def test_sql_publishes_error_on_bad_query() -> None:
    bus = Bus()
    errors = []
    bus.subscribe("slm/sql/error", lambda t, m: errors.append(m))

    comp = SqlAgentOid(
        bus=bus,
        subscribe="test/sql~query",
        properties={"driver": "sqlite", "connection": ":memory:"},
    )
    await comp.start()
    await bus.publish("test/sql", {"sql": "SELECT * FROM nonexistent_table"})

    assert len(errors) == 1
    assert "nonexistent_table" in errors[0]["message"]
    await comp.stop()


async def test_sql_plain_string_query() -> None:
    bus = Bus()
    results = []
    bus.subscribe("slm/sql/result", lambda t, m: results.append(m))

    comp = SqlAgentOid(
        bus=bus,
        subscribe="test/sql~query",
        properties={"driver": "sqlite", "connection": ":memory:"},
    )
    await comp.start()
    await bus.publish("test/sql", "SELECT 42 AS answer")

    assert len(results) == 1
    assert results[0]["rows"] == [[42]]
    await comp.stop()


async def test_sql_connection_closed_on_stop() -> None:
    bus = Bus()
    comp = SqlAgentOid(
        bus=bus,
        properties={"driver": "sqlite", "connection": ":memory:"},
    )
    await comp.start()
    assert comp._con is not None
    await comp.stop()
    assert comp._con is None
