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
    array_size: int = 1  # >1 for a VAL_BLK array kept as one leaf, not one per element


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
        out.append(LeafInfo(
            name=node.leaf_name, address=char.address,
            datatype=char.datatype, size=char.byte_size, array_size=char.array_size,
        ))
        return
    for child in node.children:
        _leaves_from_node(child, db, out)


def enumerate_leaves(db: A2LDatabase) -> list[LeafInfo]:
    """Every calibration leaf in `db` — flat CHARACTERISTICs and struct/
    array INSTANCE trees alike, one entry per CHARACTERISTIC (a VAL_BLK
    array is ONE leaf with `array_size > 1` and `size` covering the whole
    array, not one leaf per element — matches the granularity
    `a2l/dataset.py`'s dataset JSON and `encode_value()`'s `array_size`
    parameter already use; expanding into per-element leaves here would
    make a dataset entry for the array's bare name unmatchable).
    Characteristics with no resolved `datatype` are skipped (nothing to
    read/write for them). Order: instance-tree leaves first (in
    `db.instance_trees` iteration order), then remaining flat
    characteristics sorted by name.
    """
    out: list[LeafInfo] = []
    handled: set[str] = set()
    for node in db.instance_trees.values():
        _leaves_from_node(node, db, out)
        handled |= _leaf_names(node)

    for name, char in sorted(db.characteristics.items()):
        if name in handled or char.datatype is None:
            continue
        out.append(LeafInfo(
            name=name, address=char.address, datatype=char.datatype,
            size=char.byte_size, array_size=char.array_size,
        ))

    return out
