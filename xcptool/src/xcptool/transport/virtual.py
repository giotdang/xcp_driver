"""Bus ảo trong tiến trình — nền của mọi test backend.

`can.Bus(interface='virtual')` nối các bus cùng `channel` trong cùng tiến trình.
Đường code của tầng transport y hệt lúc cắm phần cứng thật, nên test ở đây có
giá trị thật chứ không chỉ là mock.
"""

from __future__ import annotations

from ..session.api import BusConfig
from .base import BackendSpec, Transport
from .pycan import PyCanTransport, open_pycan_bus

__all__ = ["SPEC", "open_virtual"]

DEFAULT_CHANNEL = "xcptool"


def open_virtual(cfg: BusConfig) -> Transport:
    bus = open_pycan_bus(
        "virtual", cfg, SPEC.package_hint,
        # Không receive_own_messages: master và fake slave là hai bus riêng,
        # nghe lại frame của chính mình sẽ tự trả lời chính mình.
        receive_own_messages=False,
    )
    return PyCanTransport(bus, cfg)


SPEC = BackendSpec(
    name="virtual",
    can_interface="virtual",
    label="Virtual bus (nội bộ, không cần phần cứng)",
    package_hint="không cần cài gì",
    open=open_virtual,
    default_channel=DEFAULT_CHANNEL,
    always_available=True,
)
