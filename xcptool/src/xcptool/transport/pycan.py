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
from .base import CanFrame, Transport, round_to_can_fd_dlc

__all__ = ["PyCanTransport", "open_pycan_bus"]


def open_pycan_bus(
    interface: str, cfg: BusConfig, package_hint: str, **extra: Any
) -> can.BusABC:
    """Mở `can.Bus` và quy mọi lỗi về cây ngoại lệ của contract."""
    kwargs: dict[str, Any] = {"interface": interface, "channel": cfg.channel, **extra}
    if cfg.is_fd:
        kwargs["fd"] = True
    if interface != "virtual":
        kwargs["bitrate"] = cfg.bitrate
        if cfg.is_fd:
            kwargs["data_bitrate"] = cfg.data_bitrate
            
        if cfg.custom_bit_timing:
            if cfg.is_fd:
                kwargs["timing"] = can.BitTimingFd(
                    f_clock=80_000_000, brp=cfg.brp, tseg1=cfg.tseg1, tseg2=cfg.tseg2, sjw=cfg.sjw,
                    dbrp=cfg.dbrp, dtseg1=cfg.dtseg1, dtseg2=cfg.dtseg2, dsjw=cfg.dsjw
                )
            else:
                kwargs["timing"] = can.BitTiming(
                    f_clock=80_000_000, brp=cfg.brp, tseg1=cfg.tseg1, tseg2=cfg.tseg2, sjw=cfg.sjw, nosamp=1
                )
            
    # Filter out non-XCP frames at the hardware/OS level
    mask = 0x1FFFFFFF if cfg.extended_id else 0x7FF
    kwargs["can_filters"] = [{"can_id": cfg.dto_id, "can_mask": mask, "extended": cfg.extended_id}]

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
        self.max_frame_len = 64 if cfg.is_fd else 8

    def send(self, can_id: int, data: bytes) -> bytes:
        payload = bytes(data)
        if self._cfg.is_fd:
            # CAN FD: tự động làm tròn lên nấc DLC hợp lệ (0..8, 12, 16, 20, 24, 32, 48, 64)
            target_len = round_to_can_fd_dlc(len(payload))
            if self._cfg.pad_dlc:
                target_len = 64
            if len(payload) < target_len:
                payload = payload.ljust(target_len, b"\x00")
        else:
            # Classic CAN: đệm 8 byte nếu ECU yêu cầu MAX_DLC_REQUIRED
            max_len = 8
            if self._cfg.pad_dlc and len(payload) < max_len:
                payload = payload.ljust(max_len, b"\x00")

        msg = can.Message(
            arbitration_id=can_id,
            data=payload,
            is_extended_id=self._cfg.extended_id,
            is_fd=self._cfg.is_fd,
            bitrate_switch=self._cfg.is_fd,
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
