"""Cửa sổ chính — điều phối duy nhất giữa UI và `Session`.

Ba luật của contract được cưỡng chế tại chỗ này, không rải rác:

  1. MỌI lời gọi chặn của Session đi qua `self.runner` (worker thread) rồi quay
     về UI thread bằng Qt signal. Không widget nào tự gọi Session.
  2. `drain_trace()` chỉ được gọi ở ĐÚNG MỘT nơi — `_poll_trace`, theo QTimer
     40 ms — rồi phân phát cho các view. Hai nơi cùng drain sẽ ăn mất frame của nhau.
  3. `closeEvent` luôn gọi `session.close()`, kể cả khi đang bận hay đang lỗi.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import Qt, QSettings, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarPosition,
    NavigationInterface,
    NavigationItemPosition,
    PushButton,
    StrongBodyLabel,
)

from ..session.api import (
    BusConfig,
    ConnState,
    PageMode,
    SlaveCaps,
    WriteProtectedError,
    XcpToolError,
)
from . import errors
from .calibration_view import (
    WORKING_PAGE as CAL_WORKING_PAGE,
    CalibrationView,
)
from .console_view import ConsoleView
from .device_dialog import DeviceDialog
from .dock_manager import DockManager
from .logging_setup import current_log_path
from .memory_view import WORKING_PAGE, MemoryView, ask_switch_to_working_page
from .theme import apply_theme
from .trace_view import TraceView
from .workers import TaskRunner

log = logging.getLogger(__name__)

__all__ = ["MainWindow", "TRACE_POLL_MS"]

TRACE_POLL_MS = 40


class MainWindow(QMainWindow):
    """`session` chỉ cần khớp `session.api.Session` — không quan tâm fake hay real."""

    unexpected_error = Signal(object)   # excepthook (thread bất kỳ) → UI thread

    def __init__(self, session: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.runner = TaskRunner()

        self._busy_label = ""
        self._connect_task = None
        self._dialog: DeviceDialog | None = None

        self.setWindowTitle("xcptool — XCP master")
        self.resize(1180, 760)

        self._build_views()
        self._build_navigation()
        self._build_docks()
        self._build_menus()
        self._build_statusbar()
        apply_theme(self)

        # Khôi phục trạng thái dock từ lần chạy trước
        _settings = QSettings("xcptool", "xcptool")
        _dock_state = _settings.value("dock_state")
        if _dock_state:
            self.dock_manager.restore_state(bytes(_dock_state))
        if _settings.value("debug_area_collapsed", False, type=bool):
            self.dock_manager.toggle_debug_area()

        self.trace_timer = QTimer(self)
        self.trace_timer.setInterval(TRACE_POLL_MS)
        self.trace_timer.timeout.connect(self._poll_trace)
        self.trace_timer.start()

        self.unexpected_error.connect(self._on_unexpected_error)
        self._refresh_state()

    # ── dựng giao diện ───────────────────────────────────────────────────────

    def _build_views(self) -> None:
        self.trace_view = TraceView(parent=self)
        self.console_view = ConsoleView(self.send_raw, parent=self)
        self.memory_view = MemoryView(
            read_cb=self.read_memory,
            write_cb=self.write_memory,
            get_pages_cb=self.refresh_pages,
            set_page_cb=self.set_page,
            copy_page_cb=self.copy_page,
            parent=self,
        )
        self.calibration_view = CalibrationView(
            read_all_cb=self.read_all_characteristics,
            write_cb=self.write_characteristic,
            get_pages_cb=self.cal_get_pages,
            set_page_cb=self.cal_set_page,
            copy_page_cb=self.cal_copy_page,
            parent=self,
        )
        self.calibration_view.a2l_load_requested.connect(self._on_a2l_load_requested)

    def _build_navigation(self) -> None:
        central = QWidget(self)
        central.setObjectName("chrome")
        self.nav = NavigationInterface(self, showMenuButton=True, showReturnButton=False)
        self.stack = QStackedWidget(self)

        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.nav)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.stack.addWidget(self.calibration_view)

        self.nav.addItem(
            routeKey="calibration",
            icon=FluentIcon.EDIT,
            text="Hiệu chỉnh",
            onClick=lambda: self.switch_to(self.calibration_view),
            position=NavigationItemPosition.SCROLL,
        )
        self.nav.addItem(
            routeKey="connect",
            icon=FluentIcon.CONNECT,
            text="Kết nối…",
            onClick=self.open_device_dialog,
            selectable=False,
            position=NavigationItemPosition.BOTTOM,
        )
        self.nav.setExpandWidth(200)

    def _build_docks(self) -> None:
        """Tạo DockManager và gắn trace/console/memory vào dock bottom."""
        self.dock_manager = DockManager(self)
        self.dock_manager.setup(self.trace_view, self.console_view, self.memory_view)

    def _build_menus(self) -> None:
        bar = self.menuBar()

        session_menu = bar.addMenu("&Phiên")
        self.act_connect = QAction("&Kết nối…", self)
        self.act_connect.setShortcut(QKeySequence("Ctrl+K"))
        self.act_connect.triggered.connect(self.open_device_dialog)
        session_menu.addAction(self.act_connect)

        self.act_disconnect = QAction("&Ngắt kết nối", self)
        self.act_disconnect.triggered.connect(self.do_disconnect)
        session_menu.addAction(self.act_disconnect)
        session_menu.addSeparator()

        act_load_a2l = QAction("Nạp &A2L…", self)
        act_load_a2l.setShortcut(QKeySequence("Ctrl+O"))
        act_load_a2l.triggered.connect(self.calibration_view.load_btn.click)
        session_menu.addAction(act_load_a2l)
        session_menu.addSeparator()

        act_quit = QAction("T&hoát", self)
        act_quit.setShortcut(QKeySequence.Quit)
        act_quit.triggered.connect(self.close)
        session_menu.addAction(act_quit)

        view_menu = bar.addMenu("&Xem")
        for dock, text, shortcut in (
            (self.dock_manager.trace_dock, "&Trace CAN", "Ctrl+1"),
            (self.dock_manager.console_dock, "&Lệnh thô", "Ctrl+2"),
        ):
            act = QAction(text, self)
            act.setShortcut(QKeySequence(shortcut))
            act.triggered.connect(
                lambda _=False, d=dock: (
                    d.show(), d.raise_(), self.dock_manager.ensure_debug_area_expanded()
                )
            )
            view_menu.addAction(act)
        mem_toggle = self.dock_manager.memory_dock.toggleViewAction()
        mem_toggle.setText("&Memory / Debug")
        mem_toggle.setShortcut(QKeySequence("Ctrl+3"))
        view_menu.addAction(mem_toggle)
        view_menu.addSeparator()

        self.act_toggle_debug_area = QAction("Ẩn/hiện &vùng debug (Trace + Lệnh thô)", self)
        self.act_toggle_debug_area.setShortcut(QKeySequence("Ctrl+`"))
        self.act_toggle_debug_area.triggered.connect(self.toggle_debug_area)
        view_menu.addAction(self.act_toggle_debug_area)

        help_menu = bar.addMenu("&Trợ giúp")
        act_log = QAction("Đường dẫn file &log", self)
        act_log.triggered.connect(
            lambda: self.notify("File log của phiên này", str(current_log_path()))
        )
        help_menu.addAction(act_log)
        act_about = QAction("&Về xcptool", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _build_statusbar(self) -> None:
        bar = self.statusBar()

        self.state_label = StrongBodyLabel("Chưa kết nối", self)
        self.caps_label = BodyLabel("", self)
        self.drop_label = BodyLabel("", self)

        self.busy_ring = IndeterminateProgressRing(self)
        self.busy_ring.setFixedSize(16, 16)
        self.busy_ring.hide()
        self.busy_label = BodyLabel("", self)
        self.cancel_btn = PushButton("Huỷ", self)
        self.cancel_btn.clicked.connect(self.cancel_busy)
        self.cancel_btn.hide()

        bar.addWidget(self.state_label)
        bar.addWidget(self.busy_ring)
        bar.addWidget(self.busy_label)
        bar.addWidget(self.cancel_btn)
        bar.addPermanentWidget(self.caps_label)
        bar.addPermanentWidget(self.drop_label)

    # ── điều hướng ───────────────────────────────────────────────────────────

    def switch_to(self, widget: QWidget) -> None:
        """Chuyển hiển thị view. Dock view → show + raise dock; stack view → set current."""
        dm = getattr(self, "dock_manager", None)
        if dm is not None:
            dock_map = {
                id(self.trace_view): dm.trace_dock,
                id(self.console_view): dm.console_dock,
                id(self.memory_view): dm.memory_dock,
            }
            dock = dock_map.get(id(widget))
            if dock is not None:
                dock.show()
                dock.raise_()
                if dock in (dm.trace_dock, dm.console_dock):
                    dm.ensure_debug_area_expanded()
                return
        # Fallback: widget nằm trong stack (Calibration, placeholder…)
        self.stack.setCurrentWidget(widget)

    def toggle_debug_area(self) -> None:
        self.dock_manager.toggle_debug_area()

    def notify(self, title: str, content: str) -> None:
        InfoBar.info(
            title=title, content=content, orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP_RIGHT, duration=4000, parent=self,
        )

    def _show_about(self) -> None:
        self.notify(
            "xcptool",
            "Công cụ XCP master đa nền tảng. Giao diện dựng bằng "
            "PySide6-Fluent-Widgets (license dual GPLv3 / thương mại).",
        )

    # ── trạng thái bận ───────────────────────────────────────────────────────

    @property
    def busy(self) -> bool:
        return bool(self._busy_label)

    def _begin_busy(self, label: str, cancellable: bool = False) -> None:
        self._busy_label = label
        self.busy_label.setText(label)
        self.busy_ring.show()
        self.cancel_btn.setVisible(cancellable)
        self.memory_view.set_busy(True)
        self.calibration_view.set_busy(True)
        self.act_connect.setEnabled(False)

    def _end_busy(self) -> None:
        self._busy_label = ""
        self.busy_label.setText("")
        self.busy_ring.hide()
        self.cancel_btn.hide()
        self.memory_view.set_busy(False)
        self.calibration_view.set_busy(False)
        self.act_connect.setEnabled(True)
        self._refresh_state()

    def cancel_busy(self) -> None:
        """Huỷ = ngừng quan tâm tới kết quả và đóng bus. Contract không có cơ
        chế cắt ngang một lệnh đang chạy, nên đây là cách trung thực duy nhất."""
        if self._connect_task is not None:
            self._connect_task.cancel()
            self._connect_task = None
        self.busy_label.setText("Đang huỷ…")
        self.cancel_btn.setEnabled(False)
        self.runner.run(
            self.session.close,
            on_ok=lambda _: self._after_cancel(),
            on_err=lambda _: self._after_cancel(),
        )

    def _after_cancel(self) -> None:
        self.cancel_btn.setEnabled(True)
        self._end_busy()
        self.notify("Đã huỷ", "Kết nối bị huỷ theo yêu cầu.")

    def _guard(self) -> bool:
        """False nghĩa là không gửi lệnh được lúc này — đã báo cho user rồi."""
        if self.busy:
            self.notify("Đang bận", f"Chờ '{self._busy_label}' xong đã.")
            return False
        if self.session.state is not ConnState.CONNECTED:
            self.notify("Chưa kết nối", "Bấm Kết nối rồi thử lại.")
            return False
        return True

    def _call(
        self,
        label: str,
        fn: Callable[..., Any],
        *args: Any,
        on_ok: Callable[[Any], None] | None = None,
        on_err: Callable[[Exception], None] | None = None,
    ) -> None:
        """Chạy một lệnh Session trên worker, tự bật/tắt trạng thái bận."""
        self._begin_busy(label)

        def ok(result: Any) -> None:
            self._end_busy()
            if on_ok is not None:
                on_ok(result)

        def err(exc: Exception) -> None:
            self._end_busy()
            if on_err is not None:
                on_err(exc)
            else:
                errors.show_error(self, exc)

        self.runner.run(fn, *args, on_ok=ok, on_err=err)

    # ── kết nối ──────────────────────────────────────────────────────────────

    def open_device_dialog(self) -> None:
        if self.busy:
            self.notify("Đang bận", f"Chờ '{self._busy_label}' xong đã.")
            return
        dlg = DeviceDialog(self, initial=self.session.load_config())
        self._dialog = dlg
        dlg.detect_requested.connect(self._detect_devices)
        self._detect_devices()
        accepted = dlg.exec()
        self._dialog = None
        if accepted and dlg.selected_config is not None:
            self.connect_to(dlg.selected_config)

    def _detect_devices(self) -> None:
        dlg = self._dialog
        if dlg is None:
            return
        dlg.set_busy(True)

        def ok(devices: Any) -> None:
            if self._dialog is dlg:
                dlg.set_busy(False)
                dlg.set_devices(devices)

        def err(exc: Exception) -> None:
            if self._dialog is dlg:
                dlg.set_busy(False)
                title, body = errors.describe(exc)
                dlg.set_error(f"{title}: {body.splitlines()[0]}")
                log.warning("list_devices() lỗi: %r", exc)

        self.runner.run(self.session.list_devices, on_ok=ok, on_err=err)

    def connect_to(self, cfg: BusConfig) -> None:
        self._begin_busy(f"Đang kết nối {cfg.backend}:{cfg.channel}…", cancellable=True)

        def ok(caps: SlaveCaps) -> None:
            self._connect_task = None
            self._end_busy()
            self.calibration_view.set_byte_order(caps.byte_order)
            self.notify("Đã kết nối", self._caps_summary(caps))
            self._refresh_pages_after_connect()

        def err(exc: Exception) -> None:
            self._connect_task = None
            self._end_busy()
            errors.show_error(self, exc)

        self._connect_task = self.runner.run(
            self.session.connect, cfg, on_ok=ok, on_err=err
        )

    def _refresh_pages_after_connect(self) -> None:
        """Đọc trạng thái trang MỘT LẦN sau khi connect, cập nhật cả memory
        panel lẫn calibration panel từ cùng một cặp GET_CAL_PAGE.

        KHÔNG được gọi `memory_view.refresh_pages()` rồi `cal_get_pages()` nối
        tiếp: cái đầu set busy=True ngay khi return (worker chạy bất đồng bộ
        trên thread khác), nên cái sau bị `_guard()` từ chối tức thì với
        thông báo "Đang bận" — hai nhãn bận trùng nhau ("Đang đọc trạng thái
        trang…") càng làm user tưởng lệnh đang treo dù chẳng có gì đang chạy.
        """
        segment = self.calibration_view.segment_spin.value()
        if not self._guard():
            return

        def read_both() -> tuple[int | None, int | None]:
            ecu = self.session.get_page(segment, PageMode.ECU)
            xcp = self.session.get_page(segment, PageMode.XCP)
            return ecu, xcp

        def ok(pages: tuple[int | None, int | None]) -> None:
            self.memory_view.on_pages(segment, *pages)
            self.calibration_view.on_pages(segment, *pages)

        self._call("Đang đọc trạng thái trang…", read_both, on_ok=ok)

    def do_disconnect(self) -> None:
        if self.busy:
            self.notify("Đang bận", f"Chờ '{self._busy_label}' xong đã.")
            return
        self._call("Đang ngắt kết nối…", self.session.disconnect,
                   on_ok=lambda _: self.notify("Đã ngắt", "Phiên XCP đã đóng."))

    # ── lệnh thô ─────────────────────────────────────────────────────────────

    def send_raw(self, payload: bytes, raise_on_error: bool) -> None:
        if not self._guard():
            self.console_view.on_error("Chưa kết nối hoặc đang bận.")
            return

        def err(exc: Exception) -> None:
            title, body = errors.describe(exc)
            self.console_view.on_error(f"{title}: {body.splitlines()[0]}")
            if not isinstance(exc, XcpToolError):
                errors.show_error(self, exc)

        self._call(
            "Đang gửi lệnh thô…",
            self.session.raw_command, payload, raise_on_error,
            on_ok=self.console_view.on_response,
            on_err=err,
        )

    # ── bộ nhớ ───────────────────────────────────────────────────────────────

    def read_memory(self, addr: int, size: int) -> None:
        if not self._guard():
            return
        self._call(
            f"Đang đọc {size} byte tại 0x{addr:08X}…",
            self.session.read, addr, size, self.memory_view.ext,
            on_ok=lambda data: self.memory_view.on_read_done(addr, data),
        )

    def write_memory(self, addr: int, data: bytes) -> None:
        if not self._guard():
            return

        def err(exc: Exception) -> None:
            if isinstance(exc, WriteProtectedError):
                self._on_write_protected(exc)
            else:
                errors.show_error(self, exc)

        self._call(
            f"Đang ghi {len(data)} byte tại 0x{addr:08X}…",
            self.session.write, addr, data, self.memory_view.ext,
            on_ok=lambda _: self.memory_view.on_write_done(),
            on_err=err,
        )

    def _on_write_protected(self, exc: WriteProtectedError) -> None:
        """Đây là điểm UX quan trọng nhất của panel bộ nhớ: không in mã lỗi mà
        đưa thẳng nút sửa nguyên nhân."""
        if not ask_switch_to_working_page(self, exc.description):
            return
        segment = self.memory_view.segment_spin.value()
        self._call(
            "Đang chuyển XCP về working page…",
            self.session.set_page, segment, WORKING_PAGE, PageMode.XCP,
            on_ok=lambda _: self._after_switch_to_working(segment),
        )

    def _after_switch_to_working(self, segment: int) -> None:
        # Ghi lại NGAY, không chen một lượt đọc trang vào giữa: Session không
        # reentrant nên lệnh đọc đó sẽ chiếm chỗ và lần ghi lại bị nuốt mất.
        # Trang thì đã biết chắc — ECU vừa ack lệnh đặt trang.
        self.memory_view.set_xcp_page_indicator(WORKING_PAGE)
        QTimer.singleShot(0, self.memory_view.retry_write)

    def refresh_pages(self, segment: int) -> None:
        if not self._guard():
            return

        def read_both() -> tuple[int | None, int | None]:
            ecu = self.session.get_page(segment, PageMode.ECU)
            xcp = self.session.get_page(segment, PageMode.XCP)
            return ecu, xcp

        self._call(
            "Đang đọc trạng thái trang…",
            read_both,
            on_ok=lambda pages: self.memory_view.on_pages(segment, *pages),
        )

    def set_page(self, segment: int, page: int, mode: PageMode) -> None:
        if not self._guard():
            return
        self._call(
            f"Đang đặt trang {page} cho {mode.name}…",
            self.session.set_page, segment, page, mode,
            on_ok=lambda _: self.memory_view.refresh_pages(),
        )

    def copy_page(self, src_seg: int, src_page: int, dst_seg: int, dst_page: int) -> None:
        if not self._guard():
            return

        def err(exc: Exception) -> None:
            if isinstance(exc, WriteProtectedError):
                self._on_write_protected(exc)
            else:
                errors.show_error(self, exc)

        self._call(
            f"Đang copy trang {src_page} → {dst_page}…",
            self.session.copy_page, src_seg, src_page, dst_seg, dst_page,
            on_ok=lambda _: self.memory_view.refresh_pages(),
            on_err=err,
        )

    # ── A2L / calibration ────────────────────────────────────────────────────

    def _on_a2l_load_requested(self, path: str) -> None:
        self._call(
            "Nạp A2L…",
            self.session.load_a2l, path,
            on_ok=lambda _: self._after_a2l_load(),
        )

    def _after_a2l_load(self) -> None:
        db = self.session.symbols
        self.calibration_view.set_database(db)
        self.notify(
            "A2L đã nạp",
            f"{len(db.characteristics)} CHARACTERISTIC, {len(db.measurements)} MEASUREMENT",
        )
        self.switch_to(self.calibration_view)

    def read_all_characteristics(self) -> None:
        if not self._guard():
            return
        symbols = self.session.symbols
        if not symbols.characteristics:
            self.calibration_view.status_label.setText(
                "Chưa nạp A2L hoặc file không có CHARACTERISTIC nào."
            )
            return

        def _batch() -> dict:
            results: dict[str, bytes | None] = {}
            for name, char in symbols.characteristics.items():
                if char.byte_size <= 0:
                    results[name] = None
                    continue
                try:
                    results[name] = self.session.read(char.address, char.byte_size)
                except Exception:  # noqa: BLE001
                    results[name] = None
            return results

        self._call(
            "Đang đọc tất cả tham số…",
            _batch,
            on_ok=self.calibration_view.on_batch_read_done,
        )

    def write_characteristic(self, name: str, addr: int, data: bytes) -> None:
        if not self._guard():
            return

        def err(exc: Exception) -> None:
            if isinstance(exc, WriteProtectedError):
                self._on_cal_write_protected(exc, name, addr, data)
            else:
                errors.show_error(self, exc)

        self._call(
            f"Đang ghi '{name}'…",
            self.session.write, addr, data,
            on_ok=lambda _: self.calibration_view.on_write_done(name),
            on_err=err,
        )

    def _on_cal_write_protected(
        self, exc: WriteProtectedError, name: str, addr: int, data: bytes
    ) -> None:
        """UI chỉ có khái niệm Working/Reference — chuyển page nghĩa là chuyển
        CẢ ECU lẫn XCP cùng lúc (DESIGN.md §5), không riêng XCP như memory panel cũ."""
        if not ask_switch_to_working_page(self, exc.description):
            return
        seg = self.calibration_view.segment_spin.value()

        def _both() -> None:
            self.session.set_page(seg, CAL_WORKING_PAGE, PageMode.ECU)
            self.session.set_page(seg, CAL_WORKING_PAGE, PageMode.XCP)

        self._call(
            "Đang chuyển sang Working…",
            _both,
            on_ok=lambda _: self._after_cal_switch_working(seg, name, addr, data),
        )

    def _after_cal_switch_working(
        self, segment: int, name: str, addr: int, data: bytes
    ) -> None:
        self.calibration_view.set_page_indicator(CAL_WORKING_PAGE)
        self._call(
            f"Đang ghi lại '{name}'…",
            self.session.write, addr, data,
            on_ok=lambda _: self.calibration_view.on_write_done(name),
        )

    def cal_get_pages(self, segment: int) -> None:
        if not self._guard():
            return

        def read_both() -> tuple[int | None, int | None]:
            ecu = self.session.get_page(segment, PageMode.ECU)
            xcp = self.session.get_page(segment, PageMode.XCP)
            return ecu, xcp

        self._call(
            "Đang đọc trạng thái trang…",
            read_both,
            on_ok=lambda pages: self.calibration_view.on_pages(segment, *pages),
        )

    def cal_set_page(self, segment: int, page: int) -> None:
        """Đặt CẢ ECU lẫn XCP về `page` — UI chỉ biết Working/Reference, không
        set hai trang lệch nhau có chủ đích (DESIGN.md §5)."""
        if not self._guard():
            return

        def _both() -> None:
            self.session.set_page(segment, page, PageMode.ECU)
            self.session.set_page(segment, page, PageMode.XCP)

        name = "Working" if page == CAL_WORKING_PAGE else "Reference"
        self._call(
            f"Đang chuyển sang {name}…",
            _both,
            on_ok=lambda _: self.cal_get_pages(segment),
        )

    def cal_copy_page(
        self, src_seg: int, src_page: int, dst_seg: int, dst_page: int
    ) -> None:
        if not self._guard():
            return
        self._call(
            f"Đang copy trang {src_page} → {dst_page}…",
            self.session.copy_page, src_seg, src_page, dst_seg, dst_page,
            on_ok=lambda _: self.cal_get_pages(dst_seg),
        )

    # ── trace ────────────────────────────────────────────────────────────────

    def _poll_trace(self) -> None:
        try:
            entries = self.session.drain_trace()
            dropped = self.session.dropped_frames
        except Exception:  # noqa: BLE001 — timer không được chết vì một lần lỗi
            log.exception("drain_trace() lỗi")
            self.trace_timer.stop()
            return
        self.trace_view.feed(entries, dropped)
        self.drop_label.setText(f"frame bị bỏ: {dropped}" if dropped else "")
        self._refresh_state()

    def _refresh_state(self) -> None:
        state = self.session.state
        text = {
            ConnState.DISCONNECTED: "Chưa kết nối",
            ConnState.CONNECTING: "Đang kết nối…",
            ConnState.CONNECTED: "Đã kết nối",
            ConnState.ERROR: "LỖI — bus không dùng được",
        }[state]
        self.state_label.setText(text)
        caps = self.session.caps
        self.caps_label.setText(self._caps_summary(caps) if caps else "")
        self.act_disconnect.setEnabled(state is ConnState.CONNECTED and not self.busy)

    @staticmethod
    def _caps_summary(caps: SlaveCaps | None) -> str:
        if caps is None:
            return ""
        res = "/".join(n for n, on in (
            ("CAL", caps.supports_cal_pag), ("DAQ", caps.supports_daq),
            ("STIM", caps.supports_stim), ("PGM", caps.supports_pgm),
        ) if on) or "không có resource nào"
        seed = "  ·  cần seed&key" if caps.needs_seed_and_key else ""
        ident = f"  ·  {caps.id_string}" if caps.id_string else ""
        return (
            f"MAX_CTO {caps.max_cto}  ·  MAX_DTO {caps.max_dto}  ·  "
            f"{caps.byte_order}-endian  ·  XCP "
            f"{caps.protocol_version[0]}.{caps.protocol_version[1]}  ·  {res}{seed}{ident}"
        )

    # ── excepthook + thoát ───────────────────────────────────────────────────

    def report_unexpected(self, exc: BaseException) -> None:
        """Gọi được từ THREAD BẤT KỲ — signal đẩy về UI thread."""
        self.unexpected_error.emit(exc)

    def _on_unexpected_error(self, exc: object) -> None:
        errors.show_unexpected(self, exc, str(current_log_path()))  # type: ignore[arg-type]

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt đặt tên
        # Lưu trạng thái dock trước khi đóng
        _settings = QSettings("xcptool", "xcptool")
        _settings.setValue("dock_state", self.dock_manager.save_state())
        _settings.setValue("debug_area_collapsed", self.dock_manager.is_debug_area_collapsed())

        self.trace_timer.stop()
        if self._connect_task is not None:
            self._connect_task.cancel()
        try:
            self.session.close()
        except Exception:  # noqa: BLE001 — close() không được ném; nếu ném thì
            log.exception("session.close() ném ngoại lệ — đó là bug của backend")
        self.runner.wait(3000)
        super().closeEvent(event)
