"""
data:sql — executes SQL queries against a DuckDB or SQLite database.

The database connection is opened lazily when the first `query` notice arrives.
Multiple component instances can connect to different databases independently.

Properties:
  driver     — "duckdb" | "sqlite" (default: "duckdb")
  connection — database path or ":memory:" (default: ":memory:")

Receives:
  query → {"sql": str}  or plain SQL string
         Optionally includes {"params": list} for parameterized queries.

Publishes:
  result → {
      "sql":       str,               # executed query
      "columns":   [str, ...],
      "rows":      [[...], ...],      # raw row values
      "row_count": int,
  }
  error  → {"sql": str, "message": str}

Scene usage example:
  {
    "type": "data:sql",
    "properties": {"driver": "duckdb", "connection": "data/medical.db"},
    "subscribe": "pipeline/sql-in~query",
    "publish":   "result~pipeline/sql-out;error~pipeline/sql-error"
  }
"""
from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "data:sql",
    "properties": {
        "driver":     {"default": "duckdb"},
        "connection": {"default": ":memory:"},
    },
    "receive": ["query"],
    "publish": "result~slm/sql/result;error~slm/sql/error",
})
class SqlAgentOid(OidComponent):
    """Executes SQL and publishes structured results."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._con = None

    async def start(self) -> None:
        await super().start()
        self._connect()

    async def stop(self) -> None:
        if self._con is not None:
            try:
                self._con.close()
            except Exception:
                pass
            self._con = None
        await super().stop()

    def _connect(self) -> None:
        driver = (self.driver or "duckdb").lower()
        if driver == "duckdb":
            try:
                import duckdb
            except ImportError as exc:
                raise RuntimeError(
                    "duckdb package is required: pip install duckdb"
                ) from exc
            self._con = duckdb.connect(self.connection)
        elif driver == "sqlite":
            import sqlite3
            self._con = sqlite3.connect(self.connection)
        else:
            raise ValueError(f"Unsupported SQL driver: {driver!r}. Use 'duckdb' or 'sqlite'.")

    async def handle_query(self, notice: str, message) -> None:
        if isinstance(message, dict):
            sql = message.get("sql", "").strip()
            params = message.get("params", [])
        else:
            sql = str(message).strip()
            params = []

        if not sql:
            return

        try:
            cursor = self._con.execute(sql, params) if params else self._con.execute(sql)
            rows = cursor.fetchall()
            columns = [d[0] for d in (cursor.description or [])]
            await self._notify("result", {
                "sql":       sql,
                "columns":   columns,
                "rows":      [list(r) for r in rows],
                "row_count": len(rows),
            })
        except Exception as exc:
            await self._notify("error", {"sql": sql, "message": str(exc)})
