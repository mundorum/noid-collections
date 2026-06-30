"""
data:file-writer — write text messages received on the bus to a file.

Accepts two input modes, mirroring the output modes of pdf:extractor-* and
pdf:postprocessor:

  complete     — receives one `text` notice with the full content, then `done`
  page_by_page — receives N `page` notices (accumulated in memory), then `done`

In both cases, the file is written on receipt of the `done` notice, so the
pipeline downstream of the extractor/postprocessor needs no special handling —
just subscribe to the same topics for `text` (or `page`) and `done`.

Publishes `written` when the file has been flushed to disk, which can be
wired to `player/done` to terminate a noid-play session.

Properties:
    output_file    — destination file path (required)
    encoding       — file encoding (default: "utf-8")
    append         — append to existing file instead of overwriting (default: False)
    page_separator — text inserted between pages in page_by_page mode (default: "\\n\\n")

Received notices:
    text — {"content": "..."}   complete text (buffered until done)
    page — {"content": "..."}   one page (accumulated until done)
    done — {}                   trigger write + publish written

Published notices:
    written — {"file": "<output_file>"}

Scene usage:
    {
      "type": "data:file-writer",
      "id":   "writer",
      "properties": {
        "output_file": "output/result.md"
      },
      "subscribe": "pipeline/text~text;pipeline/done~done",
      "publish":   "written~player/done"
    }
"""
import asyncio
from typing import List

from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "data:file-writer",
    "name": "File Writer",
    "description": (
        "Buffers incoming text or page notices and writes them to a file "
        "when a done notice is received."
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
        "page_separator": {
            "default": "\n\n",
            "description": "Text inserted between accumulated page segments.",
        },
    },
    "receive": {
        "text": {
            "description": "Complete text content. Buffered until done. Payload key: content (str).",
        },
        "page": {
            "description": "One page of content. Accumulated until done. Payload key: content (str).",
        },
        "done": {
            "description": "Triggers the file write and emits the written notice.",
        },
    },
    "publish": "written~file/written",
    "output_notices": {
        "written": {
            "description": "Emitted after the file is flushed to disk. Payload key: file (str).",
        },
    },
})
class FileWriterOid(OidComponent):
    """Buffers incoming text/page notices and writes them to a file on done."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._buffer: List[str] = []

    async def handle_text(self, notice: str, message: dict) -> None:
        self._buffer.append((message or {}).get("content", ""))

    async def handle_page(self, notice: str, message: dict) -> None:
        self._buffer.append((message or {}).get("content", ""))

    async def handle_done(self, notice: str, message: dict) -> None:
        if self._buffer:
            buf = list(self._buffer)
            sep = self.page_separator
            mode = "a" if self.append else "w"
            enc = self.encoding
            path = self.output_file
            await asyncio.to_thread(_write_file, path, buf, sep, mode, enc)
            self._buffer = []
        await self._notify("written", {"file": self.output_file})


def _write_file(path: str, contents: List[str], sep: str, mode: str, encoding: str) -> None:
    with open(path, mode, encoding=encoding) as f:
        for i, content in enumerate(contents):
            if i > 0:
                f.write(sep)
            f.write(content)
