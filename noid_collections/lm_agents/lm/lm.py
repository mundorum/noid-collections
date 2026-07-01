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
        "append_field": {
            "default": "",
            "description": (
                "Dot-separated path (e.g. 'row.comment') where the LM reply is inserted "
                "into the input message. When set, the output is the enriched input dict. "
                "When empty, the output is {content, model}."
            ),
        },
    },
    "receive": {
        "input": {
            "description": (
                "Triggers LLM inference. Payload keys: content (str), "
                "question (str, optional). Also accepts a plain string."
            ),
        },
    },
    "publish": "output~lm/output",
    "output_notices": {
        "output": {
            "description": (
                "LLM reply. When append_field is set: enriched input dict. "
                "Otherwise: {content (str), model (str)}."
            ),
        },
    },
})
class LMAgentOid(OidComponent):
    """Calls an Ollama model with a rendered prompt and publishes the reply."""

    async def handle_input(self, notice: str, message: dict) -> None:
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
        reply = response["message"]["content"]

        append_field = getattr(self, "append_field", "")
        if append_field and isinstance(message, dict):
            output = copy.deepcopy(message)
            _set_path(output, append_field, reply)
            await self._notify("output", output)
        else:
            await self._notify("output", {"content": reply, "model": self.model})

    # ------------------------------------------------------------------

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


def _set_path(obj: dict, path: str, value) -> None:
    """Set a value at a dot-separated path in a nested dict, creating dicts as needed."""
    parts = path.split(".")
    current = obj
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value
