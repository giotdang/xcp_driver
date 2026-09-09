"""`xcptool.ui.app` — tham số dòng lệnh của entry point GUI (chạy qua `run.bat`).

Alias ngắn (`-c`, `-s`) không được đổi hành vi so với tên dài, và `--config`
phải bơm ra đúng biến môi trường mà `transport.config.config_path()` đọc — nếu
không thì lần ghi lúc thoát sẽ trật file.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from xcptool.ui.app import _apply_config_override, _parse_args


@pytest.fixture(autouse=True)
def _clean_config_env():
    """`_apply_config_override` đặt thẳng `os.environ` (đúng với production —
    giá trị phải sống tới lúc app ghi config khi thoát). Trong test thì phải
    khôi phục tay, monkeypatch không thấy được thay đổi này."""
    saved = os.environ.pop("XCPTOOL_CONFIG", None)
    try:
        yield
    finally:
        os.environ.pop("XCPTOOL_CONFIG", None)
        if saved is not None:
            os.environ["XCPTOOL_CONFIG"] = saved


def test_short_and_long_flags_are_equivalent() -> None:
    short = _parse_args(["-s", "fake", "-c", "x.toml"])
    lng = _parse_args(["--session", "fake", "--config", "x.toml"])
    assert (short.session, short.config) == ("fake", "x.toml")
    assert (lng.session, lng.config) == ("fake", "x.toml")


def test_defaults_keep_current_behavior() -> None:
    args = _parse_args([])
    assert args.session == "real"
    assert args.config is None


def test_help_lists_every_option(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _parse_args(["-h"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("-c", "--config", "-s", "--session", "--light", "--selftest"):
        assert flag in out


def test_apply_config_override_sets_env_to_absolute_path(tmp_path) -> None:
    target = tmp_path / "bench.toml"
    target.write_text("[bus]\n", encoding="utf-8")
    _apply_config_override(str(target))
    assert Path(os.environ["XCPTOOL_CONFIG"]) == target.resolve()


def test_apply_config_override_missing_file_is_not_fatal(tmp_path) -> None:
    target = tmp_path / "khong-co.toml"
    _apply_config_override(str(target))  # không được ném
    assert Path(os.environ["XCPTOOL_CONFIG"]) == target.resolve()


def test_apply_config_override_none_leaves_env_untouched() -> None:
    _apply_config_override(None)
    assert "XCPTOOL_CONFIG" not in os.environ
