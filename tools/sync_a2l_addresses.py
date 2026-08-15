#!/usr/bin/env python3
"""sync_a2l_addresses.py -- resync A2L ECU_ADDRESS fields after a rebuild.

Problem this solves
--------------------
Global/static C variables get a link-time address that can shift on every
rebuild (new globals added, linker script changes, toolchain updates, ...).
Hand-editing ECU_ADDRESS in the A2L after each build does not scale.

This project avoids per-signal address churn by putting every DAQ
measurement signal into ONE struct instance (app/meas_data.h: `measData`,
generated from app/meas_params.h -- mirrors the existing calibration
pattern in app/cal_data.h / cal_params.h). Only `measData`'s own address
needs to be re-read from the linker output after a rebuild; every field's
address is `measData`'s base address + offsetof(MeasData_t, field), which
this script computes itself by parsing meas_params.h -- it does not need
per-field debug symbols, DWARF, or objdump.

Usage
-----
    1. Build the firmware, then dump the symbol table with `nm` from your
       TriCore toolchain (name varies -- e.g. tricore-elf-nm.exe):

           tricore-elf-nm.exe -S your_firmware.elf > symbols.txt

       A plain `nm`-format text file is also accepted directly, and a raw
       GNU ld `.map` file is supported on a best-effort basis (regex match
       on a hex address followed by "measData" on the same line).

    2. Run this script:

           python tools/sync_a2l_addresses.py --symbols symbols.txt \
               --a2l examples/xcp_daq_example.a2l

       (paths default to the values above, so `python tools/sync_a2l_addresses.py`
       with symbols.txt in the repo root also works)

What it does
------------
    - Parses MEAS_PARAMS_TABLE from app/meas_params.h to reconstruct
      MeasData_t's field order, type, and (for MEAS_ARRAY) element count.
    - Computes each field's byte offset the same way the C compiler lays
      out a plain struct: natural alignment, no packing pragma, fields in
      declaration order. This matches meas_data.h/.c as written -- if you
      ever add `#pragma pack` or a packed attribute there, update
      SIZE_ALIGN / the layout logic here too.
    - Reads `measData`'s base address from the symbol dump.
    - Rewrites the `ECU_ADDRESS 0x...` line inside each matching
      `/begin MEASUREMENT <field> ... /end MEASUREMENT` block in the
      target A2L file, in place.

Only fixed-width scalar types used in meas_params.h today are known to
SIZE_ALIGN. Add an entry there (or extend the regex in
`extract_fields()`) before using a new type -- the script refuses to
guess a struct's layout for you.
"""

import argparse
import re
import sys
from pathlib import Path

# type name -> (size in bytes, alignment in bytes)
# Natural alignment == size for these fixed-width iLLD/ASAP2-friendly types.
SIZE_ALIGN = {
    "uint8": (1, 1), "sint8": (1, 1), "boolean": (1, 1),
    "uint16": (2, 2), "sint16": (2, 2),
    "uint32": (4, 4), "sint32": (4, 4), "float32": (4, 4),
    "float64": (8, 8),
}

FIELD_RE = re.compile(
    r"""^\s*MEAS_(PARAM|ARRAY)\s*\(\s*
        (?P<type>\w+)\s*,\s*
        (?P<name>\w+)\s*,\s*
        (?:(?P<size>\w+)\s*,\s*)?   # MEAS_ARRAY only: element count
        .*?\)\s*\\?\s*$""",
    re.VERBOSE,
)


class Field:
    def __init__(self, name, c_type, count):
        self.name = name
        self.c_type = c_type
        self.count = count       # 1 for MEAS_PARAM, array length for MEAS_ARRAY
        self.offset = None       # filled in by layout_fields()

    @property
    def total_size(self):
        elem_size, _ = SIZE_ALIGN[self.c_type]
        return elem_size * self.count

    @property
    def align(self):
        return SIZE_ALIGN[self.c_type][1]


