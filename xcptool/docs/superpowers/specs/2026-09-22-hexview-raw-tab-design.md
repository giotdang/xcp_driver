# Hex View — Raw Tab (full file content, original record layout)

**Status:** Approved by user, ready for implementation planning.
**Date:** 2026-09-22
**Scope:** additions to `xcptool/src/xcptool/a2l/hexfile.py`
(`read_records()`, internal chunking-preservation in `patch_and_save()`);
new `Session.hex_raw_rows()`; new `ui/hex_raw_model.py`
(`QAbstractTableModel`); `ui/hex_view.py` gains a `QTabWidget` wrapping the
existing Calibration pair and a new Raw pair.
**Depends on:** [`2026-09-21-hexfile-generate-design.md`](2026-09-21-hexfile-generate-design.md)
— this is an additional presentation mode inside the same Hex View, built
on the same loaded-file session state (`Session.load_hex_file()`) and the
same `patch_and_save()` this spec extends. No new dependency on the
Calibration tab's A2L-driven data (`enumerate_leaves()`), deliberately —
see §2.

## 1. Motivation

The existing Hex View (shipped) shows one row per A2L calibration
parameter — useful for diffing known values, but it hides everything else
in the file: surrounding code, other data, and the file's own physical
line structure. The user wants to also see the file exactly as it is on
disk — address and raw bytes, one row per original record, nothing added
or removed — as a second, independent way to look at the same loaded file
and its patched result.

## 2. Goals / non-goals

**Goals:**
- Hex View gains a `QTabWidget`: **Calibration** (existing Origin/Mod
  pair, unchanged) and **Raw** (new Origin/Mod pair). Both tabs present
  the same underlying loaded file and generate result, just at different
  granularity.
- Raw's rows are **exactly the file's own original data records** — same
  address, same byte count per row as actually written in the hex/s19
  file. No re-chunking into a fixed grid (rejected during brainstorming:
  `bincopy`'s own re-serialization does not preserve original record
  boundaries — verified empirically, see §3).
- Raw **does not require an A2L to be loaded** — only the hex/s19 file.
  It can populate as soon as "Load Hex/S19…" succeeds, independent of
  Calibration's A2L-gated state. This is a deliberate decoupling: Raw's
  data source (`read_records()`) has nothing to do with `enumerate_leaves()`
  or `A2LDatabase`.
- Raw's table is **lazy-rendered** (`QAbstractTableModel` + `QTableView`,
  not the eager `QTableWidget` Calibration uses) — a multi-hundred-KB to
  multi-MB real flash image can have tens to hundreds of thousands of
  rows; only on-screen rows may ever be materialized.
- **Generate** (the already-shipped flow, unchanged) now also makes
  `patch_and_save()` preserve the *source* file's own dominant per-record
  byte length when writing the output, instead of `bincopy`'s own default
  chunking — see §3. This keeps Origin's and Mod's Raw rows aligned by
  address in the common case, and is a strictly better default for the
  output file regardless of whether the Raw tab existed at all (a
  minimally-perturbed re-save is less surprising to open in any other
  hex-editing tool too).
- Mod's Raw table reflects the **actual saved output file**, re-read from
  disk — not the in-memory patch list Calibration's Mod tab uses — because
  row layout is a property of the physical file text, not just byte
  content.
- Diff highlighting in Raw: whole row highlighted if its bytes differ from
  the row at the **same address** in the other table (matched by address,
  not row index — robust even if source chunking was irregular enough that
  the dominant-size heuristic doesn't fully replicate it for every
  record).
- Columns: **Address, Bytes (hex)** — no ASCII column (decided during
  brainstorming).

**Non-goals:**
- No editing in the Raw tab — read-only, same as Calibration's tables.
- No attempt to perfectly replicate a source file whose original records
  have genuinely mixed, non-uniform byte lengths — the dominant-size
  heuristic (§3) picks the most common length and uses it for the whole
  output. A file with irregular chunking may see some output records
  split differently than the input; §2's address-matched diffing (not
  index-matched) means this degrades gracefully rather than misaligning
  the whole view.
- No column for decoded/interpreted values in Raw (that's what
  Calibration is for) — Raw is intentionally the file's byte content only.
- No virtualization work for the Calibration tab — it stays a
  `QTableWidget`, sized to the number of A2L calibration leaves (tens to
  low hundreds), which is not a performance concern.

## 3. Verified technical groundwork (done during brainstorming, not assumed)

These were confirmed empirically against the installed `bincopy==20.1.1`
before writing this spec, because getting any of them wrong would produce
silently incorrect addresses or a misleading "faithful" view:

