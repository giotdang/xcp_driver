"""`--selftest`: mở cửa sổ, chạy hết một vòng thao tác thật, đóng, thoát 0.

Không phải test thay pytest — nó chứng minh app *đã dựng xong* chạy được đúng
đường mà user sẽ đi, kể cả phần bị pytest bỏ qua (event loop thật, worker thread
thật, timer trace thật).
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ..session.api import BusConfig, ConnState
from .main_window import MainWindow

log = logging.getLogger(__name__)

__all__ = ["run_selftest"]

_STEP_MS = 250
_STEP_TIMEOUT_MS = 20_000
_TIMEOUT_MS = 120_000


def run_selftest(app: QApplication, window: MainWindow) -> int:
    failures: list[str] = []
    steps: list[tuple[str, Callable[[], None]]] = []

    def check(cond: bool, what: str) -> None:
        if cond:
            log.info("selftest OK  — %s", what)
        else:
            failures.append(what)
            log.error("selftest FAIL — %s", what)

    found: dict[str, list] = {"devices": []}

    def step_list_devices() -> None:
        # Qua _call → worker thread + cờ bận, để bước sau chờ đúng lúc xong.
        window._call(
            "Đang dò thiết bị…",
            window.session.list_devices,
            on_ok=lambda devices: found.__setitem__("devices", devices),
            on_err=lambda exc: failures.append(f"list_devices: {exc!r}"),
        )

    def step_check_devices() -> None:
        devices = found["devices"]
        check(bool(devices), "list_devices() trả về ít nhất một kênh")
        check(any(d.hint for d in devices if not d.available),
              "kênh không dùng được có kèm hint")

    def step_connect() -> None:
        usable = next(d for d in found["devices"] if d.available)
        window.connect_to(BusConfig(backend=usable.backend, channel=usable.channel))

    def step_check_connected() -> None:
        check(window.session.state is ConnState.CONNECTED, "CONNECT thành công")
        check(window.session.caps is not None, "SlaveCaps có giá trị sau CONNECT")
        check(bool(window.caps_label.text()), "status bar hiện SlaveCaps")

    def step_raw() -> None:
        window.console_view.input.setText("FF 00")
        window.console_view.send()

    def step_check_raw() -> None:
        text = window.console_view.output.toPlainText()
        check(">>> FF 00" in text, "console ghi lại lệnh đã gửi")
        check("<<< FF" in text, "console hiện response bắt đầu bằng FF")

    def step_read() -> None:
        window.memory_view.addr_edit.setText("0x80000000")
        window.memory_view.size_spin.setValue(32)
        window.memory_view.do_read()

    def step_check_read() -> None:
        check(window.memory_view.table.rowCount() == 2, "hex dump hiện 32 byte / 2 dòng")

    def step_write() -> None:
        view = window.memory_view
        view._edited[0] = (view._edited[0] + 1) & 0xFF
        view._render()
        window.write_memory(view._base_addr, bytes(view._edited))

    def step_check_write() -> None:
        check(window.session.state is ConnState.CONNECTED, "ghi xong vẫn còn kết nối")

    def step_check_trace() -> None:
        check(window.trace_view.model.rowCount() > 0, "bảng trace có dòng")

    def step_pages() -> None:
        window.memory_view.refresh_pages()

    def step_check_pages() -> None:
        check(window.memory_view.xcp_page_label.text() not in ("", "—"),
              "panel bộ nhớ hiện trang XCP")

    def step_disconnect() -> None:
        window.do_disconnect()

    def step_close() -> None:
        window.close()

    steps = [
        ("list_devices", step_list_devices),
        ("check devices", step_check_devices),
        ("connect", step_connect),
        ("check connect", step_check_connected),
        ("raw_command", step_raw),
        ("check raw", step_check_raw),
        ("read", step_read),
        ("check read", step_check_read),
        ("write", step_write),
        ("check write", step_check_write),
        ("pages", step_pages),
        ("check pages", step_check_pages),
        ("check trace", step_check_trace),
        ("disconnect", step_disconnect),
        ("close", step_close),
    ]

    index = 0

    def advance() -> None:
        nonlocal index
        if index >= len(steps):
            app.quit()
            return
        name, fn = steps[index]
        index += 1
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — selftest phải báo, không được nổ
            failures.append(f"{name}: {exc!r}")
            log.exception("selftest bước '%s' ném ngoại lệ", name)
        # Chờ lệnh chạy xong thay vì đếm thời gian: RealSession dò thiết bị thật
        # mất vài giây, còn FakeSession trả lời tức thì.
        _wait_idle(name, 0)

    def _wait_idle(name: str, waited_ms: int) -> None:
        if window.busy and waited_ms < _STEP_TIMEOUT_MS:
            QTimer.singleShot(_STEP_MS, lambda: _wait_idle(name, waited_ms + _STEP_MS))
            return
        if window.busy:
            failures.append(f"{name}: quá giờ, lệnh vẫn đang chạy")
        QTimer.singleShot(_STEP_MS, advance)

    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(lambda: (failures.append("selftest quá giờ"), app.quit()))
    guard.start(_TIMEOUT_MS)

    QTimer.singleShot(_STEP_MS, advance)
    app.exec()

    try:
        window.session.close()
    except Exception:  # noqa: BLE001
        failures.append("session.close() ném ngoại lệ")

    if failures:
        log.error("selftest HỎNG: %s", "; ".join(failures))
        print("selftest HỎNG:\n  " + "\n  ".join(failures))
        return 1
    print("selftest OK — mọi bước đều xanh")
    return 0
