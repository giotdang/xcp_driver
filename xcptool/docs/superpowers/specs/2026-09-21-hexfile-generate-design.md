# Generate Calibration Hex/S-record File

**Status:** Approved by user, ready for implementation planning.
**Date:** 2026-09-21
**Scope:** new module `xcptool/src/xcptool/a2l/hexfile.py`; new
`Session.generate_hex_file()` in `session/api.py` (+ `session/real.py`,
`session/fake.py`); UI wiring in `xcptool/src/xcptool/ui/calibration_view.py`
and `ui/main_window.py`; new runtime dependency `bincopy`.
**Relates to:** DEV_PLAN.md §11 item (3). That note anticipated reusing the
calibration-dataset JSON format
([`2026-09-19-calibration-dataset-export-import-design.md`](2026-09-19-calibration-dataset-export-import-design.md))
as the value source — during brainstorming the user instead chose
**tree-only** as the value source (see §2). This design reuses that
feature's *pattern* (Session-boundary wrapper around a pure `a2l/` module,
context-menu action, worker-thread call) but not its module or file format;
the two features do not share code at runtime.

## 1. Motivation

After tuning a set of CHARACTERISTICs live over XCP, the user wants to bake
those tuned values into the ECU's original flash image (hex or S-record file
produced by the build), producing a new file that can be flashed directly —
without replaying every XCP write on each unit, and without hand-editing a
binary file. This is DEV_PLAN.md §11 item (3), the last of the three
features planned in the 2026-09-19 multi-select/dataset spec cycle.

## 2. Goals / non-goals

**Goals:**
- Right-click context menu on the `CalibrationView` tree offers **Generate
  Calibration Hex/S19…**, alongside the existing Export/Import actions.
- Value source is **only** the tree currently open in the running session —
  the same universe `Export All to File…` already uses
  (`self._original | self._dirty`): every CHARACTERISTIC that has been read
  or edited at least once this session, using whatever text is currently
  displayed (including unsaved/dirty edits). No ECU connection is required
  at generate time (values already live in the tree), but a session must
  have been open at some point to populate it.
- Supports both **Intel HEX** and **Motorola S-record** as input and output,
  via the `bincopy` library. Output is written in the same format as the
  input file (decided by the input file's extension — see §4).
- Every value is written to the exact byte range `[address, address +
  byte_size)` taken from the loaded A2L's `Characteristic` (same address
  space already used for live XCP read/write — no remapping).
- If **any** requested address range is not fully covered by existing data
  in the input file, the whole operation aborts before writing anything,
  and the error names every offending parameter (see §6). A calibration
  address missing from the "golden" image almost always means the wrong
  A2L/hex pair was picked — silently extending or skipping would produce a
  flashable file that looks fine but is wrong.
- Bytes outside the patched ranges are preserved unchanged (in value — see
  §4 note on record chunking).

**Non-goals (deferred, not designed here):**
- No "from dataset.json" or "from selected rows only" value source for v1 —
  only "from all tree values". Both are cheap additions later if needed
  (the underlying gather step already takes an arbitrary name list).
- No application-level checksum/CRC recomputation over the calibration
  region. Inspected `driver/Xcp_Handler.{h,c}` and
  `driver/port/tricore_illd/xcp_appl.c` during brainstorming — the only
  checksum-shaped code there is the XCP protocol's own `BUILD_CHECKSUM`
  command (a live, protocol-level query), not a boot-time guard baked into
  `.cal_rom`. If a future target does have one, it's out of scope here.
- No raw binary (`.bin`) input/output — Intel HEX and Motorola S-record
  only, matching the "hex/s19" name of this DEV_PLAN item.
- No preview/diff UI of what will change before writing — same tolerance
  as the dataset-import feature: the error list (on failure) or the
  success count (on success) is the only feedback.
- No CLI entry point — GUI-only, matching how Export/Import shipped.

## 3. Architecture decision: where does text→bytes encoding happen?

Two options were considered:

- **(A, chosen) UI pre-encodes.** `CalibrationView` resolves each eligible
  name to `(address, bytes, name)` using the *existing* per-leaf resolution
  + `encode_value()` already used by `_write_parent()` for live ECU writes
  (`calibration_view.py:943-954`), and passes that list down through
  `Session.generate_hex_file()`. `a2l/hexfile.py` never sees an
  `A2LDatabase`, a datatype, or a byte order — only raw addresses and bytes.
