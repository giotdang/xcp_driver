# Calibration Dataset Export / Import

**Status:** Approved by user, ready for implementation planning.
**Date:** 2026-09-19
**Scope:** new module `xcptool/src/xcptool/a2l/dataset.py`; UI wiring in
`xcptool/src/xcptool/ui/calibration_view.py`.
**Depends on:** [`2026-09-19-calibration-multiselect-design.md`](2026-09-19-calibration-multiselect-design.md)
— "Export Selected to File" needs multi-row tree selection and its
`_resolve_leaf_names()` helper. Implement that spec first.
**Depended on by (future, not designed yet):** "Generate hex/s19 file"
feature — intended to reuse this dataset format as one of its value
sources, per user's original request. Out of scope here.

## 1. Motivation

Calibrating a set of CHARACTERISTICs by hand every session (re-typing the
same tuned values into `CalibrationView` one cell at a time) is slow and
error-prone once a project has more than a handful of tuned parameters. The
user wants to save a working set of calibration values to a file from
`CalibrationView` (right-click on the tree), and reload it in a later
session — instead of recalibrating every variable from scratch.

## 2. Goals / non-goals

**Goals:**
- Right-click context menu on the tree offers **Export All to File…**,
  **Export Selected to File…**, and **Import Dataset from File…**.
- Export writes a JSON file containing `name → value text` for every
  exportable CHARACTERISTIC (all, or just the current multi-row selection).
  The value written is whatever is currently displayed in the tree —
  including unsaved (dirty) edits — not necessarily what the ECU currently
  holds.
- Import loads such a JSON file and stages the values into the tree exactly
  like a manual double-click edit would (marks rows dirty, does **not**
  write to the ECU by itself). The user reviews and clicks "Write
  Selected"/"Write All" same as any other edit.
- Import tolerates a dataset that doesn't perfectly match the currently
  loaded A2L: unknown names, or names whose datatype/array size changed,
  are skipped individually with a clear summary — the rest of the dataset
  still applies.
- The dataset file carries traceability metadata (source A2L filename +
  checksum, export timestamp, tool version) and warns (non-blocking) on
  import if it doesn't match the currently loaded A2L.

**Non-goals:**
- No automatic write-to-ECU on import (explicit user decision from
  brainstorming — stays consistent with the existing manual-edit-then-write
  flow).
- No support for any calibration-exchange industry format (DCM, CDFX) —
  this is xcptool's own simple format, not meant to interoperate with
  CANape/INCA.
- No UI for browsing/diffing dataset file contents before import beyond the
  post-import skip summary — if the user wants to inspect the file, it's
  plain JSON, readable in any editor.
- CHARACTERISTICs that have never been read or edited in the current
  session (no entry in `_original` or `_dirty`) are excluded from "Export
  All" / "Export Selected" — there is no real value to export for them.

## 3. File format

```json
{
  "format_version": 1,
  "tool_version": "0.1.0",
  "exported_at": "2026-09-19T14:22:00+07:00",
  "a2l_filename": "project.a2l",
  "a2l_checksum": "sha256:3f2a9c1e...",
  "values": {
    "speedPid_kp": "1.25",
    "speedPid_ki": "0.003",
    "torqueTable": "10, 20, 30, 40"
  }
}
```

