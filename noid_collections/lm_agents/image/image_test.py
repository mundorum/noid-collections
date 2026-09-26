"""Tests for lm:image-agent — a fake backend stands in for the real model."""
import base64
import json
from pathlib import Path

import pytest

from noid.core.bus import Bus
from noid_collections.lm_agents.image.backends import (
    ImageBackend, get_backend, register_backend, resolve_backend_class,
)
from noid_collections.lm_agents.image.image import ImageAgentOid
from noid_collections.lm_agents.prompt_template import render_prompt

FAKE_PNG = b"\x89PNG fake"


class FakeImage:
    """Minimal stand-in for a PIL image: only save() is used by the component."""

    def save(self, fp, format=None):
        if isinstance(fp, (str, Path)):
            Path(fp).write_bytes(FAKE_PNG)
        else:
            fp.write(FAKE_PNG)


class FakeBackend(ImageBackend):
    default_model = "fake/model"
    calls: list = []

    def generate_images(self, prompt, num_images, seed, guidance_scale, options):
        FakeBackend.calls.append({
            "prompt": prompt, "num_images": num_images, "seed": seed,
            "guidance_scale": guidance_scale, "options": options,
        })
        if prompt == "boom":
            raise RuntimeError("model exploded")
        return [FakeImage() for _ in range(num_images)]


register_backend("fake", FakeBackend)


@pytest.fixture(autouse=True)
def _reset_calls():
    FakeBackend.calls.clear()


def _agent(bus, tmp_path, **properties):
    return ImageAgentOid(
        bus=bus,
        subscribe="test/in~input;test/schema~schema;test/row~row",
        publish="document~image/document;schema~image/schema;row~image/row",
        properties={"backend": "fake", "output_dir": str(tmp_path), **properties},
    )


async def test_input_generates_image_file(tmp_path) -> None:
    bus = Bus()
    received = []
    bus.subscribe("image/document", lambda t, m: received.append(m))

    comp = _agent(bus, tmp_path, prompt_template="{{input}}, cartoon style")
    await comp.start()
    await bus.publish("test/in", {"content": "A nurse smiling"})

    assert len(received) == 1
    doc = received[0]
    assert doc["prompt"] == "A nurse smiling, cartoon style"
    assert doc["model"] == "fake/model"
    assert doc["backend"] == "fake"
    assert len(doc["images"]) == 1
    path = Path(doc["content"])
    assert path == Path(doc["images"][0]["file"])
    assert path.parent == tmp_path
    assert path.name.endswith("-a-nurse-smiling-0.png")
    assert path.read_bytes() == FAKE_PNG
    assert "data_url" not in doc["images"][0]
    await comp.stop()


async def test_generation_parameters_are_passed_to_backend(tmp_path) -> None:
    bus = Bus()
    comp = _agent(
        bus, tmp_path,
        num_images="2", seed="42", guidance_scale="3.5",
        options='{"temperature": 0.8}',
    )
    await comp.start()
    await bus.publish("test/in", "a hospital waiting room")

    assert FakeBackend.calls == [{
        "prompt": "a hospital waiting room", "num_images": 2, "seed": 42,
        "guidance_scale": 3.5, "options": {"temperature": 0.8},
    }]
    await comp.stop()


async def test_unset_seed_and_guidance_use_backend_defaults(tmp_path) -> None:
    bus = Bus()
    comp = _agent(bus, tmp_path)
    await comp.start()
    await bus.publish("test/in", {"content": "x"})

    assert FakeBackend.calls[0]["seed"] is None
    assert FakeBackend.calls[0]["guidance_scale"] is None
    assert FakeBackend.calls[0]["options"] == {}
    await comp.stop()


async def test_embed_adds_data_url(tmp_path) -> None:
    bus = Bus()
    received = []
    bus.subscribe("image/document", lambda t, m: received.append(m))

    comp = _agent(bus, tmp_path, embed=True)
    await comp.start()
    await bus.publish("test/in", {"content": "x"})

    data_url = received[0]["images"][0]["data_url"]
    prefix = "data:image/png;base64,"
    assert data_url.startswith(prefix)
    assert base64.b64decode(data_url[len(prefix):]) == FAKE_PNG
    await comp.stop()


