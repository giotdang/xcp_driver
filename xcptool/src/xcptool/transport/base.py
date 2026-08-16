"""Giao diện transport — tầng duy nhất biết CAN là gì.

`master/` không import gì ở đây (test ranh giới cấm); nó chỉ dùng duck typing
trên ba phương thức `send` / `recv` / `close`.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field

from ..session.api import BusConfig

__all__ = ["CanFrame", "Transport", "BackendSpec"]


@dataclass(frozen=True, slots=True)
class CanFrame:
    can_id: int
    data: bytes
    t_mono: float
    """time.perf_counter() lúc nhận — cùng thang với TraceEntry.t_mono."""

    dev_timestamp: float | None = None
    """Timestamp do thiết bị sinh. Chất lượng khác nhau theo hãng: PEAK/Vector
    có phần cứng, slcan do phần mềm sinh, virtual không có. Đừng giả định đồng
    nhất giữa các backend."""


class Transport(abc.ABC):
    """Một kênh CAN đã mở. Không biết XCP là gì."""

    max_frame_len: int = 8
    """Số byte tối đa một frame chở được. CAN cổ điển là 8.

    ECU vẫn có thể khai MAX_CTO > 8 (giá trị đó có nghĩa với XCP trên Ethernet).
    Master phải lấy min của hai số, nếu không sẽ hỏi ECU nhiều byte hơn mức
    một frame CAN chở nổi.
    """

    @abc.abstractmethod
    def send(self, can_id: int, data: bytes) -> bytes:
        """Đẩy một frame lên bus, trả về đúng chuỗi byte đã lên dây (đã đệm).

        Raises: BusError, DeviceNotFoundError
        """

    @abc.abstractmethod
    def recv(self, timeout: float) -> CanFrame | None:
        """Chờ tối đa `timeout` giây. `None` nghĩa là hết giờ, không phải lỗi.

        Raises: BusError, DeviceNotFoundError
        """

    @abc.abstractmethod
    def close(self) -> None:
        """Giải phóng thiết bị. Idempotent, không bao giờ ném."""


@dataclass(frozen=True)
class BackendSpec:
    """Mô tả một backend CAN. Thêm hãng mới = thêm một spec, không đụng master/."""

    name: str
    """Tên trong `BusConfig.backend` và trong config.toml."""

    can_interface: str
    """Tên `interface=` của python-can. Rỗng nghĩa là không qua python-can."""

    label: str
    """Tên hiển thị cho combo box."""

    package_hint: str
    """Cần cài gì để dùng được — nội dung của `DeviceInfo.hint` khi thiếu."""

    open: Callable[[BusConfig], Transport]

    default_channel: str = ""

    platforms: tuple[str, ...] = ()
    """`sys.platform` được hỗ trợ. Rỗng = mọi nền tảng."""

    log_needles: tuple[str, ...] = field(default_factory=tuple)
    """Mẩu chuỗi để nhặt đúng dòng cảnh báo của python-can thuộc backend này."""

    always_available: bool = False
    """True cho backend không cần phần cứng (virtual, replay)."""
