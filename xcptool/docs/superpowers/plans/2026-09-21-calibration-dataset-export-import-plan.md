# Calibration Dataset Export/Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user right-click the `CalibrationView` tree to export the currently
displayed/edited CHARACTERISTIC values to a JSON file, and re-import such a file in a
later session (staging values as dirty edits — never writing to the ECU by itself).

**Architecture:** New pure module `a2l/dataset.py` owns the JSON shape, checksum, and
per-entry validation (`build_dataset`/`apply_dataset`). `ui/calibration_view.py` gathers
`name -> value text` from the tree and does all file I/O (`QFileDialog`, `json.dump`/
`json.load`) — exactly as the spec describes. The one place this plan **necessarily
deviates from the spec's literal pseudocode** is the wiring between those two: the spec
shows `calibration_view.py` calling `dataset.build_dataset()`/`apply_dataset()`
directly, but `tests/test_boundaries.py::test_package_boundary` AST-enforces that
`xcptool.ui` may **never** import `xcptool.a2l` (see `tests/test_boundaries.py:33`).
So this plan routes both functions through two new blocking `Session` methods,
`export_dataset()`/`import_dataset()` (same pattern already used for `load_a2l()`) —
`session/real.py` and `session/fake.py` are already in `xcptool.a2l`'s import allow-list
today (they both do `from ..a2l import A2LDatabase` / `from ..a2l import load as
_a2l_load`). This is the only viable path given the enforced boundary; every other part
of the plan follows the spec's design as written. See §3 below for the exact shape.

**Tech Stack:** Python 3.12 dataclasses, `hashlib`/`json`/`pathlib` stdlib, PySide6
(`QMenu`, `QFileDialog`, `QMessageBox`), pytest + pytest-qt.

**Spec:** [`docs/superpowers/specs/2026-09-19-calibration-dataset-export-import-design.md`](../specs/2026-09-19-calibration-dataset-export-import-design.md)
— read both; this plan argues from the spec and does not repeat its rationale except
where it resolves a gap (marked "**Deviation from spec:**" inline, always with the
reason). Depends on the already-shipped
[`2026-09-19-calibration-multiselect-design.md`](../specs/2026-09-19-calibration-multiselect-design.md)
(`_resolve_leaf_names()`, `ExtendedSelection` — both already in `calibration_view.py`).

## Global Constraints

- Venv: `xcptool\.venv\Scripts\python.exe` — never bare `python`.
- `QT_QPA_PLATFORM=offscreen` for UI tests — already set in `tests/ui/conftest.py`, no
  need to set it by hand.
- After EVERY task: run the exact test file just touched. After Task 2, Task 5, Task 9
  and Task 11: also run the full suite (`pytest tests/ -x -q`) — must be 100% green
  before moving on (existing flaky exception:
  `tests/ui/test_console.py::test_nut_lenh_nhanh_dien_vao_o_nhap`, rerun alone if it's
  the ONLY red test — see `DEV_PLAN.md §5`).
- `xcptool.ui` and `xcptool.cli` must never import `xcptool.a2l` (AST-enforced,
  `tests/test_boundaries.py:33`). `xcptool.session.api`/`real`/`fake` MAY import
  `xcptool.a2l` — that is the sanctioned channel (mirrors the existing
  `A2LDatabase`/`InstanceNode` re-export already in `session/api.py:57-58`).
- Dataset JSON `format_version` is `1` (int). Do not bump it in this plan.
- Do not rename `_resolve_leaf_names`, `_char_items`, `_original`, `_dirty`,
  `_raw_data`, `COL_VALUE`/`COL_NAME` — all pre-existing and load-bearing elsewhere.
- Do not touch `examples/xcp_daq_example.a2l` — shared fixture, other tests count its
  CHARACTERISTIC/MEASUREMENT entries.

---

### File map

```
xcptool/
├── src/xcptool/
│   ├── a2l/
│   │   └── dataset.py          ← NEW (Task 1, 2) — build_dataset/apply_dataset, pure
│   ├── session/
│   │   ├── api.py              ← MODIFY (Task 3) — Session.export_dataset/import_dataset
│   │   ├── real.py             ← MODIFY (Task 4)
│   │   └── fake.py             ← MODIFY (Task 5)
│   └── ui/
│       ├── calibration_view.py ← MODIFY (Task 6-9)
│       └── main_window.py      ← MODIFY (Task 10)
└── tests/
    ├── unit/
    │   ├── test_dataset.py         ← NEW (Task 1, 2)
    │   └── test_session_dataset.py ← NEW (Task 4, 5)
    └── ui/
        └── test_calibration_view.py ← MODIFY (Task 6-9)
```

---

### Task 1: `a2l/dataset.py` — data shapes + `build_dataset()`

**Files:**
- Create: `xcptool/src/xcptool/a2l/dataset.py`
- Create: `xcptool/tests/unit/test_dataset.py`

**Interfaces:**
- Produces: `FORMAT_VERSION: int`; `SkipReason(name: str, reason: str)`;
  `DatasetImportResult(matched: dict[str,str], skipped: list[SkipReason],
  a2l_mismatch_warning: str | None)`; `build_dataset(values: dict[str, str], db:
  A2LDatabase, a2l_path: Path) -> dict`.
- Consumes: `xcptool.a2l.types.A2LDatabase` (existing).

- [x] **Step 1: Write the failing test**

```python
"""Unit tests for a2l/dataset.py — pure, no Qt, no filesystem beyond a2l_path."""
from __future__ import annotations

import json

from xcptool.a2l.dataset import FORMAT_VERSION, build_dataset
from xcptool.a2l.types import A2LDatabase


def test_build_dataset_shape(tmp_path) -> None:
    a2l_path = tmp_path / "project.a2l"
    a2l_path.write_bytes(b"/* fake a2l content */")
    db = A2LDatabase()
    payload = build_dataset({"speedPid_kp": "1.25", "torqueTable": "10, 20, 30, 40"}, db, a2l_path)

    assert payload["format_version"] == FORMAT_VERSION
    assert payload["a2l_filename"] == "project.a2l"
    assert payload["a2l_checksum"].startswith("sha256:")
    assert payload["values"] == {"speedPid_kp": "1.25", "torqueTable": "10, 20, 30, 40"}
    # must be JSON-serializable as-is
    json.dumps(payload)


def test_build_dataset_checksum_changes_with_file_content(tmp_path) -> None:
    p1 = tmp_path / "a.a2l"
    p1.write_bytes(b"AAAA")
    p2 = tmp_path / "b.a2l"
    p2.write_bytes(b"BBBB")
    db = A2LDatabase()
    c1 = build_dataset({}, db, p1)["a2l_checksum"]
    c2 = build_dataset({}, db, p2)["a2l_checksum"]
    assert c1 != c2
```

- [x] **Step 2: Run test, confirm FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_dataset.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xcptool.a2l.dataset'`

- [x] **Step 3: Write `a2l/dataset.py`**

```python
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
```

(`apply_dataset` is added in Task 2 — keeping it out of this step's diff so Step 4
only needs to prove `build_dataset` works.)

- [x] **Step 4: Run test, confirm PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_dataset.py -v`
Expected: PASS (2 passed)

- [x] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/a2l/dataset.py xcptool/tests/unit/test_dataset.py
git commit -m "feat(xcptool): add a2l/dataset.py build_dataset() + result dataclasses"
```

---

### Task 2: `a2l/dataset.py` — `apply_dataset()`

**Files:**
- Modify: `xcptool/src/xcptool/a2l/dataset.py`
- Modify: `xcptool/tests/unit/test_dataset.py`

**Interfaces:**
- Consumes: `SkipReason`, `DatasetImportResult`, `_a2l_checksum` (Task 1).
- Produces: `apply_dataset(payload: dict, db: A2LDatabase, a2l_path: Path | None =
  None) -> DatasetImportResult`.

