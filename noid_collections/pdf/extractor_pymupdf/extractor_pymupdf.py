"""
pdf:extractor-pymupdf — extract raw text from a PDF using PyMuPDF (fitz).

Triggered by an `extract` notice (or at start when auto_extract is True).
The input file can be set via the input_file property or overridden in the
triggering message as {"file": "path"} — which is the format published by
pdf:ocr's `done` notice, enabling direct chaining.

Each page is extracted with PyMuPDF's get_text("text") and wrapped in a
"--- PAGE N ---" header. Raw text (no cleanup) is published so it can be
piped to pdf:postprocessor for format conversion and cleanup.

output_mode controls the dispatch:
    "complete"     — one `text` notice with all pages joined, then `done`
    "page_by_page" — one `page` notice per page (in extraction order), then `done`

Properties:
    input_file   — path to the PDF file (overridden by message "file" key)
    output_mode  — "complete" (default) or "page_by_page"
    auto_extract — begin extraction immediately on start (default: False)

Published notices:
    text  — {"file", "content": "<full text>", "pages": N}          (complete mode)
    page  — {"file", "page": N, "total": N, "content": "<page text>"}  (page_by_page)
    done  — {"file", "pages": N}                                     (always)
    error — {"file", "error": "..."}

Scene usage:
    {
      "type": "pdf:extractor-pymupdf",
      "id":   "extractor",
      "properties": {
        "input_file":  "document.pdf",
        "output_mode": "page_by_page",
        "auto_extract": true
      },
      "publish": "page~pipeline/page;done~pipeline/done;error~pipeline/error"
    }
"""
import asyncio

from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "pdf:extractor-pymupdf",
    "properties": {
        "input_file":   {"default": ""},
        "output_mode":  {"default": "complete"},
        "auto_extract": {"default": False},
    },
    "receive": ["extract"],
    "publish": "text~pdf/text;page~pdf/page;done~pdf/done;error~pdf/error;status~pdf/extractor/status",
})
class PdfExtractorPyMuPdfOid(OidComponent):
    """Extracts raw text from a PDF page by page using PyMuPDF."""

    async def start(self) -> None:
        await super().start()
        if self.auto_extract:
            asyncio.create_task(self._extract(self.input_file))

    async def handle_extract(self, notice: str, message: dict) -> None:
        input_file = (message or {}).get("file", "") or self.input_file
        asyncio.create_task(self._extract(input_file))

    async def _extract(self, input_file: str) -> None:
        try:
            await self._notify("status", f"Extracting text from {input_file}")
            pages = await asyncio.to_thread(_read_pages_pymupdf, input_file)
            total = len(pages)
            if self.output_mode == "page_by_page":
                for page_num, text in pages:
                    await self._notify("page", {
                        "file":    input_file,
                        "page":    page_num,
                        "total":   total,
                        "content": f"--- PAGE {page_num} ---\n\n{text.strip()}",
                    })
                    await self._notify("status", f"Extracted page {page_num} / {total}")
            else:
                full_text = "\n\n".join(
                    f"--- PAGE {n} ---\n\n{t.strip()}" for n, t in pages
                )
                await self._notify("text", {
                    "file":    input_file,
                    "content": full_text,
                    "pages":   total,
                })
            await self._notify("status", f"Extraction complete — {total} pages")
            await self._notify("done", {"file": input_file, "pages": total})
        except Exception as exc:
            await self._notify("error", {"error": str(exc), "file": input_file})


def _read_pages_pymupdf(input_file: str):
    import fitz  # PyMuPDF
    doc = fitz.open(input_file)
    pages = [(i + 1, doc.load_page(i).get_text("text")) for i in range(len(doc))]
    doc.close()
    return pages
