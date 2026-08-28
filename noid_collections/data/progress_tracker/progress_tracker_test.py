"""Tests for data:progress-tracker's durable checkpoint journal."""
from pathlib import Path

from noid.core.bus import Bus
from noid_collections.data.csv_writer.csv_writer import CsvWriterOid
from noid_collections.data.progress_tracker.progress_tracker import ProgressTrackerOid


async def test_checkpoint_is_durable_before_acknowledgement(tmp_path) -> None:
    state_file = tmp_path / "progress.keys"
    bus = Bus()
    forwarded, skipped, recorded = [], [], []
    bus.subscribe("data/row", lambda _, message: forwarded.append(message))
    bus.subscribe("data/skipped", lambda _, message: skipped.append(message))
    bus.subscribe("data/checkpoint", lambda _, message: recorded.append(message))

    comp = ProgressTrackerOid(
        bus=bus,
        subscribe="test/row~row;test/checkpoint~checkpoint",
        publish="forward~data/row;skipped~data/skipped;checkpoint_recorded~data/checkpoint",
        properties={"state_file": str(state_file), "identifier_path": "row.id"},
    )
    await comp.start()

    row = {"row": {"id": "usr-99", "name": "Bob"}}
    await bus.publish("test/row", row)
    await bus.publish("test/checkpoint", row)

    assert forwarded == [row]
    assert recorded == [row]
    assert state_file.read_text(encoding="utf-8") == "usr-99\n"
    await comp.stop()

    resumed_bus = Bus()
    resumed_skipped = []
    resumed_bus.subscribe("data/skipped", lambda _, message: resumed_skipped.append(message))
    resumed = ProgressTrackerOid(
        bus=resumed_bus,
        subscribe="test/row~row",
        publish="skipped~data/skipped",
        properties={"state_file": str(state_file), "identifier_path": "row.id"},
    )
    await resumed.start()
    await resumed_bus.publish("test/row", row)

    assert resumed_skipped == [row]
    await resumed.stop()


async def test_schema_does_not_change_configured_journal_path(tmp_path) -> None:
    state_file = tmp_path / "patients.keys"
    bus = Bus()
    schemas = []
    bus.subscribe("data/schema", lambda _, message: schemas.append(message))
    comp = ProgressTrackerOid(
        bus=bus,
        subscribe="test/schema~schema",
        publish="schema~data/schema",
        properties={"state_file": str(state_file), "identifier_path": "row.id"},
    )
    await comp.start()
    await bus.publish("test/schema", {"label": "patients.csv", "columns": ["id"]})

    assert comp._state_file_abs == str(state_file.resolve())
    assert schemas == [{"label": "patients.csv", "columns": ["id"]}]
    await comp.stop()


async def test_status_reports_resolved_journal_and_loaded_checkpoint_count(tmp_path) -> None:
    state_file = tmp_path / "progress.keys"
    bus = Bus()
    states = []
    bus.subscribe("data/state", lambda _, message: states.append(message))
    comp = ProgressTrackerOid(
        bus=bus,
        subscribe="test/status~status;test/checkpoint~checkpoint",
        publish="state~data/state",
        properties={"state_file": str(state_file), "identifier_path": "row.id"},
    )
    await comp.start()

    await bus.publish("test/status", {})
    assert states == [{
        "state_file": str(state_file.resolve()),
        "exists": False,
        "completed_count": 0,
        "format": "keys-v1",
    }]

    await bus.publish("test/checkpoint", {"row": {"id": "usr-99"}})
    await bus.publish("test/status", {})
    assert states[-1] == {
        "state_file": str(state_file.resolve()),
        "exists": True,
        "completed_count": 1,
        "format": "keys-v1",
    }
    await comp.stop()


async def _run_pipeline_cycle(state_file: Path, output_file: Path) -> tuple[list, list]:
    bus = Bus()
    forwarded, skipped = [], []
    bus.subscribe("pipeline/tracker-forward", lambda _, message: forwarded.append(message))
    bus.subscribe("pipeline/tracker-skipped", lambda _, message: skipped.append(message))

    tracker = ProgressTrackerOid(
        bus=bus,
        subscribe="pipeline/schema~schema;pipeline/row~row;pipeline/checkpoint~checkpoint",
        publish="schema~pipeline/tracker-schema;forward~pipeline/tracker-forward;skipped~pipeline/tracker-skipped",
        properties={"state_file": str(state_file), "identifier_path": "row.id"},
    )
    writer = CsvWriterOid(
        bus=bus,
        subscribe="pipeline/tracker-schema~schema;pipeline/tracker-forward~row;pipeline/done~done",
        publish="row_written~pipeline/checkpoint",
        properties={"output_file": str(output_file)},
    )
    await tracker.start()
    await writer.start()

    await bus.publish("pipeline/schema", {"label": "patients.csv", "columns": ["id", "name"]})
    for row in (
        {"row": {"id": "a", "name": "Alice"}},
        {"row": {"id": "b", "name": "Bob"}},
        {"row": {"id": "c", "name": "Carol"}},
    ):
        await bus.publish("pipeline/row", row)
    await bus.publish("pipeline/done", {})

    await tracker.stop()
    await writer.stop()
    return forwarded, skipped


async def test_resume_survives_csv_writer_replacing_result_file(tmp_path) -> None:
    state_file = tmp_path / "patients.keys"
    output_file = tmp_path / "patients_output.csv"

    first_forwarded, first_skipped = await _run_pipeline_cycle(state_file, output_file)
    second_forwarded, second_skipped = await _run_pipeline_cycle(state_file, output_file)

    assert len(first_forwarded) == 3
    assert first_skipped == []
    assert second_forwarded == []
    assert len(second_skipped) == 3
    assert state_file.read_text(encoding="utf-8").splitlines() == ["a", "b", "c"]


async def test_line_break_identifier_is_rejected_without_checkpointing(tmp_path) -> None:
    state_file = tmp_path / "progress.keys"
    bus = Bus()
    errors, recorded = [], []
    bus.subscribe("data/error", lambda _, message: errors.append(message))
    bus.subscribe("data/checkpoint", lambda _, message: recorded.append(message))
    comp = ProgressTrackerOid(
        bus=bus,
        subscribe="test/checkpoint~checkpoint",
        publish="error~data/error;checkpoint_recorded~data/checkpoint",
        properties={"state_file": str(state_file), "identifier_path": "row.id"},
    )
    await comp.start()
    await bus.publish("test/checkpoint", {"row": {"id": "first\nsecond"}})

    assert recorded == []
    assert errors == [{"error": "Checkpoint identifier cannot contain a line break.", "key": "first\nsecond"}]
    assert not state_file.exists()
    await comp.stop()
