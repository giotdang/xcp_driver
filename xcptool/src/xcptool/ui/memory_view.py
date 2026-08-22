"""Memory panel — live hex dump with in-place editing + calibration page controls.

Two-page model (DESIGN.md §5): the ECU *runs* on one page, XCP *looks* at another;
both are independent. Writing while XCP points at the reference page (ROM) triggers
CRC_WRITE_PROTECTED. This is not a bug but an incorrect state, so the error message
must include a button to fix it — see `ask_switch_to_working_page`.
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
    """Dedicated dialog for CRC_WRITE_PROTECTED. Returns True if user wants to switch."""
    box = MessageBox(
        "Write protected — memory region is read-only",
        f"{detail}\n\n"
        "Most likely cause: XCP is currently pointing at the reference page (ROM) "
        f"instead of the working page (RAM).\n\n"
        f"Switch XCP to page {WORKING_PAGE} and retry the write?",
        parent,
    )
    box.yesButton.setText(f"Switch to page {WORKING_PAGE} and retry")
    box.cancelButton.setText("Keep current page")
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
        self.ext_spin.setToolTip("Address extension — most ECUs use 0")

        self.read_btn = PrimaryPushButton("Read", self)
        self.read_btn.clicked.connect(self.do_read)

        self.write_btn = PushButton("Write Block", self)
        self.write_btn.clicked.connect(self.do_write)
        self.write_btn.setEnabled(False)

        self.revert_btn = PushButton("Discard Changes", self)
        self.revert_btn.clicked.connect(self._revert)
        self.revert_btn.setEnabled(False)

        addr_row = QHBoxLayout()
        addr_row.addWidget(BodyLabel("Address:", self))
        addr_row.addWidget(self.addr_edit)
        addr_row.addWidget(BodyLabel("Size (bytes):", self))
        addr_row.addWidget(self.size_spin)
        addr_row.addWidget(BodyLabel("Ext:", self))
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

        self.refresh_pages_btn = PushButton("Read Page Status", self)
        self.refresh_pages_btn.clicked.connect(self.refresh_pages)

        self.page_spin = SpinBox(self)
        self.page_spin.setRange(0, 255)
        self.page_spin.lineEdit().setMinimumWidth(40)

        self.mode_combo = ComboBox(self)
        self.mode_combo.addItems(["XCP Page (tool view)", "ECU Page (ECU execution)"])

        self.set_page_btn = PushButton("Set Page", self)
        self.set_page_btn.clicked.connect(self._on_set_page)

        self.copy_src_spin = SpinBox(self)
        self.copy_src_spin.setRange(0, 255)
        self.copy_src_spin.setValue(1)
        self.copy_src_spin.lineEdit().setMinimumWidth(40)
        self.copy_dst_spin = SpinBox(self)
        self.copy_dst_spin.setRange(0, 255)
        self.copy_dst_spin.setValue(0)
        self.copy_dst_spin.lineEdit().setMinimumWidth(40)
        self.copy_btn = PushButton("Copy Page", self)
        self.copy_btn.clicked.connect(self._on_copy_page)

        self.reread_cb = CheckBox("Re-read after write (verify)", self)
        self.reread_cb.setChecked(True)

        page_grid = QGridLayout()
        page_grid.addWidget(BodyLabel("Segment:", self), 0, 0)
        page_grid.addWidget(self.segment_spin, 0, 1)
        page_grid.addWidget(BodyLabel("ECU Active Page:", self), 0, 2)
        page_grid.addWidget(self.ecu_page_label, 0, 3)
        page_grid.addWidget(BodyLabel("XCP View Page:", self), 0, 4)
        page_grid.addWidget(self.xcp_page_label, 0, 5)
        page_grid.addWidget(self.refresh_pages_btn, 0, 6)
        page_grid.addWidget(BodyLabel("Set Page:", self), 1, 0)
        page_grid.addWidget(self.page_spin, 1, 1)
        page_grid.addWidget(self.mode_combo, 1, 2, 1, 2)
        page_grid.addWidget(self.set_page_btn, 1, 4)
        page_grid.addWidget(BodyLabel("Copy:", self), 2, 0)
        page_grid.addWidget(self.copy_src_spin, 2, 1)
        page_grid.addWidget(BodyLabel("→", self), 2, 2)
        page_grid.addWidget(self.copy_dst_spin, 2, 3)
        page_grid.addWidget(self.copy_btn, 2, 4)
        page_grid.setColumnStretch(7, 1)

        self.status_label = CaptionLabel("No memory region loaded.", self)
        self.status_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(addr_row)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.status_label)
        layout.addLayout(page_grid)
        layout.addWidget(CaptionLabel(
            "Addresses in the A2L file always point to ROM; the ECU redirects to RAM when XCP "
            "is on the working page. Edit a cell then click “Write Block” — the entire block "
            "is written atomically; the ECU never passes through a half-old, half-new state.", self))

    # ── read / write ────────────────────────────────────────────────────────────

    @property
    def address(self) -> int:
        return self._parse_addr(self.addr_edit.text())

    @property
    def ext(self) -> int:
        return self.ext_spin.value()

    @staticmethod
    def _parse_addr(text: str) -> int:
        """Address field is always hex, with or without 0x prefix."""
        cleaned = text.strip().lower().removeprefix("0x").replace("_", "")
        return int(cleaned, 16)

    def do_read(self) -> None:
        try:
            addr = self.address
        except ValueError:
            self.status_label.setText("Invalid address — use format 0x80000000.")
            return
        self.status_label.setText(f"Reading {self.size_spin.value()} bytes at 0x{addr:08X}…")
        self._read_cb(addr, self.size_spin.value())

    def do_write(self) -> None:
        if not self._edited:
            return
        self._write_cb(self._base_addr, bytes(self._edited))

    def retry_write(self) -> None:
        """Re-write current content — used after page switch."""
        if self._edited:
            self._write_cb(self._base_addr, bytes(self._edited))

    # ── results from MainWindow ────────────────────────────────────────────────

    def on_read_done(self, addr: int, data: bytes) -> None:
        self._base_addr = addr
        self._original = data
        self._edited = bytearray(data)
        self._render()
        self.write_btn.setEnabled(False)
        self.revert_btn.setEnabled(False)
        self.status_label.setText(
            f"Read {len(data)} bytes at 0x{addr:08X}. Double-click a cell to edit."
        )

    def on_write_done(self) -> None:
        self._original = bytes(self._edited)
        self._render()
        self.write_btn.setEnabled(False)
        self.revert_btn.setEnabled(False)
        self.status_label.setText(
            f"Wrote {len(self._original)} bytes at 0x{self._base_addr:08X}."
        )
        if self.reread_cb.isChecked():
            self._read_cb(self._base_addr, len(self._original))

    def on_pages(self, segment: int, ecu_page: int | None, xcp_page: int | None) -> None:
        self.ecu_page_label.setText("\u2014" if ecu_page is None else str(ecu_page))
        self.xcp_page_label.setText("\u2014" if xcp_page is None else str(xcp_page))
        if xcp_page is not None and xcp_page != WORKING_PAGE:
            self.status_label.setText(
                f"XCP is viewing page {xcp_page} — likely the reference page "
                "(ROM, read-only). Write operations will be rejected."
            )

    def set_xcp_page_indicator(self, page: int) -> None:
        """Update indicator after ECU has acked SET_CAL_PAGE, avoiding a read."""
        self.xcp_page_label.setText(str(page))

    def refresh_pages(self) -> None:
        self._get_pages_cb(self.segment_spin.value())

    def set_xcp_working_page(self) -> None:
        self._set_page_cb(self.segment_spin.value(), WORKING_PAGE, PageMode.XCP)

    def set_busy(self, busy: bool) -> None:
        for w in (self.read_btn, self.set_page_btn, self.copy_btn, self.refresh_pages_btn):
            w.setEnabled(not busy)
        self.write_btn.setEnabled(not busy and bool(self._dirty_cells()))

    # ── internal ───────────────────────────────────────────────────────────────

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
            self.status_label.setText(f"'{text}' is not a valid hex byte (00–FF).")
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
            f"{len(dirty)} byte(s) modified, not yet written to ECU."
            if dirty else "No pending changes."
        )
