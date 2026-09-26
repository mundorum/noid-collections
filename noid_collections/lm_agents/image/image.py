"""
lm:image-agent — Text-to-image agent with a parametrizable prompt and a pluggable model.

Mirrors lm:lm-agent: the prompt is rendered from `prompt_template` ({{input}},
{{question}}, {{key}}, {{row.name}}) and the same single-item / CSV modes apply, but
the reply is an image. Images are saved as PNG files under `output_dir`; the published
messages carry their paths (and, with `embed`, base64 data URLs for UI consumers).

The model sits behind a backend (see backends.py), selected by the `backend` property:
  janus     — DeepSeek Janus-Pro via transformers (default: deepseek-community/Janus-Pro-1B)
  diffusers — any diffusers text-to-image pipeline (default: stabilityai/sd-turbo)
  "package.module:ClassName" — a custom ImageBackend subclass
The model is loaded lazily on the first notice, cached per process, and runs in a
thread executor so it does not block the event loop.

Requires: pip install "mundorum-noid-collections[image]"

Scene usage example (chain after lm:lm-agent to have an LLM write the visual prompt):
  {
    "type": "lm:image-agent",
    "properties": {
      "prompt_template": "{{input}}, cartoon illustration, flat colors, bold outlines",
      "output_dir": "output/images",
      "seed": 42
    },
    "subscribe": "pipeline/text~input",
    "publish":   "document~pipeline/image"
  }
"""
import asyncio
import base64
import copy
import io
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from noid.core.component import Noid, OidComponent

from noid_collections.lm_agents.prompt_template import render_prompt
from noid_collections.lm_agents.image.backends import get_backend

logger = logging.getLogger(__name__)


