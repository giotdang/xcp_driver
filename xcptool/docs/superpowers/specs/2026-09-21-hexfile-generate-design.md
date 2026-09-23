# Hex View — Generate Calibration Hex/S-record File

**Status:** Approved by user, ready for implementation planning.
**Date:** 2026-09-21 (revision 2 — replaces this file's original content, a
context-menu-in-CalibrationView design, written the same day and never
implemented. The user pivoted during brainstorming to a dedicated view; the
original commit `0c14f47` still holds the old version in git history.)
**Scope:** new `ui/hex_view.py` (new nav route); new `ui/value_codec.py`
(extracted from `ui/calibration_view.py`); new `a2l/hexfile.py`; additions
to `session/api.py` (+ `real.py`, `fake.py`) and `AppConfig`; menu/nav
wiring in `ui/main_window.py`; new runtime dependency `bincopy`.
**Depends on:**
[`2026-09-19-calibration-dataset-export-import-design.md`](2026-09-19-calibration-dataset-export-import-design.md)
— the value source for generation is a dataset JSON file produced by that
feature's "Export All/Selected to File…". `Session.import_dataset()` is
reused as-is for validation.
**Relates to:** DEV_PLAN.md §11 item (3).

## 1. Motivation

After tuning a set of CHARACTERISTICs live over XCP and exporting them to a
calibration dataset file (item 2), the user wants to bake those values into
the ECU's original flash image (hex or S-record file produced by the
build), producing a new, ready-to-flash file — with a visual, side-by-side
check of exactly which bytes changed before trusting it.

## 2. Goals / non-goals

**Goals:**
- New top-level view, **Hex View**, alongside Calibration View and
  Measurement View — a third `active_route` (`"hex"`), reachable the same
  way (nav rail item + `self.stack`), state persisted in `config.toml` like
  the other two.
- **Session** menu gains **Load Hex/S19…** directly below the existing
  **Load A2L…**. Loads an Intel HEX or Motorola S-record file into session
  state (replacing any previously loaded one). Order-independent: whichever
  of A2L / hex file is loaded second is what triggers the origin table to
  (re)populate.
- Hex View shows two tables side by side ("cân đối xứng qua chiều dọc của
  màn hình"): **Origin** (left, the loaded file as-is) and **Mod** (right,
  after a successful generate). One row per **calibration leaf** resolved
  from the currently loaded A2L (same leaf granularity `CalibrationView`
  and dataset export already use — struct members and array elements get
  their own row, not one row per top-level CHARACTERISTIC) — not a raw
  byte-for-byte file dump. Columns: Address, Name, Size, Bytes (hex),
  Value. Both tables share the same row set and order (sorted by address),
  so a row in one table lines up with the same row in the other.
- A leaf whose address isn't covered by the loaded hex file shows as
  "— (not in file)" in Origin, visible *before* the user attempts a
  generate — not only as a failure after the fact.
