"""Log ra file + excepthook toàn cục.

Crash không tái hiện được vẫn phải để lại dấu vết: `faulthandler` bắt cả những
lỗi mà Python không kịp dựng traceback (segfault trong Qt chẳng hạn).
"""

from __future__ import annotations

import faulthandler
import logging
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

__all__ = ["LOG_DIR", "current_log_path", "setup_logging", "install_excepthooks"]

LOG_DIR = Path.home() / ".xcptool" / "logs"

_log_path: Path | None = None
_fault_file = None  # giữ tham chiếu: faulthandler ghi thẳng vào fd này


def current_log_path() -> Path:
    return _log_path if _log_path is not None else LOG_DIR / "xcptool.log"


def setup_logging(level: int = logging.INFO, log_dir: Path | None = None) -> Path:
    """Trả về đường dẫn file log. Gọi nhiều lần vẫn an toàn."""
    global _log_path, _fault_file

    if _log_path is not None:
        return _log_path

    directory = log_dir or LOG_DIR
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = directory / f"xcptool-{stamp}.log"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handlers: list[logging.Handler] = [
            logging.FileHandler(path, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ]
    except OSError:
        # Không ghi được file (ổ đầy, quyền) — vẫn phải chạy, chỉ log ra stderr.
        path = directory / "xcptool.log"
        handlers = [logging.StreamHandler(sys.stderr)]

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )

    try:
        _fault_file = open(directory / "faulthandler.log", "a", encoding="utf-8")
        faulthandler.enable(file=_fault_file)
    except OSError:
        faulthandler.enable()

    _log_path = path
    logging.getLogger(__name__).info("Log của phiên này: %s", path)
    return path


def install_excepthooks(notify: Callable[[BaseException], None] | None = None) -> None:
    """Bắt mọi ngoại lệ lọt ra khỏi slot Qt và khỏi thread nền.

    `notify` chạy trên chính thread ném lỗi — nó phải tự marshal về UI thread
    (MainWindow dùng Signal để làm việc đó).
    """
    log = logging.getLogger("xcptool.excepthook")

    def hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical(
            "Ngoại lệ chưa bắt trên %s:\n%s",
            threading.current_thread().name,
            "".join(traceback.format_exception(exc_type, exc, tb)),
        )
        if notify is not None:
            try:
                notify(exc)
            except Exception:  # noqa: BLE001 — excepthook không được ném tiếp
                log.exception("notify() của excepthook cũng lỗi")

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        hook(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = hook
    threading.excepthook = thread_hook
