"""DAQ engine — packing, allocation, DTO decoding.

D4a: DaqSignal + pack_odts()
D4b: DaqListConfig, OdtSignalLayout, PidEntry, configure_daq, stop_daq
D4c: SamplePoint, TimestampAccumulator, decode_dto

Nguyên tắc: không import can, không import PySide6, không import ui/transport.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from ..session.api import (
    DaqCaps,
    NotConnectedError,
    SlaveCaps,
    SlaveError,
    StaticDaqCapacityError,
    UnsupportedByEcuError,
)
from .constants import ErrCode

if TYPE_CHECKING:
    from .core import XcpMaster

__all__ = [
    "DaqSignal", "pack_odts",
    "DtoFormat", "DtoKey", "make_key", "effective_timestamp",
    "DaqListConfig", "OdtSignalLayout", "PidEntry",
    "configure_daq", "stop_daq",
    "PredefinedDaqList", "configure_daq_predefined",
    "SamplePoint", "TimestampAccumulator", "decode_dto",
]


@dataclass(frozen=True)
class DaqSignal:
    """Một signal cần đưa vào DAQ list.

    Tạo từ A2L Measurement:
        DaqSignal(name=m.name, address=m.address, ext=0, size=m.byte_size, datatype=m.datatype)
    """
    name: str
    address: int
    ext: int        # address extension, 0 cho hầu hết ECU CAN
    size: int       # bytes — từ DATATYPE_SIZES[datatype] * array_size
    datatype: str   # DataType literal, dùng trong D4c để decode giá trị


_HEADER_LEN = (1, 2, 3, 4)   # theo id_type 0..3


@dataclass(frozen=True)
class DtoFormat:
    """Layout gói DTO mà ECU dùng — suy ra một lần từ caps, không hardcode.

    id_type:   kiểu identification field (DAQ_KEY_BYTE bit 7-6):
               0 = absolute ODT number            → header `PID`
               1 = relative ODT + DAQ list (BYTE) → header `ODT, DAQ`
               2 = relative ODT + DAQ list (WORD) → header `ODT, DAQ_lo, DAQ_hi`
               3 = như 2 kèm byte FILL            → header `ODT, FILL, DAQ_lo, DAQ_hi`
    byte_order: thứ tự byte của slave (WORD số DAQ list, timestamp).
    ts_size:   0 (không có timestamp) | 1 | 2 | 4 byte.
    unit_ns, ticks: bộ đếm tăng `ticks` mỗi `unit_ns` ns (0 = không hợp lệ).
    overload:  cách ECU báo overrun: "pid_msb" (MSB của PID) | "event" | "none".
    ts_always: TIMESTAMP_FIXED — mọi DTO đều mang timestamp, master không tắt được.

    `DtoFormat()` mặc định tái tạo đúng hành vi cũ của xcptool (header 1 byte,
    timestamp 4 byte/10 ns, overrun ở MSB của PID) — dùng khi ECU không trả lời
    GET_DAQ_PROCESSOR_INFO/GET_DAQ_RESOLUTION_INFO.
    """
    id_type: int = 0
    byte_order: Literal["little", "big"] = "little"
    ts_size: int = 4
    unit_ns: int = 10
    ticks: int = 1
    overload: Literal["none", "pid_msb", "event"] = "pid_msb"
    ts_always: bool = False

    def __post_init__(self) -> None:
        if self.id_type not in (0, 1, 2, 3):
            raise ValueError(f"id_type phải là 0..3, nhận {self.id_type}")
        if self.ts_size not in (0, 1, 2, 4):
            raise ValueError(f"ts_size phải là 0, 1, 2 hoặc 4, nhận {self.ts_size}")

    @property
    def header_len(self) -> int:
        return _HEADER_LEN[self.id_type]

    def data_start(self, has_timestamp: bool) -> int:
        """Offset (từ đầu frame) của byte dữ liệu đầu tiên."""
        return self.header_len + (self.ts_size if has_timestamp else 0)

    @classmethod
    def from_caps(cls, daq_caps: DaqCaps | None,
                  byte_order: Literal["little", "big"] = "little") -> DtoFormat:
        if daq_caps is None:
            return cls(byte_order=byte_order)
        return cls(
            id_type=daq_caps.id_field_type,
            byte_order=byte_order,
            ts_size=daq_caps.timestamp_size,
            unit_ns=daq_caps.timestamp_unit_ns,
            ticks=daq_caps.timestamp_ticks,
            overload=daq_caps.overload,
            ts_always=daq_caps.timestamp_fixed,
        )

    @classmethod
    def from_slave_caps(cls, caps: SlaveCaps | None) -> DtoFormat:
        """Hàm DUY NHẤT dựng DtoFormat từ caps — `configure_daq` và
        `RealSession` đều dùng nên hai bên không thể lệch nhau."""
        if caps is None:
            return cls()
        return cls.from_caps(caps.daq, caps.byte_order)


DtoKey = int | tuple[int, int]
"""Khoá bảng tra DTO: `PID` (kiểu 0) hoặc `(số DAQ list, số ODT tương đối)` (kiểu 1–3)."""


def make_key(fmt: DtoFormat, daq: int, odt: int, first_pid: int) -> DtoKey:
    """Khoá bảng tra cho ODT `odt` của DAQ list vật lý `daq`.

    Kiểu 0: PID tuyệt đối = `first_pid + odt`. Kiểu 1–3: DTO mang sẵn số DAQ
    list và ODT tương đối, `first_pid` không dùng.
    """
    if fmt.id_type == 0:
        return first_pid + odt
    return (daq, odt)


def effective_timestamp(requested: bool, fmt: DtoFormat) -> bool:
    """Timestamp thực sự có trong DTO của một DAQ list.

    - TIMESTAMP_FIXED: luôn có (master không tắt được), bất kể `requested`.
    - ECU không hỗ trợ timestamp (`ts_size == 0`): không có — hạ xuống tắt
      im lặng, kết quả giống `timestamp=False` (`timestamp_ns = 0`).
    - Còn lại: theo `requested`.
    """
    if fmt.ts_always:
        return True
    if fmt.ts_size == 0:
        return False
    return requested


@dataclass
class DaqListConfig:
    """Một DAQ list cần cấu hình trên ECU.

    signals: danh sách tín hiệu cần đo.
    event:   mã kênh event (lấy từ A2L IF_DATA XCP EVENT hoặc hardcode với ECU tham chiếu).
    timestamp: True = bật timestamp trên ODT 0 (mode bit4=0x10).
    """
    signals: list[DaqSignal]
    event: int
    timestamp: bool = True
    prescaler: int = 1      # 1 = mỗi event một lần, 2 = cách một event, v.v.
    priority: int = 0       # 0 = thấp nhất


@dataclass(frozen=True)
class OdtSignalLayout:
    """Vị trí một tín hiệu trong frame DTO.

    frame_offset: byte offset tính từ đầu frame (byte 0 = PID).
    """
    signal: DaqSignal
    frame_offset: int


@dataclass(frozen=True)
class PidEntry:
    """Thông tin cần để decode một DTO frame.

    Tra bảng O(1) bằng `PID & 0x7F` (cần mask bit 7 trước — đó là bit overrun).
    """
    daq_list: int
    odt_index: int
    has_timestamp: bool     # True chỉ khi odt_index == 0 và list có timestamp
    signals: list[OdtSignalLayout]


def configure_daq(
    master: "XcpMaster",
    configs: list[DaqListConfig],
) -> dict[int, PidEntry]:
    """Chạy toàn bộ trình tự cấu hình DAQ, trả về PID table cho decoder.

    Dynamic (`caps.daq.dynamic_daq=True`, hoặc `caps.daq is None` — không rõ,
    vẫn thử dynamic trước vì không có cách nào khác để biết cấu trúc list):
        FREE_DAQ → ALLOC_* → WRITE_DAQ × n → SET_DAQ_LIST_MODE →
        START_STOP_DAQ_LIST(select) × n → START_STOP_SYNCH(1).

    Static (`caps.daq.dynamic_daq=False`): ECU không cho ALLOC_*, list phải
    có sẵn — CLEAR_DAQ_LIST thay FREE_DAQ, list vật lý được chọn theo dung
    lượng còn trống (GET_DAQ_LIST_INFO) nên có thể không trùng thứ tự configs.

    Raises:
        UnsupportedByEcuError: ECU không có DAQ; hoặc (`caps.daq is None`)
            ECU từ chối cả FREE_DAQ/ALLOC_* lẫn không cho biết DAQ_CONFIG_TYPE.
        StaticDaqCapacityError: ECU static nhưng không đủ list rảnh.
        NotConnectedError: chưa CONNECT.
        SlaveError: ECU từ chối một bước trong chuỗi (sai thứ tự, tràn bộ nhớ...).
    """
    caps = master.caps
    if caps is None:
        raise NotConnectedError("Chưa CONNECT tới ECU")

    max_dto = caps.max_dto
    daq_caps = caps.daq
    ts_size = (daq_caps.timestamp_size if daq_caps else 4)  # byte, thường 4 trên ECU tham chiếu

    # Đóng gói signals vào ODTs theo ngân sách từng ODT
    packed: list[list[list[DaqSignal]]] = [
        pack_odts(cfg.signals, cfg.timestamp, max_dto) for cfg in configs
    ]

    if daq_caps is not None and not daq_caps.dynamic_daq:
        daq_indices = _reserve_static_lists(master, packed, daq_caps)
    else:
        daq_indices = _reserve_dynamic_lists(master, configs, packed, daq_caps)

    return _write_and_start(master, configs, packed, daq_indices, ts_size)


def _reserve_dynamic_lists(
    master: "XcpMaster",
    configs: list[DaqListConfig],
    packed: list[list[list[DaqSignal]]],
    daq_caps: DaqCaps | None,
) -> list[int]:
    """FREE_DAQ → ALLOC_DAQ → ALLOC_ODT → ALLOC_ODT_ENTRY.

    `daq_caps is None` (ECU không trả GET_DAQ_PROCESSOR_INFO): vẫn thử —
    không có cách nào khác để biết ECU tổ chức DAQ list ra sao. Nếu ECU từ
    chối bằng ERR_CMD_UNKNOWN, báo lỗi rõ ràng thay vì để lộ mã lỗi thô:
    người dùng cần biết đây là ECU (có thể) static nhưng thiếu luôn
    GET_DAQ_PROCESSOR_INFO nên không thể tự động dò ra cấu trúc list.
    """
    try:
        # ── FREE_DAQ ─────────────────────────────────────────────────────────
        master.free_daq()

        # ── ALLOC_DAQ ────────────────────────────────────────────────────────
        master.alloc_daq(len(configs))

        # ── ALLOC_ODT (mỗi list một lần) ────────────────────────────────────
        for daq_idx, odts in enumerate(packed):
            master.alloc_odt(daq_idx, len(odts))

        # ── ALLOC_ODT_ENTRY (mỗi ODT một lần) ───────────────────────────────
        for daq_idx, odts in enumerate(packed):
            for odt_idx, odt in enumerate(odts):
                master.alloc_odt_entry(daq_idx, odt_idx, len(odt))
    except SlaveError as e:
        if daq_caps is None and e.code == ErrCode.CMD_UNKNOWN:
            raise UnsupportedByEcuError(
                "Dynamic DAQ — ECU từ chối FREE_DAQ/ALLOC_* (ERR_CMD_UNKNOWN) và "
                "cũng không trả lời GET_DAQ_PROCESSOR_INFO nên không thể tự suy ra "
                "Static DAQ list. Cần A2L có /begin DAQ_LIST hoặc xác nhận thủ công "
                "với nhà cung cấp ECU."
            ) from e
        raise

    return list(range(len(configs)))


def _reserve_static_lists(
    master: "XcpMaster",
    packed: list[list[list[DaqSignal]]],
    daq_caps: DaqCaps,
) -> list[int]:
    """Gán mỗi config một DAQ list có sẵn đủ ODT — ECU static không ALLOC_*
    được nên phải tái dùng list đã tồn tại (0..max_daq-1).

    Duyệt list theo thứ tự, chọn list "rảnh" (chưa gán cho config nào khác
    trong cùng lần gọi này) đầu tiên có `max_odt >= len(odts)`, rồi
    CLEAR_DAQ_LIST để xoá nội dung cũ trước khi ghi. Không theo dõi được
    list đang bị chiếm bởi phiên DAQ khác trên cùng ECU (ngoài phạm vi
    thông tin GET_DAQ_LIST_INFO cung cấp).

    Raises:
        StaticDaqCapacityError: không đủ list rảnh cho toàn bộ configs.
    """
    max_daq = daq_caps.max_daq
    used: set[int] = set()
    daq_indices: list[int] = []

    for odts in packed:
        need = len(odts)
        found: int | None = None
        skipped_predefined = 0
        for daq in range(max_daq):
            if daq in used:
                continue
            info = master.get_daq_list_info(daq)
            if info.predefined:
                # Nội dung ODT do ECU tự định nghĩa sẵn — không có cách nào
                # biết signal nào đã ở đó, nên KHÔNG được WRITE_DAQ vào đây.
                # Dùng configure_daq_predefined() với layout đã biết trước
                # (từ A2L /begin DAQ_LIST hoặc tài liệu ECU) thay vào đó.
                skipped_predefined += 1
                continue
            if info.max_odt >= need:
                found = daq
                break
        if found is None:
            hint = (f" ({skipped_predefined} list bị bỏ qua vì predefined=True — "
                     "nội dung cố định, cần configure_daq_predefined() thay vào đó)"
                     if skipped_predefined else "")
            raise StaticDaqCapacityError(
                f"Không tìm được DAQ list tĩnh nào còn rảnh, ghi được, và đủ "
                f"{need} ODT (tổng {max_daq} list trên ECU){hint}."
            )
        used.add(found)
        daq_indices.append(found)
        master.clear_daq_list(found)

    return daq_indices


@dataclass
class PredefinedDaqList:
    """Một DAQ list tĩnh có NỘI DUNG CỐ ĐỊNH (predefined=True qua
    GET_DAQ_LIST_INFO) — ECU tự định nghĩa sẵn signal nào ở ODT nào, master
    không được và không thể tự suy ra. `odts` phải do caller cung cấp từ A2L
    `/begin DAQ_LIST` hoặc tài liệu ECU, với `frame_offset` đã tính sẵn
    (byte 0 = PID, cộng thêm timestamp nếu có — xem `OdtSignalLayout`).
    """
    daq: int                              # list vật lý trên ECU
    odts: list[list[OdtSignalLayout]]     # layout cố định — KHÔNG suy ra được, phải cung cấp
    event: int | None = None              # bắt buộc nếu ECU không fix cứng event (xem fixed_event)
    timestamp: bool = True
    prescaler: int = 1
    priority: int = 0


def configure_daq_predefined(
    master: "XcpMaster",
    lists: list[PredefinedDaqList],
) -> dict[int, PidEntry]:
    """Khởi động các DAQ list có nội dung cố định — không ALLOC_*, không
    CLEAR_DAQ_LIST, không SET_DAQ_PTR/WRITE_DAQ, vì ODT đã có sẵn nội dung
    do ECU tự định nghĩa. Chỉ SET_DAQ_LIST_MODE + START_STOP_DAQ_LIST(select)
    × n → START_STOP_SYNCH(1).

    Khác `configure_daq()` nhánh static thường (predefined=False), nơi
    master vẫn tự gán signal vào ODT còn trống qua WRITE_DAQ — ở đây master
    hoàn toàn không có cách nào tự dò nội dung một list predefined, nên
    layout phải do caller cung cấp sẵn.

    Raises:
        ValueError: list không thực sự predefined theo GET_DAQ_LIST_INFO,
            hoặc event không cố định (`fixed_event=False`) mà `pl.event` để
            trống.
        NotConnectedError, SlaveError: như các hàm DAQ khác (qua _require_daq
            trong từng lệnh master gọi).
    """
    pid_table: dict[int, PidEntry] = {}

    for pl in lists:
        info = master.get_daq_list_info(pl.daq)
        if not info.predefined:
            raise ValueError(
                f"DAQ list {pl.daq}: GET_DAQ_LIST_INFO báo predefined=False — "
                "dùng configure_daq() thay vì configure_daq_predefined()."
            )
        if info.fixed_event:
            event = info.fixed_event_channel
        elif pl.event is not None:
            event = pl.event
        else:
            raise ValueError(
                f"DAQ list {pl.daq}: event không cố định (fixed_event=False) "
                "nhưng PredefinedDaqList.event=None — phải chỉ định event."
            )

        daq_mode = 0x10 if pl.timestamp else 0x00
        master.set_daq_list_mode(pl.daq, event, daq_mode, pl.prescaler, pl.priority)
        first_pid = master.start_stop_daq_list(mode=2, daq=pl.daq)

        for odt_idx, layouts in enumerate(pl.odts):
            pid_table[first_pid + odt_idx] = PidEntry(
                daq_list=pl.daq,
                odt_index=odt_idx,
                has_timestamp=(odt_idx == 0 and pl.timestamp),
                signals=layouts,
            )

    master.start_stop_synch(mode=1)
    return pid_table


def _write_and_start(
    master: "XcpMaster",
    configs: list[DaqListConfig],
    packed: list[list[list[DaqSignal]]],
    daq_indices: list[int],
    ts_size: int,
) -> dict[int, PidEntry]:
    """SET_DAQ_PTR + WRITE_DAQ → SET_DAQ_LIST_MODE + START_STOP_DAQ_LIST(select)
    × n → START_STOP_SYNCH(1). Dùng chung cho cả hai nhánh dynamic/static.

    `daq_indices[i]` là list vật lý trên ECU dùng cho `configs[i]` — với
    dynamic luôn trùng `i` (mới cấp phát theo thứ tự); với static có thể
    không liền kề `i` (chọn theo dung lượng còn trống).
    """
    # ── SET_DAQ_PTR + WRITE_DAQ (mỗi entry một lần) ─────────────────────────
    for i, odts in enumerate(packed):
        daq_idx = daq_indices[i]
        for odt_idx, odt in enumerate(odts):
            master.set_daq_ptr(daq_idx, odt_idx, 0)
            for sig in odt:
                master.write_daq(0xFF, sig.size, sig.ext, sig.address)

    # ── SET_DAQ_LIST_MODE + START_STOP_DAQ_LIST(select) ─────────────────────
    pid_table: dict[int, PidEntry] = {}

    for i, (cfg, odts) in enumerate(zip(configs, packed)):
        daq_idx = daq_indices[i]
        daq_mode = 0x10 if cfg.timestamp else 0x00   # bit4 = timestamp enable
        master.set_daq_list_mode(daq_idx, cfg.event, daq_mode, cfg.prescaler, cfg.priority)
        first_pid = master.start_stop_daq_list(mode=2, daq=daq_idx)

        for odt_idx, odt in enumerate(odts):
            pid = first_pid + odt_idx
            has_ts = (odt_idx == 0 and cfg.timestamp)
            base = 1 + (ts_size if has_ts else 0)   # byte 0 = PID, bytes 1..ts_size = TS

            layouts: list[OdtSignalLayout] = []
            cur = base
            for sig in odt:
                layouts.append(OdtSignalLayout(signal=sig, frame_offset=cur))
                cur += sig.size

            pid_table[pid] = PidEntry(
                daq_list=daq_idx,
                odt_index=odt_idx,
                has_timestamp=has_ts,
                signals=layouts,
            )

    # ── START_STOP_SYNCH(1) ───────────────────────────────────────────────────
    master.start_stop_synch(mode=1)

    return pid_table


def stop_daq(master: "XcpMaster") -> None:
    """Dừng tất cả DAQ list. Idempotent — gọi khi ECU chưa chạy DAQ cũng không ném."""
    master.start_stop_synch(mode=0)


@dataclass(frozen=True)
class SamplePoint:
    """Một giá trị đo tại một thời điểm, decode từ DTO frame.

    value_raw: bytes thô — UI tự decode theo datatype (UINT16, FLOAT32, ...).
    timestamp_ns: nanosecond tuyệt đối từ khi bắt đầu DAQ (tích lũy qua rollover).
    """
    name: str
    timestamp_ns: int
    value_raw: bytes
    datatype: str


class TimestampAccumulator:
    """Bộ tích lũy timestamp ECU → nanosecond tuyệt đối, bù rollover.

    byte_order: thứ tự byte trong frame DTO — lấy từ SlaveCaps.byte_order.
    width_bits: độ rộng bộ đếm của ECU (8 × ts_size).
    unit_ns, ticks: bộ đếm tăng `ticks` mỗi `unit_ns` ns (theo spec ASAM), nên
        ns = tick_tích_lũy × unit_ns ÷ ticks. Giá trị 0 nghĩa là không hợp lệ →
        `to_ns` trả 0.

    Rollover chỉ được ghi nhận khi giá trị tụt quá NỬA chu kỳ
    (`last − raw > 2^(width_bits−1)`). Bước lùi nhỏ hơn là hai frame đến lệch
    thứ tự (hay gặp khi nhiều DAQ list dùng chung bộ tích lũy): epoch không đổi.

    Giới hạn: nếu hai lần nhận timestamp cách nhau quá một chu kỳ đầy đủ thì
    không phân biệt được; timestamp 1 byte quay vòng rất nhanh nên ít hữu dụng.
    """

    def __init__(self, byte_order: str = "little", width_bits: int = 32,
                 unit_ns: int = 10, ticks: int = 1) -> None:
        self.byte_order = byte_order
        self.width_bits = width_bits
        self.unit_ns = unit_ns
        self.ticks = ticks
        self._last: int | None = None
        self._epoch: int = 0   # số lần tràn × 2^width_bits

    @classmethod
    def from_format(cls, fmt: DtoFormat) -> TimestampAccumulator:
        return cls(
            byte_order=fmt.byte_order,
            width_bits=8 * fmt.ts_size if fmt.ts_size else 32,
            unit_ns=fmt.unit_ns,
            ticks=fmt.ticks,
        )

    def update(self, raw: int) -> int:
        """Nhận giá trị thô của bộ đếm, trả về tick tích lũy (không tràn)."""
        wrap = 1 << self.width_bits
        if (self._last is not None and raw < self._last
                and (self._last - raw) > wrap // 2):
            self._epoch += wrap
        self._last = raw
        return self._epoch + raw

    def to_ns(self, raw: int) -> int:
        """Trả về timestamp tuyệt đối tính bằng nanosecond."""
        total = self.update(raw)
        if self.unit_ns == 0 or self.ticks == 0:
            return 0
        return total * self.unit_ns // self.ticks


def decode_dto(
    frame: bytes,
    pid_table: Mapping[DtoKey, PidEntry],
    ts_accum: TimestampAccumulator,
    fmt: DtoFormat | None = None,
) -> list[SamplePoint]:
    """Decode một DTO frame thành list SamplePoint theo layout `fmt`.

    Chạy trên RX thread: KHÔNG bao giờ raise — frame rỗng, ngắn hơn header,
    hoặc khoá không có trong bảng → `[]`.

    Header theo `fmt.id_type` (xem DtoFormat). Bảng tra khoá bằng PID tuyệt đối
    (kiểu 0) hoặc `(số DAQ list, số ODT)` (kiểu 1–3). Nếu `fmt.overload` là
    "pid_msb", bit 7 của byte đầu là cờ overrun — mask trước khi tra bảng.
    Timestamp chỉ có ở ODT 0 (`has_timestamp=True`), ngay sau header; frame
    ngắn hơn `header + ts_size` thì `timestamp_ns = 0`.
    Frame quá ngắn cho một signal → signal đó bị bỏ qua.
    """
    if fmt is None:
        fmt = DtoFormat()
    header_len = fmt.header_len
    if len(frame) < header_len:
        return []

    first = frame[0]
    odt_or_pid = first & 0x7F if fmt.overload == "pid_msb" else first
    key: DtoKey
    if fmt.id_type == 0:
        key = odt_or_pid
    else:
        if fmt.id_type == 1:
            daq = frame[1]
        elif fmt.id_type == 2:
            daq = int.from_bytes(frame[1:3], fmt.byte_order)
        else:                                   # kiểu 3: frame[1] là byte FILL
            daq = int.from_bytes(frame[2:4], fmt.byte_order)
        key = (daq, odt_or_pid)

    entry = pid_table.get(key)
    if entry is None:
        return []

    ts_ns = 0
    if entry.has_timestamp and fmt.ts_size > 0 and len(frame) >= header_len + fmt.ts_size:
        raw_ts = int.from_bytes(
            frame[header_len:header_len + fmt.ts_size],
            ts_accum.byte_order,  # type: ignore[arg-type]
        )
        ts_ns = ts_accum.to_ns(raw_ts)

    samples: list[SamplePoint] = []
    for layout in entry.signals:
        end = layout.frame_offset + layout.signal.size
        if end > len(frame):
            continue
        samples.append(SamplePoint(
            name=layout.signal.name,
            timestamp_ns=ts_ns,
            value_raw=frame[layout.frame_offset:end],
            datatype=layout.signal.datatype,
        ))
    return samples


def pack_odts(
    signals: list[DaqSignal],
    timestamp_on: bool,
    max_dto: int = 8,
    *,
    fmt: DtoFormat | None = None,
) -> list[list[DaqSignal]]:
    """Nhét signals vào các ODT, tôn trọng ngân sách byte từng ODT.

    Ngân sách tính từ layout DTO của ECU (`fmt`, mặc định `DtoFormat()`):
        first_budget = max_dto − header_len − (ts_size nếu timestamp_on)
        rest_budget  = max_dto − header_len
    Ví dụ CAN 8 B, header 1 B, TS 4 B: ODT 0 = 3 B, ODT 1+ = 7 B.

    Thuật toán: tách signals thành hai nhóm theo first_budget, xử lý ODT 0
    riêng (first-fit-decreasing), sau đó xử lý ODT 1+ (large trước, remaining small).

    Trả về list các ODT; ODT 0 CÓ THỂ RỖNG — không phải lỗi, xảy ra khi tất cả
    signals đều lớn hơn first_budget.

    Raises:
        ValueError: DTO không đủ chỗ cho header (hoặc header + timestamp), hoặc
            một signal lớn hơn rest_budget — không thể nhét vào bất kỳ ODT nào.
    """
    if fmt is None:
        fmt = DtoFormat()
    header = fmt.header_len
    ts = fmt.ts_size if timestamp_on else 0
    rest_budget = max_dto - header
    first_budget = rest_budget - ts
    if rest_budget <= 0:
        raise ValueError(
            f"max_dto={max_dto}B không đủ chỗ cho header DTO {header}B")
    if first_budget < 0:
        raise ValueError(
            f"max_dto={max_dto}B không đủ chỗ cho header {header}B + timestamp {ts}B")

    for s in signals:
        if s.size > rest_budget:
            raise ValueError(
                f"{s.name}: {s.size}B > max {rest_budget}B/ODT — phải tách nhỏ hơn"
            )

    small = sorted([s for s in signals if s.size <= first_budget], key=lambda x: -x.size)
    large = sorted([s for s in signals if s.size > first_budget],  key=lambda x: -x.size)

    # ODT 0 — first-fit-decreasing trong first_budget
    odt0: list[DaqSignal] = []
    used = 0
    in_odt0: set[int] = set()
    for s in small:
        if used + s.size <= first_budget:
            odt0.append(s)
            used += s.size
            in_odt0.add(id(s))

    odts: list[list[DaqSignal]] = [odt0]

    # ODT 1+ — large signals trước (không lọt vào ODT 0), rồi small chưa vào ODT 0
    remaining = large + [s for s in small if id(s) not in in_odt0]
    cur: list[DaqSignal] = []
    used = 0
    for s in remaining:
        if used + s.size > rest_budget:
            odts.append(cur)
            cur, used = [], 0
        cur.append(s)
        used += s.size
    if cur:
        odts.append(cur)

    return odts