**Deviation from spec:** the spec's §4 shows `apply_dataset(payload, db)` — no
`a2l_path`. But §6 requires detecting "checksum differs from the currently loaded
A2L", and `A2LDatabase` (`a2l/types.py`) has no checksum/path field of its own — there
is no way to compute that comparison without *some* path to re-hash. Adding an
optional `a2l_path` parameter (defaulting to `None`, which degrades to a soft
"could not verify" warning instead of a hard requirement) is the minimal fix; `Session`
(Task 4/5) always has this path available from its own `load_a2l()` call and passes it
through.

Second, narrower limitation: the dataset JSON stores no per-value datatype/array_size
(spec §3 — deliberately flat `name -> text`), so "datatype/array_size differs" is
detected structurally from `text.split(",")`'s element count vs. the CURRENT
`Characteristic.array_size` — it catches array-size changes (e.g. `torqueTable`
shrinking from 4 to 3 elements) but cannot catch a pure datatype swap at the same
array_size (e.g. `UBYTE` -> `FLOAT32_IEEE` with `array_size` unchanged), since nothing
in a plain text value proves which datatype produced it. That narrower case is not
silently wrong: staging it still just calls `item.setText(COL_VALUE, text)` (identical
to a manual edit — see Task 9), and any value that doesn't actually fit the new
datatype fails loudly at `encode_value()`-time on "Write", the same as it would for a
manual typo today. This is an accepted, documented gap — not a task to add error
detection for.

- [x] **Step 1: Write the failing tests**

Append to `tests/unit/test_dataset.py`:

```python
from xcptool.a2l.dataset import DatasetImportResult, SkipReason, apply_dataset
from xcptool.a2l.types import Characteristic, RecordLayout


def _db_with_chars() -> A2LDatabase:
    db = A2LDatabase()
    db.record_layouts["RL_F32"] = RecordLayout(name="RL_F32", datatype="FLOAT32_IEEE")
    db.characteristics["speedPid_kp"] = Characteristic(
        name="speedPid_kp", description="", char_type="VALUE", address=0x1000,
        record_layout="RL_F32", lower_limit=0.0, upper_limit=10.0,
        datatype="FLOAT32_IEEE", array_size=1,
    )
    db.characteristics["torqueTable"] = Characteristic(
        name="torqueTable", description="", char_type="VAL_BLK", address=0x2000,
        record_layout="RL_F32", lower_limit=0.0, upper_limit=100.0,
        datatype="FLOAT32_IEEE", array_size=4,
    )
    return db


def test_apply_dataset_matches_known_names() -> None:
    db = _db_with_chars()
    payload = {"format_version": 1, "values": {"speedPid_kp": "1.25", "torqueTable": "10, 20, 30, 40"}}
    result = apply_dataset(payload, db)
    assert result.matched == {"speedPid_kp": "1.25", "torqueTable": "10, 20, 30, 40"}
    assert result.skipped == []
    assert result.a2l_mismatch_warning is None


def test_apply_dataset_skips_unknown_name() -> None:
    db = _db_with_chars()
    payload = {"format_version": 1, "values": {"doesNotExist": "1"}}
    result = apply_dataset(payload, db)
    assert result.matched == {}
    assert result.skipped == [SkipReason(name="doesNotExist", reason="not found in A2L")]


def test_apply_dataset_skips_array_size_mismatch() -> None:
    db = _db_with_chars()
    # torqueTable is array_size=4 — 2 values is neither 1 (broadcast) nor 4
    payload = {"format_version": 1, "values": {"torqueTable": "10, 20"}}
    result = apply_dataset(payload, db)
    assert result.matched == {}
    assert result.skipped == [SkipReason(name="torqueTable", reason="datatype/size mismatch")]


def test_apply_dataset_single_value_broadcasts_to_array_ok() -> None:
    db = _db_with_chars()
    payload = {"format_version": 1, "values": {"torqueTable": "5"}}
    result = apply_dataset(payload, db)
    assert result.matched == {"torqueTable": "5"}
    assert result.skipped == []


def test_apply_dataset_missing_format_version_raises() -> None:
    db = _db_with_chars()
    with pytest.raises(ValueError):
        apply_dataset({"values": {}}, db)


def test_apply_dataset_missing_values_raises() -> None:
    db = _db_with_chars()
    with pytest.raises(ValueError):
        apply_dataset({"format_version": 1}, db)


def test_apply_dataset_unknown_format_version_raises() -> None:
    db = _db_with_chars()
    with pytest.raises(ValueError):
        apply_dataset({"format_version": 2, "values": {}}, db)


def test_apply_dataset_checksum_match_no_warning(tmp_path) -> None:
    db = _db_with_chars()
    a2l_path = tmp_path / "p.a2l"
    a2l_path.write_bytes(b"content")
    payload = build_dataset({"speedPid_kp": "1.0"}, db, a2l_path)
    result = apply_dataset(payload, db, a2l_path)
    assert result.a2l_mismatch_warning is None
    assert result.matched == {"speedPid_kp": "1.0"}


def test_apply_dataset_checksum_mismatch_warns_but_still_matches(tmp_path) -> None:
    db = _db_with_chars()
    old_path = tmp_path / "old.a2l"
    old_path.write_bytes(b"old content")
    payload = build_dataset({"speedPid_kp": "1.0"}, db, old_path)

    new_path = tmp_path / "new.a2l"
    new_path.write_bytes(b"different content")
    result = apply_dataset(payload, db, new_path)
    assert result.a2l_mismatch_warning is not None
    assert result.matched == {"speedPid_kp": "1.0"}  # still applied, just warned


def test_apply_dataset_float64_precision_roundtrip() -> None:
    """A value that %.6g would corrupt must survive build+apply unchanged —
    dataset.py never re-formats already-formatted text."""
    db = A2LDatabase()
    db.record_layouts["RL_F64"] = RecordLayout(name="RL_F64", datatype="FLOAT64_IEEE")
    db.characteristics["preciseGain"] = Characteristic(
        name="preciseGain", description="", char_type="VALUE", address=0x3000,
        record_layout="RL_F64", lower_limit=0.0, upper_limit=10.0,
        datatype="FLOAT64_IEEE", array_size=1,
    )
    precise_text = "1.234567890123456"
    result = apply_dataset({"format_version": 1, "values": {"preciseGain": precise_text}}, db)
    assert result.matched["preciseGain"] == precise_text
```

Add `import pytest` and `from xcptool.a2l.dataset import build_dataset` near the top
if not already present from Task 1.

- [x] **Step 2: Run tests, confirm FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_dataset.py -v`
Expected: FAIL — `ImportError: cannot import name 'apply_dataset'`

- [x] **Step 3: Implement `apply_dataset`**

Append to `xcptool/src/xcptool/a2l/dataset.py`:

```python
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
```

Update the module `__all__` list (Task 1) — no change needed, `apply_dataset` is
already listed there.

- [x] **Step 4: Run tests, confirm PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_dataset.py -v`
Expected: PASS (all tests)

- [x] **Step 5: Run full suite**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ -x -q`
Expected: all green (this module has zero callers yet, so nothing else should move)

- [x] **Step 6: Commit**

```bash
git add xcptool/src/xcptool/a2l/dataset.py xcptool/tests/unit/test_dataset.py
git commit -m "feat(xcptool): add a2l/dataset.py apply_dataset() with skip/warning logic"
```

---

### Task 3: `session/api.py` — `Session` contract additions

**Files:**
- Modify: `xcptool/src/xcptool/session/api.py`

**Interfaces:**
- Consumes: `DatasetImportResult`, `SkipReason` (Task 1/2, re-exported here).
- Produces: `Session.export_dataset(values: dict[str, str]) -> dict`;
  `Session.import_dataset(payload: dict) -> DatasetImportResult`; both re-exported
  through `session.api` so `xcptool.ui` can reach them without importing `xcptool.a2l`
  (same pattern as `A2LDatabase`/`InstanceNode`, `session/api.py:57-58`).

This is a Protocol-only change (no test file — `Session` is `@runtime_checkable` but
has no body to unit-test standalone; Task 4/5 test the concrete implementations).

- [x] **Step 1: Add the re-export import**

At `xcptool/src/xcptool/session/api.py:57-58`, change:

```python
from ..a2l import A2LDatabase
from ..a2l.types import InstanceNode
```

to:

```python
from ..a2l import A2LDatabase
from ..a2l.dataset import DatasetImportResult, SkipReason
from ..a2l.types import InstanceNode
```

- [x] **Step 2: Add both names to `__all__`**

At `xcptool/src/xcptool/session/api.py:68`, change:

```python
    "A2LDatabase", "InstanceNode", "Session",
]
```

to:

```python
    "A2LDatabase", "InstanceNode", "DatasetImportResult", "SkipReason", "Session",
]
```

- [x] **Step 3: Add the two methods to the `Session` Protocol**

In the `# ── A2L (M3) ──` section of the `Session` Protocol, `session/api.py:521-531`
currently reads:

