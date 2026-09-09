"""B2 — schema và đọc/ghi `config.toml`.

File hỏng hay thiếu KHÔNG được làm chết app: user sẽ gặp chuyện đó sau một lần
tắt máy giữa chừng, và mất cấu hình còn đỡ hơn không mở nổi công cụ.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from xcptool.session.api import BusConfig
from xcptool.transport.config import (
    DEFAULT_BUS_CONFIG,
    config_path,
    load_bus_config,
    save_bus_config,
)


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XCPTOOL_HOME", str(tmp_path))


def test_missing_file_gives_defaults() -> None:
    assert not config_path().exists()
    assert load_bus_config() == DEFAULT_BUS_CONFIG


def test_round_trip_preserves_every_field() -> None:
    cfg = BusConfig(
        backend="pcan", channel="PCAN_USBBUS2", bitrate=250_000,
        cro_id=0x123, dto_id=0x456, extended_id=True, pad_dlc=False,
        t1_timeout_s=2.5)
    save_bus_config(cfg)
    assert load_bus_config() == cfg


def test_can_ids_are_written_as_hex_for_humans() -> None:
    save_bus_config(replace(DEFAULT_BUS_CONFIG, cro_id=0x123, dto_id=0x456))
    text = config_path().read_text(encoding="utf-8")
    assert "cro_id = 0x123" in text
    assert "dto_id = 0x456" in text


def test_corrupt_file_falls_back_to_defaults() -> None:
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text("this is not [ valid toml", encoding="utf-8")
    assert load_bus_config() == DEFAULT_BUS_CONFIG


def test_partial_file_keeps_defaults_for_the_rest() -> None:
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text('[bus]\nbackend = "vector"\n', encoding="utf-8")

    cfg = load_bus_config()
    assert cfg.backend == "vector"
    assert cfg.bitrate == DEFAULT_BUS_CONFIG.bitrate
    assert cfg.cro_id == DEFAULT_BUS_CONFIG.cro_id


def test_wrong_types_are_ignored_not_crashed() -> None:
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text(
        '[bus]\nbitrate = true\nchannel = 5\ncro_id = 0x99\n', encoding="utf-8")

    cfg = load_bus_config()
    assert cfg.bitrate == DEFAULT_BUS_CONFIG.bitrate     # bool không phải bitrate
    assert cfg.channel == DEFAULT_BUS_CONFIG.channel     # int không phải channel
    assert cfg.cro_id == 0x99                            # khoá hợp lệ vẫn nhận


def test_integer_timeout_is_accepted_as_float() -> None:
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text("[bus]\nt1_timeout_s = 3\n", encoding="utf-8")
    assert load_bus_config().t1_timeout_s == 3.0


def test_unknown_keys_do_not_break_loading() -> None:
    """Bản cũ đọc được file của bản mới — thêm khoá không phải thay đổi phá vỡ."""
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text(
        '[bus]\nbackend = "slcan"\nfuture_option = 42\n', encoding="utf-8")
    assert load_bus_config().backend == "slcan"


def test_saving_creates_the_directory() -> None:
    save_bus_config(DEFAULT_BUS_CONFIG)
    assert config_path().is_file()


# ── $XCPTOOL_CONFIG: chọn thẳng file cấu hình (run.bat -c <path>) ──────────────

def test_config_env_var_points_at_an_exact_file(tmp_path, monkeypatch) -> None:
    target = tmp_path / "profiles" / "bench.toml"
    monkeypatch.setenv("XCPTOOL_CONFIG", str(target))
    assert config_path() == target


def test_config_env_var_beats_home_dir(tmp_path, monkeypatch) -> None:
    # fixture `home` đã trỏ XCPTOOL_HOME vào tmp_path — file override phải thắng.
    target = tmp_path / "elsewhere" / "custom.toml"
    monkeypatch.setenv("XCPTOOL_CONFIG", str(target))
    assert config_path() == target
    assert config_path() != tmp_path / "config.toml"


def test_config_env_var_round_trips_to_the_chosen_file(tmp_path, monkeypatch) -> None:
    target = tmp_path / "profiles" / "bench.toml"
    monkeypatch.setenv("XCPTOOL_CONFIG", str(target))
    cfg = replace(DEFAULT_BUS_CONFIG, backend="pcan", channel="PCAN_USBBUS2")
    save_bus_config(cfg)
    assert target.is_file()
    assert load_bus_config() == cfg


def test_config_env_var_expands_user(monkeypatch) -> None:
    monkeypatch.setenv("XCPTOOL_CONFIG", "~/xcptool-test-profile/cfg.toml")
    assert config_path() == Path("~/xcptool-test-profile/cfg.toml").expanduser()


def test_empty_config_env_var_falls_back_to_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XCPTOOL_CONFIG", "")
    assert config_path() == tmp_path / "config.toml"
