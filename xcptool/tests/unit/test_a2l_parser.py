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


# ---------------------------------------------------------------------------
# INSTANCE checks (Task 5)
# ---------------------------------------------------------------------------

def test_instance_parses_type_ref_address_and_array() -> None:
    from xcptool.a2l.parser import parse
    text = """
    /begin INSTANCE speedPidTelemetry "PID telemetry instance" PidTelemetry_t 0x90001000
    /end INSTANCE
    /begin INSTANCE tempSensors "sensor array" T_Gain 0x90002000
        MATRIX_DIM 3
    /end INSTANCE
    """
    db = parse(text)
    inst = db.instances["speedPidTelemetry"]
    assert inst.type_name == "PidTelemetry_t"
    assert inst.address == 0x90001000
    assert inst.array_size == 1

    arr_inst = db.instances["tempSensors"]
    assert arr_inst.matrix_dim == [3]
    assert arr_inst.array_size == 3


# ---------------------------------------------------------------------------
# IF_DATA XCP / DAQ — DAQ_CONFIG_TYPE, EVENT, Measurement.event_channel
# ---------------------------------------------------------------------------

def test_daq_info_parses_config_type_and_counts(db: A2LDatabase) -> None:
    assert db.daq_info is not None
    assert db.daq_info.dynamic_daq is True   # examples/xcp_daq_example.a2l dùng DYNAMIC
    assert db.daq_info.max_daq == 2
    assert db.daq_info.max_event_channel == 2
    assert db.daq_info.min_daq == 0


def test_event_channels_parsed(db: A2LDatabase) -> None:
    assert set(db.events) == {0, 1}
    ev0 = db.events[0]
    assert ev0.name == "10 ms raster"
    assert ev0.short_name == "10ms"
    assert ev0.time_cycle == 10
    assert ev0.time_unit == 6
    assert ev0.max_daq_list == 1
    ev1 = db.events[1]
    assert ev1.name == "100 ms raster"
    assert ev1.time_cycle == 100


def test_measurement_event_channel_wired_from_daq_event(db: A2LDatabase) -> None:
    """DAQ_EVENT/FIXED_EVENT_LIST/EVENT trong IF_DATA của từng MEASUREMENT
    phải gán đúng Measurement.event_channel — trước đây field này luôn None,
    parser chưa từng gán (xem CLAUDE.md history / Phase 2)."""
    assert db.measurements["engineRpm"].event_channel == 0        # "10 ms raster"
    assert db.measurements["vehicleSpeedKph"].event_channel == 0
    assert db.measurements["coolantTempC"].event_channel == 1     # "100 ms raster"
    assert db.measurements["torqueSamples"].event_channel == 0


def test_module_level_if_data_not_clobbered_by_measurement_daq_event() -> None:
    """Regression: _visit() từng nhận nhầm BẤT KỲ IF_DATA XCP nào (kể cả lồng
    trong MEASUREMENT, chỉ chứa DAQ_EVENT) là IF_DATA XCP cấp MODULE, gọi
    _extract_xcp_protocol_info() trên nó -> luôn trả XcpProtocolInfo() mặc
    định (không có PROTOCOL_LAYER) -> ghi đè db.protocol_info sau mỗi
    measurement. MAX_CTO=16/MAX_DTO=32 (khác hẳn default 8/8) để bug này
    không thể tình cờ "đúng" như examples/xcp_daq_example.a2l."""
    from xcptool.a2l.parser import parse
    text = """
    /begin PROJECT test "Project"
      /begin MODULE test "Module"
        /begin IF_DATA XCP
          /begin PROTOCOL_LAYER
            0x0100
            1000 2000 0 0 0
            16 32
            BYTE_ORDER_MSB_LAST
          /end PROTOCOL_LAYER
        /end IF_DATA
        /begin MEASUREMENT sig1
          "signal 1" UWORD NO_COMPU_METHOD 0 0 0 100
          ECU_ADDRESS 0x90000000
          /begin IF_DATA XCP
            /begin DAQ_EVENT
              /begin FIXED_EVENT_LIST
                EVENT 0x00
              /end FIXED_EVENT_LIST
            /end DAQ_EVENT
          /end IF_DATA
        /end MEASUREMENT
      /end MODULE
    /end PROJECT
    """
    db = parse(text)
    assert db.protocol_info is not None
    assert db.protocol_info.max_cto == 16
    assert db.protocol_info.max_dto == 32
    assert db.measurements["sig1"].event_channel == 0


def test_static_daq_list_parsed_from_daq_list_block() -> None:
    """/begin DAQ_LIST — KHÔNG có ví dụ thật trong repo để đối chiếu field
    order (xem hedge đầy đủ ở StaticDaqList/types.py); test bằng snippet tự
    tạo theo suy đoán tốt nhất về khung IF_DATA XCP, xác nhận logic trích
    xuất tự nhất quán — không xác nhận được liệu ECU thật có đúng syntax
    này hay không."""
    from xcptool.a2l.parser import parse
    text = """
    /begin PROJECT test "Project"
      /begin MODULE test "Module"
        /begin IF_DATA XCP
          /begin DAQ
            STATIC
            0x02
            0x01
            0x02
            OPTIMISATION_TYPE_DEFAULT
            ADDRESS_EXTENSION_FREE
            IDENTIFICATION_FIELD_TYPE_ABSOLUTE
            GRANULARITY_ODT_ENTRY_SIZE_DAQ_BYTE
            0x07
            OVERLOAD_INDICATION_PID
            /begin DAQ_LIST
              0x00
              MAX_ODT 0x02
              MAX_ODT_ENTRIES 0x07
              EVENT_FIXED 0x00
              /begin PREDEFINED
              /end PREDEFINED
            /end DAQ_LIST
            /begin DAQ_LIST
              0x01
              MAX_ODT 0x01
              MAX_ODT_ENTRIES 0x07
            /end DAQ_LIST
          /end DAQ
        /end IF_DATA
      /end MODULE
    /end PROJECT
    """
    db = parse(text)
    assert db.daq_info is not None
    assert db.daq_info.dynamic_daq is False
    assert db.daq_info.max_daq == 2
    assert db.daq_info.min_daq == 2

    assert set(db.static_daq_lists) == {0, 1}
    l0 = db.static_daq_lists[0]
    assert l0.max_odt == 2
    assert l0.max_odt_entries == 7
    assert l0.predefined is True
    assert l0.fixed_event == 0

    l1 = db.static_daq_lists[1]
    assert l1.predefined is False
    assert l1.fixed_event is None
