# CalibrationView Multi-select (Read/Write Selected) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user Ctrl/Shift-select multiple rows in `CalibrationView`'s tree and have both "Read" and "Write Selected" act on the whole selection, instead of exactly one row.

**Architecture:** Switch the tree from `SingleSelection` to `ExtendedSelection`. Add one shared helper, `_resolve_leaf_names()`, that flattens any set of selected `QTreeWidgetItem`s (leaves, VAL_BLK array parents, or STRUCT/ARRAY group nodes) into a deduplicated list of real A2L CHARACTERISTIC names — built on top of the existing single-item recursion helper `_leaf_write_items()`. "Write Selected" reuses this to become "Write All, restricted to the current selection" (only entries already in `self._dirty` are sent). "Read" reuses it to batch-read every selected leaf through the existing `on_batch_read_done()` path. 0-or-1-row selections keep their exact current code path untouched.

**Tech Stack:** Python 3.11+, PySide6 (Qt widgets), pytest + pytest-qt. No new dependencies.

**Spec:** [`docs/superpowers/specs/2026-09-19-calibration-multiselect-design.md`](../specs/2026-09-19-calibration-multiselect-design.md)

## Global Constraints

- Zero behavior change for 0 or 1 selected row — existing single-item code paths (`_selected_char_name()` → `currentItem()`) stay byte-identical, so all pre-existing tests in `tests/ui/test_calibration_view.py` must keep passing unmodified.
- No new third-party dependency.
- Match existing code style in the touched files: Vietnamese comments/docstrings, no unrelated reformatting.
- Every `- [ ] Step: Run tests` step must actually be run and confirmed before moving on — this project's tests exercise real Qt widgets (pytest-qt `qtbot`), not mocks of the tree.
- Test runner: `xcptool\.venv\Scripts\python.exe -m pytest <path> -q` (see `xcptool/DEV_PLAN.md §0`).

---

### Task 1: Enable multi-select + shared `_resolve_leaf_names()` helper

**Files:**
- Modify: `xcptool/src/xcptool/ui/calibration_view.py:6` (import), `:315` (selection mode), insert new method after `:706` (right after `_leaf_write_items`)
- Test: `xcptool/tests/ui/test_calibration_view.py` (append new tests near the existing struct/array tests, e.g. after `test_write_parent_clears_deep_nested_leaf_dirty_and_enables_write_btn` around line 1148)

**Interfaces:**
- Produces: `CalibrationView._resolve_leaf_names(self, items: Iterable[QTreeWidgetItem]) -> list[str]` — used by Task 2 (Write Selected) and Task 3 (Read Selected).

- [ ] **Step 1: Write the failing tests**

Append to `xcptool/tests/ui/test_calibration_view.py` (uses the existing `_make_db()` / `_add_struct_instance()` helpers already defined near the top of the file):

