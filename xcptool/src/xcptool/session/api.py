"""Contract giữa lớp UI/CLI (frontend) và lớp protocol/transport (backend).

╔══════════════════════════════════════════════════════════════════════════════╗
║  FILE NÀY DO LEAD SỞ HỮU.                                                    ║
║  Frontend agent và backend agent chỉ được IMPORT, không được SỬA.            ║
║  Cần đổi bất cứ thứ gì ở đây → nhắn lead, chờ duyệt, lead sửa và báo cả hai. ║
╚══════════════════════════════════════════════════════════════════════════════╝

Không có logic nào trong file này — chỉ kiểu dữ liệu, ngoại lệ, và chữ ký hàm.

--------------------------------------------------------------------------------
LUẬT THREAD  (đọc kỹ — đây là chỗ app loại này chết nhiều nhất)
--------------------------------------------------------------------------------

Session KHÔNG biết gì về Qt. Nó không bao giờ gọi ngược lên UI.

  * Nhóm CHẶN — mọi phương thức trừ nhóm dưới. Có thể mất tới `timeout_s`.
    Frontend PHẢI gọi chúng từ worker thread (QThreadPool / QRunnable) rồi
    marshal kết quả về UI thread bằng Qt signal. Gọi thẳng từ UI thread sẽ
    làm đơ giao diện — coi như lỗi.

  * Nhóm KHÔNG CHẶN, an toàn thread — gọi thẳng từ UI thread được:
        state, caps, dropped_frames, drain_trace(), load_config(), symbols
    Frontend gọi `drain_trace()` theo QTimer 30–50 ms. KHÔNG vẽ theo từng frame.

  * Session KHÔNG reentrant: mỗi lúc chỉ một lệnh trên bus. Backend tự
    serialize bằng lock; nếu có lệnh thứ hai chen vào → ném `BusyError`
    ngay lập tức, không xếp hàng, không chờ.

  * `close()` idempotent và KHÔNG BAO GIỜ ném ngoại lệ. Gọi được cả khi
    đang ở trạng thái lỗi, cả khi chưa từng connect.

--------------------------------------------------------------------------------
LUẬT NGOẠI LỆ
--------------------------------------------------------------------------------

Mọi lỗi lường trước được đều là con của `XcpToolError`. Frontend bắt
`XcpToolError` → hiện thông báo cho user. Bất cứ ngoại lệ nào KHÁC thoát ra
khỏi Session đều là bug của backend, không phải việc frontend phải xử lý.

--------------------------------------------------------------------------------
LUẬT ĐỘC LẬP THIẾT BỊ
--------------------------------------------------------------------------------

Không chỗ nào trong app được hardcode đặc tính của một ECU cụ thể — không
MAX_CTO, không CAN ID, không byte order, không đơn vị timestamp. Tất cả đến
từ `BusConfig` (user cấu hình) hoặc `SlaveCaps` (hỏi ECU lúc CONNECT).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from ..a2l import A2LDatabase

__all__ = [
    "ConnState", "PageMode", "Direction", "FrameKind",
    "DeviceInfo", "BusConfig", "AppConfig", "DaqCaps", "SlaveCaps", "TraceEntry",
    "DaqSignal", "DaqList", "SamplePoint",
    "XcpToolError", "TransportError", "DeviceNotFoundError", "DriverMissingError",
    "BusError", "ProtocolError", "XcpTimeoutError", "MalformedResponseError",
    "SlaveError", "WriteProtectedError", "OutOfRangeError", "SequenceError",
    "AccessDeniedError", "NotConnectedError", "BusyError", "UnsupportedByEcuError",
    "A2LDatabase", "Session",
]


# ══════════════════════════════════════════════════════════════════════════════
#  Enum
# ══════════════════════════════════════════════════════════════════════════════

class ConnState(Enum):
    """Trạng thái phiên. Frontend hiển thị trên status bar."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"          # transport chết giữa chừng (rút dây, driver lỗi)


