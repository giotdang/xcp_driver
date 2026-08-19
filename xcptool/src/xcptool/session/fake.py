"""FakeSession — hiện thực `Session` bằng Python thuần, không có bus nào.

Cho phép toàn bộ GUI và CLI phát triển + test mà không cần python-can, không
cần ECU, không cần backend. Cũng là nơi mô phỏng các tình huống tồi (trễ,
timeout, response méo, rút dây giữa chừng, flood bus) để chứng minh app không
crash — xem `FakeBehavior`.

Không import: can, PySide6, xcptool.master, xcptool.transport (test ranh giới ép).
"""

from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from ..a2l import A2LDatabase
from ..a2l import load as _a2l_load
from .api import (
    BusConfig,
    BusError,
    BusyError,
    ConnState,
    DaqCaps,
    DaqList,
    DeviceInfo,
    MalformedResponseError,
    NotConnectedError,
    OutOfRangeError,
    PageMode,
    SamplePoint,
    SlaveCaps,
    SlaveError,
    TraceEntry,
    UnsupportedByEcuError,
    WriteProtectedError,
)

__all__ = ["FakeBehavior", "FakeSession", "MEM_BASE", "MEM_SIZE"]


# Vùng nhớ mà ECU giả này chấp nhận. Không phải hằng số của một ECU thật —
# chỉ là "bản đồ" của bản giả, để địa chỉ ngoài vùng có gì đó để từ chối.
# Đủ lớn để phủ luôn vùng CHARACTERISTIC của examples/xcp_daq_example.a2l
# (0x80100000..0x80100094) — nếu không, "Đọc tất cả" ở panel Hiệu chỉnh sẽ
# ăn OutOfRangeError ngay từ _check_range(), trước cả khi có frame lên bus.
MEM_BASE = 0x8000_0000
MEM_SIZE = 0x20_0000

WORKING_PAGE = 0
REFERENCE_PAGE = 1
SEGMENT_COUNT = 1
PAGE_COUNT = 2

# Mã lệnh XCP dùng để dựng chuỗi `decoded` và trả lời `raw_command`.
_CMD_NAMES = {
    0xFF: "CONNECT",
    0xFE: "DISCONNECT",
    0xFD: "GET_STATUS",
    0xFC: "SYNCH",
    0xFA: "GET_ID",
    0xF6: "SET_MTA",
    0xF5: "UPLOAD",
    0xF4: "SHORT_UPLOAD",
    0xF0: "DOWNLOAD",
    0xED: "SHORT_DOWNLOAD",
    0xEB: "SET_CAL_PAGE",
    0xEA: "GET_CAL_PAGE",
    0xE4: "COPY_CAL_PAGE",
}

# Mã lỗi theo XCP 1.0 §Error codes.
ERR_CMD_UNKNOWN = 0x20
ERR_OUT_OF_RANGE = 0x22
ERR_WRITE_PROTECTED = 0x23
ERR_SEQUENCE = 0x29

_ERR_NAMES = {
    0x00: ("CRC_CMD_SYNCH", "Đồng bộ lại sau lỗi"),
    0x10: ("CRC_CMD_BUSY", "ECU đang bận"),
    ERR_CMD_UNKNOWN: ("CRC_CMD_UNKNOWN", "ECU không biết lệnh này"),
    0x21: ("CRC_CMD_SYNTAX", "Cú pháp lệnh sai"),
    ERR_OUT_OF_RANGE: ("CRC_OUT_OF_RANGE", "Địa chỉ hoặc tham số ngoài vùng cho phép"),
    ERR_WRITE_PROTECTED: ("CRC_WRITE_PROTECTED", "Vùng nhớ đang được bảo vệ ghi"),
    0x24: ("CRC_ACCESS_DENIED", "Truy cập bị từ chối"),
    0x25: ("CRC_ACCESS_LOCKED", "Cần seed & key để mở khoá"),
    ERR_SEQUENCE: ("CRC_SEQUENCE", "Lệnh sai thứ tự"),
}


def _hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def _default_byte(addr: int) -> int:
    """Nội dung mặc định của một byte — hàm thuần, để hex dump nhìn có nghĩa
    và để đọc lại hai lần cho cùng kết quả.

    KHÔNG phụ thuộc vào số trang: giống firmware thật, Working (RAM) và
    Reference (ROM) có cùng giá trị mặc định cho tới khi Working bị ghi đè
    (khởi động: XcpCal_InitWorkingPage() = memcpy(calRAM, calROM) — xem
    CLAUDE.md). Trước đây hàm này trộn số trang vào hash nên hai trang luôn
    khác nhau kể cả chưa ai ghi gì — làm "Copy Ref → Working" trông như
    không hoạt động vì đọc lại Working sau copy vẫn ra giá trị khác Reference.
    """
    x = (addr * 2654435761) & 0xFFFF_FFFF
    return (x >> 13) & 0xFF


