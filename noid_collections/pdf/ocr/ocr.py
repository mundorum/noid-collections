"""
pdf:ocr — apply OCR to a PDF file using OCRmyPDF.

Triggered by an `ocr` notice (or at start when auto_start is True).
The input file can be set via the input_file property or overridden
in the triggering message as {"file": "path"}.
A temporary output file is created unless output_file is explicitly set.

Publishes `done` with {"file": "<output_path>"} on success,
or `error` with {"error": "...", "file": "..."} on failure.

Properties:
    input_file   — path to the input PDF (overridden by message "file" key)
    output_file  — path for the output PDF; empty = auto temp file
    language     — Tesseract language code (default: "eng")
    deskew       — correct skewed pages (default: True)
    rotate_pages — auto-rotate pages by content (default: True)
    force_ocr    — OCR even if text layer already exists (default: True)
    auto_start   — begin OCR immediately on component start (default: False)

Published notices:
    done  — {"file": "<output_path>"}
    error — {"error": "...", "file": "<input_path>"}

Scene usage:
    {
      "type": "pdf:ocr",
      "id":   "ocr",
      "properties": {
        "input_file": "document.pdf",
        "auto_start": true
      },
      "publish": "done~pipeline/ocr-done;error~pipeline/error"
    }
"""
import asyncio
import os
import tempfile

from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "pdf:ocr",
    "properties": {
        "input_file":   {"default": ""},
        "output_file":  {"default": ""},
        "language":     {"default": "eng"},
        "deskew":       {"default": True},
        "rotate_pages": {"default": True},
        "force_ocr":    {"default": True},
        "auto_start":   {"default": False},
    },
    "receive": ["ocr"],
    "publish": "done~pdf/ocr/done;error~pdf/ocr/error;status~pdf/ocr/status",
})
class PdfOcrOid(OidComponent):
    """Runs OCRmyPDF on a PDF file; publishes done with the output path."""

    async def start(self) -> None:
        await super().start()
        if self.auto_start:
            asyncio.create_task(self._run_ocr(self.input_file))

    async def handle_ocr(self, notice: str, message: dict) -> None:
        input_file = (message or {}).get("file", "") or self.input_file
        asyncio.create_task(self._run_ocr(input_file))

    async def _run_ocr(self, input_file: str) -> None:
        try:
            import ocrmypdf
            output_file = self.output_file
            if not output_file:
                fd, output_file = tempfile.mkstemp(suffix="_ocr.pdf")
                os.close(fd)
            await self._notify("status", f"OCR starting — {input_file}")
            lang = self.language
            deskew = self.deskew
            rotate = self.rotate_pages
            force = self.force_ocr
            await asyncio.to_thread(lambda: ocrmypdf.ocr(
                input_file=input_file,
                output_file=output_file,
                language=lang,
                deskew=deskew,
                rotate_pages=rotate,
                force_ocr=force,
                optimize=1,
                progress_bar=False,
            ))
            await self._notify("status", f"OCR complete — {output_file}")
            await self._notify("done", {"file": output_file})
        except Exception as exc:
            await self._notify("error", {"error": str(exc), "file": input_file})
