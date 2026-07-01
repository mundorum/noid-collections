"""
lm:ner — Named Entity Recognition component backed by HuggingFace Transformers.

The NER model can be configured at instantiation time via the `model` property.
The pipeline is loaded lazily on the first `text` notice and cached for subsequent calls.

Properties:
  model                — HuggingFace model id (default: "dslim/bert-base-NER")
  aggregation_strategy — "simple" | "first" | "average" | "max" (default: "simple")
  text_field           — key holding the text to analyze, in the flat message or
                          inside `row` (default: "content")
  csv_field            — field name added below `row` in CSV mode; no default,
                          setting it switches the component into CSV mode

Receives:
  text   → {"content": str} or plain string (single item)
  schema → {"columns": [...]} (CSV mode only)
  row    → {"row": {...}} (CSV mode only)

Publishes:
  document → {
      "text":     str,               # original input
      "entities": [
          {"text": str, "entity_type": str,
           "start": int, "end": int, "score": float},
          ...
      ]
  }
  (or the enriched input dict, with entities serialized as JSON, when csv_field is set)
  schema → input schema with csv_field appended to columns
  row    → input row with entities (serialized as JSON) added under row[csv_field]

Requires: transformers>=4.40, torch  (pip install transformers torch)

Scene usage example:
  {
    "type": "lm:ner",
    "properties": {"model": "samrawal/bert-base-uncased_clinical-ner"},
    "subscribe": "pipeline/text-out~text",
    "publish":   "document~pipeline/ner-out"
  }
"""
import copy
import json

from noid.core.component import Noid, OidComponent

_pipeline_cache: dict = {}


def _get_pipeline(model: str, aggregation_strategy: str):
    """Load (or return cached) transformers NER pipeline for the given model."""
    try:
        from transformers import pipeline
    except ImportError as exc:
        raise RuntimeError(
            "transformers package is required: pip install transformers torch"
        ) from exc

    key = (model, aggregation_strategy)
    if key not in _pipeline_cache:
        _pipeline_cache[key] = pipeline(
            "ner",
            model=model,
            aggregation_strategy=aggregation_strategy,
        )
    return _pipeline_cache[key]


@Noid.component({
    "id": "lm:ner",
    "name": "NER Agent",
    "description": (
        "Runs a HuggingFace NER pipeline on input text and publishes recognized entities. "
        "The pipeline is loaded lazily on the first notice and cached for subsequent calls."
    ),
    "properties": {
        "model": {
            "default": "dslim/bert-base-NER",
            "description": "HuggingFace model id for the NER pipeline.",
        },
        "aggregation_strategy": {
            "default": "simple",
            "description": "Entity aggregation strategy: simple, first, average, or max.",
        },
        "text_field": {
            "default": "content",
            "description": (
                "Key holding the text to analyze — read from the flat message in "
                "single-item mode, or from `row` in CSV mode."
            ),
        },
        "csv_field": {
            "description": (
                "Field name added directly below `row` (no dotted paths). Setting this "
                "property switches the component into CSV mode: `schema` and `row` "
                "notices are handled, and the `document` output carries the enriched "
                "input dict (entities serialized as JSON) instead of {text, entities}. "
                "Must not be set for plain, non-CSV usage — it has no default value."
            ),
        },
    },
    "receive": {
        "text": {
            "description": (
                "Input text to analyze on a single item. Payload key: text_field (str, "
                "default key 'content'). Also accepts a plain string."
            ),
        },
        "schema": {
            "description": (
                "CSV column schema. Payload keys: label (optional), columns (list of str). "
                "Ignored if `csv_field` is not set."
            ),
        },
        "row": {
            "description": (
                "One CSV row. Payload keys: label (optional), index (optional), "
                "row (dict). Ignored if `csv_field` is not set."
            ),
        },
    },
    "publish": "document~ner/document;schema~ner/schema;row~ner/row",
    "output_notices": {
        "document": {
            "description": (
                "Recognized entities for a single item. When csv_field is not set: "
                "{text (str), entities (list of {text, entity_type, start, end, score})}. "
                "When set: enriched input dict with entities serialized as a JSON string."
            ),
        },
        "schema": {
            "description": (
                "Input schema with csv_field appended to columns. "
                "Emitted in response to the schema notice."
            ),
        },
        "row": {
            "description": (
                "Input row with the recognized entities (serialized as JSON) added "
                "under row[csv_field]. label/index are passed through unchanged."
            ),
        },
    },
})
class NERAgentOid(OidComponent):
    """Runs a HuggingFace NER pipeline and publishes recognized entities."""

    async def handle_text(self, notice: str, message) -> None:
        text = (
            message.get(self.text_field, "")
            if isinstance(message, dict)
            else str(message)
        )
        if not text.strip():
            return

        entities = self._compute_entities(text)

        csv_field = getattr(self, "csv_field", "")
        if csv_field and isinstance(message, dict):
            output = copy.deepcopy(message)
            output[csv_field] = json.dumps(entities)
            await self._notify("document", output)
        else:
            await self._notify("document", {"text": text, "entities": entities})

    async def handle_schema(self, notice: str, message: dict) -> None:
        csv_field = getattr(self, "csv_field", "")
        if not csv_field:
            return
        envelope = dict(message) if isinstance(message, dict) else {}
        columns = list(envelope.get("columns", []))
        if csv_field not in columns:
            columns.append(csv_field)
        envelope["columns"] = columns
        await self._notify("schema", envelope)

    async def handle_row(self, notice: str, message: dict) -> None:
        csv_field = getattr(self, "csv_field", "")
        if not csv_field:
            return

        envelope = dict(message) if isinstance(message, dict) else {}
        row = copy.deepcopy(envelope.get("row", {}))
        text = str(row.get(self.text_field, ""))
        entities = self._compute_entities(text) if text.strip() else []
        row[csv_field] = json.dumps(entities)
        envelope["row"] = row
        await self._notify("row", envelope)

    # ------------------------------------------------------------------

    def _compute_entities(self, text: str) -> list:
        ner = _get_pipeline(self.model, self.aggregation_strategy)
        raw_entities = ner(text)
        return [
            {
                "text":        str(e["word"]),
                "entity_type": str(e["entity_group"]),
                "start":       int(e["start"]),
                "end":         int(e["end"]),
                "score":       float(e.get("score", 0.0)),
            }
            for e in raw_entities
        ]
