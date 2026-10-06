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


# Mã EVENT_CHANNEL_TIME_UNIT / TIMESTAMP_UNIT theo ASAM (A2L dùng chung bảng
# này cho EVENT và cho timestamp DAQ). Giá trị = số nanosecond của 1 unit;
# thiếu mã nào (picosecond 0xA–0xC) = không biểu diễn được bằng ns nguyên.
TIME_UNIT_NS: dict[int, int] = {
    0x0: 1, 0x1: 10, 0x2: 100,
    0x3: 1_000, 0x4: 10_000, 0x5: 100_000,
    0x6: 1_000_000, 0x7: 10_000_000, 0x8: 100_000_000,
    0x9: 1_000_000_000,
}


@dataclass(frozen=True)
class DaqEventSpec:
    """`/begin DAQ_EVENT ... /end DAQ_EVENT` trong IF_DATA XCP của một
    MEASUREMENT / TYPEDEF_MEASUREMENT / INSTANCE (ASAM MCD-2 MC).

    Hai dạng theo spec:

    * ``mode="fixed"``   -- `/begin FIXED_EVENT_LIST EVENT n ... /end`: signal
      CHỈ đo được ở các event này. Một phần tử => không có gì để chọn; nhiều
      phần tử => người dùng chọn trong số đó.
    * ``mode="variable"`` -- `VARIABLE` + `/begin AVAILABLE_EVENT_LIST ...` và
      `/begin DEFAULT_EVENT_LIST ...`: người dùng chọn trong `available`
      (rỗng = mọi event của ECU), `default` là gợi ý ban đầu.

    `None` (field không được set) nghĩa là A2L KHÔNG khai gì -- khác hẳn với
    "khai event 0". Khi đó mọi event DAQ của ECU đều là lựa chọn hợp lệ và
    tool không được tự đoán giúp.
    """
    mode: Literal["fixed", "variable"]
    fixed: tuple[int, ...] = ()
    available: tuple[int, ...] = ()
    default: tuple[int, ...] = ()


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
    # Event mặc định suy ra từ `daq_event` (DEFAULT_EVENT_LIST, hoặc
    # FIXED_EVENT_LIST một phần tử). None = A2L không khai -> người dùng phải
    # chọn. Cần TẤT CẢ lựa chọn hợp lệ (không chỉ cái mặc định) thì dùng
    # `a2l.events.allowed_events()`.
    event_channel: int | None = None
    daq_event: DaqEventSpec | None = None

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
    daq_event: DaqEventSpec | None = None

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
    # DAQ_EVENT khai ở cấp INSTANCE -- áp cho MỌI lá measurement bên trong và
    # thắng khai báo của TYPEDEF_MEASUREMENT (instance cụ thể hoá template).
    daq_event: DaqEventSpec | None = None

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


@dataclass(frozen=True)
class DaqListCanId:
    """Một /begin DAQ_LIST_CAN_ID trong XCP_ON_CAN: DAQ list này phát trên CAN ID
    riêng. `VARIABLE` không kèm ID (master phải SET_DAQ_ID) nên `can_id=None`."""
    daq_list: int
    fixed: bool
    can_id: int | None


@dataclass(frozen=True)
class XcpCanInfo:
    """Cấu hình CAN của ECU đọc từ IF_DATA XCP / XCP_ON_CAN. Trường nào A2L không
    có thì None — người dùng/`BusConfig` tự điền.

    ID đã bỏ bit 31 (cờ 29-bit), cờ đó nằm ở `extended`.
    """
    master_id: int | None
    slave_id: int | None
    extended: bool | None
    baudrate: int | None
    sample_point: float | None            # % của bit time
    is_fd: bool
    fd_data_baudrate: int | None
    fd_data_sample_point: float | None
    max_dlc_required: bool
    daq_list_ids: tuple[DaqListCanId, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class XcpDaqInfo:
    """/begin DAQ ... /end DAQ trong IF_DATA XCP cấp MODULE — song song với
    DaqCaps runtime (session/api.py, đọc từ GET_DAQ_PROCESSOR_INFO lúc
    CONNECT), nhưng đọc được từ A2L TRƯỚC khi connect. Xem
    examples/xcp_daq_example.a2l dòng 88-98.
    """
    dynamic_daq: bool          # DAQ_CONFIG_TYPE: True=DYNAMIC, False=STATIC
    max_daq: int
    max_event_channel: int
    min_daq: int


@dataclass(frozen=True)
class EventChannel:
    """Một /begin EVENT ... /end EVENT lồng trong DAQ — xem
    examples/xcp_daq_example.a2l dòng 100-121. `time_unit` là mã thô theo
    A2L (0..9, xem ASAM CCP/XCP time unit table), chưa quy đổi ra ns.
    """
    name: str
    short_name: str
    number: int
    max_daq_list: int
    time_cycle: int
    time_unit: int
    priority: int
    # Token [3] của /begin EVENT: DAQ | STIM | DAQ_STIM. Event chỉ-STIM không
    # dùng được để đo. "" = A2L cũ không khai -> coi như dùng được cho DAQ:
    # thà hiện một event không dùng được còn hơn ẩn mất event hợp lệ.
    direction: str = ""

    @property
    def supports_daq(self) -> bool:
        return self.direction in ("", "DAQ", "DAQ_STIM")

    @property
    def cycle_ns(self) -> int:
        """Chu kỳ raster tính bằng ns; 0 = không tuần hoàn (TIME_CYCLE=0 theo
        ASAM) hoặc mã TIME_UNIT không quy đổi được."""
        return self.time_cycle * TIME_UNIT_NS.get(self.time_unit, 0)


@dataclass(frozen=True)
class StaticDaqList:
    """Một /begin DAQ_LIST ... /end DAQ_LIST trong A2L — mô tả một list
    tĩnh có sẵn trên ECU (chỉ xuất hiện khi DAQ_CONFIG_TYPE=STATIC,
    MIN_DAQ>0).

    GIỚI HẠN QUAN TRỌNG: field ở đây chỉ cho biết CẤU TRÚC list (số ODT,
    số entry/ODT, event có bị fix cứng không) — theo hiểu biết của tôi,
    khung IF_DATA XCP chuẩn KHÔNG có cách biểu diễn signal nào nằm ở ODT
    entry nào cho một list `predefined=True`; thông tin đó (nếu ECU của
    bạn cần) phải lấy từ tài liệu ECU/nhà cung cấp, không tự suy ra được
    từ đây — dùng để tự dựng `master.daq.PredefinedDaqList.odts` thủ công.
    `examples/xcp_daq_example.a2l` dùng DYNAMIC/MIN_DAQ=0 nên không có ví
    dụ /begin DAQ_LIST thật trong repo để đối chiếu field order — xác nhận
    lại với A2L ECU static thật hoặc spec ASAM MCD-1 XCP Part 2 khi có.
    """
    number: int
    max_odt: int | None = None
    max_odt_entries: int | None = None
    predefined: bool = False
    fixed_event: int | None = None


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
    can_info: XcpCanInfo | None = None
    daq_info: XcpDaqInfo | None = None
    events: dict[int, EventChannel] = field(default_factory=dict)
    static_daq_lists: dict[int, StaticDaqList] = field(default_factory=dict)
