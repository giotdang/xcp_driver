"""A2L dataclasses: RecordLayout, Measurement, Characteristic, A2LDatabase."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, get_args  # get_args exported for callers

DataType = Literal[
    "UBYTE", "SBYTE",
    "UWORD", "SWORD",
    "ULONG", "SLONG",
    "FLOAT32_IEEE", "FLOAT64_IEEE",
]

DATATYPE_SIZES: dict[str, int] = {
    "UBYTE": 1, "SBYTE": 1,
    "UWORD": 2, "SWORD": 2,
    "ULONG": 4, "SLONG": 4,
    "FLOAT32_IEEE": 4, "FLOAT64_IEEE": 8,
}


@dataclass
class RecordLayout:
    name: str
    datatype: DataType


@dataclass
class Measurement:
    name: str
    description: str
    datatype: DataType
    address: int
    lower_limit: float
    upper_limit: float
    compu_method: str = "NO_COMPU_METHOD"
    matrix_dim: list[int] = field(default_factory=list)
    event_channel: int | None = None

    @property
    def array_size(self) -> int:
        s = 1
        for d in self.matrix_dim:
            s *= d
        return s

    @property
    def byte_size(self) -> int:
        return DATATYPE_SIZES.get(self.datatype, 1) * self.array_size


@dataclass
class Characteristic:
    name: str
    description: str
    char_type: str      # "VALUE" | "VAL_BLK" | "CURVE" | "MAP"
    address: int
    record_layout: str  # name of RecordLayout
    lower_limit: float
    upper_limit: float
    compu_method: str = "NO_COMPU_METHOD"
    array_size: int = 1  # for VAL_BLK: number of elements (from NUMBER keyword)
    # Resolved after database.resolve():
    datatype: DataType | None = None

    @property
    def byte_size(self) -> int:
        if self.datatype is None:
            return 0
        return DATATYPE_SIZES.get(self.datatype, 1) * self.array_size


@dataclass
class StructComponent:
    """Một thành viên của TYPEDEF_STRUCTURE — ASAP2 STRUCTURE_COMPONENT."""
    name: str
    type_name: str        # -> StructTypeDef | CharacteristicTypeDef | MeasurementTypeDef, theo tên
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
    """ASAP2 TYPEDEF_STRUCTURE — một KIỂU struct, không phải instance đã đặt."""
    name: str
    size: int              # byte size khai thật trong A2L — không tự tính
    components: list[StructComponent] = field(default_factory=list)


@dataclass
class CharacteristicTypeDef:
    """ASAP2 TYPEDEF_CHARACTERISTIC — giống Characteristic, bỏ `address`
    (là template STRUCTURE_COMPONENT/INSTANCE tham chiếu tới, không phải giá
    trị đã đặt vào bộ nhớ)."""
    name: str
    description: str
    char_type: str
    record_layout: str
    lower_limit: float
    upper_limit: float
    compu_method: str = "NO_COMPU_METHOD"
    array_size: int = 1
    datatype: DataType | None = None


@dataclass
class MeasurementTypeDef:
    """ASAP2 TYPEDEF_MEASUREMENT — giống Measurement, bỏ `address`."""
    name: str
    description: str
    datatype: DataType
    lower_limit: float
    upper_limit: float
    compu_method: str = "NO_COMPU_METHOD"
    matrix_dim: list[int] = field(default_factory=list)

    @property
    def array_size(self) -> int:
        s = 1
        for d in self.matrix_dim:
            s *= d
        return s


@dataclass
class Instance:
    """ASAP2 INSTANCE — đặt một TYPEDEF_* vào địa chỉ ECU thật."""
    name: str
    description: str
    type_name: str          # -> StructTypeDef | CharacteristicTypeDef | MeasurementTypeDef
    address: int
    matrix_dim: list[int] = field(default_factory=list)

    @property
    def array_size(self) -> int:
        s = 1
        for d in self.matrix_dim:
            s *= d
        return s


@dataclass
class InstanceNode:
    """Cây đã resolve cho 1 INSTANCE — dựng bởi a2l/database.py duy nhất;
    UI chỉ đọc, không tự suy địa chỉ/tên phân cấp (xem spec §10)."""
    name: str                  # tên phân cấp đầy đủ, VD "grp.member[0]"
    address: int
    leaf_name: str | None      # key trong characteristics/measurements nếu là lá; None nếu là struct/mảng cha
    is_measurement: bool       # leaf_name thuộc measurements (True) hay characteristics (False) — vô nghĩa nếu leaf_name None
    struct_size: int | None    # StructTypeDef.size thật nếu node này là struct cha; None nếu không phải
    children: list["InstanceNode"] = field(default_factory=list)


@dataclass
class XcpProtocolInfo:
    max_cto: int = 8
    max_dto: int = 8
    is_fd: bool = False
    can_fd_max_dlc: int = 8
    max_dlc_required: bool = False
    byte_order: str = "little"
    protocol_version: str = "1.0"


@dataclass
class A2LDatabase:
    measurements: dict[str, Measurement] = field(default_factory=dict)
    characteristics: dict[str, Characteristic] = field(default_factory=dict)
    record_layouts: dict[str, RecordLayout] = field(default_factory=dict)
    struct_types: dict[str, StructTypeDef] = field(default_factory=dict)
    characteristic_types: dict[str, CharacteristicTypeDef] = field(default_factory=dict)
    measurement_types: dict[str, MeasurementTypeDef] = field(default_factory=dict)
    instances: dict[str, Instance] = field(default_factory=dict)
    instance_trees: dict[str, InstanceNode] = field(default_factory=dict)
    protocol_info: XcpProtocolInfo | None = None
