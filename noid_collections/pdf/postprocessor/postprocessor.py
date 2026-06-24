"""
pdf:postprocessor — clean up and optionally convert PDF-extracted text.

Accepts text produced by pdf:extractor-pymupdf (page-marker format) or
pdf:extractor-markitdown (flowing Markdown), applies the appropriate cleanup
pipeline, and republishes the result.

Input can arrive in two forms — the component handles both transparently:
  • complete  — one `text` notice carrying the full content, then `done`
  • page_by_page — N `page` notices (accumulated internally), then `done`

The `source` property tells the component which cleanup pipeline to apply:
  • "pymupdf"    — input contains "--- PAGE N ---" markers (extractor-pymupdf)
  • "markitdown" — input is flowing Markdown (extractor-markitdown)

The `format` property sets the desired output format:
  • "text"     — plain text (hyphen joining, noise removal, optional spell check)
  • "markdown" — Markdown with heading detection and page separators

output_mode controls how the result is dispatched:
  • "complete"     — one `text` notice, then `done`
  • "page_by_page" — N `page` notices (split on page markers), then `done`

Properties:
    source        — "pymupdf" (default) or "markitdown"
    format        — "text" (default) or "markdown"
    output_mode   — "complete" (default) or "page_by_page"
    use_spellcheck — apply SymSpell spell correction when available (default: True)

Received notices:
    text — {"content": "...", ...}   complete input
    page — {"content": "...", ...}   one page of page_by_page input (accumulated)
    done — {}                        signals end-of-input; triggers processing

Published notices:
    text  — {"content": "...", "file": "..."}              (complete output_mode)
    page  — {"page": N, "total": N, "content": "...", "file": "..."}
    done  — {"file": "..."}                                (always)
    error — {"error": "..."}

Scene usage:
    {
      "type": "pdf:postprocessor",
      "id":   "postproc",
      "properties": {
        "source": "pymupdf",
        "format": "markdown"
      },
      "subscribe": "pipeline/text~text;pipeline/done~done",
      "publish":   "text~pipeline/clean;done~pipeline/clean-done"
    }
"""
import re
from typing import List, Tuple

from noid.core.component import Noid, OidComponent


# ── Spell-check helpers (optional dependency) ─────────────────────────────────

try:
    from symspellpy import SymSpell, Verbosity
    import pkg_resources
    _SYMSPELL_AVAILABLE = True
except ImportError:
    _SYMSPELL_AVAILABLE = False

_sym_spell = None


def _load_sym_spell():
    global _sym_spell
    if _sym_spell is not None:
        return _sym_spell
    try:
        ss = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
        dict_path = pkg_resources.resource_filename(
            "symspellpy", "frequency_dictionary_en_82_765.txt"
        )
        ss.load_dictionary(dict_path, term_index=0, count_index=1)
        _sym_spell = ss
    except Exception:
        pass
    return _sym_spell


def _correct_word(word: str, sym_spell) -> str:
    if not word or len(word) <= 2 or word[0].isupper() or not word.isalpha():
        return word
    suggestions = sym_spell.lookup(word, Verbosity.CLOSEST, max_edit_distance=1)
    if suggestions and suggestions[0].distance > 0:
        return suggestions[0].term
    return word


def _apply_spell_correction(text: str, stats: dict) -> str:
    if not _SYMSPELL_AVAILABLE:
        return text
    sym_spell = _load_sym_spell()
    if not sym_spell:
        return text
    lines = []
    for line in text.split("\n"):
        tokens = re.split(r"(\W+)", line)
        new_tokens = []
        for tok in tokens:
            if tok.isalpha():
                corrected = _correct_word(tok, sym_spell)
                if corrected != tok:
                    stats["spell_corrections"] += 1
                new_tokens.append(corrected)
            else:
                new_tokens.append(tok)
        lines.append("".join(new_tokens))
    return "\n".join(lines)


def _classify_heading(stripped: str) -> str:
    """Classify a stripped line as 'h1', 'h2', or 'body' using all-caps heuristic."""
    if not stripped:
        return "body"
    alpha = [c for c in stripped if c.isalpha()]
    if len(alpha) < 3:
        return "body"
    upper_ratio = sum(1 for c in alpha if c.isupper()) / len(alpha)
    if upper_ratio < 0.80:
        return "body"
    words = stripped.split()
    if 1 <= len(words) <= 4 and len(stripped) <= 40:
        return "h1"
    if 5 <= len(words) <= 8 and len(stripped) <= 60:
        return "h2"
    return "body"


