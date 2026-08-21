"""
data:progress-tracker — Progress tracking and resume checkpoint component.

Filters out already processed dataset rows based on a persistent state file.
Loads completed keys from an external output file (e.g. written by data:csv-writer) on start,
and tracks progress in-memory during execution without performing any file writes.
"""
import logging
import os
import csv

from noid.core.component import Noid, OidComponent

logger = logging.getLogger(__name__)


@Noid.component({
    "id": "data:progress-tracker",
    "name": "Progress Tracker",
    "description": (
        "Filters out already processed dataset rows based on an output file "
        "written by a component like data:csv-writer."
    ),
    "properties": {
        "state_file": {
            "default": "output.csv",
            "description": "Path to the output file (CSV or TXT) to read completed keys from on startup.",
        },
        "identifier_path": {
            "default": "index",
            "description": "Dotted path in the incoming row to resolve the unique identifier (e.g. 'index' or 'row.name').",
        },
    },
    "receive": {
        "schema": {
            "description": "Optional schema notice to dynamically set the progress file name based on the schema label."
        },
        "row": {
            "description": "Incoming row to check. If already processed, it is skipped. Otherwise, it is forwarded."
        },
        "checkpoint": {
            "description": "Signals that a row was successfully completed. Its identifier is updated in memory."
        },
    },
    "publish": "forward~data/row;skipped~data/skipped;schema~data/schema;checkpoint_recorded~data/checkpoint",
    "output_notices": {
        "schema": {
            "description": "Publishes the schema notice downstream."
        },
        "forward": {
            "description": "Forwards the incoming row if it has not been processed yet."
        },
        "skipped": {
            "description": "Publishes the skipped row notice if it has already been processed."
        },
        "checkpoint_recorded": {
            "description": "Publishes the recorded checkpoint payload."
        },
    },
})
class ProgressTrackerOid(OidComponent):
    """Filters processed items using an external output file as the progress state."""

    async def start(self) -> None:
        await super().start()
        self._completed_keys = set()

        state_file_path = getattr(self, "state_file", "output.csv")
        self._state_file_abs = os.path.abspath(state_file_path)

        self._load_keys_from_file()

    def _load_keys_from_file(self) -> None:
        # Check for temp file first since csv-writer writes to it during the run
        tmp_file = f"{self._state_file_abs}.tmp"
        file_to_read = tmp_file if os.path.exists(tmp_file) else self._state_file_abs

        if not os.path.exists(file_to_read):
            return

        # If it is a CSV file
        if file_to_read.endswith(".csv") or file_to_read.endswith(".csv.tmp"):
            try:
                id_col = self.identifier_path.split(".")[-1]
                with open(file_to_read, "r", newline="", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    try:
                        headers = next(reader)
                    except StopIteration:
                        return

                    f.seek(0)
                    dict_reader = csv.DictReader(f)
                    for row in dict_reader:
                        key = row.get(id_col)
                        if key:
                            self._completed_keys.add(key)

                logger.info(
                    "Loaded %d completed keys from CSV %s using column %r",
                    len(self._completed_keys),
                    file_to_read,
                    id_col,
                )
            except Exception as exc:
                logger.error(
                    "Failed to read progress CSV file %s: %s",
                    file_to_read,
                    exc,
                )
        else:
            # Fallback to plain text format
            try:
                with open(file_to_read, "r", encoding="utf-8") as f:
                    for line in f:
                        key = line.strip()
                        if key:
                            self._completed_keys.add(key)
                logger.info(
                    "Loaded %d completed keys from text file %s",
                    len(self._completed_keys),
                    file_to_read,
                )
            except Exception as exc:
                logger.error(
                    "Failed to read progress text file %s: %s",
                    file_to_read,
                    exc,
                )

    async def handle_schema(self, notice: str, message: dict) -> None:
        # Dynamically determine the file name based on the schema label
        label = message.get("label", "") if isinstance(message, dict) else ""
        if label:
            # Clean up the label to make it a safe filename
            safe_label = "".join(
                c for c in label if c.isalnum() or c in "._-"
            ).rstrip()
            if safe_label:
                base, _ = os.path.splitext(safe_label)
                dir_name = os.path.dirname(self._state_file_abs)
                self.state_file = os.path.join(dir_name, f"{base}_output.csv")
                self._state_file_abs = os.path.abspath(self.state_file)
                self._completed_keys = set()
                self._load_keys_from_file()

        await self._notify("schema", message)

    async def handle_row(self, notice: str, message: dict) -> None:
        key = self._resolve_key(message)
        if not key:
            logger.warning(
                "Could not resolve identifier key using path %r in message: %s. Forwarding.",
                self.identifier_path,
                message,
            )
            await self._notify("forward", message)
            return

        if key in self._completed_keys:
            logger.info("Skipping already processed row key: %s", key)
            await self._notify("skipped", message)
        else:
            await self._notify("forward", message)

    async def handle_checkpoint(self, notice: str, message: dict) -> None:
        key = self._resolve_key(message)
        if not key:
            logger.warning(
                "Could not resolve checkpoint key using path %r in message: %s.",
                self.identifier_path,
                message,
            )
            return

        if key not in self._completed_keys:
            self._completed_keys.add(key)
            logger.debug("Checkpoint recorded in-memory: %s", key)
            await self._notify("checkpoint_recorded", message)

    def _resolve_key(self, message: dict) -> str:
        if not isinstance(message, dict):
            return str(message)

        path = getattr(self, "identifier_path", "index")
        current = message
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return ""
            current = current[part]
        return str(current)