class PageMode(Enum):
    """Byte mode của GET_CAL_PAGE / SET_CAL_PAGE."""
    ECU = 0x01               # trang mà ECU đang chạy trên đó
    XCP = 0x02               # trang mà công cụ đang nhìn vào


Direction = Literal["tx", "rx"]

FrameKind = Literal[
    "cmd",      # tx: CRO
    "res",      # rx: 0xFF  positive response
    "err",      # rx: 0xFE  error
    "ev",       # rx: 0xFD  event
    "serv",     # rx: 0xFC  service request
    "daq",      # rx: DTO   (byte0 không thuộc 0xFC..0xFF)
    "other",    # frame trên CAN ID không phải của phiên này
]


# ══════════════════════════════════════════════════════════════════════════════
#  Kiểu dữ liệu
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DeviceInfo:
    """Một kênh CAN mà công cụ có thể mở. Kết quả của `list_devices()`.

    Backend luôn trả về CẢ những backend chưa cài driver, với
    `available=False` và `hint` nói rõ cần cài gói nào. Đây là lỗi người dùng
    gặp nhiều nhất với công cụ loại này — im lặng bỏ qua là thiết kế tồi.
    """
    backend: str                    # 'pcan' | 'vector' | 'etas' | 'slcan' | 'virtual' | 'replay'
    channel: str                    # 'PCAN_USBBUS1', '0', 'COM3', 'vcan0', …
    display_name: str               # chuỗi cho combo box, đã sẵn sàng hiển thị
    available: bool
    hint: str | None = None         # vì sao không dùng được / cần cài gì
    serial: str | None = None


@dataclass(frozen=True)
class BusConfig:
    """Mọi thứ cần để mở bus và nói chuyện với MỘT ECU.

    Không có giá trị nào ở đây được hardcode trong code — tất cả do user đặt
    và lưu vào thư mục hiện tại. Mặc định dưới đây chỉ là điểm khởi đầu
    tiện tay, không phải giả định về ECU.
    """
    backend: str
    channel: str
    bitrate: int = 500_000
    cro_id: int = 0x7E0             # host → ECU
    dto_id: int = 0x7E1             # ECU → host (response, event VÀ dữ liệu DAQ)
    extended_id: bool = False       # False = 11-bit
    pad_dlc: bool = True            # A2L MAX_DLC_REQUIRED → luôn đệm đủ 8 byte
    t1_timeout_s: float = 1.0       # timeout chờ response của một lệnh
    is_fd: bool = False             # CAN FD mode
    data_bitrate: int = 2_000_000   # Data phase bitrate (CAN FD only)
    
    # Custom Bit Timing (Arbitration)
    custom_bit_timing: bool = False
    f_clock: int = 80_000_000
    brp: int = 1
    tseg1: int = 14
    tseg2: int = 2
    sjw: int = 1
    
    # Custom Bit Timing (Data Phase - CAN FD only)
    dbrp: int = 1
    dtseg1: int = 14
    dtseg2: int = 2
    dsjw: int = 1


@dataclass
class AppConfig:
    """Toàn bộ cấu hình ứng dụng được lưu lại giữa các phiên làm việc."""
    bus: BusConfig
    last_a2l_path: str = ""
    scope_enabled: bool = True
    trace_row_limit: int = 20_000
    active_route: str = "calibration"
    dock_state: str = ""
    debug_area_collapsed: bool = False
    trace_visible_kinds: list[str] = field(
        default_factory=lambda: ["cmd", "res", "err", "ev", "serv", "other"]
    )