# ── Cleanup pipelines ─────────────────────────────────────────────────────────

def postprocess_text(text: str, use_spellcheck: bool = True) -> Tuple[str, dict]:
    """Clean up OCR plain text (PyMuPDF page-marked format)."""
    stats = {
        "hyphen_joins": 0,
        "noise_lines_removed": 0,
        "spell_corrections": 0,
        "spellcheck_available": _SYMSPELL_AVAILABLE and use_spellcheck,
    }

    def _join(m):
        stats["hyphen_joins"] += 1
        return m.group(1) + m.group(2)

    text = re.sub(r"(\w+)-\n(\w+)", _join, text)

    lines, cleaned = text.split("\n"), []
    for line in lines:
        s = line.strip()
        if not s or re.match(r"^---\s*PAGE", s):
            cleaned.append(line)
            continue
        alpha_count = sum(1 for c in s if c.isalpha())
        if len(s) < 15 and alpha_count < len(s) * 0.4:
            stats["noise_lines_removed"] += 1
            continue
        cleaned.append(line)
    text = "\n".join(cleaned)

    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    if use_spellcheck and _SYMSPELL_AVAILABLE:
        text = _apply_spell_correction(text, stats)

    return text, stats


def text_to_markdown(text: str, use_spellcheck: bool = True) -> Tuple[str, dict]:
    """Convert PyMuPDF page-marked plain text to Markdown."""
    text, stats = postprocess_text(text, use_spellcheck=use_spellcheck)
    stats["headings_detected"] = 0

    output = []
    for line in text.split("\n"):
        s = line.strip()
        m = re.match(r"^---\s*PAGE\s+(\d+)\s*---\s*$", s)
        if m:
            output.extend(["", "---", "", f"*— Page {m.group(1)} —*", ""])
            continue
        cls = _classify_heading(s)
        if cls == "h1":
            stats["headings_detected"] += 1
            output.extend(["", f"# {s.title()}", ""])
        elif cls == "h2":
            stats["headings_detected"] += 1
            output.extend(["", f"## {s.title()}", ""])
        else:
            output.append(line)

    return "\n".join(output), stats


def postprocess_markdown(text: str, use_spellcheck: bool = True) -> Tuple[str, dict]:
    """Clean up flowing Markdown text produced by MarkItDown."""
    stats = {
        "hyphen_joins": 0,
        "noise_lines_removed": 0,
        "spell_corrections": 0,
        "spellcheck_available": _SYMSPELL_AVAILABLE and use_spellcheck,
        "headings_detected": 0,
    }

    def _join(m):
        stats["hyphen_joins"] += 1
        return m.group(1) + m.group(2)

    text = re.sub(r"(\w+)-\n(\w+)", _join, text)

    lines, cleaned = text.split("\n"), []
    for line in lines:
        s = line.strip()
        if not s:
            cleaned.append(line)
            continue
        alpha_count = sum(1 for c in s if c.isalpha())
        if len(s) < 15 and alpha_count < len(s) * 0.4:
            stats["noise_lines_removed"] += 1
            continue
        cleaned.append(line)
    text = "\n".join(cleaned)

    output = []
    for line in text.split("\n"):
        s = line.strip()
        cls = _classify_heading(s)
        if cls == "h1":
            stats["headings_detected"] += 1
            output.extend(["", f"# {s.title()}", ""])
        elif cls == "h2":
            stats["headings_detected"] += 1
            output.extend(["", f"## {s.title()}", ""])
        else:
            output.append(line)
    text = "\n".join(output)

    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    if use_spellcheck and _SYMSPELL_AVAILABLE:
        result_lines = []
        for line in text.split("\n"):
            if line.startswith("#"):
                result_lines.append(line)
                continue
            result_lines.append(line)
        text = "\n".join(result_lines)
        text = _apply_spell_correction(text, stats)

    return text, stats


# ── Component ─────────────────────────────────────────────────────────────────