@dataclass
class FakeBehavior:
    """Cấu hình hành vi của bản giả. Test chỉnh trực tiếp các trường này."""

    connect_delay_s: float = 0.0
    list_devices_delay_s: float = 0.0
    command_delay_s: float = 0.0

    # Ném lỗi thay vì trả kết quả
    connect_error: BaseException | None = None
    read_error: BaseException | None = None
    write_error: BaseException | None = None

    # Sau bao nhiêu lệnh thì "rút dây": state = ERROR và mọi lệnh sau đều BusError
    fail_after_commands: int | None = None

    # Response méo cho raw_command (dùng để chứng minh app không vỡ)
    malformed_responses: bool = False

    # ECU không hỗ trợ CAL/PAG → get_page/set_page ném UnsupportedByEcuError
    supports_cal_pag: bool = True
    supports_daq: bool = True
    needs_seed_and_key: bool = False

    max_cto: int = 8
    max_dto: int = 8

    trace_capacity: int = 10_000


class FakeSession:
    """Bản giả của `Session`. Chữ ký khớp `session.api.Session`."""

    def __init__(self, behavior: FakeBehavior | None = None) -> None:
        self.behavior = behavior or FakeBehavior()

        self._state = ConnState.DISCONNECTED
        self._caps: SlaveCaps | None = None
        self._cfg: BusConfig | None = None

        self._trace: deque[TraceEntry] = deque(maxlen=self.behavior.trace_capacity)
        self._trace_lock = threading.Lock()
        self._dropped = 0
        self._seq = itertools.count(1)

        self._cmd_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._closed = threading.Event()
        self._command_count = 0

        # bộ nhớ: ghi đè lên giá trị mặc định, tách riêng theo trang
        self._mem: dict[int, dict[int, int]] = {WORKING_PAGE: {}, REFERENCE_PAGE: {}}
        self._ecu_page = WORKING_PAGE
        self._xcp_page = WORKING_PAGE

        self._flood_thread: threading.Thread | None = None
        self._flood_stop = threading.Event()

        self._a2l_db: A2LDatabase = A2LDatabase()

        # DAQ stub state — FakeSession giả lập DAQ không có bus thật
        self._daq_running: bool = False
        self._daq_ring: deque[SamplePoint] = deque(maxlen=10_000)

    # ── nhóm không chặn, an toàn thread ──────────────────────────────────────

    @property
    def state(self) -> ConnState:
        return self._state

    @property
    def caps(self) -> SlaveCaps | None:
        return self._caps

    @property
    def dropped_frames(self) -> int:
        return self._dropped

    def load_config(self) -> BusConfig:
        """Cấu hình của lần `connect()` gần nhất trong tiến trình, hoặc mặc định.

        Không có bus/file thật đứng sau — FakeSession không cần bền qua lần
        chạy khác, chỉ cần đúng hành vi "nhớ trong phiên" để UI test được.
        """
        return self._cfg or BusConfig(backend="virtual", channel="fake0")

    @property
    def symbols(self) -> A2LDatabase:
        return self._a2l_db

    def drain_trace(self, max_items: int = 5000) -> list[TraceEntry]:
        with self._trace_lock:
            n = min(max_items, len(self._trace))
            return [self._trace.popleft() for _ in range(n)]

    # ── vòng đời ─────────────────────────────────────────────────────────────

    def list_devices(self) -> list[DeviceInfo]:
        self._sleep(self.behavior.list_devices_delay_s)
        return [
            DeviceInfo(
                backend="virtual",
                channel="fake0",
                display_name="Bus giả lập (không cần phần cứng)",
                available=True,
            ),
            DeviceInfo(
                backend="virtual",
                channel="fake1",
                display_name="Bus giả lập #2",
                available=True,
            ),
            DeviceInfo(
                backend="pcan",
                channel="PCAN_USBBUS1",
                display_name="PEAK PCAN-USB (chưa có driver)",
                available=False,
                hint="Cần cài PCAN-Basic driver của PEAK System",
                serial="FAKE-0001",
            ),
            DeviceInfo(
                backend="vector",
                channel="0",
                display_name="Vector VN1610 (chưa có driver)",
                available=False,
                hint="Cần cài Vector XL Driver Library",
            ),
            DeviceInfo(
                backend="slcan",
                channel="COM3",
                display_name="CANable / slcan trên COM3",
                available=False,
                hint="Cần cài gói pyserial và driver COM ảo",
            ),
        ]

    def connect(self, cfg: BusConfig) -> SlaveCaps:
        if self.behavior.connect_error is not None:
            self._set_state(ConnState.ERROR)
            raise self.behavior.connect_error

        self._closed.clear()
        self._set_state(ConnState.CONNECTING)
        self._cfg = cfg

        try:
            self._sleep_interruptible(self.behavior.connect_delay_s)
        except BusError:
            self._set_state(ConnState.DISCONNECTED)
            raise

        self._emit(cfg.cro_id, "tx", bytes([0xFF, 0x00]), "cmd", "CONNECT mode=0")
        res = bytes([0xFF, self._resource_byte(), 0x01,
                     self.behavior.max_cto,
                     self.behavior.max_dto & 0xFF, self.behavior.max_dto >> 8,
                     0x01, 0x01])
        self._emit(cfg.dto_id, "rx", res, "res",
                   f"CONNECT ok maxCto={self.behavior.max_cto} maxDto={self.behavior.max_dto}")

        caps = SlaveCaps(
            max_cto=self.behavior.max_cto,
            max_dto=self.behavior.max_dto,
            byte_order="little",
            address_granularity=1,
            protocol_version=(1, 0),
            transport_version=(1, 0),
            supports_cal_pag=self.behavior.supports_cal_pag,
            supports_daq=self.behavior.supports_daq,
            supports_stim=False,
            supports_pgm=False,
            needs_seed_and_key=self.behavior.needs_seed_and_key,
            slave_block_mode=False,
            optional_cmds=False,
            daq=DaqCaps(
                max_daq=2,
                max_event_channel=2,
                min_daq=0,
                dynamic_daq=True,
                timestamp_supported=True,
                timestamp_size=4,
                timestamp_unit_ns=10,
                timestamp_ticks=1,
                pid_off_supported=False,
                granularity_odt_entry_daq=1,
                max_odt_entry_size_daq=7,
            ) if self.behavior.supports_daq else None,
            id_string="FakeECU (xcptool FakeSession)",
        )
        self._caps = caps
        self._set_state(ConnState.CONNECTED)
        return caps

    def disconnect(self) -> None:
        if self._state is not ConnState.CONNECTED:
            self._set_state(ConnState.DISCONNECTED)
            return
        cfg = self._cfg
        if cfg is not None:
            self._emit(cfg.cro_id, "tx", bytes([0xFE]), "cmd", "DISCONNECT")
            self._emit(cfg.dto_id, "rx", bytes([0xFF]), "res", "DISCONNECT ok")
        self._set_state(ConnState.DISCONNECTED)

    def close(self) -> None:
        """IDEMPOTENT, KHÔNG BAO GIỜ NÉM."""
        try:
            self._closed.set()
            self.stop_flood()
            try:
                self.disconnect()
            except Exception:  # noqa: BLE001 — close() không được để lọt gì ra
                pass
            self._set_state(ConnState.DISCONNECTED)
            self._caps = None
        except Exception:  # noqa: BLE001
            pass

    # ── bộ nhớ ───────────────────────────────────────────────────────────────

    def read(self, addr: int, size: int, ext: int = 0) -> bytes:
        with self._command("READ"):
            if self.behavior.read_error is not None:
                raise self.behavior.read_error
            self._check_range(addr, size)
            page = self._xcp_page
            overrides = self._mem[page]
            out = bytes(
                overrides.get(a, _default_byte(a))
                for a in range(addr, addr + size)
            )
            cfg = self._cfg
            assert cfg is not None
            self._emit(cfg.cro_id, "tx", bytes([0xF4, size, 0, ext]) + addr.to_bytes(4, "little"),
                       "cmd", f"SHORT_UPLOAD addr=0x{addr:08X} size={size}")
            self._emit(cfg.dto_id, "rx", bytes([0xFF]) + out[:7], "res",
                       f"UPLOAD {_hex(out[:7])}{' …' if size > 7 else ''}")
            return out

    def write(self, addr: int, data: bytes, ext: int = 0) -> None:
        with self._command("WRITE"):
            if self.behavior.write_error is not None:
                raise self.behavior.write_error
            self._check_range(addr, len(data))
            cfg = self._cfg
            assert cfg is not None
            self._emit(cfg.cro_id, "tx",
                       bytes([0xED, len(data), 0, ext]) + addr.to_bytes(4, "little"),
                       "cmd", f"SHORT_DOWNLOAD addr=0x{addr:08X} size={len(data)}")
            if self._xcp_page == REFERENCE_PAGE:
                self._emit(cfg.dto_id, "rx", bytes([0xFE, ERR_WRITE_PROTECTED]), "err",
                           "ERR CRC_WRITE_PROTECTED")
                raise WriteProtectedError(
                    ERR_WRITE_PROTECTED,
                    "CRC_WRITE_PROTECTED",
                    "XCP đang trỏ vào reference page (ROM) nên không ghi được",
                )
            page = self._xcp_page
            for i, b in enumerate(data):
                self._mem[page][addr + i] = b
            self._emit(cfg.dto_id, "rx", bytes([0xFF]), "res", "DOWNLOAD ok")

    # ── trang calibration ────────────────────────────────────────────────────

    def get_page(self, segment: int, mode: PageMode) -> int:
        with self._command("GET_CAL_PAGE"):
            self._need_cal_pag()
            self._check_segment(segment)
            cfg = self._cfg
            assert cfg is not None
            self._emit(cfg.cro_id, "tx", bytes([0xEA, mode.value, segment]), "cmd",
                       f"GET_CAL_PAGE seg={segment} mode={mode.name}")
            page = self._ecu_page if mode is PageMode.ECU else self._xcp_page
            self._emit(cfg.dto_id, "rx", bytes([0xFF, 0, 0, page]), "res",
                       f"GET_CAL_PAGE → {page}")
            return page

    def set_page(self, segment: int, page: int, mode: PageMode) -> None:
        with self._command("SET_CAL_PAGE"):
            self._need_cal_pag()
            self._check_segment(segment)
            self._check_page(page)
            cfg = self._cfg
            assert cfg is not None
            self._emit(cfg.cro_id, "tx", bytes([0xEB, mode.value, segment, page]), "cmd",
                       f"SET_CAL_PAGE seg={segment} page={page} mode={mode.name}")
            if mode is PageMode.ECU:
                self._ecu_page = page
            else:
                self._xcp_page = page
            self._emit(cfg.dto_id, "rx", bytes([0xFF]), "res", "SET_CAL_PAGE ok")

    def copy_page(
        self, src_segment: int, src_page: int, dst_segment: int, dst_page: int
    ) -> None:
        with self._command("COPY_CAL_PAGE"):
            self._need_cal_pag()
            for seg in (src_segment, dst_segment):
                self._check_segment(seg)
            for pg in (src_page, dst_page):
                self._check_page(pg)
            cfg = self._cfg
            assert cfg is not None
            self._emit(cfg.cro_id, "tx",
                       bytes([0xE4, src_segment, src_page, dst_segment, dst_page]),
                       "cmd",
                       f"COPY_CAL_PAGE {src_segment}:{src_page} → {dst_segment}:{dst_page}")
            if dst_page == REFERENCE_PAGE:
                self._emit(cfg.dto_id, "rx", bytes([0xFE, ERR_WRITE_PROTECTED]), "err",
                           "ERR CRC_WRITE_PROTECTED")
                raise WriteProtectedError(
                    ERR_WRITE_PROTECTED,
                    "CRC_WRITE_PROTECTED",
                    "Không copy được vào reference page (ROM)",
                )
            self._mem[dst_page] = dict(self._mem[src_page])
            self._emit(cfg.dto_id, "rx", bytes([0xFF]), "res", "COPY_CAL_PAGE ok")

    # ── A2L ──────────────────────────────────────────────────────────────────

    def load_a2l(self, path: str | Path) -> None:
        self._a2l_db = _a2l_load(path)

    # ── DAQ (stub) ───────────────────────────────────────────────────────────

    def start_daq(self, lists: list[DaqList]) -> None:
        """Stub — ghi nhận trạng thái; không phát frame thật."""
        with self._command("START_DAQ"):
            if not self.behavior.supports_daq:
                raise UnsupportedByEcuError("DAQ")
            self._daq_running = True
            self._daq_ring.clear()
            cfg = self._cfg
            if cfg:
                self._emit(cfg.cro_id, "tx", bytes([0xB6, 0x00]), "cmd",
                           f"START_DAQ {len(lists)} list(s)")
                self._emit(cfg.dto_id, "rx", bytes([0xFF]), "res", "START_DAQ ok")

    def stop_daq(self) -> None:
        """Stub — đặt trạng thái về không chạy."""
        with self._command("STOP_DAQ"):
            self._daq_running = False
            cfg = self._cfg
            if cfg:
                self._emit(cfg.cro_id, "tx", bytes([0xDD, 0x00]), "cmd", "STOP_DAQ")
                self._emit(cfg.dto_id, "rx", bytes([0xFF]), "res", "STOP_DAQ ok")

    def drain_daq(self, n: int = 1000) -> list[SamplePoint]:
        """Stub — trả list rỗng (FakeSession không phát frame thật)."""
        count = min(n, len(self._daq_ring))
        return [self._daq_ring.popleft() for _ in range(count)]

    # ── lệnh thô ─────────────────────────────────────────────────────────────

    def raw_command(self, payload: bytes, raise_on_error: bool = False) -> bytes:
        with self._command("RAW"):
            if not payload:
                raise MalformedResponseError("Lệnh rỗng — cần ít nhất một byte mã lệnh")
            cfg = self._cfg
            assert cfg is not None
            pid = payload[0]
            name = _CMD_NAMES.get(pid, f"CMD 0x{pid:02X}")
            self._emit(cfg.cro_id, "tx", payload, "cmd", f"{name} {_hex(payload[1:])}".strip())

            res = self._fake_response(pid, payload)
            kind = "err" if res[0] == 0xFE else "res"
            if kind == "err":
                err_name, err_desc = _ERR_NAMES.get(
                    res[1], (f"CRC_0x{res[1]:02X}", "Mã lỗi không có trong từ điển")
                )
                decoded = f"ERR {err_name}"
            else:
                decoded = f"{name} → {_hex(res)}"
            self._emit(cfg.dto_id, "rx", res, kind, decoded)

            if kind == "err" and raise_on_error:
                err_name, err_desc = _ERR_NAMES.get(
                    res[1], (f"CRC_0x{res[1]:02X}", "Mã lỗi không có trong từ điển")
                )
                raise SlaveError(res[1], err_name, err_desc)
            return res

    # ── tiện ích chỉ có ở bản giả (test dùng, UI không gọi) ──────────────────

    def start_flood(self, rate_hz: float = 2000.0) -> None:
        """Bơm frame DAQ giả vào trace để kiểm tra UI dưới tải."""
        self.stop_flood()
        self._flood_stop.clear()
        t = threading.Thread(
            target=self._flood_loop, args=(rate_hz,), name="fake-flood", daemon=True
        )
        self._flood_thread = t
        t.start()

    def stop_flood(self) -> None:
        self._flood_stop.set()
        t = self._flood_thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2.0)
        self._flood_thread = None

    def inject_trace(self, entry: TraceEntry) -> None:
        self._push(entry)

    # ── nội bộ ───────────────────────────────────────────────────────────────

    class _CommandGuard:
        def __init__(self, session: FakeSession, what: str) -> None:
            self._s = session
            self._what = what

        def __enter__(self) -> None:
            s = self._s
            if s._state is not ConnState.CONNECTED:
                if s._state is ConnState.ERROR:
                    raise BusError("Bus đang ở trạng thái lỗi — hãy kết nối lại")
                raise NotConnectedError(f"Chưa CONNECT nên không gửi được {self._what}")
            if not s._cmd_lock.acquire(blocking=False):
                raise BusyError("Đang có một lệnh khác chờ response trên bus")
            try:
                s._sleep(s.behavior.command_delay_s)
                s._command_count += 1
                limit = s.behavior.fail_after_commands
                if limit is not None and s._command_count > limit:
                    s._set_state(ConnState.ERROR)
                    raise BusError("Mất kết nối với thiết bị CAN (bản giả: rút dây)")
            except BaseException:
                s._cmd_lock.release()
                raise

        def __exit__(self, *exc: object) -> None:
            self._s._cmd_lock.release()

    def _command(self, what: str) -> _CommandGuard:
        return FakeSession._CommandGuard(self, what)

    def _fake_response(self, pid: int, payload: bytes) -> bytes:
        if self.behavior.malformed_responses:
            return bytes([0xFF])[: 1 if pid != 0xFF else 1]
        if pid == 0xFF:
            return bytes([0xFF, self._resource_byte(), 0x01,
                          self.behavior.max_cto,
                          self.behavior.max_dto & 0xFF, self.behavior.max_dto >> 8,
                          0x01, 0x01])
        if pid == 0xFE:
            return bytes([0xFF])
        if pid == 0xFD:
            return bytes([0xFF, 0x00, self._resource_byte(), 0x00, 0x00, 0x00])
        if pid == 0xFC:
            return bytes([0xFE, 0x00])  # SYNCH luôn trả ERR_CMD_SYNCH theo spec
        if pid == 0xEA:
            return bytes([0xFF, 0, 0, self._xcp_page])
        if pid in _CMD_NAMES:
            return bytes([0xFF, 0x00])
        return bytes([0xFE, ERR_CMD_UNKNOWN])

    def _resource_byte(self) -> int:
        r = 0
        if self.behavior.supports_cal_pag:
            r |= 0x01
        if self.behavior.supports_daq:
            r |= 0x04
        return r

    def _need_cal_pag(self) -> None:
        if not self.behavior.supports_cal_pag:
            raise UnsupportedByEcuError("CAL/PAG (điều khiển trang calibration)")

    def _check_segment(self, segment: int) -> None:
        if not 0 <= segment < SEGMENT_COUNT:
            raise OutOfRangeError(ERR_OUT_OF_RANGE, "CRC_OUT_OF_RANGE",
                                  f"Segment {segment} không tồn tại")

    def _check_page(self, page: int) -> None:
        if not 0 <= page < PAGE_COUNT:
            raise OutOfRangeError(ERR_OUT_OF_RANGE, "CRC_OUT_OF_RANGE",
                                  f"Trang {page} không tồn tại")

    def _check_range(self, addr: int, size: int) -> None:
        if size <= 0:
            raise OutOfRangeError(ERR_OUT_OF_RANGE, "CRC_OUT_OF_RANGE", "Kích thước phải > 0")
        if addr < MEM_BASE or addr + size > MEM_BASE + MEM_SIZE:
            raise OutOfRangeError(
                ERR_OUT_OF_RANGE,
                "CRC_OUT_OF_RANGE",
                f"Vùng 0x{addr:08X}+{size} nằm ngoài "
                f"0x{MEM_BASE:08X}..0x{MEM_BASE + MEM_SIZE - 1:08X}",
            )

    def _set_state(self, s: ConnState) -> None:
        with self._state_lock:
            self._state = s

    def _sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def _sleep_interruptible(self, seconds: float) -> None:
        """Ngủ theo lát nhỏ để close() cắt ngang được — mô phỏng bus bị đóng
        trong lúc đang mở kết nối."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._closed.is_set():
                raise BusError("Bus bị đóng trong lúc đang kết nối")
            time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))

    def _emit(self, can_id: int, direction: str, data: bytes, kind: str,
              decoded: str, note: str | None = None) -> None:
        cfg = self._cfg
        if cfg is not None and cfg.pad_dlc and len(data) < 8:
            data = data + bytes(8 - len(data))
        self._push(TraceEntry(
            seq=next(self._seq),
            t_mono=time.perf_counter(),
            direction=direction,  # type: ignore[arg-type]
            can_id=can_id,
            data=data,
            kind=kind,  # type: ignore[arg-type]
            decoded=decoded,
            note=note,
        ))

    def _push(self, entry: TraceEntry) -> None:
        with self._trace_lock:
            if len(self._trace) == self._trace.maxlen:
                self._dropped += 1
            self._trace.append(entry)

    def _flood_loop(self, rate_hz: float) -> None:
        cfg = self._cfg
        dto_id = cfg.dto_id if cfg is not None else 0x100
        tick = 0.01
        per_tick = max(1, int(rate_hz * tick))
        next_at = time.perf_counter()
        counter = 0
        while not self._flood_stop.is_set():
            for _ in range(per_tick):
                counter += 1
                payload = bytes([0x01]) + counter.to_bytes(4, "little") + bytes(3)
                self._push(TraceEntry(
                    seq=next(self._seq),
                    t_mono=time.perf_counter(),
                    direction="rx",
                    can_id=dto_id,
                    data=payload,
                    kind="daq",
                    decoded=f"DAQ pid=1 counter={counter}",
                ))
            next_at += tick
            delay = next_at - time.perf_counter()
            if delay > 0:
                self._flood_stop.wait(delay)
            else:
                next_at = time.perf_counter()
