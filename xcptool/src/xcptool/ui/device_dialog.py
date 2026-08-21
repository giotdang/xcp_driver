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
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
    QListWidgetItem,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    IndeterminateProgressRing,
    LineEdit,
    ListWidget,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
)

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
        # Row 0
        grid.addWidget(BodyLabel("Arbitration Bitrate:", self), 0, 0)
        grid.addWidget(self.bitrate_combo, 0, 1)
        grid.addWidget(BodyLabel("CRO (host→ECU):", self), 0, 2)
        grid.addWidget(self.cro_edit, 0, 3)
        grid.addWidget(BodyLabel("DTO (ECU→host):", self), 0, 4)
        grid.addWidget(self.dto_edit, 0, 5)

        # Row 1
        grid.addWidget(self._fd_label, 1, 0)
        grid.addWidget(self.data_bitrate_combo, 1, 1)
        grid.addWidget(BodyLabel("Response Timeout T1:", self), 1, 2)
        grid.addWidget(self.t1_spin, 1, 3)
        grid.addWidget(self.ext_cb, 1, 4, 1, 2)
        
        # Row 2
        self.adv_timing_btn = PushButton("Advanced Timing...", self)
        self.adv_timing_btn.clicked.connect(self._on_adv_timing)
        self.adv_timing_btn.setToolTip("Configure BRP, TSEG1, TSEG2, SJW (overrides Bitrate)")
        grid.addWidget(self.adv_timing_btn, 2, 1)
        grid.addWidget(self.fd_cb, 2, 2, 1, 2)
        grid.addWidget(self.pad_cb, 2, 4, 1, 2)

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
        self.widget.setMinimumWidth(820)

        self._custom_bit_timing = False
        self._f_clock = 80_000_000
        self._brp = 1
        self._tseg1 = 14
        self._tseg2 = 2
        self._sjw = 1
        self._dbrp = 1
        self._dtseg1 = 14
        self._dtseg2 = 2
        self._dsjw = 1

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
            if "·" in d.display_name:
                item_text = f"{d.display_name}{mark}"
            else:
                item_text = f"{d.display_name}   ·   {d.backend}:{d.channel}{mark}"
            item = QListWidgetItem(item_text)
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

    def _sync_bitrate_controls(self) -> None:
        """Đồng bộ trạng thái enable/disable của các control bitrate từ state duy nhất."""
        is_fd = self.fd_cb.isChecked()
        custom_timing = self._custom_bit_timing

        self.bitrate_combo.setEnabled(not custom_timing)
        self.data_bitrate_combo.setEnabled(is_fd and not custom_timing)
        self._fd_label.setEnabled(is_fd)

    def _on_fd_changed(self, state: int) -> None:
        self._sync_bitrate_controls()

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
            
        self._custom_bit_timing = getattr(c, "custom_bit_timing", False)
        self._f_clock = getattr(c, "f_clock", 80_000_000)
        self._brp = getattr(c, "brp", 1)
        self._tseg1 = getattr(c, "tseg1", 14)
        self._tseg2 = getattr(c, "tseg2", 2)
        self._sjw = getattr(c, "sjw", 1)
        self._dbrp = getattr(c, "dbrp", 1)
        self._dtseg1 = getattr(c, "dtseg1", 14)
        self._dtseg2 = getattr(c, "dtseg2", 2)
        self._dsjw = getattr(c, "dsjw", 1)
        self._sync_bitrate_controls()

    def _on_adv_timing(self) -> None:
        dlg = BitTimingDialog(
            self._custom_bit_timing, self.fd_cb.isChecked(), 
            self._f_clock,
            self._brp, self._tseg1, self._tseg2, self._sjw, 
            self._dbrp, self._dtseg1, self._dtseg2, self._dsjw, 
            self
        )
        if dlg.exec():
            self._custom_bit_timing = dlg.enable_cb.isChecked()
            self._f_clock = dlg.f_clock_spin.value() * 1_000_000
            self._brp = dlg.brp_spin.value()
            self._tseg1 = dlg.tseg1_spin.value()
            self._tseg2 = dlg.tseg2_spin.value()
            self._sjw = dlg.sjw_spin.value()
            self._dbrp = dlg.dbrp_spin.value()
            self._dtseg1 = dlg.dtseg1_spin.value()
            self._dtseg2 = dlg.dtseg2_spin.value()
            self._dsjw = dlg.dsjw_spin.value()
            self._sync_bitrate_controls()

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
            custom_bit_timing=self._custom_bit_timing,
            f_clock=self._f_clock,
            brp=self._brp,
            tseg1=self._tseg1,
            tseg2=self._tseg2,
            sjw=self._sjw,
            dbrp=self._dbrp,
            dtseg1=self._dtseg1,
            dtseg2=self._dtseg2,
            dsjw=self._dsjw,
        )

    def validate(self) -> bool:  # MessageBoxBase calls this before accept()
        cfg = self.build_config()
        if cfg is None:
            return False
        self.selected_config = cfg
        return True


