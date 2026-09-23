# Multi-select in CalibrationView (Read Selected / Write Selected across multiple rows)

**Status:** Approved by user, ready for implementation planning.
**Date:** 2026-09-19
**Scope:** `xcptool/src/xcptool/ui/calibration_view.py`, `xcptool/src/xcptool/ui/main_window.py`.
**Depends on:** nothing (foundation feature).
**Depended on by:** [`2026-09-19-calibration-dataset-export-import-design.md`](2026-09-19-calibration-dataset-export-import-design.md) — "Export Selected to File" needs multi-row selection.

## 1. Motivation

`CalibrationView.tree` is a `QTreeWidget` currently locked to
`QAbstractItemView.SingleSelection`. "Read" and "Write Selected" both act on
exactly one row (`_selected_char_name()`, which reads `tree.currentItem()`).

This came up while designing the calibration-dataset export feature: an
"Export Selected to File" context-menu action is only useful if the user can
select more than one row at a time (e.g. export 5 specific PID-gain
CHARACTERISTICs without exporting the whole calibration). Once multi-row
selection exists on the tree, the user asked that "Write Selected" and
"Read" become consistent with it too — select N rows, click one button,
act on all N — rather than only the future Export action supporting it.

## 2. Goals / non-goals

**Goals:**
- Tree supports standard Ctrl/Shift multi-selection (`ExtendedSelection`).
- "Read" reads every selected row (recursing into STRUCT/ARRAY parents down
  to real CHARACTERISTIC leaves) in one batch, reusing the existing
  `on_batch_read_done()` batch-result path — no new result-handling code.
- "Write Selected" writes every selected row that actually has unsaved
  changes — same semantics as "Write All", just scoped to the current
  selection instead of the entire `_dirty` set.
- A single shared helper resolves `tree.selectedItems()` (or any iterable of
  `QTreeWidgetItem`) down to real, deduplicated CHARACTERISTIC names —
  reused by Read, Write Selected, and (in the dependent spec) Export
  Selected.
- Zero behavior change when 0 or 1 row is selected — the existing
  single-item code path (`currentItem()`-based) is untouched, so existing
  tests for single-selection Read/Write keep passing unmodified.

**Non-goals:**
- No change to "Write All" or "Read All" semantics — they still operate on
  the full tree / full `_dirty` set, unrelated to selection.