- **Generate hex from dataset** button (enabled only once both an A2L and
  a hex file are loaded): pick a dataset JSON file (as produced by
  CalibrationView's Export All/Selected) → validate against the loaded A2L
  (reusing `Session.import_dataset()` unchanged) → encode every matched
  value → patch into the loaded hex file → save. On success, the Mod table
  refreshes: patched leaves show the new bytes/value, every other leaf
  mirrors Origin, and rows that actually changed are highlighted.
- Save path: a standard Save dialog, **pre-filled** with
  `<origin file stem>_mod<origin file suffix>` in the origin file's own
  directory — accept as-is with one click/Enter, or edit the path first.
  No separate "choose output path" control.
- If any matched value's address isn't covered by the loaded hex file, the
  whole generate aborts before writing anything, and the error names every
  offending `(name, address)` — consistent with the item-2 dataset import's
  own tolerance for *A2L* mismatches (skip-and-report), but stricter here
  because the output is a file meant to be flashed onto real hardware.
- Byte order: a manual **Little/Big Endian** control in Hex View, defaulted
  from `AppConfig.last_byte_order` (new field, persisted to `config.toml`
  after every successful ECU `Connect…`, the same way `last_a2l_path`
  already is). Lets generation work fully offline on a machine that has
  connected to the target ECU at least once, ever — never blocks, since
  it's editable by hand regardless.
- `AppConfig.last_hex_path` (new field, mirrors `last_a2l_path`): the last
  successfully loaded hex/s19 file path is remembered and auto-reloaded on
  app startup, same convenience A2L already has. (Not explicitly requested
  — small, low-risk, consistent with existing UX; flagging it here so it's
  easy to veto.)

**Non-goals:**
- No full-file byte-grid / hex-editor view (every byte of a multi-MB flash
  image). Scoping to calibration leaves only was a deliberate call to avoid
  needing a virtualized table model — see brainstorming discussion.
- No application-level checksum/CRC recomputation over the calibration
  region — none exists in this driver today (checked `driver/Xcp_Handler.*`
  and `xcp_appl.c`; the only checksum-shaped code is XCP's own
  `BUILD_CHECKSUM` protocol command, not a boot-time file guard).
- This design fully replaces the original context-menu-in-CalibrationView
  approach — there is no "generate from the currently open tree" path.
  CalibrationView's Export All/Selected are unchanged and remain the way to
  produce a dataset file in the first place.
- No raw binary (`.bin`) input/output — Intel HEX and Motorola S-record
  only.
- No CLI entry point — GUI-only.
- Only one hex file loaded at a time — loading a new one discards the
  previously loaded one's in-memory state (not the file on disk, obviously).

## 3. Architecture: encoding stays in `ui/`, `a2l/hexfile.py` stays pure

Same reasoning as the original design (still holds): `encode_value()` /
`decode_value_precise()` only touch primitives (bytes, str, datatype
string), so they don't violate `test_boundaries.py`'s `ui` → `xcptool.a2l`
ban, and duplicating that logic into `a2l/` to let a backend module encode
values itself would risk it silently drifting from what live ECU writes
do — a real correctness risk when the output gets flashed onto hardware.

**Refactor:** extract `encode_value()`, `decode_value_precise()`, and
`decode_value()` out of `ui/calibration_view.py` into a new
`ui/value_codec.py` (pure move, no behavior change — `calibration_view.py`
imports them back from there). `ui/hex_view.py` imports the same module.
Both are `ui/`-internal imports, which `test_boundaries.py` never
restricted (only `ui` → `xcptool.a2l`/`xcptool.master`/`can` are banned).

`a2l/hexfile.py` never sees an `A2LDatabase`, a datatype, or a byte order —
only raw addresses and bytes, same as originally designed.

## 4. Module: `a2l/hexfile.py`

```python
@dataclass
class HexImage:
    """Opaque wrapper around a parsed hex/s19 file — callers never touch
    `bincopy` directly. Carries the source path's extension, to pick the
    save format later."""

def load(path: Path) -> HexImage:
    """Parse `path` — Intel HEX or Motorola S-record, chosen by extension
    (`.hex`/`.ihex` → Intel HEX; `.s19`/`.s28`/`.s37`/`.srec`/`.mot` →
    Motorola S-record, case-insensitive; anything else raises).

    Raises:
        ValueError: extension not recognized.
        OSError: file unreadable or not valid content for its format.
    """

def read_region(image: HexImage, address: int, size: int) -> bytes | None:
    """`size` bytes at `address` from `image`, or None if that range isn't
    fully covered by the file's existing data."""

def patch_and_save(
    source_path: Path, patches: list[tuple[int, bytes, str]], output_path: Path,
) -> None:
    """Re-parse `source_path` fresh (independent of any previously loaded
    `HexImage` — never mutates one), apply every patch in `patches`
    ((address, data, name) — name used only for error messages), and save
    to `output_path` in `source_path`'s format.

    Checks ALL patches for full coverage before writing anything.

    Raises:
        ValueError: `source_path` or `output_path` extension not
            recognized, or one or more patches fall outside `source_path`'s
            existing data — message lists every offending `(name,
            address)`. Nothing is written to `output_path` in this case.
        OSError: source unreadable or output unwritable.
    """
```

`patch_and_save()` deliberately re-reads from disk on every call instead of
patching the `HexImage` that backs the Origin table's display: patching
that image in place would make a second `generate` (e.g. with a different
or updated dataset) apply on top of the *previous* generate's result
instead of the pristine original — silently cumulative, and wrong.
Re-parsing keeps every generate independent and idempotent for the same
inputs. The redundant I/O is a non-issue at calibration-file sizes and
happens off the UI thread regardless (§6).

Coverage-check and save-format specifics are implemented against whichever
`bincopy` version gets pinned — first implementation task is a quick spike
against a real sample file to confirm the exact API, same caveat as the
original design (this spec's author has not empirically verified
`bincopy`'s API in this session). The behavioral contract above is
normative regardless of which calls implement it.

## 5. `Session` contract

```python
def load_hex_file(self, path: str | Path) -> None:
    """Parse and hold `path` in session state, replacing any previously
    loaded hex/s19 file. Pure file operation — no ECU connection needed.

    Raises:
        XcpToolError: extension not recognized, or file unreadable/invalid.
    """

def hex_regions(
    self, addresses: list[tuple[int, int, str]],
) -> dict[str, bytes | None]:
    """For each (address, size, name) in `addresses`, the raw bytes at that
    range in the currently loaded hex/s19 file, keyed by name — None for a
    name if no hex file is loaded, or its range isn't fully covered. Never
    raises per-entry; used to populate the Origin table."""

def generate_hex_from_dataset(
    self, patches: list[tuple[int, bytes, str]], output_path: str | Path,
) -> None:
    """Patch the currently loaded hex/s19 file with `patches` (already
    address/byte-resolved and encoded by the caller — see §3) and save to
    `output_path`.

    Raises:
        XcpToolError: no hex file loaded, or one or more patches fall
            outside the file's existing data (lists every offending name +
            address). Nothing written in this case.
    """
```

`RealSession`/`FakeSession` both implement all three as thin wrappers over
`a2l/hexfile.py`, identical in both (pure file/session-state operation, no
bus I/O — same reasoning as `export_dataset`/`import_dataset`).

`AppConfig` gains two fields, both following the exact pattern
`last_a2l_path` already established (loaded at startup, saved after every
successful use, plain strings in `config.toml`):

```python
last_hex_path: str = ""     # auto-reload on startup, mirrors last_a2l_path
last_byte_order: str = "little"   # saved after every successful Connect…
```

## 6. UI flow

**Loading:** "Load Hex/S19…" under the Session menu (next to "Load A2L…")
→ `QFileDialog.getOpenFileName` (same extension filter as §4) →
`session.load_hex_file()` via the worker-thread `_call(...)` pattern → on
success, save `last_hex_path` to `AppConfig` and refresh Hex View's Origin
table. The Origin table refreshes whenever *either* `load_a2l` or
`load_hex_file` newly succeeds, using whatever combination is currently
available; with only one of the two loaded, it's empty with a status
message explaining which is missing.

**Origin table population:** once both A2L and hex file are loaded, Hex
View collects `(address, size, name)` for every calibration leaf in
`self._db` (same leaf-resolution already used for CalibrationView's tree —
struct/array flattening included) and calls `session.hex_regions(...)`
once (batched, not per-leaf) via `_call(...)`. Each returned entry becomes
one row; `None` renders as "— (not in file)".

**Generate:**
1. Button enabled only when both are loaded.
2. `QFileDialog.getOpenFileName(..., filter="*.json")` — pick the dataset
   file. Cancel → abort.
3. `json.load()` → `session.import_dataset(payload)` (reused unchanged) →
   `DatasetImportResult`. Structural parse failure or empty `matched` →
   status label, abort — same all-or-nothing / skip-summary behavior item
   2 already defined, unchanged here.
4. For each `(name, text)` in `matched`: resolve `(address, datatype,
   array_size)` from `self._db` (same leaf resolution as above) and
   `encode_value(text, datatype, current_byte_order, array_size)` — build
   `patches: list[tuple[int, bytes, str]]`.
5. `QFileDialog.getSaveFileName(..., dir=<origin stem>_mod<suffix>)` —
   pre-filled default, editable. Cancel → abort (nothing written,
   `matched` values are simply discarded).
6. `session.generate_hex_from_dataset(patches, output_path)` via
   `_call(...)`.
7. Success: status label `"Patched N parameter(s) into <output
   filename>."`. Mod table populated **in memory**, without re-reading
   `output_path` from disk: for a leaf whose name is in `patches`, its
   bytes are the just-encoded value; for every other leaf, its bytes equal
   Origin's. Rows where Mod's bytes differ from Origin's bytes get a
   highlighted background.
8. Failure (typically missing-address): status label + a
   `QMessageBox.critical` listing every offending `(name, address)`. Mod
   table is left as it was (not cleared, not partially updated).

## 7. Error handling

| Case | Behavior |
|---|---|
| Load Hex/S19: extension not recognized | Abort, error in status label, no state change |
| Load Hex/S19: file unreadable / invalid content | Abort, error in status label, no state change |
| Generate clicked with A2L or hex file not loaded | Button is disabled — not reachable |
| Dataset file not valid JSON / wrong shape | Abort, error in status label (via `import_dataset`'s existing all-or-nothing gate), nothing written |
| Dataset entry unknown to A2L / datatype mismatch | Skipped individually by `import_dataset` (existing behavior), summarized; the rest still proceeds to encode/patch |
| A value's text fails to encode (`encode_value()` raises) | Abort before the save dialog opens, status label names which entry + why |
| One or more matched addresses not covered by loaded hex file | Abort, dialog lists every `(name, address)`, nothing written, Mod table unchanged |
| Output path unwritable (permission, disk full, locked file) | Caught, shown in status label, no partial file left |
| User cancels dataset-file or save-path dialog | Silently abort, no status change |

## 8. Dependencies

Add `bincopy` to `[project] dependencies` in `pyproject.toml`. Exact
version floor pinned during implementation after the API-verification
spike in §4.

## 9. Testing

- `tests/unit/test_hexfile.py` (new, no Qt): `load()` extension detection
  (recognized + unrecognized, both format families); `read_region()`
  covered / partially covered / fully uncovered; `patch_and_save()` on
  synthetic Intel HEX and S-record fixtures — patched bytes land correctly,
  untouched bytes preserved, output format matches source extension;
  mixed hit/miss patch list raises `ValueError` naming *every* miss (not
  just the first) and writes nothing (assert `output_path` doesn't exist);
  **two sequential `patch_and_save()` calls against the same `source_path`
  are independent** (regression test for the in-place-mutation bug this
  design deliberately avoids — §4).
- `tests/unit/test_value_codec.py`: rename/relocate of the existing
  `encode_value`/`decode_value_precise`/`decode_value` tests (wherever they
  live today under `calibration_view` tests) — behavior-identical, so this
  should be a mechanical move, not new test logic.
- `tests/ui/test_hex_view.py` (new): nav item present and reachable;
  Generate button enabled/disabled gating (needs both A2L + hex loaded);
  Origin table populates correctly from a mocked `hex_regions()` result,
  including the "not in file" case; byte-order control defaults from
  `AppConfig.last_byte_order` and a manual change affects subsequent
  `encode_value()` calls; successful generate updates Mod table and
  highlights exactly the changed rows; missing-address failure shows the
  critical dialog and leaves Mod table untouched; save-dialog default path
  matches `<origin stem>_mod<suffix>`.
- `tests/test_boundaries.py`: unmodified, must still pass — confirms
  `ui/hex_view.py` never imports `xcptool.a2l` or `xcptool.master`.
- Full existing `CalibrationView` test suite must still pass unchanged
  after the `value_codec.py` extraction (pure move).
