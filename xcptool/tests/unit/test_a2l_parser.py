"""Unit tests for A3a — A2L parser.

Loads examples/xcp_daq_example.a2l (which now contains both MEASUREMENT
and CHARACTERISTIC/RECORD_LAYOUT blocks) and verifies the parser output.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from xcptool.a2l import load, A2LDatabase

# Resolve the shared example file relative to this test file's location:
#   parents[0] = xcptool/tests/unit/
#   parents[1] = xcptool/tests/
#   parents[2] = xcptool/
#   parents[3] = xcp_driver/   <-- repo root where examples/ lives
A2L_PATH = Path(__file__).parents[3] / "examples" / "xcp_daq_example.a2l"


@pytest.fixture(scope="module")
def db() -> A2LDatabase:
    return load(A2L_PATH)


# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------

def test_a2l_file_exists() -> None:
    assert A2L_PATH.exists(), f"A2L file not found at {A2L_PATH}"


# ---------------------------------------------------------------------------
# MEASUREMENT checks
# ---------------------------------------------------------------------------

def test_measurement_count(db: A2LDatabase) -> None:
    """8 MEASUREMENT blocks expected (unchanged from original file)."""
    assert len(db.measurements) == 8


def test_engineRpm_address(db: A2LDatabase) -> None:
    assert db.measurements["engineRpm"].address == 0x90000004


def test_engineRpm_datatype(db: A2LDatabase) -> None:
    assert db.measurements["engineRpm"].datatype == "UWORD"


def test_engineRpm_limits(db: A2LDatabase) -> None:
    meas = db.measurements["engineRpm"]
    assert meas.lower_limit == 0
    assert meas.upper_limit == 8000


def test_torqueSamples_matrix_dim(db: A2LDatabase) -> None:
    """torqueSamples is a 1-D array with MATRIX_DIM 4."""
    meas = db.measurements["torqueSamples"]
    assert meas.matrix_dim == [4]
    assert meas.array_size == 4


# ---------------------------------------------------------------------------
# CHARACTERISTIC checks
# ---------------------------------------------------------------------------

def test_characteristic_count(db: A2LDatabase) -> None:
    """31 CHARACTERISTIC blocks were added (9 scalars + 4 arrays + 18 struct members)."""
    assert len(db.characteristics) == 31


def test_systemGain_fields(db: A2LDatabase) -> None:
    char = db.characteristics["systemGain"]
    assert char.address == 0x80100000
    assert char.datatype == "FLOAT32_IEEE"   # resolved via rl_float32
    assert char.lower_limit == 0.0
    assert char.upper_limit == 10.0
    assert char.char_type == "VALUE"
    assert char.array_size == 1


def test_torqueMap_fields(db: A2LDatabase) -> None:
    char = db.characteristics["torqueMap"]
    assert char.char_type == "VAL_BLK"
    assert char.array_size == 8


def test_timeoutMs_datatype(db: A2LDatabase) -> None:
    assert db.characteristics["timeoutMs"].datatype == "ULONG"


def test_tempOffsetDegC_datatype(db: A2LDatabase) -> None:
    assert db.characteristics["tempOffsetDegC"].datatype == "SWORD"


def test_trimValue_datatype(db: A2LDatabase) -> None:
    assert db.characteristics["trimValue"].datatype == "SBYTE"


# ---------------------------------------------------------------------------
# RECORD_LAYOUT checks
# ---------------------------------------------------------------------------

def test_record_layout_count(db: A2LDatabase) -> None:
    assert len(db.record_layouts) == 6


def test_rl_float32_datatype(db: A2LDatabase) -> None:
    assert db.record_layouts["rl_float32"].datatype == "FLOAT32_IEEE"


def test_rl_sint16_datatype(db: A2LDatabase) -> None:
    assert db.record_layouts["rl_sint16"].datatype == "SWORD"


# ---------------------------------------------------------------------------
# byte_size checks
# ---------------------------------------------------------------------------

def test_systemGain_byte_size(db: A2LDatabase) -> None:
    """FLOAT32_IEEE scalar: 4 bytes × 1 = 4."""
    assert db.characteristics["systemGain"].byte_size == 4


def test_torqueMap_byte_size(db: A2LDatabase) -> None:
    """FLOAT32_IEEE × 8 elements = 32 bytes."""
    assert db.characteristics["torqueMap"].byte_size == 32


def test_adcCalPoints_byte_size(db: A2LDatabase) -> None:
    """UWORD × 4 elements = 8 bytes."""
    assert db.characteristics["adcCalPoints"].byte_size == 8


def test_tempCompTable_byte_size(db: A2LDatabase) -> None:
    """SWORD × 6 elements = 12 bytes."""
    assert db.characteristics["tempCompTable"].byte_size == 12


# ---------------------------------------------------------------------------
# TYPEDEF_STRUCTURE checks (Task 2)
# ---------------------------------------------------------------------------

def test_typedef_structure_parses_components_and_matrix_dim() -> None:
    from xcptool.a2l.parser import parse
    text = """
    /begin TYPEDEF_STRUCTURE PidTelemetry_t "PID telemetry" 0x10
        /begin STRUCTURE_COMPONENT error T_Float32 0x0
        /end STRUCTURE_COMPONENT
        /begin STRUCTURE_COMPONENT samples T_I16 0x4
            MATRIX_DIM 3
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    """
    db = parse(text)
    struct = db.struct_types["PidTelemetry_t"]
    assert struct.size == 0x10
    assert [c.name for c in struct.components] == ["error", "samples"]
    assert struct.components[0].type_name == "T_Float32"
    assert struct.components[0].offset == 0
    assert struct.components[0].matrix_dim == []
    assert struct.components[1].offset == 4
    assert struct.components[1].matrix_dim == [3]
    assert struct.components[1].array_size == 3


# ---------------------------------------------------------------------------
# Struct-typedef dataclasses (Task 1)
# ---------------------------------------------------------------------------

def test_struct_typedef_dataclasses_exist_with_defaults() -> None:
    from xcptool.a2l.types import (
        A2LDatabase, CharacteristicTypeDef, Instance, InstanceNode,
        MeasurementTypeDef, StructComponent, StructTypeDef,
    )
    comp = StructComponent(name="kp", type_name="T_Float", offset=0)
    assert comp.array_size == 1
    comp_arr = StructComponent(name="samples", type_name="T_I16", offset=4, matrix_dim=[3])
    assert comp_arr.array_size == 3

    struct = StructTypeDef(name="PidTelemetry_t", size=12, components=[comp, comp_arr])
    assert struct.components == [comp, comp_arr]

    ctd = CharacteristicTypeDef(
        name="T_Float", description="", char_type="VALUE",
        record_layout="RL_F32", lower_limit=0.0, upper_limit=1.0)
    assert ctd.array_size == 1 and ctd.datatype is None

    mtd = MeasurementTypeDef(
        name="T_I16", description="", datatype="SWORD",
        lower_limit=-100.0, upper_limit=100.0)
    assert mtd.array_size == 1

    inst = Instance(name="tel", description="", type_name="PidTelemetry_t", address=0x1000)
    assert inst.array_size == 1

    node = InstanceNode(name="tel", address=0x1000, leaf_name=None,
                        is_measurement=False, struct_size=12)
    assert node.children == []

    db = A2LDatabase()
    assert db.struct_types == {} and db.characteristic_types == {}
    assert db.measurement_types == {} and db.instances == {}
    assert db.instance_trees == {}


# ---------------------------------------------------------------------------
# TYPEDEF_CHARACTERISTIC checks (Task 3)
# ---------------------------------------------------------------------------

def test_typedef_characteristic_parses_like_characteristic_minus_address() -> None:
    from xcptool.a2l.parser import parse
    text = """
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain leaf type" VALUE RL_F32 0 CM_LINEAR 0.0 10.0
    /end TYPEDEF_CHARACTERISTIC
    """
    db = parse(text)
    ct = db.characteristic_types["T_Gain"]
    assert ct.char_type == "VALUE"
    assert ct.record_layout == "RL_F32"
    assert ct.compu_method == "CM_LINEAR"
    assert ct.lower_limit == 0.0 and ct.upper_limit == 10.0
    assert ct.array_size == 1
    assert ct.datatype is None  # resolve() (Task 6) mới điền


# ---------------------------------------------------------------------------
# TYPEDEF_MEASUREMENT checks (Task 4)
# ---------------------------------------------------------------------------

def test_typedef_measurement_parses_matrix_dim() -> None:
    from xcptool.a2l.parser import parse
    text = """
    /begin TYPEDEF_MEASUREMENT T_Samples "sample leaf type" SWORD CM_NONE 0 0 -100 100
        MATRIX_DIM 4
    /end TYPEDEF_MEASUREMENT
    """
    db = parse(text)
    mt = db.measurement_types["T_Samples"]
    assert mt.datatype == "SWORD"
    assert mt.lower_limit == -100.0 and mt.upper_limit == 100.0
    assert mt.matrix_dim == [4]
    assert mt.array_size == 4
