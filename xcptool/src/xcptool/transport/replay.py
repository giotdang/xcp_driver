"""Phát lại một file trace đã ghi — debug offline, không cần bus.

Định dạng: mỗi dòng `<t_mono> <tx|rx> <can_id_hex> <byte hex cách nhau>`, đúng
thứ tự cột mà cửa sổ debug xuất ra. Dòng trống và dòng bắt đầu bằng `#` bị bỏ qua.
`BusConfig.channel` là đường dẫn tới file.

Chỉ frame `rx` được phát lại; frame `tx` trong file là của phiên cũ, không phải
của phiên đang chạy.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from ..session.api import BusConfig, DeviceNotFoundError
from .base import BackendSpec, CanFrame, Transport

__all__ = ["SPEC", "ReplayTransport", "parse_trace_log"]


def parse_trace_log(text: str) -> list[tuple[float, int, bytes]]:
    """`(t_mono, can_id, data)` cho các dòng hướng rx. Dòng hỏng bị bỏ qua."""
    out: list[tuple[float, int, bytes]] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 3 or parts[1].lower() != "rx":
            continue
        try:
            t = float(parts[0])
            can_id = int(parts[2], 16)
            data = bytes(int(b, 16) for b in parts[3:])
        except ValueError:
            continue
        out.append((t, can_id, data))
    return out


class ReplayTransport(Transport):
    def __init__(self, frames: list[tuple[float, int, bytes]], realtime: bool = True):
        self._frames = frames
        self._realtime = realtime
        self._index = 0
        self._closed = False
        self._lock = threading.Lock()
        self._t0_file = frames[0][0] if frames else 0.0
        self._t0_wall = time.perf_counter()

    def send(self, can_id: int, data: bytes) -> bytes:
        # Không có ai ở đầu kia. Frame vẫn được ghi trace bởi tầng trên.
        return bytes(data)

    def recv(self, timeout: float) -> CanFrame | None:
        deadline = time.perf_counter() + timeout
        while not self._closed:
            with self._lock:
                if self._index >= len(self._frames):
                    frame = None
                else:
                    frame = self._frames[self._index]
            if frame is None:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    return None
                time.sleep(min(remaining, 0.02))
                continue

            t_file, can_id, data = frame
            due = self._t0_wall + (t_file - self._t0_file) if self._realtime else 0.0
            now = time.perf_counter()
            if self._realtime and due > now:
                if due > deadline:
                    time.sleep(max(0.0, min(deadline - now, 0.02)))
                    if time.perf_counter() >= deadline:
                        return None
                    continue
                time.sleep(due - now)
            with self._lock:
                self._index += 1
            return CanFrame(
                can_id=can_id, data=data, t_mono=time.perf_counter(), dev_timestamp=t_file
            )
        return None

    def close(self) -> None:
        self._closed = True


def _open(cfg: BusConfig) -> Transport:
    path = Path(cfg.channel)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DeviceNotFoundError(f"Không đọc được file trace '{path}': {exc}") from exc
    return ReplayTransport(parse_trace_log(text))


SPEC = BackendSpec(
    name="replay",
    can_interface="",
    label="Phát lại file trace (offline)",
    package_hint="không cần cài gì — channel là đường dẫn tới file trace",
    open=_open,
    default_channel="",
    always_available=True,
)
