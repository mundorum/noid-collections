"""
data:text-source — publishes text content as a message on the bus.

Set the `text` property for inline content, or `file` to load content from a
file.  Whenever a `load` notice is received the component reads its source and
publishes a `text` notice with a dict containing the label and content.

To kick off a pipeline at scene start, wire the player/start topic to the
load notice in the scene:

    "subscribe": "player/start~load"

Scene usage examples:

    Inline text:
    {
      "type": "data:text-source",
      "properties": {"label": "intro", "text": "The patient has fever and cough."},
      "subscribe": "player/start~load",
      "publish":   "text~pipeline/text-out"
    }

    From a file:
    {
      "type": "data:text-source",
      "properties": {"label": "intro", "file": "shared:data/intro.txt"},
      "subscribe": "player/start~load",
      "publish":   "text~pipeline/text-out"
    }
"""
from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "data:text-source",
    "name": "Text Source",
    "description": (
        "Publishes text content as a message whenever a load notice arrives. "
        "Content can be provided inline via the text property or read from a file. "
        "To auto-start, wire player/start to the load notice in the scene."
    ),
    "properties": {
        "text": {
            "default": "",
            "description": "Inline text content to publish. Ignored if `file` is set.",
        },
        "file": {
            "default": "",
            "kind": "resource",
            "description": "Path to a text file whose content is published. Takes precedence over `text`.",
        },
        "label": {
            "default": "text",
            "description": "Label included in the published payload to identify this source.",
        },
    },
    "receive": {
        "load": {"description": "Loads and publishes the text content (from file if set, else from the text property)."},
    },
    "publish": "text~data/text/output;done~data/text/done",
    "output_notices": {
        "text": {
            "description": (
                "Emitted when loaded. "
                "Payload keys: label (str), content (str)."
            ),
        },
        "done": {
            "description": "Emitted after text, signaling pipeline completion.",
        },
    },
})
class TextSourceOid(OidComponent):
    """Publishes its text content as a message whenever a load notice arrives."""

    async def handle_load(self, notice: str, message: dict) -> None:
        content = self._read_content()
        await self._notify("text", {"label": self.label, "content": content})
        await self._notify("done", {})

    def _read_content(self) -> str:
        if self.file:
            with open(self.file, "r", encoding="utf-8") as f:
                return f.read()
        return self.text
