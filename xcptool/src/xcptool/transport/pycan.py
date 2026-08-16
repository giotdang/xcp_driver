"""Transport dựng trên python-can — dùng chung cho pcan/vector/etas/slcan/virtual.

Thêm một hãng CAN mới là thêm một `BackendSpec` trong `registry.py`, không phải
viết lại lớp này.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import can

from ..session.api import (
    BusConfig,
    BusError,
    DeviceNotFoundError,
    DriverMissingError,
)
from .base import CanFrame, Transport

__all__ = ["PyCanTransport", "open_pycan_bus"]

_MAX_DLC = 8


def open_pycan_bus(
    interface: str, cfg: BusConfig, package_hint: str, **extra: Any
) -> can.BusABC:
    """Mở `can.Bus` và quy mọi lỗi về cây ngoại lệ của contract."""
    kwargs: dict[str, Any] = {"interface": interface, "channel": cfg.channel, **extra}
    if interface != "virtual":
        kwargs["bitrate"] = cfg.bitrate
    try:
        return can.Bus(**kwargs)
    except can.CanInterfaceNotImplementedError as exc:
        raise DriverMissingError(interface, package_hint) from exc
    except can.CanInitializationError as exc:
        raise DeviceNotFoundError(
            f"Không mở được kênh '{cfg.channel}' trên backend '{interface}': {exc}"
        ) from exc
    except can.CanError as exc:
        raise BusError(f"Lỗi bus khi mở '{interface}': {exc}") from exc
    except (OSError, ValueError) as exc:
        raise DeviceNotFoundError(
            f"Không mở được kênh '{cfg.channel}' trên backend '{interface}': {exc}"
        ) from exc


class PyCanTransport(Transport):
    def __init__(self, bus: can.BusABC, cfg: BusConfig) -> None:
        self._bus = bus
        self._cfg = cfg
        self._closed = False
        self._send_lock = threading.Lock()

    def send(self, can_id: int, data: bytes) -> bytes:
        payload = bytes(data)
        if self._cfg.pad_dlc and len(payload) < _MAX_DLC:
            # ECU khai MAX_DLC_REQUIRED → đệm đủ 8 byte kể cả lệnh 1 byte.
            payload = payload.ljust(_MAX_DLC, b"\x00")
        msg = can.Message(
            arbitration_id=can_id,
            data=payload,
            is_extended_id=self._cfg.extended_id,
        )
        try:
            with self._send_lock:
                if self._closed:
                    raise BusError("Bus đã đóng")
                self._bus.send(msg, timeout=self._cfg.t1_timeout_s)
        except can.CanOperationError as exc:
            raise BusError(f"Không gửi được frame: {exc}") from exc
        except can.CanError as exc:
            raise BusError(f"Lỗi bus khi gửi: {exc}") from exc
        except OSError as exc:
            raise DeviceNotFoundError(f"Thiết bị biến mất khi gửi: {exc}") from exc
        return payload

    def recv(self, timeout: float) -> CanFrame | None:
        deadline = time.perf_counter() + timeout
        while True:
            if self._closed:
                return None
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return None
            try:
                msg = self._bus.recv(remaining)
            except can.CanOperationError as exc:
                raise BusError(f"Lỗi bus khi nhận: {exc}") from exc
            except can.CanError as exc:
                raise BusError(f"Lỗi bus khi nhận: {exc}") from exc
            except OSError as exc:
                raise DeviceNotFoundError(f"Thiết bị biến mất khi nhận: {exc}") from exc
            if msg is None:
                return None
            if msg.is_error_frame or msg.is_remote_frame:
                continue
            return CanFrame(
                can_id=msg.arbitration_id,
                data=bytes(msg.data),
                t_mono=time.perf_counter(),
                dev_timestamp=msg.timestamp,
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._bus.shutdown()
        except Exception:  # noqa: BLE001 — close() không bao giờ được ném
            pass
