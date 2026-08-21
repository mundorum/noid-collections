"""Tests for data:progress-tracker — verifies progress retention, skipping, checkpointing, and cooperation with csv-writer."""
import csv
import os
import pytest

from noid.core.bus import Bus
from noid_collections.data.progress_tracker.progress_tracker import ProgressTrackerOid


async def test_progress_tracker_flow(tmp_path) -> None:
    bus = Bus()
    state_file = tmp_path / "progress.csv"

    forwarded = []
    skipped = []
    checkpoint_recorded = []

    bus.subscribe("data/row", lambda t, m: forwarded.append(m))
    bus.subscribe("data/skipped", lambda t, m: skipped.append(m))
    bus.subscribe("data/checkpoint", lambda t, m: checkpoint_recorded.append(m))

    comp = ProgressTrackerOid(
        bus=bus,
        subscribe="test/in/row~row;test/in/chk~checkpoint",
        publish="forward~data/row;skipped~data/skipped;checkpoint_recorded~data/checkpoint",
        properties={"state_file": str(state_file), "identifier_path": "index"},
    )
    await comp.start()

    # 1. Send initial row 1. Since state is empty, it should be forwarded.
    await bus.publish("test/in/row", {"index": 1, "row": {"name": "Alice"}})
    assert len(forwarded) == 1
    assert forwarded[-1]["index"] == 1
    assert len(skipped) == 0

    # 2. Record checkpoint for row 1.
    await bus.publish("test/in/chk", {"index": 1, "row": {"name": "Alice"}})
    assert len(checkpoint_recorded) == 1
    assert checkpoint_recorded[-1]["index"] == 1

    # Verify key is in-memory
    assert "1" in comp._completed_keys

    # 3. Send row 1 again. It should be skipped now.
    await bus.publish("test/in/row", {"index": 1, "row": {"name": "Alice"}})
    assert len(forwarded) == 1
    assert len(skipped) == 1
    assert skipped[-1]["index"] == 1

    await comp.stop()

    # Write simulated CSV output (as csv-writer would do) to verify persistence on load
    with open(state_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["index", "name"])
        writer.writerow(["1", "Alice"])

    # 4. Re-instantiate a new tracker with the same state file to test persistence.
    bus2 = Bus()
    forwarded2 = []
    skipped2 = []
    bus2.subscribe("data/row", lambda t, m: forwarded2.append(m))
    bus2.subscribe("data/skipped", lambda t, m: skipped2.append(m))

    comp2 = ProgressTrackerOid(
        bus=bus2,
        subscribe="test/in/row~row",
        publish="forward~data/row;skipped~data/skipped",
        properties={"state_file": str(state_file), "identifier_path": "index"},
    )
    await comp2.start()

    # Send row 1 (should be skipped) and row 2 (should be forwarded)
    await bus2.publish("test/in/row", {"index": 1})
    await bus2.publish("test/in/row", {"index": 2})

    assert len(skipped2) == 1
    assert skipped2[0]["index"] == 1
    assert len(forwarded2) == 1
    assert forwarded2[0]["index"] == 2

    await comp2.stop()


async def test_progress_tracker_nested_path(tmp_path) -> None:
    bus = Bus()
    state_file = tmp_path / "progress.csv"
    forwarded = []
    skipped = []

    bus.subscribe("data/row", lambda t, m: forwarded.append(m))
    bus.subscribe("data/skipped", lambda t, m: skipped.append(m))

    comp = ProgressTrackerOid(
        bus=bus,
        subscribe="test/in/row~row;test/in/chk~checkpoint",
        publish="forward~data/row;skipped~data/skipped",
        properties={"state_file": str(state_file), "identifier_path": "row.id"},
    )
    await comp.start()

    row_msg = {"row": {"id": "usr-99", "name": "Bob"}}

    # Forwarded initially
    await bus.publish("test/in/row", row_msg)
    assert len(forwarded) == 1
    assert len(skipped) == 0

    # Checkpoint
    await bus.publish("test/in/chk", row_msg)

    # Skipped now
    await bus.publish("test/in/row", row_msg)
    assert len(forwarded) == 1
    assert len(skipped) == 1
    assert skipped[0]["row"]["id"] == "usr-99"

    await comp.stop()


async def test_progress_tracker_dynamic_naming(tmp_path) -> None:
    bus = Bus()
    state_file = tmp_path / "default.csv"

    comp = ProgressTrackerOid(
        bus=bus,
        subscribe="test/in/schema~schema;test/in/chk~checkpoint",
        publish="schema~data/schema;checkpoint_recorded~data/checkpoint",
        properties={"state_file": str(state_file), "identifier_path": "row.name"},
    )
    await comp.start()

    # Receive a schema notice with a label 'patients.csv'
    await bus.publish("test/in/schema", {"label": "patients.csv", "columns": ["name", "age"]})

    # The state file should have updated dynamically to patients_output.csv
    expected_path = os.path.abspath(os.path.join(str(tmp_path), "patients_output.csv"))
    assert comp._state_file_abs == expected_path

    # Simulate writing by csv-writer
    with open(expected_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "age"])
        writer.writerow(["Alice", "30"])

    # Re-initialize tracker to verify it loads from the dynamic path
    bus2 = Bus()
    comp2 = ProgressTrackerOid(
        bus=bus2,
        subscribe="test/in/schema~schema",
        properties={"state_file": str(state_file), "identifier_path": "row.name"},
    )
    await comp2.start()

    # Send schema to update path
    await bus2.publish("test/in/schema", {"label": "patients.csv", "columns": ["name", "age"]})
    
    assert "Alice" in comp2._completed_keys

    await comp2.stop()
    await comp.stop()
