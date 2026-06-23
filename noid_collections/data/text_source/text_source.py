"""
data:text-source — publishes static text content as a message on the bus.

The `text` property holds the content.  Whenever a `trigger` notice is received,
the component publishes a `text` notice with a dict containing the label and content.

To kick off a pipeline at scene start, wire the player/start topic to the
trigger notice in the scene:

    "subscribe": "player/start~trigger"

Scene usage example:
    {
      "type": "data:text-source",
      "properties": {"label": "intro", "text": "The patient has fever and cough."},
      "subscribe": "player/start~trigger",
      "publish":   "text~pipeline/text-out"
    }
"""
from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "data:text-source",
    "properties": {
        "text":  {"default": ""},
        "label": {"default": "text"},
    },
    "receive": ["trigger"],
    "publish": "text~slm/text/output;done~slm/text/done",
})
class TextSourceOid(OidComponent):
    """Publishes its `text` property as a message whenever triggered."""

    async def handle_trigger(self, notice: str, message: dict) -> None:
        await self._publish_text()

    async def _publish_text(self) -> None:
        await self._notify("text", {"label": self.label, "content": self.text})
        await self._notify("done", {})
