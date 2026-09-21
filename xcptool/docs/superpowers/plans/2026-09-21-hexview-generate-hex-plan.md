# Hex View — Generate Calibration Hex/S-record File Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new "Hex View" to xcptool that loads a calibration ECU's
hex/s19 flash image, merges a previously exported calibration dataset JSON
into it, and shows the result next to the original with differences
highlighted.

**Architecture:** A pure `a2l/hexfile.py` module wraps `bincopy` for
parsing/patching/saving Intel HEX and Motorola S-record files, addressed
only by raw `(address, bytes)` — no A2L knowledge. `Session` (real.py/
fake.py, identical in both — this feature never touches the bus) exposes
three new methods that are thin wrappers over it. A new `ui/hex_view.py`
view resolves dataset values to `(address, bytes, name)` patches itself
(reusing `encode_value()`, newly extracted to `ui/value_codec.py` so both
`CalibrationView` and `HexView` can import it) and drives everything
through the existing worker-thread `_call()` pattern, exactly like
`CalibrationView`'s Export/Import already do.

**Tech Stack:** Python 3.11+, PySide6 + PySide6-Fluent-Widgets, `bincopy`
(new dependency) for Intel HEX / Motorola S-record parsing.

**Spec:** [`docs/superpowers/specs/2026-09-21-hexfile-generate-design.md`](../specs/2026-09-21-hexfile-generate-design.md)

## Global Constraints

- Intel HEX extensions: `.hex`, `.ihex`. Motorola S-record extensions:
  `.s19`, `.s28`, `.s37`, `.srec`, `.mot`. Matching is case-insensitive.
  Any other extension is a hard error (spec §4).
- No application-level checksum/CRC recomputation over the calibration
  region — out of scope (spec §2).
- Only one hex/s19 file loaded in session state at a time (spec §2).
- `a2l/hexfile.py` never imports Qt or any A2L type — only stdlib +
  `bincopy` (spec §3). `ui/hex_view.py` and `ui/calibration_view.py` never
  import `xcptool.a2l` (enforced by `tests/test_boundaries.py`).
- Every `Session` call from a view goes through `MainWindow._call(label,
  fn, *args, on_ok=..., on_err=...)` — no view ever calls `self.session.*`
  directly (`main_window.py:390-420`, existing pattern).
- `patch_and_save()` always re-parses its source file fresh from disk —
  never mutates the `HexImage` backing the Origin table's display, so
  repeated generates are independent (spec §4).
- `bincopy` is confirmed installed and its relevant API verified against
  version `20.1.1` during planning (see Task 1) — pin `bincopy>=20.1.1` in
  `pyproject.toml`.

---

## Task 1: `a2l/hexfile.py` — load and read a hex/s19 file

**Files:**
- Create: `xcptool/src/xcptool/a2l/hexfile.py`
- Modify: `xcptool/pyproject.toml` (add `bincopy>=20.1.1` to `[project]` → `dependencies`)
- Test: `xcptool/tests/unit/test_hexfile.py`

**Interfaces:**
- Produces: `HexImage` (dataclass), `load(path: Path) -> HexImage`,
  `read_region(image: HexImage, address: int, size: int) -> bytes | None`.
  Consumed by `Session.load_hex_file()`/`Session.hex_regions()` in Task 6.

Verified empirically against installed `bincopy==20.1.1` during planning:
`BinFile.as_binary(minimum_address=a, maximum_address=b)` never raises for
a gap — it silently returns **fewer bytes than requested** (empty for a
fully-uncovered range, a short slice for a partially-covered one). Coverage
must be checked by comparing the returned length to the requested size, not
by catching an exception.

- [ ] **Step 1: Add the dependency**

Edit `xcptool/pyproject.toml`, in the `[project]` → `dependencies` list
(alongside `python-can`, `PySide6`, etc.), add:

```toml
    "bincopy>=20.1.1",  # Intel HEX / Motorola S-record parsing (Hex View)
```

Install it into the venv:

```bash
xcptool/.venv/Scripts/python.exe -m pip install "bincopy>=20.1.1"
```

- [ ] **Step 2: Write the failing tests**

Create `xcptool/tests/unit/test_hexfile.py`:

```python
"""Unit tests for a2l/hexfile.py — no Qt, pure file/bytes operations."""
from __future__ import annotations

from pathlib import Path

import pytest

from xcptool.a2l import hexfile

# A minimal 8-byte Intel HEX file: 0x0100-0x0107 = 01 02 03 04 05 06 07 08
_IHEX = (
    ":08010000010203040506070882\n"
    ":00000001FF\n"
)

# The same 8 bytes at the same address, as Motorola S-record (S1, 16-bit addr).
_SREC = (
    "S1130100010203040506070800000000000000E0\n"
    "S5030001FB\n"
    "S9030000FC\n"
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="ascii")
    return p


def test_load_rejects_unrecognized_extension(tmp_path: Path) -> None:
    p = _write(tmp_path, "image.bin", _IHEX)
    with pytest.raises(ValueError, match="[Ee]xtension"):
        hexfile.load(p)


def test_load_and_read_region_ihex(tmp_path: Path) -> None:
    p = _write(tmp_path, "image.hex", _IHEX)
    image = hexfile.load(p)
    assert hexfile.read_region(image, 0x0100, 4) == b"\x01\x02\x03\x04"
    assert hexfile.read_region(image, 0x0104, 4) == b"\x05\x06\x07\x08"


def test_load_and_read_region_srec(tmp_path: Path) -> None:
    p = _write(tmp_path, "image.s19", _SREC)
    image = hexfile.load(p)
    assert hexfile.read_region(image, 0x0100, 8) == bytes(range(1, 9))


def test_read_region_uncovered_returns_none(tmp_path: Path) -> None:
    p = _write(tmp_path, "image.hex", _IHEX)
    image = hexfile.load(p)
    assert hexfile.read_region(image, 0x0200, 4) is None


def test_read_region_partially_covered_returns_none(tmp_path: Path) -> None:
    p = _write(tmp_path, "image.hex", _IHEX)
    image = hexfile.load(p)
    # 0x0104..0x010B overlaps the file's last byte (0x0107) but extends past it.
    assert hexfile.read_region(image, 0x0104, 8) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_hexfile.py -v`
Expected: FAIL/ERROR — `xcptool.a2l.hexfile` doesn't exist yet.

- [ ] **Step 4: Implement `a2l/hexfile.py`**

```python
"""Pure Intel HEX / Motorola S-record file operations, backed by `bincopy`.

No Qt, no A2L knowledge — everything here works with raw addresses and
bytes only. `ui/` and `session/` are the only callers (see
tests/test_boundaries.py — `ui` may never import `xcptool.a2l` directly).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import bincopy

__all__ = ["HexImage", "load", "read_region", "patch_and_save"]

_IHEX_EXTS = frozenset({".hex", ".ihex"})
_SREC_EXTS = frozenset({".s19", ".s28", ".s37", ".srec", ".mot"})


def _format_for(path: Path) -> str:
    """'ihex' or 'srec', chosen by `path`'s extension (case-insensitive).

    Raises:
        ValueError: extension isn't one of the recognized hex/s-record ones.
    """
    ext = path.suffix.lower()
    if ext in _IHEX_EXTS:
        return "ihex"
    if ext in _SREC_EXTS:
        return "srec"
    recognized = sorted(_IHEX_EXTS | _SREC_EXTS)
    raise ValueError(
        f"Unrecognized hex/s-record extension {path.suffix!r} for {path} "
        f"(expected one of {recognized})"
    )


def _read_into(path: Path) -> tuple["bincopy.BinFile", str]:
    fmt = _format_for(path)
    bf = bincopy.BinFile()
    if fmt == "ihex":
        bf.add_ihex_file(str(path))
    else:
        bf.add_srec_file(str(path))
    return bf, fmt


@dataclass
class HexImage:
    """Opaque wrapper around a parsed hex/s19 file — callers never touch
    `bincopy` directly."""
    _binfile: "bincopy.BinFile"
    _format: str  # "ihex" | "srec" — the format `_binfile` was parsed as


def load(path: Path) -> HexImage:
    """Parse `path` — Intel HEX or Motorola S-record, chosen by extension.

    Raises:
        ValueError: extension not recognized.
        OSError: file unreadable.
        bincopy.Error: content isn't valid for the chosen format.
    """
    bf, fmt = _read_into(path)
    return HexImage(_binfile=bf, _format=fmt)


def read_region(image: HexImage, address: int, size: int) -> bytes | None:
    """`size` bytes at `address` from `image`, or None if that range isn't
    fully covered by the file's existing data (`bincopy` returns a short
    read for a gap instead of raising — see Task 1's verification note)."""
    data = image._binfile.as_binary(minimum_address=address, maximum_address=address + size)
    return bytes(data) if len(data) == size else None
```

`patch_and_save()` is deliberately left out of this step — Task 2 adds it
with its own tests, so this task's diff stays reviewable on its own.

- [ ] **Step 5: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_hexfile.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add xcptool/pyproject.toml xcptool/src/xcptool/a2l/hexfile.py xcptool/tests/unit/test_hexfile.py
git commit -m "feat(xcptool): add a2l/hexfile.py load()/read_region(), bincopy dependency"
```

---

## Task 2: `a2l/hexfile.py` — patch and save

**Files:**
- Modify: `xcptool/src/xcptool/a2l/hexfile.py`
- Test: `xcptool/tests/unit/test_hexfile.py`

**Interfaces:**
- Consumes: `HexImage`, `_format_for()`, `_read_into()` from Task 1.
- Produces: `patch_and_save(source_path: Path, patches: list[tuple[int,
  bytes, str]], output_path: Path) -> None`. Consumed by
  `Session.generate_hex_from_dataset()` in Task 7.

- [ ] **Step 1: Write the failing tests**

Append to `xcptool/tests/unit/test_hexfile.py`:

```python
def test_patch_and_save_writes_patched_bytes_ihex(tmp_path: Path) -> None:
    src = _write(tmp_path, "image.hex", _IHEX)
    out = tmp_path / "image_mod.hex"
    hexfile.patch_and_save(src, [(0x0102, b"\xAA\xBB", "myParam")], out)

    result = hexfile.load(out)
    assert hexfile.read_region(result, 0x0100, 8) == b"\x01\x02\xAA\xBB\x05\x06\x07\x08"


def test_patch_and_save_preserves_untouched_bytes(tmp_path: Path) -> None:
    src = _write(tmp_path, "image.hex", _IHEX)
    out = tmp_path / "image_mod.hex"
    hexfile.patch_and_save(src, [(0x0100, b"\xFF", "onlyFirstByte")], out)

    result = hexfile.load(out)
    assert hexfile.read_region(result, 0x0100, 8) == b"\xFF\x02\x03\x04\x05\x06\x07\x08"


def test_patch_and_save_srec_to_srec(tmp_path: Path) -> None:
    src = _write(tmp_path, "image.s19", _SREC)
    out = tmp_path / "image_mod.s19"
    hexfile.patch_and_save(src, [(0x0100, b"\x99", "p")], out)

    assert out.read_text(encoding="ascii").startswith("S1")  # S-record, not Intel HEX
    result = hexfile.load(out)
    assert hexfile.read_region(result, 0x0100, 1) == b"\x99"


