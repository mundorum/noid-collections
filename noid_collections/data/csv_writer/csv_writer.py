"""
data:csv-writer — write CSV data received on the bus to a file.

Accepts two input modes, mirroring the output modes of data:csv-source:

  complete   — receives one `table` notice with columns and all rows, then `done`
  row_by_row — receives `schema` once (column names), then N `row` notices, then `done`

Rows are written straight to a temporary file (`<output_file>.tmp`) as they
arrive, so memory usage stays bounded regardless of table size. `schema` and
`table` both (re)start the file: any previously written content is discarded.
On `done`, the temporary file is atomically moved to `output_file` (replacing
any existing file there), so `output_file` never shows partial content.

The `format` property matches data:csv-source's output format:
  "dict" (default) — rows are dicts {"col": value, ...}
  "list" (compact) — rows are lists [value, ...] ordered by `columns`

Properties:
    output_file — destination file path (required)
    encoding    — file encoding (default: "utf-8")
    format      — "dict" (default) or "list" (compact)
    delimiter   — field separator (default: ","); use "\t" for tab-separated
                  output. Must match the delimiter used by any paired
                  data:csv-source upstream, the same way `format` must match.

The quote character is not configurable: Python's csv module already quotes
a field only when needed (default quotechar `"`), so there is nothing to
configure or auto-detect.

Received notices:
    table  — {"columns": [...], "rows": [...]}  complete table; (re)starts the file
    schema — {"columns": [...]}                 column names; (re)starts the file
    row    — {"row": {...} or [...]}             one row, written immediately
    done   — {}                                 finalize the file

Published notices:
    written — {}                          emitted after each physical write (schema/table/row)
    done    — {"file": "<output_file>"}   emitted once the file is finalized and ready to use

Scene usage:
    {
      "type": "data:csv-writer",
      "id":   "writer",
      "properties": {
        "output_file": "output/result.csv"
      },
      "subscribe": "pipeline/table~table;pipeline/done~done",
      "publish":   "done~player/done"
    }

  Row-by-row wiring (pipe from data:csv-source):
    "subscribe": "csv/schema~schema;csv/row~row;csv/exhausted~done"
"""
import asyncio
import csv
import os
from typing import List, Optional, TextIO, Union

from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "data:csv-writer",
    "name": "CSV Writer",
    "description": (
        "Streams incoming CSV table or row notices to a temporary file and "
        "atomically publishes it to output_file when a done notice is received. "
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
        "format": {
            "default": "dict",
            "description": (
                "Row payload format, matching data:csv-source. "
                "'dict' (default): each row is {col: value, ...}. "
                "'list' (compact): each row is [value, ...] ordered by columns."
            ),
        },
        "delimiter": {
            "default": ",",
            "description": (
                "Field separator character. Use \"\\t\" for tab-separated output. "
                "Must match the delimiter used by any paired data:csv-source."
            ),
        },
    },
    "receive": {
        "table": {
            "description": (
                "Complete table payload. (Re)starts the file, discarding any "
                "previously written content. Keys: columns (list of str), "
                "rows (list of dicts or lists). Optional label key is ignored."
            ),
        },
        "schema": {
            "description": (
                "Column names for row-by-row mode. (Re)starts the file, discarding "
                "any previously written content. Key: columns (list of str). "
                "Optional label key is ignored."
            ),
        },
        "row": {
            "description": (
                "One data row, written immediately. "
                "Key: row (dict or list depending on format). "
                "Optional label and index keys are ignored."
            ),
        },
        "done": {
            "description": "Finalizes the file and emits the done notice.",
        },
    },
    "publish": "written~csv/written;done~csv/done",
    "output_notices": {
        "written": {
            "description": "Emitted after each physical write (schema/table/row).",
        },
        "done": {
            "description": (
                "Emitted once the file is finalized and ready to use. Payload key: file (str)."
            ),
        },
    },
})
class CsvWriterOid(OidComponent):
    """Streams incoming CSV table/row notices to a file, finalized atomically on done."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._columns: List[str] = []
        self._file: Optional[TextIO] = None
        self._writer = None
        self._tmp_path: Optional[str] = None

    async def handle_table(self, notice: str, message: dict) -> None:
        msg = message or {}
        columns = list(msg.get("columns", []))
        rows = list(msg.get("rows", []))
        fmt = self.format
        await asyncio.to_thread(self._reset_and_open, columns)
        await asyncio.to_thread(self._write_rows, rows, columns, fmt)
        await self._notify("written", {})

    async def handle_schema(self, notice: str, message: dict) -> None:
        columns = list((message or {}).get("columns", []))
        await asyncio.to_thread(self._reset_and_open, columns)
        await self._notify("written", {})

    async def handle_row(self, notice: str, message: dict) -> None:
        row = (message or {}).get("row")
        if row is None:
            return
        if self._file is None:
            await asyncio.to_thread(self._reset_and_open, self._columns)
        await asyncio.to_thread(self._write_rows, [row], self._columns, self.format)
        await self._notify("written", {})

    async def handle_done(self, notice: str, message: dict) -> None:
        await asyncio.to_thread(self._finalize)
        await self._notify("done", {"file": self.output_file})

    # -- blocking helpers, always run via asyncio.to_thread --

    def _reset_and_open(self, columns: List[str]) -> None:
        self._close_file()
        self._columns = columns
        self._tmp_path = f"{self.output_file}.tmp"
        self._file = open(self._tmp_path, "w", newline="", encoding=self.encoding)
        self._writer = csv.writer(self._file, delimiter=self.delimiter)
        if columns:
            self._writer.writerow(columns)

    def _write_rows(self, rows: List[Union[dict, list]], columns: List[str], fmt: str) -> None:
        for row in rows:
            if fmt == "list":
                self._writer.writerow(row)
            else:
                self._writer.writerow([row.get(col, "") for col in columns])

    def _close_file(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
            self._writer = None

    def _finalize(self) -> None:
        wrote_something = self._tmp_path is not None
        tmp_path = self._tmp_path
        self._close_file()
        if wrote_something:
            os.replace(tmp_path, self.output_file)
        self._tmp_path = None
        self._columns = []
