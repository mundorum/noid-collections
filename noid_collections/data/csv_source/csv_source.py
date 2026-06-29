"""
data:csv-source — reads CSV data and publishes it in two modes:

  1. Complete table  — send a `load` notice with all rows as a list of dicts.
  2. Row-by-row      — send `schema` once (column names), then one `row` per call.
     `first` resets the cursor and emits the first row.
     `next`  advances the cursor and emits the next row, or `exhausted` at end.

Content can be provided inline via the `content` property or read from a file
via the `input_file` property.  `input_file` takes precedence over `content`.

The optional `sample_size` property limits the number of rows served. If set
to a positive integer, only the first N rows are visible (in all modes: load,
first, and next).  0 means no limit.

Notices received:
  load   → publish the full table (label + columns + rows)
  first  → publish schema + first row; reset internal cursor
  next   → publish next row, or `exhausted` if no more rows

Notices published:
  table     → {"label", "columns": [...], "rows": [{...}, ...]}
  schema    → {"label", "columns": [...]}
  row       → {"label", "index": int, "row": {...}}
  exhausted → {"label"}

Scene usage example:
  {
    "type": "data:csv-source",
    "properties": {
      "label":   "patients",
      "content": "name,age\\nAlice,30\\nBob,25"
    },
    "subscribe": "pipeline/start~load;pipeline/first~first;pipeline/next~next",
    "publish":   "table~pipeline/table;schema~pipeline/schema;row~pipeline/row;exhausted~pipeline/done"
  }

  Or loading from a file with a sample limit:
  {
    "type": "data:csv-source",
    "properties": {
      "label":       "patients",
      "input_file":  "shared:data/patients.csv",
      "sample_size": 10
    },
    "subscribe": "pipeline/start~load;pipeline/first~first;pipeline/next~next",
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
    "id": "data:csv-source",
    "name": "CSV Source",
    "description": (
        "Reads CSV data and publishes it in full-table mode "
        "or row-by-row mode with a movable cursor. "
        "Content can be provided inline or read from a file. "
        "An optional sample_size limits the number of rows served."
    ),
    "properties": {
        "content": {
            "default": "",
            "description": (
                "Inline CSV text, including a header row as the first line. "
                "Ignored if `input_file` is set."
            ),
        },
        "input_file": {
            "default": "",
            "kind": "resource",
            "description": "Path to a CSV file to read. Takes precedence over `content`.",
        },
        "label": {
            "default": "csv",
            "description": "Label included in every published payload to identify this source.",
        },
        "sample_size": {
            "default": 0,
            "description": (
                "Maximum number of rows to serve. 0 means no limit. "
                "Applies consistently to all modes (load, first, next)."
            ),
        },
    },
    "receive": {
        "load":  {"description": "Publish the entire CSV as a structured table."},
        "first": {"description": "Reset the row cursor; publish schema then the first row."},
        "next":  {"description": "Advance the cursor; publish the next row, or exhausted if none remain."},
    },
    "publish": (
        "table~data/csv/table"
        ";schema~data/csv/schema"
        ";row~data/csv/row"
        ";exhausted~data/csv/exhausted"
    ),
    "output_notices": {
        "table": {
            "description": "Full table payload. Keys: label, columns (list of str), rows (list of dicts).",
        },
        "schema": {
            "description": "Column names only. Keys: label, columns (list of str). Emitted before the first row.",
        },
        "row": {
            "description": "One data row. Keys: label, index (int), row (dict).",
        },
        "exhausted": {
            "description": "All rows have been served. Key: label.",
        },
    },
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
            if self.input_file:
                with open(self.input_file, "r", encoding="utf-8") as f:
                    content = f.read()
            else:
                content = self.content
            self._columns, self._rows = _parse_csv(content)
            self._parsed = True

    def _effective_rows(self) -> List[Dict[str, str]]:
        """Return rows capped to sample_size (0 = no cap)."""
        n = int(self.sample_size) if self.sample_size else 0
        return self._rows[:n] if n > 0 else self._rows

    async def handle_load(self, notice: str, message: dict) -> None:
        """Publish the entire CSV as a structured table."""
        self._ensure_parsed()
        rows = self._effective_rows()
        await self._notify("table", {
            "label":   self.label,
            "columns": self._columns,
            "rows":    rows,
        })

    async def handle_first(self, notice: str, message: dict) -> None:
        """Reset cursor, publish schema, then publish the first row."""
        self._ensure_parsed()
        self._cursor = 0
        await self._notify("schema", {"label": self.label, "columns": self._columns})
        rows = self._effective_rows()
        if rows:
            await self._notify("row", {
                "label": self.label,
                "index": 0,
                "row":   rows[0],
            })
        else:
            await self._notify("exhausted", {"label": self.label})

    async def handle_next(self, notice: str, message: dict) -> None:
        """Advance cursor and publish the next row, or signal exhaustion."""
        self._ensure_parsed()
        self._cursor += 1
        rows = self._effective_rows()
        if 0 <= self._cursor < len(rows):
            await self._notify("row", {
                "label": self.label,
                "index": self._cursor,
                "row":   rows[self._cursor],
            })
        else:
            await self._notify("exhausted", {"label": self.label})