- **(B, rejected) Session/a2l resolves.** Pass `dict[str, str]` values down
  (mirroring `export_dataset`) and have `a2l/hexfile.py` resolve addresses
  and call `encode_value()` itself. Rejected because `encode_value()` /
  `decode_value_precise()` currently live in `ui/calibration_view.py` (they
  only touch primitives, so they don't violate `tests/test_boundaries.py`'s
  `ui` → `xcptool.a2l` ban); moving or duplicating them into `a2l/` to
  support this path would touch working, tested code for no functional
  gain, and a second encode implementation risks silently drifting from the
  one live writes use — a real correctness risk when the output is a file
  meant to be flashed onto real hardware.

Consequence of (A): `a2l/hexfile.py` is a small, pure, address/bytes-only
module, independently testable with synthetic fixtures and no A2L
knowledge at all. The existing `test_boundaries.py` ban on `ui` importing
`xcptool.a2l` is satisfied automatically — patches crossing the `ui` →
`Session` boundary are plain tuples, not A2L types.

## 4. Module: `a2l/hexfile.py`

```python
def patch_hex_file(
    patches: list[tuple[int, bytes, str]],  # (address, data, name) — name is only for error messages
    input_path: Path,
    output_path: Path,
) -> None:
    """Load `input_path` (Intel HEX or Motorola S-record, chosen by
    extension — see below), overwrite every byte range named in `patches`,
    and save the result to `output_path` in the same format as the input.

    Checks ALL patches for full coverage before writing anything — a patch
    whose `[address, address + len(data))` range is not entirely contained
    in the input file's existing data is a hard error, not a partial write.

    Raises:
        ValueError: input/output extension not recognized, or one or more
            patches fall outside the input file's data — message lists
            every offending `(name, address)` pair. Nothing is written to
            `output_path` in this case.
        OSError: input_path unreadable or output_path unwritable.
    """
```

- Uses `bincopy.BinFile` to load/patch/save — it parses both Intel HEX and
  Motorola S-record through the same API, so the module doesn't need two
  code paths for the two formats.
- **Output format is chosen by `input_path`'s extension**, not by
  introspecting which parser `bincopy` matched: `.hex` / `.ihex` → Intel
  HEX; `.s19` / `.s28` / `.s37` / `.srec` / `.mot` → Motorola S-record
  (case-insensitive). Any other extension is a `ValueError` asking the user
  to pick a recognized file. This sidesteps relying on unverified `bincopy`
  internals for "what format did I just parse" — the extension rule is
  simple, explicit, and matches how the CAN/AUTOSAR toolchains that
  produce these files name them.
- Coverage check and the exact save call are implemented against whatever
  `bincopy` version gets pinned — **first implementation task is a quick
  spike against a real sample file to confirm the exact API** (segment
  membership check, `as_ihex()`/`as_srec()` or equivalent), since this
  spec's author has not empirically verified `bincopy`'s API in this
  session. The behavioral contract above (full-range coverage check before
  any write; abort-with-full-list on any miss) is normative regardless of
  which `bincopy` calls implement it.
- Patched output is **not** required to be byte-identical in *record
  chunking/line layout* to the input outside the patched ranges — `bincopy`
  re-serializes from its own internal address→byte map, which may split
  lines differently than the original file. The decoded address→byte
  content is what must be preserved exactly; this is irrelevant to any
  flash tool, which only reads the decoded memory image.
- Callers are responsible for passing non-overlapping, leaf-level patches
  (the same invariant `_write_parent()`'s `entries` list already
  maintains) — `patch_hex_file()` does not defend against overlapping
  patches in the input list.

## 5. `Session` contract

Added to the `Session` Protocol in `session/api.py`, next to
`export_dataset`/`import_dataset`:

```python
def generate_hex_file(
    self,
    patches: list[tuple[int, bytes, str]],
    input_path: str | Path,
    output_path: str | Path,
) -> None:
    """Patch `input_path` (Intel HEX or Motorola S-record) with `patches`
    and write the result to `output_path`. Pure file operation — does not
    touch the bus and does not require an active connection.

    Raises:
        XcpToolError: one or more patches fall outside the input file's
            existing data (message lists every offending name + address),
            the input/output extension isn't recognized, or the file
            couldn't be read/written.
    """
```

`RealSession` and `FakeSession` both implement it as a thin wrapper —
identical in both, same as `export_dataset`/`import_dataset` today (this
feature never touches the bus, so there is no real-vs-fake behavior to
diverge):

