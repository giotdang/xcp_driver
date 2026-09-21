"""Unit tests for a2l/hexfile.py — no Qt, pure file/bytes operations."""
from __future__ import annotations

from pathlib import Path

import pytest

from xcptool.a2l import hexfile

# A minimal 8-byte Intel HEX file: 0x0100-0x0107 = 01 02 03 04 05 06 07 08.
# Generated with `bincopy.BinFile().add_binary(bytes(range(1,9)), address=0x100).as_ihex()`
# rather than hand-computed, to avoid a hand-arithmetic checksum error.
_IHEX = (
    ":080100000102030405060708D3\n"
    ":00000001FF\n"
)

# Same 8 bytes at the same address, as Motorola S-record — generated with
# `.as_srec()` the same way, for the same reason.
_SREC = (
    "S30D000001000102030405060708CD\n"
    "S5030001FB\n"
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

    assert out.read_text(encoding="ascii").startswith("S")  # S-record, not Intel HEX
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
