"""Durable, message-driven progress tracking.

``data:progress-tracker`` forwards rows whose stable identifier has not been
checkpointed and persists completed identifiers in its own append-only journal.
The journal is deliberately separate from result files written by
``data:csv-writer``: a result writer is free to replace its output atomically,
whereas progress must survive that replacement.
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Set

from noid.core.component import Noid, OidComponent

logger = logging.getLogger(__name__)


@Noid.component({
    "id": "data:progress-tracker",
    "name": "Progress Tracker",
    "description": "Forwards uncheckpointed rows and persists identifiers in a separate append-only journal.",
    "properties": {
        "state_file": {
            "default": "progress.keys",
            "kind": "resource",
            "description": "Path to the UTF-8 checkpoint journal (one identifier per line), separate from result files.",
        },
        "identifier_path": {
            "default": "index",
            "description": "Dotted path containing a stable identifier (for example 'row.id'). 'index' is safe only with immutable row order.",
        },
    },
    "receive": {
        "schema": {"description": "Schema notice to forward; it never changes the checkpoint journal path."},
        "row": {"description": "Incoming row to check. Completed rows are skipped; other rows are forwarded."},
        "checkpoint": {"description": "Success acknowledgement containing the same identifier as the forwarded row."},
    },
    "publish": "forward~data/row;skipped~data/skipped;schema~data/schema;checkpoint_recorded~data/checkpoint;error~data/error",
    "output_notices": {
        "schema": {"description": "Publishes the schema notice downstream unchanged."},
        "forward": {"description": "Forwards a row whose identifier is not checkpointed."},
        "skipped": {"description": "Publishes a row whose identifier is already checkpointed."},
        "checkpoint_recorded": {"description": "Emitted only after the identifier is durably appended."},
        "error": {"description": "A checkpoint could not be persisted. Payload keys: error, key."},
    },
})
class ProgressTrackerOid(OidComponent):
    """Filters rows against a durable, append-only identifier journal."""

    async def start(self) -> None:
        await super().start()
        self._state_file_abs = os.path.abspath(self.state_file)
        self._completed_keys: Set[str] = await asyncio.to_thread(self._load_keys)
        self._checkpoint_lock = asyncio.Lock()

    def _load_keys(self) -> Set[str]:
        """Load the journal. A missing journal means no work has completed yet."""
        path = Path(self._state_file_abs)
        if not path.exists():
            return set()
        if not path.is_file():
            raise RuntimeError(f"Progress state path is not a file: {path}")
        with path.open("r", encoding="utf-8", newline="") as journal:
            keys = {line.rstrip("\r\n") for line in journal}
        keys.discard("")
        logger.info("Loaded %d completed keys from journal %s", len(keys), path)
        return keys

    def _append_key(self, key: str) -> None:
        """Append one key and force it to durable storage before acknowledging it."""
        path = Path(self._state_file_abs)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as journal:
            journal.write(f"{key}\n")
            journal.flush()
            os.fsync(journal.fileno())

    async def handle_schema(self, notice: str, message: dict) -> None:
        await self._notify("schema", message)

    async def handle_row(self, notice: str, message: dict) -> None:
        key = self._resolve_key(message)
        if not key:
            logger.warning("Could not resolve identifier path %r; forwarding row.", self.identifier_path)
            await self._notify("forward", message)
        elif key in self._completed_keys:
            await self._notify("skipped", message)
        else:
            await self._notify("forward", message)

    async def handle_checkpoint(self, notice: str, message: dict) -> None:
        key = self._resolve_key(message)
        if not key:
            logger.warning("Could not resolve checkpoint identifier path %r.", self.identifier_path)
            return
        if "\n" in key or "\r" in key:
            await self._notify("error", {"error": "Checkpoint identifier cannot contain a line break.", "key": key})
            return

        async with self._checkpoint_lock:
            if key in self._completed_keys:
                return
            try:
                await asyncio.to_thread(self._append_key, key)
            except OSError as exc:
                logger.exception("Failed to persist checkpoint key %r", key)
                await self._notify("error", {"error": str(exc), "key": key})
                return
            self._completed_keys.add(key)

        await self._notify("checkpoint_recorded", message)

    def _resolve_key(self, message: Any) -> str:
        if not isinstance(message, dict):
            return "" if message is None else str(message)
        current: Any = message
        for part in self.identifier_path.split("."):
            if not isinstance(current, dict) or part not in current:
                return ""
            current = current[part]
        return "" if current is None else str(current)
