# A2L struct support via real ASAP2 TYPEDEF_STRUCTURE/INSTANCE

**Status:** Approved by user, ready for implementation planning.
**Date:** 2026-09-11
**Scope:** `xcptool/src/xcptool/a2l/` (parser + data model), `xcptool/src/xcptool/ui/calibration_view.py`, `xcptool/src/xcptool/ui/measurement_view.py`.

## 1. Motivation

`CalibrationView` currently decides whether a set of CHARACTERISTICs is "one
struct" purely by looking at their **names** (`_group_by_prefix` in
`calibration_view.py`: strip the text after the last `_` or before the first
`.`, group ≥2 CHARACTERISTICs that share the remaining prefix). This is a
guess, not a fact read from the A2L file — the parser (`a2l/parser.py`) never
parses any ASAP2 struct-typedef construct, so there is no real signal to
check the guess against.

Two bugs shipped earlier this cycle were direct consequences of that guess:

- **Size overflow on Write All** (fixed in commit before this spec): the
  grouped write buffer was sized as `sum(member.byte_size)`, which silently
  assumed the grouped members are byte-for-byte contiguous. A real compiler's
  alignment padding (or two unrelated CHARACTERISTICs that merely share a
  name prefix) broke that assumption. Mitigated by
  `_split_into_contiguous_runs()`, which writes each truly-contiguous run as
  its own WRITE command instead of guessing one combined size. This fix
  **stays in place** — it is a correctness net for real (address, size)
  pairs regardless of where the grouping decision came from, so nothing here
  removes it.
- **Struct parent color never clears on a single-child write** (fixed
  earlier this cycle): `on_write_done()` only walked up to the parent when
  the write itself was the parent (STRUCT branch of `_write_parent`); a
  lone-child "Write Selected" left the parent orange forever. Already fixed,
  unrelated to naming — kept as-is.

Those fixes make the *write path* safe regardless of how grouping is
decided. This spec addresses the remaining problem: the *grouping decision
itself* is a guess. The user's real, production A2L (used against the real
ECU) **does** declare structs properly, using ASAP2's `TYPEDEF_STRUCTURE` /
`STRUCTURE_COMPONENT` / `INSTANCE` records, on both the CHARACTERISTIC
(calibration) and MEASUREMENT (DAQ) side. The fix is to read that real data
instead of guessing from names, and — per explicit decision below — **stop
guessing from names altogether**, even as a fallback.

## 2. Goals / non-goals

**Goals:**
- Parse `TYPEDEF_STRUCTURE`, `STRUCTURE_COMPONENT`, `TYPEDEF_CHARACTERISTIC`,
  `TYPEDEF_MEASUREMENT`, `INSTANCE` per the ASAP2 spec.
- Resolve them into real, absolute per-member addresses — recursively:
  nested structs (a component whose type is itself a `TYPEDEF_STRUCTURE`)
  and array instances/components (`MATRIX_DIM` on an `INSTANCE` or on a
  `STRUCTURE_COMPONENT`) both need to work.
- Replace `_group_by_prefix`-based grouping in `CalibrationView` with real
  hierarchy built from the resolved data.
- Mirror the same tree-building change in `MeasurementView` (read-only side,
  no write/dirty-color concerns, but same "no naming guess" requirement).
- CHARACTERISTIC/MEASUREMENT blocks that are **not** reached by any
  `INSTANCE` keep working exactly as they do today: one flat, independent
  row per declared block (scalar, or array via existing `VAL_BLK`/
  `MATRIX_DIM` handling). No grouping is invented for them.

**Non-goals (explicitly out of scope for this spec):**
- No fallback to name-based grouping, for any file, ever (decided in §6).
- No change to the write path's buffer-splitting logic (`_write_parent`,
  `_split_into_contiguous_runs`) — it already operates on real (address,
  bytes) pairs and needs nothing struct-shape-aware to stay correct.