def test_patch_and_save_missing_address_raises_and_writes_nothing(tmp_path: Path) -> None:
    src = _write(tmp_path, "image.hex", _IHEX)
    out = tmp_path / "image_mod.hex"

    with pytest.raises(ValueError, match="notInFile"):
        hexfile.patch_and_save(
            src,
            [(0x0100, b"\x01", "coveredParam"), (0x9000, b"\x02", "notInFile")],
            out,
        )
    assert not out.exists()


def test_patch_and_save_lists_every_missing_address_not_just_first(tmp_path: Path) -> None:
    src = _write(tmp_path, "image.hex", _IHEX)
    out = tmp_path / "image_mod.hex"

    with pytest.raises(ValueError) as excinfo:
        hexfile.patch_and_save(
            src,
            [(0x9000, b"\x02", "firstMissing"), (0xA000, b"\x03", "secondMissing")],
            out,
        )
    assert "firstMissing" in str(excinfo.value)
    assert "secondMissing" in str(excinfo.value)


def test_patch_and_save_unrecognized_output_extension_raises(tmp_path: Path) -> None:
    src = _write(tmp_path, "image.hex", _IHEX)
    out = tmp_path / "image_mod.bin"
    with pytest.raises(ValueError, match="[Ee]xtension"):
        hexfile.patch_and_save(src, [(0x0100, b"\x01", "p")], out)


def test_patch_and_save_sequential_calls_are_independent(tmp_path: Path) -> None:
    """Regression: patch_and_save() must never mutate state shared across
    calls — two generates from the same source must not accumulate."""
    src = _write(tmp_path, "image.hex", _IHEX)
    out1 = tmp_path / "image_mod1.hex"
    out2 = tmp_path / "image_mod2.hex"

    hexfile.patch_and_save(src, [(0x0100, b"\xAA", "p1")], out1)
    hexfile.patch_and_save(src, [(0x0100, b"\xBB", "p1")], out2)

    result1 = hexfile.load(out1)
    result2 = hexfile.load(out2)
    assert hexfile.read_region(result1, 0x0100, 1) == b"\xAA"
    assert hexfile.read_region(result2, 0x0100, 1) == b"\xBB"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_hexfile.py -v`
Expected: the 7 new tests FAIL/ERROR — `patch_and_save` doesn't exist yet.

- [ ] **Step 3: Implement `patch_and_save()`**

Append to `xcptool/src/xcptool/a2l/hexfile.py` (and add `"patch_and_save"`
to the existing `__all__` list):

```python
def patch_and_save(
    source_path: Path, patches: list[tuple[int, bytes, str]], output_path: Path,
) -> None:
    """Re-parse `source_path` fresh (independent of any previously loaded
    `HexImage` — never mutates one), apply every patch in `patches`
    ((address, data, name) — name used only for error messages), and save
    to `output_path` in the format chosen by `output_path`'s own extension.

    Checks ALL patches for full coverage before writing anything.

    Raises:
        ValueError: `source_path` or `output_path` extension not
            recognized, or one or more patches fall outside `source_path`'s
            existing data — message lists every offending `(name,
            address)`. Nothing is written to `output_path` in this case.
        OSError: source unreadable or output unwritable.
    """
    out_fmt = _format_for(output_path)  # validate before touching the source at all
    bf, _src_fmt = _read_into(source_path)

    missing: list[str] = []
    for address, data, name in patches:
        covered = bf.as_binary(minimum_address=address, maximum_address=address + len(data))
        if len(covered) != len(data):
            missing.append(f"{name} (0x{address:08X}, {len(data)} byte(s))")
    if missing:
        raise ValueError(
            f"Address(es) not found in {source_path.name}: " + ", ".join(missing)
        )

    for address, data, _name in patches:
        bf.add_binary(bytes(data), address=address, overwrite=True)

    text = bf.as_ihex() if out_fmt == "ihex" else bf.as_srec()
    output_path.write_text(text, encoding="ascii")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_hexfile.py -v`
Expected: 12 passed (5 from Task 1 + 7 new).

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/a2l/hexfile.py xcptool/tests/unit/test_hexfile.py
git commit -m "feat(xcptool): add a2l/hexfile.py patch_and_save()"
```

---

## Task 3: Extract `ui/value_codec.py` from `calibration_view.py`

**Files:**
- Create: `xcptool/src/xcptool/ui/value_codec.py`
- Modify: `xcptool/src/xcptool/ui/calibration_view.py:53-201` (remove the
  moved code, import it back instead)
- Modify: `xcptool/tests/ui/test_calibration_view.py:15-29` (import from
  the new location)

**Interfaces:**
- Produces: `ui.value_codec.decode_value(data: bytes, datatype: str,
  byte_order: str, radix: str = "DEC") -> str`,
  `ui.value_codec.decode_value_precise(data: bytes, datatype: str,
  byte_order: str) -> str`, `ui.value_codec.encode_value(text: str,
  datatype: str, byte_order: str, array_size: int) -> bytes`. Consumed by
  `calibration_view.py` (unchanged call sites) and `ui/hex_view.py`
  (Task 12).

This is a pure move — no behavior change. `calibration_view.py:53-59`
(`_ENDIAN`, `_DTYPE_FMT`) and `:80-201` (`decode_value`,
`decode_value_precise`, `encode_value`) are used **only** by these three
functions (verified — `_FRIENDLY_DTYPE` right next to them is a *different*
constant used by tree-building, stays put).

- [ ] **Step 1: Create `ui/value_codec.py` with the moved code**

```python
"""Text <-> raw-bytes codec for A2L CHARACTERISTIC values — struct.pack
math only, no A2L types, no Qt. Shared by CalibrationView (live ECU
read/write) and HexView (dataset -> hex/s19 patch), so there is exactly one
place that decides how a value's text becomes the bytes written anywhere —
diverging encodings between "write to ECU" and "write to hex file" would be
a real correctness bug.
"""
from __future__ import annotations

import struct

__all__ = ["decode_value", "decode_value_precise", "encode_value"]

_ENDIAN: dict[str, str] = {"little": "<", "big": ">"}
_DTYPE_FMT: dict[str, str] = {
    "UBYTE": "B", "SBYTE": "b",
    "UWORD": "H", "SWORD": "h",
    "ULONG": "I", "SLONG": "i",
    "FLOAT32_IEEE": "f", "FLOAT64_IEEE": "d",
}


def decode_value(data: bytes, datatype: str, byte_order: str, radix: str = "DEC") -> str:
    """Giải mã bytes thành chuỗi đọc được.

    VAL_BLK / array: "v0, v1, v2, …".  VALUE scalar: "v".
    """
    fmt_char = _DTYPE_FMT.get(datatype, "B")
    endian = _ENDIAN.get(byte_order, "<")
    item_size = struct.calcsize(fmt_char)
    if item_size == 0 or len(data) < item_size:
        return "???"
    n = len(data) // item_size
    is_float = datatype.startswith("FLOAT")
    parts: list[str] = []

    for i in range(n):
        chunk = data[i * item_size : (i + 1) * item_size]
        if is_float:
            v = struct.unpack_from(endian + fmt_char, chunk)[0]
            if radix == "HEX":
                int_fmt = "I" if datatype == "FLOAT32_IEEE" else "Q"
                raw_int = struct.unpack_from(endian + int_fmt, chunk)[0]
                parts.append(f"0x{raw_int:0{item_size * 2}X}")
            elif radix == "BIN":
                int_fmt = "I" if datatype == "FLOAT32_IEEE" else "Q"
                raw_int = struct.unpack_from(endian + int_fmt, chunk)[0]
                parts.append(f"0b{raw_int:0{item_size * 8}b}")
            elif radix == "ASCII":
                chars = [chr(b) if 32 <= b <= 126 else "." for b in chunk]
                parts.append("".join(chars))
            else:
                parts.append(f"{v:.6g}")
        else:
            v = struct.unpack_from(endian + fmt_char, chunk)[0]
            if radix == "HEX":
                mask = (1 << (item_size * 8)) - 1
                parts.append(f"0x{v & mask:X}")
            elif radix == "BIN":
                mask = (1 << (item_size * 8)) - 1
                parts.append(f"0b{v & mask:b}")
            elif radix == "ASCII":
                try:
                    parts.append(chr(v) if 32 <= v <= 126 else ".")
                except ValueError:
                    parts.append(str(v))
            else:
                parts.append(str(v))
    return ", ".join(parts)


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


def encode_value(text: str, datatype: str, byte_order: str, array_size: int) -> bytes:
    """Mã hoá chuỗi nhập từ người dùng thành bytes để ghi xuống ECU.

    Hỗ trợ cả định dạng số (DEC, HEX, BIN) lẫn ký tự/chuỗi ASCII.

    Raises:
        ValueError: chuỗi không parse được hoặc số lượng phần tử không khớp.
        struct.error: giá trị nằm ngoài khoảng kiểu dữ liệu.
    """
    fmt_char = _DTYPE_FMT.get(datatype)
    if fmt_char is None:
        raise ValueError(f"Unsupported datatype: {datatype}")
    endian = _ENDIAN.get(byte_order, "<")
    item_size = struct.calcsize(fmt_char)
    raw = [p.strip() for p in text.split(",")]
    if len(raw) == 1 and array_size > 1:
        raw = raw * array_size
    if len(raw) != array_size:
        raise ValueError(f"Expected {array_size} values, received {len(raw)}")
    is_float = datatype.startswith("FLOAT")
    buf = bytearray()

    for part in raw:
        if is_float:
            part_lower = part.lower()
            if part_lower.startswith("0x") or part_lower.startswith("0b"):
                int_fmt = "I" if datatype == "FLOAT32_IEEE" else "Q"
                raw_int = int(part, 0)
                buf += struct.pack(endian + int_fmt, raw_int)
            else:
                try:
                    v = float(part)
                    buf += struct.pack(endian + fmt_char, v)
                except ValueError:
                    encoded_bytes = part.encode("latin-1")
                    if len(encoded_bytes) > item_size:
                        raise ValueError(f"ASCII string '{part}' too long for {datatype} (max {item_size} bytes)")
                    padded = encoded_bytes.ljust(item_size, b"\x00") if endian == "<" else encoded_bytes.rjust(item_size, b"\x00")
                    buf += padded
        else:
            try:
                v = int(part, 0)
                buf += struct.pack(endian + fmt_char, v)
            except ValueError:
                # Không phải số (Dec/Hex/Bin) -> parse theo ký tự / chuỗi ASCII
                encoded_bytes = part.encode("latin-1")
                if len(encoded_bytes) > item_size:
                    raise ValueError(f"ASCII string '{part}' too long for {datatype} (max {item_size} bytes)")
                padded = encoded_bytes.ljust(item_size, b"\x00") if endian == "<" else encoded_bytes.rjust(item_size, b"\x00")
                buf += padded

    return bytes(buf)
```

- [ ] **Step 2: Remove the moved code from `calibration_view.py`, import instead**

In `xcptool/src/xcptool/ui/calibration_view.py`:
- Delete lines 53-59 (`_ENDIAN`, `_DTYPE_FMT`) — keep `_FRIENDLY_DTYPE`
  (formerly 61-67) where it is.
- Delete lines 80-201 (the three function bodies, formerly between
  `_FRIENDLY_DTYPE`/`COL_*` block and `_split_into_contiguous_runs`).
- Add to the imports section (near the top, alongside other same-package
  imports):

```python
from .value_codec import decode_value, decode_value_precise, encode_value
```

- [ ] **Step 3: Update the test import**

In `xcptool/tests/ui/test_calibration_view.py:15-29`, change the import
source from `xcptool.ui.calibration_view` to `xcptool.ui.value_codec` for
`decode_value`, `decode_value_precise`, `encode_value` (whatever else that
import block pulls from `calibration_view` — `CalibrationView` itself,
etc. — stays imported from `calibration_view` as before; only these three
names move).

