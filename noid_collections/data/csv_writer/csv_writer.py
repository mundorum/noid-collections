"""
data:csv-writer — write CSV data received on the bus to a file.

Accepts two input modes, mirroring the output modes of data:csv-source:

  complete   — receives one `table` notice with columns and all rows, then `done`
  row_by_row — receives `schema` once (column names), then N `row` notices, then `done`

In both cases, the file is written on receipt of the `done` notice.

The `format` property matches data:csv-source's output format:
  "dict" (default) — rows are dicts {"col": value, ...}
  "list" (compact) — rows are lists [value, ...] ordered by `columns`

Properties:
    output_file — destination file path (required)
    encoding    — file encoding (default: "utf-8")
    append      — append to existing file instead of overwriting (default: False)
    format      — "dict" (default) or "list" (compact)

Received notices:
    table  — {"columns": [...], "rows": [...]}  complete table (replaces buffer)
    schema — {"columns": [...]}                 column names, resets row buffer
    row    — {"row": {...} or [...]}             one row (accumulated until done)
    done   — {}                                 trigger write + publish written

Published notices:
    written — {"file": "<output_file>"}

Scene usage:
    {
      "type": "data:csv-writer",
      "id":   "writer",
      "properties": {
        "output_file": "output/result.csv"
      },
      "subscribe": "pipeline/table~table;pipeline/done~done",
      "publish":   "written~player/done"
    }

  Row-by-row wiring (pipe from data:csv-source):
    "subscribe": "csv/schema~schema;csv/row~row;csv/exhausted~done"
"""
import asyncio
import csv
from typing import List, Union

from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "data:csv-writer",
    "name": "CSV Writer",
    "description": (
        "Buffers incoming CSV table or row notices and writes them to a file "
        "when a done notice is received. "
        "Mirrors the two output modes of data:csv-source: "
        "complete table (table + done) or row-by-row (schema + row… + done)."
    ),
    "properties": {
        "output_file": {
            "default": "",
            "kind": "resource",
            "description": "Destination file path (required).",
        },
        "encoding": {
            "default": "utf-8",
            "description": "File encoding.",
        },
        "append": {
            "default": False,
            "description": "Append to an existing file instead of overwriting.",
        },
        "format": {
            "default": "dict",
            "description": (
                "Row payload format, matching data:csv-source. "
                "'dict' (default): each row is {col: value, ...}. "
                "'list' (compact): each row is [value, ...] ordered by columns."
            ),
        },
    },
    "receive": {
        "table": {
            "description": (
                "Complete table payload. Replaces any buffered data. "
                "Keys: columns (list of str), rows (list of dicts or lists). "
                "Optional label key is ignored."
            ),
        },
        "schema": {
            "description": (
                "Column names for row-by-row mode. Resets the row buffer. "
                "Key: columns (list of str). Optional label key is ignored."
            ),
        },
        "row": {
            "description": (
                "One data row, accumulated until done. "
                "Key: row (dict or list depending on format). "
                "Optional label and index keys are ignored."
            ),
        },
        "done": {
            "description": "Triggers the file write and emits the written notice.",
        },
    },
    "publish": "written~csv/written",
    "output_notices": {
        "written": {
            "description": "Emitted after the file is flushed to disk. Payload key: file (str).",
        },
    },
})
class CsvWriterOid(OidComponent):
    """Buffers incoming CSV table/row notices and writes them to a file on done."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._columns: List[str] = []
        self._rows: List[Union[dict, list]] = []

    async def handle_table(self, notice: str, message: dict) -> None:
        msg = message or {}
        self._columns = list(msg.get("columns", []))
        self._rows = list(msg.get("rows", []))

    async def handle_schema(self, notice: str, message: dict) -> None:
        self._columns = list((message or {}).get("columns", []))
        self._rows = []

    async def handle_row(self, notice: str, message: dict) -> None:
        row = (message or {}).get("row")
        if row is not None:
            self._rows.append(row)

    async def handle_done(self, notice: str, message: dict) -> None:
        if self._columns or self._rows:
            columns = list(self._columns)
            rows = list(self._rows)
            fmt = self.format
            mode = "a" if self.append else "w"
            enc = self.encoding
            path = self.output_file
            await asyncio.to_thread(_write_csv, path, columns, rows, fmt, mode, enc)
            self._columns = []
            self._rows = []
        await self._notify("written", {"file": self.output_file})


def _write_csv(
    path: str,
    columns: List[str],
    rows: List[Union[dict, list]],
    fmt: str,
    mode: str,
    encoding: str,
) -> None:
    with open(path, mode, newline="", encoding=encoding) as f:
        writer = csv.writer(f)
        if columns:
            writer.writerow(columns)
        for row in rows:
            if fmt == "list":
                writer.writerow(row)
            else:
                writer.writerow([row.get(col, "") for col in columns])
