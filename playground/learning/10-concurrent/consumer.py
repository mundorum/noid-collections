"""
learning:consumer — receives and displays items, simulating variable availability.

A sink component that subscribes to items produced on the bus. Its handler
is async and sleeps a random fraction of a second before printing, modelling
a consumer that is not always immediately available. While it is "busy"
(sleeping), the bus queues incoming messages and delivers them in order once
the handler is free again — the noid equivalent of a blocking thread blocked
on processing work in the classic Producer-Consumer pattern.

Each consumed item is printed with the item body, the timestamp it was
produced, and the timestamp it is consumed, so the queuing delay is visible.

Properties:
  label — prefix for console output (default: "consumer")

Scene usage:
  {
    "type":       "learning:consumer",
    "properties": {"label": "consumer"},
    "subscribe":  "pipeline/items~item"
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
})
class ConsumerOid(OidComponent):
    async def handle_item(self, notice: str, message: dict) -> None:
        # Simulate variable processing time — consumer is not always available.
        await asyncio.sleep(random.random())
        consumed_at = datetime.now().isoformat(timespec="milliseconds")
        print(
            f"[{self.label}] Consumed: {message['body']}"
            f"  (produced: {message['produced_at']}, consumed: {consumed_at})"
        )
