"""
lm:ner — Named Entity Recognition component backed by HuggingFace Transformers.

The NER model can be configured at instantiation time via the `model` property.
The pipeline is loaded lazily on the first `text` notice and cached for subsequent calls.

Properties:
  model                — HuggingFace model id (default: "dslim/bert-base-NER")
  aggregation_strategy — "simple" | "first" | "average" | "max" (default: "simple")

Receives: text  → {"content": str} or plain string
Publishes:
  entities → {
      "text":     str,               # original input
      "entities": [
          {"text": str, "entity_type": str,
           "start": int, "end": int, "score": float},
          ...
      ]
  }

Requires: transformers>=4.40, torch  (pip install transformers torch)

Scene usage example:
  {
    "type": "lm:ner",
    "properties": {"model": "samrawal/bert-base-uncased_clinical-ner"},
    "subscribe": "pipeline/text-out~text",
    "publish":   "entities~pipeline/ner-out"
  }
"""
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
    },
    "receive": {
        "text": {
            "description": (
                "Input text to analyze. Payload key: content (str). "
                "Also accepts a plain string."
            ),
        },
    },
    "publish": "entities~slm/ner/output",
    "output_notices": {
        "entities": {
            "description": (
                "Recognized entities. Payload keys: text (str, original input), "
                "entities (list of {text, entity_type, start, end, score})."
            ),
        },
    },
})
class NERAgentOid(OidComponent):
    """Runs a HuggingFace NER pipeline and publishes recognized entities."""

    async def handle_text(self, notice: str, message) -> None:
        text = (
            message.get("content", "")
            if isinstance(message, dict)
            else str(message)
        )
        if not text.strip():
            return

        ner = _get_pipeline(self.model, self.aggregation_strategy)

        raw_entities = ner(text)
        entities = [
            {
                "text":        str(e["word"]),
                "entity_type": str(e["entity_group"]),
                "start":       int(e["start"]),
                "end":         int(e["end"]),
                "score":       float(e.get("score", 0.0)),
            }
            for e in raw_entities
        ]

        await self._notify("entities", {"text": text, "entities": entities})