@Noid.component({
    "id": "pdf:postprocessor",
    "name": "PDF Postprocessor",
    "description": (
        "Cleans up PDF-extracted text and optionally converts it to Markdown, "
        "then republishes the result. Supports both complete and page-by-page input/output."
    ),
    "properties": {
        "source": {
            "default": "pymupdf",
            "description": "Input format: pymupdf (page-marker text) or markitdown (flowing Markdown).",
        },
        "format": {
            "default": "text",
            "description": "Output format: text (plain) or markdown.",
        },
        "output_mode": {
            "default": "complete",
            "description": "Dispatch mode: complete (one text notice) or page_by_page (one page notice per page).",
        },
        "use_spellcheck": {
            "default": True,
            "description": "Apply SymSpell spell correction when the symspellpy package is installed.",
        },
    },
    "receive": {
        "text": {
            "description": "Complete extracted text. Payload keys: content (str), file (str, optional).",
        },
        "page": {
            "description": "One page of extracted text, accumulated until done. Payload keys: content (str), file (str, optional).",
        },
        "done": {
            "description": "Signals end of input; triggers postprocessing and publishes results.",
        },
    },
    "publish": (
        "text~pdf/processed/text"
        ";page~pdf/processed/page"
        ";done~pdf/processed/done"
        ";error~pdf/processed/error"
        ";status~pdf/postprocessor/status"
    ),
    "output_notices": {
        "text": {
            "description": "Processed full text (complete mode). Keys: file (str), content (str).",
        },
        "page": {
            "description": "One processed page (page_by_page mode). Keys: file, page (int), total (int), content (str).",
        },
        "done": {
            "description": "All output published. Keys: file (str), pages (int, page_by_page mode only).",
        },
        "error": {
            "description": "Postprocessing failed. Key: error (str).",
        },
        "status": {
            "description": "Progress message string emitted during processing.",
        },
    },
})
class PdfPostprocessorOid(OidComponent):
    """Accumulates extracted pages, applies cleanup, and republishes the result."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._buffer: List[str] = []
        self._source_file: str = ""

    async def handle_text(self, notice: str, message: dict) -> None:
        self._source_file = (message or {}).get("file", "") or self._source_file
        self._buffer.append((message or {}).get("content", ""))
        await self._notify("status", "Post-processor received complete text")

    async def handle_page(self, notice: str, message: dict) -> None:
        self._source_file = (message or {}).get("file", "") or self._source_file
        self._buffer.append((message or {}).get("content", ""))
        await self._notify("status", f"Post-processor buffering page {len(self._buffer)}")

    async def handle_done(self, notice: str, message: dict) -> None:
        n = len(self._buffer)
        await self._notify("status", f"Post-processing {n} segment(s)...")
        full_text = "\n\n".join(self._buffer)
        self._buffer = []
        try:
            processed, _ = self._apply_postprocess(full_text)
            await self._publish_result(processed)
        except Exception as exc:
            await self._notify("error", {"error": str(exc)})

    def _apply_postprocess(self, text: str) -> Tuple[str, dict]:
        spellcheck = self.use_spellcheck
        src, fmt = self.source, self.format
        if src == "markitdown":
            if fmt == "markdown":
                return postprocess_markdown(text, use_spellcheck=spellcheck)
            return postprocess_text(text, use_spellcheck=spellcheck)
        # pymupdf — page-marked text
        if fmt == "markdown":
            return text_to_markdown(text, use_spellcheck=spellcheck)
        return postprocess_text(text, use_spellcheck=spellcheck)

    async def _publish_result(self, text: str) -> None:
        if self.output_mode == "page_by_page":
            pages = self._split_pages(text)
            total = len(pages)
            for i, content in enumerate(pages, 1):
                await self._notify("status", f"Post-processing: publishing page {i} / {total}")
                await self._notify("page", {
                    "file":    self._source_file,
                    "page":    i,
                    "total":   total,
                    "content": content,
                })
            await self._notify("status", f"Post-processing complete — {total} pages")
            await self._notify("done", {
                "file":  self._source_file,
                "pages": total,
            })
        else:
            await self._notify("text", {
                "file":    self._source_file,
                "content": text,
            })
            await self._notify("status", "Post-processing complete")
            await self._notify("done", {"file": self._source_file})

    def _split_pages(self, text: str) -> List[str]:
        if self.format == "markdown":
            # Markdown page separator: blank line + --- + blank line
            parts = re.split(r"\n---\n", text)
        else:
            # Plain text page markers: --- PAGE N ---
            parts = re.split(r"\n*--- PAGE \d+ ---\n*", text)
        return [p.strip() for p in parts if p.strip()]
