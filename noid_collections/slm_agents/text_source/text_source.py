"""
slm:text-source — publishes static text content as a message on the bus.

The `text` property holds the content.  Whenever a `trigger` notice is received
(or at start if `auto_publish` is True), the component publishes a `text` notice
with a dict containing the label and content.

Scene usage example:
    {
      "type": "slm:text-source",
      "properties": {"label": "intro", "text": "The patient has fever and cough."},
      "subscribe": "pipeline/start~trigger",
      "publish":   "text~pipeline/text-out"
    }
"""
from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "slm:text-source",
    "properties": {
        "text":         {"default": ""},
        "label":        {"default": "text"},
        "auto_publish": {"default": False},
    },
    "receive": ["trigger"],
    "publish": "text~slm/text/output",
})
class TextSourceOid(OidComponent):
    """Publishes its `text` property as a message whenever triggered."""

    async def start(self) -> None:
        await super().start()
        if self.auto_publish:
            await self._publish_text()

    async def handle_trigger(self, notice: str, message: dict) -> None:
        await self._publish_text()

    async def _publish_text(self) -> None:
        await self._notify("text", {"label": self.label, "content": self.text})
