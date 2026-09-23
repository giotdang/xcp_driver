# Hex View Raw Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Raw" tab to the existing Hex View, showing every original
data record of the loaded hex/s19 file (address + bytes exactly as
written, no re-chunking), alongside the existing "Calibration" tab.

**Architecture:** A new pure function `a2l/hexfile.read_records()` parses
a hex/s19 file's original lines directly via `bincopy.unpack_ihex()`/
`unpack_srec()` (not `BinFile.segments`, which merges adjacent data and
loses original record boundaries). `patch_and_save()` gains an internal
step that detects the source file's dominant record size and preserves it
on output, so Origin/Mod rows stay aligned by address. A new
`Session.hex_raw_rows()`/`hex_raw_rows_of()` exposes this to the UI. A new
`QAbstractTableModel` (`ui/hex_raw_model.py`) renders it lazily — required
because a real flash image can have far more rows than the existing
eager `QTableWidget` (used by the Calibration tab) can handle. `ui/
hex_view.py` wraps both tab's tables in a `QTabWidget`.

**Tech Stack:** Python 3.11+, PySide6 (`QAbstractTableModel`, `QTableView`,
`QTabWidget` — new to this codebase, verified working against the
installed PySide6 6.11.1 during planning), `bincopy` (already a
dependency — `unpack_ihex`/`unpack_srec` module-level functions, not
previously used in this codebase).

**Spec:** [`docs/superpowers/specs/2026-09-22-hexview-raw-tab-design.md`](../specs/2026-09-22-hexview-raw-tab-design.md)

## Global Constraints

- `read_records()` returns original records **exactly as written** — no
  re-chunking, no padding, no merging. Non-data record types are consumed
  for address-tracking (Intel HEX extended-address records) or skipped
  (headers/counts/termination), never returned as rows.
- Raw tab requires **only** a loaded hex/s19 file — never gated on A2L
  being loaded (unlike Calibration).
- Raw tables are **read-only** (no editing), matching Calibration's
  tables.
- Diff highlighting in Raw is **address-matched, not index-matched** —
  robust to the rare case where the dominant-size heuristic doesn't fully
  replicate an irregularly-chunked source file.
- Columns: **Address, Bytes (hex)** only — no ASCII column (decided during
  brainstorming).
- `patch_and_save()`'s public signature does not change — the
  chunking-preservation is an internal behavior change only.

---

## Task 1: `a2l/hexfile.py` — `read_records()`

**Files:**
- Modify: `xcptool/src/xcptool/a2l/hexfile.py`
- Test: `xcptool/tests/unit/test_hexfile.py`

**Interfaces:**
- Consumes: `_format_for()` (existing, `hexfile.py:20-35`).
- Produces: `read_records(path: Path) -> list[tuple[int, bytes]]`.
  Consumed by Task 2 (`_dominant_record_size`), Task 3
  (`Session.hex_raw_rows()`/`hex_raw_rows_of()`).

Verified empirically during planning against installed `bincopy==20.1.1`
(all three findings load-bearing for this task):
- `bincopy.unpack_ihex(line) -> (type: int, address: int, size: int,
  data: bytearray)` decodes exactly one Intel HEX line, checksum already
  validated (raises `bincopy.Error` on mismatch) — this is the per-line
  primitive `BinFile.add_ihex()` uses internally, distinct from the
  merged `Segments` model.
- Intel HEX per-line addresses are only 16 bits. A type `0x04` record
  (extended linear address) sets the upper bits for every subsequent
  type `0x00` (data) record until the next type `0x04`/`0x02`:
  `real_address = (offset << 16) + line_address` for type 4,
  `real_address = (offset << 4) + line_address` for the legacy type
  `0x02` (extended segment address). Confirmed directly: a file based at
  `0x80100000` produces a type-4 record carrying `0x8010`, followed by a
  type-0 record whose own address field is `0x0000` — the type-0 record
  alone does NOT carry the real address.
- `bincopy.unpack_srec(line) -> (type: str, address: int, size: int,
  data: bytearray)` — S-record's `type` is a **string** digit (`'0'`
  through `'9'`), unlike Intel HEX's int. S1/S2/S3 (data, 16/24/32-bit
  address) each carry their **complete** address directly — no
  extended-address state needed. Confirmed: an S3 record based at
  `0x80100000` decoded with `address == 2148532224` (`== 0x80100000`)
  immediately.

- [ ] **Step 1: Write the failing tests**

Append to `xcptool/tests/unit/test_hexfile.py` (add `from xcptool.a2l
import hexfile` is already imported; no new imports needed beyond what's
already there):