@dataclass(frozen=True)
class DaqCaps:
    """Năng lực DAQ, đọc từ GET_DAQ_PROCESSOR_INFO + GET_DAQ_RESOLUTION_INFO.

    Ngoài phạm vi M1/M2 — khai báo sẵn để contract không phải đổi ở M4.
    `None` ở `SlaveCaps.daq` nghĩa là ECU không trả lời các lệnh này.
    """
    max_daq: int
    max_event_channel: int
    min_daq: int
    dynamic_daq: bool               # False = cấu hình DAQ tĩnh
    timestamp_supported: bool
    timestamp_size: int             # 0 | 1 | 2 | 4 byte
    timestamp_unit_ns: int          # đã quy về ns, backend tự chuyển từ mã đơn vị
    timestamp_ticks: int
    pid_off_supported: bool
    granularity_odt_entry_daq: int
    max_odt_entry_size_daq: int


@dataclass(frozen=True)
class SlaveCaps:
    """ECU tự khai nó là gì. Toàn bộ lấy từ response CONNECT và các GET_*_INFO.

    KHÔNG được hardcode bất cứ trường nào ở đây. Đây chính là thứ làm công cụ
    dùng lại được cho ECU khác.
    """
    max_cto: int
    max_dto: int
    byte_order: Literal["little", "big"]
    address_granularity: int        # 1 | 2 | 4 byte
    protocol_version: tuple[int, int]
    transport_version: tuple[int, int]

    # resource byte của CONNECT
    supports_cal_pag: bool
    supports_daq: bool
    supports_stim: bool
    supports_pgm: bool
    needs_seed_and_key: bool        # True → phải unlock trước khi dùng resource

    # comm_mode_basic byte
    slave_block_mode: bool
    optional_cmds: bool             # có GET_COMM_MODE_INFO hay không

    daq: DaqCaps | None = None
    id_string: str | None = None    # từ GET_ID nếu ECU hỗ trợ


@dataclass(frozen=True)
class TraceEntry:
    """Một dòng trong cửa sổ debug CAN.

    Backend sinh entry cho MỌI frame đi qua — cả tx lẫn rx, cả frame không
    thuộc phiên (`kind='other'`). `decoded` luôn có giá trị: khi không giải mã
    được thì để chuỗi hex. Frontend không bao giờ phải tự giải mã byte.
    """
    seq: int                        # tăng đơn điệu, không bao giờ lặp trong một phiên
    t_mono: float                   # time.perf_counter() lúc gửi/nhận
    direction: Direction
    can_id: int
    data: bytes                     # nguyên trạng trên bus, đã gồm phần đệm
    kind: FrameKind
    decoded: str                    # 'CONNECT mode=0' | 'ERR CRC_WRITE_PROTECTED' | '01 02 …'
    note: str | None = None         # 'timeout T1', 'retry', 'dropped 42 frames'…


@dataclass(frozen=True)
class DaqSignal:
    """Một signal cần đưa vào DAQ list.

    Tạo từ `A2LDatabase.measurements[name]`:
        DaqSignal(name=m.name, address=m.address, ext=0, size=m.byte_size, datatype=m.datatype)
    """
    name: str
    address: int
    ext: int        # address extension, thường = 0 với ECU CAN
    size: int       # byte — DATATYPE_SIZES[datatype] × array_size
    datatype: str   # DataType literal ('UINT16', 'FLOAT32', ...)


@dataclass
class DaqList:
    """Một DAQ list cần cấu hình trên ECU."""
    signals: list[DaqSignal]
    event: int                  # mã kênh event (từ A2L hoặc hardcode)
    timestamp: bool = True      # bật timestamp trên ODT 0
    prescaler: int = 1          # 1 = mỗi event một lần
    priority: int = 0           # 0 = thấp nhất


@dataclass(frozen=True)
class SamplePoint:
    """Một giá trị đo tại một thời điểm, decode từ DTO frame.

    value_raw: bytes thô — UI tự decode theo datatype.
    timestamp_ns: nanosecond tuyệt đối tính từ START_STOP_SYNCH, bù rollover.
    """
    name: str
    timestamp_ns: int
    value_raw: bytes
    datatype: str


# ══════════════════════════════════════════════════════════════════════════════
#  Ngoại lệ
# ══════════════════════════════════════════════════════════════════════════════

