"""Panel bộ nhớ — hex dump sửa trực tiếp + điều khiển trang calibration.

Mô hình hai trang (DESIGN.md §5): ECU đang *chạy* trên một trang, XCP đang *nhìn*
vào một trang, hai thứ độc lập. Ghi khi XCP trỏ reference page → ECU trả
CRC_WRITE_PROTECTED. Đó không phải bug mà là trạng thái sai, nên thông báo phải
kèm nút sửa trạng thái đó — xem `ask_switch_to_working_page`.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    LineEdit,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    TableWidget,
    isDarkTheme,
)

from ..session.api import PageMode

__all__ = ["MemoryView", "ask_switch_to_working_page", "WORKING_PAGE"]

BYTES_PER_ROW = 16

# XCP không chuẩn hoá "trang nào là working" — spec chỉ đánh số trang. Quy ước
# 0 = working (RAM) / 1 = reference (ROM) là của slave XcpBasic trong dự án này;
# ECU khác có thể đánh số khác nên đây là *gợi ý mặc định*, user đổi được.
WORKING_PAGE = 0


def ask_switch_to_working_page(parent: QWidget | None, detail: str) -> bool:
    """Hộp thoại chuyên cho CRC_WRITE_PROTECTED. True = user muốn chuyển trang."""
    box = MessageBox(
        "Không ghi được — vùng nhớ đang được bảo vệ",
        f"{detail}\n\n"
        "Nguyên nhân thường gặp: XCP đang trỏ vào reference page (ROM, chỉ đọc) "
        f"thay vì working page (RAM).\n\n"
        f"Chuyển XCP sang trang {WORKING_PAGE} rồi ghi lại?",
        parent,
    )
    box.yesButton.setText(f"Chuyển sang trang {WORKING_PAGE} và ghi lại")
    box.cancelButton.setText("Để nguyên")
    return bool(box.exec())


class MemoryView(QWidget):
    """Callback do MainWindow cấp — mọi lời gọi Session đều chạy trên worker."""

    def __init__(
        self,
        read_cb: Callable[[int, int], None],
        write_cb: Callable[[int, bytes], None],
        get_pages_cb: Callable[[int], None],
        set_page_cb: Callable[[int, int, PageMode], None],
        copy_page_cb: Callable[[int, int, int, int], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("memoryView")
        self._read_cb = read_cb
        self._write_cb = write_cb
        self._get_pages_cb = get_pages_cb
        self._set_page_cb = set_page_cb
        self._copy_page_cb = copy_page_cb

        self._base_addr = 0
        self._original: bytes = b""
        self._edited: bytearray = bytearray()
        self._suspend_signals = False

        self._build_ui()

    # ── dựng giao diện ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)

        self.addr_edit = LineEdit(self)
        self.addr_edit.setText("0x80000000")
        self.addr_edit.setFont(mono)
        self.addr_edit.setFixedWidth(140)
        self.addr_edit.returnPressed.connect(self.do_read)

        self.size_spin = SpinBox(self)
        self.size_spin.setRange(1, 4096)
        self.size_spin.setValue(64)
        self.size_spin.lineEdit().setMinimumWidth(50)

        self.ext_spin = SpinBox(self)
        self.ext_spin.setRange(0, 255)
        self.ext_spin.setValue(0)
        self.ext_spin.lineEdit().setMinimumWidth(40)
        self.ext_spin.setToolTip("Address extension — hầu hết ECU dùng 0")

        self.read_btn = PrimaryPushButton("Đọc", self)
        self.read_btn.clicked.connect(self.do_read)

        self.write_btn = PushButton("Ghi vùng này", self)
        self.write_btn.clicked.connect(self.do_write)
        self.write_btn.setEnabled(False)

        self.revert_btn = PushButton("Bỏ sửa", self)
        self.revert_btn.clicked.connect(self._revert)
        self.revert_btn.setEnabled(False)

        addr_row = QHBoxLayout()
        addr_row.addWidget(BodyLabel("Địa chỉ:", self))
        addr_row.addWidget(self.addr_edit)
        addr_row.addWidget(BodyLabel("Số byte:", self))
        addr_row.addWidget(self.size_spin)
        addr_row.addWidget(BodyLabel("ext:", self))
        addr_row.addWidget(self.ext_spin)
        addr_row.addWidget(self.read_btn)
        addr_row.addWidget(self.write_btn)
        addr_row.addWidget(self.revert_btn)
        addr_row.addStretch(1)

        # ── bảng hex ─────────────────────────────────────────────────────────
        self.table = TableWidget(self)
        self.table.setColumnCount(BYTES_PER_ROW + 1)
        self.table.setHorizontalHeaderLabels(
            [f"{i:X}" for i in range(BYTES_PER_ROW)] + ["ASCII"]
        )
        self.table.setFont(mono)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )
        header = self.table.horizontalHeader()
        for i in range(BYTES_PER_ROW):
            header.setSectionResizeMode(i, QHeaderView.Fixed)
            self.table.setColumnWidth(i, 40)
        header.setSectionResizeMode(BYTES_PER_ROW, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)

        # ── điều khiển trang ─────────────────────────────────────────────────
        self.segment_spin = SpinBox(self)
        self.segment_spin.setRange(0, 255)
        self.segment_spin.lineEdit().setMinimumWidth(40)

        self.ecu_page_label = StrongBodyLabel("—", self)
        self.xcp_page_label = StrongBodyLabel("—", self)

        self.refresh_pages_btn = PushButton("Đọc lại trạng thái trang", self)
        self.refresh_pages_btn.clicked.connect(self.refresh_pages)

        self.page_spin = SpinBox(self)
        self.page_spin.setRange(0, 255)
        self.page_spin.lineEdit().setMinimumWidth(40)

        self.mode_combo = ComboBox(self)
        self.mode_combo.addItems(["Trang XCP (công cụ nhìn)", "Trang ECU (ECU chạy)"])

        self.set_page_btn = PushButton("Đặt trang", self)
        self.set_page_btn.clicked.connect(self._on_set_page)

        self.copy_src_spin = SpinBox(self)
        self.copy_src_spin.setRange(0, 255)
        self.copy_src_spin.setValue(1)
        self.copy_src_spin.lineEdit().setMinimumWidth(40)
        self.copy_dst_spin = SpinBox(self)
        self.copy_dst_spin.setRange(0, 255)
        self.copy_dst_spin.setValue(0)
        self.copy_dst_spin.lineEdit().setMinimumWidth(40)
        self.copy_btn = PushButton("Copy trang", self)
        self.copy_btn.clicked.connect(self._on_copy_page)

        self.reread_cb = CheckBox("Đọc lại sau khi ghi để đối chiếu", self)
        self.reread_cb.setChecked(True)

        page_grid = QGridLayout()
        page_grid.addWidget(BodyLabel("Segment:", self), 0, 0)
        page_grid.addWidget(self.segment_spin, 0, 1)
        page_grid.addWidget(BodyLabel("Trang ECU đang chạy:", self), 0, 2)
        page_grid.addWidget(self.ecu_page_label, 0, 3)
        page_grid.addWidget(BodyLabel("Trang XCP đang nhìn:", self), 0, 4)
        page_grid.addWidget(self.xcp_page_label, 0, 5)
        page_grid.addWidget(self.refresh_pages_btn, 0, 6)
        page_grid.addWidget(BodyLabel("Đặt trang:", self), 1, 0)
        page_grid.addWidget(self.page_spin, 1, 1)
        page_grid.addWidget(self.mode_combo, 1, 2, 1, 2)
        page_grid.addWidget(self.set_page_btn, 1, 4)
        page_grid.addWidget(BodyLabel("Copy:", self), 2, 0)
        page_grid.addWidget(self.copy_src_spin, 2, 1)
        page_grid.addWidget(BodyLabel("→", self), 2, 2)
        page_grid.addWidget(self.copy_dst_spin, 2, 3)
        page_grid.addWidget(self.copy_btn, 2, 4)
        page_grid.setColumnStretch(7, 1)

        self.status_label = CaptionLabel("Chưa đọc vùng nhớ nào.", self)
        self.status_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(addr_row)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.status_label)
        layout.addLayout(page_grid)
        layout.addWidget(CaptionLabel(
            "Địa chỉ trong A2L luôn trỏ ROM; slave tự chuyển hướng sang RAM khi XCP "
            "ở working page. Sửa ô rồi bấm “Ghi vùng này” — cả vùng được ghi trọn "
            "khối, ECU không đi qua trạng thái nửa cũ nửa mới.", self))

    # ── đọc / ghi ────────────────────────────────────────────────────────────

    @property
    def address(self) -> int:
        return self._parse_addr(self.addr_edit.text())

    @property
    def ext(self) -> int:
        return self.ext_spin.value()

    @staticmethod
    def _parse_addr(text: str) -> int:
        """Ô địa chỉ luôn là hex, có hay không có tiền tố 0x."""
        cleaned = text.strip().lower().removeprefix("0x").replace("_", "")
        return int(cleaned, 16)

    def do_read(self) -> None:
        try:
            addr = self.address
        except ValueError:
            self.status_label.setText("Địa chỉ không hợp lệ — nhập dạng 0x80000000.")
            return
        self.status_label.setText(f"Đang đọc {self.size_spin.value()} byte tại 0x{addr:08X}…")
        self._read_cb(addr, self.size_spin.value())

    def do_write(self) -> None:
        if not self._edited:
            return
        self._write_cb(self._base_addr, bytes(self._edited))

    def retry_write(self) -> None:
        """Ghi lại đúng nội dung đang hiện — dùng sau khi chuyển trang."""
        if self._edited:
            self._write_cb(self._base_addr, bytes(self._edited))

    # ── kết quả từ MainWindow ────────────────────────────────────────────────

    def on_read_done(self, addr: int, data: bytes) -> None:
        self._base_addr = addr
        self._original = data
        self._edited = bytearray(data)
        self._render()
        self.write_btn.setEnabled(False)
        self.revert_btn.setEnabled(False)
        self.status_label.setText(
            f"Đã đọc {len(data)} byte tại 0x{addr:08X}. Nhấp đúp một ô để sửa."
        )

    def on_write_done(self) -> None:
        self._original = bytes(self._edited)
        self._render()
        self.write_btn.setEnabled(False)
        self.revert_btn.setEnabled(False)
        self.status_label.setText(
            f"Đã ghi {len(self._original)} byte tại 0x{self._base_addr:08X}."
        )
        if self.reread_cb.isChecked():
            self._read_cb(self._base_addr, len(self._original))

    def on_pages(self, segment: int, ecu_page: int | None, xcp_page: int | None) -> None:
        self.ecu_page_label.setText("—" if ecu_page is None else str(ecu_page))
        self.xcp_page_label.setText("—" if xcp_page is None else str(xcp_page))
        if xcp_page is not None and xcp_page != WORKING_PAGE:
            self.status_label.setText(
                f"XCP đang nhìn trang {xcp_page} — nhiều khả năng là reference page "
                "(ROM, chỉ đọc). Ghi sẽ bị từ chối."
            )

    def set_xcp_page_indicator(self, page: int) -> None:
        """Cập nhật chỉ báo sau khi ECU đã ack SET_CAL_PAGE, khỏi tốn một lượt đọc."""
        self.xcp_page_label.setText(str(page))

    def refresh_pages(self) -> None:
        self._get_pages_cb(self.segment_spin.value())

    def set_xcp_working_page(self) -> None:
        self._set_page_cb(self.segment_spin.value(), WORKING_PAGE, PageMode.XCP)

    def set_busy(self, busy: bool) -> None:
        for w in (self.read_btn, self.set_page_btn, self.copy_btn, self.refresh_pages_btn):
            w.setEnabled(not busy)
        self.write_btn.setEnabled(not busy and bool(self._dirty_cells()))

    # ── nội bộ ───────────────────────────────────────────────────────────────

    def _on_set_page(self) -> None:
        mode = PageMode.XCP if self.mode_combo.currentIndex() == 0 else PageMode.ECU
        self._set_page_cb(self.segment_spin.value(), self.page_spin.value(), mode)

    def _on_copy_page(self) -> None:
        seg = self.segment_spin.value()
        self._copy_page_cb(seg, self.copy_src_spin.value(), seg, self.copy_dst_spin.value())

    def _dirty_cells(self) -> list[int]:
        return [i for i, (a, b) in enumerate(zip(self._original, self._edited)) if a != b]

    def _revert(self) -> None:
        self._edited = bytearray(self._original)
        self._render()
        self.write_btn.setEnabled(False)
        self.revert_btn.setEnabled(False)

    def _render(self) -> None:
        self._suspend_signals = True
        try:
            data = self._edited
            rows = (len(data) + BYTES_PER_ROW - 1) // BYTES_PER_ROW
            self.table.setRowCount(rows)
            self.table.setVerticalHeaderLabels(
                [f"{self._base_addr + r * BYTES_PER_ROW:08X}" for r in range(rows)]
            )
            dirty = set(self._dirty_cells())
            changed = QColor("#FFB86C") if isDarkTheme() else QColor("#B35C00")

            for r in range(rows):
                chunk = data[r * BYTES_PER_ROW:(r + 1) * BYTES_PER_ROW]
                for c in range(BYTES_PER_ROW):
                    idx = r * BYTES_PER_ROW + c
                    item = QTableWidgetItem(f"{data[idx]:02X}" if idx < len(data) else "")
                    item.setTextAlignment(Qt.AlignCenter)
                    if idx >= len(data):
                        item.setFlags(Qt.ItemIsEnabled)
                    elif idx in dirty:
                        item.setForeground(changed)
                    self.table.setItem(r, c, item)
                ascii_item = QTableWidgetItem(
                    "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                )
                ascii_item.setFlags(Qt.ItemIsEnabled)
                self.table.setItem(r, BYTES_PER_ROW, ascii_item)
        finally:
            self._suspend_signals = False

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._suspend_signals or item.column() >= BYTES_PER_ROW:
            return
        idx = item.row() * BYTES_PER_ROW + item.column()
        if idx >= len(self._edited):
            return
        text = item.text().strip()
        try:
            value = int(text, 16)
            if not 0 <= value <= 0xFF:
                raise ValueError
        except ValueError:
            self.status_label.setText(f"'{text}' không phải byte hex (00–FF).")
            self._suspend_signals = True
            item.setText(f"{self._edited[idx]:02X}")
            self._suspend_signals = False
            return

        self._edited[idx] = value
        self._render()
        dirty = self._dirty_cells()
        self.write_btn.setEnabled(bool(dirty))
        self.revert_btn.setEnabled(bool(dirty))
        self.status_label.setText(
            f"{len(dirty)} byte đã sửa, chưa ghi xuống ECU."
            if dirty else "Không có thay đổi nào."
        )