- [ ] **Step 4: Run the full CalibrationView test suite to verify nothing broke**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_calibration_view.py -v`
Expected: same pass count as before this task (pure move — check the count
matches a run from before Step 1 if in doubt).

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/ui/value_codec.py xcptool/src/xcptool/ui/calibration_view.py xcptool/tests/ui/test_calibration_view.py
git commit -m "refactor(xcptool): extract value_codec.py from calibration_view.py"
```

---

## Task 4: `ui/leaf_enum.py` — flat leaf enumeration from an A2LDatabase

**Files:**
- Create: `xcptool/src/xcptool/ui/leaf_enum.py`
- Test: `xcptool/tests/unit/test_leaf_enum.py`

**Interfaces:**
- Produces: `LeafInfo` (dataclass: `name: str, address: int, datatype:
  str, size: int`), `enumerate_leaves(db: A2LDatabase) -> list[LeafInfo]`.
  Consumed by `ui/hex_view.py` (Task 9, 11).

Mirrors the traversal `calibration_view.py`'s `set_database()` /
`_build_tree_item_from_node()` / `_leaf_names()`
(`calibration_view.py:439-465,1086-1184`) already do to build the tree —
same struct/array/INSTANCE handling, but returning plain data instead of
`QTreeWidgetItem`s, and with **no session-state filter** (unlike
`_gather_dataset_values()`, every characteristic with a known datatype is
included, not just ones read/edited this session — Hex View works from the
loaded A2L file itself, not from live session state). This is a
deliberate, small duplication of that traversal shape rather than a
refactor of the already-tested tree-building code — see spec's
brainstorming notes.

- [ ] **Step 1: Write the failing tests**

Create `xcptool/tests/unit/test_leaf_enum.py`:

```python
"""Unit tests for ui/leaf_enum.py — pure data, no Qt required to run."""
from __future__ import annotations

from xcptool.session.api import A2LDatabase, Characteristic, InstanceNode
from xcptool.ui.leaf_enum import LeafInfo, enumerate_leaves


def _db(characteristics: dict[str, Characteristic], instance_trees=None) -> A2LDatabase:
    db = A2LDatabase()
    db.characteristics.update(characteristics)
    if instance_trees:
        db.instance_trees.update(instance_trees)
    return db


def test_enumerate_flat_scalar() -> None:
    char = Characteristic(
        name="kp", description="", char_type="VALUE", address=0x1000,
        record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="FLOAT32_IEEE",
    )
    leaves = enumerate_leaves(_db({"kp": char}))
    assert leaves == [LeafInfo(name="kp", address=0x1000, datatype="FLOAT32_IEEE", size=4)]


def test_enumerate_skips_unresolved_datatype() -> None:
    char = Characteristic(
        name="broken", description="", char_type="VALUE", address=0x1000,
        record_layout="", lower_limit=0.0, upper_limit=10.0, datatype=None,
    )
    assert enumerate_leaves(_db({"broken": char})) == []


def test_enumerate_expands_val_blk_array_into_one_leaf_per_element() -> None:
    char = Characteristic(
        name="table", description="", char_type="VAL_BLK", address=0x2000,
        record_layout="", lower_limit=0.0, upper_limit=10.0,
        datatype="UWORD", array_size=3,
    )
    leaves = enumerate_leaves(_db({"table": char}))
    assert leaves == [
        LeafInfo(name="table[0]", address=0x2000, datatype="UWORD", size=2),
        LeafInfo(name="table[1]", address=0x2002, datatype="UWORD", size=2),
        LeafInfo(name="table[2]", address=0x2004, datatype="UWORD", size=2),
    ]


def test_enumerate_instance_tree_leaf_not_duplicated_from_flat_characteristics() -> None:
    """A CHARACTERISTIC reachable through instance_trees must be reported
    exactly once, using its INSTANCE address, not skipped or doubled."""
    char = Characteristic(
        name="outer.member", description="", char_type="VALUE", address=0x3004,
        record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE",
    )
    node = InstanceNode(
        name="outer", address=0x3000, leaf_name=None, is_measurement=False,
        struct_size=8,
        children=[
            InstanceNode(
                name="outer.member", address=0x3004, leaf_name="outer.member",
                is_measurement=False, struct_size=None, children=[],
            ),
        ],
    )
    leaves = enumerate_leaves(_db({"outer.member": char}, {"outer": node}))
    assert leaves == [LeafInfo(name="outer.member", address=0x3004, datatype="UBYTE", size=1)]


def test_enumerate_instance_tree_skips_measurement_leaves() -> None:
    node = InstanceNode(
        name="m", address=0x4000, leaf_name="m", is_measurement=True,
        struct_size=None, children=[],
    )
    assert enumerate_leaves(_db({}, {"m": node})) == []
```

