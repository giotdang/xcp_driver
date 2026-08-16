"""ETAS ES58x / ES5xx qua BOA (Windows only)."""

from __future__ import annotations

from ..session.api import BusConfig
from .base import BackendSpec, Transport
from .pycan import PyCanTransport, open_pycan_bus

__all__ = ["SPEC"]


def _open(cfg: BusConfig) -> Transport:
    return PyCanTransport(open_pycan_bus("etas", cfg, SPEC.package_hint), cfg)


SPEC = BackendSpec(
    name="etas",
    can_interface="etas",
    label="ETAS ES58x / ES5xx",
    package_hint="ETAS Distribution Package (BOA) — chỉ có bản Windows",
    open=_open,
    default_channel="ETAS://USB/ES581.4:0/CAN:1",
    platforms=("win32",),
    log_needles=("etas", "boa"),
)
