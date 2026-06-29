"""
basic:timer — emits pulse notices at regular intervals.

The timer runs for a fixed number of cycles or indefinitely.  Start it by
wiring player/start (or any other topic) to the `start` notice in the scene.
Stop it early with `stop`; reset the count and halt with `reset`.

Properties:
  cycles  — total pulses to emit before stopping; 0 = run until stopped (default: 0)
  period  — seconds between pulses (default: 1.0)

Notices received:
  start  → begin the timer (no-op if already running)
  stop   → pause the timer without resetting the count
  reset  → stop the timer and reset the count to zero

Notices published:
  pulse  → {"count": int}   emitted each cycle (count is 1-based)
  done   → {}               emitted when all cycles complete (only when cycles > 0)

Scene usage example:

  Auto-start, 5 pulses at 2-second intervals:
  {
    "type": "basic:timer",
    "id": "t1",
    "properties": {"cycles": 5, "period": 2.0},
    "subscribe": "player/start~start",
    "publish":   "pulse~pipeline/tick;done~player/done"
  }

  Indefinite timer, externally stopped:
  {
    "type": "basic:timer",
    "id": "clock",
    "properties": {"period": 0.5},
    "subscribe": "ctrl/start~start;ctrl/stop~stop;ctrl/reset~reset",
    "publish":   "pulse~pipeline/tick"
  }
"""
import asyncio

from noid.core.component import Noid, OidComponent


@Noid.component({
    "id": "basic:timer",
    "name": "Timer",
    "description": (
        "Emits pulse notices at regular intervals for a fixed or unlimited "
        "number of cycles. Responds to start, stop, and reset notices."
    ),
    "properties": {
        "cycles": {
            "default": 0,
            "description": (
                "Number of pulses to emit before publishing done and halting. "
                "0 means run indefinitely until a stop or reset notice arrives."
            ),
        },
        "period": {
            "default": 1.0,
            "description": "Seconds between consecutive pulses.",
        },
    },
    "receive": {
        "start": {"description": "Begin the timer. No-op if already running."},
        "stop":  {"description": "Pause the timer without resetting the count."},
        "reset": {"description": "Stop the timer and reset the pulse count to zero."},
    },
    "publish": "pulse~basic/timer/pulse;done~basic/timer/done",
    "output_notices": {
        "pulse": {
            "description": "Emitted each cycle. Payload key: count (int, 1-based).",
        },
        "done": {
            "description": (
                "Emitted when all cycles complete. "
                "Only published when cycles > 0. Payload: {}."
            ),
        },
    },
})
class TimerOid(OidComponent):
    """Emits pulse notices at regular intervals for a fixed or unlimited number of cycles."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._task: asyncio.Task | None = None
        self._count: int = 0

    async def stop(self) -> None:
        await self._stop_task()
        await super().stop()

    async def handle_start(self, notice: str, message: dict) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())

    async def handle_stop(self, notice: str, message: dict) -> None:
        await self._stop_task()

    async def handle_reset(self, notice: str, message: dict) -> None:
        await self._stop_task()
        self._count = 0

    async def _stop_task(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(float(self.period))
                self._count += 1
                await self._notify("pulse", {"count": self._count})
                cycles = int(self.cycles) if self.cycles else 0
                if cycles and self._count >= cycles:
                    await self._notify("done", {})
                    break
        except asyncio.CancelledError:
            pass
