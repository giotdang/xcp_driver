"""`RealSession` — hiện thực `session.api.Session` trên bus CAN thật.

Đây là chỗ duy nhất `transport/` và `master/` gặp nhau. Lớp này không biết Qt
tồn tại và không bao giờ gọi ngược lên UI: frontend gọi các phương thức chặn từ
worker thread, rồi tự marshal kết quả về UI thread.
"""

from __future__ import annotations

import functools
import logging
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from ..a2l import A2LDatabase
from ..a2l import load as _a2l_load
from ..master.core import XcpMaster
from ..master.daq import (
    DaqListConfig,
    DaqSignal as _MasterDaqSignal,
    PidEntry,
    SamplePoint as _MasterSamplePoint,
    TimestampAccumulator,
    configure_daq,
    decode_dto,
    stop_daq as _master_stop_daq,
)
from ..master.trace import DEFAULT_CAPACITY, TraceBuffer
from ..transport import config as cfg_store
from ..transport import registry
from ..transport.base import Transport
from .api import (
    BusConfig,
    ConnState,
    DaqList,
    DaqSignal,
    DeviceInfo,
    NotConnectedError,
    PageMode,
    SamplePoint,
    SlaveCaps,
    TraceEntry,
    UnsupportedByEcuError,
    XcpToolError,
)

__all__ = ["RealSession"]

log = logging.getLogger("xcptool.session")

# Bit của byte Resource Protection Status (GET_STATUS) ứng với tài nguyên mà
# công cụ này thực sự dùng. Khoá riêng PGM không cản trở đo/hiệu chỉnh.
_PROTECTION_BITS_WE_NEED = 0x01 | 0x04   # CAL/PAG | DAQ

F = TypeVar("F", bound=Callable[..., Any])

_DAQ_RING_CAPACITY = 10_000


def _to_master_sig(s: DaqSignal) -> _MasterDaqSignal:
    return _MasterDaqSignal(name=s.name, address=s.address, ext=s.ext,
                             size=s.size, datatype=s.datatype)


def _to_master_cfg(dl: DaqList) -> DaqListConfig:
    return DaqListConfig(
        signals=[_to_master_sig(s) for s in dl.signals],
        event=dl.event,
        timestamp=dl.timestamp,
        prescaler=dl.prescaler,
        priority=dl.priority,
    )


def _from_master_sample(sp: _MasterSamplePoint) -> SamplePoint:
    return SamplePoint(name=sp.name, timestamp_ns=sp.timestamp_ns,
                       value_raw=sp.value_raw, datatype=sp.datatype)


def _guarded(what: str) -> Callable[[F], F]:
    """Không ngoại lệ nào ngoài `XcpToolError` được rời khỏi Session.

    Lỗi ngoài dự kiến vẫn ghi log kèm traceback — nuốt im lặng thì frontend hiện
    được thông báo nhưng ta mất manh mối.
    """
    def decorate(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: object, **kwargs: object) -> object:
            try:
                return fn(*args, **kwargs)
            except XcpToolError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("Lỗi ngoài dự kiến khi %s", what)
                raise XcpToolError(f"Lỗi nội bộ khi {what}: {exc!r}") from exc
        return wrapper  # type: ignore[return-value]
    return decorate