```python
def test_tree_ho_tro_multi_select(qtbot) -> None:
    v = _make_view(qtbot)
    assert v.tree.selectionMode() == QAbstractItemView.ExtendedSelection


def test_resolve_leaf_names_don_1_scalar(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    item = v._char_items["GAIN"]
    assert v._resolve_leaf_names([item]) == ["GAIN"]


def test_resolve_leaf_names_struct_cha_ra_het_la_that(qtbot) -> None:
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["grp_a"] = Characteristic(
        "grp_a", "", "VALUE", MEM_BASE, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["grp_b"] = Characteristic(
        "grp_b", "", "VALUE", MEM_BASE + 2, "I16", 0, 100, datatype="SWORD", array_size=1)
    _add_struct_instance(db, "grp", ["grp_a", "grp_b"])
    v.set_database(db)
    parent = v._char_items["grp"]
    assert sorted(v._resolve_leaf_names([parent])) == ["grp_a", "grp_b"]


def test_resolve_leaf_names_khu_trung_cha_va_con(qtbot) -> None:
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["grp_a"] = Characteristic(
        "grp_a", "", "VALUE", MEM_BASE, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["grp_b"] = Characteristic(
        "grp_b", "", "VALUE", MEM_BASE + 2, "I16", 0, 100, datatype="SWORD", array_size=1)
    _add_struct_instance(db, "grp", ["grp_a", "grp_b"])
    v.set_database(db)
    parent = v._char_items["grp"]
    child_a = parent.child(0)
    names = v._resolve_leaf_names([parent, child_a])
    assert sorted(names) == ["grp_a", "grp_b"]  # grp_a không lặp lại dù chọn cả cha lẫn con


def test_resolve_leaf_names_val_blk_tra_ve_1_ten_cha(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    parent = v._char_items["LUT"]
    assert v._resolve_leaf_names([parent]) == ["LUT"]


def test_resolve_leaf_names_array_elem_con_tra_ve_ten_cha(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    child = v._char_items["LUT"].child(2)
    assert v._resolve_leaf_names([child]) == ["LUT"]


def test_resolve_leaf_names_gop_2_nhom_doc_lap(qtbot) -> None:
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["grp1_a"] = Characteristic(
        "grp1_a", "", "VALUE", MEM_BASE, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["grp2_a"] = Characteristic(
        "grp2_a", "", "VALUE", MEM_BASE + 2, "I16", 0, 100, datatype="SWORD", array_size=1)
    _add_struct_instance(db, "grp1", ["grp1_a"])
    _add_struct_instance(db, "grp2", ["grp2_a"])
    v.set_database(db)
    names = v._resolve_leaf_names([v._char_items["grp1"], v._char_items["grp2"]])
    assert sorted(names) == ["grp1_a", "grp2_a"]
```

`_make_db()` (defined at the top of the test file) already includes `GAIN` (scalar UBYTE), `OFFSET` (scalar ULONG) and `LUT` (`VAL_BLK`, `array_size=4`) — no new fixture needed for these tests.

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool\.venv\Scripts\python.exe -m pytest xcptool/tests/ui/test_calibration_view.py -k resolve_leaf_names -v`
Expected: every test FAILs — `test_tree_ho_tro_multi_select` fails on the `assert` (mode is still `SingleSelection`), the `_resolve_leaf_names` tests fail with `AttributeError: 'CalibrationView' object has no attribute '_resolve_leaf_names'`.

- [ ] **Step 3: Implement**

In `xcptool/src/xcptool/ui/calibration_view.py`, change the import line:

```python
from typing import Any, Callable
```
to:
```python
from typing import Any, Callable, Iterable
```

Change line 315 from:
```python
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
```
to:
```python
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
```

Insert this new method immediately after `_leaf_write_items()` (i.e. right after its closing `return result` — currently line 706 — and before `_write_parent`):

```python
    def _resolve_leaf_names(self, items: Iterable[QTreeWidgetItem]) -> list[str]:
        """Flatten a set of tree items (leaves, VAL_BLK array parents, or
        STRUCT/ARRAY group nodes) into a deduplicated list of real A2L
        CHARACTERISTIC names, in input order.

        Mirrors `_selected_char_name()`'s Qt.UserRole handling (array_elem
        tuple -> parent char name; a name already in self._db.characteristics
        -> itself) for a single item, and falls back to `_leaf_write_items()`'s
        existing struct/array recursion for group nodes whose data role is a
        hierarchical (non-CHARACTERISTIC-key) name."""
        seen: set[str] = set()
        result: list[str] = []

        def add(name: str) -> None:
            if name not in seen:
                seen.add(name)
                result.append(name)

        for item in items:
            data_role = item.data(COL_NAME, Qt.UserRole)
            if isinstance(data_role, tuple):
                add(data_role[1] if data_role[0] == "array_elem" else data_role[0])
                continue
            if isinstance(data_role, str) and data_role in self._db.characteristics:
                add(data_role)
                continue
            for _leaf_item, c_name, _c_def in self._leaf_write_items(item):
                add(c_name)
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `xcptool\.venv\Scripts\python.exe -m pytest xcptool/tests/ui/test_calibration_view.py -k "resolve_leaf_names or multi_select" -v`
Expected: PASS, all 7 new tests.

- [ ] **Step 5: Run the full CalibrationView test file to check for regressions**

