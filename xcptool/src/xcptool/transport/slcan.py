"""CANable / CANtact và các adapter slcan trên cổng COM ảo.

Cảnh báo về chất lượng timestamp: slcan sinh timestamp bằng phần mềm trên PC,
không phải phần cứng như PEAK/Vector. Đừng dùng nó để đo jitter của ECU.
"""

from __future__ import annotations

from ..session.api import BusConfig
from .base import BackendSpec, Transport
from .pycan import PyCanTransport, open_pycan_bus

__all__ = ["SPEC"]


def _open(cfg: BusConfig) -> Transport:
    return PyCanTransport(open_pycan_bus("slcan", cfg, SPEC.package_hint), cfg)


SPEC = BackendSpec(
    name="slcan",
    can_interface="slcan",
    label="slcan / CANable (COM ảo)",
    package_hint="gói Python `pyserial` (pip install xcptool[slcan]) và driver COM ảo",
    open=_open,
    default_channel="COM3",
    log_needles=("slcan", "pyserial", "serial module"),
)