@Noid.component({
    "id": "lm:image-agent",
    "name": "Image Agent",
    "description": (
        "Generates images from a rendered prompt template with a pluggable text-to-image "
        "model (Janus-Pro by default), saving PNG files and publishing their paths."
    ),
    "properties": {
        "backend": {
            "default": "janus",
            "description": (
                "Image backend: 'janus', 'diffusers', or a custom ImageBackend "
                "subclass as 'package.module:ClassName'."
            ),
        },
        "model": {
            "default": "",
            "description": (
                "Model id for the backend (e.g. a Hugging Face repo id). "
                "Empty uses the backend default."
            ),
        },
        "device": {
            "default": "auto",
            "description": "'auto', 'cpu', or 'cuda'. 'auto' uses a GPU only if it has enough memory.",
        },
        "dtype": {
            "default": "auto",
            "description": "Torch dtype name ('bfloat16', 'float16', 'float32') or 'auto' for the backend default.",
        },
        "prompt_template": {
            "default": "{{input}}",
            "kind": "text",
            "description": (
                "Prompt template. Supports {{input}}, {{question}}, flat message keys "
                "as {{key}}, and dot-separated paths into nested fields as {{row.name}}. "
                "Append a style here, e.g. '{{input}}, simple colored drawing, white background'."
            ),
        },
        "num_images": {
            "default": 1,
            "description": "Number of images generated per prompt (one batch).",
        },
        "guidance_scale": {
            "description": (
                "Classifier-free guidance scale; higher follows the prompt more closely. "
                "Unset uses the backend default (Janus: 5.0)."
            ),
        },
        "seed": {
            "description": "Random seed for reproducible images. Unset for random.",
        },
        "options": {
            "default": "",
            "kind": "text",
            "description": (
                "Backend-specific options as a JSON object, e.g. {\"temperature\": 1.0} for "
                "janus or {\"num_inference_steps\": 1, \"width\": 512} for diffusers."
            ),
        },
        "output_dir": {
            "default": "output/images",
            "kind": "resource",
            "description": "Directory where generated PNG files are written (created if missing).",
        },
        "embed": {
            "default": False,
            "description": "Also include each image as a base64 data URL (data_url) in the output.",
        },
        "csv_field": {
            "description": (
                "Field name added directly below `row` (no dotted paths). Setting this "
                "property switches the component into CSV mode: `schema` and `row` "
                "notices are handled, and the `document` output carries the enriched "
                "input dict instead of {content, images, ...}. The field holds the image "
                "path, or a JSON list of paths when num_images > 1. Must not be set for "
                "plain, non-CSV usage — it has no default value."
            ),
        },
        "error_mode": {
            "default": "fallback_value",
            "description": "Behavior when generation fails: 'fallback_value' or 'propagate'.",
        },
        "error_fallback_value": {
            "default": "IMAGE_ERROR",
            "description": "Value written to the output field when error_mode is 'fallback_value' and generation fails.",
        },
    },
    "receive": {
        "input": {
            "description": (
                "Triggers image generation on a single item. Payload keys: content (str), "
                "question (str, optional). Also accepts a plain string."
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
    "publish": "document~image/document;schema~image/schema;row~image/row",
    "output_notices": {
        "document": {
            "description": (
                "Generated image(s) for a single item. When csv_field is set: enriched "
                "input dict. Otherwise: {content (str, path of the first image or the "
                "fallback value), images (list of {file, data_url?}), prompt (str), "
                "model (str), backend (str)}."
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
                "Input row with the image path(s) added under row[csv_field]. "
                "label/index are passed through unchanged."
            ),
        },
    },
})
class ImageAgentOid(OidComponent):
    """Generates images from a rendered prompt through a pluggable text-to-image backend."""

    async def handle_input(self, notice: str, message) -> None:
        content = message.get("content", "") if isinstance(message, dict) else str(message)
        result = await self._generate(message, _slugify(content))

        csv_field = getattr(self, "csv_field", "")
        if csv_field and isinstance(message, dict):
            output = copy.deepcopy(message)
            output[csv_field] = self._field_value(result["images"])
            await self._notify("document", output)
        else:
            images = result["images"]
            await self._notify("document", {
                "content": self._field_value(None if images is None else images[:1]),
                "images":  images or [],
                "prompt":  result["prompt"],
                "model":   result["model"],
                "backend": self.backend,
            })

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
        index = envelope.get("index")
        tag = f"row{index}" if index is not None else "row"
        result = await self._generate(message, tag)

        row = copy.deepcopy(envelope.get("row", {}))
        row[csv_field] = self._field_value(result["images"])
        envelope["row"] = row
        await self._notify("row", envelope)

    # ------------------------------------------------------------------

    async def _generate(self, message, tag: str) -> dict:
        """Render the prompt, generate and save images.

        Returns {prompt, model, images}; images is None when generation failed
        and error_mode is 'fallback_value'.
        """
        prompt = render_prompt(self.prompt_template, message)
        model = self.model or ""
        try:
            options = _parse_options(getattr(self, "options", ""))
            backend = await asyncio.to_thread(
                get_backend, self.backend, self.model, self.device, self.dtype
            )
            model = backend.model_id
            images = await asyncio.to_thread(
                backend.generate,
                prompt,
                num_images=int(self.num_images),
                seed=_optional(getattr(self, "seed", None), int),
                guidance_scale=_optional(getattr(self, "guidance_scale", None), float),
                options=options,
            )
            records = await asyncio.to_thread(self._save_images, images, tag or "image")
        except Exception as exc:
            if getattr(self, "error_mode", "fallback_value") == "propagate":
                raise RuntimeError(
                    f"Image generation failed with backend {self.backend!r}: {exc}"
                ) from exc
            logger.warning(
                "Image generation failed with backend %r, model %r: %s",
                self.backend, model, exc,
            )
            records = None
        return {"prompt": prompt, "model": model, "images": records}

    def _save_images(self, images: list, tag: str) -> list:
        """Write images as PNG files (blocking; runs in a thread)."""
        out_dir = Path(self.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        records = []
        for i, image in enumerate(images):
            path = out_dir / f"{stamp}-{tag}-{i}.png"
            image.save(path, format="PNG")
            record = {"file": str(path)}
            if getattr(self, "embed", False):
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                record["data_url"] = (
                    "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
                )
            records.append(record)
        return records

    def _field_value(self, records) -> str:
        """Single path, JSON list of paths, or the fallback value on failure."""
        if records is None:
            return getattr(self, "error_fallback_value", "IMAGE_ERROR")
        paths = [r["file"] for r in records]
        if len(paths) == 1:
            return paths[0]
        return json.dumps(paths)


def _parse_options(options) -> dict:
    if isinstance(options, dict):
        return options
    if not options or not str(options).strip():
        return {}
    parsed = json.loads(options)
    if not isinstance(parsed, dict):
        raise ValueError(f"options must be a JSON object, got {options!r}")
    return parsed


def _optional(value, cast):
    return None if value is None or value == "" else cast(value)


def _slugify(text: str, max_len: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:max_len]