class BitTimingDialog(MessageBoxBase):
    def __init__(self, enabled: bool, is_fd: bool, f_clock: int, brp: int, tseg1: int, tseg2: int, sjw: int, dbrp: int, dtseg1: int, dtseg2: int, dsjw: int, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("Advanced Bit Timing", self)
        
        self.enable_cb = CheckBox("Enable Custom Bit Timing", self)
        self.enable_cb.setChecked(enabled)
        self.is_fd = is_fd
        
        grid = QGridLayout()

        self.f_clock_spin = SpinBox(self)
        self.f_clock_spin.setRange(1, 1000)
        self.f_clock_spin.setValue(int(f_clock / 1_000_000))
        grid.addWidget(BodyLabel("Clock (MHz):", self), 0, 0)
        grid.addWidget(self.f_clock_spin, 0, 1)

        grid.addWidget(StrongBodyLabel("Arbitration Phase", self), 1, 0, 1, 2)
        
        self.brp_spin = SpinBox(self)
        self.brp_spin.setRange(1, 1024)
        self.brp_spin.setValue(brp)
        grid.addWidget(BodyLabel("BRP:", self), 2, 0)
        grid.addWidget(self.brp_spin, 2, 1)
        
        self.tseg1_spin = SpinBox(self)
        self.tseg1_spin.setRange(1, 256)
        self.tseg1_spin.setValue(tseg1)
        grid.addWidget(BodyLabel("TSEG1:", self), 3, 0)
        grid.addWidget(self.tseg1_spin, 3, 1)
        
        self.tseg2_spin = SpinBox(self)
        self.tseg2_spin.setRange(1, 128)
        self.tseg2_spin.setValue(tseg2)
        grid.addWidget(BodyLabel("TSEG2:", self), 4, 0)
        grid.addWidget(self.tseg2_spin, 4, 1)
        
        self.sjw_spin = SpinBox(self)
        self.sjw_spin.setRange(1, 128)
        self.sjw_spin.setValue(sjw)
        grid.addWidget(BodyLabel("SJW:", self), 5, 0)
        grid.addWidget(self.sjw_spin, 5, 1)

        # Data Phase (if FD)
        if is_fd:
            grid.addWidget(StrongBodyLabel("Data Phase (CAN FD)", self), 1, 2, 1, 2)
            
            self.dbrp_spin = SpinBox(self)
            self.dbrp_spin.setRange(1, 1024)
            self.dbrp_spin.setValue(dbrp)
            grid.addWidget(BodyLabel("DBRP:", self), 2, 2)
            grid.addWidget(self.dbrp_spin, 2, 3)
            
            self.dtseg1_spin = SpinBox(self)
            self.dtseg1_spin.setRange(1, 256)
            self.dtseg1_spin.setValue(dtseg1)
            grid.addWidget(BodyLabel("DTSEG1:", self), 3, 2)
            grid.addWidget(self.dtseg1_spin, 3, 3)
            
            self.dtseg2_spin = SpinBox(self)
            self.dtseg2_spin.setRange(1, 128)
            self.dtseg2_spin.setValue(dtseg2)
            grid.addWidget(BodyLabel("DTSEG2:", self), 4, 2)
            grid.addWidget(self.dtseg2_spin, 4, 3)
            
            self.dsjw_spin = SpinBox(self)
            self.dsjw_spin.setRange(1, 128)
            self.dsjw_spin.setValue(dsjw)
            grid.addWidget(BodyLabel("DSJW:", self), 5, 2)
            grid.addWidget(self.dsjw_spin, 5, 3)
        else:
            self.dbrp_spin = SpinBox(self); self.dbrp_spin.setValue(dbrp)
            self.dtseg1_spin = SpinBox(self); self.dtseg1_spin.setValue(dtseg1)
            self.dtseg2_spin = SpinBox(self); self.dtseg2_spin.setValue(dtseg2)
            self.dsjw_spin = SpinBox(self); self.dsjw_spin.setValue(dsjw)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.enable_cb)
        self.viewLayout.addLayout(grid)
        self.viewLayout.addWidget(CaptionLabel("Note: If enabled, these values override the default Bitrate dropdown.", self))
        
        self.yesButton.setText("Apply")
        self.cancelButton.setText("Cancel")
        self.widget.setMinimumWidth(400 if is_fd else 250)
        
        self.enable_cb.stateChanged.connect(self._on_enable_changed)
        self._on_enable_changed()

    def _on_enable_changed(self):
        is_enabled = self.enable_cb.isChecked()
        self.f_clock_spin.setEnabled(is_enabled)
        self.brp_spin.setEnabled(is_enabled)
        self.tseg1_spin.setEnabled(is_enabled)
        self.tseg2_spin.setEnabled(is_enabled)
        self.sjw_spin.setEnabled(is_enabled)
        if self.is_fd:
            self.dbrp_spin.setEnabled(is_enabled)
            self.dtseg1_spin.setEnabled(is_enabled)
            self.dtseg2_spin.setEnabled(is_enabled)
            self.dsjw_spin.setEnabled(is_enabled)