async def test_csv_mode_schema_and_row(tmp_path) -> None:
    bus = Bus()
    schemas, rows = [], []
    bus.subscribe("image/schema", lambda t, m: schemas.append(m))
    bus.subscribe("image/row", lambda t, m: rows.append(m))

    comp = _agent(
        bus, tmp_path,
        csv_field="picture",
        prompt_template="A drawing of {{row.name}}, a {{row.age}} year old patient",
    )
    await comp.start()
    await bus.publish("test/schema", {"label": "patients", "columns": ["name", "age"]})
    await bus.publish("test/row", {
        "label": "patients", "index": 3, "row": {"name": "Ana", "age": "70"},
    })

    assert schemas == [{"label": "patients", "columns": ["name", "age", "picture"]}]
    assert FakeBackend.calls[0]["prompt"] == "A drawing of Ana, a 70 year old patient"
    assert len(rows) == 1
    assert rows[0]["label"] == "patients" and rows[0]["index"] == 3
    path = Path(rows[0]["row"]["picture"])
    assert path.name.endswith("-row3-0.png")
    assert path.exists()
    await comp.stop()


async def test_csv_mode_multiple_images_serialized_as_json(tmp_path) -> None:
    bus = Bus()
    rows = []
    bus.subscribe("image/row", lambda t, m: rows.append(m))

    comp = _agent(bus, tmp_path, csv_field="picture", num_images=2)
    await comp.start()
    await bus.publish("test/row", {"index": 0, "row": {"content": "x"}})

    paths = json.loads(rows[0]["row"]["picture"])
    assert len(paths) == 2
    assert all(Path(p).exists() for p in paths)
    await comp.stop()


async def test_row_ignored_without_csv_field(tmp_path) -> None:
    bus = Bus()
    rows = []
    bus.subscribe("image/row", lambda t, m: rows.append(m))

    comp = _agent(bus, tmp_path)
    await comp.start()
    await bus.publish("test/row", {"row": {"content": "x"}})

    assert rows == []
    assert FakeBackend.calls == []
    await comp.stop()


async def test_failure_publishes_fallback_value(tmp_path) -> None:
    bus = Bus()
    received = []
    bus.subscribe("image/document", lambda t, m: received.append(m))

    comp = _agent(bus, tmp_path, error_fallback_value="NO_IMAGE")
    await comp.start()
    await bus.publish("test/in", {"content": "boom"})

    assert received[0]["content"] == "NO_IMAGE"
    assert received[0]["images"] == []
    await comp.stop()


async def test_failure_propagates(tmp_path) -> None:
    bus = Bus()
    comp = _agent(bus, tmp_path, error_mode="propagate")
    await comp.start()
    with pytest.raises(RuntimeError, match="model exploded"):
        await comp.handle_input("input", {"content": "boom"})
    await comp.stop()


async def test_invalid_options_use_fallback(tmp_path) -> None:
    bus = Bus()
    received = []
    bus.subscribe("image/document", lambda t, m: received.append(m))

    comp = _agent(bus, tmp_path, options="[1, 2]")
    await comp.start()
    await bus.publish("test/in", {"content": "x"})

    assert received[0]["content"] == "IMAGE_ERROR"
    assert FakeBackend.calls == []
    await comp.stop()


def test_backend_resolved_by_import_path() -> None:
    cls = resolve_backend_class("noid_collections.lm_agents.image.image_test:FakeBackend")
    assert cls is FakeBackend


def test_unknown_backend_raises() -> None:
    with pytest.raises(ValueError, match="Unknown image backend"):
        resolve_backend_class("nope")


def test_backend_instances_are_cached() -> None:
    first = get_backend("fake", "m1")
    assert get_backend("fake", "m1") is first
    assert get_backend("fake", "m2") is not first
    assert first.model_id == "m1"


def test_render_prompt_keeps_backslashes() -> None:
    assert render_prompt("see {{input}}", {"content": r"C:\data\x"}) == r"see C:\data\x"