`Characteristic`'s required fields (`a2l/types.py:53-70`, read in full
during planning) are exactly `name`, `description`, `char_type`,
`address`, `record_layout`, `lower_limit`, `upper_limit` — every other
field (`compu_method`, `array_size`, `datatype`) has a default, so the
fixtures above are already complete as written.

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_leaf_enum.py -v`
Expected: FAIL/ERROR — `xcptool.ui.leaf_enum` doesn't exist yet.

- [ ] **Step 3: Implement `ui/leaf_enum.py`**

```python
"""Flat (name, address, datatype, size) enumeration of every calibration
leaf in a loaded A2LDatabase — struct/array/INSTANCE-aware, but pure data
(no Qt). Deliberately mirrors, rather than reuses, the traversal
`calibration_view.py`'s tree-building already does (see this module's
plan task for why) — keep the two in sync by hand if that traversal's
struct/array/INSTANCE rules ever change.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..session.api import A2LDatabase, InstanceNode

__all__ = ["LeafInfo", "enumerate_leaves"]


@dataclass(frozen=True)
class LeafInfo:
    name: str
    address: int
    datatype: str
    size: int


def _leaf_names(node: InstanceNode) -> set[str]:
    if node.leaf_name is not None:
        return set() if node.is_measurement else {node.leaf_name}
    names: set[str] = set()
    for child in node.children:
        names |= _leaf_names(child)
    return names


def _leaves_from_node(node: InstanceNode, db: A2LDatabase, out: list[LeafInfo]) -> None:
    if node.leaf_name is not None:
        if node.is_measurement:
            return
        char = db.characteristics.get(node.leaf_name)
        if char is None or char.datatype is None:
            return
        if char.array_size > 1:
            _append_array_elements(out, char)
        else:
            out.append(LeafInfo(
                name=node.leaf_name, address=char.address,
                datatype=char.datatype, size=char.byte_size,
            ))
        return
    for child in node.children:
        _leaves_from_node(child, db, out)


def _append_array_elements(out: list[LeafInfo], char) -> None:
    elem_size = char.byte_size // char.array_size
    for i in range(char.array_size):
        out.append(LeafInfo(
            name=f"{char.name}[{i}]",
            address=char.address + i * elem_size,
            datatype=char.datatype,
            size=elem_size,
        ))


def enumerate_leaves(db: A2LDatabase) -> list[LeafInfo]:
    """Every calibration leaf in `db` — flat CHARACTERISTICs and struct/
    array INSTANCE trees alike, one entry per addressable leaf (array
    elements get their own entry, e.g. `table[0]`). Characteristics with
    no resolved `datatype` are skipped (nothing to read/write for them).
    Order: instance-tree leaves first (in `db.instance_trees` iteration
    order), then remaining flat characteristics sorted by name.
    """
    out: list[LeafInfo] = []
    handled: set[str] = set()
    for node in db.instance_trees.values():
        _leaves_from_node(node, db, out)
        handled |= _leaf_names(node)

    for name, char in sorted(db.characteristics.items()):
        if name in handled or char.datatype is None:
            continue
        if char.array_size > 1:
            _append_array_elements(out, char)
        else:
            out.append(LeafInfo(name=name, address=char.address, datatype=char.datatype, size=char.byte_size))

    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_leaf_enum.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/ui/leaf_enum.py xcptool/tests/unit/test_leaf_enum.py
git commit -m "feat(xcptool): add ui/leaf_enum.py pure leaf enumeration for Hex View"
```

---

## Task 5: `AppConfig.last_hex_path` / `last_byte_order` + `config.toml` plumbing

**Files:**
- Modify: `xcptool/src/xcptool/session/api.py` (`AppConfig` dataclass)
- Modify: `xcptool/src/xcptool/transport/config.py` (`DEFAULT_APP_CONFIG`,
  `load_app_config()`, `dumps_app_config()`)
- Test: `xcptool/tests/unit/test_config.py` (existing — currently only
  covers `BusConfig`/`load_bus_config`/`save_bus_config`, has an
  `autouse` `home` fixture that already points `XCPTOOL_HOME` at a fresh
  `tmp_path` for every test in the file; add `AppConfig` round-trip
  coverage to it, which didn't exist before this task)

**Interfaces:**
- Produces: `AppConfig.last_hex_path: str`, `AppConfig.last_byte_order:
  str`. Consumed by `ui/hex_view.py` (Task 9, startup auto-reload) and
  `ui/main_window.py` (Task 10, 14 — save after successful load/connect).

- [ ] **Step 1: Write the failing test**

In `xcptool/tests/unit/test_config.py`, add `load_app_config`,
`save_app_config` to the existing `from xcptool.transport.config import
(...)` block (which currently only imports the `Bus*` names), then add:

```python
def test_app_config_round_trips_hex_path_and_byte_order() -> None:
    cfg = load_app_config()
    cfg.last_hex_path = "C:/proj/golden.hex"
    cfg.last_byte_order = "big"
    save_app_config(cfg)

    reloaded = load_app_config()
    assert reloaded.last_hex_path == "C:/proj/golden.hex"
    assert reloaded.last_byte_order == "big"


def test_app_config_defaults_hex_path_empty_and_byte_order_little() -> None:
    cfg = load_app_config()
    assert cfg.last_hex_path == ""
    assert cfg.last_byte_order == "little"
```

(No `tmp_path`/`monkeypatch` arguments needed — the file's `home` fixture
is `autouse=True` and already isolates every test in it to its own
`XCPTOOL_HOME`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_config.py -v -k hex_path_and_byte_order or defaults_hex_path`
Expected: FAIL — `AttributeError: 'AppConfig' object has no attribute 'last_hex_path'`.

- [ ] **Step 3: Add the fields to `AppConfig`**

In `xcptool/src/xcptool/session/api.py`, in the `AppConfig` dataclass
(currently `last_a2l_path: str = ""` at the top of its field list), add
right below it:

```python
    last_hex_path: str = ""
    last_byte_order: str = "little"
```

- [ ] **Step 4: Wire them into `transport/config.py`**

In `xcptool/src/xcptool/transport/config.py`:

`DEFAULT_APP_CONFIG` — add the two fields (after `last_a2l_path=""`):

```python
    last_hex_path="",
    last_byte_order="little",
```

`load_app_config()` — in the `sess_sec` block (currently only reads
`last_a2l_path`), add:

```python
    last_hex = str(sess_sec.get("last_hex_path", "")) if isinstance(sess_sec, dict) else ""
    last_bo_raw = sess_sec.get("last_byte_order", "little") if isinstance(sess_sec, dict) else "little"
    last_bo = last_bo_raw if last_bo_raw in ("little", "big") else "little"
```

and add both to the `return AppConfig(...)` call:

```python
        last_hex_path=last_hex,
        last_byte_order=last_bo,
```

`dumps_app_config()` — in the `[session]` block (currently just
`last_a2l_path`), add:

```python
        f'last_hex_path = "{esc(cfg.last_hex_path)}"\n'
        f'last_byte_order = "{esc(cfg.last_byte_order)}"\n'
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_config.py -v`
Expected: all pass, including the 2 new ones.

- [ ] **Step 6: Run the full unit test suite for regressions**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/ -v`
Expected: all pass — no existing `AppConfig`/`config.toml` test should
have needed a change (new fields have defaults, old `.toml` files without
them still load fine).

- [ ] **Step 7: Commit**

```bash
git add xcptool/src/xcptool/session/api.py xcptool/src/xcptool/transport/config.py xcptool/tests/unit/
git commit -m "feat(xcptool): add AppConfig.last_hex_path/last_byte_order + config.toml persistence"
```

---

## Task 6: `Session.load_hex_file()` / `Session.hex_regions()`

**Files:**
- Modify: `xcptool/src/xcptool/session/api.py` (`Session` Protocol, after
  `import_dataset` at `:542-556` — same section, new "Hex View" subsection)
- Modify: `xcptool/src/xcptool/session/real.py`
- Modify: `xcptool/src/xcptool/session/fake.py`
- Test: `xcptool/tests/unit/test_session_hexview.py` (new — both
  `RealSession` and `FakeSession` are exercised the same way here since
  neither touches the bus, matching how `export_dataset`/`import_dataset`
  are tested; check `tests/unit/` for the file that already tests those
  two and mirror its session-construction fixture)

**Interfaces:**
- Consumes: `a2l.hexfile.load()`, `a2l.hexfile.read_region()` (Task 1).
- Produces: `Session.load_hex_file(path: str | Path) -> None`,
  `Session.hex_regions(addresses: list[tuple[int, int, str]]) -> dict[str,
  bytes | None]`. Consumed by `ui/main_window.py` (Task 10, 11).

- [ ] **Step 1: Write the failing tests**

`xcptool/tests/unit/test_session_dataset.py` already tests
`export_dataset`/`import_dataset` the same way this task needs — both
`RealSession()` and `FakeSession()` take no constructor arguments, and it
parametrizes over both classes directly:

```python
@pytest.fixture(params=[RealSession, FakeSession])
def session(request):
    return request.param()
```

Create `xcptool/tests/unit/test_session_hexview.py` using that exact
pattern:

```python
"""Session.load_hex_file()/hex_regions() — exercised against both
RealSession and FakeSession, since neither touches the bus for this
feature (mirrors tests/unit/test_session_dataset.py's export_dataset/
import_dataset tests)."""
from __future__ import annotations

from pathlib import Path

import pytest

from xcptool.session.api import XcpToolError
from xcptool.session.fake import FakeSession
from xcptool.session.real import RealSession

_IHEX = ":08010000010203040506070882\n:00000001FF\n"


def _write_hex(tmp_path: Path) -> Path:
    p = tmp_path / "image.hex"
    p.write_text(_IHEX, encoding="ascii")
    return p


@pytest.fixture(params=[RealSession, FakeSession])
def session(request):
    return request.param()


def test_hex_regions_before_load_returns_none_for_everything(session) -> None:
    result = session.hex_regions([(0x0100, 4, "p1")])
    assert result == {"p1": None}


def test_load_then_hex_regions_returns_covered_bytes(session, tmp_path) -> None:
    session.load_hex_file(_write_hex(tmp_path))
    result = session.hex_regions([(0x0100, 4, "p1"), (0x9000, 2, "notInFile")])
    assert result == {"p1": b"\x01\x02\x03\x04", "notInFile": None}


def test_load_hex_file_unrecognized_extension_raises_xcptoolerror(session, tmp_path) -> None:
    bad = tmp_path / "image.bin"
    bad.write_text(_IHEX, encoding="ascii")
    with pytest.raises(XcpToolError):
        session.load_hex_file(bad)


def test_load_hex_file_replaces_previous(session, tmp_path) -> None:
    first = _write_hex(tmp_path)
    session.load_hex_file(first)

    second_content = ":04020000AABBCCDD5A\n:00000001FF\n"
    second = tmp_path / "second.hex"
    second.write_text(second_content, encoding="ascii")
    session.load_hex_file(second)

    result = session.hex_regions([(0x0100, 4, "fromFirst"), (0x0200, 4, "fromSecond")])
    assert result == {"fromFirst": None, "fromSecond": b"\xAA\xBB\xCC\xDD"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_session_hexview.py -v`
Expected: FAIL — `load_hex_file`/`hex_regions` don't exist on either session yet.

- [ ] **Step 3: Add to the `Session` Protocol**

In `xcptool/src/xcptool/session/api.py`, after `import_dataset`'s
docstring (currently ending around `:549`, right before `# ── DAQ ──`),
add a new subsection:

```python
    # ── Hex View ─────────────────────────────────────────────────────────────

    def load_hex_file(self, path: str | Path) -> None:
        """Parse and hold `path` in session state, replacing any previously
        loaded hex/s19 file. Pure file operation — no ECU connection needed.

        Raises: XcpToolError nếu extension không nhận ra, hoặc file không
        đọc được/nội dung không hợp lệ.
        """

    def hex_regions(
        self, addresses: list[tuple[int, int, str]],
    ) -> dict[str, bytes | None]:
        """For each (address, size, name) in `addresses`, the raw bytes at
        that range in the currently loaded hex/s19 file, keyed by name —
        None for a name if no hex file is loaded, or its range isn't fully
        covered. Never raises per-entry."""
```

- [ ] **Step 4: Implement in `RealSession`**

In `xcptool/src/xcptool/session/real.py`, near `load_a2l` (`:271-273`),
add the hex-file state fields to `__init__` (alongside wherever
`self._a2l_db`/`self._a2l_path` are initialized) and the two methods:

```python
        self._hex_image: HexImage | None = None
        self._hex_path: Path | None = None
```

```python
    def load_hex_file(self, path: str | Path) -> None:
        try:
            self._hex_image = hexfile.load(Path(path))
        except (ValueError, OSError) as exc:
            raise XcpToolError(f"Không nạp được file hex/s19: {exc}") from exc
        self._hex_path = Path(path)

    def hex_regions(self, addresses: list[tuple[int, int, str]]) -> dict[str, bytes | None]:
        if self._hex_image is None:
            return {name: None for _addr, _size, name in addresses}
        return {
            name: hexfile.read_region(self._hex_image, addr, size)
            for addr, size, name in addresses
        }
```

Add the import at the top of `real.py` (alongside the existing
`from ..a2l...` imports used by `export_dataset`/`import_dataset`):

```python
from ..a2l import hexfile
from ..a2l.hexfile import HexImage
```

- [ ] **Step 5: Implement in `FakeSession`**

In `xcptool/src/xcptool/session/fake.py`, same pattern — add the same two
`__init__` fields and the same two methods (identical body to
`RealSession`'s — this feature never touches the bus, so there is no
real-vs-fake behavior to diverge, matching `export_dataset`/
`import_dataset`'s existing precedent at `fake.py:457-469`):

```python
        self._hex_image: HexImage | None = None
        self._hex_path: Path | None = None
```

```python
    def load_hex_file(self, path: str | Path) -> None:
        try:
            self._hex_image = hexfile.load(Path(path))
        except (ValueError, OSError) as exc:
            raise XcpToolError(f"Không nạp được file hex/s19: {exc}") from exc
        self._hex_path = Path(path)

    def hex_regions(self, addresses: list[tuple[int, int, str]]) -> dict[str, bytes | None]:
        if self._hex_image is None:
            return {name: None for _addr, _size, name in addresses}
        return {
            name: hexfile.read_region(self._hex_image, addr, size)
            for addr, size, name in addresses
        }
```

Add the same two imports at the top of `fake.py`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_session_hexview.py -v`
Expected: 8 passed (4 tests × 2 session params).

- [ ] **Step 7: Commit**

```bash
git add xcptool/src/xcptool/session/api.py xcptool/src/xcptool/session/real.py xcptool/src/xcptool/session/fake.py xcptool/tests/unit/test_session_hexview.py
git commit -m "feat(xcptool): add Session.load_hex_file()/hex_regions()"
```

---

## Task 7: `Session.generate_hex_from_dataset()`

**Files:**
- Modify: `xcptool/src/xcptool/session/api.py` (`Session` Protocol, right
  after `hex_regions`)
- Modify: `xcptool/src/xcptool/session/real.py`
- Modify: `xcptool/src/xcptool/session/fake.py`
- Test: `xcptool/tests/unit/test_session_hexview.py`

**Interfaces:**
- Consumes: `a2l.hexfile.patch_and_save()` (Task 2), `self._hex_path`
  (Task 6).
- Produces: `Session.generate_hex_from_dataset(patches: list[tuple[int,
  bytes, str]], output_path: str | Path) -> None`. Consumed by
  `ui/hex_view.py` (Task 13).

- [ ] **Step 1: Write the failing tests**

Append to `xcptool/tests/unit/test_session_hexview.py`:

```python
def test_generate_hex_from_dataset_writes_patched_file(session, tmp_path) -> None:
    session.load_hex_file(_write_hex(tmp_path))
    out = tmp_path / "image_mod.hex"

    session.generate_hex_from_dataset([(0x0100, b"\xAA\xBB", "p")], out)

    assert out.exists()
    result = session.hex_regions([(0x0100, 2, "p")])
    # re-reading via a fresh load, independent of session state:
    from xcptool.a2l import hexfile
    reloaded = hexfile.load(out)
    assert hexfile.read_region(reloaded, 0x0100, 2) == b"\xAA\xBB"


def test_generate_hex_from_dataset_no_hex_loaded_raises(session, tmp_path) -> None:
    out = tmp_path / "image_mod.hex"
    with pytest.raises(XcpToolError):
        session.generate_hex_from_dataset([(0x0100, b"\xAA", "p")], out)


def test_generate_hex_from_dataset_missing_address_raises_and_writes_nothing(session, tmp_path) -> None:
    session.load_hex_file(_write_hex(tmp_path))
    out = tmp_path / "image_mod.hex"

    with pytest.raises(XcpToolError, match="notInFile"):
        session.generate_hex_from_dataset([(0x9000, b"\xAA", "notInFile")], out)
    assert not out.exists()


def test_generate_hex_from_dataset_sequential_calls_independent(session, tmp_path) -> None:
    session.load_hex_file(_write_hex(tmp_path))
    out1 = tmp_path / "mod1.hex"
    out2 = tmp_path / "mod2.hex"

    session.generate_hex_from_dataset([(0x0100, b"\xAA", "p")], out1)
    session.generate_hex_from_dataset([(0x0100, b"\xBB", "p")], out2)

    from xcptool.a2l import hexfile
    assert hexfile.read_region(hexfile.load(out1), 0x0100, 1) == b"\xAA"
    assert hexfile.read_region(hexfile.load(out2), 0x0100, 1) == b"\xBB"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_session_hexview.py -v`
Expected: the 4 new tests FAIL — `generate_hex_from_dataset` doesn't exist yet.

- [ ] **Step 3: Add to the `Session` Protocol**

In `xcptool/src/xcptool/session/api.py`, right after `hex_regions`:

```python
    def generate_hex_from_dataset(
        self, patches: list[tuple[int, bytes, str]], output_path: str | Path,
    ) -> None:
        """Patch the currently loaded hex/s19 file with `patches` (already
        address/byte-resolved and encoded by the caller) and save to
        `output_path`.

        Raises: XcpToolError nếu chưa có hex file nào được nạp, hoặc một
        hay nhiều patch nằm ngoài vùng dữ liệu đã có trong file (liệt kê
        đủ mọi name+address vi phạm). Không ghi gì nếu lỗi.
        """
```

- [ ] **Step 4: Implement in `RealSession` and `FakeSession`**

Identical body in both files (same reasoning as Task 6 — no bus I/O), right
after `hex_regions`:

```python
    def generate_hex_from_dataset(
        self, patches: list[tuple[int, bytes, str]], output_path: str | Path,
    ) -> None:
        if self._hex_path is None:
            raise XcpToolError("Chưa nạp file hex/s19 — không thể generate")
        try:
            hexfile.patch_and_save(self._hex_path, patches, Path(output_path))
        except (ValueError, OSError) as exc:
            raise XcpToolError(str(exc)) from exc
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/test_session_hexview.py -v`
Expected: 16 passed (8 from Task 6 + 8 new [4 tests × 2 params]).

- [ ] **Step 6: Run the full unit test suite for regressions**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/unit/ -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add xcptool/src/xcptool/session/api.py xcptool/src/xcptool/session/real.py xcptool/src/xcptool/session/fake.py xcptool/tests/unit/test_session_hexview.py
git commit -m "feat(xcptool): add Session.generate_hex_from_dataset()"
```

---

## Task 8: `ui/hex_view.py` — widget skeleton

**Files:**
- Create: `xcptool/src/xcptool/ui/hex_view.py`
- Test: `xcptool/tests/ui/test_hex_view.py`

**Interfaces:**
- Consumes: `ui.leaf_enum.LeafInfo` (Task 4), `session.api.A2LDatabase`,
  `session.api.DatasetImportResult`.
- Produces: `HexView` (`QWidget` subclass) — constructor signature,
  `origin_table`/`mod_table` (`QTableWidget`), `byte_order_combo`
  (`QComboBox`), `generate_btn` (`PushButton`), and the public methods
  listed in Step 3 below. Consumed by `ui/main_window.py` (Task 10
  onward).

This task builds the widget shell and its public surface only — no
Session wiring yet (Tasks 10-14 wire it into `MainWindow`). "Testable" here
means: constructs without error, columns/headers are right, and each
public method's *local* effect (no Session call involved) is correct.

- [ ] **Step 1: Write the failing tests**

Create `xcptool/tests/ui/test_hex_view.py`. First check how
`tests/ui/test_calibration_view.py` constructs a `QApplication`/pytest-qt
fixture for a headless run (it already does this — reuse the exact same
`qtbot`/`qapp` fixture pattern, do not invent a new one):

```python
"""HexView widget tests — headless via pytest-qt, mirrors the fixture
pattern already used in tests/ui/test_calibration_view.py."""
from __future__ import annotations

from xcptool.session.api import A2LDatabase, Characteristic, DatasetImportResult, SkipReason
from xcptool.ui.hex_view import HexView


def _make_view(qtbot):
    import_calls = []
    generate_calls = []
    view = HexView(
        import_dataset_cb=lambda payload: import_calls.append(payload),
        generate_cb=lambda patches, out: generate_calls.append((patches, out)),
    )
    qtbot.addWidget(view)
    return view, import_calls, generate_calls


def test_constructs_with_two_tables_and_expected_columns(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    for table in (view.origin_table, view.mod_table):
        assert table.columnCount() == 5
        headers = [table.horizontalHeaderItem(i).text() for i in range(5)]
        assert headers == ["Address", "Name", "Size", "Bytes", "Value"]


def test_generate_button_disabled_until_both_a2l_and_hex_loaded(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    assert not view.generate_btn.isEnabled()

    view.set_database(A2LDatabase())
    assert not view.generate_btn.isEnabled()  # A2L loaded, hex not yet

    view.set_hex_loaded("C:/proj/golden.hex")
    assert view.generate_btn.isEnabled()  # both loaded now


def test_set_byte_order_updates_combo_selection(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    view.set_byte_order("big")
    assert view.byte_order_combo.currentText() == "Big Endian"
    view.set_byte_order("little")
    assert view.byte_order_combo.currentText() == "Little Endian"


def test_current_byte_order_reflects_manual_combo_change(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    view.byte_order_combo.setCurrentText("Big Endian")
    assert view.current_byte_order() == "big"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_hex_view.py -v`
Expected: FAIL/ERROR — `xcptool.ui.hex_view` doesn't exist yet.

- [ ] **Step 3: Implement the `HexView` skeleton**

```python
"""Hex View — load a calibration ECU's hex/s19 image, merge a previously
exported calibration dataset into it, preview the result next to the
original with differences highlighted. See
docs/superpowers/specs/2026-09-21-hexfile-generate-design.md.
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import PushButton

