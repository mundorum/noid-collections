"""Tests for noid_collections.manifest_sync."""
import json
from pathlib import Path

import pytest

from noid.core.component import Noid, OidComponent
from noid_collections.manifest import COLLECTIONS
from noid_collections.manifest_sync import sync_all, sync_component


@pytest.fixture(autouse=True)
def _clean_registry():
    before = set(Noid._oid_reg.keys())
    yield
    for k in list(Noid._oid_reg.keys()):
        if k not in before:
            del Noid._oid_reg[k]


def _write_fake_component(root: Path, group: str, name: str) -> Path:
    """Create a fixture component at root/group/name/name.py, registered under test:<name>."""
    comp_dir = root / group / name
    comp_dir.mkdir(parents=True)
    (comp_dir / "__init__.py").write_text("", encoding="utf-8")
    (comp_dir / f"{name}.py").write_text(
        f'''"""A fake component for testing."""
from noid.core.component import Noid, OidComponent


@Noid.component({{"id": "test:{name.replace("_", "-")}"}})
class FakeOid(OidComponent):
    """A fake component used only by manifest_sync tests."""
''',
        encoding="utf-8",
    )
    return comp_dir / f"{name}.py"


def test_manifest_collections_is_list_of_dicts():
    assert isinstance(COLLECTIONS, list)
    assert COLLECTIONS
    for entry in COLLECTIONS:
        assert set(entry.keys()) == {"name", "pip_extra", "modules", "description"}


def test_sync_component_adds_new_entry(tmp_path):
    pkg_root = tmp_path / "noid_collections"
    pkg_root.mkdir()
    py_path = _write_fake_component(pkg_root, "data", "fake_thing")
    manifest_path = tmp_path / "collections.json"
    manifest_path.write_text("[]", encoding="utf-8")

    sync_component(py_path, manifest_path, write_yaml=False, root=pkg_root)

    collections = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(collections) == 1
    entry = collections[0]
    assert entry["name"] == "Data — Fake Thing"
    assert entry["pip_extra"] is None
    assert entry["modules"] == ["noid_collections.data.fake_thing.fake_thing"]
    assert entry["description"] == "A fake component used only by manifest_sync tests."


def test_sync_component_is_idempotent_without_force(tmp_path):
    pkg_root = tmp_path / "noid_collections"
    pkg_root.mkdir()
    py_path = _write_fake_component(pkg_root, "data", "fake_thing")
    manifest_path = tmp_path / "collections.json"
    manifest_path.write_text("[]", encoding="utf-8")

    sync_component(py_path, manifest_path, write_yaml=False, root=pkg_root)
    collections = json.loads(manifest_path.read_text(encoding="utf-8"))
    collections[0]["description"] = "Curated blurb."  # simulate hand-curation
    manifest_path.write_text(json.dumps(collections), encoding="utf-8")

    # Simulate a second, separate `noid-collections-extract-meta` run: a fresh
    # process would have an empty registry, so drop the id we just registered.
    del Noid._oid_reg["test:fake-thing"]
    sync_component(py_path, manifest_path, write_yaml=False, root=pkg_root)

    collections = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(collections) == 1
    assert collections[0]["description"] == "Curated blurb."


def test_sync_component_force_overwrites_entry(tmp_path):
    pkg_root = tmp_path / "noid_collections"
    pkg_root.mkdir()
    py_path = _write_fake_component(pkg_root, "data", "fake_thing")
    manifest_path = tmp_path / "collections.json"
    manifest_path.write_text(
        json.dumps([{
            "name": "Stale Name",
            "pip_extra": "stale",
            "modules": ["noid_collections.data.fake_thing.fake_thing"],
            "description": "Stale description.",
        }]),
        encoding="utf-8",
    )

    sync_component(py_path, manifest_path, write_yaml=False, force=True, root=pkg_root)

    collections = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(collections) == 1
    assert collections[0]["name"] == "Data — Fake Thing"
    assert collections[0]["description"] == "A fake component used only by manifest_sync tests."


def test_sync_all_skips_broken_module_and_continues(tmp_path):
    pkg_root = tmp_path / "noid_collections"
    pkg_root.mkdir()
    _write_fake_component(pkg_root, "data", "fake_good")

    broken_dir = pkg_root / "data" / "fake_broken"
    broken_dir.mkdir(parents=True)
    (broken_dir / "__init__.py").write_text("", encoding="utf-8")
    (broken_dir / "fake_broken.py").write_text(
        "import nonexistent_dependency_xyz\n", encoding="utf-8",
    )

    manifest_path = tmp_path / "collections.json"
    manifest_path.write_text("[]", encoding="utf-8")

    warnings = sync_all(root=pkg_root, manifest_path=manifest_path)

    assert any("fake_broken" in w for w in warnings)
    collections = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(collections) == 1
    assert collections[0]["modules"] == ["noid_collections.data.fake_good.fake_good"]
