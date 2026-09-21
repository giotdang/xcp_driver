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
