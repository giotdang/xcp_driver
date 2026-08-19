"""Tạo và quản lý các QDockWidget debug — Trace CAN, Lệnh thô, Memory/Debug."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QToolButton,
    QWidget,
)

__all__ = ["DockManager"]

_ARROW_COLLAPSE = "▼"  # ▼ — vùng debug đang mở, bấm để thu nhỏ (mũi tên xuống)
_ARROW_EXPAND = "▲"    # ▲ — vùng debug đang thu nhỏ, bấm để mở lại (mũi tên lên)

_TITLEBAR_HEIGHT = 28
_DEFAULT_EXPANDED_HEIGHT = 220
_WIDGET_HEIGHT_MAX = 16_777_215  # QWIDGETSIZE_MAX của Qt — không export qua PySide6


class DockManager:
    """Tạo các dock widget và gán vào QMainWindow."""

    def __init__(self, main_window: QMainWindow) -> None:
        self._mw = main_window
        self.trace_dock: QDockWidget | None = None
        self.console_dock: QDockWidget | None = None
        self.memory_dock: QDockWidget | None = None
        self._debug_arrow_btns: list[QToolButton] = []
        self._debug_collapsed = False
        self._expanded_height: int | None = None

    def setup(
        self,
        trace_widget: QWidget,
        console_widget: QWidget,
        memory_widget: QWidget,
    ) -> None:
        """Tạo dock widgets và add vào main window."""
        self.trace_dock = self._make_dock(
            "Trace CAN", trace_widget, closable=False, on_toggle=self.toggle_debug_area
        )
        self.console_dock = self._make_dock(
            "Lệnh thô", console_widget, closable=False, on_toggle=self.toggle_debug_area
        )
        self.memory_dock = self._make_dock("Memory / Debug", memory_widget, closable=True)

        self._mw.addDockWidget(Qt.BottomDockWidgetArea, self.trace_dock)
        self._mw.addDockWidget(Qt.BottomDockWidgetArea, self.console_dock)
        self._mw.tabifyDockWidget(self.trace_dock, self.console_dock)
        self._mw.addDockWidget(Qt.BottomDockWidgetArea, self.memory_dock)
        self._mw.tabifyDockWidget(self.console_dock, self.memory_dock)

        # Trace CAN là tab mặc định hiển thị
        self.trace_dock.raise_()
        # Memory dock mặc định ẩn
        self.memory_dock.hide()

    def save_state(self) -> bytes:
        return bytes(self._mw.saveState())

    def restore_state(self, state: bytes) -> bool:
        return self._mw.restoreState(state)

    # ── vùng debug (Trace CAN + Lệnh thô) ────────────────────────────────────

    def is_debug_area_collapsed(self) -> bool:
        return self._debug_collapsed

    def toggle_debug_area(self) -> bool:
        """Thu nhỏ/mở rộng Trace CAN + Lệnh thô để nhường chỗ cho panel chính
        (Calibration). Memory/Debug dock không đụng tới — nó có toggle riêng
        qua View menu.

        KHÔNG dùng `hide()` — nút mũi tên nằm ngay trên title bar của chính
        dock này, ẩn cả dock thì nút cũng biến mất theo, không còn cách nào
        bấm lại để mở ra (bug user báo cáo). Thay vào đó thu nhỏ chiều cao
        dock xuống đúng bằng title bar, giống nút minimize — dock vẫn "hiện
        diện" nên title bar (và nút) luôn bấm được.

        Trả về True nếu đang MỞ RỘNG sau khi gọi.
        """
        if self._debug_collapsed:
            self._expand_debug_area()
        else:
            self._collapse_debug_area()
        self.sync_toggle_buttons()
        return not self._debug_collapsed

    def _collapse_debug_area(self) -> None:
        # Chỉ nhớ chiều cao hiện tại nếu nó có nghĩa (đã qua layout thật) —
        # gọi collapse ngay lúc khởi động (khôi phục trạng thái đã lưu) thì
        # trace_dock.height() có thể còn là giá trị tạm trước khi layout chạy.
        current_height = self.trace_dock.height()
        if current_height > _TITLEBAR_HEIGHT:
            self._expanded_height = current_height
        # setMaximumHeight(0) thay vì hide(): hide() loại nội dung khỏi layout
        # HOÀN TOÀN, kể cả chiều rộng nó đóng góp — QMainWindowLayout khi đó
        # tính lại bề rộng cả dock/tab-group chỉ theo minimumSizeHint() của
        # title bar (rất hẹp), để lại khoảng trống lớn bên phải (bug user báo
        # cáo). Ép chiều cao tối đa = 0 vẫn loại bỏ được ràng buộc minimum-
        # height (để resizeDocks() thu nhỏ được xuống dưới minimumSizeHint),
        # nhưng KHÔNG đụng tới sizeHint bề rộng — dock vẫn full-width.
        self.trace_dock.widget().setMaximumHeight(0)
        self.console_dock.widget().setMaximumHeight(0)
        self._mw.resizeDocks(
            [self.trace_dock], [_TITLEBAR_HEIGHT], Qt.Orientation.Vertical
        )
        self._debug_collapsed = True

    def _expand_debug_area(self) -> None:
        self.trace_dock.widget().setMaximumHeight(_WIDGET_HEIGHT_MAX)
        self.console_dock.widget().setMaximumHeight(_WIDGET_HEIGHT_MAX)
        height = self._expanded_height or _DEFAULT_EXPANDED_HEIGHT
        self._mw.resizeDocks([self.trace_dock], [height], Qt.Orientation.Vertical)
        self.trace_dock.raise_()
        self._debug_collapsed = False

    def ensure_debug_area_expanded(self) -> None:
        """Mở lại nếu đang thu nhỏ — gọi khi user chủ động điều hướng tới
        Trace CAN/Lệnh thô (Ctrl+1/2, `MainWindow.switch_to()`), vì lúc đó họ
        rõ ràng muốn NHÌN THẤY nội dung chứ không chỉ raise() một tab rỗng."""
        if self._debug_collapsed:
            self._expand_debug_area()
        self.sync_toggle_buttons()

    @property
    def debug_toggle_symbol(self) -> str:
        """Mũi tên hiện đang hiện trên title bar của Trace CAN/Lệnh thô."""
        return _ARROW_EXPAND if self._debug_collapsed else _ARROW_COLLAPSE

    def sync_toggle_buttons(self) -> None:
        """Đồng bộ mũi tên + tooltip trên title bar của Trace CAN/Lệnh thô với
        trạng thái thu nhỏ/mở thật."""
        arrow = self.debug_toggle_symbol
        tooltip = (
            "Mở lại Trace CAN + Lệnh thô"
            if self._debug_collapsed else
            "Thu nhỏ Trace CAN + Lệnh thô để nhường chỗ cho panel Hiệu chỉnh"
        )
        for btn in self._debug_arrow_btns:
            btn.setText(arrow)
            btn.setToolTip(tooltip)

    # ── dựng dock widget ─────────────────────────────────────────────────────

    def _make_dock(
        self,
        title: str,
        widget: QWidget,
        closable: bool,
        on_toggle: Callable[[], None] | None = None,
    ) -> QDockWidget:
        dock = QDockWidget(title, self._mw)
        dock.setWidget(widget)
        dock.setAllowedAreas(
            Qt.BottomDockWidgetArea | Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
        )
        features = QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        if closable:
            features |= QDockWidget.DockWidgetClosable
        dock.setFeatures(features)

        if on_toggle is not None:
            # Title bar riêng: chữ + nút mũi tên thu nhỏ/mở ở góc phải — nút
            # này là con thật của dock nên trôi theo khi dock được float/kéo đi.
            dock.setTitleBarWidget(self._make_titlebar(dock, title, on_toggle))
        else:
            # QSS để khớp Fluent theme — chỉ title bar gốc (dock giữ title bar mặc định)
            dock.setStyleSheet("""
                QDockWidget::title {
                    background: transparent;
                    padding: 4px 8px;
                    font-size: 13px;
                }
                QDockWidget::close-button,
                QDockWidget::float-button {
                    border: none;
                    padding: 0;
                }
            """)
        return dock

    def _make_titlebar(
        self, dock: QDockWidget, title: str, on_toggle: Callable[[], None]
    ) -> QWidget:
        bar = QWidget(dock)
        bar.setFixedHeight(_TITLEBAR_HEIGHT)
        bar.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 2, 4, 2)
        layout.setSpacing(4)

        label = QLabel(title, bar)
        label.setStyleSheet("font-size: 13px;")
        layout.addWidget(label)
        layout.addStretch(1)

        btn = QToolButton(bar)
        btn.setText(_ARROW_COLLAPSE)
        btn.setAutoRaise(True)
        btn.setFixedSize(22, 22)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QToolButton { color: #0078d4; background: transparent;"
            " border: none; font-size: 15px; font-weight: bold; }"
            " QToolButton:hover { color: #0060a3; }"
        )
        btn.clicked.connect(on_toggle)
        layout.addWidget(btn, 0, Qt.AlignBottom)
        self._debug_arrow_btns.append(btn)

        return bar