- No multi-row support for anything other than Read and Write Selected
  (e.g. no bulk delete, no bulk page-switch — those don't exist today and
  aren't requested).
- No visual redesign of the tree (no checkboxes, no "N selected" counter
  beyond what Qt's native multi-select highlighting already shows).

## 3. Selection mode change

`calibration_view.py:315`:

```python
self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
```

becomes:

```python
self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
```

`ExtendedSelection` is the standard Qt behavior: plain click selects one row
(clears previous selection), Ctrl+click toggles a row in/out of the
selection, Shift+click extends a contiguous range. This is additive — Qt's
`currentItem()` (the focused row, used by the existing single-item code
path) keeps working exactly as before regardless of how many rows are
`selectedItems()`.

## 4. Shared helper — resolve selection to leaf CHARACTERISTIC names

New private method on `CalibrationView`:

```python
def _resolve_leaf_names(self, items: Iterable[QTreeWidgetItem]) -> list[str]:
    """Flatten a set of tree items (leaves and/or STRUCT/ARRAY parents) into
    a deduplicated list of real CHARACTERISTIC names, in tree order."""
```

This factors out the recursion that `_leaf_write_items()` already performs
for a *single* STRUCT/ARRAY parent item (`calibration_view.py`, used by
`_write_parent`, `on_write_done`, `_update_write_btn`). `_resolve_leaf_names`
calls `_leaf_write_items()`-equivalent logic per input item and unions the
results with a seen-set, so selecting both a struct parent and one of its
own children doesn't double-count.

`_leaf_write_items()` itself is not changed — it continues to serve single
struct/array items. Extracting the *multi-item* wrapper on top of it avoids
touching well-tested existing recursion logic while giving Read/Write/Export
one shared entry point.

## 5. Read Selected (multi)

**Backend refactor (`main_window.py:628-683`):** `read_all_characteristics()`
and `read_characteristic(name)` currently duplicate the same
read-one-CHARACTERISTIC-and-collect-into-a-dict logic. Consolidate into one
method:

```python
def read_characteristics(self, names: list[str]) -> None:
    """Read a specific list of CHARACTERISTICs; reports back via
    on_batch_read_done (unchanged) regardless of list length."""
```

`read_all_characteristics()` becomes a one-line wrapper:
`self.read_characteristics(self.calibration_view.loaded_characteristic_names())`.
The standalone `read_characteristic(name)` method is removed; its single
caller is replaced (see below).

**`CalibrationView` side:** `read_cb` changes signature from
`Callable[[str], None]` to `Callable[[list[str]], None]`. `_on_read()`
becomes:

```python
def _on_read(self) -> None:
    names = self._resolve_leaf_names(self.tree.selectedItems())
    if not names:
        return
    self._read_cb(names)
```

This replaces the old single-name path entirely — there is no behavioral
difference for a 1-row selection (`_resolve_leaf_names` on a single leaf
returns a 1-element list, `read_characteristics([name])` behaves exactly
like the old `read_characteristic(name)`), so no special-casing is needed
here (unlike Write, see §6).

**Button enable state:** `read_btn` is enabled whenever the resolved name
list is non-empty (i.e. at least one selected row is, or contains, a real
CHARACTERISTIC leaf — a pure STRUCT/ARRAY grouping row with no real leaves
underneath, if that can occur, resolves to an empty list and leaves the
button disabled for that selection).

## 6. Write Selected (multi)

Unlike Read, Write must not blindly rewrite rows that have no pending
change — re-sending an unchanged value wastes CAN bandwidth and is
surprising if the user Ctrl-selected a mix of edited and untouched rows.

**Rule:** "Write Selected" with N > 1 rows selected behaves like **"Write
All" restricted to the current selection** — only entries already in
`self._dirty` are written; selected-but-clean rows are silently skipped.
This reuses `_on_write_all`'s existing STRUCT/ARRAY-promotion logic
unchanged (a struct parent with at least one dirty leaf still writes the
*entire* struct in one contiguous run — write-buffer contiguity rules from
the A2L-struct spec are untouched).

**Implementation shape:** extract the "map dirty names → the set of
top-level items that must be written (promoting struct/array children to
their parent)" loop currently inline in `_on_write_all()`
(`calibration_view.py:656-673`) into a helper:

```python
def _write_roots_for(self, names: Iterable[str]) -> set[QTreeWidgetItem]:
```

- `_on_write_all()` becomes: `self._write_roots_for(self._dirty)`.
- New multi-select branch of `_on_write()`: when
  `len(self.tree.selectedItems()) > 1`, compute
  `selected_names = set(self._resolve_leaf_names(self.tree.selectedItems()))`,
  then `self._write_roots_for(self._dirty & selected_names)`, then feed the
  result into the existing `self._write_queue` / `_process_write_queue()`
  pipeline exactly as `_on_write_all()` already does.
- When 0 or 1 row is selected, `_on_write()` keeps its current body
  unchanged (`_selected_char_name()` → `_write_parent()`), preserving
  existing single-item behavior and tests byte-for-byte.

**Button enable state:** `_on_item_selection_changed()` / `_update_write_btn()`
currently derive the enabled state from a single `_selected_char_name()`.
For N > 1 selected rows, enable `write_btn` iff
`self._dirty & set(self._resolve_leaf_names(selected_items))` is non-empty.

## 7. Testing

- `tests/ui/test_calibration_view.py`: existing single-selection Read/Write
  tests must keep passing unmodified (regression guard for §5/§6's "0 or 1
  row: unchanged" rule).
- New tests: multi-select Read (2+ rows, including one STRUCT parent + one
  unrelated scalar) reports a correct batch-read result; multi-select Write
  Selected only writes rows that are actually dirty (select 3 rows, dirty 1
  → exactly 1 WRITE observed on the fake session); selecting a struct parent
  with one dirty leaf writes the whole struct's contiguous run, not just the
  dirty leaf.
- `_resolve_leaf_names`: unit-level coverage for dedup (parent + its own
  child both selected → leaf counted once) and for a selection spanning
  multiple independent struct instances.
