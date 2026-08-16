"""Bắt và nuốt tiếng ồn của python-can khi thiếu driver hãng.

`can.detect_available_configs()` phun ~19 dòng cảnh báo ra stderr trên một máy
chưa cài driver nào (xem DEV_PLAN.md §5.1). Đó không phải lỗi, nhưng để nguyên
thì log và cửa sổ debug ngập rác ngay lần chạy đầu.

Cảnh báo đi qua cây logger `can` lúc *import* module backend, chạm stderr qua
`logging.lastResort` vì ứng dụng chưa gắn handler nào. Ta gắn handler thu gom
riêng, cắt `propagate`, rồi chuyển các dòng thu được thành `DeviceInfo.hint`.
"""

from __future__ import annotations

import contextlib
import io
import logging
import warnings
from collections.abc import Iterator
from dataclasses import dataclass

__all__ = ["CapturedLog", "capture_can_logs", "BLOCKING_PHRASES"]

BLOCKING_PHRASES = (
    "won't be able to use",
    "could not import",
    "cannot load",
    "failed to load",
    "is unavailable",
    "not installed",
    "library not found",
    "no module named",
)
"""Từ vựng của python-can khi một backend thực sự KHÔNG dùng được.

Lọc theo danh sách này vì cây logger `can` còn phun cả lời khuyên vô hại —
ví dụ pcan báo "uptime library not available, timestamps are relative to boot
time". Lấy bừa dòng đầu tiên thì hint của PEAK sẽ nói về timestamp thay vì nói
người dùng cần cài PCAN-Basic, tức là tệ hơn không có hint.
"""


@dataclass
class CapturedLog:
    """Các dòng python-can đã nói trong lúc dò thiết bị."""

    records: list[logging.LogRecord]
    stderr_text: str = ""

    def messages_for(self, *needles: str, blocking_only: bool = True) -> list[str]:
        """Các dòng thuộc về backend khớp `needles`.

        `blocking_only` giữ lại đúng những dòng nói backend không dùng được,
        bỏ các lời khuyên vô hại — xem `BLOCKING_PHRASES`.
        """
        out: list[str] = []
        for rec in self.records:
            if rec.levelno < logging.WARNING:
                continue
            text = rec.getMessage()
            haystack = f"{rec.name} {text}".lower()
            if not any(n.lower() in haystack for n in needles):
                continue
            if blocking_only and not any(p in text.lower() for p in BLOCKING_PHRASES):
                continue
            out.append(text)
        return out


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextlib.contextmanager
def capture_can_logs() -> Iterator[CapturedLog]:
    """Trong khối này, không một dòng nào của python-can lọt ra stderr."""
    captured = CapturedLog(records=[])
    collector = _Collector()
    can_log = logging.getLogger("can")

    prev_propagate = can_log.propagate
    prev_level = can_log.level
    prev_disabled = can_log.disabled
    can_log.addHandler(collector)
    can_log.propagate = False
    can_log.setLevel(logging.DEBUG)
    can_log.disabled = False

    sink = io.StringIO()
    try:
        with warnings.catch_warnings(), contextlib.redirect_stderr(sink):
            warnings.simplefilter("ignore")
            yield captured
    finally:
        can_log.removeHandler(collector)
        can_log.propagate = prev_propagate
        can_log.setLevel(prev_level)
        can_log.disabled = prev_disabled
        captured.records = collector.records
        captured.stderr_text = sink.getvalue()
