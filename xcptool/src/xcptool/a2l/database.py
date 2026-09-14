"""A2L database loader: parse a file and resolve record-layout types."""
from __future__ import annotations

import logging
from pathlib import Path

from .parser import parse
from .types import DATATYPE_SIZES, A2LDatabase, Characteristic, InstanceNode, Measurement

_log = logging.getLogger(__name__)


def load(path: str | Path) -> A2LDatabase:
    """Parse an A2L file and return a fully resolved A2LDatabase.

    Steps:
    1. Read the file as UTF-8 (replace undecodable bytes).
    2. ``parse()`` — build measurements, characteristics, record_layouts.
    3. ``_resolve()`` — fill Characteristic.datatype from RecordLayout.
    4. ``_resolve_instances()`` — flatten INSTANCE into real Characteristic/
       Measurement objects + InstanceNode display tree.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    db = parse(text)
    _resolve(db)
    _resolve_instances(db)
    return db


def _resolve(db: A2LDatabase) -> None:
    """Propagate RecordLayout.datatype → Characteristic.datatype (và tương tự
    cho CharacteristicTypeDef — struct-leaf template cần datatype thật
    TRƯỚC khi _resolve_instances() cần tính byte size của nó)."""
    for char in db.characteristics.values():
        rl = db.record_layouts.get(char.record_layout)
        if rl:
            char.datatype = rl.datatype
    for tmpl in db.characteristic_types.values():
        rl = db.record_layouts.get(tmpl.record_layout)
        if rl:
            tmpl.datatype = rl.datatype


def _array_len(matrix_dim: list[int]) -> int:
    n = 1
    for d in matrix_dim:
        n *= d
    return n


def _resolve_instances(db: A2LDatabase) -> None:
    """Đệ quy flatten mọi INSTANCE thành Characteristic/Measurement thật
    (địa chỉ tuyệt đối) + InstanceNode (cây hiển thị cho UI). Struct lồng
    struct và mảng (component lẫn instance) xem Task 8/9/11."""
    for inst in db.instances.values():
        node = _resolve_one(db, inst.type_name, inst.address, inst.name,
                            inst.matrix_dim, frozenset())
        if node is not None:
            db.instance_trees[inst.name] = node


def _size_of(db: A2LDatabase, type_name: str) -> int | None:
    """Byte size của 1 phần tử — cần để stride qua mảng."""
    if type_name in db.struct_types:
        return db.struct_types[type_name].size
    if type_name in db.characteristic_types:
        tmpl = db.characteristic_types[type_name]
        if tmpl.datatype is None:
            return None
        return DATATYPE_SIZES.get(tmpl.datatype, 1) * tmpl.array_size
    if type_name in db.measurement_types:
        tmpl = db.measurement_types[type_name]
        return DATATYPE_SIZES.get(tmpl.datatype, 1) * tmpl.array_size
    return None


def _resolve_one(
    db: A2LDatabase, type_name: str, base_addr: int, name: str,
    matrix_dim: list[int], seen: frozenset[str],
) -> InstanceNode | None:
    n = _array_len(matrix_dim)
    if n == 1:
        return _resolve_type(db, type_name, base_addr, name, seen)

    size = _size_of(db, type_name)
    if size is None:
        _log.warning("Cannot size array element type %r for %r, skipping", type_name, name)
        return None
    children: list[InstanceNode] = []
    for i in range(n):
        child = _resolve_type(db, type_name, base_addr + i * size, f"{name}[{i}]", seen)
        if child is not None:
            children.append(child)
    if not children:
        return None
    return InstanceNode(name=name, address=base_addr, leaf_name=None,
                        is_measurement=False, struct_size=None, children=children)


def _resolve_type(
    db: A2LDatabase, type_name: str, addr: int, name: str, seen: frozenset[str],
) -> InstanceNode | None:
    if type_name in db.struct_types:
        if type_name in seen:
            _log.warning("Circular TYPEDEF_STRUCTURE reference at %r via %r, skipping",
                        name, type_name)
            return None
        struct = db.struct_types[type_name]
        children: list[InstanceNode] = []
        for comp in struct.components:
            child = _resolve_one(db, comp.type_name, addr + comp.offset,
                                 f"{name}.{comp.name}", comp.matrix_dim,
                                 seen | {type_name})
            if child is not None:
                children.append(child)
        return InstanceNode(name=name, address=addr, leaf_name=None,
                            is_measurement=False, struct_size=struct.size,
                            children=children)
    if type_name in db.characteristic_types:
        tmpl = db.characteristic_types[type_name]
        if name in db.characteristics:
            _log.warning("INSTANCE-resolved name %r collides with an existing "
                        "CHARACTERISTIC, skipping", name)
            return None
        db.characteristics[name] = Characteristic(
            name=name, description=tmpl.description, char_type=tmpl.char_type,
            address=addr, record_layout=tmpl.record_layout,
            lower_limit=tmpl.lower_limit, upper_limit=tmpl.upper_limit,
            compu_method=tmpl.compu_method, array_size=tmpl.array_size,
            datatype=tmpl.datatype)
        return InstanceNode(name=name, address=addr, leaf_name=name,
                            is_measurement=False, struct_size=None)
    if type_name in db.measurement_types:
        tmpl = db.measurement_types[type_name]
        if name in db.measurements:
            _log.warning("INSTANCE-resolved name %r collides with an existing "
                        "MEASUREMENT, skipping", name)
            return None
        db.measurements[name] = Measurement(
            name=name, description=tmpl.description, datatype=tmpl.datatype,
            address=addr, lower_limit=tmpl.lower_limit, upper_limit=tmpl.upper_limit,
            compu_method=tmpl.compu_method, matrix_dim=tmpl.matrix_dim)
        return InstanceNode(name=name, address=addr, leaf_name=name,
                            is_measurement=True, struct_size=None)
    _log.warning("INSTANCE/STRUCTURE_COMPONENT %r references unknown type %r, skipping",
                name, type_name)
    return None