```python
def generate_hex_file(self, patches, input_path, output_path) -> None:
    try:
        hexfile.patch_hex_file(patches, Path(input_path), Path(output_path))
    except (ValueError, OSError) as exc:
        raise XcpToolError(str(exc)) from exc
```

## 6. UI flow

Context menu gains a new entry, separated from the JSON dataset actions:

```
Export All to File…
Export Selected to File…
───────────────────────
Import Dataset from File…
───────────────────────
Generate Calibration Hex/S19…
```

Enabled whenever `self._char_items` is non-empty (same gate as `Export
All`). Handler sequence in `calibration_view.py`:

1. Eligible names = `set(self._original) | self._dirty`. Empty → status
   label explains why, no dialogs shown.
2. Gather `(address, bytes, name)` for every eligible name via a new
   `_gather_patch_entries(names)` helper — the same per-leaf resolution +
   `encode_value()` loop `_write_parent()` already runs
   (`calibration_view.py:943-954`), factored out so both call sites share
   one implementation. (Whether `_write_parent()` itself gets refactored
   to call the new helper, or keeps its own copy for now, is left to the
   implementation plan — the contract that matters is *one* encode
   behavior, not zero duplication.) A `ValueError` from `encode_value()`
   (unparseable text) aborts here with a status-label message, before any
   file dialog opens.
3. `QFileDialog.getOpenFileName(..., filter="Hex / S-record (*.hex *.ihex *.s19 *.s28 *.s37 *.srec *.mot)")`
   — pick the original file. Cancel → silently abort.
4. `QFileDialog.getSaveFileName(...)` — pick the output path, pre-filled
   with `<original stem>_patched<original suffix>`. Cancel → silently
   abort.
5. Call `session.generate_hex_file(patches, input_path, output_path)`
   through the existing worker-thread `_call(...)` pattern (`main_window.py`,
   same as every other `Session` call) — patching a multi-hundred-KB to
   multi-MB image must not block the Qt event loop.
6. Success: status label `"Patched N parameter(s) into <output filename>."`
7. Failure: status label shows the exception message; if it's a
   missing-address error (the common case), also pop a
   `QMessageBox.critical` listing every `(name, address)` that was missing
   — mirrors `_show_skip_summary()`'s dialog shape, but framed as an abort,
   not a tolerated skip.

## 7. Error handling

| Case | Behavior |
|---|---|
| No CHARACTERISTIC read/edited yet in this session | No dialogs shown, status label explains why |
| User cancels either file dialog | Silently abort, no status change |
| A value's current tree text fails to encode (`encode_value()` raises) | Abort before any file dialog, status label shows which name + why |
| Input or output extension not recognized | Abort, error in status label, nothing written |
| Input file unreadable, or not valid Intel HEX / S-record content | Abort, error in status label, nothing written |
| One or more patch addresses not fully covered by existing input data | Abort, dialog lists every `(name, address)`, nothing written |
| Output path unwritable (permission, disk full, locked file) | Caught, shown in status label, no partial file left |

## 8. Dependencies

Add `bincopy` to `[project] dependencies` in `pyproject.toml` (this file is
lead-owned per its header comment — the addition happens as part of this
feature's own implementation, not a separate hand-off). Exact version floor
to be pinned during implementation after the API-verification spike in §4.

## 9. Testing

- `tests/unit/test_hexfile.py` (new, no Qt): patch a small synthetic Intel
  HEX fixture — assert patched bytes land at the right offset, bytes
  outside the patch keep their original value, round-trip through
  `bincopy` to confirm per-line checksums are valid in the output. Same
  three assertions for a Motorola S-record fixture. A patch list with one
  covered + one out-of-range address raises `ValueError` naming *only* the
  out-of-range one, and writes nothing (verify `output_path` doesn't
  exist). Unrecognized extension raises before touching `bincopy` at all.
- `tests/ui/test_calibration_view.py`: context-menu entry enablement
  (same empty/non-empty gate as Export All); `_gather_patch_entries()`
  against the existing nested-struct/array fixtures (reusing the M3
  struct-typedef test fixtures) produces the same `(address, bytes)` pairs
  `_write_parent()` would send to the ECU for the same tree state; status
  label and critical-dialog content on the missing-address failure path;
  worker-thread wiring (`_call`) invoked with the right arguments on
  confirm, not invoked when either file dialog is cancelled.
- `tests/test_boundaries.py` requires no changes — verify it still passes,
  confirming `ui/calibration_view.py` never needs to import `xcptool.a2l`
  for this feature.
