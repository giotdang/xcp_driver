"""Bảng đăng ký backend + dò thiết bị.

`list_devices()` KHÔNG BAO GIỜ ném và KHÔNG BAO GIỜ để lọt cảnh báo của
python-can ra stderr. Backend thiếu driver vẫn xuất hiện trong danh sách với
`available=False` và `hint` nói rõ cần cài gì — im lặng bỏ qua là thiết kế tồi,
đây là lỗi user gặp nhiều nhất với công cụ loại này.
"""

from __future__ import annotations

import sys
from typing import Any

from ..session.api import BusConfig, DeviceInfo, DriverMissingError
from . import etas, pcan, replay, slcan, vector, virtual
from .base import BackendSpec, Transport
from .quiet import capture_can_logs

__all__ = ["SPECS", "backend_names", "get_spec", "open_transport", "list_devices"]

SPECS: dict[str, BackendSpec] = {
    spec.name: spec
    for spec in (virtual.SPEC, pcan.SPEC, vector.SPEC, etas.SPEC, slcan.SPEC, replay.SPEC)
}

# Cảnh báo lúc import backend chỉ phát ra ở lần dò ĐẦU TIÊN trong tiến trình.
# Giữ lại để lần gọi list_devices() thứ hai vẫn có hint như lần đầu.
_HINT_CACHE: dict[str, str] = {}


def backend_names() -> list[str]:
    return list(SPECS)


def get_spec(name: str) -> BackendSpec:
    try:
        return SPECS[name]
    except KeyError:
        raise DriverMissingError(
            name, f"backend không tồn tại — chọn một trong {', '.join(SPECS)}"
        ) from None


def open_transport(cfg: BusConfig) -> Transport:
    """Mở kênh theo cấu hình. Raises: DriverMissingError, DeviceNotFoundError, BusError"""
    return get_spec(cfg.backend).open(cfg)


def _detect() -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Dò thiết bị trong im lặng. Trả về (channel theo backend, hint theo backend)."""
    by_interface: dict[str, list[dict[str, Any]]] = {}
    hints: dict[str, str] = {}
    try:
        import can
    except ImportError:
        return by_interface, hints

    with capture_can_logs() as captured:
        try:
            configs = can.detect_available_configs()
        except Exception:  # noqa: BLE001 — dò thiết bị không được làm sập app
            configs = []

    for cfg in configs:
        iface = str(cfg.get("interface", ""))
        by_interface.setdefault(iface, []).append(dict(cfg))

    for spec in SPECS.values():
        if not spec.log_needles:
            continue
        lines = captured.messages_for(*spec.log_needles)
        if lines:
            hints[spec.name] = lines[0]
    return by_interface, hints


def _unavailable_hint(spec: BackendSpec, detected_hint: str | None) -> str:
    if spec.platforms and sys.platform not in spec.platforms:
        return f"Chỉ chạy trên {', '.join(spec.platforms)} — máy này là {sys.platform}."
    cached = detected_hint or _HINT_CACHE.get(spec.name)
    if cached:
        _HINT_CACHE[spec.name] = cached
        return f"{cached.rstrip('.')}. Cần: {spec.package_hint}."
    return f"Chưa dò thấy thiết bị nào. Cần: {spec.package_hint}."


def list_devices() -> list[DeviceInfo]:
    by_interface, hints = _detect()
    out: list[DeviceInfo] = []

    for spec in SPECS.values():
        if spec.always_available:
            out.append(DeviceInfo(
                backend=spec.name,
                channel=spec.default_channel,
                display_name=spec.label,
                available=True,
                hint=None if spec.name != "replay" else "Chọn file trace ở ô channel.",
            ))
            continue

        found = by_interface.get(spec.can_interface, [])
        if not found:
            out.append(DeviceInfo(
                backend=spec.name,
                channel=spec.default_channel,
                display_name=f"{spec.label} (chưa dùng được)",
                available=False,
                hint=_unavailable_hint(spec, hints.get(spec.name)),
            ))
            continue

        for cfg in found:
            channel = str(cfg.get("channel", spec.default_channel))
            serial = cfg.get("serial") or cfg.get("device_id")
            out.append(DeviceInfo(
                backend=spec.name,
                channel=channel,
                display_name=f"{spec.label} — {channel}",
                available=True,
                serial=str(serial) if serial is not None else None,
            ))

    return out
