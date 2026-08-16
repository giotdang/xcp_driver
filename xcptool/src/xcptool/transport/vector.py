"""Vector VN16xx / CANcase qua XL Driver Library."""

from __future__ import annotations

from ..session.api import BusConfig
from .base import BackendSpec, Transport
from .pycan import PyCanTransport, open_pycan_bus

__all__ = ["SPEC"]


def _open(cfg: BusConfig) -> Transport:
    return PyCanTransport(open_pycan_bus("vector", cfg, SPEC.package_hint), cfg)


SPEC = BackendSpec(
    name="vector",
    can_interface="vector",
    label="Vector XL",
    package_hint="Vector XL Driver Library (vxlapi64.dll) — cài kèm Vector Driver Setup",
    open=_open,
    default_channel="0",
    platforms=("win32",),
    log_needles=("vector", "vxlapi"),
)
