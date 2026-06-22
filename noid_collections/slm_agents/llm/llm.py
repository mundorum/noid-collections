"""
slm:llm-agent — LLM component backed by Ollama.

The Ollama model can be set at instantiation time via the `model` property.
The `prompt_template` property accepts {input} and {question} placeholders.

Requires: ollama>=0.3  (pip install ollama)
"""
import re

from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "slm:llm-agent",
    "properties": {
        "model":           {"default": "llama3.2"},
        "host":            {"default": "http://localhost:11434"},
        "prompt_template": {"default": "{input}"},
        "temperature":     {"default": 0.1},
    },
    "receive": ["input"],
    "publish": "output~slm/llm/output",
})
class LLMAgentOid(OidComponent):
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

        await self._notify("output", {"content": reply, "model": self.model})

    # ------------------------------------------------------------------

    @staticmethod
    def _render_template(template: str, input_val: str, question: str, message: dict) -> str:
        result = re.sub(re.escape("{input}"), input_val, template, flags=re.IGNORECASE)
        result = re.sub(re.escape("{question}"), question, result, flags=re.IGNORECASE)
        if isinstance(message, dict):
            for key, value in message.items():
                result = re.sub(
                    re.escape(f"{{{key}}}"), str(value), result, flags=re.IGNORECASE
                )
        return result
