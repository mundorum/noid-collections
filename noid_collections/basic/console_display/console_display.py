"""
slm:console-display — prints received messages to stdout.

A sink component for pipeline development and debugging.  Receives a `show`
notice and writes a formatted representation of the message to the console.

Properties:
  label      — prefix printed before each message (default: "")
  show_topic — also print the originating bus topic (default: False)
  pretty     — JSON-pretty-print dict payloads (default: True)

Scene usage example:
  {
    "type": "slm:console-display",
    "properties": {"label": "LLM Output"},
    "subscribe": "pipeline/llm-out~show"
  }
"""
import json

from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "slm:console-display",
    "properties": {
        "label":       {"default": ""},
        "show_topic":  {"default": False},
        "pretty":      {"default": True},
    },
    "receive": ["show"],
})
class ConsoleDisplayOid(OidComponent):
    """Prints every received message to stdout."""

    def handle_show(self, notice: str, message) -> None:
        prefix = f"[{self.label}] " if self.label else ""
        if self.show_topic:
            prefix = f"{prefix}({notice}) "

        if isinstance(message, dict) and self.pretty:
            body = json.dumps(message, indent=2, ensure_ascii=False)
        else:
            body = str(message)

        print(f"{prefix}{body}")