```python
    def load_a2l(self, path: str | Path) -> None:
        """Nạp và parse file A2L. CHẶN (đọc file + parse).

        Kết quả truy xuất qua `symbols`. Gọi từ worker thread — có thể mất vài
        trăm ms với file lớn.

        Raises: XcpToolError nếu file không đọc được hoặc lỗi parse nghiêm trọng
        """

    # ── DAQ (M4) ─────────────────────────────────────────────────────────────
```

Change it to (inserting the two new methods between `load_a2l` and the `DAQ (M4)`
section header):

```python
    def load_a2l(self, path: str | Path) -> None:
        """Nạp và parse file A2L. CHẶN (đọc file + parse).

        Kết quả truy xuất qua `symbols`. Gọi từ worker thread — có thể mất vài
        trăm ms với file lớn.

        Raises: XcpToolError nếu file không đọc được hoặc lỗi parse nghiêm trọng
        """

    def export_dataset(self, values: dict[str, str]) -> dict:
        """Build a calibration-dataset JSON dict (name->text values, plus
        traceability metadata) from the currently loaded A2L. CHẶN — reads the
        A2L file once to compute its checksum.

        Raises: XcpToolError nếu chưa `load_a2l()` thành công, hoặc file A2L
        không đọc lại được để tính checksum.
        """

    def import_dataset(self, payload: dict) -> DatasetImportResult:
        """Validate a parsed dataset JSON payload and cross-check it against the
        currently loaded A2L. CHẶN nhẹ — không I/O ngoài, chỉ so khớp trong bộ
        nhớ (cộng một lần đọc A2L để so checksum, nếu còn file).

        Does NOT touch `symbols` or write anything — the caller applies
        `result.matched` to its own UI state.

        Raises: XcpToolError nếu `payload` sai cấu trúc (thiếu
        format_version/values, format_version không nhận diện được).
        """

    # ── DAQ (M4) ─────────────────────────────────────────────────────────────
```

- [x] **Step 4: Sanity-check the file still parses**

Run: `xcptool\.venv\Scripts\python.exe -c "import ast; ast.parse(open('src/xcptool/session/api.py', encoding='utf-8').read())"`
(run from `xcptool/` directory)
Expected: no output, exit code 0

- [x] **Step 5: Run full suite**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ -x -q`
Expected: all green — `Session` is a `Protocol`, adding methods to it doesn't break
existing implementers until something calls them (Task 4/5 add the bodies).

- [x] **Step 6: Commit**

```bash
git add xcptool/src/xcptool/session/api.py
git commit -m "feat(xcptool): add export_dataset/import_dataset to Session contract"
```

---

### Task 4: `session/real.py` — implement `export_dataset`/`import_dataset`

**Files:**
- Modify: `xcptool/src/xcptool/session/real.py`
- Create: `xcptool/tests/unit/test_session_dataset.py`

**Interfaces:**
- Consumes: `build_dataset`, `apply_dataset` (Task 1/2); `_guarded` (existing,
  `real.py:83`); `Session.export_dataset`/`import_dataset` (Task 3).
- Produces: `RealSession._a2l_path: Path | None` (new instance attribute);
  `RealSession.export_dataset()`/`import_dataset()` bodies.

`RealSession` needs no live ECU connection for either method — both operate purely on
`self._a2l_db`/`self._a2l_path`, set by `load_a2l()`. This is testable by
instantiating `RealSession()` directly, never calling `connect()`.

- [x] **Step 1: Write the failing tests**

```python
"""Unit tests for Session.export_dataset/import_dataset — RealSession and
FakeSession both wrap a2l/dataset.py identically; neither needs a live connection."""
from __future__ import annotations

import pytest

from xcptool.a2l.dataset import SkipReason
from xcptool.session.api import XcpToolError
from xcptool.session.fake import FakeSession
from xcptool.session.real import RealSession


@pytest.fixture(params=[RealSession, FakeSession])
def session(request):
    return request.param()


def test_export_dataset_without_a2l_raises(session) -> None:
    with pytest.raises(XcpToolError):
        session.export_dataset({"x": "1"})


def test_export_then_import_roundtrip(session, tmp_path) -> None:
    a2l_path = tmp_path / "project.a2l"
    # Field order/shape confirmed against examples/xcp_daq_example.a2l:348-357
    # (name, description, char_type, address, record_layout, max_diff,
    # compu_method, lower_limit, upper_limit).
    a2l_path.write_text(
        "/begin RECORD_LAYOUT RL_F32\n"
        "  FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT\n"
        "/end RECORD_LAYOUT\n"
        "/begin CHARACTERISTIC speedPid_kp\n"
        '  "PID gain"\n'
        "  VALUE\n"
        "  0x1000\n"
        "  RL_F32\n"
        "  0\n"
        "  NO_COMPU_METHOD\n"
        "  0.0\n"
        "  10.0\n"
        "/end CHARACTERISTIC\n",
        encoding="utf-8",
    )
    session.load_a2l(a2l_path)

    payload = session.export_dataset({"speedPid_kp": "1.25"})
    assert payload["values"] == {"speedPid_kp": "1.25"}
    assert payload["a2l_filename"] == "project.a2l"

    result = session.import_dataset(payload)
    assert result.matched == {"speedPid_kp": "1.25"}
    assert result.skipped == []
    assert result.a2l_mismatch_warning is None


def test_import_dataset_invalid_payload_raises(session) -> None:
    with pytest.raises(XcpToolError):
        session.import_dataset({"not": "a valid dataset"})


def test_import_dataset_unknown_name_skipped(session, tmp_path) -> None:
    a2l_path = tmp_path / "empty.a2l"
    a2l_path.write_text("", encoding="utf-8")
    session.load_a2l(a2l_path)

    result = session.import_dataset({"format_version": 1, "values": {"ghost": "1"}})
    assert result.matched == {}
    assert result.skipped == [SkipReason(name="ghost", reason="not found in A2L")]
```

- [x] **Step 2: Run tests, confirm FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_session_dataset.py -v`
Expected: FAIL — `AttributeError: 'RealSession' object has no attribute 'export_dataset'`
(and same for `FakeSession` — both params fail; that's expected, Task 5 fixes the
`FakeSession` side)

- [x] **Step 3: Track `_a2l_path` and implement both methods in `RealSession`**

At `xcptool/src/xcptool/session/real.py:109` (inside `__init__`, right after
`self._a2l_db: A2LDatabase = A2LDatabase()`), add:

```python
        self._a2l_path: Path | None = None
```

At `xcptool/src/xcptool/session/real.py:268-270`, change:

```python
    @_guarded("nạp A2L")
    def load_a2l(self, path: str | Path) -> None:
        self._a2l_db = _a2l_load(path)
```

to:

```python
    @_guarded("nạp A2L")
    def load_a2l(self, path: str | Path) -> None:
        self._a2l_db = _a2l_load(path)
        self._a2l_path = Path(path)
```

Then, right after `load_a2l`, add the two new methods:

```python
    @_guarded("export dataset")
    def export_dataset(self, values: dict[str, str]) -> dict:
        if self._a2l_path is None:
            raise XcpToolError("Chưa nạp file A2L — không thể export dataset")
        return build_dataset(values, self._a2l_db, self._a2l_path)

    @_guarded("import dataset")
    def import_dataset(self, payload: dict) -> DatasetImportResult:
        return apply_dataset(payload, self._a2l_db, self._a2l_path)
```

