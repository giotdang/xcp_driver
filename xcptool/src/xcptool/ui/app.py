"""Entry point của GUI: `python -m xcptool.ui.app --session fake`.

Sở hữu ba việc xuyên suốt (DEV_PLAN.md §3):
  * log ra file + `faulthandler`
  * `sys.excepthook` và `threading.excepthook` — app không được biến mất im lặng
  * gọi `session.close()` khi thoát, kể cả khi thoát do lỗi
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .logging_setup import install_excepthooks, setup_logging
from .main_window import MainWindow
from .session_factory import SESSION_KINDS, create_session

log = logging.getLogger(__name__)

__all__ = ["main", "build_app", "ensure_utf8_stdio"]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="xcptool-gui", description="XCP master — giao diện")
    p.add_argument("-c", "--config", default=None, metavar="PATH",
                   help="file cấu hình để nạp và lưu lại (mặc định: ./config.toml nếu có)")
    p.add_argument("-s", "--session", choices=SESSION_KINDS, default="real",
                   help="'fake' chạy không cần phần cứng lẫn backend (mặc định: real)")
    p.add_argument("--selftest", action="store_true",
                   help="mở cửa sổ, chạy một kịch bản ngắn, đóng, thoát 0")
    p.add_argument("--light", action="store_true", help="dùng theme sáng")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   help="mức log ghi ra file (mặc định: INFO)")
    return p.parse_args(argv)


def _apply_config_override(config_arg: str | None) -> None:
    """`--config PATH` → biến môi trường mà `transport.config.config_path()` đọc.

    Phải đặt TRƯỚC khi MainWindow dựng lên, để cả lần đọc lúc khởi động lẫn lần
    ghi lúc thoát đều trỏ vào đúng file này. File chưa tồn tại không phải lỗi —
    app khởi động từ mặc định rồi tạo file đó lúc thoát (dùng như một profile
    có tên).
    """
    if config_arg is None:
        return
    path = Path(config_arg).expanduser().resolve()
    os.environ["XCPTOOL_CONFIG"] = str(path)
    if path.is_file():
        log.info("Dùng file cấu hình: %s", path)
    else:
        log.warning("File cấu hình %s chưa tồn tại — khởi động từ mặc định, "
                    "sẽ tạo khi thoát", path)


def ensure_utf8_stdio() -> None:
    """Console Windows mặc định cp1252 — in tiếng Việt ra đó sẽ nổ
    UnicodeEncodeError. Trong một QTimer slot thì lỗi đó lặp lại mỗi nhịp và
    treo cả app, nên phải xử lý ngay ở entry point."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def build_app(argv: list[str]) -> tuple[QApplication, MainWindow, argparse.Namespace]:
    ensure_utf8_stdio()
    args = _parse_args(argv)
    log_path = setup_logging(getattr(logging, args.log_level))
    _apply_config_override(args.config)
    log.info("xcptool khởi động, session=%s", args.session)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    session = create_session(args.session)
    window = MainWindow(session)

    install_excepthooks(window.report_unexpected)
    log.info("Log ghi vào %s", log_path)
    return app, window, args


def main(argv: list[str] | None = None) -> int:
    app, window, args = build_app(list(sys.argv[1:] if argv is None else argv))

    if args.light:
        from .theme import apply_theme

        apply_theme(window, dark=False)

    window.show()

    if args.selftest:
        from .selftest import run_selftest

        return run_selftest(app, window)

    try:
        return app.exec()
    finally:
        # Thoát do lỗi cũng phải đóng bus. closeEvent có thể đã chạy rồi —
        # close() idempotent nên gọi hai lần vô hại.
        try:
            window.session.close()
        except Exception:  # noqa: BLE001
            log.exception("session.close() lúc thoát ném ngoại lệ")


if __name__ == "__main__":
    raise SystemExit(main())
