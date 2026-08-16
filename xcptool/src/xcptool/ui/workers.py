"""Marshal worker thread → Qt signal.

Mọi phương thức CHẶN của `Session` phải đi qua đây. Gọi thẳng từ UI thread làm
đơ giao diện — contract coi đó là lỗi.

`TaskSignals` được tạo trong UI thread nên mọi kết nối signal đều là queued
connection: slot chạy trên UI thread, không có chuyện đụng widget từ thread khác.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

log = logging.getLogger(__name__)

__all__ = ["Task", "TaskRunner"]


class TaskSignals(QObject):
    finished = Signal(object)     # kết quả trả về của hàm
    failed = Signal(object)       # instance Exception
    done = Signal(object)         # chính Task, để runner bỏ tham chiếu


class Task(QRunnable):
    """Chạy một lời gọi chặn trên thread pool, đẩy kết quả về UI thread."""

    def __init__(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._cancelled = False
        self.signals = TaskSignals()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        """Bỏ kết quả khi nó về. Lời gọi đang chạy KHÔNG bị cắt ngang —
        contract không có cơ chế huỷ; UI chỉ ngừng quan tâm tới kết quả."""
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # noqa: BLE001 — phân loại ở phía UI
            if self._cancelled:
                log.debug("Task đã huỷ, bỏ qua lỗi %r", exc)
            else:
                self.signals.failed.emit(exc)
        else:
            if not self._cancelled:
                self.signals.finished.emit(result)
        finally:
            self.signals.done.emit(self)


class TaskRunner:
    """Giữ tham chiếu tới Task đang chạy để GC không thu chúng giữa chừng."""

    def __init__(self, pool: QThreadPool | None = None) -> None:
        self.pool = pool or QThreadPool.globalInstance()
        self._alive: set[Task] = set()

    def run(
        self,
        fn: Callable[..., Any],
        /,
        *args: Any,
        on_ok: Callable[[Any], None] | None = None,
        on_err: Callable[[Exception], None] | None = None,
        **kwargs: Any,
    ) -> Task:
        task = Task(fn, *args, **kwargs)
        if on_ok is not None:
            task.signals.finished.connect(lambda r: on_ok(r))
        if on_err is not None:
            task.signals.failed.connect(lambda e: on_err(e))
        task.signals.done.connect(self._alive.discard)
        self._alive.add(task)
        self.pool.start(task)
        return task

    def wait(self, timeout_ms: int = 5000) -> bool:
        return self.pool.waitForDone(timeout_ms)