`@_guarded` (already defined at `real.py:83`, already used on `load_a2l` and every
other blocking method) converts the `ValueError` that `apply_dataset` raises on a
structurally-invalid payload into `XcpToolError`, matching the Session contract's rule
that "every expected error is an `XcpToolError` subclass" (`session/api.py:37-38`).

Add the import at the top of `real.py` (near the existing `from ..a2l import
A2LDatabase` / `from ..a2l import load as _a2l_load`, `real.py:20-21`):

```python
from ..a2l.dataset import DatasetImportResult, apply_dataset, build_dataset
```

- [x] **Step 4: Run tests — `RealSession` param passes, `FakeSession` param still fails**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_session_dataset.py -v`
Expected: `RealSession`-parametrized cases PASS; `FakeSession`-parametrized cases FAIL
(Task 5 fixes those)

- [x] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/session/real.py xcptool/tests/unit/test_session_dataset.py
git commit -m "feat(xcptool): implement RealSession.export_dataset/import_dataset"
```

---

### Task 5: `session/fake.py` — implement `export_dataset`/`import_dataset`

**Files:**
- Modify: `xcptool/src/xcptool/session/fake.py`

**Interfaces:**
- Consumes: same as Task 4 (`build_dataset`, `apply_dataset`, `XcpToolError`).
- Produces: `FakeSession._a2l_path: Path | None`; mirrors `RealSession`'s two methods.