class XcpToolError(Exception):
    """Gốc của mọi lỗi lường trước được. Frontend bắt đúng lớp này."""
    user_message: str = "Lỗi không xác định"

    def __init__(self, user_message: str | None = None, /, **ctx: object) -> None:
        if user_message is not None:
            self.user_message = user_message
        self.context = ctx
        super().__init__(self.user_message)


# ── transport ────────────────────────────────────────────────────────────────

class TransportError(XcpToolError):
    """Lỗi ở tầng bus, chưa đụng tới giao thức XCP."""


class DeviceNotFoundError(TransportError):
    """Kênh đã chọn không còn tồn tại (rút dây, đổi cổng USB)."""


class DriverMissingError(TransportError):
    """Chưa cài driver của hãng. `package_hint` nói rõ cần cài gì."""

    def __init__(self, backend: str, package_hint: str) -> None:
        self.backend = backend
        self.package_hint = package_hint
        super().__init__(f"Backend '{backend}' chưa dùng được. Cần cài: {package_hint}")


class BusError(TransportError):
    """Bus lỗi lúc đang chạy: bus-off, error-passive, hàng gửi đầy."""


# ── giao thức ────────────────────────────────────────────────────────────────

class ProtocolError(XcpToolError):
    """Lỗi ở tầng XCP."""


class XcpTimeoutError(ProtocolError):
    """Hết T1 mà ECU không trả lời."""


class MalformedResponseError(ProtocolError):
    """ECU trả frame ngắn hơn dự kiến hoặc sai định dạng.

    Backend PHẢI ném lỗi này thay vì để struct.error / IndexError lọt ra.
    """


class SlaveError(ProtocolError):
    """ECU trả 0xFE kèm mã lỗi. `code` là mã thô, `name` là tên trong spec."""

    def __init__(self, code: int, name: str, description: str) -> None:
        self.code = code
        self.name = name
        self.description = description
        super().__init__(f"{name} (0x{code:02X}): {description}")


class WriteProtectedError(SlaveError):
    """CRC_WRITE_PROTECTED — thường là do XCP đang trỏ reference page.

    Frontend nên hiện kèm nút chuyển về working page, đừng chỉ in mã lỗi.
    """


class OutOfRangeError(SlaveError):
    """CRC_OUT_OF_RANGE."""


class SequenceError(SlaveError):
    """CRC_SEQUENCE — gửi lệnh sai thứ tự."""


class AccessDeniedError(SlaveError):
    """CRC_ACCESS_DENIED / CRC_ACCESS_LOCKED — cần seed & key."""


# ── trạng thái phiên ─────────────────────────────────────────────────────────

class NotConnectedError(XcpToolError):
    """Gọi lệnh khi chưa CONNECT."""


class BusyError(XcpToolError):
    """Đã có một lệnh đang chờ response. Session không reentrant."""


class UnsupportedByEcuError(XcpToolError):
    """ECU này không có tính năng đó (theo `SlaveCaps`).

    Ví dụ: gọi set_page() khi `supports_cal_pag=False`. Backend kiểm tra
    trước khi gửi lên bus, không để ECU trả lỗi mơ hồ.
    """

    def __init__(self, feature: str) -> None:
        self.feature = feature
        super().__init__(f"ECU không hỗ trợ: {feature}")


# ══════════════════════════════════════════════════════════════════════════════
#  Giao diện Session
# ══════════════════════════════════════════════════════════════════════════════

