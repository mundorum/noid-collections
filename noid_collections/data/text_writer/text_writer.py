"""
data:text-writer — write text messages received on the bus to a file.

Accepts two input modes, mirroring the output modes of pdf:extractor-* and
pdf:postprocessor:

  complete     — receives one `document` notice with the full content, then `done`
  segment_by_segment — receives N `segment` notices (written as they arrive), then `done`

Segments are written straight to a temporary file (`<output_file>.tmp`) as
they arrive, so memory usage stays bounded regardless of document size.
`document` (re)starts the file: any previously written content is discarded.
On `done`, the temporary file is atomically moved to `output_file` (replacing
any existing file there), so `output_file` never shows partial content.

Publishes `written` after each physical write, and `done` once the file is
finalized — `done` can be wired to `player/done` to terminate a noid-play
session.

Properties:
    output_file       — destination file path (required)
    encoding           — file encoding (default: "utf-8")
    segment_separator — text inserted between accumulated segments (default: "\\n\\n")

Received notices:
    document — {"content": "..."}   complete text; (re)starts the file
    segment  — {"content": "..."}   one segment, written immediately
    done     — {}                    finalize the file

Published notices:
    written — {}                          emitted after each physical write (document/segment)
    done    — {"file": "<output_file>"}   emitted once the file is finalized and ready to use

Scene usage:
    {
      "type": "data:text-writer",
      "id":   "writer",
      "properties": {
        "output_file": "output/result.md"
      },
      "subscribe": "pipeline/document~document;pipeline/done~done",
      "publish":   "done~player/done"
    }
"""
import asyncio
import os
from typing import Optional, TextIO

from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "data:text-writer",
    "name": "Text Writer",
    "description": (
        "Streams incoming document or segment notices to a temporary file and "
        "atomically publishes it to output_file when a done notice is received."
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
        "segment_separator": {
            "default": "\n\n",
            "description": "Text inserted between accumulated segments.",
        },
    },
    "receive": {
        "document": {
            "description": (
                "Complete text content. (Re)starts the file, discarding any "
                "previously written content. Payload key: content (str)."
            ),
        },
        "segment": {
            "description": "One segment of content, written immediately. Payload key: content (str).",
        },
        "done": {
            "description": "Finalizes the file and emits the done notice.",
        },
    },
    "publish": "written~file/written;done~file/done",
    "output_notices": {
        "written": {
            "description": "Emitted after each physical write (document/segment).",
        },
        "done": {
            "description": (
                "Emitted once the file is finalized and ready to use. Payload key: file (str)."
            ),
        },
    },
})
class TextWriterOid(OidComponent):
    """Streams incoming document/segment notices to a file, finalized atomically on done."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._file: Optional[TextIO] = None
        self._tmp_path: Optional[str] = None
        self._first_write = True

    async def handle_document(self, notice: str, message: dict) -> None:
        content = (message or {}).get("content", "")
        await asyncio.to_thread(self._reset_and_open)
        await asyncio.to_thread(self._write_segment, content)
        await self._notify("written", {})

    async def handle_segment(self, notice: str, message: dict) -> None:
        content = (message or {}).get("content", "")
        if self._file is None:
            await asyncio.to_thread(self._reset_and_open)
        await asyncio.to_thread(self._write_segment, content)
        await self._notify("written", {})

    async def handle_done(self, notice: str, message: dict) -> None:
        await asyncio.to_thread(self._finalize)
        await self._notify("done", {"file": self.output_file})

    # -- blocking helpers, always run via asyncio.to_thread --

    def _reset_and_open(self) -> None:
        self._close_file()
        self._tmp_path = f"{self.output_file}.tmp"
        self._file = open(self._tmp_path, "w", encoding=self.encoding)
        self._first_write = True

    def _write_segment(self, content: str) -> None:
        if not self._first_write:
            self._file.write(self.segment_separator)
        self._file.write(content)
        self._first_write = False

    def _close_file(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def _finalize(self) -> None:
        wrote_something = self._tmp_path is not None
        tmp_path = self._tmp_path
        self._close_file()
        if wrote_something:
            os.replace(tmp_path, self.output_file)
        self._tmp_path = None
        self._first_write = True
