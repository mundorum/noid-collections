"""
learning:producer — generates numbered items at random intervals.

A source component that emits a configurable number of items, each carrying
a sequential number, a body string, and the timestamp it was produced.
Between items it sleeps a random fraction of a second, mirroring the
threading Producer-Consumer pattern where production time varies.

After emitting all items it publishes a `done` notice so the NoidPlayer
can shut the scene down.

Properties:
  count   — number of items to produce (default: 10)

Scene usage:
  {
    "type":       "learning:producer",
    "properties": {"count": 10},
    "publish":    "item~pipeline/items;done~player/done"
  }
"""
import asyncio
import random
from datetime import datetime

from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "learning:producer",
    "properties": {
        "count": {"default": 10},
    },
    "publish": "item~producer/items;done~player/done",
})
class ProducerOid(OidComponent):
    async def start(self) -> None:
        await super().start()
        self._task = asyncio.create_task(self._produce())

    async def stop(self) -> None:
        task = getattr(self, "_task", None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await super().stop()

    async def _produce(self) -> None:
        for i in range(self.count):
            produced_at = datetime.now().isoformat(timespec="milliseconds")
            message = {
                "seq": i,
                "body": f"item-{i}",
                "produced_at": produced_at,
            }
            await self._notify("item", message)
            await asyncio.sleep(random.random())
        await self._notify("done", {})
