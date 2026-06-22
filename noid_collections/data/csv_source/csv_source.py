"""
slm:csv-source — reads a CSV string and publishes it in two modes:

  1. Complete table  — send a `table` notice with all rows as a list of dicts.
  2. Row-by-row      — send `schema` once (column names), then one `row` per call.
     `first` resets the cursor and emits the first row.
     `next`  advances the cursor and emits the next row, or `exhausted` at end.

Notices received:
  table  → publish the full table (label + columns + rows)
  first  → publish schema + first row; reset internal cursor
  next   → publish next row, or `exhausted` if no more rows

Notices published:
  table     → {"label", "columns": [...], "rows": [{...}, ...]}
  schema    → {"label", "columns": [...]}
  row       → {"label", "index": int, "row": {...}}
  exhausted → {"label"}

Scene usage example:
  {
    "type": "slm:csv-source",
    "properties": {
      "label":   "patients",
      "content": "name,age\\nAlice,30\\nBob,25"
    },
    "subscribe": "pipeline/start~table;pipeline/first~first;pipeline/next~next",
    "publish":   "table~pipeline/table;schema~pipeline/schema;row~pipeline/row;exhausted~pipeline/done"
  }
"""
import csv
import io
from typing import Dict, List

from noid.core.component import Noid, OidComponent


def _parse_csv(content: str) -> tuple[List[str], List[Dict[str, str]]]:
    """Return (columns, rows) from a CSV string.  First line is the header."""
    if not content.strip():
        return [], []
    reader = csv.DictReader(io.StringIO(content), skipinitialspace=True)
    columns = [c.strip() for c in (reader.fieldnames or [])]
    rows: List[Dict[str, str]] = []
    for raw_row in reader:
        if raw_row is None:
            continue
        rows.append({
            (k or "").strip(): (v or "").strip()
            for k, v in raw_row.items()
            if k is not None and k.strip()
        })
    return columns, rows


@Noid.component({
    "id": "slm:csv-source",
    "properties": {
        "content": {"default": ""},
        "label":   {"default": "csv"},
    },
    "receive": ["table", "first", "next"],
    "publish":  (
        "table~slm/csv/table"
        ";schema~slm/csv/schema"
        ";row~slm/csv/row"
        ";exhausted~slm/csv/exhausted"
    ),
})
class CsvSourceOid(OidComponent):
    """CSV reader that serves the complete table or rows one at a time."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._columns: List[str] = []
        self._rows: List[Dict[str, str]] = []
        self._cursor: int = -1
        self._parsed: bool = False

    def _ensure_parsed(self) -> None:
        if not self._parsed:
            self._columns, self._rows = _parse_csv(self.content)
            self._parsed = True

    async def handle_table(self, notice: str, message: dict) -> None:
        """Publish the entire CSV as a structured table."""
        self._ensure_parsed()
        await self._notify("table", {
            "label":   self.label,
            "columns": self._columns,
            "rows":    self._rows,
        })

    async def handle_first(self, notice: str, message: dict) -> None:
        """Reset cursor, publish schema, then publish the first row."""
        self._ensure_parsed()
        self._cursor = 0
        await self._notify("schema", {"label": self.label, "columns": self._columns})
        if self._rows:
            await self._notify("row", {
                "label": self.label,
                "index": 0,
                "row":   self._rows[0],
            })
        else:
            await self._notify("exhausted", {"label": self.label})

    async def handle_next(self, notice: str, message: dict) -> None:
        """Advance cursor and publish the next row, or signal exhaustion."""
        self._ensure_parsed()
        self._cursor += 1
        if 0 <= self._cursor < len(self._rows):
            await self._notify("row", {
                "label": self.label,
                "index": self._cursor,
                "row":   self._rows[self._cursor],
            })
        else:
            await self._notify("exhausted", {"label": self.label})