```python
def test_read_records_ihex_returns_original_lines_unmodified(tmp_path: Path) -> None:
    # Three original 8-byte records — read_records() must return exactly
    # these three, not re-chunked into anything else.
    p = _write(tmp_path, "image.hex",
                ":080100000001020304050607DB\n"
                ":0801080008090A0B0C0D0E0F93\n"
                ":0801100010111213141516174B\n"
                ":00000001FF\n")
    records = hexfile.read_records(p)
    assert records == [
        (0x0100, bytes(range(0, 8))),
        (0x0108, bytes(range(8, 16))),
        (0x0110, bytes(range(16, 24))),
    ]


def test_read_records_ihex_applies_extended_linear_address(tmp_path: Path) -> None:
    # Regression: a type-04 record's offset must be combined with the
    # following type-00 record's own (16-bit-only) address field — the
    # type-00 line alone encodes 0x0000, not the real high address.
    p = _write(tmp_path, "image.hex",
                ":0200000480106A\n"
                ":080000000102030405060708D4\n"
                ":00000001FF\n")
    records = hexfile.read_records(p)
    assert records == [(0x80100000, bytes(range(1, 9)))]


def test_read_records_ihex_stops_at_eof_record(tmp_path: Path) -> None:
    # A record after :00000001FF (EOF) must not be parsed as data. Note:
    # read_records() breaks the loop as soon as it sees the EOF record, so
    # it never actually reaches (or validates the checksum of) this third
    # line either way — its checksum is still correct here (verified via
    # bincopy.unpack_ihex() while writing this plan) so the fixture stays
    # honest even though this specific test doesn't exercise that path.
    p = _write(tmp_path, "image.hex",
                ":080100000001020304050607DB\n"
                ":00000001FF\n"
                ":080200000102030405060708D2\n")
    records = hexfile.read_records(p)
    assert records == [(0x0100, bytes(range(0, 8)))]


def test_read_records_srec_returns_original_lines_unmodified(tmp_path: Path) -> None:
    p = _write(tmp_path, "image.s19",
                "S30D8010000001020304050607083E\n"
                "S5030001FB\n")
    records = hexfile.read_records(p)
    assert records == [(0x80100000, bytes(range(1, 9)))]


def test_read_records_srec_skips_count_and_termination_records(tmp_path: Path) -> None:
    # S0 (header), S5 (count) must not appear as rows — only S1/S2/S3 data.
    p = _write(tmp_path, "image.s19",
                "S0030000FC\n"
                "S30D8010000001020304050607083E\n"
                "S5030001FB\n"
                "S70500000000FA\n")
    records = hexfile.read_records(p)
    assert records == [(0x80100000, bytes(range(1, 9)))]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_hexfile.py -v -k read_records`
Expected: FAIL/ERROR — `read_records` doesn't exist yet.

- [ ] **Step 3: Implement `read_records()`**

Append to `xcptool/src/xcptool/a2l/hexfile.py`, and add `"read_records"`
to the existing `__all__` list (`hexfile.py:14`):

```python
def read_records(path: Path) -> list[tuple[int, bytes]]:
    """Every ORIGINAL data record in `path`, in file order, address and
    byte length exactly as written — no merging, no re-chunking (unlike
    `load()`'s `bincopy.BinFile`, which coalesces adjacent data into flat
    Segments at parse time and loses this).

    Intel HEX: tracks type 0x04 (extended linear, offset = value << 16)
    and type 0x02 (extended segment, offset = value << 4) records as
    running state, applied to subsequent type 0x00 (data) records'
    addresses. Type 0x01 (EOF) stops parsing. Types 0x03/0x05 (start
    address) are informational and skipped.

    Motorola S-record: S1/S2/S3 (data, 16/24/32-bit address) records are
    returned directly — no running state needed, each carries its
    complete address. S0 (header), S5/S6 (count), S7/S8/S9 (termination/
    start address) are skipped.

    Raises:
        ValueError: extension not recognized.
        OSError: file unreadable.
        bincopy.Error: a line's checksum doesn't match its content.
    """
    fmt = _format_for(path)
    text = path.read_text(encoding="ascii")
    rows: list[tuple[int, bytes]] = []

    if fmt == "ihex":
        extended_offset = 0
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            record_type, address, _size, data = bincopy.unpack_ihex(line)
            if record_type == 0x00:
                rows.append((extended_offset + address, bytes(data)))
            elif record_type == 0x04:
                extended_offset = int.from_bytes(data, "big") << 16
            elif record_type == 0x02:
                extended_offset = int.from_bytes(data, "big") << 4
            elif record_type == 0x01:
                break
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            record_type, address, _size, data = bincopy.unpack_srec(line)
            if record_type in ("1", "2", "3"):
                rows.append((address, bytes(data)))

    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_hexfile.py -v`