class RealSession:
    def __init__(self, trace_capacity: int = DEFAULT_CAPACITY) -> None:
        self._trace = TraceBuffer(trace_capacity)
        self._master: XcpMaster | None = None
        self._transport: Transport | None = None
        self._last_state = ConnState.DISCONNECTED
        self._a2l_db: A2LDatabase = A2LDatabase()

        # DAQ state — protected bởi _daq_lock khi cập nhật _daq_ring
        self._daq_pid_table: dict[int, PidEntry] | None = None
        self._daq_ts_accum: TimestampAccumulator = TimestampAccumulator()
        self._daq_ring: deque[SamplePoint] = deque(maxlen=_DAQ_RING_CAPACITY)
        self._daq_lock = threading.Lock()

    # ── không chặn, an toàn thread ───────────────────────────────────────────

    @property
    def state(self) -> ConnState:
        master = self._master
        return self._last_state if master is None else master.state

    @property
    def caps(self) -> SlaveCaps | None:
        master = self._master
        return master.caps if master is not None else None

    @property
    def dropped_frames(self) -> int:
        return self._trace.dropped

    def drain_trace(self, max_items: int = 5000) -> list[TraceEntry]:
        return self._trace.drain(max_items)

    def load_config(self) -> BusConfig:
        return cfg_store.load_bus_config()

    def load_app_config(self) -> AppConfig:
        return cfg_store.load_app_config()

    def save_app_config(self, cfg: AppConfig) -> None:
        try:
            cfg_store.save_app_config(cfg)
        except OSError:
            log.warning("Không lưu được app config: %s", cfg_store.config_path(), exc_info=True)

    @property
    def symbols(self) -> A2LDatabase:
        return self._a2l_db

    # ── vòng đời ─────────────────────────────────────────────────────────────

    @_guarded("dò thiết bị")
    def list_devices(self) -> list[DeviceInfo]:
        return registry.list_devices()

    @_guarded("kết nối")
    def connect(self, cfg: BusConfig) -> SlaveCaps:
        self._teardown()
        self._last_state = ConnState.CONNECTING

        transport = registry.open_transport(cfg)
        master = XcpMaster(transport, cfg, trace=self._trace)
        self._transport = transport
        self._master = master

        try:
            caps = master.connect()
            self._reject_if_locked(master, caps)
        except XcpToolError:
            self._teardown()
            self._last_state = ConnState.DISCONNECTED
            raise

        self._remember(cfg)
        return caps

    def _reject_if_locked(self, master: XcpMaster, caps: SlaveCaps) -> None:
        """Seed & key: báo rõ rồi ngắt sạch, không hỏng lặng lẽ giữa chừng."""
        protection = master.resource_protection or 0
        if caps.needs_seed_and_key and protection & _PROTECTION_BITS_WE_NEED:
            raise UnsupportedByEcuError(
                "ECU yêu cầu seed & key để mở khoá calibration/DAQ "
                f"(protection=0x{protection:02X}) — công cụ chưa hỗ trợ")

    def _remember(self, cfg: BusConfig) -> None:
        """Nhớ lựa chọn cho lần sau. Ghi hỏng thì thôi, đừng làm hỏng phiên."""
        try:
            cfg_store.save_bus_config(cfg)
        except OSError:
            log.warning("Không lưu được %s", cfg_store.config_path(), exc_info=True)

    @_guarded("ngắt kết nối")
    def disconnect(self) -> None:
        master = self._master
        if master is None:
            return
        master.disconnect()
        self._last_state = master.state
        self._teardown()


    def close(self) -> None:
        """IDEMPOTENT và KHÔNG BAO GIỜ NÉM — frontend gọi trong closeEvent()."""
        try:
            # master.close() tự lo DISCONNECT (có giới hạn chờ) rồi mới dừng thread.
            self._teardown()
        except Exception:  # noqa: BLE001 — close() ném là bug, chặn tại đây
            log.exception("Lỗi khi đóng phiên, đã nuốt")
        finally:
            self._last_state = ConnState.DISCONNECTED

    def _teardown(self) -> None:
        master, transport = self._master, self._transport
        self._master = None
        self._transport = None
        self._daq_pid_table = None   # huỷ DAQ state khi teardown
        if master is not None:
            master.set_daq_callback(None)
            master.close()          # đã tự đóng link
        elif transport is not None:
            transport.close()

    # ── bộ nhớ ───────────────────────────────────────────────────────────────

    def _require_master(self) -> XcpMaster:
        master = self._master
        if master is None:
            raise NotConnectedError("Chưa CONNECT tới ECU")
        return master

    @_guarded("đọc bộ nhớ")
    def read(self, addr: int, size: int, ext: int = 0) -> bytes:
        return self._require_master().read(addr, size, ext)

    @_guarded("ghi bộ nhớ")
    def write(self, addr: int, data: bytes, ext: int = 0) -> None:
        self._require_master().write(addr, data, ext)

    # ── trang calibration ────────────────────────────────────────────────────

    @_guarded("đọc trang calibration")
    def get_page(self, segment: int, mode: PageMode) -> int:
        return self._require_master().get_page(segment, mode)

    @_guarded("đổi trang calibration")
    def set_page(self, segment: int, page: int, mode: PageMode) -> None:
        self._require_master().set_page(segment, page, mode)

    @_guarded("sao chép trang calibration")
    def copy_page(
        self, src_segment: int, src_page: int, dst_segment: int, dst_page: int
    ) -> None:
        self._require_master().copy_page(src_segment, src_page, dst_segment, dst_page)

    # ── A2L ──────────────────────────────────────────────────────────────────

    @_guarded("nạp A2L")
    def load_a2l(self, path: str | Path) -> None:
        self._a2l_db = _a2l_load(path)

    # ── DAQ ──────────────────────────────────────────────────────────────────

    @_guarded("cấu hình DAQ")
    def start_daq(self, lists: list[DaqList]) -> None:
        master = self._require_master()
        caps = master.caps
        byte_order = caps.byte_order if caps else "little"

        # Reset trước khi configure để không trộn mẫu từ phiên cũ
        master.set_daq_callback(None)
        self._daq_pid_table = None
        with self._daq_lock:
            self._daq_ring.clear()
        self._daq_ts_accum = TimestampAccumulator(byte_order=byte_order)

        master_cfgs = [_to_master_cfg(dl) for dl in lists]
        pid_table = configure_daq(master, master_cfgs)

        self._daq_pid_table = pid_table
        master.set_daq_callback(self._on_daq_frame)

    @_guarded("dừng DAQ")
    def stop_daq(self) -> None:
        master = self._require_master()
        master.set_daq_callback(None)
        self._daq_pid_table = None
        _master_stop_daq(master)

    def drain_daq(self, n: int = 1000) -> list[SamplePoint]:
        """KHÔNG CHẶN — pop tối đa n sample từ ring buffer."""
        with self._daq_lock:
            count = min(n, len(self._daq_ring))
            return [self._daq_ring.popleft() for _ in range(count)]

    def _on_daq_frame(self, frame: bytes) -> None:
        """Callback từ XcpMaster RX thread — giải mã frame và đẩy vào ring."""
        pid_table = self._daq_pid_table
        if pid_table is None:
            return
        samples = decode_dto(frame, pid_table, self._daq_ts_accum)
        if not samples:
            return
        with self._daq_lock:
            for sp in samples:
                self._daq_ring.append(_from_master_sample(sp))

    # ── lệnh thô ─────────────────────────────────────────────────────────────

    @_guarded("gửi lệnh thô")
    def raw_command(self, payload: bytes, raise_on_error: bool = False) -> bytes:
        return self._require_master().raw_command(payload, raise_on_error)
