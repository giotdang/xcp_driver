"""Dialog chọn thiết bị CAN + tham số bus.

Hai điểm không được cắt bớt:

  * Thiết bị `available=False` VẪN hiện, kèm `hint` nói rõ phải cài gói nào.
    Im lặng bỏ qua là lỗi user gặp nhiều nhất với công cụ loại này.
  * `list_devices()` là lời gọi CHẶN → chạy trên worker, dialog hiện spinner
    trong lúc chờ.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    IndeterminateProgressRing,
    LineEdit,
    ListWidget,
    MessageBoxBase,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
)
from PySide6.QtWidgets import QListWidgetItem

from ..session.api import BusConfig, DeviceInfo

__all__ = ["DeviceDialog"]

# Giá trị mặc định của ô nhập, lấy thẳng từ contract thay vì gõ lại hằng số.
_BUS_DEFAULTS = BusConfig(backend="", channel="")


class DeviceDialog(MessageBoxBase):
    """Trả về `BusConfig` qua `selected_config` sau khi user bấm Kết nối.

    `initial` là lựa chọn để tự điền sẵn — lấy từ `session.load_config()` phía
    gọi (thường là `MainWindow`). Dialog không tự đọc/ghi file cấu hình nào;
    việc "nhớ lựa chọn" là trách nhiệm của `Session` (xem `session/api.py`),
    không phải của UI.
    """

    detect_requested = Signal()

    def __init__(
        self, parent: QWidget | None = None, initial: BusConfig | None = None
    ) -> None:
        super().__init__(parent)
        self.selected_config: BusConfig | None = None
        self._devices: list[DeviceInfo] = []
        self._initial = initial or _BUS_DEFAULTS

        self.titleLabel = SubtitleLabel("Chọn thiết bị CAN", self)

        self.list = ListWidget(self)
        self.list.setMinimumHeight(200)
        self.list.currentRowChanged.connect(self._on_row_changed)

        self.spinner = IndeterminateProgressRing(self)
        self.spinner.setFixedSize(24, 24)
        self.spinner.hide()

        self.detect_btn = PushButton("Dò lại thiết bị", self)
        self.detect_btn.clicked.connect(self._on_detect_clicked)

        self.hint_label = CaptionLabel("", self)
        self.hint_label.setWordWrap(True)

        top_row = QHBoxLayout()
        top_row.addWidget(self.detect_btn)
        top_row.addWidget(self.spinner)
        top_row.addStretch(1)
        self.status_label = BodyLabel("", self)
        top_row.addWidget(self.status_label)

        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)

        self.bitrate_combo = ComboBox(self)
        for b in (125_000, 250_000, 500_000, 800_000, 1_000_000):
            self.bitrate_combo.addItem(f"{b // 1000} kbps", userData=b)
        self.bitrate_combo.setCurrentIndex(2)

        self.cro_edit = LineEdit(self)
        self.cro_edit.setFont(mono)
        self.dto_edit = LineEdit(self)
        self.dto_edit.setFont(mono)
        self.ext_cb = CheckBox("CAN ID 29-bit", self)
        self.pad_cb = CheckBox("Đệm đủ 8 byte (MAX_DLC_REQUIRED)", self)
        self.pad_cb.setChecked(True)
        self.t1_spin = SpinBox(self)
        self.t1_spin.setRange(100, 10_000)
        self.t1_spin.setSingleStep(100)
        self.t1_spin.setValue(1000)
        self.t1_spin.setSuffix(" ms")

        grid = QGridLayout()
        grid.addWidget(BodyLabel("Bitrate:", self), 0, 0)
        grid.addWidget(self.bitrate_combo, 0, 1)
        grid.addWidget(BodyLabel("CRO (host→ECU):", self), 0, 2)
        grid.addWidget(self.cro_edit, 0, 3)
        grid.addWidget(BodyLabel("DTO (ECU→host):", self), 0, 4)
        grid.addWidget(self.dto_edit, 0, 5)
        grid.addWidget(BodyLabel("Timeout T1:", self), 1, 0)
        grid.addWidget(self.t1_spin, 1, 1)
        grid.addWidget(self.ext_cb, 1, 2, 1, 2)
        grid.addWidget(self.pad_cb, 1, 4, 1, 2)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addLayout(top_row)
        self.viewLayout.addWidget(self.list)
        self.viewLayout.addWidget(self.hint_label)
        self.viewLayout.addWidget(StrongBodyLabel("Tham số bus", self))
        self.viewLayout.addLayout(grid)
        self.viewLayout.addWidget(CaptionLabel(
            "CRO và DTO thường dùng chung một ID cho response và dữ liệu DAQ — "
            "công cụ tự phân loại theo byte 0.", self))

        self.yesButton.setText("Kết nối")
        self.cancelButton.setText("Đóng")
        self.yesButton.setEnabled(False)
        self.widget.setMinimumWidth(720)

        self._apply_initial_config()

    # ── nạp danh sách ────────────────────────────────────────────────────────

    def set_busy(self, busy: bool) -> None:
        self.spinner.setVisible(busy)
        self.detect_btn.setEnabled(not busy)
        if busy:
            self.status_label.setText("Đang dò thiết bị…")

    def set_devices(self, devices: list[DeviceInfo]) -> None:
        self._devices = devices
        self.list.clear()
        select_row = -1
        for i, d in enumerate(devices):
            mark = "" if d.available else "  (chưa dùng được)"
            item = QListWidgetItem(f"{d.display_name}   ·   {d.backend}:{d.channel}{mark}")
            if not d.available:
                item.setForeground(Qt.gray)
            self.list.addItem(item)
            if d.backend == self._initial.backend and d.channel == self._initial.channel:
                select_row = i
        self.status_label.setText(
            f"{sum(1 for d in devices if d.available)}/{len(devices)} kênh dùng được"
        )
        if select_row < 0:
            select_row = next((i for i, d in enumerate(devices) if d.available), -1)
        if select_row >= 0:
            self.list.setCurrentRow(select_row)

    def set_error(self, message: str) -> None:
        self.status_label.setText(message)

    # ── nội bộ ───────────────────────────────────────────────────────────────

    def _on_detect_clicked(self) -> None:
        self.detect_requested.emit()

    def _on_row_changed(self, row: int) -> None:
        if not 0 <= row < len(self._devices):
            self.yesButton.setEnabled(False)
            self.hint_label.setText("")
            return
        d = self._devices[row]
        self.yesButton.setEnabled(d.available)
        if d.available:
            self.hint_label.setText(
                f"Serial: {d.serial}" if d.serial else "Kênh này sẵn sàng."
            )
        else:
            self.hint_label.setText(
                d.hint or "Kênh này hiện không dùng được (không rõ nguyên nhân)."
            )

    def _apply_initial_config(self) -> None:
        c = self._initial
        self.cro_edit.setText(f"0x{c.cro_id:03X}")
        self.dto_edit.setText(f"0x{c.dto_id:03X}")
        self.ext_cb.setChecked(c.extended_id)
        self.pad_cb.setChecked(c.pad_dlc)
        self.t1_spin.setValue(int(c.t1_timeout_s * 1000))
        idx = self.bitrate_combo.findData(c.bitrate)
        if idx >= 0:
            self.bitrate_combo.setCurrentIndex(idx)

    def build_config(self) -> BusConfig | None:
        row = self.list.currentRow()
        if not 0 <= row < len(self._devices):
            return None
        d = self._devices[row]
        try:
            cro = int(self.cro_edit.text().strip().lower().removeprefix("0x"), 16)
            dto = int(self.dto_edit.text().strip().lower().removeprefix("0x"), 16)
        except ValueError:
            self.status_label.setText("CAN ID phải là số hex, ví dụ 7E0.")
            return None
        return BusConfig(
            backend=d.backend,
            channel=d.channel,
            bitrate=self.bitrate_combo.currentData(),
            cro_id=cro,
            dto_id=dto,
            extended_id=self.ext_cb.isChecked(),
            pad_dlc=self.pad_cb.isChecked(),
            t1_timeout_s=self.t1_spin.value() / 1000.0,
        )

    def validate(self) -> bool:  # MessageBoxBase gọi trước khi accept()
        cfg = self.build_config()
        if cfg is None:
            return False
        self.selected_config = cfg
        return True
