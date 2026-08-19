"""DAQ engine — packing, allocation, DTO decoding.

D4a: DaqSignal + pack_odts()
D4b: DaqListConfig, OdtSignalLayout, PidEntry, configure_daq, stop_daq
D4c: SamplePoint, TimestampAccumulator, decode_dto

Nguyên tắc: không import can, không import PySide6, không import ui/transport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import XcpMaster

__all__ = [
    "DaqSignal", "pack_odts",
    "DaqListConfig", "OdtSignalLayout", "PidEntry",
    "configure_daq", "stop_daq",
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

    Trình tự: FREE_DAQ → ALLOC_* → WRITE_DAQ × n → SET_DAQ_LIST_MODE →
    START_STOP_DAQ_LIST(select) × n → START_STOP_SYNCH(1).

    Raises:
        UnsupportedByEcuError: ECU không có DAQ.
        NotConnectedError: chưa CONNECT.
        SlaveError: ECU từ chối một bước trong chuỗi (sai thứ tự, tràn bộ nhớ...).
    """
    caps = master.caps
    if caps is None:
        from ..session.api import NotConnectedError
        raise NotConnectedError("Chưa CONNECT tới ECU")

    max_dto = caps.max_dto
    ts_size = (caps.daq.timestamp_size if caps.daq else 4)  # byte, thường 4 trên ECU tham chiếu

    # Đóng gói signals vào ODTs theo ngân sách từng ODT
    packed: list[list[list[DaqSignal]]] = [
        pack_odts(cfg.signals, cfg.timestamp, max_dto) for cfg in configs
    ]

    # ── FREE_DAQ ─────────────────────────────────────────────────────────────
    master.free_daq()

    # ── ALLOC_DAQ ────────────────────────────────────────────────────────────
    master.alloc_daq(len(configs))

    # ── ALLOC_ODT (mỗi list một lần) ─────────────────────────────────────────
    for daq_idx, odts in enumerate(packed):
        master.alloc_odt(daq_idx, len(odts))

    # ── ALLOC_ODT_ENTRY (mỗi ODT một lần) ────────────────────────────────────
    for daq_idx, odts in enumerate(packed):
        for odt_idx, odt in enumerate(odts):
            master.alloc_odt_entry(daq_idx, odt_idx, len(odt))

    # ── SET_DAQ_PTR + WRITE_DAQ (mỗi entry một lần) ──────────────────────────
    for daq_idx, odts in enumerate(packed):
        for odt_idx, odt in enumerate(odts):
            master.set_daq_ptr(daq_idx, odt_idx, 0)
            for sig in odt:
                master.write_daq(0xFF, sig.size, sig.ext, sig.address)

    # ── SET_DAQ_LIST_MODE + START_STOP_DAQ_LIST(select) ──────────────────────
    pid_table: dict[int, PidEntry] = {}

    for daq_idx, (cfg, odts) in enumerate(zip(configs, packed)):
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
    """Bộ tích lũy timestamp 32-bit ECU → nanosecond tuyệt đối.

    ECU dùng counter 32-bit, unit 10ns/tick. Rollover xảy ra sau ~42,9 giây.
    Khi `raw < _last`, cộng thêm 2^32 vào epoch để giữ timestamp monotone.

    byte_order: thứ tự byte trong frame DTO — lấy từ SlaveCaps.byte_order.
    """

    def __init__(self, byte_order: str = "little") -> None:
        self.byte_order = byte_order
        self._last: int | None = None
        self._epoch: int = 0   # số lần tràn × 2^32

    def update(self, raw: int) -> int:
        """Nhận giá trị 32-bit thô, trả về tick tích lũy (không tràn)."""
        if self._last is not None and raw < self._last:
            self._epoch += 0x1_0000_0000
        self._last = raw
        return self._epoch + raw

    def to_ns(self, raw: int) -> int:
        """Trả về timestamp tuyệt đối tính bằng nanosecond (unit 10ns/tick)."""
        return self.update(raw) * 10


def decode_dto(
    frame: bytes,
    pid_table: dict[int, PidEntry],
    ts_accum: TimestampAccumulator,
) -> list[SamplePoint]:
    """Decode một DTO frame thành list SamplePoint.

    bit 7 của PID = overrun flag — mask trước khi tra bảng.
    Timestamp chỉ có ở ODT 0 (has_timestamp=True) — 4 byte @ offset 1.
    Frame quá ngắn cho một signal → signal đó bị bỏ qua (không raise).
    """
    if not frame:
        return []
    pid = frame[0] & 0x7F
    entry = pid_table.get(pid)
    if entry is None:
        return []

    ts_ns = 0
    if entry.has_timestamp and len(frame) >= 5:
        raw_ts = int.from_bytes(frame[1:5], ts_accum.byte_order)  # type: ignore[arg-type]
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
) -> list[list[DaqSignal]]:
    """Nhét signals vào các ODT, tôn trọng ngân sách byte từng ODT.

    ODT 0 có ngân sách nhỏ hơn khi timestamp bật (PID 1B + TS 4B = 5B overhead):
        first_budget = max_dto − 1 − (4 if timestamp_on else 0)   # 3 hoặc 7
        rest_budget  = max_dto − 1                                 # luôn 7

    Thuật toán: tách signals thành hai nhóm theo first_budget, xử lý ODT 0
    riêng (first-fit-decreasing), sau đó xử lý ODT 1+ (large trước, remaining small).

    Trả về list các ODT; ODT 0 CÓ THỂ RỖNG — không phải lỗi, xảy ra khi tất cả
    signals đều lớn hơn first_budget.

    Raises:
        ValueError: một signal lớn hơn rest_budget — không thể nhét vào bất kỳ ODT nào.
    """
    first_budget = max_dto - 1 - (4 if timestamp_on else 0)
    rest_budget = max_dto - 1

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