Run: `xcptool\.venv\Scripts\python.exe -m pytest xcptool/tests/ui/test_calibration_view.py -q`
Expected: PASS, no failures (selection-mode change must not break any existing single-selection test).

- [ ] **Step 6: Commit**

```bash
git add xcptool/src/xcptool/ui/calibration_view.py xcptool/tests/ui/test_calibration_view.py
git commit -m "feat(xcptool): enable multi-select in CalibrationView tree + leaf-name resolver"
```

---

### Task 2: Write Selected acts on the full selection

**Files:**
- Modify: `xcptool/src/xcptool/ui/calibration_view.py` — `_on_write_all()` (was lines 656-673), `_on_write()` (was lines 646-654), `_update_write_btn()` (was lines 1065-1084)
- Test: `xcptool/tests/ui/test_calibration_view.py`

**Interfaces:**
- Consumes: `self._resolve_leaf_names(items: Iterable[QTreeWidgetItem]) -> list[str]` (Task 1).
- Produces: `CalibrationView._write_roots_for(self, names: Iterable[str]) -> set[QTreeWidgetItem]` — the struct/array-promotion logic factored out of `_on_write_all()`, reused by both `_on_write_all()` and the new multi-select branch of `_on_write()`.

- [ ] **Step 1: Write the failing tests**

Append to `xcptool/tests/ui/test_calibration_view.py`:

