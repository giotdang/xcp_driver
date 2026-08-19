"""Panel đo lường real-time — MEASUREMENT tree từ A2L, pyqtgraph scope."""

from __future__ import annotations

import logging
import struct
import time
from collections import deque
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    PrimaryPushButton,
    PushButton,
)

from ..session.api import A2LDatabase, DaqList, DaqSignal, SamplePoint

__all__ = ["MeasurementView"]

# Bảng màu cycling cho các đường signal
_COLORS = [
    "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4",
    "#DDA0DD", "#F9CA24", "#F0932B", "#6C5CE7",
]

_DTYPE_FMT: dict[str, str] = {
    "UBYTE": "B", "SBYTE": "b",
    "UWORD": "H", "SWORD": "h",
    "ULONG": "I", "SLONG": "i",
    "FLOAT32_IEEE": "f", "FLOAT64_IEEE": "d",
}
_ENDIAN: dict[str, str] = {"little": "<", "big": ">"}

# Số điểm tối đa mỗi signal trong bộ đệm (~30s tại 100 Hz)
_MAX_POINTS = 3000

# Index cột trong QTreeWidget
COL_NAME  = 0
COL_DTYPE = 1
COL_ADDR  = 2


def _raw_to_float(data: bytes, datatype: str, byte_order: str) -> float | None:
    """Giải mã bytes thô → float.  Trả None nếu datatype không biết / frame ngắn."""
    fmt = _DTYPE_FMT.get(datatype)
    if fmt is None:
        return None
    endian = _ENDIAN.get(byte_order, "<")
    size = struct.calcsize(fmt)
    if len(data) < size:
        return None
    return float(struct.unpack_from(endian + fmt, data)[0])