- No support for ASAP2 struct-typedef features beyond what's needed here:
  `TYPEDEF_BLOB`, `TYPEDEF_AXIS`, `SYMBOL_LINK`, `ADDRESS_TYPE`,
  `ECU_ADDRESS_EXTENSION`, `OVERWRITE`, `READ_ONLY` and similar optional
  ASAP2 sub-keywords on `INSTANCE`/`STRUCTURE_COMPONENT` are not parsed. If
  present in a real file they are silently ignored (consistent with how the
  parser already ignores unrecognized tokens within a known block), not an
  error.
- No UI affordance to manually declare "these characteristics are one
  struct" (a hand-maintained override table). If real A2L data is absent,
  the tool shows flat rows — full stop, matching §6.

## 3. ASAP2 grammar parsed

Grammar as specified by ASAM MCD-2 MC (ASAP2) ≥ v1.6. Token layout follows
the same "`[n]` = positional token, `keyword X` = looked up by name via
`_Block.get()`" convention already used in `parser.py`'s module docstring.

```
TYPEDEF_STRUCTURE:
  [0] name
  [1] description        (quoted string)
  [2] size                (unsigned, total byte size of the struct — real,
                           not derived)
  children: STRUCTURE_COMPONENT (one or more)

STRUCTURE_COMPONENT:
  [0] name                (member name)
  [1] type_name           (references another TYPEDEF_STRUCTURE /
                           TYPEDEF_CHARACTERISTIC / TYPEDEF_MEASUREMENT by name)
  [2] offset              (unsigned, byte offset within the struct — real)
  keyword MATRIX_DIM <n> [<m> ...]   (optional: this component is itself an
                                       array of `type_name`, length = product
                                       of dims)

TYPEDEF_CHARACTERISTIC:
  [0] name
  [1] description
  [2] char_type           (VALUE | VAL_BLK | CURVE | MAP — same vocabulary
                           as CHARACTERISTIC)
  [3] record_layout_name
  [4] max_diff            (ignored, matches CHARACTERISTIC handling)
  [5] compu_method_ref
  [6] lower_limit
  [7] upper_limit
  keyword NUMBER <n>      (only for VAL_BLK, matches CHARACTERISTIC handling)
  — same as CHARACTERISTIC's token layout, minus the [3] address slot (no
    address: this is a type, not a placed instance).

TYPEDEF_MEASUREMENT:
  [0] name
  [1] description
  [2] datatype
  [3] compu_method_ref
  [4] resolution          (ignored, matches MEASUREMENT handling)
  [5] accuracy            (ignored, matches MEASUREMENT handling)
  [6] lower_limit
  [7] upper_limit
  keyword MATRIX_DIM <n> [<m> ...]
  — same as MEASUREMENT's token layout, minus the ECU_ADDRESS keyword.

INSTANCE:
  [0] name
  [1] description
  [2] type_name           (references a TYPEDEF_STRUCTURE /
                           TYPEDEF_CHARACTERISTIC / TYPEDEF_MEASUREMENT)
  [3] address              (hex — same slot semantics as CHARACTERISTIC's
                            ECU_ADDRESS / MEASUREMENT's ECU_ADDRESS keyword,
                            but positional per the INSTANCE grammar)
  keyword MATRIX_DIM <n> [<m> ...]   (optional: this instance is itself an
                                       array of `type_name`, length = product
                                       of dims; each element occupies
                                       `size_of(type_name)` bytes starting at
                                       `address`)
```

Any other optional sub-keyword inside these blocks (`SYMBOL_LINK`,
`ADDRESS_TYPE`, `LAYOUT`, `READ_ONLY`, `ECU_ADDRESS_EXTENSION`, ...) is left
unread, per the non-goals above — the existing tokenizer already drops
unknown tokens harmlessly since extraction only ever looks for specific
positions/keywords.

## 4. Data model additions (`a2l/types.py`)

