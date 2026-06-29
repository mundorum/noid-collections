"""Tests for basic:timer."""
import asyncio

from noid.core.bus import Bus
from noid_collections.basic.timer.timer import TimerOid


async def test_timer_emits_pulses() -> None:
    bus = Bus()
    pulses = []
    bus.subscribe("basic/timer/pulse", lambda t, m: pulses.append(m))

    comp = TimerOid(
        bus=bus,
        subscribe="test/start~start",
        properties={"cycles": 3, "period": 0.05},
    )
    await comp.start()
    await bus.publish("test/start", {})
    await asyncio.sleep(0.25)

    assert len(pulses) == 3
    assert pulses[0] == {"count": 1}
    assert pulses[1] == {"count": 2}
    assert pulses[2] == {"count": 3}
    await comp.stop()


async def test_timer_publishes_done_after_all_cycles() -> None:
    bus = Bus()
    done_msgs = []
    bus.subscribe("basic/timer/done", lambda t, m: done_msgs.append(m))

    comp = TimerOid(
        bus=bus,
        subscribe="test/start~start",
        properties={"cycles": 2, "period": 0.05},
    )
    await comp.start()
    await bus.publish("test/start", {})
    await asyncio.sleep(0.20)

    assert len(done_msgs) == 1
    await comp.stop()


async def test_timer_stop_halts_pulses() -> None:
    bus = Bus()
    pulses = []
    bus.subscribe("basic/timer/pulse", lambda t, m: pulses.append(m))

    comp = TimerOid(
        bus=bus,
        subscribe="test/start~start;test/stop~stop",
        properties={"period": 0.05},
    )
    await comp.start()
    await bus.publish("test/start", {})
    await asyncio.sleep(0.12)        # ~2 pulses
    await bus.publish("test/stop", {})
    count_after_stop = len(pulses)
    await asyncio.sleep(0.12)        # no more pulses expected

    assert count_after_stop >= 1
    assert len(pulses) == count_after_stop
    await comp.stop()


async def test_timer_reset_clears_count() -> None:
    bus = Bus()
    pulses = []
    bus.subscribe("basic/timer/pulse", lambda t, m: pulses.append(m))

    comp = TimerOid(
        bus=bus,
        subscribe="test/start~start;test/reset~reset",
        properties={"period": 0.05},
    )
    await comp.start()
    await bus.publish("test/start", {})
    await asyncio.sleep(0.12)        # ~2 pulses
    await bus.publish("test/reset", {})
    await asyncio.sleep(0.02)

    assert comp._count == 0
    await comp.stop()


async def test_timer_start_is_noop_when_running() -> None:
    bus = Bus()
    pulses = []
    bus.subscribe("basic/timer/pulse", lambda t, m: pulses.append(m))

    comp = TimerOid(
        bus=bus,
        subscribe="test/start~start",
        properties={"period": 0.05},
    )
    await comp.start()
    await bus.publish("test/start", {})
    await bus.publish("test/start", {})  # second start — should not spawn a second task
    await asyncio.sleep(0.12)

    # Count should reflect a single timer, not doubled pulses
    assert len(pulses) >= 1
    assert all(pulses[i]["count"] == i + 1 for i in range(len(pulses)))
    await comp.stop()


async def test_timer_zero_cycles_runs_indefinitely() -> None:
    bus = Bus()
    done_msgs = []
    pulses = []
    bus.subscribe("basic/timer/pulse", lambda t, m: pulses.append(m))
    bus.subscribe("basic/timer/done",  lambda t, m: done_msgs.append(m))

    comp = TimerOid(
        bus=bus,
        subscribe="test/start~start;test/stop~stop",
        properties={"cycles": 0, "period": 0.05},
    )
    await comp.start()
    await bus.publish("test/start", {})
    await asyncio.sleep(0.22)
    await bus.publish("test/stop", {})

    assert len(pulses) >= 3
    assert len(done_msgs) == 0   # done never fires when cycles=0
    await comp.stop()
