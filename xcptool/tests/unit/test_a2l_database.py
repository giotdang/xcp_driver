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


def test_struct_instance_resolves_each_member_to_a_real_address() -> None:
    db = _resolve("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_LINEAR 0.0 10.0
    /end TYPEDEF_CHARACTERISTIC
    /begin TYPEDEF_STRUCTURE Pid_t "pid gains" 8
        /begin STRUCTURE_COMPONENT kp T_Gain 0
        /end STRUCTURE_COMPONENT
        /begin STRUCTURE_COMPONENT ki T_Gain 4
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE speedPid "speed pid" Pid_t 0x80100000
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)

    assert db.characteristics["speedPid.kp"].address == 0x80100000
    assert db.characteristics["speedPid.ki"].address == 0x80100004

    node = db.instance_trees["speedPid"]
    assert node.leaf_name is None
    assert node.struct_size == 8
    assert [c.name for c in node.children] == ["speedPid.kp", "speedPid.ki"]
    assert all(c.leaf_name == c.name for c in node.children)


def test_array_component_expands_to_indexed_addresses() -> None:
    db = _resolve("""
    /begin RECORD_LAYOUT RL_I16
        FNC_VALUES 1 SWORD ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_I16 "i16" VALUE RL_I16 0 CM_NONE -100 100
    /end TYPEDEF_CHARACTERISTIC
    /begin TYPEDEF_STRUCTURE WithArray_t "has array member" 6
        /begin STRUCTURE_COMPONENT samples T_I16 0
            MATRIX_DIM 3
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE grp "grp" WithArray_t 0x80100000
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)

    assert db.characteristics["grp.samples[0]"].address == 0x80100000
    assert db.characteristics["grp.samples[1]"].address == 0x80100002
    assert db.characteristics["grp.samples[2]"].address == 0x80100004

    node = db.instance_trees["grp"]
    samples_node = node.children[0]
    assert samples_node.leaf_name is None  # mảng — không phải lá
    assert [c.name for c in samples_node.children] == [
        "grp.samples[0]", "grp.samples[1]", "grp.samples[2]"]


def test_array_instance_of_struct_expands_each_element() -> None:
    db = _resolve("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin TYPEDEF_STRUCTURE Pid_t "pid" 4
        /begin STRUCTURE_COMPONENT kp T_Gain 0
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE pids "array of pid" Pid_t 0x80100000
        MATRIX_DIM 2
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)

    assert db.characteristics["pids[0].kp"].address == 0x80100000
    assert db.characteristics["pids[1].kp"].address == 0x80100004


def test_nested_struct_resolves_recursively() -> None:
    db = _resolve("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin TYPEDEF_STRUCTURE Inner_t "inner" 4
        /begin STRUCTURE_COMPONENT val T_Gain 0
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin TYPEDEF_STRUCTURE Outer_t "outer" 4
        /begin STRUCTURE_COMPONENT inner Inner_t 0
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE thing "nested" Outer_t 0x80100000
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)
    assert db.characteristics["thing.inner.val"].address == 0x80100000


def test_circular_struct_reference_warns_and_skips(caplog) -> None:
    db = _resolve("""
    /begin TYPEDEF_STRUCTURE A_t "a" 4
        /begin STRUCTURE_COMPONENT b B_t 0
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin TYPEDEF_STRUCTURE B_t "b" 4
        /begin STRUCTURE_COMPONENT a A_t 0
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE thing "circular" A_t 0x80100000
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)  # KHÔNG được raise / đệ quy vô hạn
    assert db.characteristics == {}
    assert "circular" in caplog.text.lower() or "recursion" in caplog.text.lower()


def test_unknown_type_name_warns_and_skips(caplog) -> None:
    db = _resolve("""
    /begin INSTANCE thing "bad type ref" NotDefinedAnywhere_t 0x80100000
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)
    assert db.instance_trees == {}
    assert "unknown" in caplog.text.lower() or "NotDefinedAnywhere_t" in caplog.text


def test_matrix_dim_zero_warns_and_skips(caplog) -> None:
    """Bug thật (final review, Fix 4): mọi guard khác trong _resolve_one/
    _resolve_type (unknown type, name collision, circular reference, size
    None) đều log warning trước khi trả None. Guard còn thiếu: khi
    _array_len(matrix_dim) == 0 (A2L khai sai "MATRIX_DIM 0"), nhánh mảng
    rơi thẳng vào `if not children: return None` (children luôn rỗng vì
    range(0) không lặp) mà KHÔNG log gì — component/instance biến mất khỏi
    tree, log không nói gì để giải thích tại sao."""
    db = _resolve("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin INSTANCE thing "malformed zero-length array" T_Gain 0x80100000
        MATRIX_DIM 0
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)  # KHÔNG được raise
    assert db.instance_trees == {}
    assert "matrix_dim" in caplog.text.lower() or "0 elements" in caplog.text.lower()


def test_name_collision_keeps_original_and_warns(caplog) -> None:
    db = _resolve("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin CHARACTERISTIC dup "already exists" VALUE 0x12345678 RL_F32 0 CM_NONE 0 10
    /end CHARACTERISTIC
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin INSTANCE dup "collides with the CHARACTERISTIC above" T_Gain 0x80100000
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)
    assert db.characteristics["dup"].address == 0x12345678  # KHÔNG bị ghi đè
    assert "collide" in caplog.text.lower() or "collision" in caplog.text.lower()