Expected: all pass, including the 5 new ones (17 total).

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/a2l/hexfile.py xcptool/tests/unit/test_hexfile.py
git commit -m "feat(xcptool): add a2l/hexfile.py read_records() — original hex/s19 record layout"
```

---

## Task 2: `a2l/hexfile.py` — preserve source chunking in `patch_and_save()`

**Files:**
- Modify: `xcptool/src/xcptool/a2l/hexfile.py`
- Test: `xcptool/tests/unit/test_hexfile.py`

**Interfaces:**
- Consumes: `read_records()` (Task 1).
- Produces: `_dominant_record_size(records: list[tuple[int, bytes]]) ->
  int` (module-internal, not in `__all__`). `patch_and_save()`'s
  observable behavior changes (output record size matches source's
  dominant size instead of bincopy's own default) but its signature does
  not.

Verified during planning: `as_ihex()`/`as_srec()` default to bincopy's
own chunking (`number_of_data_bytes=32` unless given explicitly) —
three original 8-byte records became one 24-byte record under the
default. Passing `number_of_data_bytes=N` explicitly reproduces the
original record layout exactly (byte-for-byte, including identical
per-line checksums) when the source was uniformly N-byte chunked.
Also verified: patching 2 bytes squarely inside the middle record of a
3×8-byte source, then saving with `number_of_data_bytes=8`, changes only
that one line's data+checksum — record count and addresses are
unaffected.

- [ ] **Step 1: Write the failing tests**

Append to `xcptool/tests/unit/test_hexfile.py`:

```python
def test_dominant_record_size_picks_majority() -> None:
    records = [(0, b"x" * 16), (16, b"x" * 16), (32, b"x" * 4)]
    assert hexfile._dominant_record_size(records) == 16


def test_dominant_record_size_ties_broken_by_first_occurrence() -> None:
    # 8-byte and 16-byte records both appear twice; 8 appears FIRST in
    # file order and must win — not an arbitrary/hash-order tie-break.
    records = [(0, b"x" * 8), (8, b"x" * 16), (24, b"x" * 8), (40, b"x" * 16)]
    assert hexfile._dominant_record_size(records) == 8


def test_dominant_record_size_empty_defaults_to_32() -> None:
    assert hexfile._dominant_record_size([]) == 32


def test_patch_and_save_preserves_uniform_source_record_size(tmp_path: Path) -> None:
    src = _write(tmp_path, "image.hex",
                ":080100000001020304050607DB\n"
                ":0801080008090A0B0C0D0E0F93\n"
                ":0801100010111213141516174B\n"
                ":00000001FF\n")
    out = tmp_path / "image_mod.hex"
    hexfile.patch_and_save(src, [(0x0108, b"\xAA\xBB", "midRecordParam")], out)

    out_records = hexfile.read_records(out)
    # Same THREE records, same addresses — only the middle one's bytes changed.
    assert [addr for addr, _data in out_records] == [0x0100, 0x0108, 0x0110]
    assert out_records[1][1] == b"\xAA\xBB" + bytes(range(10, 16))
    assert out_records[0][1] == bytes(range(0, 8))  # untouched record unchanged
    assert out_records[2][1] == bytes(range(16, 24))  # untouched record unchanged
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_hexfile.py -v -k dominant_record_size or preserves_uniform`
Expected: FAIL — `_dominant_record_size` doesn't exist;
`test_patch_and_save_preserves_uniform_source_record_size` fails because
the current `patch_and_save()` collapses all three records into one
(bincopy's default chunking).

- [ ] **Step 3: Implement `_dominant_record_size()` and update `patch_and_save()`**

Add to `xcptool/src/xcptool/a2l/hexfile.py`, directly above
`patch_and_save()`:

```python
def _dominant_record_size(records: list[tuple[int, bytes]]) -> int:
    """Most common byte length among `records`' data. Ties are broken by
    whichever length appears FIRST in file order (not an arbitrary/hash
    tie-break) — deliberately not implemented via `collections.Counter`,
    whose `most_common()` tie order isn't a documented guarantee. Empty
    `records` defaults to 32, matching bincopy's own default so an empty
    or unparseable source doesn't change existing behavior."""
    if not records:
        return 32
    counts: dict[int, int] = {}
    order: list[int] = []
    for _address, data in records:
        size = len(data)
        if size not in counts:
            counts[size] = 0
            order.append(size)
        counts[size] += 1
    best_size = order[0]
    best_count = counts[best_size]
    for size in order[1:]:
        if counts[size] > best_count:
            best_size = size
            best_count = counts[size]
    return best_size
```

Modify `patch_and_save()`'s body (`hexfile.py:126-130`) — replace the
final format-and-write lines:

```python
    text = bf.as_ihex() if out_fmt == "ihex" else bf.as_srec()
    output_path.write_text(text, encoding="ascii")