- **`bincopy.BinFile` merges contiguous/adjacent added ranges into flat
  `Segments` at parse time**, discarding original record boundaries.
  `bf.segments.chunks(size=16)` (considered and rejected as the Raw row
  source) re-chunks the *merged* result into a new uniform grid — for two
  original 20-byte records at `0x100`/`0x114`, it produced `16, 16, 8`
  instead of `20, 20`. Segment merging happens **before** any chunking
  call sees the data, so no `chunks()` parameter can undo it.
- **`bincopy.unpack_ihex(line)` / `unpack_srec(line)`** are the
  per-line, non-merging primitives `BinFile.add_ihex()`/`add_srec()` use
  internally — `(type, address, size, data)` for exactly one line, with
  its checksum already validated (raises `bincopy.Error` on mismatch).
  These are what `read_records()` (§4) is built on.
- **Intel HEX per-line addresses are only 16 bits** — a file whose data
  spans more than 64KB (e.g. this project's own example, based at
  `0x80100000`) carries the upper bits in a separate **type 04** (extended
  linear address) or type 02 (extended segment address, offset `<<4`,
  legacy/rare) record that precedes the data records it applies to.
  `unpack_ihex()` on a type-00 data line returns only that line's own
  16-bit address field — `0x0000`, not `0x80100000` — the caller must
  track the most recent type-04/02 record's offset and add it. Verified
  directly: a real file based at `0x80100000` decodes as a type-04 record
  carrying `0x8010`, followed by a type-00 record whose own address field
  is `0x0000`.
- **S-record has no equivalent problem** — S1 (16-bit), S2 (24-bit), S3
  (32-bit) data records each carry their complete address directly.
  Verified: `unpack_srec()` on an S3 line based at `0x80100000` returned
  `2148532224` (`= 0x80100000`) immediately, no extra state needed.
- **`as_ihex()`/`as_srec()` default to `bincopy`'s own chunking**
  (`number_of_data_bytes=32` unless overridden), not the input's —
  verified: three original 8-byte records became one 24-byte record under
  the default. Passing an explicit `number_of_data_bytes=N` matching the
  original reproduces the original record layout exactly (byte-for-byte,
  including identical per-line checksums).

## 4. Module: `a2l/hexfile.py` additions

```python
def read_records(path: Path) -> list[tuple[int, bytes]]:
    """Every ORIGINAL data record in `path`, in file order, address and
    byte length exactly as written — no merging, no re-chunking. This is
    what the file's own lines say, nothing added or removed.

    Intel HEX: tracks type 04 (extended linear, offset = value << 16) and
    type 02 (extended segment, offset = value << 4) records as running
    state, applied to subsequent type 00 (data) records' addresses. Type
    01 (EOF) stops parsing; types 03/05 (start address) are informational
    and skipped.

    Motorola S-record: S1/S2/S3 (data, 16/24/32-bit address) records are
    returned directly — no running state needed, each carries its
    complete address. S0 (header), S5/S6 (count), S7/S8/S9 (start
    address/termination) are skipped.

    Raises:
        ValueError: extension not recognized (reuses `_format_for()`).
        OSError: file unreadable.
        bincopy.Error: a line's checksum doesn't match its content.
    """


def _dominant_record_size(records: list[tuple[int, bytes]]) -> int:
    """Most common byte length among `records`' data, defaulting to 32
    (bincopy's own default) if `records` is empty. Ties broken by
    whichever length appears first in file order."""
```

`patch_and_save()` (existing, unchanged signature) gains one internal
step: before the final `as_ihex()`/`as_srec()` call, it calls
`read_records(source_path)` (already reading that file for the
coverage-check pass — no new I/O) and computes
`_dominant_record_size(...)`, passing it as `number_of_data_bytes=N` to
the save call instead of leaving bincopy's default in place. Every
existing caller and test is unaffected in behavior except that output
files now have tighter, source-matching record sizes instead of
bincopy's default 32-byte chunking.

## 5. `Session.hex_raw_rows()`

```python
def hex_raw_rows(self) -> list[tuple[int, bytes]]:
    """Every original data record of the currently loaded hex/s19 file,
    in file order — see a2l.hexfile.read_records(). Empty list if no
    file is loaded.

    Raises: XcpToolError on re-read failure (file removed/changed on
    disk since Session.load_hex_file() — same failure mode load_hex_file
    itself already handles, surfaced here on the rarer path where the
    file vanishes between load and this call).
    """
```