class MeasurementView(QWidget):
    """Panel đo lường — checkbox tree (trái) + pyqtgraph scope (phải).

    Signals phát cho MainWindow:
        a2l_load_requested(str) — user bấm "Nạp A2L…"
        daq_start_requested(object) — list[DaqList], user bấm "Bắt đầu đo"
        daq_stop_requested() — user bấm "Dừng"
    """

    a2l_load_requested = Signal(str)
    daq_start_requested = Signal(object)   # list[DaqList]
    daq_stop_requested  = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("measurementView")

        self._db: A2LDatabase = A2LDatabase()
        self._byte_order = "little"
        self._daq_running = False

        # Plot state — được thiết lập khi _setup_curves() chạy
        self._curves: dict[str, pg.PlotDataItem] = {}
        # Fix 1: Tách thành hai deque float riêng thay vì deque[tuple] —
        # tránh unpack tuple mỗi lần, np.fromiter() nhanh hơn list comprehension.
        self._xs: dict[str, deque[float]] = {}
        self._ys: dict[str, deque[float]] = {}
        # Fix 3: Theo dõi số điểm đã vẽ — skip setData() khi không có gì mới.
        self._drawn_len: dict[str, int] = {}
        self._legend: pg.LegendItem | None = None

        # Mốc thời gian: ns từ ECU (t0_ns) hoặc wall clock (start_mono)
        self._t0_ns: int = 0
        self._start_mono: float = 0.0

        self._build_ui()

    # ── dựng giao diện ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # toolbar
        self.load_btn = PushButton("Nạp A2L…", self)
        self.load_btn.clicked.connect(self._on_load_click)

        self.start_btn = PrimaryPushButton("Bắt đầu đo", self)
        self.start_btn.clicked.connect(self._on_start)

        self.stop_btn = PushButton("Dừng", self)
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)

        self.count_label = BodyLabel("Chưa nạp A2L.", self)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.load_btn)
        toolbar.addWidget(self.start_btn)
        toolbar.addWidget(self.stop_btn)
        toolbar.addWidget(self.count_label)
        toolbar.addStretch(1)

        # cây signal (trái)
        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Signal", "Kiểu", "Địa chỉ"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(COL_NAME,  QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_DTYPE, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_ADDR,  QHeaderView.ResizeToContents)

        # đồ thị (phải)
        # Fix 2: OpenGL offload render sang GPU — nhanh hơn software QPainter.
        # Graceful fallback nếu PyOpenGL chưa cài (log warning, không crash).
        try:
            import OpenGL  # noqa: F401
            pg.setConfigOptions(antialias=True, useOpenGL=True)
        except ImportError:
            log.warning(
                "PyOpenGL chưa cài — scope dùng software rendering (chậm hơn). "
                "Cài bằng: pip install PyOpenGL"
            )
            pg.setConfigOptions(antialias=False, useOpenGL=False)
        self._plot = pg.PlotWidget(background=None)
        self._plot.setLabel("left",   "Giá trị")
        self._plot.setLabel("bottom", "Thời gian (s)")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._legend = self._plot.addLegend(offset=(10, 10))

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(self.tree)
        splitter.addWidget(self._plot)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 800])

        self.status_label = CaptionLabel("", self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(toolbar)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.status_label)

    # ── API công khai (gọi từ MainWindow, UI thread) ─────────────────────────

    def set_database(self, db: A2LDatabase) -> None:
        """Điền tree từ A2LDatabase mới nạp — xoá mọi state cũ."""
        self._db = db
        self.tree.clear()
        for name, meas in sorted(db.measurements.items()):
            item = QTreeWidgetItem()
            item.setData(COL_NAME, Qt.UserRole, name)
            item.setText(COL_NAME, name)
            item.setCheckState(COL_NAME, Qt.Unchecked)
            item.setText(COL_DTYPE, meas.datatype)
            item.setText(COL_ADDR, f"0x{meas.address:08X}")
            item.setToolTip(COL_NAME, meas.description)
            self.tree.addTopLevelItem(item)
        n = len(db.measurements)
        self.count_label.setText(f"{n} MEASUREMENT")
        self.status_label.setText(
            "Chọn signals (tick ô vuông) rồi bấm 'Bắt đầu đo'."
            if n > 0 else "File A2L không có MEASUREMENT nào."
        )

    def set_byte_order(self, byte_order: str) -> None:
        self._byte_order = byte_order

    def on_daq_started(self) -> None:
        """Gọi từ MainWindow sau khi start_daq() thành công."""
        self._daq_running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("Đang đo…")
        self._t0_ns = 0
        self._start_mono = time.perf_counter()

    def on_daq_stopped(self) -> None:
        """Gọi từ MainWindow sau khi stop_daq() thành công."""
        self._daq_running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Đã dừng.")

    def on_samples(self, samples: list[SamplePoint]) -> None:
        """Gọi từ timer 40ms trong MainWindow — thêm điểm vào scope."""
        if not samples or not self._curves:
            return

        # Bước 1: nạp điểm mới vào buffer
        for sp in samples:
            xs_buf = self._xs.get(sp.name)
            ys_buf = self._ys.get(sp.name)
            curve  = self._curves.get(sp.name)
            if xs_buf is None or curve is None:
                continue

            val = _raw_to_float(sp.value_raw, sp.datatype, self._byte_order)
            if val is None:
                continue

            if sp.timestamp_ns > 0:
                if self._t0_ns == 0:
                    self._t0_ns = sp.timestamp_ns
                t_s = (sp.timestamp_ns - self._t0_ns) * 1e-9
            else:
                t_s = time.perf_counter() - self._start_mono

            xs_buf.append(t_s)
            ys_buf.append(val)  # type: ignore[union-attr]

        # Bước 2: vẽ lại những curve có điểm mới
        # Fix 1: np.fromiter() + Fix 3: skip khi độ dài không đổi
        for name, curve in self._curves.items():
            xs_buf = self._xs[name]
            n = len(xs_buf)
            if n == 0 or n == self._drawn_len.get(name, 0):
                continue   # Fix 3: không có điểm mới, bỏ qua
            # Fix 1: NumPy array — pyqtgraph nhận thẳng, không convert thêm
            xs = np.fromiter(xs_buf, dtype=np.float64, count=n)
            ys = np.fromiter(self._ys[name], dtype=np.float64, count=n)
            curve.setData(x=xs, y=ys)
            self._drawn_len[name] = n

    def set_busy(self, busy: bool) -> None:
        """MainWindow gọi khi bắt đầu / kết thúc một tác vụ nền."""
        # Chỉ ảnh hưởng nút Start (Stop không cần disable khi bận)
        self.start_btn.setEnabled(not busy and not self._daq_running)

    # ── hành động người dùng ─────────────────────────────────────────────────

    def _on_load_click(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file A2L", "", "A2L files (*.a2l);;All files (*)"
        )
        if path:
            self.a2l_load_requested.emit(path)

    def _on_start(self) -> None:
        lists = self._build_daq_lists()
        if not lists:
            self.status_label.setText(
                "Tick ít nhất một ô vuông trong danh sách signal trước."
            )
            return
        self._setup_curves(lists)
        self.daq_start_requested.emit(lists)

    def _on_stop(self) -> None:
        self.daq_stop_requested.emit()

    # ── nội bộ ───────────────────────────────────────────────────────────────

    def _checked_names(self) -> list[str]:
        names: list[str] = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.checkState(COL_NAME) == Qt.Checked:
                name = item.data(COL_NAME, Qt.UserRole)
                if name:
                    names.append(name)
        return names

    def _build_daq_lists(self) -> list[DaqList]:
        checked = self._checked_names()
        if not checked:
            return []
        signals: list[DaqSignal] = []
        for name in checked:
            meas = self._db.measurements.get(name)
            if meas is None:
                continue
            signals.append(DaqSignal(
                name=meas.name,
                address=meas.address,
                ext=0,
                size=meas.byte_size,
                datatype=meas.datatype,
            ))
        if not signals:
            return []
        return [DaqList(signals=signals, event=0, timestamp=True)]

    def _setup_curves(self, lists: list[Any]) -> None:
        """Xoá curves cũ và khởi tạo curve mới cho mỗi signal được chọn."""
        # Xoá curves cũ khỏi plot
        for curve in self._curves.values():
            self._plot.removeItem(curve)
        self._curves.clear()
        self._xs.clear()
        self._ys.clear()
        self._drawn_len.clear()
        self._t0_ns = 0

        if self._legend is not None:
            self._legend.clear()

        color_idx = 0
        for dl in lists:
            for sig in dl.signals:
                color = _COLORS[color_idx % len(_COLORS)]
                color_idx += 1
                pen = pg.mkPen(color=color, width=1.5)
                curve = self._plot.plot([], [], name=sig.name, pen=pen)
                self._curves[sig.name] = curve
                self._xs[sig.name] = deque(maxlen=_MAX_POINTS)
                self._ys[sig.name] = deque(maxlen=_MAX_POINTS)