```python
def test_write_selected_da_chon_chi_ghi_dong_dirty(qtbot) -> None:
    """Chọn 3 dòng, chỉ 1 dòng dirty -> chỉ đúng 1 lệnh WRITE được gửi."""
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["a"] = Characteristic(
        "a", "", "VALUE", MEM_BASE, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["b"] = Characteristic(
        "b", "", "VALUE", MEM_BASE + 2, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["c"] = Characteristic(
        "c", "", "VALUE", MEM_BASE + 4, "I16", 0, 100, datatype="SWORD", array_size=1)
    v.set_database(db)

    item_a, item_b, item_c = v._char_items["a"], v._char_items["b"], v._char_items["c"]
    v._original["a"] = item_a.text(COL_VALUE)
    v._original["b"] = item_b.text(COL_VALUE)
    v._original["c"] = item_c.text(COL_VALUE)

    item_b.setText(COL_VALUE, "42")
    v._on_item_changed(item_b, COL_VALUE)
    assert v._dirty == {"b"}

    item_a.setSelected(True)
    item_b.setSelected(True)
    item_c.setSelected(True)

    writes: list[tuple[str, int, bytes]] = []
    v._write_cb = lambda name, addr, data: writes.append((name, addr, data))
    v._on_write()

    assert [w[0] for w in writes] == ["b"]


def test_write_selected_struct_cha_co_con_dirty_ghi_ca_khoi(qtbot) -> None:
    """Chọn nhiều dòng gồm 1 struct cha có con dirty -> ghi TOÀN BỘ struct
    (đúng cơ chế contiguous-run cũ), không chỉ đúng con dirty; dòng không
    dirty trong tập chọn bị bỏ qua."""
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["grp_a"] = Characteristic(
        "grp_a", "", "VALUE", MEM_BASE, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["grp_b"] = Characteristic(
        "grp_b", "", "VALUE", MEM_BASE + 2, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["solo"] = Characteristic(
        "solo", "", "VALUE", MEM_BASE + 64, "I16", 0, 100, datatype="SWORD", array_size=1)
    _add_struct_instance(db, "grp", ["grp_a", "grp_b"])
    v.set_database(db)

    parent = v._char_items["grp"]
    child_a, child_b = parent.child(0), parent.child(1)
    v._original["grp_a"] = child_a.text(COL_VALUE)
    v._original["grp_b"] = child_b.text(COL_VALUE)
    solo_item = v._char_items["solo"]
    v._original["solo"] = solo_item.text(COL_VALUE)

    child_a.setText(COL_VALUE, "99")
    v._on_item_changed(child_a, COL_VALUE)
    assert v._dirty == {"grp_a"}

    parent.setSelected(True)
    solo_item.setSelected(True)

    writes: list[tuple[str, int, bytes]] = []
    v._write_cb = lambda name, addr, data: writes.append((name, addr, data))
    v._on_write()

    # solo không dirty -> bỏ qua; "grp" (2 member liền khít) ghi 1 lệnh duy nhất.
    assert [w[0] for w in writes] == ["grp"]


def test_write_selected_khong_ai_dirty_khong_ghi_gi(qtbot) -> None:
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["a"] = Characteristic(
        "a", "", "VALUE", MEM_BASE, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["b"] = Characteristic(
        "b", "", "VALUE", MEM_BASE + 2, "I16", 0, 100, datatype="SWORD", array_size=1)
    v.set_database(db)
    item_a, item_b = v._char_items["a"], v._char_items["b"]
    item_a.setSelected(True)
    item_b.setSelected(True)

    writes: list[tuple[str, int, bytes]] = []
    v._write_cb = lambda name, addr, data: writes.append((name, addr, data))
    v._on_write()
    assert writes == []


def test_write_btn_enable_theo_multi_select(qtbot) -> None:
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["a"] = Characteristic(
        "a", "", "VALUE", MEM_BASE, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["b"] = Characteristic(
        "b", "", "VALUE", MEM_BASE + 2, "I16", 0, 100, datatype="SWORD", array_size=1)
    v.set_database(db)
    item_a, item_b = v._char_items["a"], v._char_items["b"]
    v._original["a"] = item_a.text(COL_VALUE)
    item_a.setText(COL_VALUE, "5")
    v._on_item_changed(item_a, COL_VALUE)

    item_a.setSelected(True)
    item_b.setSelected(True)
    v._update_write_btn()
    assert v.write_btn.isEnabled()

    item_a.setSelected(False)
    v.tree.setCurrentItem(item_b)
    v._update_write_btn()
    # chỉ còn "b" chọn (đường 1-item cũ), "b" không dirty -> tắt nút
    assert not v.write_btn.isEnabled()


def test_write_all_van_dung_sau_khi_tach_helper(qtbot) -> None:
    """Regression: _on_write_all() phải cho kết quả giống hệt trước khi tách
    _write_roots_for() ra khỏi nó."""
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["a"] = Characteristic("a", "", "VALUE", MEM_BASE, "F32", 0, 10, datatype="FLOAT32_IEEE", array_size=1)
    db.characteristics["b"] = Characteristic("b", "", "VALUE", MEM_BASE + 4, "F32", 0, 10, datatype="FLOAT32_IEEE", array_size=1)
    v.set_database(db)

    item_a, item_b = v._char_items["a"], v._char_items["b"]
    item_a.setText(COL_VALUE, "1.0")
    item_b.setText(COL_VALUE, "2.0")
    v._dirty.add("a")
    v._dirty.add("b")

    writes = []
    v._write_cb = lambda name, addr, data: writes.append(name)
    v._on_write_all()
    assert sorted(writes) == ["a", "b"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool\.venv\Scripts\python.exe -m pytest xcptool/tests/ui/test_calibration_view.py -k "write_selected or write_btn_enable_theo or write_all_van_dung" -v`
Expected: the multi-select tests FAIL (current `_on_write`/`_update_write_btn` only ever look at `currentItem()`, so selecting 3 rows and calling `_on_write()` sends 0 or 1 writes, not the expected filtered set) — `test_write_all_van_dung_sau_khi_tach_helper` PASSes already (it's a pure regression check for behavior that must survive Step 3's refactor, confirming the baseline before the change).

- [ ] **Step 3: Implement**

In `xcptool/src/xcptool/ui/calibration_view.py`, replace `_on_write_all()` (currently):

```python
    def _on_write_all(self) -> None:
        """Called when 'Write All' is clicked."""
        dirty_names = list(self._dirty)
        items_to_write = set()
        for char_name in dirty_names:
            item = self._char_items.get(char_name)
            if not item: continue
            
            if item.parent() is not None and (
                item.parent().text(COL_TYPE).startswith("STRUCT")
                or item.parent().text(COL_TYPE).startswith("ARRAY[")
            ):
                items_to_write.add(item.parent())
            else:
                items_to_write.add(item)
                
        self._write_queue = list(items_to_write)
        self._process_write_queue()
```

