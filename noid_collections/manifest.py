"""
Static discovery manifest for mundorum-noid-collections.

Consumers (e.g. the noid authoring server) can read COLLECTIONS to discover
available component groups, their module paths, and the pip extra required to
install their heavy dependencies — without importing any component code.

COLLECTIONS is loaded from collections.json, which is generated/maintained by
`noid-collections-extract-meta` (see manifest_sync.py). Run it after adding or
updating a component instead of hand-editing this file; collections.json can
still be edited directly since it's plain JSON.

Each entry in COLLECTIONS is a dict with:
  name         str   — display name shown in the UI
  pip_extra    str|None — pip extra to install (e.g. "lm"), None for base deps
  modules      list[str] — importable Python module paths that register Noid components
  description  str   — short human-readable description
"""
import json
from pathlib import Path

COLLECTIONS: list[dict] = json.loads(
    (Path(__file__).resolve().parent / "collections.json").read_text(encoding="utf-8")
)
