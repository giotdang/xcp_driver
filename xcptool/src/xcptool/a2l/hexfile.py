"""Pure Intel HEX / Motorola S-record file operations, backed by `bincopy`.

No Qt, no A2L knowledge — everything here works with raw addresses and
bytes only. `ui/` and `session/` are the only callers (see
tests/test_boundaries.py — `ui` may never import `xcptool.a2l` directly).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import bincopy

__all__ = ["HexImage", "load", "read_region", "patch_and_save", "read_records"]

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


def _covered(bf: "bincopy.BinFile", address: int, size: int) -> bool:
    """Whether [address, address+size) is fully contained in one real
    segment of `bf`.

    Deliberately does NOT use `as_binary()`'s return length as a coverage
    proxy: `BinFile.as_binary(minimum_address, maximum_address)` pads with
    `b'\\xff' * word_size_bytes` up to `maximum_address` whenever that
    address is reached while walking segments — including when the entire
    requested range sits *before* the lowest real segment (but still below
    the file's overall `maximum_address`). That makes a full-length,
    entirely-fabricated 0xFF read indistinguishable from a real one by
    length alone — confirmed by direct reproduction while implementing
    Task 6 (querying address 0x100 on a file whose only real data starts
    at 0x200 returned 4 bytes of 0xFF, not an empty/short read). Coverage
    must be decided from the segment list itself.
    """
    end = address + size
    return any(seg.address <= address and end <= seg.address + len(seg.data) for seg in bf.segments)


def read_region(image: HexImage, address: int, size: int) -> bytes | None:
    """`size` bytes at `address` from `image`, or None if that range isn't
    fully covered by one real segment of the file's existing data."""
    if not _covered(image._binfile, address, size):
        return None
    data = image._binfile.as_binary(minimum_address=address, maximum_address=address + size)
    return bytes(data)


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
        if not _covered(bf, address, len(data)):
            missing.append(f"{name} (0x{address:08X}, {len(data)} byte(s))")
    if missing:
        raise ValueError(
            f"Address(es) not found in {source_path.name}: " + ", ".join(missing)
        )

    for address, data, _name in patches:
        bf.add_binary(bytes(data), address=address, overwrite=True)

    text = bf.as_ihex() if out_fmt == "ihex" else bf.as_srec()
    output_path.write_text(text, encoding="ascii")


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