```

with:

```python
    record_size = _dominant_record_size(read_records(source_path))
    text = (
        bf.as_ihex(number_of_data_bytes=record_size) if out_fmt == "ihex"
        else bf.as_srec(number_of_data_bytes=record_size)
    )
    output_path.write_text(text, encoding="ascii")
```

This re-reads `source_path` a second time (once via `_read_into()` for
the `BinFile`/coverage-check, once via `read_records()` for the
dominant-size computation) — a deliberate simplicity-over-micro-
optimization tradeoff: `read_records()` is a lightweight line-by-line
text parse, and source files at the sizes this tool handles (KB to low
MB) make a second pass a non-issue. Keeps the two parsing concerns
(binary patching vs. record-layout inspection) cleanly separate instead
of threading a new return value through `_read_into()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_hexfile.py -v`
Expected: all pass (21 total).

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/a2l/hexfile.py xcptool/tests/unit/test_hexfile.py
git commit -m "feat(xcptool): patch_and_save() preserves source file's record chunking"
```

---

## Task 3: `Session.hex_raw_rows()` / `hex_raw_rows_of()`

**Files:**
- Modify: `xcptool/src/xcptool/session/api.py`
- Modify: `xcptool/src/xcptool/session/real.py`
- Modify: `xcptool/src/xcptool/session/fake.py`
- Test: `xcptool/tests/unit/test_session_hexview.py`

**Interfaces:**
- Consumes: `read_records()` (Task 1).
- Produces: `Session.hex_raw_rows() -> list[tuple[int, bytes]]`,
  `Session.hex_raw_rows_of(path: str | Path) -> list[tuple[int, bytes]]`.
  Consumed by `ui/main_window.py` (Task 5).

- [ ] **Step 1: Write the failing tests**

Append to `xcptool/tests/unit/test_session_hexview.py` (its existing
`_write_hex()` helper and `session` fixture — parametrized over
`RealSession`/`FakeSession` — are reused as-is):

```python
def test_hex_raw_rows_before_load_returns_empty(session) -> None:
    assert session.hex_raw_rows() == []


def test_hex_raw_rows_matches_read_records(session, tmp_path) -> None:
    p = _write_hex(tmp_path)
    session.load_hex_file(p)
    from xcptool.a2l import hexfile
    assert session.hex_raw_rows() == hexfile.read_records(p)


def test_hex_raw_rows_of_reads_an_arbitrary_file_not_the_loaded_one(session, tmp_path) -> None:
    loaded = _write_hex(tmp_path)
    session.load_hex_file(loaded)

    other = tmp_path / "other.hex"
    other.write_text(":04020000AABBCCDDEC\n:00000001FF\n", encoding="ascii")

    assert session.hex_raw_rows() == [(0x0100, bytes(range(1, 9)))]
    assert session.hex_raw_rows_of(other) == [(0x0200, b"\xAA\xBB\xCC\xDD")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_session_hexview.py -v -k raw_rows`
Expected: FAIL — `hex_raw_rows`/`hex_raw_rows_of` don't exist on either session yet.

- [ ] **Step 3: Add to the `Session` Protocol**

In `xcptool/src/xcptool/session/api.py`, right after `generate_hex_from_dataset`'s
docstring (`api.py:574-584`):

```python
    def hex_raw_rows(self) -> list[tuple[int, bytes]]:
        """Every original data record of the currently loaded hex/s19
        file, in file order — see a2l.hexfile.read_records(). Empty list
        if no file is loaded."""

    def hex_raw_rows_of(self, path: str | Path) -> list[tuple[int, bytes]]:
        """Every original data record of the file at `path` — same as
        `hex_raw_rows()` but for an arbitrary file, not necessarily the
        currently loaded one (used to re-read a just-generated output
        file).

        Raises: XcpToolError nếu file không đọc được/nội dung không hợp lệ.
        """
```

- [ ] **Step 4: Implement in `RealSession`**

In `xcptool/src/xcptool/session/real.py`, right after `generate_hex_from_dataset`
(`real.py:574-582` per the grep during planning — insert after its
closing line):

```python
    @_guarded("đọc toàn bộ hex/s19")
    def hex_raw_rows(self) -> list[tuple[int, bytes]]:
        if self._hex_path is None:
            return []
        return hexfile.read_records(self._hex_path)

    @_guarded("đọc toàn bộ hex/s19")
    def hex_raw_rows_of(self, path: str | Path) -> list[tuple[int, bytes]]:
        return hexfile.read_records(Path(path))
```

- [ ] **Step 5: Implement in `FakeSession`**

In `xcptool/src/xcptool/session/fake.py`, right after `generate_hex_from_dataset`
(`fake.py:492-498`):

