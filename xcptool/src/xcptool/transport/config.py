"""Đọc/ghi `~/.xcptool/config.toml`.

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

from ..session.api import BusConfig

__all__ = [
    "DEFAULT_BUS_CONFIG", "config_dir", "config_path",
    "load_bus_config", "save_bus_config", "dumps_bus_config",
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
)

_ENV_DIR = "XCPTOOL_HOME"


def config_dir() -> Path:
    """`~/.xcptool`, hoặc `$XCPTOOL_HOME` khi được đặt (test dùng lối này)."""
    override = os.environ.get(_ENV_DIR)
    return Path(override) if override else Path.home() / ".xcptool"


def config_path() -> Path:
    return config_dir() / "config.toml"


def _coerce(raw: dict[str, object], base: BusConfig) -> BusConfig:
    """Nhặt đúng các khoá hiểu được, bỏ qua phần thừa và phần sai kiểu."""
    fields: dict[str, object] = {}
    for key, kind in (
        ("backend", str), ("channel", str), ("bitrate", int),
        ("cro_id", int), ("dto_id", int), ("extended_id", bool),
        ("pad_dlc", bool), ("t1_timeout_s", float),
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
    """Đọc cấu hình đã lưu. File thiếu hoặc hỏng → trả mặc định, không ném."""
    base = default or DEFAULT_BUS_CONFIG
    path = config_path()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return base
    section = raw.get("bus")
    if not isinstance(section, dict):
        return base
    return _coerce(section, base)


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
    )


def save_bus_config(cfg: BusConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(dumps_bus_config(cfg), encoding="utf-8")
    tmp.replace(path)
    return path
