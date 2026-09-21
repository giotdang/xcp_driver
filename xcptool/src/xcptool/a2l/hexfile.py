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
    read for a gap instead of raising — verified against bincopy 20.1.1
    during planning)."""
    data = image._binfile.as_binary(minimum_address=address, maximum_address=address + size)
    return bytes(data) if len(data) == size else None


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