```python
@dataclass
class StructComponent:
    name: str
    type_name: str                       # -> StructTypeDef | CharacteristicTypeDef
                                          #    | MeasurementTypeDef, by name
    offset: int
    matrix_dim: list[int] = field(default_factory=list)

    @property
    def array_size(self) -> int:
        s = 1
        for d in self.matrix_dim:
            s *= d
        return s


@dataclass
class StructTypeDef:
    name: str
    size: int                            # real, declared — never derived
    components: list[StructComponent] = field(default_factory=list)


@dataclass
class CharacteristicTypeDef:
    """Same fields as Characteristic, minus `address` — a template used by
    STRUCTURE_COMPONENT/INSTANCE, not a placed value."""
    name: str
    description: str
    char_type: str
    record_layout: str
    lower_limit: float
    upper_limit: float
    compu_method: str = "NO_COMPU_METHOD"
    array_size: int = 1
    datatype: DataType | None = None     # resolved from record_layout, same
                                          # as Characteristic.datatype today


@dataclass
class MeasurementTypeDef:
    """Same fields as Measurement, minus `address`."""
    name: str
    description: str
    datatype: DataType
    lower_limit: float
    upper_limit: float
    compu_method: str = "NO_COMPU_METHOD"
    matrix_dim: list[int] = field(default_factory=list)

    @property
    def array_size(self) -> int: ...     # same formula as Measurement today


@dataclass
class Instance:
    name: str
    description: str
    type_name: str                       # -> StructTypeDef | CharacteristicTypeDef
                                          #    | MeasurementTypeDef, by name
    address: int
    matrix_dim: list[int] = field(default_factory=list)

    @property
    def array_size(self) -> int: ...     # same formula
```

`A2LDatabase` gains four dicts: `struct_types`, `characteristic_types`,
`measurement_types`, `instances` — same `name -> object` shape as the
existing `characteristics`/`measurements`/`record_layouts`.

`_visit()` in `parser.py` gains five more `elif block.name == "..."` arms,
each wrapped in the same try/except-log-and-skip the other block types
already use — a malformed struct-typedef block must not take down parsing
of the rest of the file.

## 5. Resolution (`a2l/database.py`)

Runs as a new step in `load()`, after today's `_resolve()` (record-layout →
datatype) and using its result (so a `CharacteristicTypeDef`'s `datatype`
is already filled in by the time struct resolution runs — record layouts
are resolved once, for both plain CHARACTERISTICs and struct-leaf templates).

```python
def _resolve_instances(db: A2LDatabase) -> None:
    for inst in db.instances.values():
        _resolve_one(db, inst.type_name, inst.address, inst.name,
                     inst.matrix_dim, seen=frozenset())

def _resolve_one(db, type_name, base_addr, name, matrix_dim, seen):
    n = _array_len(matrix_dim)
    for i in range(n):
        addr = base_addr + i * _size_of(db, type_name)
        elem_name = f"{name}[{i}]" if n > 1 else name
        _resolve_type(db, type_name, addr, elem_name, seen)

def _resolve_type(db, type_name, addr, name, seen):
    if type_name in db.struct_types:
        if type_name in seen:
            log.warning("circular TYPEDEF_STRUCTURE reference at %r via %r, skipping", name, type_name)
            return
        struct = db.struct_types[type_name]
        for comp in struct.components:
            _resolve_one(db, comp.type_name, addr + comp.offset,
                         f"{name}.{comp.name}", comp.matrix_dim,
                         seen | {type_name})
    elif type_name in db.characteristic_types:
        tmpl = db.characteristic_types[type_name]
        if name in db.characteristics:
            log.warning("INSTANCE-resolved name %r collides with an existing "
                        "CHARACTERISTIC, skipping", name)
            return
        db.characteristics[name] = Characteristic(
            name=name, description=tmpl.description, char_type=tmpl.char_type,
            address=addr, record_layout=tmpl.record_layout,
            lower_limit=tmpl.lower_limit, upper_limit=tmpl.upper_limit,
            compu_method=tmpl.compu_method, array_size=tmpl.array_size,
            datatype=tmpl.datatype)
    elif type_name in db.measurement_types:
        tmpl = db.measurement_types[type_name]
        if name in db.measurements:
            log.warning("INSTANCE-resolved name %r collides with an existing "
                        "MEASUREMENT, skipping", name)
            return
        db.measurements[name] = Measurement(
            name=name, description=tmpl.description, datatype=tmpl.datatype,
            address=addr, lower_limit=tmpl.lower_limit,
            upper_limit=tmpl.upper_limit, compu_method=tmpl.compu_method,
            matrix_dim=tmpl.matrix_dim)   # event_channel left at its default
                                          # (None) — today's plain MEASUREMENT
                                          # parsing never sets it either
    else:
        log.warning("INSTANCE/STRUCTURE_COMPONENT %r references unknown type %r, skipping", name, type_name)
```

