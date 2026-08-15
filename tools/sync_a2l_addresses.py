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
    - For struct-typed fields (e.g. PidTelemetry_t), also lays out that
      struct's own members via STRUCT_TYPES below, and targets one A2L
      MEASUREMENT per member, named "<field>_<member>" -- matching how
      xcp_daq_example.a2l represents speedPidTelemetry.error/.integral/
      .output as 3 separate flat records (XCP has no wire-level concept
      of a struct-shaped DTO, see meas_types.h / the DAQ conversation).
      Array fields (MEAS_ARRAY) stay a single target -- they're described
      in the A2L as one MEASUREMENT with MATRIX_DIM instead.
    - Reads `measData`'s base address from the symbol dump.
    - Rewrites the `ECU_ADDRESS 0x...` line inside each matching
      `/begin MEASUREMENT <target> ... /end MEASUREMENT` block in the
      target A2L file, in place.

Only fixed-width scalar types (SIZE_ALIGN) and struct types registered in
STRUCT_TYPES are known to this script. Add an entry to the relevant table
(and keep it in sync with meas_types.h for structs) before using a new
type -- the script refuses to guess a layout it wasn't told about.
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

# struct type name -> ordered [(member_name, member_c_type, member_count), ...]
# Must be kept in sync with app/meas_types.h by hand -- this script does not
# parse C struct definitions, only the flat MEAS_PARAMS_TABLE macro list.
# member_c_type must be in SIZE_ALIGN (one level of nesting only).
STRUCT_TYPES = {
    "PidTelemetry_t": [
        ("error", "float32", 1),
        ("integral", "float32", 1),
        ("output", "float32", 1),
    ],
}

FIELD_RE = re.compile(
    r"""^\s*MEAS_(PARAM|ARRAY)\s*\(\s*
        (?P<type>\w+)\s*,\s*
        (?P<name>\w+)\s*,\s*
        (?:(?P<size>\w+)\s*,\s*)?   # MEAS_ARRAY only: element count
        .*?\)\s*\\?\s*$""",
    re.VERBOSE,
)


def struct_layout(struct_type):
    """(members_with_offset, total_size, align) for a STRUCT_TYPES entry,
    laid out the same way layout_fields() lays out top-level fields."""
    if struct_type not in STRUCT_TYPES:
        sys.exit(
            f"error: struct type '{struct_type}' is not in STRUCT_TYPES.\n"
            f"       Add its member list to sync_a2l_addresses.py (matching "
            f"app/meas_types.h) before syncing."
        )
    offset = 0
    max_align = 1
    laid_out = []
    for member_name, member_type, member_count in STRUCT_TYPES[struct_type]:
        if member_type not in SIZE_ALIGN:
            sys.exit(
                f"error: {struct_type}.{member_name} has type '{member_type}', "
                f"not in SIZE_ALIGN (nested structs are not supported)."
            )
        elem_size, align = SIZE_ALIGN[member_type]
        offset = (offset + align - 1) // align * align
        laid_out.append((member_name, offset))
        offset += elem_size * member_count
        max_align = max(max_align, align)
    total_size = (offset + max_align - 1) // max_align * max_align  # trailing pad
    return laid_out, total_size, max_align


class Field:
    def __init__(self, name, c_type, count):
        self.name = name
        self.c_type = c_type
        self.count = count       # 1 for MEAS_PARAM, array length for MEAS_ARRAY
        self.offset = None       # filled in by layout_fields()

    @property
    def is_struct(self):
        return self.c_type in STRUCT_TYPES

    @property
    def total_size(self):
        if self.is_struct:
            _, size, _ = struct_layout(self.c_type)
            return size * self.count
        elem_size, _ = SIZE_ALIGN[self.c_type]
        return elem_size * self.count

    @property
    def align(self):
        if self.is_struct:
            _, _, align = struct_layout(self.c_type)
            return align
        return SIZE_ALIGN[self.c_type][1]

    def leaf_targets(self):
        """[(a2l_measurement_name, byte_offset_from_measData), ...] --
        one entry for a scalar/array field, one per member for a struct
        field (name joined with '_', matching the .a2l's MEASUREMENT
        names, e.g. speedPidTelemetry_error)."""
        if not self.is_struct:
            return [(self.name, self.offset)]
        members, _, _ = struct_layout(self.c_type)
        return [(f"{self.name}_{member_name}", self.offset + member_offset)
                for member_name, member_offset in members]


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
        if c_type not in SIZE_ALIGN and c_type not in STRUCT_TYPES:
            sys.exit(
                f"error: type '{c_type}' (field '{name}') is not in SIZE_ALIGN "
                f"or STRUCT_TYPES.\n       Add it to sync_a2l_addresses.py before "
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


def patch_a2l(a2l_file: Path, targets, base_addr: int) -> int:
    """targets: [(a2l_measurement_name, byte_offset_from_measData), ...],
    already flattened by Field.leaf_targets()."""
    text = a2l_file.read_text(encoding="utf-8")
    patched = 0
    for name, offset in targets:
        addr = base_addr + offset
        pattern = re.compile(
            MEASUREMENT_BLOCK_RE_TMPL.format(name=re.escape(name)),
            re.DOTALL,
        )
        new_text, n = pattern.subn(lambda m: f"{m.group(1)}0x{addr:08X}", text, count=1)
        if n == 0:
            print(f"warning: no MEASUREMENT '{name}' block found in {a2l_file}, skipped")
            continue
        text = new_text
        patched += 1
        print(f"  {name:<28} offset=+0x{offset:02X}  ECU_ADDRESS=0x{addr:08X}")
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
    targets = [t for f in fields for t in f.leaf_targets()]
    base_addr = find_symbol_address(args.symbols, args.base_symbol)
    print(f"{args.base_symbol} @ 0x{base_addr:08X} (from {args.symbols})")

    patched = patch_a2l(args.a2l, targets, base_addr)
    print(f"patched {patched}/{len(targets)} MEASUREMENT block(s) in {args.a2l}")
    if patched != len(targets):
        sys.exit(1)


if __name__ == "__main__":
    main()
