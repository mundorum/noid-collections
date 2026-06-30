"""
Keeps noid_collections/collections.json (and manifest.COLLECTIONS) in sync with
the components actually present in this package.

Wraps noid.core.meta.extract_meta_from_module / write_meta_yaml — the same
framework functions `noid-extract-meta` uses — so `.meta.yaml` generation
behaves identically. The manifest itself (collection naming, pip extras) is a
noid-collections-specific concern layered on top, kept out of the shared noid
framework.

CLI:
    noid-collections-extract-meta path/to/component.py [...]
    noid-collections-extract-meta --all
    noid-collections-extract-meta path/to/component.py --no-manifest
    noid-collections-extract-meta --all --force

Programmatic:
    from noid_collections.manifest_sync import sync_component, sync_all
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from noid.core.meta import extract_meta_from_module, meta_to_yaml, write_meta_yaml

PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST_PATH = PACKAGE_ROOT / "collections.json"

GROUP_LABELS: Dict[str, str] = {
    "basic": "Basic",
    "data": "Data",
    "pdf": "PDF",
    "logic": "Logic",
    "lm_agents": "LM Agents",
}

PIP_EXTRA_MAP: Dict[str, str] = {
    "lm_agents/lm": "lm",
    "lm_agents/ner": "ner",
    "data/sql": "sql",
    "logic/prolog": "prolog",
    "pdf": "pdf",  # prefix match: covers all pdf/* component dirs
}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_component_modules(root: Path = PACKAGE_ROOT) -> List[Path]:
    """Return the one main .py file per component directory under root.

    Convention (matches every existing component): a component lives in its
    own directory and its main module file is named after that directory,
    e.g. data/csv_writer/csv_writer.py.
    """
    modules = []
    for path in sorted(root.rglob("*.py")):
        if path.name in ("__init__.py", "manifest.py", "manifest_sync.py"):
            continue
        if path.stem.endswith("_test"):
            continue
        if "__pycache__" in path.parts:
            continue
        if path.stem == path.parent.name:
            modules.append(path)
    return modules


# ---------------------------------------------------------------------------
# Derivation helpers
# ---------------------------------------------------------------------------

def module_dotted_path(py_path: Path, root: Path = PACKAGE_ROOT) -> str:
    """Dotted import path for a component file, e.g. noid_collections.data.csv_writer.csv_writer."""
    rel = py_path.resolve().relative_to(root.resolve().parent)
    return ".".join(rel.with_suffix("").parts)


def _relative_dir(py_path: Path, root: Path = PACKAGE_ROOT) -> str:
    return py_path.resolve().parent.relative_to(root.resolve()).as_posix()


def _group_label_for(rel_dir: str) -> str:
    top = rel_dir.split("/", 1)[0]
    return GROUP_LABELS.get(top, top.replace("_", " ").title())


def _pip_extra_for(rel_dir: str) -> Optional[str]:
    for prefix, extra in PIP_EXTRA_MAP.items():
        if rel_dir == prefix or rel_dir.startswith(prefix + "/"):
            return extra
    return None


def _build_entry(meta: Dict[str, Any], module_dotted: str, rel_dir: str) -> Dict[str, Any]:
    return {
        "name": f"{_group_label_for(rel_dir)} — {meta['name']}",
        "pip_extra": _pip_extra_for(rel_dir),
        "modules": [module_dotted],
        "description": meta.get("description", ""),
    }


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------

def _load_manifest(manifest_path: Path) -> List[Dict[str, Any]]:
    if not manifest_path.exists():
        return []
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _write_manifest(manifest_path: Path, collections: List[Dict[str, Any]]) -> None:
    manifest_path.write_text(
        json.dumps(collections, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _find_entry(collections: List[Dict[str, Any]], module_dotted: str) -> Optional[Dict[str, Any]]:
    for entry in collections:
        if module_dotted in entry.get("modules", []):
            return entry
    return None


def _sync_manifest_entries(
    collections: List[Dict[str, Any]],
    meta_list: List[Dict[str, Any]],
    module_dotted: str,
    rel_dir: str,
    *,
    force: bool,
) -> List[str]:
    """Add or (if force) refresh manifest entries for the given module's
    components, mutating collections in place. Returns log messages.

    Existing entries are left untouched without --force: collections.json
    descriptions/names are often hand-curated short blurbs, distinct from the
    longer .meta.yaml descriptions, so a blind overwrite would be lossy.
    """
    messages = []
    for meta in meta_list:
        entry = _find_entry(collections, module_dotted)
        if entry is None:
            collections.append(_build_entry(meta, module_dotted, rel_dir))
            messages.append(f"Manifest: added {meta['id']!r}")
        elif force:
            fresh = _build_entry(meta, module_dotted, rel_dir)
            entry["name"] = fresh["name"]
            entry["pip_extra"] = fresh["pip_extra"]
            entry["description"] = fresh["description"]
            messages.append(f"Manifest: refreshed {meta['id']!r}")
    return messages


def _write_meta_files(meta_list: List[Dict[str, Any]], component_dir: Path) -> None:
    for meta in meta_list:
        comp_slug = meta["id"].replace(":", "-")
        write_meta_yaml(meta, component_dir / f"{comp_slug}.meta.yaml")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sync_component(
    py_path: Path,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    *,
    include_manifest: bool = True,
    force: bool = False,
    write_yaml: bool = True,
    root: Path = PACKAGE_ROOT,
) -> List[Dict[str, Any]]:
    """Extract metadata for one component module and (optionally) sync the manifest.

    Returns the list of meta dicts extracted (one per component registered by
    the module).
    """
    meta_list = extract_meta_from_module(py_path)

    if write_yaml:
        _write_meta_files(meta_list, py_path.parent)

    if include_manifest:
        collections = _load_manifest(manifest_path)
        _sync_manifest_entries(
            collections, meta_list,
            module_dotted_path(py_path, root), _relative_dir(py_path, root),
            force=force,
        )
        _write_manifest(manifest_path, collections)

    return meta_list


def sync_all(
    root: Path = PACKAGE_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    *,
    include_manifest: bool = True,
    force: bool = False,
) -> List[str]:
    """Sync every discovered component module.

    Returns a list of warning strings for modules that failed to import (e.g.
    missing optional dependencies) — those are skipped rather than aborting
    the whole run.
    """
    collections = _load_manifest(manifest_path) if include_manifest else []
    warnings: List[str] = []

    for py_path in discover_component_modules(root):
        try:
            meta_list = extract_meta_from_module(py_path)
        except Exception as exc:  # noqa: BLE001 - tolerate missing optional deps per module
            warnings.append(f"Skipped {py_path}: {exc}")
            continue

        _write_meta_files(meta_list, py_path.parent)

        if include_manifest:
            _sync_manifest_entries(
                collections, meta_list,
                module_dotted_path(py_path, root), _relative_dir(py_path, root),
                force=force,
            )

    if include_manifest:
        _write_manifest(manifest_path, collections)

    return warnings


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="noid-collections-extract-meta",
        description=(
            "Extract noid component metadata (.meta.yaml) and keep "
            "collections.json in sync, for components in this package."
        ),
    )
    parser.add_argument("module", nargs="*", help="Path(s) to component Python module file(s).")
    parser.add_argument(
        "--all", action="store_true",
        help="Scan the whole package for component modules instead of using MODULE args.",
    )
    parser.add_argument(
        "--out", "-o", metavar="PATH",
        help="Output path for .meta.yaml (single-module mode only).",
    )
    parser.add_argument(
        "--stdout", action="store_true",
        help="Print YAML to stdout instead of writing files (skips manifest sync).",
    )
    parser.add_argument("--no-manifest", action="store_true", help="Skip updating collections.json.")
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite name/description/pip_extra for already-known entries.",
    )
    parser.add_argument(
        "--manifest", metavar="PATH", default=str(DEFAULT_MANIFEST_PATH),
        help="Path to collections.json.",
    )
    return parser


def _cli_sync_one_module(module_path: Path, *, args, include_manifest: bool) -> None:
    try:
        meta_list = extract_meta_from_module(module_path)
    except Exception as exc:  # noqa: BLE001 - reported to the user, then exit
        print(f"Error processing {module_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    out_arg = Path(args.out) if args.out else None
    single_component = len(meta_list) == 1

    for meta in meta_list:
        if args.stdout:
            print(meta_to_yaml(meta))
            continue

        if out_arg is not None and out_arg.is_dir():
            out_path = out_arg / f"{meta['id'].replace(':', '-')}.meta.yaml"
        elif out_arg is not None and single_component:
            out_path = out_arg
        else:
            out_path = module_path.parent / f"{meta['id'].replace(':', '-')}.meta.yaml"

        write_meta_yaml(meta, out_path)
        print(f"Written: {out_path}")

    if include_manifest:
        manifest_path = Path(args.manifest)
        collections = _load_manifest(manifest_path)
        messages = _sync_manifest_entries(
            collections, meta_list,
            module_dotted_path(module_path), _relative_dir(module_path),
            force=args.force,
        )
        for msg in messages:
            print(msg)
        _write_manifest(manifest_path, collections)


def _cli() -> None:
    args = _build_arg_parser().parse_args()

    if args.all and args.module:
        _build_arg_parser().error("--all cannot be combined with explicit MODULE arguments")
    if not args.all and not args.module:
        _build_arg_parser().error("provide MODULE path(s) or use --all")

    include_manifest = not args.no_manifest and not args.stdout

    if args.all:
        manifest_path = Path(args.manifest)
        warnings = sync_all(manifest_path=manifest_path, include_manifest=include_manifest, force=args.force)
        for w in warnings:
            print(w, file=sys.stderr)
        status = f"Manifest updated: {manifest_path}" if include_manifest else "Manifest sync skipped."
        print(f"Synced. {status}")
        return

    for module_path_str in args.module:
        _cli_sync_one_module(Path(module_path_str), args=args, include_manifest=include_manifest)


if __name__ == "__main__":
    _cli()