`RealSession`/`FakeSession`: thin wrappers, same pattern as `hex_regions()`
— `RealSession` uses `@_guarded(...)`, `FakeSession` uses explicit
`try/except` (matching each file's own established convention, per the
Hex View plan's Task 6 correction). Both call
`hexfile.read_records(self._hex_path)`.

A second method for the Mod side, reading an arbitrary already-written
output file (not the currently-loaded one):

```python
def hex_raw_rows_of(self, path: str | Path) -> list[tuple[int, bytes]]:
    """Every original data record of the file at `path` — same as
    hex_raw_rows() but for an arbitrary file, not the currently loaded
    one. Used to re-read a just-generated output file for the Raw Mod
    table."""
```

## 6. UI: Raw tab

**Tab structure (`ui/hex_view.py`):** wrap the existing
`origin_table`/`mod_table` `QHBoxLayout` in a `QTabWidget` page
("Calibration"), add a second page ("Raw") with its own origin/mod pair
built from the new model. `HexView`'s public API gains no new
constructor parameters — the Raw tables are internal, populated the same
way Calibration's are (via `Session` calls routed through `MainWindow`).

**New file `ui/hex_raw_model.py`:**

```python
class HexRawTableModel(QAbstractTableModel):
    """Address + hex-bytes rows for one loaded/generated hex file.
    Lazy — Qt only calls data() for on-screen rows regardless of how
    many rows() there are."""

    def set_rows(self, rows: list[tuple[int, bytes]]) -> None:
        """Replace all rows and reset the model."""

    def set_diff_addresses(self, addresses: set[int]) -> None:
        """Addresses whose row should render highlighted (§2 diff rule)
        — set once after both Origin and Mod rows are known, cheap O(1)
        lookup per row in data()'s background-role branch."""
```

Two columns (`Address`, `Bytes`) via `columnCount()`/`headerData()`;
`rowCount()` = `len(self._rows)`; `data()` handles `DisplayRole` (hex
text, e.g. `f"0x{addr:08X}"` / `data.hex().upper()`) and
`BackgroundRole` (the same `_DIFF_BRUSH` colour `hex_view.py` already
defines, reused via import — not redefined).

**Population flow:**
- On `Session.load_hex_file()` success (already wired for Calibration's
  origin table refresh — extend that same success handler): also call
  `session.hex_raw_rows()` (worker thread, same `_call()` pattern) and
  feed the Raw Origin model.
- On `Session.generate_hex_from_dataset()` success (already wired): also
  call `session.hex_raw_rows_of(output_path)` and feed the Raw Mod model,
  then compute the diff-address set (origin rows keyed by address vs. mod
  rows, same-address-different-bytes) and call `set_diff_addresses()` on
  the Mod model.

## 7. Error handling

| Case | Behavior |
|---|---|
| Raw tab opened before any hex file loaded | Empty tables, no error (matches Calibration's "load a file first" framing) |
| `read_records()` hits a bad checksum mid-file | Whole call raises (same all-or-nothing as `hexfile.load()` today) — surfaced via the existing `load_hex_file`/`generate_hex_from_dataset` error paths, no new UI error path needed since Raw shares those triggers |
| Source file has irregular (non-uniform) record sizes | `_dominant_record_size()` picks the majority; output may not byte-for-byte replicate minority-sized records' original grouping — documented limitation (§2), not an error |
| Generate produces a Mod file whose row *count* differs from Origin's (rare, irregular-source edge case) | No crash — diffing is address-keyed, not index-keyed; rows present in one but not the other simply don't match for highlighting purposes |

## 8. Testing

- `tests/unit/test_hexfile.py` additions: `read_records()` against a
  real extended-linear-address Intel HEX fixture (regression-locks §3's
  finding — assert the decoded address is the *combined* one, not the
  line's own 16-bit field); S-record fixture (no extended-address state
  needed); non-data record types (EOF, header, count, start-address)
  correctly excluded from the returned rows; a file with irregular
  (mixed) record sizes still returns every record intact.
  `_dominant_record_size()`: uniform-size file picks that size; mixed
  file picks the majority; empty list defaults to 32. `patch_and_save()`:
  output's records match input's sizes when the input is uniform; a
  patch landing mid-record doesn't change that record's address/size
  boundaries, only its bytes.
- `tests/unit/test_session_hexview.py` additions: `hex_raw_rows()` /
  `hex_raw_rows_of()` against both `RealSession`/`FakeSession`, empty
  list before any load, matches `read_records()` directly.
- `tests/unit/test_hex_raw_model.py` (new, no Qt needed for the pure
  logic parts, but the model itself needs `QAbstractTableModel` so this
  file does need the Qt test setup): `rowCount()`/`data()` correctness;
  a row count in the thousands doesn't require `data()` to have been
  called for more than a handful of them (asserts laziness cheaply,
  without needing a real multi-MB fixture); `set_diff_addresses()`
  changes exactly the intended rows' `BackgroundRole`.
- `tests/ui/test_hex_view.py` / `test_hex_view_integration.py`
  additions: tab exists and is reachable; Raw Origin populates on
  successful hex load without requiring A2L; Raw Mod populates after a
  successful generate, re-reading the output file rather than reusing
  in-memory patch bytes; diff highlighting lines up by address across a
  generate that changes a subset of records.