def extract_fields(meas_params_h: Path):
    """Parse MEAS_PARAMS_TABLE lines from meas_params.h, in declared order."""
    fields = []
    in_table = False
    for raw_line in meas_params_h.read_text(encoding="utf-8").splitlines():
        if "MEAS_PARAMS_TABLE" in raw_line and "define" in raw_line:
            in_table = True
            continue
        if not in_table:
            continue
        if raw_line.strip().startswith("/*") or raw_line.strip().startswith("*"):
            continue
        m = FIELD_RE.match(raw_line)
        if not m:
            # blank/backslash-continuation/comment-only lines -- table ends
            # at the first non-matching, non-continuation content line.
            if raw_line.strip() and not raw_line.rstrip().endswith("\\"):
                break
            continue
        kind, c_type, name = m.group(1), m.group("type"), m.group("name")
        if c_type not in SIZE_ALIGN:
            sys.exit(
                f"error: type '{c_type}' (field '{name}') is not in SIZE_ALIGN.\n"
                f"       Add its (size, alignment) to sync_a2l_addresses.py before "
                f"syncing, or this script cannot compute a trustworthy offset."
            )
        count = int(m.group("size")) if kind == "ARRAY" else 1
        fields.append(Field(name, c_type, count))
    if not fields:
        sys.exit(f"error: no MEAS_PARAM/MEAS_ARRAY entries found in {meas_params_h}")
    return fields


def layout_fields(fields):
    """Assign .offset to each field: natural alignment, declaration order,
    exactly what the compiler does for a plain (non-packed) struct."""
    offset = 0
    for f in fields:
        offset = (offset + f.align - 1) // f.align * f.align
        f.offset = offset
        offset += f.total_size
    return fields


SYM_LINE_RES = [
    # `nm` output, e.g.: "900012a0 D measData" or "900012a0 00000010 D measData"
    re.compile(r"^([0-9a-fA-F]{4,16})\s+(?:[0-9a-fA-F]{4,16}\s+)?\S\s+(?P<name>\S+)\s*$"),
    # GNU ld .map, e.g.: "                0x0000000090000000                measData"
    re.compile(r"^\s*(0x[0-9a-fA-F]+)\s+(?P<name>\S+)\s*$"),
]


def find_symbol_address(symbols_file: Path, symbol: str) -> int:
    for line in symbols_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        for pattern in SYM_LINE_RES:
            m = pattern.match(line)
            if m and m.group("name") == symbol:
                return int(m.group(1), 16)
    sys.exit(
        f"error: symbol '{symbol}' not found in {symbols_file}\n"
        f"       Make sure it was dumped with `nm` (or is present in a GNU ld "
        f".map) and that the firmware actually defines it (app/meas_data.c)."
    )


MEASUREMENT_BLOCK_RE_TMPL = (
    r"(/begin MEASUREMENT\s+{name}\b.*?ECU_ADDRESS\s+)0x[0-9a-fA-F]+"
)


def patch_a2l(a2l_file: Path, fields, base_addr: int) -> int:
    text = a2l_file.read_text(encoding="utf-8")
    patched = 0
    for f in fields:
        addr = base_addr + f.offset
        pattern = re.compile(
            MEASUREMENT_BLOCK_RE_TMPL.format(name=re.escape(f.name)),
            re.DOTALL,
        )
        new_text, n = pattern.subn(lambda m: f"{m.group(1)}0x{addr:08X}", text, count=1)
        if n == 0:
            print(f"warning: no MEASUREMENT '{f.name}' block found in {a2l_file}, skipped")
            continue
        text = new_text
        patched += 1
        print(f"  {f.name:<20} offset=+0x{f.offset:02X}  ECU_ADDRESS=0x{addr:08X}")
    a2l_file.write_text(text, encoding="utf-8")
    return patched


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--meas-header", default="app/meas_params.h", type=Path,
                     help="path to meas_params.h (default: %(default)s)")
    ap.add_argument("--symbols", default="symbols.txt", type=Path,
                     help="nm output or GNU ld .map file (default: %(default)s)")
    ap.add_argument("--a2l", default="examples/xcp_daq_example.a2l", type=Path,
                     help="A2L file to patch in place (default: %(default)s)")
    ap.add_argument("--base-symbol", default="measData",
                     help="C symbol whose address anchors the struct (default: %(default)s)")
    args = ap.parse_args()

    for p in (args.meas_header, args.symbols, args.a2l):
        if not p.is_file():
            sys.exit(f"error: {p} not found")

    fields = layout_fields(extract_fields(args.meas_header))
    base_addr = find_symbol_address(args.symbols, args.base_symbol)
    print(f"{args.base_symbol} @ 0x{base_addr:08X} (from {args.symbols})")

    patched = patch_a2l(args.a2l, fields, base_addr)
    print(f"patched {patched}/{len(fields)} MEASUREMENT block(s) in {args.a2l}")
    if patched != len(fields):
        sys.exit(1)


if __name__ == "__main__":
    main()
