"""CAN device selection dialog + bus parameter configuration.

Two things that must not be silently dropped:

  * Devices with `available=False` are still shown with a `hint` indicating
    which package to install. Silent omission is the most common UX failure
    for tools of this type.
  * `list_devices()` is a BLOCKING call → runs on a worker; the dialog shows
    a spinner while waiting.
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

# Backends known to support CAN FD (python-can interface names)
_FD_CAPABLE_BACKENDS: frozenset[str] = frozenset({
    "pcan", "vector", "kvaser", "ixxat", "socketcan", "virtual",
})

# Default values for input fields come directly from the contract, not hardcoded.
_BUS_DEFAULTS = BusConfig(backend="", channel="")


class DeviceDialog(MessageBoxBase):
    """Returns a `BusConfig` via `selected_config` after the user clicks Connect.

    `initial` is used to pre-fill fields — typically loaded via
    `session.load_config()` in `MainWindow`. The dialog does not read or write
    any config file; session persistence is the responsibility of `Session`
    (see `session/api.py`), not the UI layer.
    """

    detect_requested = Signal()

    def __init__(
        self, parent: QWidget | None = None, initial: BusConfig | None = None
    ) -> None:
        super().__init__(parent)
        self.selected_config: BusConfig | None = None
        self._devices: list[DeviceInfo] = []
        self._initial = initial or _BUS_DEFAULTS

        self.titleLabel = SubtitleLabel("Select CAN Interface", self)

        self.list = ListWidget(self)
        self.list.setMinimumHeight(200)
        self.list.currentRowChanged.connect(self._on_row_changed)

        self.spinner = IndeterminateProgressRing(self)
        self.spinner.setFixedSize(24, 24)
        self.spinner.hide()

        self.detect_btn = PushButton("Scan Devices", self)
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

        # ── Arbitration bitrate ──────────────────────────────────────────────
        self.bitrate_combo = ComboBox(self)
        for b in (125_000, 250_000, 500_000, 800_000, 1_000_000):
            self.bitrate_combo.addItem(f"{b // 1000} kbps", userData=b)
        self.bitrate_combo.setCurrentIndex(2)   # 500 kbps default

        # ── CAN ID fields ────────────────────────────────────────────────────
        self.cro_edit = LineEdit(self)
        self.cro_edit.setFont(mono)
        self.dto_edit = LineEdit(self)
        self.dto_edit.setFont(mono)

        # ── Flags ────────────────────────────────────────────────────────────
        self.ext_cb = CheckBox("29-bit CAN ID", self)
        self.pad_cb = CheckBox("Pad short frames to 8 bytes", self)
        self.pad_cb.setToolTip(
            "Pad all CTO frames to at least 8 bytes.\n"
            "Many AUTOSAR XCP stacks strictly require this even on CAN FD."
        )
        self.pad_cb.setChecked(True)

        # ── Timeout ──────────────────────────────────────────────────────────
        self.t1_spin = SpinBox(self)
        self.t1_spin.setRange(100, 10_000)
        self.t1_spin.setSingleStep(100)
        self.t1_spin.setValue(1000)
        self.t1_spin.setSuffix(" ms")

        # ── CAN FD ───────────────────────────────────────────────────────────
        self.fd_cb = CheckBox("CAN FD", self)
        self.fd_cb.setToolTip(
            "Enable CAN Flexible Data-Rate (ISO 11898-7).\n"
            "MAX_DTO can be up to 64 bytes; requires a CAN FD-capable interface."
        )
        self.fd_cb.stateChanged.connect(self._on_fd_changed)

        self.data_bitrate_combo = ComboBox(self)
        for b in (1_000_000, 2_000_000, 4_000_000, 5_000_000, 8_000_000):
            self.data_bitrate_combo.addItem(f"{b // 1_000_000} Mbps", userData=b)
        self.data_bitrate_combo.setCurrentIndex(1)  # 2 Mbps default
        self.data_bitrate_combo.setEnabled(False)

        self._fd_label = BodyLabel("Data Bitrate:", self)
        self._fd_label.setEnabled(False)

        grid = QGridLayout()
        grid.addWidget(BodyLabel("Arbitration Bitrate:", self), 0, 0)
        grid.addWidget(self.bitrate_combo, 0, 1)
        grid.addWidget(BodyLabel("CRO (host→ECU):", self), 0, 2)
        grid.addWidget(self.cro_edit, 0, 3)
        grid.addWidget(BodyLabel("DTO (ECU→host):", self), 0, 4)
        grid.addWidget(self.dto_edit, 0, 5)
        grid.addWidget(BodyLabel("Response Timeout T1:", self), 1, 0)
        grid.addWidget(self.t1_spin, 1, 1)
        grid.addWidget(self.ext_cb, 1, 2, 1, 2)
        grid.addWidget(self.pad_cb, 1, 4, 1, 2)
        grid.addWidget(self.fd_cb, 2, 0, 1, 2)
        grid.addWidget(self._fd_label, 2, 2)
        grid.addWidget(self.data_bitrate_combo, 2, 3)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addLayout(top_row)
        self.viewLayout.addWidget(self.list)
        self.viewLayout.addWidget(self.hint_label)
        self.viewLayout.addWidget(StrongBodyLabel("Bus Parameters", self))
        self.viewLayout.addLayout(grid)
        self.viewLayout.addWidget(CaptionLabel(
            "CRO and DTO typically share a single CAN ID for responses and DAQ data — "
            "the tool classifies frames automatically based on byte 0.", self))

        self.yesButton.setText("Connect")
        self.cancelButton.setText("Close")
        self.yesButton.setEnabled(False)
        self.widget.setMinimumWidth(760)

        self._apply_initial_config()

    # ── device list population ─────────────────────────────────────────────

    def set_busy(self, busy: bool) -> None:
        self.spinner.setVisible(busy)
        self.detect_btn.setEnabled(not busy)
        if busy:
            self.status_label.setText("Scanning interfaces…")

    def set_devices(self, devices: list[DeviceInfo]) -> None:
        self._devices = devices
        self.list.clear()
        select_row = -1
        for i, d in enumerate(devices):
            mark = "" if d.available else "  (unavailable)"
            item = QListWidgetItem(f"{d.display_name}   ·   {d.backend}:{d.channel}{mark}")
            if not d.available:
                item.setForeground(Qt.gray)
            self.list.addItem(item)
            if d.backend == self._initial.backend and d.channel == self._initial.channel:
                select_row = i
        available_count = sum(1 for d in devices if d.available)
        self.status_label.setText(
            f"{available_count}/{len(devices)} interface(s) available"
        )
        if select_row < 0:
            select_row = next((i for i, d in enumerate(devices) if d.available), -1)
        if select_row >= 0:
            self.list.setCurrentRow(select_row)

    def set_error(self, message: str) -> None:
        self.status_label.setText(message)

    # ── internal helpers ───────────────────────────────────────────────────

    def _on_detect_clicked(self) -> None:
        self.detect_requested.emit()

    def _on_row_changed(self, row: int) -> None:
        if not 0 <= row < len(self._devices):
            self.yesButton.setEnabled(False)
            self.hint_label.setText("")
            self._update_fd_availability(backend=None)
            return
        d = self._devices[row]
        self.yesButton.setEnabled(d.available)
        if d.available:
            self.hint_label.setText(
                f"Serial: {d.serial}" if d.serial else "Interface is ready."
            )
        else:
            self.hint_label.setText(
                d.hint or "This interface is currently unavailable (reason unknown)."
            )
        self._update_fd_availability(backend=d.backend)

    def _update_fd_availability(self, backend: str | None) -> None:
        """Grayout CAN FD checkbox when the selected backend does not support FD."""
        fd_capable = backend is not None and backend.lower() in _FD_CAPABLE_BACKENDS
        self.fd_cb.setEnabled(fd_capable)
        if not fd_capable:
            self.fd_cb.setChecked(False)
            self.fd_cb.setToolTip(
                "CAN FD is not supported by this backend.\n"
                "Use PCAN, Vector, Kvaser, socketcan, or virtual for CAN FD."
            )
        else:
            self.fd_cb.setToolTip(
                "Enable CAN Flexible Data-Rate (ISO 11898-7).\n"
                "MAX_DTO can be up to 64 bytes; requires a CAN FD-capable interface."
            )

    def _on_fd_changed(self, state: int) -> None:
        enabled = bool(state)
        self.data_bitrate_combo.setEnabled(enabled)
        self._fd_label.setEnabled(enabled)

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
        # CAN FD fields — only if BusConfig has these attrs (added in Phase 2)
        is_fd = getattr(c, "is_fd", False)
        data_bitrate = getattr(c, "data_bitrate", 2_000_000)
        self.fd_cb.setChecked(is_fd)
        idx2 = self.data_bitrate_combo.findData(data_bitrate)
        if idx2 >= 0:
            self.data_bitrate_combo.setCurrentIndex(idx2)

    def build_config(self) -> BusConfig | None:
        row = self.list.currentRow()
        if not 0 <= row < len(self._devices):
            return None
        d = self._devices[row]
        try:
            cro = int(self.cro_edit.text().strip().lower().removeprefix("0x"), 16)
            dto = int(self.dto_edit.text().strip().lower().removeprefix("0x"), 16)
        except ValueError:
            self.status_label.setText("CAN ID must be a hex number, e.g. 7E0.")
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
            is_fd=self.fd_cb.isChecked(),
            data_bitrate=self.data_bitrate_combo.currentData(),
        )

    def validate(self) -> bool:  # MessageBoxBase calls this before accept()
        cfg = self.build_config()
        if cfg is None:
            return False
        self.selected_config = cfg
        return True
