"""Protocol core XCP — không biết CAN là gì, không biết GUI là gì.

Nó nói chuyện với một `Link` (ba phương thức `send`/`recv`/`close`) mà tầng
`transport/` hiện thực. Không import `can`, không import `PySide6`, không import
`xcptool.transport` — test ranh giới cưỡng chế điều đó, và đó chính là thứ làm
core dùng lại được khi sau này chạy XCP trên Ethernet.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Protocol

from ..session.api import (
    BusConfig,
    BusError,
    BusyError,
    ConnState,
    DaqCaps,
    MalformedResponseError,
    NotConnectedError,
    PageMode,
    SlaveCaps,
    TraceEntry,
    TransportError,
    UnsupportedByEcuError,
    XcpTimeoutError,
    XcpToolError,
)
from .codec import classify, describe_rx, describe_tx, hexs, pack_u32
from .constants import TIMESTAMP_UNIT_NS, Cmd, Pid
from .errors import make_slave_error
from .trace import DEFAULT_CAPACITY, TraceBuffer

__all__ = ["Link", "RxFrame", "XcpMaster"]

log = logging.getLogger("xcptool.master")

_RECV_SLICE_S = 0.05
"""Nhịp thức dậy của RX thread — đủ nhỏ để close() không phải chờ lâu."""


class RxFrame(Protocol):
    """Hình dạng của frame mà `Link.recv()` trả về (duck typing, không import)."""

    can_id: int
    data: bytes
    t_mono: float


class Link(Protocol):
    """Tầng dưới mà core cần. `transport.Transport` thoả mãn giao diện này."""

    max_frame_len: int
    """Trần vật lý của một frame. Core lấy min với MAX_CTO mà ECU khai."""

    def send(self, can_id: int, data: bytes) -> bytes: ...
    def recv(self, timeout: float) -> RxFrame | None: ...
    def close(self) -> None: ...


class _Sentinel:
    """Báo cho lệnh đang chờ biết RX thread đã chết."""

    def __init__(self, error: XcpToolError) -> None:
        self.error = error


class XcpMaster:
    """Một phiên XCP trên một link. Không reentrant — xem contract."""

    def __init__(
        self,
        link: Link,
        cfg: BusConfig,
        trace: TraceBuffer | None = None,
    ) -> None:
        self._link = link
        self._cfg = cfg
        self._trace = trace if trace is not None else TraceBuffer(DEFAULT_CAPACITY)

        self._state = ConnState.DISCONNECTED
        self._caps: SlaveCaps | None = None
        self._rx_error: XcpToolError | None = None
        self.resource_protection: int | None = None
        """Byte Resource Protection Status của GET_STATUS. `None` = ECU không trả lời."""

        self._responses: queue.Queue[bytes | _Sentinel] = queue.Queue(maxsize=1)
        self._cmd_lock = threading.Lock()
        self._pending_cmd: int | None = None

        # DAQ callback — được gọi từ RX thread khi nhận DAO frame (byte0 < 0xFC).
        # Phải là hàm nhanh, không chặn; set_daq_callback() để đăng ký/huỷ.
        self._daq_callback: Callable[[bytes], None] | None = None

        self._stop = threading.Event()
        self._rx_thread = threading.Thread(
            target=self._rx_loop, name="xcp-rx", daemon=True)
        self._rx_thread.start()

    # ── trạng thái (không chặn) ──────────────────────────────────────────────

    @property
    def state(self) -> ConnState:
        return self._state

    @property
    def caps(self) -> SlaveCaps | None:
        return self._caps

    @property
    def dropped_frames(self) -> int:
        return self._trace.dropped

    @property
    def trace(self) -> TraceBuffer:
        return self._trace

    def drain_trace(self, max_items: int = 5000) -> list[TraceEntry]:
        return self._trace.drain(max_items)

    def set_daq_callback(self, callback: Callable[[bytes], None] | None) -> None:
        """Đăng ký (hoặc huỷ) callback nhận DAO frame.

        Callback được gọi từ RX thread khi frame có byte0 < 0xFC (DAO/event).
        Phải trả về ngay — không được gọi transact() hay chặn trong callback.
        Truyền None để tắt.
        """
        self._daq_callback = callback

    # ── RX thread ────────────────────────────────────────────────────────────

    def _rx_loop(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    frame = self._link.recv(_RECV_SLICE_S)
                except XcpToolError as exc:
                    self._rx_failed(exc)
                    return
                if frame is not None:
                    self._on_frame(frame)
        except BaseException as exc:  # noqa: BLE001 — RX thread chết = app vẫn sống
            self._rx_failed(BusError(f"RX thread hỏng: {exc!r}"))

    def _rx_failed(self, error: XcpToolError) -> None:
        log.exception("RX thread dừng vì lỗi: %s", error)
        self._rx_error = error
        self._state = ConnState.ERROR
        self._trace.add("rx", 0, b"", "other", "RX thread dừng", note=str(error))
        # Đánh thức lệnh đang chờ thay vì để nó ngồi hết T1.
        try:
            self._responses.put_nowait(_Sentinel(error))
        except queue.Full:
            pass

    def _on_frame(self, frame: RxFrame) -> None:
        data = bytes(frame.data)
        if frame.can_id != self._cfg.dto_id:
            self._trace.add("rx", frame.can_id, data, "other",
                            hexs(data) or "(rỗng)", t_mono=frame.t_mono)
            return

        kind = classify(data)
        self._trace.add("rx", frame.can_id, data, kind,
                        describe_rx(data, self._pending_cmd), t_mono=frame.t_mono)

        if kind in ("res", "err"):
            try:
                self._responses.put_nowait(data)
            except queue.Full:
                # Response tới sau khi lệnh đã bỏ cuộc — bỏ, giữ cái mới nhất.
                try:
                    self._responses.get_nowait()
                    self._responses.put_nowait(data)
                except (queue.Empty, queue.Full):
                    pass
        elif kind == "daq":
            cb = self._daq_callback
            if cb is not None:
                try:
                    cb(data)
                except Exception:  # noqa: BLE001 — callback không được làm chết RX thread
                    log.exception("Lỗi trong DAQ callback, đã nuốt")

    # ── giao dịch lệnh ───────────────────────────────────────────────────────

    def _check_link_alive(self) -> None:
        if self._rx_error is not None:
            raise self._rx_error

    def _drain_responses(self) -> None:
        while True:
            try:
                self._responses.get_nowait()
            except queue.Empty:
                return

    def _send_raw(self, payload: bytes, note: str | None = None) -> None:
        self._pending_cmd = payload[0] if payload else None
        try:
            on_wire = self._link.send(self._cfg.cro_id, payload)
        except TransportError:
            self._trace.add("tx", self._cfg.cro_id, payload, "cmd",
                            describe_tx(payload), note="gửi thất bại")
            raise
        self._trace.add("tx", self._cfg.cro_id, on_wire, "cmd",
                        describe_tx(payload), note=note)

    def _await_response(self, timeout: float) -> bytes | None:
        deadline = time.perf_counter() + timeout
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return None
            try:
                item = self._responses.get(timeout=remaining)
            except queue.Empty:
                return None
            if isinstance(item, _Sentinel):
                raise item.error
            return item

    def _synch(self) -> None:
        """Gửi SYNCH để ECU vứt lệnh dở dang. Trả lời của nó là ERR_CMD_SYNCH,
        không phải lỗi thật."""
        self._drain_responses()
        try:
            self._send_raw(bytes([Cmd.SYNCH]), note="resync sau timeout T1")
            self._await_response(self._cfg.t1_timeout_s)
        except XcpToolError:
            pass
        self._drain_responses()

    def transact(
        self,
        payload: bytes,
        *,
        raise_on_error: bool = True,
        timeout: float | None = None,
        retry: bool = True,
        require_connected: bool = True,
    ) -> bytes:
        """Gửi một CTO và chờ response. Không reentrant → `BusyError` nếu chồng.

        Raises: NotConnectedError, BusyError, XcpTimeoutError, SlaveError,
                TransportError
        """
        if require_connected and self._state is not ConnState.CONNECTED:
            self._check_link_alive()
            raise NotConnectedError("Chưa CONNECT tới ECU")
        return self._locked_transact(
            payload, raise_on_error=raise_on_error, timeout=timeout, retry=retry)

    def _locked_transact(
        self, payload: bytes, *, raise_on_error: bool, timeout: float | None,
        retry: bool,
    ) -> bytes:
        if not self._cmd_lock.acquire(blocking=False):
            raise BusyError("Đang có một lệnh chờ response — Session không reentrant")
        try:
            self._check_link_alive()
            return self._exchange(
                payload, raise_on_error=raise_on_error,
                timeout=timeout if timeout is not None else self._cfg.t1_timeout_s,
                retry=retry)
        finally:
            self._pending_cmd = None
            self._cmd_lock.release()

    def _exchange(
        self, payload: bytes, *, raise_on_error: bool, timeout: float, retry: bool
    ) -> bytes:
        attempts = 2 if retry else 1
        for attempt in range(attempts):
            self._drain_responses()
            self._send_raw(payload)
            data = self._await_response(timeout)
            if data is not None:
                return self._interpret(data, raise_on_error=raise_on_error)
            # Data rỗng: đây là chú thích, không phải frame thứ hai trên bus.
            self._trace.add("tx", self._cfg.cro_id, b"", "cmd",
                            f"(không có trả lời cho {describe_tx(payload)})",
                            note=f"timeout T1 ({timeout:.3f}s)")
            if attempt + 1 < attempts:
                self._synch()
        raise XcpTimeoutError(
            f"ECU không trả lời lệnh 0x{payload[0]:02X} trong {timeout:.3f}s"
            + (" (đã thử lại sau SYNCH)" if retry else ""))

    def _interpret(self, data: bytes, *, raise_on_error: bool) -> bytes:
        if not data:
            raise MalformedResponseError("ECU trả frame rỗng")
        if data[0] == Pid.ERR:
            if len(data) < 2:
                raise MalformedResponseError("Frame lỗi thiếu mã lỗi")
            if raise_on_error:
                raise make_slave_error(data[1])
        return data

    # ── vòng đời phiên ───────────────────────────────────────────────────────

    def connect(self) -> SlaveCaps:
        """CONNECT rồi hỏi năng lực. Không giả định gì về ECU."""
        self._check_link_alive()
        self._state = ConnState.CONNECTING
        try:
            resp = self._locked_transact(
                bytes([Cmd.CONNECT, 0x00]),
                raise_on_error=True, timeout=None, retry=True)
        except XcpToolError:
            self._state = ConnState.DISCONNECTED
            raise

        caps = self._parse_connect(resp)
        self._state = ConnState.CONNECTED
        self._caps = caps
        # Các câu hỏi phụ chỉ chạy được khi đã ở trạng thái CONNECTED.
        caps = self._enrich_caps(caps)
        self._caps = caps
        return caps

    def _parse_connect(self, resp: bytes) -> SlaveCaps:
        if len(resp) < 8:
            raise MalformedResponseError(
                f"Response CONNECT cần 8 byte, ECU trả {len(resp)}: {hexs(resp)}")
        resource, comm_mode, max_cto = resp[1], resp[2], resp[3]
        byte_order = "big" if comm_mode & 0x01 else "little"
        max_dto = int.from_bytes(resp[4:6], byte_order)  # type: ignore[arg-type]
        granularity = 1 << ((comm_mode >> 1) & 0x03)

        if max_cto < 8:
            raise MalformedResponseError(
                f"MAX_CTO={max_cto} — XCP trên CAN cần ít nhất 8 byte")
        if max_dto < 8:
            raise MalformedResponseError(
                f"MAX_DTO={max_dto} — XCP trên CAN cần ít nhất 8 byte")

        return SlaveCaps(
            max_cto=max_cto,
            max_dto=max_dto,
            byte_order=byte_order,  # type: ignore[arg-type]
            address_granularity=granularity,
            # CONNECT chỉ khai số hiệu chính; minor không có trên dây.
            protocol_version=(resp[6], 0),
            transport_version=(resp[7], 0),
            supports_cal_pag=bool(resource & 0x01),
            supports_daq=bool(resource & 0x04),
            supports_stim=bool(resource & 0x08),
            supports_pgm=bool(resource & 0x10),
            needs_seed_and_key=False,
            slave_block_mode=bool(comm_mode & 0x40),
            optional_cmds=bool(comm_mode & 0x80),
        )

    def _enrich_caps(self, caps: SlaveCaps) -> SlaveCaps:
        from dataclasses import replace

        extra: dict[str, object] = {}

        protection = self._probe_protection()
        self.resource_protection = protection
        if protection is not None:
            extra["needs_seed_and_key"] = protection != 0

        if caps.supports_daq:
            daq = self._probe_daq_caps()
            if daq is not None:
                extra["daq"] = daq

        ident = self._probe_id(caps)
        if ident:
            extra["id_string"] = ident

        return replace(caps, **extra) if extra else caps  # type: ignore[arg-type]

    def _optional(self, payload: bytes) -> bytes | None:
        """Lệnh không bắt buộc: ECU im lặng hoặc từ chối → `None`, không ném."""
        try:
            return self._locked_transact(
                payload, raise_on_error=True,
                timeout=self._cfg.t1_timeout_s, retry=False)
        except XcpToolError:
            return None

    def _probe_protection(self) -> int | None:
        resp = self._optional(bytes([Cmd.GET_STATUS]))
        if resp is None or len(resp) < 3:
            return None
        return resp[2]

    def _probe_daq_caps(self) -> DaqCaps | None:
        proc = self._optional(bytes([Cmd.GET_DAQ_PROCESSOR_INFO]))
        res = self._optional(bytes([Cmd.GET_DAQ_RESOLUTION_INFO]))
        if proc is None or res is None or len(proc) < 8 or len(res) < 8:
            return None

        order = self._caps.byte_order if self._caps else "little"
        properties = proc[1]
        ts_mode = res[5]
        ts_size = ts_mode & 0x07
        ts_unit_code = (ts_mode >> 4) & 0x0F

        return DaqCaps(
            max_daq=int.from_bytes(proc[2:4], order),        # type: ignore[arg-type]
            max_event_channel=int.from_bytes(proc[4:6], order),  # type: ignore[arg-type]
            min_daq=proc[6],
            dynamic_daq=bool(properties & 0x01),
            timestamp_supported=ts_size != 0,
            timestamp_size=ts_size,
            timestamp_unit_ns=TIMESTAMP_UNIT_NS.get(ts_unit_code, 0),
            timestamp_ticks=int.from_bytes(res[6:8], order),  # type: ignore[arg-type]
            pid_off_supported=bool(properties & 0x20),
            granularity_odt_entry_daq=res[1],
            max_odt_entry_size_daq=res[2],
        )

    def _probe_id(self, caps: SlaveCaps) -> str | None:
        """GET_ID type 1 (tên file ASAM-MC2). Nhiều ECU tắt lệnh này."""
        resp = self._optional(bytes([Cmd.GET_ID, 0x01]))
        if resp is None or len(resp) < 8:
            return None
        length = int.from_bytes(resp[4:8], caps.byte_order)  # type: ignore[arg-type]
        if not 0 < length <= 255:
            return None
        try:
            raw = self._read_locked(length, caps)
        except XcpToolError:
            return None
        return raw.decode("latin-1").rstrip("\x00").strip() or None

    def disconnect(self) -> None:
        """Êm nếu vốn đã disconnected — contract yêu cầu thế."""
        if self._state is not ConnState.CONNECTED:
            self._state = (ConnState.ERROR if self._rx_error
                           else ConnState.DISCONNECTED)
            return
        try:
            self._locked_transact(
                bytes([Cmd.DISCONNECT]),
                raise_on_error=True, timeout=None, retry=False)
        finally:
            self._state = (ConnState.ERROR if self._rx_error
                           else ConnState.DISCONNECTED)
            self._caps = None

    def _final_disconnect(self, wait_s: float) -> None:
        """Cố gửi DISCONNECT lúc đóng — không thì ECU cứ bắn DAQ lên bus tiếp.

        Chờ có giới hạn để lấy quyền dùng bus: nếu một lệnh khác đang chạy (user
        đóng app giữa lúc đang đọc), thà bỏ DISCONNECT còn hơn treo lúc thoát.
        """
        if self._state is not ConnState.CONNECTED:
            return
        acquired = self._cmd_lock.acquire(timeout=wait_s)
        try:
            if not acquired:
                log.warning("Bỏ DISCONNECT lúc đóng: bus đang bận")
                return
            self._exchange(bytes([Cmd.DISCONNECT]), raise_on_error=False,
                           timeout=self._cfg.t1_timeout_s, retry=False)
        except Exception:  # noqa: BLE001 — đang trên đường thoát
            log.debug("DISCONNECT lúc đóng thất bại", exc_info=True)
        finally:
            self._pending_cmd = None
            if acquired:
                self._cmd_lock.release()

    def close(self, disconnect_wait_s: float = 1.0) -> None:
        """Dừng RX thread và đóng link. Idempotent, không bao giờ ném."""
        try:
            self._final_disconnect(disconnect_wait_s)
        except Exception:  # noqa: BLE001
            log.exception("Lỗi khi DISCONNECT lúc đóng, đã nuốt")
        self._state = ConnState.DISCONNECTED if self._rx_error is None \
            else ConnState.ERROR
        self._caps = None
        self._stop.set()
        try:
            self._responses.put_nowait(_Sentinel(BusError("Phiên đã đóng")))
        except queue.Full:
            pass
        if self._rx_thread.is_alive():
            self._rx_thread.join(timeout=2.0)
            if self._rx_thread.is_alive():
                log.warning("RX thread không kết thúc trong 2s — bỏ lại (daemon)")
        try:
            self._link.close()
        except Exception:  # noqa: BLE001 — close() không bao giờ được ném
            log.exception("Lỗi khi đóng link, đã nuốt")
        if self._state is not ConnState.ERROR:
            self._state = ConnState.DISCONNECTED

    # ── bộ nhớ ───────────────────────────────────────────────────────────────

    def _require_caps(self) -> SlaveCaps:
        caps = self._caps
        if caps is None or self._state is not ConnState.CONNECTED:
            self._check_link_alive()
            raise NotConnectedError("Chưa CONNECT tới ECU")
        return caps

    def _cto_len(self, caps: SlaveCaps) -> int:
        """CTO dùng được thật: ECU khai bao nhiêu cũng không vượt được một frame."""
        return min(caps.max_cto, getattr(self._link, "max_frame_len", 8))

    def _set_mta(self, addr: int, ext: int, caps: SlaveCaps) -> None:
        payload = bytes([Cmd.SET_MTA, 0, 0, ext & 0xFF]) + pack_u32(addr, caps.byte_order)
        self._locked_transact(payload, raise_on_error=True, timeout=None, retry=True)

    def _upload_chunk(self, size: int) -> bytes:
        resp = self._locked_transact(
            bytes([Cmd.UPLOAD, size]), raise_on_error=True, timeout=None, retry=True)
        if len(resp) < 1 + size:
            raise MalformedResponseError(
                f"UPLOAD {size} byte nhưng ECU chỉ trả {max(len(resp) - 1, 0)}: "
                f"{hexs(resp)}")
        return resp[1:1 + size]

    def _read_locked(self, size: int, caps: SlaveCaps) -> bytes:
        """UPLOAD từ MTA hiện tại — dùng khi ECU đã tự đặt MTA (vd. GET_ID)."""
        out = bytearray()
        chunk = self._cto_len(caps) - 1
        while len(out) < size:
            out += self._upload_chunk(min(chunk, size - len(out)))
        return bytes(out)

    def read(self, addr: int, size: int, ext: int = 0) -> bytes:
        caps = self._require_caps()
        if size < 0:
            raise ValueError("size không được âm")
        if size == 0:
            return b""

        max_chunk = self._cto_len(caps) - 1

        if size <= max_chunk:
            # Một lệnh duy nhất — rẻ hơn SET_MTA + UPLOAD (hai lệnh).
            payload = (bytes([Cmd.SHORT_UPLOAD, size, 0, ext & 0xFF])
                       + pack_u32(addr, caps.byte_order))
            resp = self._locked_transact(
                payload, raise_on_error=True, timeout=None, retry=True)
            if len(resp) < 1 + size:
                raise MalformedResponseError(
                    f"SHORT_UPLOAD {size} byte nhưng ECU trả "
                    f"{max(len(resp) - 1, 0)}: {hexs(resp)}")
            return resp[1:1 + size]

        # Khối dài: đặt MTA một lần, MTA tự tăng sau mỗi UPLOAD.
        self._set_mta(addr, ext, caps)
        return self._read_locked(size, caps)

    def write(self, addr: int, data: bytes, ext: int = 0) -> None:
        caps = self._require_caps()
        payload = bytes(data)
        if not payload:
            return

        # SHORT_DOWNLOAD mang được MAX_CTO-8 byte; với MAX_CTO=8 là 0 byte,
        # nên đường SET_MTA + DOWNLOAD mới là đường chính trên CAN.
        short_capacity = self._cto_len(caps) - 8
        if len(payload) <= short_capacity:
            cro = (bytes([Cmd.SHORT_DOWNLOAD, len(payload), 0, ext & 0xFF])
                   + pack_u32(addr, caps.byte_order) + payload)
            self._locked_transact(cro, raise_on_error=True, timeout=None, retry=True)
            return

        self._set_mta(addr, ext, caps)
        chunk = self._cto_len(caps) - 2
        for off in range(0, len(payload), chunk):
            part = payload[off:off + chunk]
            self._locked_transact(
                bytes([Cmd.DOWNLOAD, len(part)]) + part,
                raise_on_error=True, timeout=None, retry=True)

    # ── trang calibration ────────────────────────────────────────────────────

    def _require_cal_pag(self) -> SlaveCaps:
        caps = self._require_caps()
        if not caps.supports_cal_pag:
            raise UnsupportedByEcuError("CAL/PAG (chuyển trang calibration)")
        return caps

    def get_page(self, segment: int, mode: PageMode) -> int:
        self._require_cal_pag()
        resp = self._locked_transact(
            bytes([Cmd.GET_CAL_PAGE, mode.value, segment & 0xFF]),
            raise_on_error=True, timeout=None, retry=True)
        if len(resp) < 4:
            raise MalformedResponseError(
                f"Response GET_CAL_PAGE cần 4 byte, ECU trả {len(resp)}: {hexs(resp)}")
        return resp[3]

    def set_page(self, segment: int, page: int, mode: PageMode) -> None:
        self._require_cal_pag()
        self._locked_transact(
            bytes([Cmd.SET_CAL_PAGE, mode.value, segment & 0xFF, page & 0xFF]),
            raise_on_error=True, timeout=None, retry=True)

    def copy_page(
        self, src_segment: int, src_page: int, dst_segment: int, dst_page: int
    ) -> None:
        self._require_cal_pag()
        self._locked_transact(
            bytes([Cmd.COPY_CAL_PAGE, src_segment & 0xFF, src_page & 0xFF,
                   dst_segment & 0xFF, dst_page & 0xFF]),
            raise_on_error=True, timeout=None, retry=True)

    # ── DAQ ──────────────────────────────────────────────────────────────────

    def _require_daq(self) -> SlaveCaps:
        caps = self._require_caps()
        if not caps.supports_daq:
            raise UnsupportedByEcuError("DAQ")
        return caps

    def free_daq(self) -> None:
        """FREE_DAQ — xoá sạch cấu hình DAQ trên ECU. Bắt buộc trước ALLOC_DAQ."""
        self._require_daq()
        self._locked_transact(
            bytes([Cmd.FREE_DAQ, 0x00]),
            raise_on_error=True, timeout=None, retry=False)

    def alloc_daq(self, count: int) -> None:
        """ALLOC_DAQ — cấp phát `count` DAQ list."""
        caps = self._require_daq()
        self._locked_transact(
            bytes([Cmd.ALLOC_DAQ, 0x00]) + count.to_bytes(2, caps.byte_order),
            raise_on_error=True, timeout=None, retry=False)

    def alloc_odt(self, daq: int, count: int) -> None:
        """ALLOC_ODT — cấp phát `count` ODT cho DAQ list `daq`."""
        caps = self._require_daq()
        self._locked_transact(
            bytes([Cmd.ALLOC_ODT, 0x00]) + daq.to_bytes(2, caps.byte_order) + bytes([count]),
            raise_on_error=True, timeout=None, retry=False)

    def alloc_odt_entry(self, daq: int, odt: int, count: int) -> None:
        """ALLOC_ODT_ENTRY — cấp phát `count` entry cho ODT `odt` của list `daq`."""
        caps = self._require_daq()
        self._locked_transact(
            bytes([Cmd.ALLOC_ODT_ENTRY, 0x00])
            + daq.to_bytes(2, caps.byte_order)
            + bytes([odt, count]),
            raise_on_error=True, timeout=None, retry=False)

    def set_daq_ptr(self, daq: int, odt: int, entry: int) -> None:
        """SET_DAQ_PTR — đặt con trỏ ghi cho chuỗi WRITE_DAQ tiếp theo."""
        caps = self._require_daq()
        self._locked_transact(
            bytes([Cmd.SET_DAQ_PTR, 0x00])
            + daq.to_bytes(2, caps.byte_order)
            + bytes([odt, entry]),
            raise_on_error=True, timeout=None, retry=False)

    def write_daq(self, bit_offset: int, size: int, ext: int, addr: int) -> None:
        """WRITE_DAQ — ghi một entry vào ODT tại con trỏ hiện tại rồi tự tăng.

        bit_offset: 0xFF = không dùng bit masking (đọc toàn byte).
        """
        caps = self._require_daq()
        self._locked_transact(
            bytes([Cmd.WRITE_DAQ, bit_offset & 0xFF, size & 0xFF, ext & 0xFF])
            + pack_u32(addr, caps.byte_order),
            raise_on_error=True, timeout=None, retry=False)

    def set_daq_list_mode(
        self, daq: int, event: int,
        mode: int = 0x10, prescaler: int = 1, prio: int = 0
    ) -> None:
        """SET_DAQ_LIST_MODE — cấu hình event/mode/prescaler cho DAQ list.

        mode bits: bit4=0x10 bật timestamp; bit0=0 là DAQ (không phải STIM).
        """
        caps = self._require_daq()
        self._locked_transact(
            bytes([Cmd.SET_DAQ_LIST_MODE, mode & 0xFF])
            + daq.to_bytes(2, caps.byte_order)
            + event.to_bytes(2, caps.byte_order)
            + bytes([prescaler & 0xFF, prio & 0xFF]),
            raise_on_error=True, timeout=None, retry=False)

    def start_stop_daq_list(self, mode: int, daq: int) -> int:
        """START_STOP_DAQ_LIST — mode 2 = select (trả firstPid); 1=start; 0=stop."""
        caps = self._require_daq()
        resp = self._locked_transact(
            bytes([Cmd.START_STOP_DAQ_LIST, mode & 0xFF]) + daq.to_bytes(2, caps.byte_order),
            raise_on_error=True, timeout=None, retry=False)
        if len(resp) < 2:
            raise MalformedResponseError(
                f"Response START_STOP_DAQ_LIST cần ≥2 byte, ECU trả {len(resp)}: {hexs(resp)}")
        return resp[1]

    def start_stop_synch(self, mode: int) -> None:
        """START_STOP_SYNCH — mode 1 = khởi động đồng loạt; 0 = dừng tất cả."""
        self._require_daq()
        self._locked_transact(
            bytes([Cmd.START_STOP_SYNCH, mode & 0xFF]),
            raise_on_error=True, timeout=None, retry=False)

    # ── lệnh thô ─────────────────────────────────────────────────────────────

    def raw_command(self, payload: bytes, raise_on_error: bool = False) -> bytes:
        if not payload:
            raise ValueError("payload rỗng")
        return self.transact(
            bytes(payload), raise_on_error=raise_on_error, timeout=None, retry=False)
