"""PEAK PCAN-USB và họ hàng."""

from __future__ import annotations

from ..session.api import BusConfig
from .base import BackendSpec, Transport
from .pycan import PyCanTransport, open_pycan_bus

__all__ = ["SPEC"]


def _open(cfg: BusConfig) -> Transport:
    return PyCanTransport(open_pycan_bus("pcan", cfg, SPEC.package_hint), cfg)


SPEC = BackendSpec(
    name="pcan",
    can_interface="pcan",
    label="PEAK PCAN",
    package_hint="driver PCAN-Basic của PEAK (PCANBasic.dll / libpcanbasic.so)",
    open=_open,
    default_channel="PCAN_USBBUS1",
    log_needles=("pcan", "PCANBasic"),
)
