"""
Static discovery manifest for mundorum-noid-collections.

Consumers (e.g. the noid authoring server) can read COLLECTIONS to discover
available component groups, their module paths, and the pip extra required to
install their heavy dependencies — without importing any component code.

Each entry in COLLECTIONS is a dict with:
  name         str   — display name shown in the UI
  pip_extra    str|None — pip extra to install (e.g. "lm"), None for base deps
  modules      list[str] — importable Python module paths that register Noid components
  description  str   — short human-readable description
"""

COLLECTIONS: list[dict] = [
    {
        "name": "Basic",
        "pip_extra": None,
        "modules": [
            "noid_collections.basic.console_display.console_display",
        ],
        "description": "Console display and basic I/O utilities.",
    },
    {
        "name": "Data — Text",
        "pip_extra": None,
        "modules": [
            "noid_collections.data.text_source.text_source",
        ],
        "description": "Read plain-text files.",
    },
    {
        "name": "Data — CSV",
        "pip_extra": None,
        "modules": [
            "noid_collections.data.csv_source.csv_source",
        ],
        "description": "Read CSV files row by row.",
    },
    {
        "name": "Data — File Writer",
        "pip_extra": None,
        "modules": [
            "noid_collections.data.file_writer.file_writer",
        ],
        "description": "Write output to files.",
    },
    {
        "name": "Data — SQL",
        "pip_extra": "sql",
        "modules": [
            "noid_collections.data.sql.sql",
        ],
        "description": "SQL queries via DuckDB or SQLite.",
    },
    {
        "name": "PDF — PyMuPDF Extractor",
        "pip_extra": "pdf",
        "modules": [
            "noid_collections.pdf.extractor_pymupdf.extractor_pymupdf",
        ],
        "description": "Extract text from PDFs using PyMuPDF.",
    },
    {
        "name": "PDF — Markitdown Extractor",
        "pip_extra": "pdf",
        "modules": [
            "noid_collections.pdf.extractor_markitdown.extractor_markitdown",
        ],
        "description": "Extract Markdown from PDFs using markitdown.",
    },
    {
        "name": "PDF — OCR",
        "pip_extra": "pdf",
        "modules": [
            "noid_collections.pdf.ocr.ocr",
        ],
        "description": "OCR scanned PDFs via ocrmypdf.",
    },
    {
        "name": "PDF — Postprocessor",
        "pip_extra": "pdf",
        "modules": [
            "noid_collections.pdf.postprocessor.postprocessor",
        ],
        "description": "Clean up and spell-correct extracted PDF text.",
    },
    {
        "name": "Logic — Prolog",
        "pip_extra": "prolog",
        "modules": [
            "noid_collections.logic.prolog.prolog",
        ],
        "description": "Prolog queries via pyswip.",
    },
    {
        "name": "LM Agents — LM",
        "pip_extra": "lm",
        "modules": [
            "noid_collections.lm_agents.lm.lm",
        ],
        "description": "LLM agent backed by Ollama.",
    },
    {
        "name": "LM Agents — NER",
        "pip_extra": "ner",
        "modules": [
            "noid_collections.lm_agents.ner.ner",
        ],
        "description": "Named-entity recognition via HuggingFace Transformers.",
    },
]
