"""
pdf:extractor-markitdown — extract text/markdown from a PDF using MarkItDown.

MarkItDown converts the entire PDF at once (no page-by-page access), producing
flowing Markdown-style text. This component wraps that conversion as a noid
component, mirroring the interface of pdf:extractor-pymupdf so the two are
interchangeable in scene pipelines.

Triggered by an `extract` notice. The input file can be set via the
input_file property or overridden in the triggering message as {"file": "path"}.

When output_mode is "page_by_page" the entire converted text is published as
a single `page` notice (MarkItDown has no page boundary information), followed
by `done`.

Requires: pip install "markitdown[pdf]"

Properties:
    input_file  — path to the PDF file (overridden by message "file" key)
    output_mode — "complete" (default) or "page_by_page"

Published notices:
    text  — {"file", "content": "<markdown text>", "pages": null}   (complete mode)
    page  — {"file", "page": 1, "total": 1, "content": "<text>"}    (page_by_page)
    done  — {"file", "pages": null}                                  (always)
    error — {"file", "error": "..."}

Scene usage:
    {
      "type": "pdf:extractor-markitdown",
      "id":   "extractor",
      "properties": {
        "input_file": "document.pdf"
      },
      "subscribe": "player/start~extract",
      "publish": "text~pipeline/text;done~pipeline/done;error~pipeline/error"
    }
"""
import asyncio

from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "pdf:extractor-markitdown",
    "name": "PDF Extractor MarkItDown",
    "description": (
        "Extracts text from a PDF as flowing Markdown using MarkItDown. "
        "Interchangeable with pdf:extractor-pymupdf in scene pipelines."
    ),
    "properties": {
        "input_file": {
            "default": "",
            "description": "Path to the PDF to extract. Can be overridden by the extract notice payload.",
        },
        "output_mode": {
            "default": "complete",
            "description": (
                "Dispatch mode: complete (one text notice) or page_by_page "
                "(one page notice; MarkItDown has no page boundaries so total is always 1)."
            ),
        },
    },
    "receive": {
        "extract": {
            "description": "Trigger text extraction. Payload key file (str) overrides the input_file property.",
        },
    },
    "publish": "text~pdf/text;page~pdf/page;done~pdf/done;error~pdf/error;status~pdf/extractor/status",
    "output_notices": {
        "text": {
            "description": "Extracted Markdown content (complete mode). Keys: file (str), content (str), pages (null).",
        },
        "page": {
            "description": "Extracted content as a single page (page_by_page mode). Keys: file, page (1), total (1), content (str).",
        },
        "done": {
            "description": "Extraction complete. Keys: file (str), pages (null).",
        },
        "error": {
            "description": "Extraction failed. Keys: file (str), error (str).",
        },
        "status": {
            "description": "Progress message string emitted during extraction.",
        },
    },
})
class PdfExtractorMarkItDownOid(OidComponent):
    """Extracts text from a PDF using MarkItDown; publishes complete markdown content."""

    async def handle_extract(self, notice: str, message: dict) -> None:
        input_file = (message or {}).get("file", "") or self.input_file
        asyncio.create_task(self._extract(input_file))

    async def _extract(self, input_file: str) -> None:
        try:
            await self._notify("status", f"MarkItDown conversion starting — {input_file}")
            loop = asyncio.get_event_loop()
            content = await loop.run_in_executor(None, _convert_markitdown, input_file)
            if self.output_mode == "page_by_page":
                await self._notify("page", {
                    "file":    input_file,
                    "page":    1,
                    "total":   1,
                    "content": content,
                })
                await self._notify("status", "MarkItDown conversion complete — 1 page")
            else:
                await self._notify("text", {
                    "file":    input_file,
                    "content": content,
                    "pages":   None,
                })
                await self._notify("status", "MarkItDown conversion complete")
            await self._notify("done", {"file": input_file, "pages": None})
        except ImportError:
            await self._notify("error", {
                "error": "markitdown not installed — run: pip install 'markitdown[pdf]'",
                "file":  input_file,
            })
        except Exception as exc:
            await self._notify("error", {"error": str(exc), "file": input_file})


def _convert_markitdown(input_file: str) -> str:
    from markitdown import MarkItDown
    return MarkItDown().convert(input_file).text_content