with:

```python
    def _write_roots_for(self, names: Iterable[str]) -> set[QTreeWidgetItem]:
        """Map CHARACTERISTIC names to the tree item(s) that must actually be
        written — a STRUCT/ARRAY member is promoted to its parent, since a
        struct write always sends the whole contiguous run, never one member
        alone (see `_write_parent`'s STRUCT/ARRAY branch)."""
        items_to_write: set[QTreeWidgetItem] = set()
        for char_name in names:
            item = self._char_items.get(char_name)
            if not item:
                continue
            if item.parent() is not None and (
                item.parent().text(COL_TYPE).startswith("STRUCT")
                or item.parent().text(COL_TYPE).startswith("ARRAY[")
            ):
                items_to_write.add(item.parent())
            else:
                items_to_write.add(item)
        return items_to_write

    def _on_write_all(self) -> None:
        """Called when 'Write All' is clicked."""
        self._write_queue = list(self._write_roots_for(self._dirty))
        self._process_write_queue()
```

Replace `_on_write()` (currently):

```python
    def _on_write(self) -> None:
        """Called when 'Write Selected' is clicked."""
        char_name = self._selected_char_name()
        if not char_name:
            return
            
        item = self._char_items.get(char_name)
        if item:
            self._write_parent(char_name, item)
```

with:

```python
    def _on_write(self) -> None:
        """Called when 'Write Selected' is clicked."""
        selected = self.tree.selectedItems()
        if len(selected) > 1:
            names = set(self._resolve_leaf_names(selected)) & self._dirty
            if not names:
                return
            self._write_queue = list(self._write_roots_for(names))
            self._process_write_queue()
            return

        char_name = self._selected_char_name()
        if not char_name:
            return

        item = self._char_items.get(char_name)
        if item:
            self._write_parent(char_name, item)
```

In `_update_write_btn()`, replace (currently):

```python
    def _update_write_btn(self) -> None:
        char_name = self._selected_char_name()
        if not char_name:
            self.write_btn.setEnabled(False)
            return
            
        item = self._char_items.get(char_name)
        if item and (
            item.text(COL_TYPE).startswith("STRUCT") or item.text(COL_TYPE).startswith("ARRAY[")
        ):
```

with:

```python
    def _update_write_btn(self) -> None:
        selected = self.tree.selectedItems()
        if len(selected) > 1:
            enable = bool(set(self._resolve_leaf_names(selected)) & self._dirty)
            self.write_btn.setEnabled(enable)
            return

        char_name = self._selected_char_name()
        if not char_name:
            self.write_btn.setEnabled(False)
            return
            
        item = self._char_items.get(char_name)
        if item and (
            item.text(COL_TYPE).startswith("STRUCT") or item.text(COL_TYPE).startswith("ARRAY[")
        ):
```

