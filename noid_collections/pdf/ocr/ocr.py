"""
pdf:ocr — apply OCR to a PDF file using OCRmyPDF.

Triggered by an `ocr` notice. The input file can be set via the input_file
property or overridden in the triggering message as {"file": "path"}.
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

Published notices:
    done  — {"file": "<output_path>"}
    error — {"error": "...", "file": "<input_path>"}

Scene usage:
    {
      "type": "pdf:ocr",
      "id":   "ocr",
      "properties": {
        "input_file": "document.pdf"
      },
      "subscribe": "player/start~ocr",
      "publish": "done~pipeline/ocr-done;error~pipeline/error"
    }
"""
import asyncio
import os
import tempfile

from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "pdf:ocr",
    "name": "PDF OCR",
    "description": (
        "Applies OCR to a PDF file using OCRmyPDF and publishes "
        "the path to the output file."
    ),
    "properties": {
        "input_file": {
            "default": "",
            "kind": "resource",
            "description": "Path to the input PDF. Can be overridden by the ocr notice payload.",
        },
        "output_file": {
            "default": "",
            "kind": "resource",
            "description": "Path for the OCR'd output PDF. If empty, a temporary file is created.",
        },
        "language": {
            "default": "eng",
            "description": "Tesseract language code (e.g. eng, por, fra).",
        },
        "deskew": {
            "default": True,
            "description": "Correct skewed pages before OCR.",
        },
        "rotate_pages": {
            "default": True,
            "description": "Auto-rotate pages based on content orientation.",
        },
        "force_ocr": {
            "default": True,
            "description": "OCR even if a text layer already exists in the PDF.",
        },
    },
    "receive": {
        "ocr": {
            "description": "Trigger OCR. Payload key file (str) overrides the input_file property.",
        },
    },
    "publish": "done~pdf/ocr/done;error~pdf/ocr/error;status~pdf/ocr/status",
    "output_notices": {
        "done": {
            "description": "OCR complete. Payload key: file (str) — path to the output PDF.",
        },
        "error": {
            "description": "OCR failed. Keys: error (str), file (str) — input path.",
        },
        "status": {
            "description": "Progress message string emitted during OCR.",
        },
    },
})
class PdfOcrOid(OidComponent):
    """Runs OCRmyPDF on a PDF file; publishes done with the output path."""

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
            ocrmypdf.ocr(
                input_file=input_file,
                output_file=output_file,
                language=self.language,
                deskew=self.deskew,
                rotate_pages=self.rotate_pages,
                force_ocr=self.force_ocr,
                optimize=1,
                progress_bar=False,
            )
            await self._notify("status", f"OCR complete — {output_file}")
            await self._notify("done", {"file": output_file})
        except Exception as exc:
            await self._notify("error", {"error": str(exc), "file": input_file})
