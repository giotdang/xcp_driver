"""Calibration dataset export/import — a plain JSON snapshot of CalibrationView
tree values (spec: docs/superpowers/specs/2026-09-19-calibration-dataset-export-
import-design.md).

Pure functions, no Qt dependency, independently unit-testable. File I/O
(QFileDialog, json.dump/json.load) stays in ui/calibration_view.py; the Session
layer (session/real.py, session/fake.py) is the only caller of this module from
outside a2l/ — xcptool.ui may never import xcptool.a2l directly (AST-enforced by
tests/test_boundaries.py).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .types import A2LDatabase

FORMAT_VERSION = 1
TOOL_VERSION = "0.1.0"

__all__ = [
    "FORMAT_VERSION", "TOOL_VERSION",
    "SkipReason", "DatasetImportResult",
    "build_dataset", "apply_dataset",
]


def _a2l_checksum(a2l_path: Path) -> str:
    return "sha256:" + hashlib.sha256(a2l_path.read_bytes()).hexdigest()


def build_dataset(values: dict[str, str], db: A2LDatabase, a2l_path: Path) -> dict:
    """Build the JSON-serializable dict (spec §3) from a name->text map.

    Does not touch the filesystem except reading `a2l_path` once, to compute the
    traceability checksum. `db` is accepted (matches the spec's signature and
    keeps the door open for future per-value metadata) but unused today — values
    are already-formatted text supplied by the caller.
    """
    del db  # unused today, kept in the signature per spec §4
    return {
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "exported_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "a2l_filename": a2l_path.name,
        "a2l_checksum": _a2l_checksum(a2l_path),
        "values": dict(values),
    }


@dataclass
class SkipReason:
    name: str
    reason: str  # "not found in A2L" | "datatype/size mismatch" | "value is not text"


@dataclass
class DatasetImportResult:
    matched: dict[str, str] = field(default_factory=dict)
    skipped: list[SkipReason] = field(default_factory=list)
    a2l_mismatch_warning: str | None = None


def apply_dataset(
    payload: dict, db: A2LDatabase, a2l_path: Path | None = None,
) -> DatasetImportResult:
    """Validate `payload` and cross-check each entry against `db.characteristics`.

    Raises:
        ValueError: payload is not the expected JSON shape — missing
            'format_version'/'values', wrong types, or an unrecognized
            format_version. This is an all-or-nothing parse gate, distinct from
            the per-entry tolerance below (unknown name / size mismatch just
            skip that one entry).
    """
    if not isinstance(payload, dict):
        raise ValueError("Dataset file must contain a JSON object")
    if "format_version" not in payload or "values" not in payload:
        raise ValueError("Dataset file missing 'format_version' or 'values'")
    if payload["format_version"] != FORMAT_VERSION:
        raise ValueError(f"Unsupported dataset format_version: {payload['format_version']!r}")
    values = payload["values"]
    if not isinstance(values, dict):
        raise ValueError("Dataset 'values' must be a JSON object")

    warning = _checksum_warning(payload, a2l_path)

    matched: dict[str, str] = {}
    skipped: list[SkipReason] = []
    for name, text in values.items():
        if not isinstance(text, str):
            skipped.append(SkipReason(name=name, reason="value is not text"))
            continue
        char = db.characteristics.get(name)
        if char is None:
            skipped.append(SkipReason(name=name, reason="not found in A2L"))
            continue
        part_count = len(text.split(","))
        if part_count not in (1, char.array_size):
            skipped.append(SkipReason(name=name, reason="datatype/size mismatch"))
            continue
        matched[name] = text

    return DatasetImportResult(matched=matched, skipped=skipped, a2l_mismatch_warning=warning)


def _checksum_warning(payload: dict, a2l_path: Path | None) -> str | None:
    checksum = payload.get("a2l_checksum")
    if not checksum:
        return None
    if a2l_path is None or not a2l_path.is_file():
        return "Could not verify dataset's source A2L (no A2L file to compare against)."
    if _a2l_checksum(a2l_path) != checksum:
        filename = payload.get("a2l_filename", "?")
        return f"Dataset was exported from a different A2L ({filename}) — values may not match."
    return None