- `values` keys are real CHARACTERISTIC names — the same keys already used
  internally by `CalibrationView._original` / `_dirty` (for a struct member,
  this is the leaf's own A2L name, not a synthesized "group.member" display
  path; for a `VAL_BLK` array, one entry holds the whole comma-joined
  array, matching `encode_value()`'s expected input format). No JSON nesting
  is needed to represent struct/array hierarchy — the flat A2L name space
  already disambiguates every leaf.
- `a2l_checksum` is `"sha256:" + hexdigest` of the raw A2L file bytes at
  export time, computed with `hashlib.sha256`.
- Numeric values are formatted with enough significant digits to round-trip
  exactly (`%.17g` for `FLOAT64_IEEE`, `%.9g` for `FLOAT32_IEEE`) — **not**
  `calibration_view.decode_value()`'s `%.6g`, which is a display-only
  rounding that would lose precision on export/import round-trips. This
  needs a small dedicated formatting function in `a2l/dataset.py`; integer
  and ASCII values reuse `decode_value()`'s existing (lossless) formatting
  as-is.
- No `byte_order` field: values are stored as human-readable text (decimal
  numbers / ASCII), which is endianness-agnostic. Re-encoding to bytes on
  import/write always uses the *currently connected* session's byte order
  (from `SlaveCaps`), which is the only byte order that can ever be correct
  at write time — storing the exporting session's byte order would be
  actively wrong if re-imported against a different-endian ECU.

## 4. Module: `a2l/dataset.py`

Pure functions, no Qt dependency, independently unit-testable:

```python
def build_dataset(
    values: dict[str, str], db: A2LDatabase, a2l_path: Path,
) -> dict:
    """Build the JSON-serializable dict described in §3 from a name→text
    map. Does not touch the filesystem."""

@dataclass
class SkipReason:
    name: str
    reason: str  # "not found in A2L" | "datatype/size mismatch"

@dataclass
class DatasetImportResult:
    matched: dict[str, str]       # name -> value text, ready to apply
    skipped: list[SkipReason]
    a2l_mismatch_warning: str | None  # None if checksum matches or absent

def apply_dataset(payload: dict, db: A2LDatabase) -> DatasetImportResult:
    """Validate `payload` (raises ValueError on structurally invalid input
    — missing format_version/values, wrong JSON shape) and cross-check each
    entry against `db.characteristics`."""
```

File I/O (`json.dump`/`json.load`, `QFileDialog`) stays in
`calibration_view.py` — `dataset.py` only ever sees already-parsed dicts /
already-open data, keeping it trivially testable without touching disk or
Qt.

## 5. Export flow

Context menu (`tree.setContextMenuPolicy(Qt.CustomContextMenu)` +
`customContextMenuRequested`):

- **Export All to File…** — enabled whenever the tree is non-empty
  (A2L loaded). Eligible names: every name present in `self._original` or
  `self._dirty` (i.e. has been read or edited at least once this session).
  Note `self._dirty` is only a `set[str]` of names currently mid-edit — it
  does not itself hold a value — so the actual text exported for every
  eligible name is read straight from the tree item, the same way
  `_write_parent()` already does: `item.text(COL_VALUE)` for a scalar/struct
  leaf, or the child cells joined with `", "` for a `VAL_BLK` array/struct
  member with children. This naturally picks up unsaved dirty edits (they
  are already the item's current text) without needing a separate "dirty
  value" lookup.
- **Export Selected to File…** — enabled only when `tree.selectedItems()`
  is non-empty. Uses `self._resolve_leaf_names(tree.selectedItems())` (from
  the multi-select spec) to get the target name list, then the same
  eligibility + tree-text-read rule as above, restricted to that list.

Both call `QFileDialog.getSaveFileName(..., filter="*.json")`, then
`dataset.build_dataset(...)`, then `json.dump(..., indent=2)`. Status label
reports the count written (and, for Export All/Selected, how many eligible
rows were skipped for having no known value yet).

## 6. Import flow

**Import Dataset from File…** — enabled whenever the tree is non-empty.
`QFileDialog.getOpenFileName(..., filter="*.json")` →
`json.load()` → `dataset.apply_dataset(payload, self._db)`:

- JSON parse failure or structurally invalid payload (missing
  `format_version`/`values`, wrong types) → error message via
  `status_label`, **nothing applied** — this is an all-or-nothing parse
  gate, distinct from the per-entry tolerance below.
- `DatasetImportResult.a2l_mismatch_warning` set (checksum differs from the
  currently loaded A2L, or `a2l_filename` differs) → shown as a warning,
  import still proceeds.
- For every `(name, text)` in `matched`: locate `item = self._char_items[name]`
  and apply `text` using **the same item/children branching `on_read_done()`
  already uses** (`calibration_view.py:446-473`) — for a plain scalar or a
  struct leaf, `item.setText(COL_VALUE, text)` directly; for a `VAL_BLK`
  array (`char.array_size > 1 and item.childCount() > 0`), the parent cell
  stays `"—"` and `text` is split on `,` and written one part per child via
  `item.child(i).setText(COL_VALUE, part)`. Each `setText` runs under normal
  (non-suspended) signal flow, so `_on_item_changed()` fires exactly as it
  would for a manual double-click edit, marking the affected row(s) dirty
  and tinting them. No new dirty-tracking code path is introduced — import
  is, mechanically, a scripted sequence of the same edits a user could make
  by hand.
- Result summary in `status_label`:
  `"Imported 45/50 params. 5 skipped — see details."` When `skipped` is
  non-empty, a small dialog lists each skipped name + reason (kept out of
  the single-line status label to stay readable for large skip counts).

## 7. Error handling

| Case | Behavior |
|---|---|
| File not valid JSON | Abort, error in status label, nothing applied |
| Missing `format_version` / `values` key | Abort, error in status label, nothing applied |
| Unknown `format_version` (future-proofing: not `1`) | Abort, error in status label, nothing applied |
| Name in file not in current A2L | Skip that entry, list in skip summary |
| Name's datatype/array_size differs from current A2L | Skip that entry, list in skip summary |
| `a2l_checksum` differs from current A2L | Warn (non-blocking), import proceeds |
| Export requested with zero eligible values (nothing read/edited yet) | No file written, status label explains why |
| Disk I/O error (permission, path) on either direction | Caught, shown in status label, no partial file left on export failure |

## 8. Testing

- `tests/unit/test_dataset.py` (new, no Qt): `build_dataset`/`apply_dataset`
  round-trip for scalar/FLOAT32/FLOAT64/VAL_BLK/ASCII values; precision
  round-trip specifically for FLOAT64 (value that `%.6g` would corrupt);
  mismatch handling (missing name, datatype change, size change) each
  produce the right `SkipReason`; checksum mismatch produces
  `a2l_mismatch_warning` without blocking `matched`.
- `tests/ui/test_calibration_view.py`: context-menu item enablement
  (Export Selected disabled with empty selection, Import disabled with no
  A2L loaded); export-all writes a file the fake filesystem/tmp_path can
  read back; import stages values as dirty (color + `_dirty` membership)
  without calling the write callback; skip-summary dialog appears only
  when `skipped` is non-empty.
