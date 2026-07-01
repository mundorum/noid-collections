"""
data:csv-source — reads CSV data and publishes it in two modes:

  1. Complete table  — send a `load` notice with all rows as a list of dicts.
  2. Row-by-row      — send `schema` once (column names), then one `row` per call.
     `first` resets the cursor and emits the first row.
     `next`  advances the cursor and emits the next row, or `exhausted` at end.

Content can be provided inline via the `content` property or read from a file
via the `input_file` property.  `input_file` takes precedence over `content`.

The `delimiter` property sets the field separator (default ","). Use "\t" for
tab-separated files. It must match the delimiter used by any paired
data:csv-writer downstream, the same way `format` must match.

The quote character is not configurable: Python's csv module already handles
quoting transparently (default quotechar `"`), so there is nothing to detect
or configure.

The optional `sample_size` property limits the number of rows served. If set
to a positive integer, only the first N rows are visible (in all modes: load,
first, and next).  0 means no limit.

The `format` property controls the row payload shape:
  "dict" (default) — each row is a dict {"col": value, ...}
  "list" (compact) — each row is a list [value, ...]; column order follows `columns`

Row indices are 1-based in all modes.

Notices received:
  load   → publish the full table (label + columns + rows)
  first  → publish schema + first row; reset internal cursor
  next   → publish next row, or `exhausted` if no more rows

Notices published (format="dict"):
  table     → {"label", "columns": [...], "rows": [{...}, ...]}
  schema    → {"label", "columns": [...]}
  row       → {"label", "index": int, "row": {...}}
  exhausted → {"label"}

Notices published (format="list"):
  table     → {"label", "columns": [...], "rows": [[...], ...]}
  schema    → {"label", "columns": [...]}
  row       → {"label", "index": int, "row": [...]}
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

  Or loading from a file with compact format:
  {
    "type": "data:csv-source",
    "properties": {
      "label":       "patients",
      "input_file":  "shared:data/patients.csv",
      "sample_size": 10,
      "format":      "list"
    },
    "subscribe": "pipeline/start~load;pipeline/first~first;pipeline/next~next",
    "publish":   "table~pipeline/table;schema~pipeline/schema;row~pipeline/row;exhausted~pipeline/done"
  }
"""
import csv
import io
from typing import Dict, List

from noid.core.component import Noid, OidComponent


def _parse_csv(content: str, delimiter: str = ",") -> tuple[List[str], List[Dict[str, str]]]:
    """Return (columns, rows) from a CSV string.  First line is the header."""
    if not content.strip():
        return [], []
    reader = csv.DictReader(io.StringIO(content), skipinitialspace=True, delimiter=delimiter)
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
            "kind": "text",
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
        "delimiter": {
            "default": ",",
            "description": (
                "Field separator character. Use \"\\t\" for tab-separated files. "
                "Must match the delimiter used by any paired data:csv-writer."
            ),
        },
        "label": {
            "default": "",
            "description": (
                "Optional label included in every published payload to identify this source. "
                "If empty (the default), no label key is included in the payload."
            ),
        },
        "sample_size": {
            "default": 0,
            "description": (
                "Maximum number of rows to serve. 0 means no limit. "
                "Applies consistently to all modes (load, first, next)."
            ),
        },
        "format": {
            "default": "dict",
            "description": (
                "Row payload format. "
                "'dict' (default): each row is {col: value, ...}. "
                "'list' (compact): each row is [value, ...] ordered by columns; "
                "saves memory for large tables by omitting repeated field names."
            ),
        },
    },
    "receive": {
        "load":  {"description": "Publish the entire CSV as a structured table."},
        "first": {"description": "Reset the row cursor; publish schema then the first row."},
        "next":  {
            "description": "Advance the cursor; publish the next row, or exhausted if none remain.",
        },
    },
    "publish": (
        "table~csv/table"
        ";schema~csv/schema"
        ";row~csv/row"
        ";exhausted~csv/exhausted"
    ),
    "output_notices": {
        "table": {
            "description": (
                "Full table payload. Keys: label, columns (list of str), rows. "
                "rows is a list of dicts (format='dict') or a list of lists (format='list')."
            ),
        },
        "schema": {
            "description": (
                "Column names only. Keys: label, columns (list of str). "
                "Emitted before the first row."
            ),
        },
        "row": {
            "description": (
                "One data row. Keys: label, index (int, 1-based), row. "
                "row is a dict (format='dict') or a list (format='list')."
            ),
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
            self._columns, self._rows = _parse_csv(content, self.delimiter)
            self._parsed = True

    def _effective_rows(self) -> List[Dict[str, str]]:
        """Return rows capped to sample_size (0 = no cap)."""
        n = int(self.sample_size) if self.sample_size else 0
        return self._rows[:n] if n > 0 else self._rows

    def _label_payload(self) -> dict:
        """Return {"label": ...} when a label is configured, else {}."""
        return {"label": self.label} if self.label else {}

    def _row_payload(self, row: Dict[str, str]):
        """Convert a row dict to the configured format."""
        if self.format == "list":
            return [row.get(col, "") for col in self._columns]
        return row

    async def handle_load(self, notice: str, message: dict) -> None:
        """Publish the entire CSV as a structured table."""
        self._ensure_parsed()
        rows = self._effective_rows()
        await self._notify("table", {
            **self._label_payload(),
            "columns": self._columns,
            "rows":    [self._row_payload(r) for r in rows],
        })

    async def handle_first(self, notice: str, message: dict) -> None:
        """Reset cursor, publish schema, then publish the first row."""
        self._ensure_parsed()
        self._cursor = 0
        await self._notify("schema", {**self._label_payload(), "columns": self._columns})
        rows = self._effective_rows()
        if rows:
            await self._notify("row", {
                **self._label_payload(),
                "index": 1,
                "row":   self._row_payload(rows[0]),
            })
        else:
            await self._notify("exhausted", self._label_payload())

    async def handle_next(self, notice: str, message: dict) -> None:
        """Advance cursor and publish the next row, or signal exhaustion."""
        self._ensure_parsed()
        self._cursor += 1
        rows = self._effective_rows()
        if 0 <= self._cursor < len(rows):
            await self._notify("row", {
                **self._label_payload(),
                "index": self._cursor + 1,
                "row":   self._row_payload(rows[self._cursor]),
            })
        else:
            await self._notify("exhausted", self._label_payload())