```python
    def hex_raw_rows(self) -> list[tuple[int, bytes]]:
        if self._hex_path is None:
            return []
        try:
            return hexfile.read_records(self._hex_path)
        except (ValueError, OSError) as exc:
            raise XcpToolError(str(exc)) from exc

    def hex_raw_rows_of(self, path: str | Path) -> list[tuple[int, bytes]]:
        try:
            return hexfile.read_records(Path(path))
        except (ValueError, OSError) as exc:
            raise XcpToolError(str(exc)) from exc
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_session_hexview.py -v`
Expected: all pass (6 new × 2 session params = 12 new, plus the existing
16 = 28 total in this file).

- [ ] **Step 7: Run the full unit test suite for regressions**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/ -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add xcptool/src/xcptool/session/api.py xcptool/src/xcptool/session/real.py xcptool/src/xcptool/session/fake.py xcptool/tests/unit/test_session_hexview.py
git commit -m "feat(xcptool): add Session.hex_raw_rows()/hex_raw_rows_of()"
```

---

## Task 4: `ui/hex_raw_model.py` — lazy table model

**Files:**
- Create: `xcptool/src/xcptool/ui/hex_raw_model.py`
- Test: `xcptool/tests/ui/test_hex_raw_model.py` (new — **`tests/ui/`, not
  `tests/unit/`**: `QT_QPA_PLATFORM=offscreen` is set in
  `tests/ui/conftest.py` at import time and nowhere under `tests/unit/`;
  `QAbstractTableModel` is a `QObject` and needs a `QApplication` to
  exist, so this file must inherit that setup rather than risk trying to
  touch a real display server)

**Interfaces:**
- Consumes: nothing from earlier tasks (pure Qt component; row data is
  `list[tuple[int, bytes]]`, the same shape `Session.hex_raw_rows()`
  returns, but this model doesn't call Session itself).
- Produces: `HexRawTableModel(diff_brush: QBrush, parent: QObject | None
  = None)` with `set_rows(rows: list[tuple[int, bytes]]) -> None` and
  `set_diff_addresses(addresses: set[int]) -> None`. Consumed by
  `ui/hex_view.py` (Task 5).

`diff_brush` is a constructor parameter, not a module-level import of
`hex_view.py`'s `_DIFF_BRUSH` — importing it directly would create a
circular import (`hex_view.py` needs to import `HexRawTableModel` to use
it, `hex_raw_model.py` would need to import `_DIFF_BRUSH` back from
`hex_view.py`). Task 5 constructs both Raw models passing `hex_view.py`'s
own `_DIFF_BRUSH`, keeping one source of truth for the colour without the
cycle.

- [ ] **Step 1: Write the failing tests**

Create `xcptool/tests/ui/test_hex_raw_model.py`:

```python
"""ui/hex_raw_model.py — lazy QAbstractTableModel for the Hex View Raw
tab. Needs a QApplication (via tests/ui/conftest.py's offscreen setup),
even though the model itself has no visible widget."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor

from xcptool.ui.hex_raw_model import HexRawTableModel

_BRUSH = QBrush(QColor("#5a3d00"))


def test_columns_are_address_and_bytes() -> None:
    model = HexRawTableModel(_BRUSH)
    assert model.columnCount() == 2
    assert model.headerData(0, Qt.Horizontal) == "Address"
    assert model.headerData(1, Qt.Horizontal) == "Bytes"


def test_set_rows_populates_row_count_and_cell_text() -> None:
    model = HexRawTableModel(_BRUSH)
    model.set_rows([(0x100, b"\x01\x02"), (0x200, b"\x03\x04\x05")])

    assert model.rowCount() == 2
    assert model.data(model.index(0, 0)) == "0x00000100"
    assert model.data(model.index(0, 1)) == "0102"
    assert model.data(model.index(1, 0)) == "0x00000200"
    assert model.data(model.index(1, 1)) == "030405"


def test_data_is_not_called_eagerly_for_a_large_row_count() -> None:
    # Laziness check without needing a real multi-MB fixture or a visible
    # QTableView: data() must not have been invoked at all just from
    # set_rows() — Qt only calls it per cell when something actually
    # asks (e.g. a view painting visible cells).
    model = HexRawTableModel(_BRUSH)
    calls = []
    original_data = model.data
    model.data = lambda index, role=Qt.DisplayRole: (calls.append(1), original_data(index, role))[1]

    model.set_rows([(i * 16, bytes(4)) for i in range(50_000)])

    assert model.rowCount() == 50_000
    assert calls == []


def test_set_diff_addresses_highlights_only_the_matching_rows() -> None:
    model = HexRawTableModel(_BRUSH)
    model.set_rows([(0x100, b"\x01"), (0x200, b"\x02")])
    model.set_diff_addresses({0x200})

    assert model.data(model.index(0, 0), Qt.BackgroundRole) is None
    assert model.data(model.index(1, 0), Qt.BackgroundRole) == _BRUSH
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_hex_raw_model.py -v`
Expected: FAIL/ERROR — `xcptool.ui.hex_raw_model` doesn't exist yet.

- [ ] **Step 3: Implement `HexRawTableModel`**

```python
"""HexRawTableModel — lazy (address, bytes) table for the Hex View Raw
tab. Qt only calls data() for rows actually being painted, so this scales
to real flash-image row counts (tens to hundreds of thousands) without
eagerly building anything — unlike CalibrationView/Hex View's Calibration
tab, both of which use the eager QTableWidget (fine there: row count is
bounded by A2L calibration parameter count, tens to low hundreds).
"""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush

__all__ = ["HexRawTableModel"]

_COLUMNS = ["Address", "Bytes"]


class HexRawTableModel(QAbstractTableModel):
    def __init__(self, diff_brush: QBrush, parent=None) -> None:
        super().__init__(parent)
        self._diff_brush = diff_brush
        self._rows: list[tuple[int, bytes]] = []
        self._diff_addresses: set[int] = set()

    def set_rows(self, rows: list[tuple[int, bytes]]) -> None:
        self.beginResetModel()
        self._rows = rows
        self._diff_addresses = set()
        self.endResetModel()

    def set_diff_addresses(self, addresses: set[int]) -> None:
        self._diff_addresses = addresses
        if not self._rows:
            return
        top_left = self.index(0, 0)
        bottom_right = self.index(len(self._rows) - 1, len(_COLUMNS) - 1)
        self.dataChanged.emit(top_left, bottom_right, [Qt.BackgroundRole])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(_COLUMNS)

    def headerData(self, section: int, orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return _COLUMNS[section]

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        address, raw = self._rows[index.row()]
        if role == Qt.DisplayRole:
            return f"0x{address:08X}" if index.column() == 0 else raw.hex().upper()
        if role == Qt.BackgroundRole and address in self._diff_addresses:
            return self._diff_brush
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_hex_raw_model.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/ui/hex_raw_model.py xcptool/tests/ui/test_hex_raw_model.py
git commit -m "feat(xcptool): add ui/hex_raw_model.py — lazy table model for Hex View Raw tab"
```

---

## Task 5: Wire the Raw tab into `HexView` and `MainWindow`

**Files:**
- Modify: `xcptool/src/xcptool/ui/hex_view.py`
- Modify: `xcptool/src/xcptool/ui/main_window.py`
- Test: `xcptool/tests/ui/test_hex_view.py`
- Test: `xcptool/tests/ui/test_hex_view_integration.py`

**Interfaces:**
- Consumes: `HexRawTableModel` (Task 4), `Session.hex_raw_rows()`/
  `hex_raw_rows_of()` (Task 3).
- Produces: `HexView.raw_origin_view`/`raw_mod_view` (`QTableView`),
  `HexView.raw_origin_model`/`raw_mod_model` (`HexRawTableModel`),
  `HexView.on_raw_origin_ready(rows: list[tuple[int, bytes]]) -> None`,
  `HexView.on_raw_mod_ready(rows: list[tuple[int, bytes]]) -> None`.

- [ ] **Step 1: Write the failing tests**

In `xcptool/tests/ui/test_hex_view.py`, add
`from xcptool.ui.hex_raw_model import HexRawTableModel` to the imports,
then append:

```python
def test_raw_tab_exists_alongside_calibration_tab(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    assert isinstance(view.raw_origin_model, HexRawTableModel)
    assert isinstance(view.raw_mod_model, HexRawTableModel)
    assert view.raw_origin_view.model() is view.raw_origin_model
    assert view.raw_mod_view.model() is view.raw_mod_model


def test_on_raw_origin_ready_populates_the_raw_origin_model(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    view.on_raw_origin_ready([(0x100, b"\x01\x02"), (0x200, b"\x03\x04")])

    assert view.raw_origin_model.rowCount() == 2
    assert view.raw_origin_model.data(view.raw_origin_model.index(0, 1)) == "0102"


def test_on_raw_mod_ready_populates_and_highlights_only_changed_rows(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    view.on_raw_origin_ready([(0x100, b"\x01\x02"), (0x200, b"\x03\x04")])
    view.on_raw_mod_ready([(0x100, b"\xAA\xBB"), (0x200, b"\x03\x04")])

    from PySide6.QtCore import Qt
    model = view.raw_mod_model
    assert model.data(model.index(0, 0), Qt.BackgroundRole) is not None  # 0x100 changed
    assert model.data(model.index(1, 0), Qt.BackgroundRole) is None      # 0x200 unchanged
```

In `xcptool/tests/ui/test_hex_view_integration.py`, append:

```python
def test_load_hex_success_also_populates_raw_tab_without_a2l(window: MainWindow, tmp_path: Path, qtbot) -> None:
    # Raw must populate from the hex file alone — no A2L load in this test.
    p = tmp_path / "image.hex"
    p.write_text(":080100000102030405060708D3\n:00000001FF\n", encoding="ascii")

    window._on_hex_load_requested(str(p))
    qtbot.waitUntil(lambda: window.hex_view.raw_origin_model.rowCount() == 1, timeout=2000)
    assert window.hex_view.raw_origin_model.data(window.hex_view.raw_origin_model.index(0, 1)) == "0102030405060708"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_hex_view.py xcptool/tests/ui/test_hex_view_integration.py -v -k raw`
Expected: FAIL — `raw_origin_model` etc. don't exist on `HexView` yet.

- [ ] **Step 3: Restructure `HexView.__init__` into a `QTabWidget`**

In `xcptool/src/xcptool/ui/hex_view.py`, add imports:

```python
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .hex_raw_model import HexRawTableModel
```

(`QTableView`, `QTabWidget` are new to the existing import block;
`HexRawTableModel` is a new import line.)

Replace the `tables`/`root` construction at the end of `__init__`
(`hex_view.py:81-90`, currently):

```python
        tables = QHBoxLayout()
        self.origin_table = _make_table()
        self.mod_table = _make_table()
        tables.addWidget(self.origin_table)
        tables.addWidget(self.mod_table)

        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addLayout(tables)
        root.addWidget(self.status_label)
```

with:

```python
        cal_page = QWidget()
        cal_layout = QHBoxLayout(cal_page)
        self.origin_table = _make_table()
        self.mod_table = _make_table()
        cal_layout.addWidget(self.origin_table)
        cal_layout.addWidget(self.mod_table)

        raw_page = QWidget()
        raw_layout = QHBoxLayout(raw_page)
        self.raw_origin_model = HexRawTableModel(_DIFF_BRUSH)
        self.raw_mod_model = HexRawTableModel(_DIFF_BRUSH)
        self.raw_origin_view = QTableView()
        self.raw_origin_view.setModel(self.raw_origin_model)
        self.raw_mod_view = QTableView()
        self.raw_mod_view.setModel(self.raw_mod_model)
        raw_layout.addWidget(self.raw_origin_view)
        raw_layout.addWidget(self.raw_mod_view)

        tab_widget = QTabWidget()
        tab_widget.addTab(cal_page, "Calibration")
        tab_widget.addTab(raw_page, "Raw")

        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addWidget(tab_widget)
        root.addWidget(self.status_label)
```

- [ ] **Step 4: Add `on_raw_origin_ready()`/`on_raw_mod_ready()`**

Add to `HexView`, right after `on_regions_ready()` (`hex_view.py:113-115`):

```python
    def on_raw_origin_ready(self, rows: list[tuple[int, bytes]]) -> None:
        self.raw_origin_model.set_rows(rows)

    def on_raw_mod_ready(self, rows: list[tuple[int, bytes]]) -> None:
        self.raw_mod_model.set_rows(rows)
        origin_by_address = dict(self.raw_origin_model._rows)
        changed = {
            address for address, data in rows
            if origin_by_address.get(address) != data
        }
        self.raw_mod_model.set_diff_addresses(changed)
```

`self.raw_origin_model._rows` reaches into `HexRawTableModel`'s "private"
attribute — acceptable here since `hex_view.py` and `hex_raw_model.py`
are both part of the same `ui/` package and already tightly coupled by
construction (Task 4 built the model with no public rows-getter, since
nothing outside needed one until now). If this reach-in feels wrong once
written, add a trivial `rows` property to `HexRawTableModel` instead —
either is fine; don't add speculative API surface beyond what's used.

- [ ] **Step 5: Wire `MainWindow`**

In `xcptool/src/xcptool/ui/main_window.py`, modify `_after_hex_load()`
(`main_window.py:708-711`, currently):

```python
    def _after_hex_load(self, path: str) -> None:
        self.hex_view.set_hex_loaded(path)
        self._app_config.last_hex_path = path
        self._save_current_app_config()
```

Add a Raw-rows fetch after the existing three lines:

```python
    def _after_hex_load(self, path: str) -> None:
        self.hex_view.set_hex_loaded(path)
        self._app_config.last_hex_path = path
        self._save_current_app_config()
        self._call(
            "Reading full hex/s19 content…",
            self.session.hex_raw_rows,
            on_ok=self.hex_view.on_raw_origin_ready,
            on_err=lambda exc: self.hex_view.status_label.setText(f"Raw read failed: {exc}"),
        )
```

Modify `_on_hexview_generate_requested()` (`main_window.py:181-189`,
currently):

```python
    def _on_hexview_generate_requested(
        self, patches: list[tuple[int, bytes, str]], output_path: str,
    ) -> None:
        self._call(
            "Generating calibration hex/s19…",
            self.session.generate_hex_from_dataset, patches, output_path,
            on_ok=lambda _: self.hex_view.on_generate_done(output_path),
            on_err=self.hex_view.on_generate_error,
        )
```

to also fetch the Raw Mod rows on success:

```python
    def _on_hexview_generate_requested(
        self, patches: list[tuple[int, bytes, str]], output_path: str,
    ) -> None:
        def on_ok(_: object) -> None:
            self.hex_view.on_generate_done(output_path)
            self._call(
                "Reading generated hex/s19 content…",
                self.session.hex_raw_rows_of, output_path,
                on_ok=self.hex_view.on_raw_mod_ready,
                on_err=lambda exc: self.hex_view.status_label.setText(f"Raw read failed: {exc}"),
            )

        self._call(
            "Generating calibration hex/s19…",
            self.session.generate_hex_from_dataset, patches, output_path,
            on_ok=on_ok,
            on_err=self.hex_view.on_generate_error,
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_hex_view.py xcptool/tests/ui/test_hex_view_integration.py -v`
Expected: all pass.

- [ ] **Step 7: Run the full UI test suite for regressions**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/ -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add xcptool/src/xcptool/ui/hex_view.py xcptool/src/xcptool/ui/main_window.py xcptool/tests/ui/test_hex_view.py xcptool/tests/ui/test_hex_view_integration.py
git commit -m "feat(xcptool): wire Hex View Raw tab into HexView and MainWindow"
```

---

## Task 6: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ -q`
Expected: all pass. Baseline going into this plan was 619 (per
`DEV_PLAN.md §11` item 3's final note) — expect that plus every test
added in Tasks 1-5 above.

- [ ] **Step 2: Run the architecture boundary test specifically**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/test_boundaries.py -v`
Expected: all pass — confirms `ui/hex_raw_model.py` and the edited
`ui/hex_view.py` never import `xcptool.a2l` or `xcptool.master` directly
(the Raw tab's data arrives as plain `list[tuple[int, bytes]]` from
`Session`, same boundary-respecting shape as the Calibration tab's
patches).

- [ ] **Step 3: Manually try the Raw tab against the real example files**

`examples/xcp_daq_example.hex`/`.s19` and `xcptool/dataset.json` already
exist in the repo from earlier hand-testing of the Calibration tab. Load
the hex file, switch to the Raw tab, confirm it populates **without**
loading the A2L first (per this plan's Global Constraints) — then load
the A2L, generate from `dataset.json`, and confirm the Raw Mod tab shows
the same rows as Origin except for the addresses `dataset.json` actually
changes (`speedPid_kp`, `speedPid_ki`, `speedPid_outMax`,
`speedPid_outMin`, `adcCalPoints`), highlighted.

- [ ] **Step 4: Update `DEV_PLAN.md` §11**

Add a short note under item (3) (same pattern as the two notes already
there) recording that the Raw tab shipped, its final test count, and
anything Tasks 1-5 ended up doing differently from this plan, if
anything did.

- [ ] **Step 5: Commit**

```bash
git add xcptool/DEV_PLAN.md
git commit -m "docs(xcptool): mark Hex View Raw tab shipped"
```

---

## Plan Self-Review Notes

- **Spec coverage:** §2 goals — tab alongside Calibration (Task 5), rows
  are original records not re-chunked (Task 1, verified against
  `chunks()`'s rejected behavior in the spec's §3), Raw independent of
  A2L (Task 5's `_after_hex_load` hook, tested explicitly in
  `test_load_hex_success_also_populates_raw_tab_without_a2l`), lazy
  rendering (Task 4, laziness test), chunking-preserving generate (Task
  2), Mod re-read from disk not memory (Task 5's `hex_raw_rows_of`
  usage), address-matched diff (Task 5's `on_raw_mod_ready`), 2-column
  layout (Task 4). §3's four verified findings are all reproduced as
  regression tests (Task 1's extended-address test, Task 2's
  chunking-preservation test), not just asserted in prose.
- **Placeholder scan:** no TBD/TODO; every code block is real, either
  transcribed from a snippet actually executed during planning (Tasks 1,
  2) or new code following those same verified primitives (Tasks 3-5).
- **Type consistency:** `list[tuple[int, bytes]]` is the one row shape
  used everywhere — `read_records()` (Task 1), `hex_raw_rows()`/
  `hex_raw_rows_of()` (Task 3), `HexRawTableModel.set_rows()` (Task 4),
  `on_raw_origin_ready`/`on_raw_mod_ready` (Task 5) — no renamed fields
  or reordered tuples anywhere. `HexRawTableModel(diff_brush, parent)`'s
  constructor signature is identical at its one definition (Task 4) and
  its two call sites (Task 5).
