"""Một node XCP thật trên `virtual` bus — ECU giả cho test backend.

Khác `session/fake.py` (frontend sở hữu, không có bus nào): thứ này nói chuyện
bằng frame CAN thật, nên đường code của `transport/` và `master/` được đi qua
y hệt lúc cắm phần cứng.

Nó cố tình cư xử tệ được — timeout, frame méo, mã lỗi lạ, flood bus — vì đó
chính là thứ làm lộ crash, và slave thật rất khó ép làm.

Mọi đặc tính đều là tham số của `SlaveConfig`: đổi `max_cto=12` ở đây thì
`SlaveCaps.max_cto` mà master đọc được phải đổi theo. Đó là bài test chứng minh
master không hardcode.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

import can

from ..master.constants import TIMESTAMP_UNIT_NS, Cmd, ErrCode
from ..transport.base import round_to_can_fd_dlc

__all__ = ["SlaveConfig", "FakeSlave"]

log = logging.getLogger("xcptool.devtools.fakeslave")

# DAQ_PROPERTIES bit 7-6: cách ECU báo overrun
_OVERLOAD_BITS = {"none": 0x00, "pid_msb": 0x40, "event": 0x80}

REFERENCE_PAGE = 0
WORKING_PAGE = 1


@dataclass
class SlaveConfig:
    """Đặc tính của ECU giả. Test đổi field ở đây để dựng ECU khác."""

    channel: str = "xcptool"
    cro_id: int = 0x600
    dto_id: int = 0x601
    extended_id: bool = False
    is_fd: bool = False
    pad_dlc: bool = True

    max_cto: int = 8
    max_dto: int = 8
    byte_order: str = "little"
    address_granularity: int = 1          # 1 | 2 | 4 byte
    protocol_version: int = 1
    transport_version: int = 1

    supports_cal_pag: bool = True
    supports_daq: bool = True
    supports_stim: bool = False
    supports_pgm: bool = False
    slave_block_mode: bool = False
    optional_cmds: bool = False
    resource_protection: int = 0x00       # ≠0 → master kết luận cần seed & key

    supports_get_status: bool = True
    supports_daq_info: bool = True
    supports_get_id: bool = True
    id_string: str = "fakeslave.a2l"

    # DAQ info — chỉ để capability discovery có thứ để đọc, chưa chạy DAQ thật.
    daq_dynamic: bool = True
    max_daq: int = 2
    max_event_channel: int = 4
    min_daq: int = 0
    pid_off_supported: bool = False
    timestamp_size: int = 4
    timestamp_unit_code: int = 0x1        # 0x1 = 10 ns
    timestamp_ticks: int = 1
    timestamp_supported: bool = True      # bit TIMESTAMP_SUPPORTED trong DAQ_PROPERTIES
    timestamp_fixed: bool = False         # bit TIMESTAMP_FIXED: DTO luôn có timestamp
    id_field_type: int = 0                # 0 absolute | 1 rel+DAQ BYTE | 2 rel+DAQ WORD | 3 WORD aligned
    overload: str = "pid_msb"             # "none" | "pid_msb" | "event"
    granularity_odt_entry_daq: int = 1
    max_odt_entry_size_daq: int = 7

    # Static DAQ (D4d) — chỉ dùng khi daq_dynamic=False. `min_daq` list đầu
    # tiên được cấp sẵn lúc khởi động (không qua ALLOC_*), mỗi list có
    # static_max_odt ODT. Nội dung ODT vẫn ghi được qua SET_DAQ_PTR/WRITE_DAQ
    # — chưa mô phỏng list nội dung cố định hẳn (GET_DAQ_LIST_INFO luôn báo
    # predefined=False).
    static_max_odt: int = 2
    static_max_odt_entries: int = 7

    # Chỉ số list (trong 0..min_daq-1) báo predefined=True qua
    # GET_DAQ_LIST_INFO — nội dung ODT coi như đã "firmware wire sẵn", test
    # tự nạp qua set_predefined_daq_content() thay vì WRITE_DAQ.
    static_predefined_lists: frozenset[int] = frozenset()

    mem_base: int = 0x8000_0000
    mem_size: int = 1024
    # ECU và XCP boot ở Reference page (Flash) — đúng hành vi firmware thật
    ecu_page: int = REFERENCE_PAGE
    xcp_page: int = REFERENCE_PAGE

    # ── nút bấm cư xử tệ ─────────────────────────────────────────────────────
    drop_responses: int = 0
    """Bỏ qua N lệnh tiếp theo — ECU câm để test timeout T1."""

    truncate_responses: int = 0
    """Cắt cụt N response tiếp theo còn 2 byte — test MalformedResponseError."""

    response_delay_s: float = 0.0
    force_error: int | None = None
    """Trả mã lỗi này cho mọi lệnh (trừ CONNECT/SYNCH)."""

    unknown_error_code: int = 0x7F
    """Mã lỗi ngoài spec dùng cho test 'mã lỗi lạ'."""

    daq_flood_hz: float = 0.0
    daq_flood_pid: int = 0x01

    log_commands: bool = False


class FakeSlave:
    """Chạy trong thread riêng. Dùng như context manager."""

    def __init__(self, cfg: SlaveConfig | None = None) -> None:
        self.cfg = cfg or SlaveConfig()
        kwargs: dict[str, object] = {}
        if self.cfg.is_fd:
            kwargs["fd"] = True
        self._bus = can.Bus(
            interface="virtual", channel=self.cfg.channel, receive_own_messages=False, **kwargs)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name="fake-slave", daemon=True)
        self._flood_thread: threading.Thread | None = None

        self.memory = bytearray(self.cfg.mem_size)
        self.reference = bytearray(self.cfg.mem_size)
        self._mta_addr = 0
        self._mta_source = "mem"
        self._id_bytes = self.cfg.id_string.encode("latin-1")
        # Có trần: soak 30 phút gọi hàng trăm nghìn lệnh, một list vô hạn ở đây
        # sẽ hiện ra thành "rò bộ nhớ" trong báo cáo soak — nhưng là rò của đồ
        # test, không phải của sản phẩm. Đủ sâu cho mọi khẳng định trong test.
        self.commands_seen: deque[int] = deque(maxlen=10_000)

        # DAQ state — được reset bởi FREE_DAQ
        # _daq_lists[daq][odt] = list of (bit_offset, size, ext, addr)
        self._daq_lists: list[list[list[tuple[int, int, int, int]]]] = []
        self._daq_modes: list[dict[str, int]] = []
        self._daq_first_pids: list[int] = []
        self._daq_write_pos: tuple[int, int, int] = (0, 0, 0)  # (daq, odt, entry)
        self._daq_next_pid: int = 0
        self.daq_running: bool = False  # public — test kiểm tra trực tiếp
        # public — test assert list nào từng bị WRITE_DAQ dù đang predefined
        # (không nên xảy ra: configure_daq_predefined() không bao giờ ghi)
        self.write_daq_to_predefined: set[int] = set()
        if not self.cfg.daq_dynamic and self.cfg.min_daq > 0:
            self._reset_static_daq_lists()

        # DAQ send thread — gửi DTO frame 100 Hz khi daq_running=True
        self._daq_thread: threading.Thread | None = None
        self._daq_stop: threading.Event = threading.Event()
        self._daq_t0: float = 0.0

    # ── vòng đời ─────────────────────────────────────────────────────────────

    def start(self) -> FakeSlave:
        self._thread.start()
        if self.cfg.daq_flood_hz > 0:
            self._flood_thread = threading.Thread(
                target=self._flood_loop, name="fake-slave-daq", daemon=True)
            self._flood_thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._daq_stop.set()
        for t in (self._thread, self._flood_thread, self._daq_thread):
            if t is not None and t.is_alive():
                t.join(timeout=2.0)
        try:
            self._bus.shutdown()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> FakeSlave:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # ── trợ giúp cho test ────────────────────────────────────────────────────

    def poke(self, addr: int, data: bytes, page: int = WORKING_PAGE) -> None:
        """Đặt sẵn nội dung bộ nhớ, bỏ qua chống ghi."""
        off = addr - self.cfg.mem_base
        buf = self.memory if page == WORKING_PAGE else self.reference
        buf[off:off + len(data)] = data

    def peek(self, addr: int, size: int, page: int = WORKING_PAGE) -> bytes:
        off = addr - self.cfg.mem_base
        buf = self.memory if page == WORKING_PAGE else self.reference
        return bytes(buf[off:off + size])

    def send_raw(self, can_id: int, data: bytes) -> None:
        """Bơm một frame tuỳ ý lên bus — dùng cho test frame lạ / frame méo."""
        self._bus.send(can.Message(
            arbitration_id=can_id, data=bytes(data),
            is_extended_id=self.cfg.extended_id))

    # ── vòng lặp ─────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self._bus.recv(0.05)
            except Exception:  # noqa: BLE001 — ECU giả không được làm sập test
                log.exception("fake slave: lỗi khi nhận")
                return
            if msg is None or msg.arbitration_id != self.cfg.cro_id:
                continue
            try:
                self._handle(bytes(msg.data))
            except Exception:  # noqa: BLE001
                log.exception("fake slave: lỗi khi xử lý lệnh")

    def _flood_loop(self) -> None:
        period = 1.0 / self.cfg.daq_flood_hz
        counter = 0
        next_at = time.perf_counter()
        while not self._stop.is_set():
            now = time.perf_counter()
            if now < next_at:
                time.sleep(min(next_at - now, 0.005))
                continue
            next_at += period
            counter = (counter + 1) & 0xFFFFFFFF
            payload = bytes([self.cfg.daq_flood_pid]) + counter.to_bytes(4, "little") \
                + b"\x00\x00\x00"
            try:
                self._bus.send(can.Message(
                    arbitration_id=self.cfg.dto_id, data=payload,
                    is_extended_id=self.cfg.extended_id))
            except Exception:  # noqa: BLE001
                return

    def _timestamp_ticks(self, elapsed_ns: float) -> int:
        """Giá trị bộ đếm timestamp của ECU giả: tăng `timestamp_ticks` mỗi
        `unit` (theo `timestamp_unit_code`), cắt theo `timestamp_size` byte."""
        unit_ns = TIMESTAMP_UNIT_NS.get(self.cfg.timestamp_unit_code, 0)
        size = self.cfg.timestamp_size
        if unit_ns == 0 or self.cfg.timestamp_ticks == 0 or size == 0:
            return 0
        ticks = int(elapsed_ns * self.cfg.timestamp_ticks / unit_ns)
        return ticks & ((1 << (8 * size)) - 1)

    def _dto_header(self, daq: int, odt_idx: int, first_pid: int) -> bytes:
        """Header identification field của DTO theo `id_field_type`."""
        kind = self.cfg.id_field_type
        if kind == 0:
            return bytes([(first_pid + odt_idx) & 0xFF])
        odt = bytes([odt_idx & 0xFF])
        if kind == 1:
            return odt + bytes([daq & 0xFF])
        word = daq.to_bytes(2, self.cfg.byte_order)  # type: ignore[arg-type]
        if kind == 2:
            return odt + word
        return odt + b"\x00" + word                  # kiểu 3: byte FILL

    def _daq_send_loop(self) -> None:
        """Gửi DTO frame 100 Hz cho mỗi DAQ list đang chạy."""
        period = 0.01   # 10ms = 100 Hz
        next_at = time.perf_counter()
        while not self._daq_stop.is_set() and not self._stop.is_set():
            now = time.perf_counter()
            if now < next_at:
                time.sleep(min(next_at - now, 0.005))
                continue
            next_at += period
            elapsed_ns = (now - self._daq_t0) * 1e9
            self._send_daq_frames(self._timestamp_ticks(elapsed_ns))

    def _send_daq_frames(self, ts_ticks: int) -> None:
        """Đọc bộ nhớ ECU giả, đóng gói frame DTO và gửi lên bus."""
        try:
            snap = list(zip(self._daq_lists, self._daq_modes, self._daq_first_pids))
        except Exception:  # noqa: BLE001
            return
        bo = self.cfg.byte_order
        ts_size = self.cfg.timestamp_size if self.cfg.timestamp_supported else 0
        for daq, (odts, mode_info, first_pid) in enumerate(snap):
            has_ts = ts_size > 0 and (self.cfg.timestamp_fixed
                                      or bool(mode_info.get("mode", 0) & 0x10))
            try:
                odt_list = list(enumerate(odts))
            except Exception:  # noqa: BLE001
                continue
            for odt_idx, entries in odt_list:
                frame = bytearray(self._dto_header(daq, odt_idx, first_pid))
                if odt_idx == 0 and has_ts:
                    frame += ts_ticks.to_bytes(ts_size, bo)  # type: ignore[arg-type]
                for _bit_off, sz, _ext, addr in entries:
                    off = addr - self.cfg.mem_base
                    if 0 <= off and off + sz <= self.cfg.mem_size:
                        frame += self.memory[off:off + sz]
                    else:
                        frame += bytes(sz)
                if self.cfg.is_fd:
                    target_len = round_to_can_fd_dlc(len(frame))
                    if self.cfg.pad_dlc and target_len < 8:
                        target_len = 8
                    if len(frame) < target_len:
                        frame = frame.ljust(target_len, b"\x00")
                    payload = bytes(frame[:self.cfg.max_dto])
                else:
                    if self.cfg.pad_dlc and len(frame) < 8:
                        frame = frame.ljust(8, b"\x00")
                    payload = bytes(frame[:8])
                try:
                    self._bus.send(can.Message(
                        arbitration_id=self.cfg.dto_id, data=payload,
                        is_extended_id=self.cfg.extended_id,
                        is_fd=self.cfg.is_fd,
                        bitrate_switch=self.cfg.is_fd))
                except Exception:  # noqa: BLE001
                    return

    # ── xử lý lệnh ───────────────────────────────────────────────────────────

    def _reply(self, data: bytes) -> None:
        truncated = self.cfg.truncate_responses > 0
        if truncated:
            # Không đệm lại sau khi cắt: một response "ngắn hơn dự kiến" trên CAN
            # nghĩa là DLC nhỏ, đệm đủ 8 byte thì chẳng mô phỏng được gì.
            self.cfg.truncate_responses -= 1
            data = data[:2]
        payload = bytes(data)
        if self.cfg.is_fd:
            max_cap = self.cfg.max_cto
            if self.cfg.pad_dlc and not truncated:
                target_len = round_to_can_fd_dlc(len(payload))
                if target_len < 8:
                    target_len = 8
                if len(payload) < target_len:
                    payload = payload.ljust(target_len, b"\x00")
            payload = payload[:max_cap]
        else:
            if self.cfg.pad_dlc and not truncated and len(payload) < 8:
                payload = payload.ljust(8, b"\x00")
            payload = payload[:8]

        if self.cfg.response_delay_s > 0:
            time.sleep(self.cfg.response_delay_s)
        try:
            self._bus.send(can.Message(
                arbitration_id=self.cfg.dto_id, data=payload,
                is_extended_id=self.cfg.extended_id,
                is_fd=self.cfg.is_fd,
                bitrate_switch=self.cfg.is_fd))
        except Exception:  # noqa: BLE001
            log.exception("fake slave: không gửi được response")

    def _err(self, code: int) -> None:
        self._reply(bytes([0xFE, code]))

    def _u16(self, value: int) -> bytes:
        return value.to_bytes(2, self.cfg.byte_order)  # type: ignore[arg-type]

    def _addr_of(self, data: bytes) -> int:
        return int.from_bytes(data[4:8], self.cfg.byte_order)  # type: ignore[arg-type]

    def _slice(self, addr: int, size: int) -> tuple[int, bytearray] | None:
        off = addr - self.cfg.mem_base
        if off < 0 or off + size > self.cfg.mem_size:
            return None
        buf = self.memory if self.cfg.xcp_page == WORKING_PAGE else self.reference
        return off, buf

    def _handle(self, data: bytes) -> None:
        if not data:
            return
        cmd = data[0]
        self.commands_seen.append(cmd)
        if self.cfg.log_commands:
            log.info("fake slave ← 0x%02X", cmd)

        if self.cfg.drop_responses > 0:
            self.cfg.drop_responses -= 1
            return

        if cmd == Cmd.SYNCH:
            self._err(ErrCode.CMD_SYNCH)
            return

        if self.cfg.force_error is not None and cmd != Cmd.CONNECT:
            self._err(self.cfg.force_error)
            return

        handler = _HANDLERS.get(cmd)
        if handler is None:
            self._err(ErrCode.CMD_UNKNOWN)
            return
        handler(self, data)

    # ── từng lệnh ────────────────────────────────────────────────────────────

    def _cmd_connect(self, data: bytes) -> None:
        c = self.cfg
        resource = ((0x01 if c.supports_cal_pag else 0)
                    | (0x04 if c.supports_daq else 0)
                    | (0x08 if c.supports_stim else 0)
                    | (0x10 if c.supports_pgm else 0))
        gran_bits = {1: 0, 2: 1, 4: 2}.get(c.address_granularity, 0)
        comm_mode = ((0x01 if c.byte_order == "big" else 0)
                     | (gran_bits << 1)
                     | (0x40 if c.slave_block_mode else 0)
                     | (0x80 if c.optional_cmds else 0))
        self._reply(bytes([0xFF, resource, comm_mode, c.max_cto])
                    + self._u16(c.max_dto)
                    + bytes([c.protocol_version, c.transport_version]))

    def _cmd_disconnect(self, data: bytes) -> None:
        self._reply(b"\xff")

    def _cmd_get_status(self, data: bytes) -> None:
        if not self.cfg.supports_get_status:
            self._err(ErrCode.CMD_UNKNOWN)
            return
        self._reply(bytes([0xFF, 0x00, self.cfg.resource_protection, 0x00])
                    + self._u16(0))

    def _cmd_get_id(self, data: bytes) -> None:
        if not self.cfg.supports_get_id:
            self._err(ErrCode.CMD_UNKNOWN)
            return
        self._mta_source = "id"
        self._mta_addr = 0
        length = len(self._id_bytes)
        self._reply(bytes([0xFF, 0x00, 0x00, 0x00])
                    + length.to_bytes(4, self.cfg.byte_order))  # type: ignore[arg-type]

    def _cmd_set_mta(self, data: bytes) -> None:
        if len(data) < 8:
            self._err(ErrCode.CMD_SYNTAX)
            return
        self._mta_source = "mem"
        self._mta_addr = self._addr_of(data)
        self._reply(b"\xff")

    def _cmd_upload(self, data: bytes) -> None:
        if len(data) < 2:
            self._err(ErrCode.CMD_SYNTAX)
            return
        size = data[1]
        if size > self.cfg.max_cto - 1:
            self._err(ErrCode.OUT_OF_RANGE)
            return
        if self._mta_source == "id":
            chunk = self._id_bytes[self._mta_addr:self._mta_addr + size]
            self._mta_addr += len(chunk)
            self._reply(b"\xff" + chunk.ljust(size, b"\x00"))
            return
        got = self._slice(self._mta_addr, size)
        if got is None:
            self._err(ErrCode.OUT_OF_RANGE)
            return
        off, buf = got
        self._mta_addr += size
        self._reply(b"\xff" + bytes(buf[off:off + size]))

    def _cmd_short_upload(self, data: bytes) -> None:
        if len(data) < 8:
            self._err(ErrCode.CMD_SYNTAX)
            return
        size = data[1]
        if size > self.cfg.max_cto - 1:
            self._err(ErrCode.OUT_OF_RANGE)
            return
        got = self._slice(self._addr_of(data), size)
        if got is None:
            self._err(ErrCode.OUT_OF_RANGE)
            return
        off, buf = got
        self._reply(b"\xff" + bytes(buf[off:off + size]))

    def _write(self, addr: int, payload: bytes) -> bool:
        if self.cfg.xcp_page == REFERENCE_PAGE:
            self._err(ErrCode.WRITE_PROTECTED)
            return False
        got = self._slice(addr, len(payload))
        if got is None:
            self._err(ErrCode.OUT_OF_RANGE)
            return False
        off, buf = got
        buf[off:off + len(payload)] = payload
        return True

    def _cmd_download(self, data: bytes) -> None:
        if len(data) < 2:
            self._err(ErrCode.CMD_SYNTAX)
            return
        size = data[1]
        payload = data[2:2 + size]
        if len(payload) < size:
            self._err(ErrCode.CMD_SYNTAX)
            return
        if self._write(self._mta_addr, payload):
            self._mta_addr += size
            self._reply(b"\xff")

    def _cmd_short_download(self, data: bytes) -> None:
        if len(data) < 8:
            self._err(ErrCode.CMD_SYNTAX)
            return
        size = data[1]
        payload = data[8:8 + size]
        if len(payload) < size:
            self._err(ErrCode.CMD_SYNTAX)
            return
        if self._write(self._addr_of(data), payload):
            self._reply(b"\xff")

    def _cmd_get_cal_page(self, data: bytes) -> None:
        if not self.cfg.supports_cal_pag or len(data) < 3:
            self._err(ErrCode.CMD_UNKNOWN)
            return
        mode = data[1]
        page = self.cfg.ecu_page if mode == 0x01 else self.cfg.xcp_page
        self._reply(bytes([0xFF, 0x00, 0x00, page]))

    def _cmd_set_cal_page(self, data: bytes) -> None:
        if not self.cfg.supports_cal_pag or len(data) < 4:
            self._err(ErrCode.CMD_UNKNOWN)
            return
        mode, _segment, page = data[1], data[2], data[3]
        if page not in (WORKING_PAGE, REFERENCE_PAGE):
            self._err(ErrCode.PAGE_NOT_VALID)
            return
        if mode & 0x01:
            self.cfg.ecu_page = page
        if mode & 0x02:
            self.cfg.xcp_page = page
        self._reply(b"\xff")

    def _cmd_copy_cal_page(self, data: bytes) -> None:
        if not self.cfg.supports_cal_pag or len(data) < 5:
            self._err(ErrCode.CMD_UNKNOWN)
            return
        src_page, dst_page = data[2], data[4]
        if dst_page == REFERENCE_PAGE:
            self._err(ErrCode.WRITE_PROTECTED)
            return
        src = self.memory if src_page == WORKING_PAGE else self.reference
        dst = self.memory if dst_page == WORKING_PAGE else self.reference
        dst[:] = src
        self._reply(b"\xff")

    def _cmd_daq_processor_info(self, data: bytes) -> None:
        if not (self.cfg.supports_daq and self.cfg.supports_daq_info):
            self._err(ErrCode.CMD_UNKNOWN)
            return
        properties = ((0x01 if self.cfg.daq_dynamic else 0)
                      | (0x10 if self.cfg.timestamp_supported else 0)
                      | (0x20 if self.cfg.pid_off_supported else 0)
                      | _OVERLOAD_BITS[self.cfg.overload])
        key_byte = (self.cfg.id_field_type & 0x03) << 6
        self._reply(bytes([0xFF, properties])
                    + self._u16(self.cfg.max_daq)
                    + self._u16(self.cfg.max_event_channel)
                    + bytes([self.cfg.min_daq, key_byte]))

    def daq_entries(self, daq: int, odt: int) -> list[tuple[int, int, int, int]]:
        """Trả về list entries (bit_off, sz, ext, addr) đã ghi qua WRITE_DAQ — cho test."""
        try:
            return list(self._daq_lists[daq][odt])
        except IndexError:
            return []

    def _reset_static_daq_lists(self) -> None:
        """Dựng lại `min_daq` list cố định — gọi lúc khởi động (ECU static
        không có ALLOC_* để tự dựng, nên phải có sẵn từ đầu)."""
        n = self.cfg.min_daq
        self._daq_lists = [[[] for _ in range(self.cfg.static_max_odt)] for _ in range(n)]
        self._daq_modes = [{"event": 0, "mode": 0, "prescaler": 1, "prio": 0}
                           for _ in range(n)]
        self._daq_first_pids = [0] * n

    def set_predefined_daq_content(
        self, daq: int, odt: int, entries: list[tuple[int, int, int, int]]
    ) -> None:
        """Test helper — mô phỏng ODT nội dung cố định do "firmware" đã wire
        sẵn cho một list trong `static_predefined_lists`, không qua WRITE_DAQ.

        `entries`: cùng định dạng (bit_off, size, ext, addr) như `daq_entries()`.
        """
        self._daq_lists[daq][odt] = list(entries)

    def _cmd_free_daq(self, data: bytes) -> None:
        if not self.cfg.daq_dynamic:
            self._err(ErrCode.CMD_UNKNOWN)
            return
        self._daq_stop.set()   # ngừng thread nếu đang chạy
        self._daq_lists = []
        self._daq_modes = []
        self._daq_first_pids = []
        self._daq_next_pid = 0
        self._daq_write_pos = (0, 0, 0)
        self.daq_running = False
        self._reply(b"\xff")

    def _cmd_alloc_daq(self, data: bytes) -> None:
        if not self.cfg.daq_dynamic:
            self._err(ErrCode.CMD_UNKNOWN)
            return
        if len(data) < 4:
            self._err(ErrCode.CMD_SYNTAX)
            return
        count = int.from_bytes(data[2:4], self.cfg.byte_order)  # type: ignore[arg-type]
        self._daq_lists = [[] for _ in range(count)]
        self._daq_modes = [{"event": 0, "mode": 0, "prescaler": 1, "prio": 0}
                           for _ in range(count)]
        self._daq_first_pids = [0] * count
        self._reply(b"\xff")

    def _cmd_alloc_odt(self, data: bytes) -> None:
        if not self.cfg.daq_dynamic:
            self._err(ErrCode.CMD_UNKNOWN)
            return
        if len(data) < 5:
            self._err(ErrCode.CMD_SYNTAX)
            return
        daq = int.from_bytes(data[2:4], self.cfg.byte_order)  # type: ignore[arg-type]
        count = data[4]
        if daq >= len(self._daq_lists):
            self._err(ErrCode.OUT_OF_RANGE)
            return
        self._daq_lists[daq] = [[] for _ in range(count)]
        self._reply(b"\xff")

    def _cmd_alloc_odt_entry(self, data: bytes) -> None:
        if not self.cfg.daq_dynamic:
            self._err(ErrCode.CMD_UNKNOWN)
            return
        if len(data) < 6:
            self._err(ErrCode.CMD_SYNTAX)
            return
        daq = int.from_bytes(data[2:4], self.cfg.byte_order)  # type: ignore[arg-type]
        # Phần body chỉ kiểm tra bounds; entries tự WRITE_DAQ điền.
        if daq >= len(self._daq_lists):
            self._err(ErrCode.OUT_OF_RANGE)
            return
        self._reply(b"\xff")

    def _cmd_clear_daq_list(self, data: bytes) -> None:
        if len(data) < 4:
            self._err(ErrCode.CMD_SYNTAX)
            return
        daq = int.from_bytes(data[2:4], self.cfg.byte_order)  # type: ignore[arg-type]
        if daq >= len(self._daq_lists):
            self._err(ErrCode.OUT_OF_RANGE)
            return
        self._daq_lists[daq] = [[] for _ in range(len(self._daq_lists[daq]))]
        self._reply(b"\xff")

    def _cmd_daq_list_info(self, data: bytes) -> None:
        if not (self.cfg.supports_daq and self.cfg.supports_daq_info):
            self._err(ErrCode.CMD_UNKNOWN)
            return
        if len(data) < 4:
            self._err(ErrCode.CMD_SYNTAX)
            return
        daq = int.from_bytes(data[2:4], self.cfg.byte_order)  # type: ignore[arg-type]
        if daq >= len(self._daq_lists):
            self._err(ErrCode.OUT_OF_RANGE)
            return
        # bit0 PREDEFINED theo static_predefined_lists. bit2 = DAQ-capable.
        # FIXED_EVENT (bit1) chưa mô phỏng — event luôn tự chọn được qua
        # SET_DAQ_LIST_MODE, kể cả với list predefined.
        predefined = daq in self.cfg.static_predefined_lists
        properties = (0x01 if predefined else 0x00) | 0x04
        self._reply(bytes([0xFF, properties, len(self._daq_lists[daq]),
                            self.cfg.static_max_odt_entries])
                    + self._u16(0))

    def _cmd_daq_event_info(self, data: bytes) -> None:
        if not (self.cfg.supports_daq and self.cfg.supports_daq_info):
            self._err(ErrCode.CMD_UNKNOWN)
            return
        if len(data) < 4:
            self._err(ErrCode.CMD_SYNTAX)
            return
        event = int.from_bytes(data[2:4], self.cfg.byte_order)  # type: ignore[arg-type]
        if event >= self.cfg.max_event_channel:
            self._err(ErrCode.OUT_OF_RANGE)
            return
        # properties bit2 = DAQ hỗ trợ. MAX_DAQ_LIST=0xFF = không giới hạn
        # trong fake. Không mô phỏng tên/cycle/priority thật — trả 0.
        self._reply(bytes([0xFF, 0x04, 0xFF, 0x00, 0x00, 0x00, 0x00]))

    def _cmd_set_daq_ptr(self, data: bytes) -> None:
        if len(data) < 6:
            self._err(ErrCode.CMD_SYNTAX)
            return
        daq = int.from_bytes(data[2:4], self.cfg.byte_order)  # type: ignore[arg-type]
        odt, entry = data[4], data[5]
        self._daq_write_pos = (daq, odt, entry)
        self._reply(b"\xff")

    def _cmd_write_daq(self, data: bytes) -> None:
        if len(data) < 8:
            self._err(ErrCode.CMD_SYNTAX)
            return
        bit_off, sz, ext = data[1], data[2], data[3]
        addr = int.from_bytes(data[4:8], self.cfg.byte_order)  # type: ignore[arg-type]
        daq, odt, entry = self._daq_write_pos
        if daq >= len(self._daq_lists) or odt >= len(self._daq_lists[daq]):
            self._err(ErrCode.OUT_OF_RANGE)
            return
        if daq in self.cfg.static_predefined_lists:
            # Không hard-reject (chưa rõ ECU thật trả mã lỗi gì cho case này)
            # — chỉ ghi nhận để test assert master không bao giờ thử ghi vào
            # list predefined.
            self.write_daq_to_predefined.add(daq)
        entries = self._daq_lists[daq][odt]
        # Điền hoặc thay thế tại vị trí entry, tự mở rộng nếu cần.
        while len(entries) <= entry:
            entries.append((0, 0, 0, 0))
        entries[entry] = (bit_off, sz, ext, addr)
        self._daq_write_pos = (daq, odt, entry + 1)
        self._reply(b"\xff")

    def _cmd_set_daq_list_mode(self, data: bytes) -> None:
        if len(data) < 8:
            self._err(ErrCode.CMD_SYNTAX)
            return
        mode = data[1]
        daq = int.from_bytes(data[2:4], self.cfg.byte_order)  # type: ignore[arg-type]
        event = int.from_bytes(data[4:6], self.cfg.byte_order)  # type: ignore[arg-type]
        prescaler, prio = data[6], data[7]
        if daq >= len(self._daq_lists):
            self._err(ErrCode.OUT_OF_RANGE)
            return
        if (self.cfg.timestamp_fixed and self.cfg.timestamp_supported
                and not (mode & 0x10)):
            # Spec: TIMESTAMP_FIXED thì master không được tắt timestamp.
            self._err(ErrCode.CMD_SYNTAX)
            return
        self._daq_modes[daq] = {"event": event, "mode": mode,
                                 "prescaler": prescaler, "prio": prio}
        self._reply(b"\xff")

    def _cmd_start_stop_daq_list(self, data: bytes) -> None:
        if len(data) < 4:
            self._err(ErrCode.CMD_SYNTAX)
            return
        mode = data[1]  # 0=stop, 1=start, 2=select
        daq = int.from_bytes(data[2:4], self.cfg.byte_order)  # type: ignore[arg-type]
        if daq >= len(self._daq_lists):
            self._err(ErrCode.OUT_OF_RANGE)
            return
        if mode == 2:  # select — assign firstPid
            first_pid = self._daq_next_pid
            self._daq_first_pids[daq] = first_pid
            self._daq_next_pid += len(self._daq_lists[daq])
            self._reply(bytes([0xFF, first_pid]))
        else:
            self._reply(b"\xff")

    def _cmd_start_stop_synch(self, data: bytes) -> None:
        if len(data) < 2:
            self._err(ErrCode.CMD_SYNTAX)
            return
        mode = data[1]
        self.daq_running = mode == 1
        if mode == 1:
            # Trả lời TRƯỚC khi khởi động thread gửi DAQ — nếu làm ngược lại,
            # thread gửi ngay frame đầu tiên (next_at = perf_counter() lúc
            # start, không có độ trễ ban đầu) và có thể lên bus trước cả RES
            # của chính START_STOP_SYNCH này, khiến Trace CAN đọc rất khó hiểu
            # (bug user báo cáo qua screenshot: 2 frame DAQ đến trước RES).
            self._daq_stop.clear()
            self._daq_t0 = time.perf_counter()
            self._reply(b"\xff")
            self._daq_thread = threading.Thread(
                target=self._daq_send_loop, name="fake-slave-daq-tx", daemon=True)
            self._daq_thread.start()
        else:
            self._daq_stop.set()
            self._reply(b"\xff")

    def _cmd_daq_resolution_info(self, data: bytes) -> None:
        if not (self.cfg.supports_daq and self.cfg.supports_daq_info):
            self._err(ErrCode.CMD_UNKNOWN)
            return
        ts_mode = ((self.cfg.timestamp_size & 0x07)
                   | (0x08 if self.cfg.timestamp_fixed else 0)
                   | ((self.cfg.timestamp_unit_code & 0x0F) << 4))
        self._reply(bytes([0xFF,
                           self.cfg.granularity_odt_entry_daq,
                           self.cfg.max_odt_entry_size_daq,
                           0x01, 0x00, ts_mode])
                    + self._u16(self.cfg.timestamp_ticks))


_HANDLERS = {
    int(Cmd.CONNECT): FakeSlave._cmd_connect,
    int(Cmd.DISCONNECT): FakeSlave._cmd_disconnect,
    int(Cmd.GET_STATUS): FakeSlave._cmd_get_status,
    int(Cmd.GET_ID): FakeSlave._cmd_get_id,
    int(Cmd.SET_MTA): FakeSlave._cmd_set_mta,
    int(Cmd.UPLOAD): FakeSlave._cmd_upload,
    int(Cmd.SHORT_UPLOAD): FakeSlave._cmd_short_upload,
    int(Cmd.DOWNLOAD): FakeSlave._cmd_download,
    int(Cmd.SHORT_DOWNLOAD): FakeSlave._cmd_short_download,
    int(Cmd.GET_CAL_PAGE): FakeSlave._cmd_get_cal_page,
    int(Cmd.SET_CAL_PAGE): FakeSlave._cmd_set_cal_page,
    int(Cmd.COPY_CAL_PAGE): FakeSlave._cmd_copy_cal_page,
    int(Cmd.GET_DAQ_PROCESSOR_INFO): FakeSlave._cmd_daq_processor_info,
    int(Cmd.GET_DAQ_RESOLUTION_INFO): FakeSlave._cmd_daq_resolution_info,
    int(Cmd.GET_DAQ_LIST_INFO): FakeSlave._cmd_daq_list_info,
    int(Cmd.GET_DAQ_EVENT_INFO): FakeSlave._cmd_daq_event_info,
    # DAQ allocation (D4b) — chỉ ECU dynamic mới chấp nhận
    int(Cmd.FREE_DAQ): FakeSlave._cmd_free_daq,
    int(Cmd.ALLOC_DAQ): FakeSlave._cmd_alloc_daq,
    int(Cmd.ALLOC_ODT): FakeSlave._cmd_alloc_odt,
    int(Cmd.ALLOC_ODT_ENTRY): FakeSlave._cmd_alloc_odt_entry,
    # Static DAQ (D4d)
    int(Cmd.CLEAR_DAQ_LIST): FakeSlave._cmd_clear_daq_list,
    int(Cmd.SET_DAQ_PTR): FakeSlave._cmd_set_daq_ptr,
    int(Cmd.WRITE_DAQ): FakeSlave._cmd_write_daq,
    int(Cmd.SET_DAQ_LIST_MODE): FakeSlave._cmd_set_daq_list_mode,
    int(Cmd.START_STOP_DAQ_LIST): FakeSlave._cmd_start_stop_daq_list,
    int(Cmd.START_STOP_SYNCH): FakeSlave._cmd_start_stop_synch,
}
