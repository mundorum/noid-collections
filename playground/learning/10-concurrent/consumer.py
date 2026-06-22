"""
learning:consumer — receives items and publishes a consumed record.

Demonstrates the noid bus queuing mechanism via set_ready().

handle_item is SYNCHRONOUS. It calls set_ready(False) immediately, which
causes the bus to buffer any further incoming items in the component's
_pending_messages list rather than dispatching them. A task is then created
to do the actual (slow) work. Because handle_item returns at once (no
await), the bus finishes dispatching the produced message to all subscribers
— including the display — before the consumer's processing begins.

When the processing task finishes it calls set_ready(True), which schedules
a drain: the next buffered item is dequeued and handle_item is called again,
maintaining strict FIFO order. This mirrors the threading.Queue / consumer-
thread pattern from the original Producer-Consumer example.

Properties:
  label — identifier added to the published record (default: "consumer")

Scene usage:
  {
    "type":       "learning:consumer",
    "properties": {"label": "consumer"},
    "subscribe":  "pipeline/items~item",
    "publish":    "consumed~pipeline/consumed"
  }
"""
import asyncio
import random
from datetime import datetime

from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "learning:consumer",
    "properties": {
        "label": {"default": "consumer"},
    },
    "receive": ["item"],
    "publish": "consumed~consumer/consumed",
})
class ConsumerOid(OidComponent):
    def handle_item(self, notice: str, message: dict) -> None:
        # Mark busy so any new items arriving during processing are buffered.
        self.set_ready(False)
        asyncio.create_task(self._process(message))

    async def _process(self, message: dict) -> None:
        try:
            await asyncio.sleep(random.random())
            consumed_at = datetime.now().isoformat(timespec="milliseconds")
            await self._notify("consumed", {
                "seq":         message["seq"],
                "body":        message["body"],
                "produced_at": message["produced_at"],
                "consumed_at": consumed_at,
            })
        finally:
            # Unblock: the framework drains one buffered item (if any) and
            # calls handle_item again, which sets_ready(False) once more.
            self.set_ready(True)