Helpers used above:
- `_array_len(matrix_dim)` = product of `matrix_dim`'s entries, or `1` when
  `matrix_dim` is empty (not an array) — same formula as
  `Instance.array_size`/`StructComponent.array_size` (§4).
- `_size_of(db, type_name)` returns `StructTypeDef.size` for a struct type,
  or `DATATYPE_SIZES[datatype] * array_size` for a leaf type template (same
  formula `Characteristic.byte_size`/`Measurement.byte_size` already use) —
  needed to stride to the next element of an array instance/component.

Guards, all resulting in a **skip + warning**, never a crash or a silent
wrong address (consistent with the parser's existing per-block resilience):
- Circular struct reference (`seen` set, by type name) — a struct cannot
  contain itself, directly or through a chain of other structs.
- `type_name` that doesn't resolve to any known struct/characteristic/
  measurement type def.
- A resolved name that collides with a name already in
  `characteristics`/`measurements` (either a plain block or another
  instance's resolution) — never silently overwrite.

The result: every leaf ends up as a genuine, fully-formed `Characteristic`
or `Measurement` in the *existing* `db.characteristics`/`db.measurements`
dicts, addressed for real. Every existing consumer of those dicts (session
read/write, `encode_value`/`decode_value`, dirty tracking) needs **zero**
changes — they already only care about name → address/datatype/byte_size.

## 6. Legacy files (no `INSTANCE` at all): flat, no grouping — decided

**Decision (user, explicit): remove `_group_by_prefix` entirely, no
fallback.** A CHARACTERISTIC/MEASUREMENT reached by no `INSTANCE` renders as
one independent top-level row, exactly like a plain scalar does today —
never grouped under a synthetic "STRUCT" parent, regardless of its name.

This is a visible behavior change for any A2L that still uses the old flat-
name convention (e.g. this repo's own `examples/xcp_daq_example.a2l`, whose
`speedPid_kp`/`speedPid_ki`/`speedPid_kd`/... currently show grouped under a
"speedPid" struct node): after this change they show as five independent
rows. This is accepted as correct: the tool no longer displays a
relationship it cannot verify from the file.

## 7. UI integration

### 7.1 `CalibrationView.set_database()` (`ui/calibration_view.py`)

Replace the `_group_by_prefix`-driven loop with:

```python
for inst in db.instances.values():
    item = self._build_instance_node(inst.name, inst.type_name, ...)
    self.tree.addTopLevelItem(item)
    ...
for name, char in db.characteristics.items():
    if name already placed by an instance loop above: skip
    else: existing flat scalar/array item, unchanged
```

`_build_instance_node(name, type_name, address)`:
- struct type → parent item, `COL_TYPE = f"STRUCT ({len(components)})"`,
  `COL_ADDR`/`COL_SIZE` from the *real* `address`/`StructTypeDef.size`;
  recurse per component (nested struct → recurse again; component array →
  reuse `_build_array_children`-equivalent; plain leaf → `_make_item` on the
  already-resolved `Characteristic`).
- non-struct type (a bare `INSTANCE` of a `TYPEDEF_CHARACTERISTIC`, no
  struct involved) → same as today's flat scalar/array item, just address-
  sourced from the instance instead of a plain CHARACTERISTIC block.
- instance-level array (`MATRIX_DIM` on the `INSTANCE` itself) → one array
  parent, each element built by recursing into `_build_instance_node` for
  that element's resolved sub-tree.

`_make_item`/`_build_array_children` are reused unchanged — only the
decision of *what nests under what* changes.

Write path (`_write_parent`, `on_write_done`, `_split_into_contiguous_runs`)
needs **no changes** — see §1: it already keys everything off the tree's
real per-item address/size, which is now sourced from resolution instead of
a `sum()` guess, but the code reading `item.text(COL_ADDR)`/
`item.text(COL_SIZE)` doesn't know or care where those strings came from.

### 7.2 `MeasurementView.set_database()` (`ui/measurement_view.py`)

Has its own **separate, independent copy** of `_group_by_prefix` (line 129 —
not imported from `calibration_view.py`; the two views duplicated the same
heuristic independently). Both copies are deleted, not just one.

`set_database()`'s current STRUCT branch builds one parent
`QTreeWidgetItem` (`COL_DTYPE = "STRUCT (n)"`, `COL_ADDR` = min address of
the group, unchecked, no value) with one child per grouped MEASUREMENT
(name = suffix after the shared prefix, own dtype/address, no checkbox — only
leaves are selectable for DAQ). This is simpler than `CalibrationView`: pure
read-only display + DAQ-list checkbox selection, no dirty tracking, no
write path. The replacement mirrors §7.1's `_build_instance_node` almost
directly: walk `db.instances` + `db.struct_types`/`db.measurement_types`
instead of name-grouping `db.measurements`, recursing the same way for
nested/array structs; leaf nodes keep today's checkbox/dtype/address
rendering unchanged. `MEASUREMENT` blocks reached by no `INSTANCE` render
flat, same as `CalibrationView`'s equivalent case (§6).

## 8. Testing

- `a2l/parser.py`: one test per new block type (`TYPEDEF_STRUCTURE`,
  `STRUCTURE_COMPONENT`, `TYPEDEF_CHARACTERISTIC`, `TYPEDEF_MEASUREMENT`,
  `INSTANCE`) parsing a minimal hand-written snippet into the right
  dataclass fields; a malformed/unknown-block test asserting warn-and-skip
  (matching the existing `test_a2l_parser.py` style for CHARACTERISTIC/
  MEASUREMENT).
- `a2l/database.py`: resolution tests — flat struct (matches today's old
  `_group_by_prefix` test's shape, `speedPid`-like, but via real INSTANCE
  data now), nested struct (2+ levels), array instance, array component,
  array-of-struct, circular reference → warning + no crash, unknown
  `type_name` → warning + skip, name collision → warning + skip + original
  entry preserved.
- `ui/test_calibration_view.py`: replace
  `test_set_database_groups_struct_characteristics` (currently asserts
  `_group_by_prefix`'s output) with an INSTANCE-driven equivalent; add a
  CHARACTERISTIC-with-no-INSTANCE test asserting it renders flat (§6); keep
  all existing write-path tests (`_split_into_contiguous_runs`,
  `on_write_done` parent-color propagation) as regression coverage — they
  must keep passing unchanged, since the write path itself isn't touched.
- `ui/test_measurement_view.py`: equivalent coverage once 7.2's exact
  tree-building shape is nailed down.
- Full suite green before considering any phase done, per this project's
  existing verification bar.

## 9. Migration notes for implementation planning

- `_group_by_prefix` exists as **two independent copies** —
  `calibration_view.py` and `measurement_view.py` (line 129, not a shared
  import). Both are deleted, not deprecated — no caller of either should
  remain.
- `test_set_database_groups_struct_characteristics` in
  `test_calibration_view.py` currently asserts the exact behavior this spec
  removes; it must be rewritten, not left red. `test_measurement_view.py`
  is expected to have an analogous test needing the same treatment —
  confirm by grep at implementation time.
- Natural phase split for the implementation plan: (1) parser + data model +
  resolution, fully unit-tested in isolation from any UI; (2)
  `CalibrationView` integration (the view with the actual reported bugs);
  (3) `MeasurementView` integration. Each phase should land with full test
  suite green before the next starts.
