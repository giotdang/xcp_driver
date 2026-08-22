"""Đọc/ghi `config.toml`.

Đây là module DUY NHẤT (cùng `session/api.py`) được phép chứa giá trị mặc định
mang đặc tính ECU — CAN ID, bitrate. Chúng là *điểm khởi đầu tiện tay cho user*,
không phải giả định của logic. Test ranh giới `test_no_hardcoded_ecu_constants`
cho phép file này đúng vì lý do đó.

Stdlib có `tomllib` để đọc nhưng không có bộ ghi. Schema ở đây phẳng và biết
trước, nên ghi bằng tay vài dòng rẻ hơn thêm một dependency.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import replace
from pathlib import Path

from ..session.api import AppConfig, BusConfig

__all__ = [
    "DEFAULT_BUS_CONFIG", "DEFAULT_APP_CONFIG", "config_dir", "config_path",
    "load_bus_config", "save_bus_config", "dumps_bus_config",
    "load_app_config", "save_app_config", "dumps_app_config",
]

DEFAULT_BUS_CONFIG = BusConfig(
    backend="virtual",
    channel="xcptool",
    bitrate=500_000,
    cro_id=0x7E0,
    dto_id=0x7E1,
    extended_id=False,
    pad_dlc=True,
    t1_timeout_s=1.0,
    is_fd=False,
    data_bitrate=2_000_000,
)

DEFAULT_APP_CONFIG = AppConfig(
    bus=DEFAULT_BUS_CONFIG,
    last_a2l_path="",
    scope_enabled=True,
    trace_row_limit=20_000,
    active_route="calibration",
    dock_state="",
    debug_area_collapsed=False,
    trace_visible_kinds=["cmd", "res", "err", "ev", "serv", "other"],
)

_ENV_DIR = "XCPTOOL_HOME"


def config_dir() -> Path:
    """`thư mục hiện tại`, hoặc `$XCPTOOL_HOME` khi được đặt (test dùng lối này)."""
    override = os.environ.get(_ENV_DIR)
    return Path(override) if override else Path.cwd()


def config_path() -> Path:
    return config_dir() / "config.toml"


def _coerce_bus(raw: dict[str, object], base: BusConfig) -> BusConfig:
    """Nhặt đúng các khoá hiểu được cho bus, bỏ qua phần thừa và phần sai kiểu."""
    fields: dict[str, object] = {}
    for key, kind in (
        ("backend", str), ("channel", str), ("bitrate", int),
        ("cro_id", int), ("dto_id", int), ("extended_id", bool),
        ("pad_dlc", bool), ("t1_timeout_s", float),
        ("is_fd", bool), ("data_bitrate", int),
        ("custom_bit_timing", bool), ("f_clock", int),
        ("brp", int), ("tseg1", int), ("tseg2", int), ("sjw", int),
        ("dbrp", int), ("dtseg1", int), ("dtseg2", int), ("dsjw", int),
    ):
        if key not in raw:
            continue
        value = raw[key]
        if kind is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        # bool là con của int trong Python — chặn 'bitrate = true' lọt qua.
        if kind is int and isinstance(value, bool):
            continue
        if isinstance(value, kind):
            fields[key] = value
    return replace(base, **fields)  # type: ignore[arg-type]


def load_bus_config(default: BusConfig | None = None) -> BusConfig:
    """Đọc cấu hình bus đã lưu. File thiếu hoặc hỏng → trả mặc định, không ném."""
    base = default or DEFAULT_BUS_CONFIG
    path = config_path()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return base
    section = raw.get("bus")
    if not isinstance(section, dict):
        return base
    return _coerce_bus(section, base)


def load_app_config(default: AppConfig | None = None) -> AppConfig:
    """Đọc toàn bộ cấu hình app đã lưu. File thiếu hoặc hỏng → trả mặc định."""
    base = default or DEFAULT_APP_CONFIG
    path = config_path()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return base

    bus_sec = raw.get("bus")
    bus_cfg = _coerce_bus(bus_sec, base.bus) if isinstance(bus_sec, dict) else base.bus

    sess_sec = raw.get("session", {})
    last_a2l = str(sess_sec.get("last_a2l_path", "")) if isinstance(sess_sec, dict) else ""

    ui_sec = raw.get("ui", {})
    scope_on = True
    row_lim = 20_000
    vis_kinds = ["cmd", "res", "err", "ev", "serv", "other"]
    if isinstance(ui_sec, dict):
        if isinstance(ui_sec.get("scope_enabled"), bool):
            scope_on = ui_sec["scope_enabled"]
        if isinstance(ui_sec.get("trace_row_limit"), int):
            row_lim = ui_sec["trace_row_limit"]
        if isinstance(ui_sec.get("trace_visible_kinds"), list):
            vis_kinds = [str(k) for k in ui_sec["trace_visible_kinds"]]
        active_route = str(ui_sec.get("active_route", "calibration"))
        dock_state = str(ui_sec.get("dock_state", ""))
        debug_area_collapsed = bool(ui_sec.get("debug_area_collapsed", False))
    else:
        active_route = "calibration"
        dock_state = ""
        debug_area_collapsed = False

    return AppConfig(
        bus=bus_cfg,
        last_a2l_path=last_a2l,
        scope_enabled=scope_on,
        trace_row_limit=row_lim,
        active_route=active_route,
        dock_state=dock_state,
        debug_area_collapsed=debug_area_collapsed,
        trace_visible_kinds=vis_kinds,
    )


def dumps_bus_config(cfg: BusConfig) -> str:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    return (
        "# xcptool — cấu hình bus. File này do công cụ ghi, sửa tay được.\n"
        "[bus]\n"
        f'backend = "{esc(cfg.backend)}"\n'
        f'channel = "{esc(cfg.channel)}"\n'
        f"bitrate = {cfg.bitrate}\n"
        f"cro_id = 0x{cfg.cro_id:X}\n"
        f"dto_id = 0x{cfg.dto_id:X}\n"
        f"extended_id = {str(cfg.extended_id).lower()}\n"
        f"pad_dlc = {str(cfg.pad_dlc).lower()}\n"
        f"t1_timeout_s = {cfg.t1_timeout_s}\n"
        f"is_fd = {str(cfg.is_fd).lower()}\n"
        f"data_bitrate = {cfg.data_bitrate}\n"
        f"custom_bit_timing = {str(cfg.custom_bit_timing).lower()}\n"
        f"f_clock = {cfg.f_clock}\n"
        f"brp = {cfg.brp}\n"
        f"tseg1 = {cfg.tseg1}\n"
        f"tseg2 = {cfg.tseg2}\n"
        f"sjw = {cfg.sjw}\n"
        f"dbrp = {cfg.dbrp}\n"
        f"dtseg1 = {cfg.dtseg1}\n"
        f"dtseg2 = {cfg.dtseg2}\n"
        f"dsjw = {cfg.dsjw}\n"
    )


def dumps_app_config(cfg: AppConfig) -> str:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    kinds_str = ", ".join(f'"{esc(k)}"' for k in cfg.trace_visible_kinds)
    return (
        "# xcptool configuration file\n\n"
        + dumps_bus_config(cfg.bus)
        + "\n[session]\n"
        f'last_a2l_path = "{esc(cfg.last_a2l_path)}"\n'
        + "\n[ui]\n"
        f"scope_enabled = {str(cfg.scope_enabled).lower()}\n"
        f"trace_row_limit = {cfg.trace_row_limit}\n"
        f"active_route = \"{esc(cfg.active_route)}\"\n"
        f"dock_state = \"{esc(cfg.dock_state)}\"\n"
        f"debug_area_collapsed = {str(cfg.debug_area_collapsed).lower()}\n"
        f"trace_visible_kinds = [{kinds_str}]\n"
    )


def save_bus_config(cfg: BusConfig) -> Path:
    # Bảo toàn các session/ui settings khi chỉ update bus config
    app_cfg = load_app_config()
    app_cfg.bus = cfg
    return save_app_config(app_cfg)


def save_app_config(cfg: AppConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(dumps_app_config(cfg), encoding="utf-8")
    tmp.replace(path)
    return path