from ..session.api import A2LDatabase, DatasetImportResult
from .leaf_enum import LeafInfo, enumerate_leaves

__all__ = ["HexView"]

_COLUMNS = ["Address", "Name", "Size", "Bytes", "Value"]
_BYTE_ORDER_LABELS = {"little": "Little Endian", "big": "Big Endian"}
_BYTE_ORDER_VALUES = {v: k for k, v in _BYTE_ORDER_LABELS.items()}
_DIFF_BRUSH = QBrush(QColor("#5a3d00"))  # dark amber — visible in both light/dark themes


def _make_table() -> QTableWidget:
    table = QTableWidget(0, len(_COLUMNS))
    table.setHorizontalHeaderLabels(_COLUMNS)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    return table


class HexView(QWidget):
    regions_requested = Signal(list)  # list[tuple[int, int, str]] -> MainWindow calls session.hex_regions

    def __init__(
        self,
        import_dataset_cb: Callable[[dict], None],
        generate_cb: Callable[[list[tuple[int, bytes, str]], str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._import_dataset_cb = import_dataset_cb
        self._generate_cb = generate_cb

        self._db: A2LDatabase | None = None
        self._leaves: list[LeafInfo] = []
        self._hex_loaded = False
        self._origin_bytes: dict[str, bytes | None] = {}

        top = QHBoxLayout()
        top.addWidget(QLabel("Byte order:"))
        self.byte_order_combo = QComboBox()
        self.byte_order_combo.addItems(list(_BYTE_ORDER_LABELS.values()))
        top.addWidget(self.byte_order_combo)
        top.addStretch(1)
        self.generate_btn = PushButton("Generate hex from dataset")
        self.generate_btn.setEnabled(False)
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        top.addWidget(self.generate_btn)
        self.status_label = QLabel("Load an A2L and a hex/s19 file to begin.")

        tables = QHBoxLayout()
        self.origin_table = _make_table()
        self.mod_table = _make_table()
        tables.addWidget(self.origin_table)
        tables.addWidget(self.mod_table)

        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addLayout(tables)
        root.addWidget(self.status_label)

    # ── public state transitions ────────────────────────────────────────────

    def set_database(self, db: A2LDatabase) -> None:
        self._db = db
        self._leaves = enumerate_leaves(db)
        self._update_generate_enabled()
        self._request_regions_if_ready()

    def set_hex_loaded(self, path: str) -> None:
        self._hex_loaded = True
        self._update_generate_enabled()
        self._request_regions_if_ready()

    def set_byte_order(self, byte_order: str) -> None:
        label = _BYTE_ORDER_LABELS.get(byte_order, _BYTE_ORDER_LABELS["little"])
        self.byte_order_combo.setCurrentText(label)

    def current_byte_order(self) -> str:
        return _BYTE_ORDER_VALUES.get(self.byte_order_combo.currentText(), "little")

    # ── internal ─────────────────────────────────────────────────────────────

    def _update_generate_enabled(self) -> None:
        self.generate_btn.setEnabled(self._db is not None and self._hex_loaded)

    def _request_regions_if_ready(self) -> None:
        if self._db is None or not self._hex_loaded or not self._leaves:
            return
        addresses = [(leaf.address, leaf.size, leaf.name) for leaf in self._leaves]
        self.regions_requested.emit(addresses)

    def _on_generate_clicked(self) -> None:
        raise NotImplementedError  # wired in Task 12
```

`on_regions_ready`, `on_dataset_validated`, `on_generate_done`,
`on_generate_error` are intentionally not implemented yet — Tasks 11-13
add them alongside the tests that actually exercise the table-population
and diff-highlight behavior they're responsible for.

- [ ] **Step 4: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_hex_view.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/ui/hex_view.py xcptool/tests/ui/test_hex_view.py
git commit -m "feat(xcptool): add HexView widget skeleton (no Session wiring yet)"
```

---

## Task 9: Wire Hex View into navigation, menu, and route persistence

**Files:**
- Modify: `xcptool/src/xcptool/ui/main_window.py`:
  - `_build_views()` (`:130-157`)
  - `_build_navigation()` (`:159-206`)
  - `_build_menus()` (`:213-236`, the Session menu)
  - `_save_current_app_config()` (`:876-894`, area — active_route)
- Test: `xcptool/tests/ui/test_hex_view_integration.py` (new — MainWindow
  wiring tests for Hex View live here for the rest of this plan; there is
  no `test_main_window.py` in this codebase, `MainWindow` behavior is
  tested per-feature, e.g. `test_connect_flow.py`)

**Interfaces:**
- Consumes: `HexView` (Task 8), the `window` fixture from
  `xcptool/tests/ui/conftest.py` (`MainWindow` built on a `FakeSession`;
  do **not** invent a new fixture — this one already exists and is used
  by every other `ui/` test file).
- Produces: `MainWindow.hex_view`, Session-menu action `Load Hex/S19…`,
  nav route `"hex"`. Consumed by Task 10 onward (this task only wires
  navigation — loading a file and populating tables come next).

- [ ] **Step 1: Write the failing test**

Create `xcptool/tests/ui/test_hex_view_integration.py`:

```python
"""MainWindow <-> HexView wiring — navigation, menu, Session calls.
HexView's own dialog/rendering/diff-highlight behavior is covered in
tests/ui/test_hex_view.py; this file only covers what MainWindow adds on
top of it. Fixtures (`window`, `session`, `qtbot`) come from
tests/ui/conftest.py.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMenu

from xcptool.ui.main_window import MainWindow


def test_hex_view_registered_as_third_nav_route(window: MainWindow) -> None:
    assert window.hex_view is not None
    assert window.stack.indexOf(window.hex_view) != -1


def test_switching_to_hex_route_persists_in_app_config(window: MainWindow) -> None:
    window.switch_to(window.hex_view)
    window.nav.setCurrentItem("hex")
    window._save_current_app_config()
    assert window._app_config.active_route == "hex"


def test_session_menu_has_load_hex_action(window: MainWindow) -> None:
    assert window.act_load_hex.text() == "&Load Hex/S19…"
    menus = window.menuBar().findChildren(QMenu)
    session_menu = next(m for m in menus if m.title() == "&Session")
    assert window.act_load_hex in session_menu.actions()
```

Verified empirically during planning (`QMenuBar.findChildren(QMenu)` +
`.title()` + `in menu.actions()`) against this project's installed
PySide6 — this is real, working introspection, not a guess.

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_hex_view_integration.py -v -k hex`
Expected: FAIL — `window.hex_view` doesn't exist yet.

- [ ] **Step 3: Register `HexView` in `_build_views()`**

In `xcptool/src/xcptool/ui/main_window.py`, in `_build_views()` (after the
`self.measurement_view` block, `:154-157`):

```python
        self.hex_view = HexView(
            import_dataset_cb=self._on_hexview_import_dataset_requested,
            generate_cb=self._on_hexview_generate_requested,
            parent=self,
        )
        self.hex_view.regions_requested.connect(self._on_hex_regions_requested)
```

(`_on_hexview_import_dataset_requested`, `_on_hexview_generate_requested`,
`_on_hex_regions_requested` are added in Tasks 11-13 — for this task,
stub them as empty methods so the file imports cleanly:)

```python
    def _on_hexview_import_dataset_requested(self, payload: dict) -> None:
        pass  # wired in Task 12

    def _on_hexview_generate_requested(self, patches: list[tuple[int, bytes, str]], output_path: str) -> None:
        pass  # wired in Task 13

    def _on_hex_regions_requested(self, addresses: list[tuple[int, int, str]]) -> None:
        pass  # wired in Task 11
```

Add the import at the top of `main_window.py`, alongside
`from .measurement_view import MeasurementView`:

```python
from .hex_view import HexView
```

- [ ] **Step 4: Add the third nav route in `_build_navigation()`**

In `_build_navigation()`, right after `self.stack.addWidget(self.measurement_view)` (`:173`):

```python
        self.stack.addWidget(self.hex_view)
```

Right after the `"measurement"` `self.nav.addItem(...)` block (`:182-188`):

```python
        self.nav.addItem(
            routeKey="hex",
            icon=FluentIcon.DOCUMENT,
            text="Hex View",
            onClick=lambda: self.switch_to(self.hex_view),
            position=NavigationItemPosition.SCROLL,
        )
```

Extend the active-route restore logic (`:199-206`) to a third branch:

```python
        active = getattr(self._app_config, "active_route", "calibration")
        if active == "measurement":
            self.switch_to(self.measurement_view)
            self.nav.setCurrentItem("measurement")
        elif active == "hex":
            self.switch_to(self.hex_view)
            self.nav.setCurrentItem("hex")
        else:
            self.switch_to(self.calibration_view)
            self.nav.setCurrentItem("calibration")
```

- [ ] **Step 5: Add "Load Hex/S19…" to the Session menu**

In `_build_menus()`, right after the `act_load_a2l` block
(`:227-231`, before its `session_menu.addSeparator()`):

```python
        self.act_load_hex = QAction("&Load Hex/S19…", self)
        self.act_load_hex.triggered.connect(self._on_load_hex_clicked)
        session_menu.addAction(self.act_load_hex)
```

Add the handler (near `_on_a2l_load_requested`, `:611-616` — this task
only opens the file dialog and stubs the session call; Task 10 fills it in):

```python
    def _on_load_hex_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Hex/S19 File", "",
            "Hex / S-record (*.hex *.ihex *.s19 *.s28 *.s37 *.srec *.mot)",
        )
        if not path:
            return
        self._on_hex_load_requested(path)

    def _on_hex_load_requested(self, path: str) -> None:
        pass  # wired in Task 10
```

Confirm `QFileDialog` is already imported at the top of `main_window.py`
(it's used elsewhere for A2L/dataset dialogs) — if not, add
`from PySide6.QtWidgets import QFileDialog` to the existing
`PySide6.QtWidgets` import block.

- [ ] **Step 6: Extend `_save_current_app_config()`'s route detection**

Find the line computing `active_route=` (`:887`, currently
`"measurement" if self.stack.currentWidget() == self.measurement_view else "calibration"`)
and extend it to three branches:

```python
        if self.stack.currentWidget() == self.measurement_view:
            active_route = "measurement"
        elif self.stack.currentWidget() == self.hex_view:
            active_route = "hex"
        else:
            active_route = "calibration"
```

then use `active_route=active_route` in the `AppConfig(...)` construction
in place of the old inline ternary.

- [ ] **Step 7: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_hex_view_integration.py -v`
Expected: all pass, including the new ones.

- [ ] **Step 8: Run the full UI test suite for regressions**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/ -v`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add xcptool/src/xcptool/ui/main_window.py xcptool/tests/ui/test_hex_view_integration.py
git commit -m "feat(xcptool): register Hex View nav route and Load Hex/S19 menu action"
```

---

## Task 10: Origin table population

**Files:**
- Modify: `xcptool/src/xcptool/ui/hex_view.py` (add `on_regions_ready`)
- Modify: `xcptool/src/xcptool/ui/main_window.py`
  (`_on_hex_load_requested`, `_on_hex_regions_requested` — replace Task
  9's stubs)
- Test: `xcptool/tests/ui/test_hex_view.py`, `test_hex_view_integration.py`

**Interfaces:**
- Consumes: `Session.load_hex_file`/`hex_regions` (Task 6),
  `MainWindow._call` (existing).
- Produces: `HexView.on_regions_ready(regions: dict[str, bytes | None]) ->
  None`. Consumed by Task 11 (Mod table reuses the same rendering helper).

- [ ] **Step 1: Write the failing tests**

In `xcptool/tests/ui/test_hex_view.py`:

```python
def test_on_regions_ready_populates_origin_table(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    char = Characteristic(
        name="kp", description="", char_type="VALUE", address=0x1000,
        record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE",
    )
    db = A2LDatabase()
    db.characteristics["kp"] = char
    view.set_database(db)

    view.on_regions_ready({"kp": b"\x2A"})

    assert view.origin_table.rowCount() == 1
    assert view.origin_table.item(0, 0).text() == "0x00001000"
    assert view.origin_table.item(0, 1).text() == "kp"
    assert view.origin_table.item(0, 3).text() == "2A"
    assert view.origin_table.item(0, 4).text() == "42"


def test_on_regions_ready_shows_not_in_file_for_missing_address(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    char = Characteristic(
        name="kp", description="", char_type="VALUE", address=0x1000,
        record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE",
    )
    db = A2LDatabase()
    db.characteristics["kp"] = char
    view.set_database(db)

    view.on_regions_ready({"kp": None})

    assert view.origin_table.item(0, 3).text() == "— (not in file)"
    assert view.origin_table.item(0, 4).text() == "— (not in file)"
```

In `xcptool/tests/ui/test_hex_view_integration.py` (add `from pathlib
import Path` and `from xcptool.session.api import A2LDatabase,
Characteristic` to its imports):

```python
def test_load_hex_success_refreshes_origin_table(window: MainWindow, tmp_path: Path, qtbot) -> None:
    p = tmp_path / "image.hex"
    p.write_text(":08010000010203040506070882\n:00000001FF\n", encoding="ascii")

    char = Characteristic(
        name="kp", description="", char_type="VALUE", address=0x0100,
        record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE",
    )
    db = A2LDatabase()
    db.characteristics["kp"] = char
    window.hex_view.set_database(db)

    window._on_hex_load_requested(str(p))
    qtbot.waitUntil(lambda: window.hex_view.origin_table.rowCount() == 1, timeout=2000)
    assert window.hex_view.origin_table.item(0, 3).text() == "01"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_hex_view.py xcptool/tests/ui/test_hex_view_integration.py -v -k regions_ready or load_hex_success`
Expected: FAIL — `on_regions_ready` doesn't exist / origin table stays empty.

- [ ] **Step 3: Implement `on_regions_ready` in `HexView`**

Add to `xcptool/src/xcptool/ui/hex_view.py` (needs `decode_value` for the
Value column — add the import at the top:
`from .value_codec import decode_value`):

```python
    def on_regions_ready(self, regions: dict[str, bytes | None]) -> None:
        self._origin_bytes = regions
        self._render_table(self.origin_table, regions)

    def _render_table(self, table: QTableWidget, values: dict[str, bytes | None]) -> None:
        table.setRowCount(len(self._leaves))
        byte_order = self.current_byte_order()
        for row, leaf in enumerate(self._leaves):
            data = values.get(leaf.name)
            table.setItem(row, 0, QTableWidgetItem(f"0x{leaf.address:08X}"))
            table.setItem(row, 1, QTableWidgetItem(leaf.name))
            table.setItem(row, 2, QTableWidgetItem(str(leaf.size)))
            if data is None:
                table.setItem(row, 3, QTableWidgetItem("— (not in file)"))
                table.setItem(row, 4, QTableWidgetItem("— (not in file)"))
            else:
                table.setItem(row, 3, QTableWidgetItem(data.hex().upper()))
                value_text = decode_value(data, leaf.datatype, byte_order)
                table.setItem(row, 4, QTableWidgetItem(value_text))
```

- [ ] **Step 4: Wire `MainWindow`'s hex-load and regions-request handlers**

Replace the Task 9 stubs in `xcptool/src/xcptool/ui/main_window.py`:

```python
    def _on_hex_load_requested(self, path: str) -> None:
        self._call(
            "Loading hex/s19…",
            self.session.load_hex_file, path,
            on_ok=lambda _: self._after_hex_load(path),
            on_err=lambda exc: self.hex_view.status_label.setText(f"Load failed: {exc}"),
        )

    def _after_hex_load(self, path: str) -> None:
        self.hex_view.set_hex_loaded(path)
        self._app_config.last_hex_path = path
        self._save_current_app_config()

    def _on_hex_regions_requested(self, addresses: list[tuple[int, int, str]]) -> None:
        self._call(
            "Reading hex/s19 regions…",
            self.session.hex_regions, addresses,
            on_ok=self.hex_view.on_regions_ready,
            on_err=lambda exc: self.hex_view.status_label.setText(f"Read failed: {exc}"),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_hex_view.py xcptool/tests/ui/test_hex_view_integration.py -v`
Expected: all pass, including the 3 new ones.

- [ ] **Step 6: Commit**

```bash
git add xcptool/src/xcptool/ui/hex_view.py xcptool/src/xcptool/ui/main_window.py xcptool/tests/ui/test_hex_view.py xcptool/tests/ui/test_hex_view_integration.py
git commit -m "feat(xcptool): populate Hex View Origin table from loaded hex/s19 + A2L"
```

---

## Task 11: Generate flow, part 1 — dataset pick, validate, encode to patches

**Files:**
- Modify: `xcptool/src/xcptool/ui/hex_view.py`
- Modify: `xcptool/src/xcptool/ui/main_window.py`
- Test: `xcptool/tests/ui/test_hex_view.py`

**Interfaces:**
- Consumes: `Session.import_dataset` (existing), `encode_value` (Task 3),
  `LeafInfo` (Task 4).
- Produces: `HexView.on_dataset_validated(result: DatasetImportResult) ->
  None` — builds `patches: list[tuple[int, bytes, str]]` and stashes them
  as `self._pending_patches`, ready for Task 12 to open the save dialog
  and call `generate_cb`.

This task stops at "patches are computed and stashed" — Task 12 adds the
save-path dialog and the actual `generate_cb` call, so each task's test
covers one clear step of the flow.

- [ ] **Step 1: Write the failing tests**

In `xcptool/tests/ui/test_hex_view.py`:

```python
def test_generate_clicked_opens_dataset_file_dialog_and_calls_import_cb(qtbot, monkeypatch) -> None:
    view, import_calls, _ = _make_view(qtbot)
    db = A2LDatabase()
    view.set_database(db)
    view.set_hex_loaded("golden.hex")

    monkeypatch.setattr(
        "xcptool.ui.hex_view.QFileDialog.getOpenFileName",
        lambda *a, **k: ("dataset.json", ""),
    )
    monkeypatch.setattr(
        "xcptool.ui.hex_view.Path.read_text",
        lambda self, encoding="utf-8": '{"format_version": 1, "values": {"kp": "5"}}',
    )

    view.generate_btn.click()

    assert len(import_calls) == 1
    assert import_calls[0] == {"format_version": 1, "values": {"kp": "5"}}


def test_generate_clicked_cancel_dialog_does_not_call_import_cb(qtbot, monkeypatch) -> None:
    view, import_calls, _ = _make_view(qtbot)
    view.set_database(A2LDatabase())
    view.set_hex_loaded("golden.hex")
    monkeypatch.setattr(
        "xcptool.ui.hex_view.QFileDialog.getOpenFileName", lambda *a, **k: ("", "")
    )

    view.generate_btn.click()

    assert import_calls == []


def test_on_dataset_validated_builds_patches_from_matched_values(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    char = Characteristic(
        name="kp", description="", char_type="VALUE", address=0x1000,
        record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE",
    )
    db = A2LDatabase()
    db.characteristics["kp"] = char
    view.set_database(db)

    result = DatasetImportResult(matched={"kp": "42"}, skipped=[], a2l_mismatch_warning=None)
    view.on_dataset_validated(result)

    assert view._pending_patches == [(0x1000, b"\x2A", "kp")]


def test_on_dataset_validated_empty_matched_shows_status_no_patches(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    view.set_database(A2LDatabase())

    result = DatasetImportResult(
        matched={}, skipped=[SkipReason(name="x", reason="not found in A2L")],
        a2l_mismatch_warning=None,
    )
    view.on_dataset_validated(result)

    assert view._pending_patches == []
    assert "0" in view.status_label.text() or "no" in view.status_label.text().lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_hex_view.py -v -k generate_clicked or on_dataset_validated`
Expected: FAIL — `_on_generate_clicked` still raises `NotImplementedError`,
`on_dataset_validated` doesn't exist.

- [ ] **Step 3: Implement in `HexView`**

Add imports at the top of `hex_view.py`:

```python
import json
from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from ..session.api import DatasetImportResult
from .value_codec import encode_value
```

Replace the `_on_generate_clicked` stub and add `on_dataset_validated`,
plus a `self._pending_patches: list[tuple[int, bytes, str]] = []` field
initialized in `__init__` (alongside `self._origin_bytes`):

```python
    def _on_generate_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Calibration Dataset", "", "JSON (*.json)",
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            self.status_label.setText(f"Failed to read dataset file: {e}")
            return
        self._import_dataset_cb(payload)

    def on_dataset_validated(self, result: DatasetImportResult) -> None:
        assert self._db is not None  # generate_btn is disabled otherwise
        by_name = {leaf.name: leaf for leaf in self._leaves}
        byte_order = self.current_byte_order()
        patches: list[tuple[int, bytes, str]] = []
        errors: list[str] = []
        for name, text in result.matched.items():
            leaf = by_name.get(name)
            if leaf is None:
                continue  # not a leaf HexView knows about (e.g. a MEASUREMENT-only name)
            try:
                data = encode_value(text, leaf.datatype, byte_order, leaf.size // _dtype_item_size(leaf.datatype))
            except ValueError as e:
                errors.append(f"{name}: {e}")
                continue
            patches.append((leaf.address, data, name))

        self._pending_patches = patches
        if errors:
            self.status_label.setText(f"{len(errors)} value(s) failed to encode: {errors[0]}")
            self._pending_patches = []
            return
        if not patches:
            self.status_label.setText("Nothing to patch — dataset matched 0 known parameter(s).")
            return
        self.status_label.setText(f"{len(patches)} parameter(s) ready — choose where to save.")
```

`encode_value()`'s last argument is `array_size`, not byte size — `LeafInfo`
stores `size` (total bytes for that leaf), which for an already-flattened
array-element leaf (Task 4 gives each array element its own `LeafInfo`
with `array_size` effectively 1) is just the element's own byte width.
Add this small helper right above `HexView` (module-level, not a method):

```python
_DTYPE_ITEM_SIZE = {
    "UBYTE": 1, "SBYTE": 1, "UWORD": 2, "SWORD": 2,
    "ULONG": 4, "SLONG": 4, "FLOAT32_IEEE": 4, "FLOAT64_IEEE": 8,
}


def _dtype_item_size(datatype: str) -> int:
    return _DTYPE_ITEM_SIZE.get(datatype, 1)
```

Since Task 4's `enumerate_leaves()` already expands every array/VAL_BLK
into one single-element `LeafInfo` per index, `leaf.size` is always exactly
one item's width here, so `leaf.size // _dtype_item_size(leaf.datatype)`
is always `1` — pass `array_size=1` to `encode_value()` directly instead;
simplify the call to:

```python
                data = encode_value(text, leaf.datatype, byte_order, array_size=1)
```

and drop the now-unnecessary `_DTYPE_ITEM_SIZE`/`_dtype_item_size` helper
above — it was only needed for the array_size computation this
simplification removes.

- [ ] **Step 4: Wire `MainWindow._on_hexview_import_dataset_requested`**

Replace the Task 9 stub:

```python
    def _on_hexview_import_dataset_requested(self, payload: dict) -> None:
        self._call(
            "Validating calibration dataset…",
            self.session.import_dataset, payload,
            on_ok=self.hex_view.on_dataset_validated,
            on_err=lambda exc: self.hex_view.status_label.setText(f"Validate failed: {exc}"),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_hex_view.py -v`
Expected: all pass, including the 4 new ones.

- [ ] **Step 6: Commit**

```bash
git add xcptool/src/xcptool/ui/hex_view.py xcptool/src/xcptool/ui/main_window.py xcptool/tests/ui/test_hex_view.py
git commit -m "feat(xcptool): Hex View generate flow part 1 — dataset pick, validate, encode"
```

---

## Task 12: Generate flow, part 2 — save dialog, patch, Mod table + diff highlight

**Files:**
- Modify: `xcptool/src/xcptool/ui/hex_view.py`
- Modify: `xcptool/src/xcptool/ui/main_window.py`
- Test: `xcptool/tests/ui/test_hex_view.py`, `test_hex_view_integration.py`

**Interfaces:**
- Consumes: `Session.generate_hex_from_dataset` (Task 7),
  `self._pending_patches` (Task 11), `_render_table` (Task 10).
- Produces: `HexView.on_generate_done(output_path: str) -> None`,
  `HexView.on_generate_error(exc: Exception) -> None`.

`on_dataset_validated` (Task 11) currently stops after stashing
`_pending_patches` and updating the status label. This task makes it also
open the save dialog and call `generate_cb`, and adds the two completion
handlers.

- [ ] **Step 1: Write the failing tests**

In `xcptool/tests/ui/test_hex_view.py`:

```python
def test_on_dataset_validated_opens_prefilled_save_dialog_and_calls_generate_cb(qtbot, monkeypatch) -> None:
    view, _, generate_calls = _make_view(qtbot)
    char = Characteristic(
        name="kp", description="", char_type="VALUE", address=0x1000,
        record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE",
    )
    db = A2LDatabase()
    db.characteristics["kp"] = char
    view.set_database(db)
    view.set_hex_loaded("C:/proj/golden.hex")

    captured_default = {}

    def fake_save_dialog(parent, title, default_path, filt):
        captured_default["path"] = default_path
        return ("C:/proj/golden_mod.hex", "")

    monkeypatch.setattr("xcptool.ui.hex_view.QFileDialog.getSaveFileName", fake_save_dialog)

    result = DatasetImportResult(matched={"kp": "42"}, skipped=[], a2l_mismatch_warning=None)
    view.on_dataset_validated(result)

    assert "golden_mod.hex" in captured_default["path"]
    assert len(generate_calls) == 1
    patches, out_path = generate_calls[0]
    assert patches == [(0x1000, b"\x2A", "kp")]
    assert out_path == "C:/proj/golden_mod.hex"


def test_on_dataset_validated_cancel_save_dialog_does_not_call_generate_cb(qtbot, monkeypatch) -> None:
    view, _, generate_calls = _make_view(qtbot)
    char = Characteristic(
        name="kp", description="", char_type="VALUE", address=0x1000,
        record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE",
    )
    db = A2LDatabase()
    db.characteristics["kp"] = char
    view.set_database(db)
    view.set_hex_loaded("C:/proj/golden.hex")
    monkeypatch.setattr("xcptool.ui.hex_view.QFileDialog.getSaveFileName", lambda *a, **k: ("", ""))

    result = DatasetImportResult(matched={"kp": "42"}, skipped=[], a2l_mismatch_warning=None)
    view.on_dataset_validated(result)

    assert generate_calls == []


def test_on_generate_done_populates_mod_table_with_patched_and_unchanged_values(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    kp = Characteristic(name="kp", description="", char_type="VALUE", address=0x1000,
                         record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE")
    ki = Characteristic(name="ki", description="", char_type="VALUE", address=0x1001,
                         record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE")
    db = A2LDatabase()
    db.characteristics.update({"kp": kp, "ki": ki})
    view.set_database(db)
    view.on_regions_ready({"kp": b"\x01", "ki": b"\x02"})
    view._pending_patches = [(0x1000, b"\x2A", "kp")]

    view.on_generate_done("C:/proj/golden_mod.hex")

    assert view.mod_table.rowCount() == 2
    rows = {view.mod_table.item(r, 1).text(): r for r in range(view.mod_table.rowCount())}
    assert view.mod_table.item(rows["kp"], 3).text() == "2A"   # patched
    assert view.mod_table.item(rows["ki"], 3).text() == "02"   # unchanged, mirrors origin

    from xcptool.ui.hex_view import _DIFF_BRUSH
    assert view.mod_table.item(rows["kp"], 0).background().color() == _DIFF_BRUSH.color()
    assert view.mod_table.item(rows["ki"], 0).background().color() != _DIFF_BRUSH.color()
    assert "golden_mod.hex" in view.status_label.text()


def test_on_generate_error_shows_critical_dialog_leaves_mod_table_unchanged(qtbot, monkeypatch) -> None:
    view, _, _ = _make_view(qtbot)
    view.set_database(A2LDatabase())
    view.mod_table.setRowCount(0)

    shown = {}
    monkeypatch.setattr(
        "xcptool.ui.hex_view.QMessageBox.critical",
        lambda parent, title, text: shown.update(title=title, text=text),
    )

    view.on_generate_error(Exception("Address(es) not found in golden.hex: kp (0x00001000, 1 byte(s))"))

    assert shown["text"]
    assert view.mod_table.rowCount() == 0
```

In `xcptool/tests/ui/test_hex_view_integration.py`:

```python
def test_hexview_generate_requested_reaches_session_and_reports_error(window: MainWindow, qtbot) -> None:
    # Exercises the MainWindow wiring only — HexView's own dialog/patch-
    # building behavior is covered in test_hex_view.py. `window`'s
    # FakeSession has no hex file loaded here, so this exercises (and
    # pins) the error path: the call must reach HexView, not crash
    # MainWindow or silently vanish.
    window._on_hexview_generate_requested([(0x1000, b"\x2A", "kp")], "C:/proj/out.hex")
    qtbot.waitUntil(lambda: window.hex_view.status_label.text() != "", timeout=2000)
    assert "Generate failed" in window.hex_view.status_label.text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_hex_view.py xcptool/tests/ui/test_hex_view_integration.py -v -k generate`
Expected: FAIL — save dialog never opens, `on_generate_done`/
`on_generate_error` don't exist.

- [ ] **Step 3: Implement in `HexView`**

Add `from PySide6.QtWidgets import QFileDialog, QMessageBox` (extend the
existing `QFileDialog` import line). Extend `on_dataset_validated` — after
the existing `if not patches: ...return` block, add:

```python
        default_path = str(Path(self._hex_path_str).with_name(
            Path(self._hex_path_str).stem + "_mod" + Path(self._hex_path_str).suffix
        ))
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Patched Hex/S-record File", default_path,
            "Hex / S-record (*.hex *.ihex *.s19 *.s28 *.s37 *.srec *.mot)",
        )
        if not out_path:
            return
        self._generate_cb(patches, out_path)
```

This needs `self._hex_path_str: str` — `set_hex_loaded(path)` currently
only sets a boolean flag; extend it to also store the path (edit the
Task 8 implementation):

```python
    def set_hex_loaded(self, path: str) -> None:
        self._hex_loaded = True
        self._hex_path_str = path
        self._update_generate_enabled()
        self._request_regions_if_ready()
```

and initialize `self._hex_path_str = ""` in `__init__` alongside
`self._hex_loaded = False`.

Add the two completion handlers:

```python
    def on_generate_done(self, output_path: str) -> None:
        patched_bytes = {name: data for _addr, data, name in self._pending_patches}
        mod_values = dict(self._origin_bytes)
        mod_values.update(patched_bytes)
        self._render_table(self.mod_table, mod_values)

        changed = set(patched_bytes) & {
            name for name in patched_bytes
            if self._origin_bytes.get(name) != patched_bytes[name]
        }
        for row, leaf in enumerate(self._leaves):
            if leaf.name in changed:
                for col in range(len(_COLUMNS)):
                    self.mod_table.item(row, col).setBackground(_DIFF_BRUSH)

        self.status_label.setText(f"Patched {len(self._pending_patches)} parameter(s) into {Path(output_path).name}.")
        self._pending_patches = []

    def on_generate_error(self, exc: Exception) -> None:
        self.status_label.setText(f"Generate failed: {exc}")
        QMessageBox.critical(self, "Generate Failed", str(exc))
```

- [ ] **Step 4: Wire `MainWindow._on_hexview_generate_requested`**

Replace the Task 9 stub:

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

- [ ] **Step 5: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_hex_view.py xcptool/tests/ui/test_hex_view_integration.py -v`
Expected: all pass, including the 5 new ones.

- [ ] **Step 6: Commit**

```bash
git add xcptool/src/xcptool/ui/hex_view.py xcptool/src/xcptool/ui/main_window.py xcptool/tests/ui/test_hex_view.py xcptool/tests/ui/test_hex_view_integration.py
git commit -m "feat(xcptool): Hex View generate flow part 2 — save, patch, Mod table diff highlight"
```

---

## Task 13: byte_order persistence after Connect + startup auto-reload of last hex file

**Files:**
- Modify: `xcptool/src/xcptool/ui/main_window.py` (`connect_to`'s `ok()`
  closure, `:466-472`; `__init__`'s auto-load-A2L block, `:123-125`)
- Test: `xcptool/tests/ui/test_hex_view_integration.py`

**Interfaces:**
- Consumes: `AppConfig.last_hex_path`/`last_byte_order` (Task 5),
  `HexView.set_byte_order` (Task 8).

`FakeSession.connect()` hardcodes `SlaveCaps(byte_order="little", ...)`
(`session/fake.py:271-300`) — it cannot be made to report `"big"`. Both
tests below therefore pre-seed a *non-default* starting value in
`AppConfig` via `session._app_cfg = AppConfig(...)` before constructing
`MainWindow` — `FakeSession.load_app_config()` returns exactly that object
(`getattr(self, "_app_cfg", <default>)`, `session/fake.py:205-215`) — so a
passing test proves the wiring actually ran, not that a field already had
its default value.

- [ ] **Step 1: Write the failing tests**

Add to `xcptool/tests/ui/test_hex_view_integration.py` (needs
`from xcptool.session.api import AppConfig, BusConfig, ConnState` and
`from xcptool.session.fake import FakeBehavior, FakeSession` added to its
imports):

```python
def test_connect_success_persists_byte_order_and_updates_hexview(qtbot) -> None:
    session = FakeSession(FakeBehavior())
    session._app_cfg = AppConfig(
        bus=BusConfig(backend="virtual", channel="fake0"), last_byte_order="big",
    )
    window = MainWindow(session)
    qtbot.addWidget(window)

    window.connect_to(BusConfig(backend="virtual", channel="fake0"))
    qtbot.waitUntil(lambda: window.session.state is ConnState.CONNECTED, timeout=5000)
    qtbot.waitUntil(lambda: not window.busy, timeout=5000)

    assert window._app_config.last_byte_order == "little"  # FakeSession always reports "little"
    assert window.hex_view.byte_order_combo.currentText() == "Little Endian"
    window.close()


def test_startup_auto_reloads_last_hex_path_if_file_exists(tmp_path, qtbot) -> None:
    p = tmp_path / "golden.hex"
    p.write_text(":08010000010203040506070882\n:00000001FF\n", encoding="ascii")

    session = FakeSession(FakeBehavior())
    session._app_cfg = AppConfig(
        bus=BusConfig(backend="virtual", channel="fake0"), last_hex_path=str(p),
    )
    window = MainWindow(session)
    qtbot.addWidget(window)

    qtbot.waitUntil(lambda: window.hex_view._hex_loaded, timeout=2000)
    assert window.hex_view._hex_path_str == str(p)
    window.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_hex_view_integration.py -v -k byte_order or auto_reloads_last_hex`
Expected: FAIL.

- [ ] **Step 3: Persist `last_byte_order` after Connect**

In `xcptool/src/xcptool/ui/main_window.py`, in `connect_to()`'s `ok()`
closure (`:466-472`), after the two existing `set_byte_order` calls:

```python
        def ok(caps: SlaveCaps) -> None:
            self._connect_task = None
            self._end_busy()
            self.calibration_view.set_byte_order(caps.byte_order)
            self.measurement_view.set_byte_order(caps.byte_order)
            self.hex_view.set_byte_order(caps.byte_order)
            self._app_config.last_byte_order = caps.byte_order
            self._save_current_app_config()
            self.notify("Connected", self._caps_summary(caps))
            self._refresh_pages_after_connect()
```

- [ ] **Step 4: Auto-reload the last hex file on startup**

In `__init__`, right after the existing A2L auto-load block
(`:123-125`):

```python
        if self._app_config.last_hex_path and Path(self._app_config.last_hex_path).is_file():
            QTimer.singleShot(50, lambda: self._on_hex_load_requested(self._app_config.last_hex_path))
```

Also apply the persisted byte order to `HexView` at startup, right after
`_refresh_state()` in `__init__` (near where `trace_view.cap_spin` etc. get
restored from `self._app_config`):

```python
        self.hex_view.set_byte_order(self._app_config.last_byte_order)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ui/test_hex_view_integration.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add xcptool/src/xcptool/ui/main_window.py xcptool/tests/ui/test_hex_view_integration.py
git commit -m "feat(xcptool): persist byte_order after Connect, auto-reload last hex file on startup"
```

---

## Task 14: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/ -q`
Expected: all pass, zero failures, zero errors. Compare the total count
against the 565 baseline noted in `DEV_PLAN.md §11` — it should now read
"565 + every test added in Tasks 1-13 above".

- [ ] **Step 2: Run the architecture boundary test specifically**

Run: `xcptool/.venv/Scripts/python.exe -m pytest xcptool/tests/test_boundaries.py -v`
Expected: all pass — confirms `ui/hex_view.py` and the edited
`ui/calibration_view.py` never import `xcptool.a2l` or `xcptool.master`
directly.

- [ ] **Step 3: Manual smoke test via `--selftest`**

Run whatever self-test entry point `DEV_PLAN.md §11` referenced for the
dataset feature ("`--selftest --session fake` xanh 15/15 bước qua event
loop thật") — extend that walkthrough manually once, interactively, to
also: load a hex/s19 fixture, load an A2L, export a dataset from
CalibrationView, switch to Hex View, generate, and visually confirm the
Mod table highlights the changed row(s). This is the one step in this plan
that isn't automated — do it before considering the feature done.

- [ ] **Step 4: Update `DEV_PLAN.md` §11**

Change the status line to reflect item (3) shipped:

```markdown
**Trạng thái: mục (1), (2) và (3) đã triển khai xong.**
```

and add a short note under item (3) (mirroring how (2)'s note documents
its "triển khai thật khác spec ở điểm nào" — see `DEV_PLAN.md:2083-2092`)
summarizing anything Tasks 1-13 ended up doing differently from this plan,
if anything did.

- [ ] **Step 5: Commit**

```bash
git add xcptool/DEV_PLAN.md
git commit -m "docs(xcptool): mark Hex View (DEV_PLAN §11 item 3) shipped"
```

---

## Plan Self-Review Notes

- **Spec coverage:** every §2 Goal in the spec maps to a task — nav route
  (9), Load Hex/S19 menu (9), two tables/leaf rows (8, 10, 12), "not in
  file" display (10), Generate button gating (8), dataset-based generate
  flow (11, 12), pre-filled save dialog (12), abort-with-full-list (2, 7,
  12), byte_order control + persistence (8, 13), `last_hex_path`
  auto-reload (13), full replacement of the old context-menu design (no
  task resurrects it). §3 architecture (encoding stays in `ui/`) is Task
  11's `encode_value()` call, never inside `a2l/hexfile.py`. §8 dependency
  is Task 1.
- **Fixture/API accuracy verified during planning, not assumed:** every
  fixture and constructor this plan's tests use was read from the real
  source before being typed in — `tests/ui/conftest.py`'s `session`/
  `window`/`connected_window`/`behavior`/`cfg` fixtures (there is no
  `test_main_window.py`; `MainWindow` tests live per-feature, so this plan
  adds its own `tests/ui/test_hex_view_integration.py`), `tests/unit/
  test_config.py`'s `home` autouse fixture, `tests/unit/
  test_session_dataset.py`'s `@pytest.fixture(params=[RealSession,
  FakeSession])` pattern (both take no constructor args),
  `FakeSession.connect()`'s hardcoded `byte_order="little"`
  (`session/fake.py:271-300` — Task 13's tests pre-seed a *different*
  starting value via `session._app_cfg` specifically so a pass proves the
  wiring ran, not that a field already matched its default),
  `FakeSession.load_app_config()`'s `_app_cfg` override mechanism
  (`session/fake.py:205-215`), `A2LDatabase`'s and `Characteristic`'s
  actual dataclass fields (`a2l/types.py`), and `bincopy==20.1.1`'s real
  coverage-check behavior (short read, never an exception — confirmed by
  running it, not by reading its docstring) and `QMenuBar` menu-lookup API
  (confirmed by running a 5-line PySide6 snippet). Nothing in this plan's
  test code should require the executor to go discover a fixture that
  isn't already named and cited by file:line above.
- **Type consistency check:** `patches: list[tuple[int, bytes, str]]`
  (address, data, name) is the one shape used everywhere — Task 2
  (`patch_and_save`), Task 7 (`generate_hex_from_dataset`), Task 11
  (`on_dataset_validated` builds it), Task 12 (`generate_cb` receives it,
  `on_generate_done` reads `self._pending_patches` in the same shape).
  `LeafInfo(name, address, datatype, size)` (Task 4) is consumed
  identically in Tasks 8, 10, 11, 12 — no renamed fields anywhere.