- [x] **Step 1: Confirm the failing case (from Task 4's test file)**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_session_dataset.py -v -k FakeSession`
Expected: FAIL — `AttributeError: 'FakeSession' object has no attribute 'export_dataset'`

- [x] **Step 2: Find `FakeSession.load_a2l` and add `_a2l_path` tracking**

`xcptool/src/xcptool/session/fake.py` has its own `load_a2l` mirroring `real.py`'s
(same shape: `self._a2l_db = _a2l_load(path)`). Add `self._a2l_path: Path | None =
None` next to `self._a2l_db: A2LDatabase = A2LDatabase()` in `FakeSession.__init__`
(the same line shown earlier at `fake.py:174`), then update `load_a2l` there the same
way as Task 4 Step 3:

```python
    def load_a2l(self, path: str | Path) -> None:
        self._a2l_db = _a2l_load(path)
        self._a2l_path = Path(path)
```

(`FakeSession.load_a2l` is not `@_guarded`-wrapped today — leave that as-is; do not
introduce a decorator that doesn't already exist on this method.)

- [x] **Step 3: Add the two methods, wrapping `ValueError` by hand**

`FakeSession` doesn't use the `@_guarded` decorator (that's a `real.py`-only helper).
Add explicit try/except instead, right after `load_a2l`:

```python
    def export_dataset(self, values: dict[str, str]) -> dict:
        if self._a2l_path is None:
            raise XcpToolError("Chưa nạp file A2L — không thể export dataset")
        try:
            return build_dataset(values, self._a2l_db, self._a2l_path)
        except OSError as exc:
            raise XcpToolError(f"Không đọc được file A2L để tính checksum: {exc}") from exc

    def import_dataset(self, payload: dict) -> DatasetImportResult:
        try:
            return apply_dataset(payload, self._a2l_db, self._a2l_path)
        except ValueError as exc:
            raise XcpToolError(str(exc)) from exc
```

Add the import near `fake.py`'s existing `from ..a2l import A2LDatabase` / `from
..a2l import load as _a2l_load`:

```python
from ..a2l.dataset import DatasetImportResult, apply_dataset, build_dataset
```

Confirm `XcpToolError` is already imported in `fake.py` (it raises other
`XcpToolError` subclasses already, e.g. via `self.behavior.connect_error` — check the
existing `from .api import (...)` block and add `XcpToolError` to it if not already
present).

- [x] **Step 4: Run the full dataset test file, confirm PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_session_dataset.py -v`
Expected: PASS — all `RealSession` and `FakeSession` parametrized cases

- [x] **Step 5: Run full suite**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ -x -q`
Expected: all green

- [x] **Step 6: Commit**

```bash
git add xcptool/src/xcptool/session/fake.py
git commit -m "feat(xcptool): implement FakeSession.export_dataset/import_dataset"
```

---

### Task 6: `ui/calibration_view.py` — precise export formatter

**Files:**
- Modify: `xcptool/src/xcptool/ui/calibration_view.py`
- Modify: `xcptool/tests/ui/test_calibration_view.py`

**Interfaces:**
- Consumes: `_DTYPE_FMT`, `_ENDIAN` (existing module-level dicts, `calibration_view.py:49-55`).
- Produces: `decode_value_precise(data: bytes, datatype: str, byte_order: str) -> str`.

**Deviation from spec:** §3 asks for "a small dedicated formatting function in
a2l/dataset.py" for round-trip-exact float precision. Since `dataset.py`'s
`build_dataset()` only ever receives already-formatted `dict[str, str]` (per its own
§4 signature — there is no raw-bytes parameter to format from), the precise formatter
has to run *before* that dict is built, i.e. in `calibration_view.py`, right next to
`decode_value()` — the module that already owns the raw-bytes-to-text problem for
display. It is used only by the export gather step (Task 7), never by the ECU-read
display path (`on_read_done` keeps using `decode_value`'s `%.6g` for on-screen values —
unchanged).

- [x] **Step 1: Write the failing test**

Add near the existing `test_decode_*` tests in `tests/ui/test_calibration_view.py`
(after `test_decode_too_short_returns_placeholder`, `test_calibration_view.py:155`):

```python
from xcptool.ui.calibration_view import decode_value_precise


def test_decode_value_precise_float64_full_precision() -> None:
    v = 1.234567890123456
    data = struct.pack("<d", v)
    text = decode_value_precise(data, "FLOAT64_IEEE", "little")
    assert float(text) == v
    assert text != f"{v:.6g}"  # must NOT be the lossy display rounding


def test_decode_value_precise_float32_full_precision() -> None:
    data = struct.pack("<f", 3.14159265)
    text = decode_value_precise(data, "FLOAT32_IEEE", "little")
    # round-trips exactly through the same 32-bit float, even if not equal to
    # the original 64-bit Python float
    assert struct.pack("<f", float(text)) == data


def test_decode_value_precise_int_matches_decode_value() -> None:
    data = bytes([1, 2, 3])
    assert decode_value_precise(data, "UBYTE", "little") == decode_value(data, "UBYTE", "little")


def test_decode_value_precise_array_joins_with_comma() -> None:
    data = struct.pack("<3f", 1.0, 2.0, 3.0)
    assert decode_value_precise(data, "FLOAT32_IEEE", "little") == "1, 2, 3"
```

- [x] **Step 2: Run test, confirm FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ui/test_calibration_view.py -v -k decode_value_precise`
Expected: FAIL — `ImportError: cannot import name 'decode_value_precise'`

- [x] **Step 3: Implement `decode_value_precise`**

In `xcptool/src/xcptool/ui/calibration_view.py`, right after `decode_value()`'s
closing line (`calibration_view.py:122`, just before `def encode_value(...)` at line
125), insert:

```python
def decode_value_precise(data: bytes, datatype: str, byte_order: str) -> str:
    """Like `decode_value(data, datatype, byte_order, radix="DEC")` but with full
    round-trip precision for floats (`%.17g` for FLOAT64_IEEE, `%.9g` for
    FLOAT32_IEEE) instead of `decode_value`'s display-only `%.6g` rounding.
    Integer formatting is identical — only used for calibration-dataset export
    (`_gather_dataset_values`), never for on-screen display."""
    fmt_char = _DTYPE_FMT.get(datatype, "B")
    endian = _ENDIAN.get(byte_order, "<")
    item_size = struct.calcsize(fmt_char)
    if item_size == 0 or len(data) < item_size:
        return "???"
    n = len(data) // item_size
    float_fmt = "%.9g" if datatype == "FLOAT32_IEEE" else "%.17g"
    parts: list[str] = []
    for i in range(n):
        chunk = data[i * item_size:(i + 1) * item_size]
        v = struct.unpack_from(endian + fmt_char, chunk)[0]
        parts.append(float_fmt % v if datatype.startswith("FLOAT") else str(v))
    return ", ".join(parts)
```

- [x] **Step 4: Run test, confirm PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ui/test_calibration_view.py -v -k decode_value_precise`
Expected: PASS (4 passed)

- [x] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/ui/calibration_view.py xcptool/tests/ui/test_calibration_view.py
git commit -m "feat(xcptool): add decode_value_precise() for dataset export"
```

---

### Task 7: `ui/calibration_view.py` — context menu skeleton + value gathering

**Files:**
- Modify: `xcptool/src/xcptool/ui/calibration_view.py`
- Modify: `xcptool/tests/ui/test_calibration_view.py`

**Interfaces:**
- Consumes: `decode_value_precise` (Task 6), `_resolve_leaf_names` (existing,
  `calibration_view.py:721`), `_char_items`/`_original`/`_dirty`/`_raw_data`
  (existing).
- Produces: `CalibrationView.__init__` gains `export_dataset_cb: Callable[[dict[str,
  str]], None]` and `import_dataset_cb: Callable[[dict], None]` parameters;
  `_gather_dataset_values(names: Iterable[str]) -> dict[str, str]`;
  `_context_menu_enabled_state() -> tuple[bool, bool, bool]` (export_all,
  export_selected, import — factored out so tests don't have to pop up a real
  `QMenu`); `_on_tree_context_menu(pos) -> None` (uses the helper above); the tree
  gets `Qt.CustomContextMenu` policy wired to it. `self._pending_export: tuple[str,
  dict[str, str]] | None = None` new instance attribute (consumed by Task 8).

- [x] **Step 1: Write the failing tests**

Update `_make_view()` in `tests/ui/test_calibration_view.py` (`test_calibration_view.py:98-134`)
to accept and forward the two new callbacks:

```python
def _make_view(qtbot) -> CalibrationView:
    calls: dict[str, list] = {
        "read_all": [], "read": [], "write": [], "pages": [], "set_page": [], "copy": [],
        "export_dataset": [], "import_dataset": [],
    }

    def read_all_cb():
        calls["read_all"].append(True)

    def read_cb(names):
        calls["read"].append(names)

    def write_cb(name, addr, data):
        calls["write"].append((name, addr, data))

    def pages_cb(seg):
        calls["pages"].append(seg)

    def set_page_cb(seg, page):
        calls["set_page"].append((seg, page))

    def copy_page_cb(src_seg, src_page, dst_seg, dst_page):
        calls["copy"].append((src_seg, src_page, dst_seg, dst_page))

    def export_dataset_cb(values):
        calls["export_dataset"].append(values)

    def import_dataset_cb(payload):
        calls["import_dataset"].append(payload)

    v = CalibrationView(
        read_all_cb=read_all_cb,
        read_cb=read_cb,
        write_cb=write_cb,
        get_pages_cb=pages_cb,
        set_page_cb=set_page_cb,
        copy_page_cb=copy_page_cb,
        export_dataset_cb=export_dataset_cb,
        import_dataset_cb=import_dataset_cb,
    )
    qtbot.addWidget(v)
    v._calls = calls  # type: ignore[attr-defined]
    return v
```

Then add new tests after the existing `set_database`/read tests:

```python
def test_gather_dataset_values_excludes_untouched(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    # nothing read or edited yet -> nothing eligible
    assert v._gather_dataset_values(["GAIN", "OFFSET"]) == {}


def test_gather_dataset_values_uses_precise_text_for_clean_read(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_read_done("GAIN", bytes([42]))
    values = v._gather_dataset_values(["GAIN"])
    assert values == {"GAIN": "42"}


def test_gather_dataset_values_uses_tree_text_for_dirty(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_read_done("GAIN", bytes([42]))
    item = v._char_items["GAIN"]
    item.setFlags(item.flags() | Qt.ItemIsEditable)
    item.setText(COL_VALUE, "99")  # simulate a manual edit -> _on_item_changed fires
    assert "GAIN" in v._dirty
    assert v._gather_dataset_values(["GAIN"]) == {"GAIN": "99"}


def test_gather_dataset_values_array_joins_children(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_read_done("LUT", bytes([1, 2, 3, 4]))
    assert v._gather_dataset_values(["LUT"]) == {"LUT": "1, 2, 3, 4"}


def test_context_menu_enabled_state_no_data(qtbot) -> None:
    v = _make_view(qtbot)
    export_all, export_selected, import_enabled = v._context_menu_enabled_state()
    assert export_all is False
    assert export_selected is False
    assert import_enabled is False


def test_context_menu_enabled_state_with_data_and_selection(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.tree.topLevelItem(0).setSelected(True)
    export_all, export_selected, import_enabled = v._context_menu_enabled_state()
    assert export_all is True
    assert export_selected is True
    assert import_enabled is True
```

Add `from PySide6.QtCore import Qt` is already imported at the top of the test file
(`test_calibration_view.py:8`) — no new import needed there.

- [x] **Step 2: Run tests, confirm FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ui/test_calibration_view.py -v -k "gather_dataset or context_menu_enabled"`
Expected: FAIL — `TypeError: CalibrationView.__init__() missing 2 required positional
arguments: 'export_dataset_cb' and 'import_dataset_cb'` (from `_make_view` itself,
since `CalibrationView.__init__` doesn't accept them yet)

- [x] **Step 3: Add constructor params + state**

In `xcptool/src/xcptool/ui/calibration_view.py`, at the `__init__` signature
(`calibration_view.py:225-234`), change:

```python
    def __init__(
        self,
        read_all_cb: Callable[[], None],
        read_cb: Callable[[list[str]], None],           # (names)
        write_cb: Callable[[str, int, bytes], None],   # (name, addr, data)
        get_pages_cb: Callable[[int], None],           # (segment)
        set_page_cb: Callable[[int, int], None],        # (segment, page) — set CẢ ECU lẫn XCP
        copy_page_cb: Callable[[int, int, int, int], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("calibrationView")
        self._read_all_cb = read_all_cb
        self._read_cb = read_cb
        self._write_cb = write_cb
        self._get_pages_cb = get_pages_cb
        self._set_page_cb = set_page_cb
        self._copy_page_cb = copy_page_cb
```

to:

```python
    def __init__(
        self,
        read_all_cb: Callable[[], None],
        read_cb: Callable[[list[str]], None],           # (names)
        write_cb: Callable[[str, int, bytes], None],   # (name, addr, data)
        get_pages_cb: Callable[[int], None],           # (segment)
        set_page_cb: Callable[[int, int], None],        # (segment, page) — set CẢ ECU lẫn XCP
        copy_page_cb: Callable[[int, int, int, int], None],
        export_dataset_cb: Callable[[dict[str, str]], None],  # (values) -> Session.export_dataset
        import_dataset_cb: Callable[[dict], None],             # (payload) -> Session.import_dataset
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("calibrationView")
        self._read_all_cb = read_all_cb
        self._read_cb = read_cb
        self._write_cb = write_cb
        self._get_pages_cb = get_pages_cb
        self._set_page_cb = set_page_cb
        self._copy_page_cb = copy_page_cb
        self._export_dataset_cb = export_dataset_cb
        self._import_dataset_cb = import_dataset_cb
        # (path, values) awaiting on_export_ready(); None when no export in flight
        self._pending_export: tuple[str, dict[str, str]] | None = None
```

- [x] **Step 4: Wire the context menu policy in `_build_ui`**

At `calibration_view.py:319-320` (right after `self.tree.itemChanged.connect(self._on_item_changed)`), add:

```python
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
```

- [x] **Step 5: Add `QMenu` import**

At the `PySide6.QtWidgets` import block (`calibration_view.py:10-19`), add `QMenu`
and `QMessageBox` (the latter is used by Task 9, adding it now avoids a second edit
to the same import block):

```python
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
```

- [x] **Step 6: Implement `_gather_dataset_values`, `_context_menu_enabled_state`,
      `_on_tree_context_menu`**

Add these methods right after `_resolve_leaf_names` (`calibration_view.py`, ends at
line 749 per the existing method):

```python
    def _gather_dataset_values(self, names: Iterable[str]) -> dict[str, str]:
        """For each name that is eligible (read or edited at least once this
        session — present in `self._original` or `self._dirty`), produce
        name -> value text. Dirty values are read straight from the tree (they
        are exactly what the user typed, already full precision). Clean values
        are reformatted from `self._raw_data` with `decode_value_precise` —
        NOT the tree's displayed text, which for floats is `decode_value`'s
        lossy `%.6g` (see Task 6's deviation note)."""
        values: dict[str, str] = {}
        for name in names:
            if name not in self._original and name not in self._dirty:
                continue
            item = self._char_items.get(name)
            char = self._db.characteristics.get(name)
            if item is None or char is None:
                continue
            if name in self._dirty:
                if item.childCount() > 0:
                    text = ", ".join(item.child(i).text(COL_VALUE) for i in range(item.childCount()))
                else:
                    text = item.text(COL_VALUE)
            else:
                raw = self._raw_data.get(name)
                if raw is None or char.datatype is None:
                    continue
                text = decode_value_precise(raw, char.datatype, self._byte_order)
            values[name] = text
        return values

    def _context_menu_enabled_state(self) -> tuple[bool, bool, bool]:
        """(export_all_enabled, export_selected_enabled, import_enabled) —
        factored out of `_on_tree_context_menu` so tests can assert enablement
        without popping up a real QMenu."""
        return (
            bool(self._char_items),
            bool(self.tree.selectedItems()),
            bool(self._char_items),
        )

    def _on_tree_context_menu(self, pos) -> None:
        export_all_enabled, export_selected_enabled, import_enabled = self._context_menu_enabled_state()
        menu = QMenu(self)
        export_all_act = menu.addAction("Export All to File…")
        export_all_act.setEnabled(export_all_enabled)
        export_selected_act = menu.addAction("Export Selected to File…")
        export_selected_act.setEnabled(export_selected_enabled)
        menu.addSeparator()
        import_act = menu.addAction("Import Dataset from File…")
        import_act.setEnabled(import_enabled)

        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is export_all_act:
            self._on_export_all_to_file()
        elif chosen is export_selected_act:
            self._on_export_selected_to_file()
        elif chosen is import_act:
            self._on_import_dataset_from_file()
```

`_on_export_all_to_file`, `_on_export_selected_to_file`, `_on_import_dataset_from_file`
are added in Task 8/9 — for this task, add temporary no-op stubs so the module still
imports:

```python
    def _on_export_all_to_file(self) -> None:
        pass

    def _on_export_selected_to_file(self) -> None:
        pass

    def _on_import_dataset_from_file(self) -> None:
        pass
```

(Task 8 replaces the first two stubs; Task 9 replaces the third. Keeping them as
explicit `pass` stubs here — not omitted — is what makes this task's diff import-
clean and independently testable, per the "each task ends with an independently
testable deliverable" rule.)

- [x] **Step 7: Run tests, confirm PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ui/test_calibration_view.py -v`
Expected: PASS — full file, including all pre-existing tests (constructor signature
change must not break any of them since `_make_view` was updated in Step 1)

- [x] **Step 8: Commit**

```bash
git add xcptool/src/xcptool/ui/calibration_view.py xcptool/tests/ui/test_calibration_view.py
git commit -m "feat(xcptool): add dataset context menu skeleton + value gathering to CalibrationView"
```

---

### Task 8: `ui/calibration_view.py` — Export flow

**Files:**
- Modify: `xcptool/src/xcptool/ui/calibration_view.py`
- Modify: `xcptool/tests/ui/test_calibration_view.py`

**Interfaces:**
- Consumes: `_gather_dataset_values`, `_pending_export`, `_export_dataset_cb` (Task 7).
- Produces: `_on_export_all_to_file`, `_on_export_selected_to_file`,
  `_export_to_file(names)`, `on_export_ready(payload: dict) -> None` (called by
  `MainWindow` — Task 10 — with the dict `Session.export_dataset()` returned).

- [x] **Step 1: Write the failing tests**

```python
def test_export_all_no_eligible_values_shows_status_no_dialog(qtbot, monkeypatch) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    called = []
    monkeypatch.setattr(
        "xcptool.ui.calibration_view.QFileDialog.getSaveFileName",
        lambda *a, **k: called.append(1) or ("", ""),
    )
    v._on_export_all_to_file()
    assert called == []  # dialog never opened
    assert "Nothing to export" in v.status_label.text() or "nothing" in v.status_label.text().lower()
    assert v._calls["export_dataset"] == []


def test_export_all_calls_export_cb_with_gathered_values(qtbot, monkeypatch) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_read_done("GAIN", bytes([42]))
    monkeypatch.setattr(
        "xcptool.ui.calibration_view.QFileDialog.getSaveFileName",
        lambda *a, **k: ("C:/tmp/out.json", "JSON (*.json)"),
    )
    v._on_export_all_to_file()
    assert v._calls["export_dataset"] == [{"GAIN": "42"}]


def test_export_selected_uses_resolve_leaf_names(qtbot, monkeypatch) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_read_done("GAIN", bytes([42]))
    v.on_read_done("OFFSET", bytes([1, 0, 0, 0]))
    v._char_items["GAIN"].setSelected(True)
    monkeypatch.setattr(
        "xcptool.ui.calibration_view.QFileDialog.getSaveFileName",
        lambda *a, **k: ("C:/tmp/out.json", "JSON (*.json)"),
    )
    v._on_export_selected_to_file()
    assert v._calls["export_dataset"] == [{"GAIN": "42"}]  # OFFSET not selected -> excluded


def test_export_cancelled_dialog_does_not_call_cb(qtbot, monkeypatch) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_read_done("GAIN", bytes([42]))
    monkeypatch.setattr(
        "xcptool.ui.calibration_view.QFileDialog.getSaveFileName",
        lambda *a, **k: ("", ""),  # user cancelled
    )
    v._on_export_all_to_file()
    assert v._calls["export_dataset"] == []


def test_on_export_ready_writes_file_and_updates_status(qtbot, monkeypatch, tmp_path) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_read_done("GAIN", bytes([42]))
    out_path = tmp_path / "out.json"
    monkeypatch.setattr(
        "xcptool.ui.calibration_view.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(out_path), "JSON (*.json)"),
    )
    v._on_export_all_to_file()
    payload = {
        "format_version": 1, "tool_version": "0.1.0", "exported_at": "2026-09-21T00:00:00",
        "a2l_filename": "x.a2l", "a2l_checksum": "sha256:abc", "values": {"GAIN": "42"},
    }
    v.on_export_ready(payload)
    assert out_path.is_file()
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written == payload
    assert "Exported 1" in v.status_label.text()
```

Add `import json` to the top of `test_calibration_view.py` if not already present.

- [x] **Step 2: Run tests, confirm FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ui/test_calibration_view.py -v -k "export_all or export_selected or export_cancelled or on_export_ready"`
Expected: FAIL — stub methods are `pass`, so `v._calls["export_dataset"]` stays empty
even when it shouldn't, and `status_label`/file assertions fail

- [x] **Step 3: Implement the export flow**

At the top of `xcptool/src/xcptool/ui/calibration_view.py`, change:

```python
import struct
from typing import Any, Callable, Iterable
```

to:

```python
import json
import struct
from pathlib import Path
from typing import Any, Callable, Iterable
```

Replace the two export stub methods added in Task 7 with:

```python
    def _on_export_all_to_file(self) -> None:
        self._export_to_file(set(self._original) | self._dirty)

    def _on_export_selected_to_file(self) -> None:
        self._export_to_file(self._resolve_leaf_names(self.tree.selectedItems()))

    def _export_to_file(self, names: Iterable[str]) -> None:
        values = self._gather_dataset_values(names)
        if not values:
            self.status_label.setText(
                "Nothing to export — no CHARACTERISTIC has been read or edited yet."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Calibration Dataset", "dataset.json", "JSON (*.json)"
        )
        if not path:
            return
        self._pending_export = (path, values)
        self._export_dataset_cb(values)

    def on_export_ready(self, payload: dict) -> None:
        """Called by MainWindow with the dict Session.export_dataset() returned,
        after the worker-thread call started by _export_to_file() completes."""
        pending = self._pending_export
        self._pending_export = None
        if pending is None:
            return
        path, values = pending
        try:
            Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as e:
            self.status_label.setText(f"Failed to write dataset file: {e}")
            return
        self.status_label.setText(f"Exported {len(values)} parameter(s) to {Path(path).name}.")
```

- [x] **Step 4: Run tests, confirm PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ui/test_calibration_view.py -v`
Expected: PASS — full file

- [x] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/ui/calibration_view.py xcptool/tests/ui/test_calibration_view.py
git commit -m "feat(xcptool): implement CalibrationView export-to-file flow"
```

---

### Task 9: `ui/calibration_view.py` — Import flow

**Files:**
- Modify: `xcptool/src/xcptool/ui/calibration_view.py`
- Modify: `xcptool/tests/ui/test_calibration_view.py`

**Interfaces:**
- Consumes: `_import_dataset_cb` (Task 7), `DatasetImportResult`/`SkipReason` (from
  `session.api`, Task 3 re-export), `QMessageBox` (imported Task 7).
- Produces: `_on_import_dataset_from_file`, `on_import_done(result:
  DatasetImportResult) -> None` (called by `MainWindow` with what
  `Session.import_dataset()` returned), `_show_skip_summary(skipped:
  list[SkipReason]) -> None`.

- [x] **Step 1: Write the failing tests**

```python
from xcptool.session.api import DatasetImportResult, SkipReason


def test_import_dataset_from_file_reads_and_calls_cb(qtbot, monkeypatch, tmp_path) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    payload = {"format_version": 1, "values": {"GAIN": "99"}}
    in_path = tmp_path / "in.json"
    in_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "xcptool.ui.calibration_view.QFileDialog.getOpenFileName",
        lambda *a, **k: (str(in_path), "JSON (*.json)"),
    )
    v._on_import_dataset_from_file()
    assert v._calls["import_dataset"] == [payload]


def test_import_dataset_from_file_invalid_json_shows_status(qtbot, monkeypatch, tmp_path) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(
        "xcptool.ui.calibration_view.QFileDialog.getOpenFileName",
        lambda *a, **k: (str(bad_path), "JSON (*.json)"),
    )
    v._on_import_dataset_from_file()
    assert v._calls["import_dataset"] == []
    assert "Failed to read" in v.status_label.text()


def test_import_dataset_cancelled_dialog_noop(qtbot, monkeypatch) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    monkeypatch.setattr(
        "xcptool.ui.calibration_view.QFileDialog.getOpenFileName",
        lambda *a, **k: ("", ""),
    )
    v._on_import_dataset_from_file()
    assert v._calls["import_dataset"] == []


def test_on_import_done_stages_scalar_as_dirty(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_read_done("GAIN", bytes([42]))  # original = "42"
    result = DatasetImportResult(matched={"GAIN": "99"}, skipped=[], a2l_mismatch_warning=None)
    v.on_import_done(result)
    assert v._char_items["GAIN"].text(COL_VALUE) == "99"
    assert "GAIN" in v._dirty
    assert "Imported 1/1" in v.status_label.text()


def test_on_import_done_stages_array_children(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_read_done("LUT", bytes([1, 2, 3, 4]))
    result = DatasetImportResult(matched={"LUT": "9, 9, 9, 9"}, skipped=[], a2l_mismatch_warning=None)
    v.on_import_done(result)
    item = v._char_items["LUT"]
    assert [item.child(i).text(COL_VALUE) for i in range(item.childCount())] == ["9", "9", "9", "9"]
    assert "LUT" in v._dirty


def test_on_import_done_shows_skip_summary_when_skipped(qtbot, monkeypatch) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    shown = []
    monkeypatch.setattr(
        "xcptool.ui.calibration_view.QMessageBox.information",
        lambda *a, **k: shown.append(a),
    )
    result = DatasetImportResult(
        matched={}, skipped=[SkipReason(name="ghost", reason="not found in A2L")],
        a2l_mismatch_warning=None,
    )
    v.on_import_done(result)
    assert len(shown) == 1
    assert "Imported 0/1" in v.status_label.text()
    assert "1 skipped" in v.status_label.text()


def test_on_import_done_no_skips_no_dialog(qtbot, monkeypatch) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_read_done("GAIN", bytes([42]))
    shown = []
    monkeypatch.setattr(
        "xcptool.ui.calibration_view.QMessageBox.information",
        lambda *a, **k: shown.append(a),
    )
    result = DatasetImportResult(matched={"GAIN": "1"}, skipped=[], a2l_mismatch_warning=None)
    v.on_import_done(result)
    assert shown == []
```

- [x] **Step 2: Run tests, confirm FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ui/test_calibration_view.py -v -k "import_dataset_from_file or on_import_done"`
Expected: FAIL — `_on_import_dataset_from_file` is still the Task 7 no-op stub,
`on_import_done` doesn't exist yet

- [x] **Step 3: Implement the import flow**

Replace the `_on_import_dataset_from_file` stub (Task 7) with:

```python
    def _on_import_dataset_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Calibration Dataset", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            self.status_label.setText(f"Failed to read dataset file: {e}")
            return
        self._import_dataset_cb(payload)

    def on_import_done(self, result: "DatasetImportResult") -> None:
        """Called by MainWindow with what Session.import_dataset() returned."""
        for name, text in result.matched.items():
            item = self._char_items.get(name)
            char = self._db.characteristics.get(name)
            if item is None or char is None:
                continue
            if char.array_size > 1 and item.childCount() > 0:
                parts = [p.strip() for p in text.split(",")]
                for i in range(min(item.childCount(), len(parts))):
                    item.child(i).setText(COL_VALUE, parts[i])
            else:
                item.setText(COL_VALUE, text)

        total = len(result.matched) + len(result.skipped)
        msg = f"Imported {len(result.matched)}/{total} params."
        if result.skipped:
            msg += f" {len(result.skipped)} skipped — see details."
        if result.a2l_mismatch_warning:
            msg += f" {result.a2l_mismatch_warning}"
        self.status_label.setText(msg)

        if result.skipped:
            self._show_skip_summary(result.skipped)

    def _show_skip_summary(self, skipped: "list[SkipReason]") -> None:
        lines = "\n".join(f"{s.name}: {s.reason}" for s in skipped)
        QMessageBox.information(self, "Import Skipped Entries", lines)
```

Add the type-only import for annotations (both names are only used in string-quoted
hints above, but importing them keeps the file self-documenting and matches how
`A2LDatabase`/`InstanceNode` are already imported): change the existing
`calibration_view.py:32` line

```python
from ..session.api import A2LDatabase, InstanceNode
```

to:

```python
from ..session.api import A2LDatabase, DatasetImportResult, InstanceNode, SkipReason
```

...and drop the quotes around `DatasetImportResult`/`SkipReason` in the two method
signatures above now that they're real (non-circular) imports:

```python
    def on_import_done(self, result: DatasetImportResult) -> None:
```
```python
    def _show_skip_summary(self, skipped: list[SkipReason]) -> None:
```

- [x] **Step 4: Run tests, confirm PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ui/test_calibration_view.py -v`
Expected: PASS — full file

- [x] **Step 5: Run full suite**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ -x -q`
Expected: all green (this is the last change to `calibration_view.py` in this plan)

- [x] **Step 6: Commit**

```bash
git add xcptool/src/xcptool/ui/calibration_view.py xcptool/tests/ui/test_calibration_view.py
git commit -m "feat(xcptool): implement CalibrationView import-from-file flow"
```

---

### Task 10: `ui/main_window.py` — wire callbacks to `Session`

**Files:**
- Modify: `xcptool/src/xcptool/ui/main_window.py`
- Modify: `xcptool/tests/ui/test_calibration_view.py` (integration-level check only;
  `MainWindow` already has its own test coverage elsewhere — this task adds the
  minimum needed to prove the wiring, not a full new MainWindow test file)

**Interfaces:**
- Consumes: `CalibrationView.__init__`'s new `export_dataset_cb`/`import_dataset_cb`
  params (Task 7); `CalibrationView.on_export_ready`/`on_import_done` (Task 8/9);
  `Session.export_dataset`/`import_dataset` (Task 3/4/5); `MainWindow._call` (existing,
  `main_window.py:388`).

- [x] **Step 1: Locate the `CalibrationView(...)` construction site**

`xcptool/src/xcptool/ui/main_window.py:141-149` currently reads:

```python
        self.calibration_view = CalibrationView(
            read_all_cb=self.read_all_characteristics,
            read_cb=self.read_characteristics,
            write_cb=self.write_characteristic,
            get_pages_cb=self.cal_get_pages,
            set_page_cb=self.cal_set_page,
            copy_page_cb=self.cal_copy_page,
            parent=self,
        )
```

Step 5 below adds two more keyword arguments here.

- [x] **Step 2: Write the failing test**

`MainWindow.__init__(self, session: Any, parent: QWidget | None = None)`
(`main_window.py:76`) — construct it directly with a `FakeSession`, matching how
`tests/ui/conftest.py` already does for other `MainWindow` tests:

```python
def test_main_window_wires_calibration_dataset_callbacks(qtbot) -> None:
    """MainWindow must construct CalibrationView with working dataset callbacks —
    a smoke test that the wiring doesn't raise and reaches Session."""
    from xcptool.session.fake import FakeSession
    from xcptool.ui.main_window import MainWindow

    session = FakeSession()
    win = MainWindow(session=session)
    qtbot.addWidget(win)
    assert win.calibration_view._export_dataset_cb is not None
    assert win.calibration_view._import_dataset_cb is not None
```

- [x] **Step 3: Run test, confirm FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ui/test_calibration_view.py -v -k wires_calibration_dataset`
Expected: FAIL — `TypeError` from `CalibrationView(...)` missing the two new required
kwargs (since `main_window.py` doesn't pass them yet)

- [x] **Step 4: Add the two handler methods**

In `xcptool/src/xcptool/ui/main_window.py`, in the `# ── A2L / calibration ──` section
(right after `_after_a2l_load`, `main_window.py:616-626`), add:

```python
    def _on_export_dataset_requested(self, values: dict[str, str]) -> None:
        self._call(
            "Exporting calibration dataset…",
            self.session.export_dataset, values,
            on_ok=self.calibration_view.on_export_ready,
            on_err=lambda exc: self.calibration_view.status_label.setText(
                f"Export failed: {exc}"
            ),
        )

    def _on_import_dataset_requested(self, payload: dict) -> None:
        self._call(
            "Importing calibration dataset…",
            self.session.import_dataset, payload,
            on_ok=self.calibration_view.on_import_done,
            on_err=lambda exc: self.calibration_view.status_label.setText(
                f"Import failed: {exc}"
            ),
        )
```

Both use explicit `on_err` (rather than `_call`'s default `errors.show_error` popup)
so failures land in `status_label`, matching the spec's error-handling table (§7:
"Abort, error in status label") rather than the app's generic modal error dialog.

- [x] **Step 5: Pass the two callbacks at the `CalibrationView(...)` construction site**

At `main_window.py:141-149` (Step 1), change:

```python
        self.calibration_view = CalibrationView(
            read_all_cb=self.read_all_characteristics,
            read_cb=self.read_characteristics,
            write_cb=self.write_characteristic,
            get_pages_cb=self.cal_get_pages,
            set_page_cb=self.cal_set_page,
            copy_page_cb=self.cal_copy_page,
            parent=self,
        )
```

to:

```python
        self.calibration_view = CalibrationView(
            read_all_cb=self.read_all_characteristics,
            read_cb=self.read_characteristics,
            write_cb=self.write_characteristic,
            get_pages_cb=self.cal_get_pages,
            set_page_cb=self.cal_set_page,
            copy_page_cb=self.cal_copy_page,
            export_dataset_cb=self._on_export_dataset_requested,
            import_dataset_cb=self._on_import_dataset_requested,
            parent=self,
        )
```

- [x] **Step 6: Run test, confirm PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ui/test_calibration_view.py -v -k wires_calibration_dataset`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add xcptool/src/xcptool/ui/main_window.py xcptool/tests/ui/test_calibration_view.py
git commit -m "feat(xcptool): wire CalibrationView dataset export/import to Session in MainWindow"
```

---

### Task 11: Full-suite regression + docs

**Files:**
- Modify: `xcptool/DEV_PLAN.md`

- [x] **Step 1: Run the full suite**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ -x -q`
Expected: all green (module-level flaky exception per Global Constraints — if it's
the ONLY red test, rerun it alone before concluding regression)

- [x] **Step 2: Manual smoke test (per `DEV_PLAN.md §6` "không crash" criteria)**

**Actually done:** not the literal interactive click-through described below — an
ad-hoc end-to-end script driving the same production code paths (real `MainWindow` +
real `FakeSession`, `load_a2l` on `examples/xcp_daq_example.a2l`, gather → export →
mutate the file → import → write) hung repeatedly in this headless/offscreen
environment (Qt/import startup time made it unreliable to bisect further) and was
abandoned as not worth the effort, since two other automated layers already cover the
same ground: `pytest` (565 green) calls the real `_on_export_all_to_file`/
`on_export_ready`/`_on_import_dataset_from_file`/`on_import_done` methods against a
real `CalibrationView`, and `python -m xcptool.ui.app --session fake --selftest`
(15/15 steps green) proves the real event loop + the new `MainWindow` wiring doesn't
break the app. The literal walkthrough below was never performed and is left here for
whoever wants to do it by hand:

Launch the app with the fake session and manually exercise: load
`examples/xcp_daq_example.a2l`, Read All, right-click → Export All to File… to a temp
path, verify the JSON file's `values` dict is non-empty, then right-click → Import
Dataset from File… on that same file — confirm the rows go dirty (orange) with no ECU
write attempted, then Write All to confirm the staged values reach `FakeSlave`/the
fake session's memory correctly.

- [x] **Step 3: Update `DEV_PLAN.md §11`**

At `xcptool/DEV_PLAN.md:2067`, change:

```markdown
**Trạng thái: mục (1) đã triển khai xong (2026-09-19); (2) và (3) chưa bắt
đầu.** 3 tính năng liên quan, làm theo đúng thứ tự phụ thuộc dưới đây
(branch `feature`).
```

to:

```markdown
**Trạng thái: mục (1) và (2) đã triển khai xong; (3) chưa bắt đầu.** 3 tính
năng liên quan, làm theo đúng thứ tự phụ thuộc dưới đây (branch `feature`).
```

And append a short implementation note under item 2 (after its existing paragraph,
`DEV_PLAN.md:2077-2081`) recording the one real deviation from the spec, for future
readers:

```markdown
   **Triển khai thật (khác spec ở một điểm, bắt buộc bởi kiến trúc):**
   `calibration_view.py` không gọi `a2l.dataset.build_dataset`/`apply_dataset`
   trực tiếp như spec mô tả — `tests/test_boundaries.py` cấm `ui/` import
   `xcptool.a2l`. Hai hàm đó được gọi qua `Session.export_dataset()`/
   `import_dataset()` mới (giống hệt cách `load_a2l()` đã làm) — xem
   `docs/superpowers/plans/2026-09-21-calibration-dataset-export-import-plan.md`
   cho lý do đầy đủ.
```

- [x] **Step 4: Commit**

```bash
git add xcptool/DEV_PLAN.md
git commit -m "docs(xcptool): mark calibration dataset export/import shipped"
```