@runtime_checkable
class Session(Protocol):
    """API duy nhất mà frontend được phép gọi.

    Có hai bản hiện thực, cùng chữ ký:
      * `xcptool.session.real.RealSession`  — backend agent viết
      * `xcptool.session.fake.FakeSession`  — frontend agent viết

    FakeSession cho phép toàn bộ GUI và CLI phát triển + test mà không cần
    python-can, không cần ECU, không cần phần cứng. Nó cũng là nơi mô phỏng
    các tình huống tồi (timeout, frame méo, rút dây, flood) để chứng minh app
    không crash.

    Frontend KHÔNG được import bất cứ thứ gì từ `xcptool.master`,
    `xcptool.transport` hay `xcptool.a2l`. Test ranh giới sẽ ép luật này.
    """

    # ── thuộc tính không chặn, an toàn thread ────────────────────────────────

    @property
    def state(self) -> ConnState: ...

    @property
    def caps(self) -> SlaveCaps | None:
        """`None` khi chưa CONNECT thành công."""

    @property
    def dropped_frames(self) -> int:
        """Số frame bị ring buffer bỏ vì UI rút không kịp. Hiện trên status bar."""

    def drain_trace(self, max_items: int = 5000) -> list[TraceEntry]:
        """Lấy và xoá các entry trace đang chờ. KHÔNG CHẶN, an toàn thread.

        Trả về list rỗng khi không có gì mới. Frontend gọi theo QTimer 30–50 ms.
        Ring buffer có trần — quá thì bỏ entry CŨ nhất và tăng `dropped_frames`,
        không bao giờ để RAM phình.
        """

    def load_config(self) -> BusConfig:
        """`BusConfig` nên dùng làm giá trị khởi đầu cho dialog chọn thiết bị.

        KHÔNG CHẶN — chỉ đọc trạng thái cục bộ nhỏ (file hoặc bộ nhớ), an toàn
        gọi thẳng từ UI thread lúc dựng dialog, không cần worker thread.

        Đây là nguồn DUY NHẤT cho việc "nhớ lựa chọn thiết bị" — `ui/` không
        được tự đọc/ghi file cấu hình riêng, phải đi qua đây. `RealSession` đọc
        `config.toml` ở thư mục hiện tại (được `connect()` tự lưu sau mỗi lần thành
        công); `FakeSession` trả lại `BusConfig` của lần `connect()` gần nhất
        trong tiến trình, hoặc giá trị mặc định nếu chưa từng connect.
        """

    def load_app_config(self) -> AppConfig:
        """Đọc toàn bộ cấu hình ứng dụng bao gồm bus, session và ui."""

    def save_app_config(self, cfg: AppConfig) -> None:
        """Lưu toàn bộ cấu hình ứng dụng."""

    @property
    def symbols(self) -> A2LDatabase:
        """Database A2L đã nạp. Trả `A2LDatabase()` rỗng nếu chưa `load_a2l()`.

        KHÔNG CHẶN — chỉ trả object đã có trong bộ nhớ, an toàn gọi từ UI thread.
        """

    # ── vòng đời (CHẶN — gọi từ worker thread) ───────────────────────────────

    def list_devices(self) -> list[DeviceInfo]:
        """Dò các kênh CAN đang cắm. Không ném lỗi khi thiếu driver — trả về
        entry với `available=False` và `hint`.

        Có thể mất vài giây (dò từng backend) → luôn gọi từ worker thread.
        """

    def connect(self, cfg: BusConfig) -> SlaveCaps:
        """Mở bus, gửi CONNECT, rồi hỏi năng lực ECU.

        Backend PHẢI hỏi thật, không giả định: MAX_CTO/MAX_DTO/byte order từ
        response CONNECT; DAQ info từ GET_DAQ_PROCESSOR_INFO và
        GET_DAQ_RESOLUTION_INFO (bỏ qua êm nếu ECU không hỗ trợ).

        Raises:
            DriverMissingError, DeviceNotFoundError, BusError, XcpTimeoutError,
            MalformedResponseError
        """

    def disconnect(self) -> None:
        """Gửi DISCONNECT, giữ bus mở. Êm nếu vốn đã disconnected."""

    def close(self) -> None:
        """Dừng thread, đóng bus, giải phóng thiết bị.

        IDEMPOTENT và KHÔNG BAO GIỜ NÉM. Frontend gọi trong closeEvent() —
        kể cả khi DAQ đang chạy hoặc bus đang lỗi. Ném ở đây là bug.
        """

    # ── bộ nhớ (M2) ──────────────────────────────────────────────────────────

    def read(self, addr: int, size: int, ext: int = 0) -> bytes:
        """Đọc `size` byte tại `addr`.

        Backend tự chia khối theo MAX_CTO thật của ECU và tự chọn
        SHORT_UPLOAD hay SET_MTA+UPLOAD. Frontend không cần biết giới hạn nào.

        Raises: NotConnectedError, BusyError, XcpTimeoutError, SlaveError
        """

    def write(self, addr: int, data: bytes, ext: int = 0) -> None:
        """Ghi `data` tại `addr`, chia khối tự động như `read`.

        Ghi trọn khối cho struct/mảng thay vì từng field — ECU không được đi
        qua trạng thái nửa cũ nửa mới.

        Raises: NotConnectedError, BusyError, XcpTimeoutError,
                WriteProtectedError, SlaveError
        """

    # ── trang calibration (M2) ───────────────────────────────────────────────

    def get_page(self, segment: int, mode: PageMode) -> int:
        """Trang nào đang hoạt động cho `mode`. Raises: UnsupportedByEcuError"""

    def set_page(self, segment: int, page: int, mode: PageMode) -> None:
        """Đổi trang cho `mode`. Raises: UnsupportedByEcuError, SlaveError"""

    def copy_page(
        self, src_segment: int, src_page: int, dst_segment: int, dst_page: int
    ) -> None:
        """COPY_CAL_PAGE. Raises: UnsupportedByEcuError, SlaveError"""

    # ── A2L (M3) ─────────────────────────────────────────────────────────────

    def load_a2l(self, path: str | Path) -> None:
        """Nạp và parse file A2L. CHẶN (đọc file + parse).

        Kết quả truy xuất qua `symbols`. Gọi từ worker thread — có thể mất vài
        trăm ms với file lớn.

        Raises: XcpToolError nếu file không đọc được hoặc lỗi parse nghiêm trọng
        """

    # ── DAQ (M4) ─────────────────────────────────────────────────────────────

    def start_daq(self, lists: list[DaqList]) -> None:
        """Cấu hình DAQ list trên ECU rồi gọi START_STOP_SYNCH. CHẶN.

        Sau khi trả về, ECU bắt đầu phát DTO frame. Dùng `drain_daq()` để
        lấy sample. Gọi `stop_daq()` để dừng.

        Raises: NotConnectedError, UnsupportedByEcuError, SlaveError,
                BusyError, XcpTimeoutError
        """

    def stop_daq(self) -> None:
        """Dừng tất cả DAQ list. Idempotent. CHẶN.

        Raises: NotConnectedError, BusyError, XcpTimeoutError
        """

    def drain_daq(self, n: int = 1000) -> list[SamplePoint]:
        """Lấy và xoá tối đa `n` sample từ ring buffer. KHÔNG CHẶN, an toàn thread.

        Gọi theo QTimer 40ms. Trả list rỗng khi không có gì mới. Ring buffer
        có trần — khi đầy, sample CŨ nhất bị bỏ (real-time priority).
        """

    # ── lệnh thô (M1 — cửa sổ debug) ─────────────────────────────────────────

    def raw_command(self, payload: bytes, raise_on_error: bool = False) -> bytes:
        """Gửi một CTO thô và trả về response thô. Dành cho console debug.

        `payload` là nội dung CTO chưa đệm (backend tự đệm theo `pad_dlc`).
        Trả về nguyên frame response gồm cả byte 0 (0xFF hoặc 0xFE).

        `raise_on_error=False` (mặc định cho console): response lỗi được TRẢ VỀ
        để user tự nhìn byte, không ném ngoại lệ. Đặt True nếu muốn hành xử
        như các lệnh khác.

        Raises: NotConnectedError, BusyError, XcpTimeoutError
        """
