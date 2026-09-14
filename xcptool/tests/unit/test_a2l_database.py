"""Unit tests cho a2l/database.py — resolve() và struct-instance resolution."""
from __future__ import annotations

from xcptool.a2l.database import load
from xcptool.a2l.parser import parse
from xcptool.a2l.types import A2LDatabase


def _resolve(text: str) -> A2LDatabase:
    """Parse + chạy đúng pipeline resolve của load() (không cần file thật)."""
    from xcptool.a2l.database import _resolve as resolve_fn
    db = parse(text)
    resolve_fn(db)
    return db


def test_resolve_fills_datatype_for_characteristic_type_templates() -> None:
    db = _resolve("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_LINEAR 0.0 10.0
    /end TYPEDEF_CHARACTERISTIC
    """)
    assert db.characteristic_types["T_Gain"].datatype == "FLOAT32_IEEE"


def test_flat_instance_of_characteristic_type_materializes_real_characteristic() -> None:
    db = _resolve("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_LINEAR 0.0 10.0
    /end TYPEDEF_CHARACTERISTIC
    /begin INSTANCE mainGain "main gain instance" T_Gain 0x80100000
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)

    char = db.characteristics["mainGain"]
    assert char.address == 0x80100000
    assert char.datatype == "FLOAT32_IEEE"
    assert char.char_type == "VALUE"

    node = db.instance_trees["mainGain"]
    assert node.leaf_name == "mainGain"
    assert node.is_measurement is False
    assert node.address == 0x80100000
    assert node.children == []


def test_flat_instance_of_measurement_type_materializes_real_measurement() -> None:
    db = _resolve("""
    /begin TYPEDEF_MEASUREMENT T_Speed "speed" FLOAT32_IEEE CM_NONE 0 0 0 300
    /end TYPEDEF_MEASUREMENT
    /begin INSTANCE vehicleSpeed "speed instance" T_Speed 0x90000000
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)

    meas = db.measurements["vehicleSpeed"]
    assert meas.address == 0x90000000
    assert meas.datatype == "FLOAT32_IEEE"

    node = db.instance_trees["vehicleSpeed"]
    assert node.leaf_name == "vehicleSpeed"
    assert node.is_measurement is True
