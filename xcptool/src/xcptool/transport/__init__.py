"""Tầng transport — nơi duy nhất biết CAN là gì.

`master/` không được import gì ở đây; nó chỉ dùng duck typing trên
`send` / `recv` / `close`. Test ranh giới cưỡng chế luật này.
"""

from __future__ import annotations

from .base import BackendSpec, CanFrame, Transport
from .config import (
    DEFAULT_BUS_CONFIG,
    config_path,
    load_bus_config,
    save_bus_config,
)
from .registry import SPECS, backend_names, get_spec, list_devices, open_transport

__all__ = [
    "BackendSpec", "CanFrame", "Transport",
    "DEFAULT_BUS_CONFIG", "config_path", "load_bus_config", "save_bus_config",
    "SPECS", "backend_names", "get_spec", "list_devices", "open_transport",
]