(the rest of `_update_write_btn()`'s body — the `any(...)`/`else` branch — is unchanged, it only runs for the `len(selected) <= 1` case now).

- [ ] **Step 4: Run tests to verify they pass**

Run: `xcptool\.venv\Scripts\python.exe -m pytest xcptool/tests/ui/test_calibration_view.py -k "write_selected or write_btn_enable_theo or write_all_van_dung" -v`
Expected: PASS, all 5 tests.

- [ ] **Step 5: Run the full CalibrationView test file to check for regressions**

Run: `xcptool\.venv\Scripts\python.exe -m pytest xcptool/tests/ui/test_calibration_view.py -q`
Expected: PASS — in particular `test_write_selected_single_struct_child_clears_parent_name_color`, `test_write_selected_single_child_keeps_parent_dirty_if_sibling_still_dirty`, `test_write_all_waits_for_every_run_before_next_queue_item`, `test_write_all_uses_queue` (all pre-existing, all exercise the `len(selected) <= 1` / `_on_write_all` code paths this task touched) must still pass unmodified.

- [ ] **Step 6: Commit**

```bash
git add xcptool/src/xcptool/ui/calibration_view.py xcptool/tests/ui/test_calibration_view.py
git commit -m "feat(xcptool): Write Selected writes every dirty row in a multi-selection"
```

---

### Task 3: Read acts on the full selection

**Files:**
- Modify: `xcptool/src/xcptool/ui/main_window.py` — `read_all_characteristics()` and `read_characteristic()` (currently lines 628-683), constructor wiring (currently line 143)
- Modify: `xcptool/src/xcptool/ui/calibration_view.py` — `read_cb` parameter type (constructor, currently line 228), `_on_read()` (currently lines 638-644)
- Modify: `xcptool/tests/ui/test_calibration_view.py` — `_make_view()`'s `calls` dict/`read_cb` (currently lines 98-104), the one existing call site `connected_window.read_characteristic("P0")` (currently line 495)

**Interfaces:**
- Consumes: `self._resolve_leaf_names(items: Iterable[QTreeWidgetItem]) -> list[str]` (Task 1).
- Produces: `MainWindow.read_characteristics(self, names: list[str]) -> None` (replaces `read_characteristic`); `CalibrationView.read_cb` is now `Callable[[list[str]], None]` (was `Callable[[str], None]`).

- [ ] **Step 1: Write the failing tests**

First, fix `_make_view()` in `xcptool/tests/ui/test_calibration_view.py` — its `calls` dict is currently missing the `"read"` key that `read_cb` writes into (dead code today because nothing calls `_on_read()` through this fixture yet). Change:

```python
    calls: dict[str, list] = {"read_all": [], "write": [], "pages": [], "set_page": [], "copy": []}

    def read_all_cb():
        calls["read_all"].append(True)

    def read_cb(name):
        calls["read"].append(name)
```

to:

```python
    calls: dict[str, list] = {
        "read_all": [], "read": [], "write": [], "pages": [], "set_page": [], "copy": [],
    }

    def read_all_cb():
        calls["read_all"].append(True)

    def read_cb(names):
        calls["read"].append(names)
```

Then append to the same test file:

```python
def test_on_read_da_chon_nhieu_dong_goi_read_cb_voi_list(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    item_gain = v._char_items["GAIN"]
    item_offset = v._char_items["OFFSET"]
    item_gain.setSelected(True)
    item_offset.setSelected(True)
    v._on_read()
    assert sorted(v._calls["read"][0]) == ["GAIN", "OFFSET"]


def test_on_read_1_dong_goi_read_cb_voi_list_1_phan_tu(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    item_gain = v._char_items["GAIN"]
    v.tree.setCurrentItem(item_gain)
    item_gain.setSelected(True)
    v._on_read()
    assert v._calls["read"] == [["GAIN"]]


def test_on_read_khong_chon_gi_khong_goi_cb(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v._on_read()
    assert v._calls["read"] == []
```

Next, in `xcptool/tests/ui/test_calibration_view.py`, change the one existing call site (inside `test_huy_read_all_dung_dung_task_dang_chay`, currently line 495) from:

```python
    connected_window.read_characteristic("P0")
```

to:

```python
    connected_window.read_characteristics(["P0"])
```

Finally, append this MainWindow-level integration test near `test_doc_tat_ca_qua_session`:

```python
def test_read_characteristics_doc_nhieu_ten_qua_session(qtbot, connected_window: MainWindow) -> None:
    db = _make_db()
    connected_window.session._a2l_db = db  # type: ignore[attr-defined]
    connected_window.calibration_view.set_database(db)
    connected_window.read_characteristics(["GAIN", "OFFSET"])
    qtbot.waitUntil(lambda: not connected_window.busy, timeout=5000)
    items = connected_window.calibration_view._char_items
    assert items["GAIN"].text(COL_VALUE) != "—"
    assert items["OFFSET"].text(COL_VALUE) != "—"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool\.venv\Scripts\python.exe -m pytest xcptool/tests/ui/test_calibration_view.py -k "on_read or read_characteristics_doc_nhieu or huy_read_all" -v`
Expected (Python doesn't enforce type hints at runtime, so the failures are assertion/attribute errors, not `TypeError`, until `_on_read()` itself changes in Step 3):
- `test_on_read_da_chon_nhieu_dong_goi_read_cb_voi_list` FAILs with `IndexError: list index out of range` — the old `_on_read()` still calls `self._selected_char_name()` (i.e. `tree.currentItem()`), and neither `setSelected(True)` call in this test changes the "current" item, so `read_cb` is never invoked and `v._calls["read"]` stays `[]`.
- `test_on_read_1_dong_goi_read_cb_voi_list_1_phan_tu` FAILs the assertion — this test does call `setCurrentItem(item_gain)`, so the old code still fires `read_cb("GAIN")` (a bare string), giving `v._calls["read"] == ["GAIN"]` where the test expects `[["GAIN"]]`.
- `test_on_read_khong_chon_gi_khong_goi_cb` already PASSes unmodified (nothing selected -> old and new code both no-op) — kept only as a regression guard, not expected to go red here.
- `test_read_characteristics_doc_nhieu_ten_qua_session` and `test_huy_read_all_dung_dung_task_dang_chay` both FAIL with `AttributeError: 'MainWindow' object has no attribute 'read_characteristics'`.

- [ ] **Step 3: Implement**

In `xcptool/src/xcptool/ui/main_window.py`, replace `read_all_characteristics()` and `read_characteristic()` (currently):

```python
    def read_all_characteristics(self) -> None:
        if not self._guard():
            return
        symbols = self.session.symbols
        names = self.calibration_view.loaded_characteristic_names()
        if not names:
            self.calibration_view.status_label.setText(
                "No A2L loaded or file contains no CHARACTERISTICs."
            )
            return

        def _batch(task_ref: list[Any]) -> dict:
            results: dict[str, bytes | None] = {}
            for name in names:
                if task_ref[0] and task_ref[0].cancelled:
                    break
                char = symbols.characteristics.get(name)
                if char is None or char.byte_size <= 0:
                    results[name] = None
                    continue
                try:
                    results[name] = self.session.read(char.address, char.byte_size)
                except Exception:  # noqa: BLE001
                    results[name] = None
            return results

        task_ref: list[Any] = [None]
        task_ref[0] = self._call(
            "Reading all parameters…",
            _batch,
            task_ref,
            on_ok=self.calibration_view.on_batch_read_done,
        )

    def read_characteristic(self, name: str) -> None:
        if not self._guard():
            return
        symbols = self.session.symbols
        char = symbols.characteristics.get(name)
        if not char:
            return
            
        def _read() -> dict:
            if char.byte_size <= 0:
                return {name: None}
            try:
                data = self.session.read(char.address, char.byte_size)
                return {name: data}
            except Exception:
                return {name: None}

        self._call(
            f"Reading {name}…",
            _read,
            on_ok=self.calibration_view.on_batch_read_done,
        )
```

with:

```python
    def read_all_characteristics(self) -> None:
        names = self.calibration_view.loaded_characteristic_names()
        if not names:
            self.calibration_view.status_label.setText(
                "No A2L loaded or file contains no CHARACTERISTICs."
            )
            return
        self.read_characteristics(names)

    def read_characteristics(self, names: list[str]) -> None:
        if not self._guard():
            return
        symbols = self.session.symbols
        label = f"Reading {names[0]}…" if len(names) == 1 else f"Reading {len(names)} parameters…"

        def _batch(task_ref: list[Any]) -> dict:
            results: dict[str, bytes | None] = {}
            for name in names:
                if task_ref[0] and task_ref[0].cancelled:
                    break
                char = symbols.characteristics.get(name)
                if char is None or char.byte_size <= 0:
                    results[name] = None
                    continue
                try:
                    results[name] = self.session.read(char.address, char.byte_size)
                except Exception:  # noqa: BLE001
                    results[name] = None
            return results

        task_ref: list[Any] = [None]
        task_ref[0] = self._call(
            label,
            _batch,
            task_ref,
            on_ok=self.calibration_view.on_batch_read_done,
        )
```

Note the intentional behavior change: reading a name that isn't in `symbols.characteristics` now goes through the same `_call()`/busy-indicator/`on_batch_read_done()` path as every other read (reported as 1 failed of N in the status label) instead of silently no-op-ing before Step 3 of this task existed. No test relies on the old silent no-op.

Update the constructor wiring (currently line 143):

```python
            read_cb=self.read_characteristic,
```

to:

```python
            read_cb=self.read_characteristics,
```

In `xcptool/src/xcptool/ui/calibration_view.py`, update the constructor parameter type hint (currently):

```python
        read_cb: Callable[[str], None],                # (name)
```

to:

```python
        read_cb: Callable[[list[str]], None],           # (names)
```

Replace `_on_read()` (currently):

```python
    def _on_read(self) -> None:
        """Read only the selected parent characteristic."""
        char_name = self._selected_char_name()
        if not char_name:
            return
            
        self._read_cb(char_name)
```

with:

```python
    def _on_read(self) -> None:
        """Read every selected characteristic (1 or many rows)."""
        names = self._resolve_leaf_names(self.tree.selectedItems())
        if not names:
            return
        self._read_cb(names)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `xcptool\.venv\Scripts\python.exe -m pytest xcptool/tests/ui/test_calibration_view.py -k "on_read or read_characteristics_doc_nhieu or huy_read_all" -v`
Expected: PASS, all listed tests.

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `xcptool\.venv\Scripts\python.exe -m pytest xcptool/tests/ -q`
Expected: PASS, full suite green (this task touches `main_window.py`, which other test files besides `test_calibration_view.py` may also exercise indirectly through `MainWindow`).

- [ ] **Step 6: Commit**

```bash
git add xcptool/src/xcptool/ui/calibration_view.py xcptool/src/xcptool/ui/main_window.py xcptool/tests/ui/test_calibration_view.py
git commit -m "feat(xcptool): Read acts on every selected row; consolidate MainWindow read paths"
```

---

### Task 4: Final regression pass + DEV_PLAN.md status update

**Files:**
- Modify: `xcptool/DEV_PLAN.md` (§11, status line for item 1)

**Interfaces:**
- Consumes: nothing new — this task only verifies and documents.

- [ ] **Step 1: Full suite**

Run: `xcptool\.venv\Scripts\python.exe -m pytest xcptool/tests/ -q`
Expected: PASS, 0 failures, 0 unexpected skips.

- [ ] **Step 2: Manual smoke check (per `DEV_PLAN.md §6` "không crash" criteria)**

Launch the app against a loaded A2L with at least one struct and one `VAL_BLK` array (`xcptool\run.bat` or `xcptool\.venv\Scripts\python.exe -m xcptool.cli.main`), connect to the fake/virtual bus, Ctrl-click 3-4 rows spanning a struct + a scalar + an array in the Calibration view, click "Read" then edit one value and click "Write Selected" — confirm only the edited row's group is written (check the CAN trace dock) and the app does not crash or freeze.

- [ ] **Step 3: Update DEV_PLAN.md**

In `xcptool/DEV_PLAN.md §11`, change:

```
**Trạng thái: spec đã duyệt, chưa triển khai.** 3 tính năng liên quan, làm
theo đúng thứ tự phụ thuộc dưới đây (branch `feature`).
```

to:

```
**Trạng thái: mục (1) đã triển khai xong (2026-09-19); (2) và (3) chưa bắt
đầu.** 3 tính năng liên quan, làm theo đúng thứ tự phụ thuộc dưới đây
(branch `feature`).
```

- [ ] **Step 4: Commit**

```bash
git add xcptool/DEV_PLAN.md
git commit -m "docs(xcptool): mark calibration multi-select feature as shipped"
```

**→ Feature complete when Task 4 commit is green.** `CalibrationView.tree` is `ExtendedSelection`; "Read" and "Write Selected" both act on the full row selection; `MainWindow.read_characteristic()` no longer exists anywhere in the codebase — `grep -rn "read_characteristic\b" xcptool/src xcptool/tests` must return **no matches** (the `\b` word boundary does not match inside `read_characteristics`, so any hit means the old single-name method is still referenced somewhere).
