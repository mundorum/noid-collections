"""
data:text-source — publishes static text content as a message on the bus.

The `text` property holds the content.  Whenever a `trigger` notice is received
(or at start if `auto_publish` is True), the component publishes a `text` notice
with a dict containing the label and content.

Scene usage example:
    {
      "type": "data:text-source",
      "properties": {"label": "intro", "text": "The patient has fever and cough."},
      "subscribe": "pipeline/start~trigger",
      "publish":   "text~pipeline/text-out"
    }
"""
import asyncio

from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "data:text-source",
    "properties": {
        "text":         {"default": ""},
        "label":        {"default": "text"},
        "auto_publish": {"default": False},
    },
    "receive": ["trigger"],
    "publish": "text~slm/text/output;done~slm/text/done",
})
class TextSourceOid(OidComponent):
    """Publishes its `text` property as a message whenever triggered."""

    async def start(self) -> None:
        await super().start()
        if self.auto_publish:
            # Defer by one event-loop tick so all other components finish
            # starting (and wiring their subscriptions) before the message fires.
            asyncio.create_task(self._publish_text())

    async def handle_trigger(self, notice: str, message: dict) -> None:
        await self._publish_text()

    async def _publish_text(self) -> None:
        await self._notify("text", {"label": self.label, "content": self.text})
        await self._notify("done", {})
