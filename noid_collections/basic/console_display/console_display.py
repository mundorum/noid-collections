"""
basic:console-display — prints received messages to stdout.

A sink component for pipeline development and debugging.  Receives a `show`
notice and writes a formatted representation of the message to the console.

Properties:
  label      — prefix printed before each message (default: "")
  show_topic — also print the originating bus topic (default: False)
  pretty     — JSON-pretty-print dict payloads (default: True)
  field      — if set, display only this key from a dict payload (default: "")

Scene usage example:
  {
    "type": "basic:console-display",
    "properties": {"label": "LLM Output", "field": "content"},
    "subscribe": "pipeline/llm-out~show"
  }
"""
import json

from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "basic:console-display",
    "name": "Console Display",
    "description": (
        "Prints received messages to stdout. "
        "A sink component for pipeline development and debugging."
    ),
    "properties": {
        "label": {
            "default": "",
            "description": "Prefix string printed before each message.",
        },
        "show_topic": {
            "default": False,
            "description": "Also print the triggering notice name after the label.",
        },
        "pretty": {
            "default": True,
            "description": "JSON-pretty-print dict payloads (2-space indent).",
        },
        "field": {
            "default": "",
            "description": "If set, display only this key from a dict payload.",
        },
    },
    "receive": {
        "show": {
            "description": "Message to display. Accepts any payload type.",
        },
    },
    "publish": "output~console/output",
    "output_notices": {
        "output": {
            "description": "Re-emits the received message unchanged, enabling downstream chaining.",
        },
    },
})
class ConsoleDisplayOid(OidComponent):
    """Prints every received message to stdout."""

    async def handle_show(self, notice: str, message) -> None:
        prefix = f"[{self.label}] " if self.label else ""
        if self.show_topic:
            prefix = f"{prefix}({notice}) "

        payload = message[self.field] if (self.field and isinstance(message, dict) and self.field in message) else message

        if isinstance(payload, dict) and self.pretty:
            body = json.dumps(payload, indent=2, ensure_ascii=False)
        else:
            body = str(payload)

        print(f"{prefix}{body}")
        await self._notify("output", message)
