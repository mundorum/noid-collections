"""
lm:lm-agent — LM component backed by Ollama.

The Ollama model can be set at instantiation time via the `model` property.
The `prompt_template` property accepts {input}, {question}, and dotted-path
placeholders like {row.name} that resolve into nested message fields.

Requires: ollama>=0.3  (pip install ollama)
"""
import copy
import re

from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "lm:lm-agent",
    "name": "LM Agent",
    "description": "Calls an Ollama LLM with a rendered prompt template and publishes the reply.",
    "properties": {
        "model": {
            "default": "llama3.2",
            "description": "Ollama model name to use for inference.",
        },
        "host": {
            "default": "http://localhost:11434",
            "description": "Ollama server URL.",
        },
        "prompt_template": {
            "default": "{input}",
            "kind": "text",
            "description": (
                "Prompt template. Supports {input}, {question}, flat message keys "
                "as {key}, and dot-separated paths into nested fields as {row.name}."
            ),
        },
        "temperature": {
            "default": 0.1,
            "description": "Sampling temperature (0 = deterministic, higher = more creative).",
        },
        "csv_field": {
            "description": (
                "Field name added directly below `row` (no dotted paths). Setting this "
                "property switches the component into CSV mode: `schema` and `row` "
                "notices are handled, and the `document` output carries the enriched "
                "input dict instead of {content, model}. Must not be set for plain, "
                "non-CSV usage — it has no default value."
            ),
        },
    },
    "receive": {
        "input": {
            "description": (
                "Triggers LLM inference on a single item. Payload keys: content (str), "
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
    "publish": "document~lm/document;schema~lm/schema;row~lm/row",
    "output_notices": {
        "document": {
            "description": (
                "LLM reply for a single item. When csv_field is set: enriched input dict. "
                "Otherwise: {content (str), model (str)}."
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
                "Input row with the LLM reply added under row[csv_field]. "
                "label/index are passed through unchanged."
            ),
        },
    },
})
class LMAgentOid(OidComponent):
    """Calls an Ollama model with a rendered prompt and publishes the reply."""

    async def handle_input(self, notice: str, message: dict) -> None:
        reply = await self._infer(message)

        csv_field = getattr(self, "csv_field", "")
        if csv_field and isinstance(message, dict):
            output = copy.deepcopy(message)
            output[csv_field] = reply
            await self._notify("document", output)
        else:
            await self._notify("document", {"content": reply, "model": self.model})

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

        reply = await self._infer(message)

        envelope = dict(message) if isinstance(message, dict) else {}
        row = copy.deepcopy(envelope.get("row", {}))
        row[csv_field] = reply
        envelope["row"] = row
        await self._notify("row", envelope)

    # ------------------------------------------------------------------

    async def _infer(self, message) -> str:
        try:
            import ollama
        except ImportError as exc:
            raise RuntimeError(
                "ollama package is required: pip install ollama"
            ) from exc

        content = message.get("content", "") if isinstance(message, dict) else str(message)
        question = message.get("question", "") if isinstance(message, dict) else ""

        prompt = self._render_template(self.prompt_template, content, question, message)

        client = ollama.Client(host=self.host)
        response = client.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": self.temperature},
        )
        return response["message"]["content"]

    @staticmethod
    def _render_template(template: str, input_val: str, question: str, message: dict) -> str:
        result = re.sub(re.escape("{input}"), input_val, template, flags=re.IGNORECASE)
        result = re.sub(re.escape("{question}"), question, result, flags=re.IGNORECASE)
        if isinstance(message, dict):
            def _replace(match: re.Match) -> str:
                key = match.group(1)
                if key in message:
                    return str(message[key])
                return _resolve_path(message, key)
            result = re.sub(r"\{([^}]+)\}", _replace, result)
        return result


def _resolve_path(obj: dict, path: str) -> str:
    """Walk a dot-separated path in a nested dict; return str value or empty string."""
    current = obj
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return ""
        current = current[part]
    return str(current)
