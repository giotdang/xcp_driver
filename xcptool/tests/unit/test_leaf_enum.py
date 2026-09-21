"""Unit tests for ui/leaf_enum.py — pure data, no Qt required to run."""
from __future__ import annotations

from xcptool.a2l.types import A2LDatabase, Characteristic, InstanceNode
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
