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
    SwitchButton,
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

# Tên thân thiện cho kiểu dữ liệu A2L → kiểu C quen thuộc
_FRIENDLY_DTYPE: dict[str, str] = {
    "UBYTE": "UINT8", "SBYTE": "INT8",
    "UWORD": "UINT16", "SWORD": "INT16",
    "ULONG": "UINT32", "SLONG": "INT32",
    "FLOAT32_IEEE": "FLOAT32", "FLOAT64_IEEE": "FLOAT64",
}

# Index cột trong QTreeWidget
COL_NAME  = 0
COL_DTYPE = 1
COL_ADDR  = 2
COL_VALUE = 3



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


def _group_by_prefix(names: list[str]) -> list[tuple[str | None, list[str]]]:
    """Gom nhóm các tên theo struct prefix (dấu '.' hoặc tiền tố '_' nếu có >= 2 biến).

    Trả về danh sách (group_name, [full_name1, full_name2, ...]):
    - Nếu là struct: ("speedPidTelemetry", ["speedPidTelemetry_error", ...])
    - Nếu là biến đơn/mảng: (None, ["engineRpm"])
    """
    prefixes: dict[str, list[str]] = {}
    for name in names:
        if "." in name:
            p = name.split(".", 1)[0]
            prefixes.setdefault(p, []).append(name)
        elif "_" in name:
            p = name.rsplit("_", 1)[0]
            prefixes.setdefault(p, []).append(name)
        else:
            prefixes.setdefault("", []).append(name)

    valid_groups = {p: member_list for p, member_list in prefixes.items() if p and len(member_list) >= 2}

    handled: set[str] = set()
    result: list[tuple[str | None, list[str]]] = []
    for name in names:
        if name in handled:
            continue
        found = None
        for p, members in valid_groups.items():
            if name in members:
                found = (p, members)
                break
        if found is not None:
            p, members = found
            result.append((p, members))
            handled.update(members)
        else:
            result.append((None, [name]))
            handled.add(name)
    return result



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

        # Ánh xạ tên signal (vd: "speed", "torqueSamples[0]") -> QTreeWidgetItem
        self._tree_items: dict[str, QTreeWidgetItem] = {}

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
        self.load_btn = PushButton("Load A2L…", self)
        self.load_btn.clicked.connect(self._on_load_click)

        self.start_btn = PrimaryPushButton("Start Acquisition", self)
        self.start_btn.clicked.connect(self._on_start)

        self.stop_btn = PushButton("Stop", self)
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)

        # Switch to enable/disable scope plotting
        self.scope_switch = SwitchButton(self)
        self.scope_switch.setOnText("Scope: On")
        self.scope_switch.setOffText("Scope: Off")
        self.scope_switch.setChecked(True)
        self.scope_switch.checkedChanged.connect(self._on_scope_toggled)

        self.count_label = BodyLabel("No A2L loaded.", self)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.load_btn)
        toolbar.addWidget(self.start_btn)
        toolbar.addWidget(self.stop_btn)
        toolbar.addWidget(self.scope_switch)
        toolbar.addWidget(self.count_label)
        toolbar.addStretch(1)

        # signal tree (left) — parameter table & live values
        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Signal", "Type", "Address", "Value"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(COL_NAME,  QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_DTYPE, QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_ADDR,  QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_VALUE, QHeaderView.Stretch)
        
        self.tree.setColumnWidth(COL_NAME, 200)
        self.tree.setColumnWidth(COL_DTYPE, 100)
        self.tree.setColumnWidth(COL_ADDR, 90)

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
        self._plot.setLabel("left",   "Value")
        self._plot.setLabel("bottom", "Time (s)")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._legend = self._plot.addLegend(offset=(10, 10))

        self._splitter = QSplitter(Qt.Horizontal, self)
        self._splitter.addWidget(self.tree)
        self._splitter.addWidget(self._plot)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([320, 720])

        self.status_label = CaptionLabel("", self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(toolbar)
        layout.addWidget(self._splitter, 1)
        layout.addWidget(self.status_label)

    # ── API công khai (gọi từ MainWindow, UI thread) ─────────────────────────

    def set_database(self, db: A2LDatabase) -> None:
        """Điền tree từ A2LDatabase mới nạp — gom nhóm struct và array phân cấp."""
        self._db = db
        self.tree.clear()
        self._tree_items.clear()

        groups = _group_by_prefix(sorted(db.measurements.keys()))
        for group_name, members in groups:
            if group_name is not None and len(members) >= 2:
                # ── STRUCT / GROUP ──────────────────────────────────────────
                struct_meas = [db.measurements[m] for m in members]
                min_addr = min(m.address for m in struct_meas)

                parent = QTreeWidgetItem()
                # Lưu danh sách tất cả các signal con vào parent data
                parent.setData(COL_NAME, Qt.UserRole, members)
                parent.setText(COL_NAME, group_name)
                parent.setCheckState(COL_NAME, Qt.Unchecked)
                parent.setText(COL_DTYPE, f"STRUCT ({len(members)})")
                parent.setText(COL_ADDR, f"0x{min_addr:08X}")
                parent.setText(COL_VALUE, "-")
                self.tree.addTopLevelItem(parent)

                # Các trường con không có Checkbox
                for m in struct_meas:
                    child = QTreeWidgetItem()
                    child.setData(COL_NAME, Qt.UserRole, m.name)
                    disp_name = m.name[len(group_name):].lstrip("._") or m.name
                    child.setText(COL_NAME, disp_name)
                    child.setText(COL_DTYPE, _FRIENDLY_DTYPE.get(m.datatype, m.datatype))
                    child.setText(COL_ADDR, f"0x{m.address:08X}")
                    child.setText(COL_VALUE, "-")
                    child.setToolTip(COL_NAME, m.description)
                    parent.addChild(child)
                    self._tree_items[m.name] = child
                parent.setExpanded(True)
            else:
                # ── SCALAR hoặc ARRAY ───────────────────────────────────────
                name = members[0]
                meas = db.measurements[name]
                item = QTreeWidgetItem()
                item.setData(COL_NAME, Qt.UserRole, name)
                item.setText(COL_NAME, name)
                item.setCheckState(COL_NAME, Qt.Unchecked)
                friendly = _FRIENDLY_DTYPE.get(meas.datatype, meas.datatype)
                item.setText(
                    COL_DTYPE,
                    friendly if meas.array_size == 1 else f"{friendly}[{meas.array_size}]"
                )
                item.setText(COL_ADDR, f"0x{meas.address:08X}")
                item.setText(COL_VALUE, "-")
                item.setToolTip(COL_NAME, meas.description)
                self.tree.addTopLevelItem(item)

                if meas.array_size == 1:
                    self._tree_items[name] = item
                else:
                    elem_size = meas.byte_size // meas.array_size
                    for i in range(meas.array_size):
                        child_name = f"{meas.name}[{i}]"
                        child = QTreeWidgetItem()
                        child.setData(COL_NAME, Qt.UserRole, child_name)
                        child.setText(COL_NAME, f"[{i}]")
                        child.setText(COL_DTYPE, _FRIENDLY_DTYPE.get(meas.datatype, meas.datatype))
                        child.setText(COL_ADDR, f"0x{(meas.address + i * elem_size):08X}")
                        child.setText(COL_VALUE, "-")
                        item.addChild(child)
                        self._tree_items[child_name] = child
                    item.setExpanded(True)

        n = len(db.measurements)
        self.count_label.setText(f"{n} MEASUREMENT(s)")
        self.status_label.setText(
            "Select signals (check boxes) then click 'Start Acquisition'."
            if n > 0 else "A2L file contains no MEASUREMENTs."
        )


    def set_byte_order(self, byte_order: str) -> None:
        self._byte_order = byte_order

    def on_daq_started(self) -> None:
        """Called from MainWindow after start_daq() succeeds."""
        self._daq_running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("Acquiring DAQ data…")
        self._t0_ns = 0
        self._start_mono = time.perf_counter()

    def on_daq_stopped(self) -> None:
        """Called from MainWindow after stop_daq() succeeds."""
        self._daq_running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Stopped.")

    def on_samples(self, samples: list[SamplePoint]) -> None:
        """Gọi từ timer 40ms trong MainWindow — cập nhật live value & scope."""
        if not samples:
            return

        # Bước 1: Cập nhật giá trị hiển thị thời gian thực (Live Value) trên Tree
        # Chỉ cập nhật các item lá (con của array hoặc scalar) — dòng cha giữ nguyên "-"
        for sp in samples:
            val = _raw_to_float(sp.value_raw, sp.datatype, self._byte_order)
            if val is not None:
                tree_item = self._tree_items.get(sp.name)
                if tree_item is not None:
                    tree_item.setText(COL_VALUE, f"{val:.4g}")

        # Bước 2: Nếu tắt chế độ vẽ Scope hoặc chưa cấu hình curves -> bỏ qua phần vẽ đồ thị
        if not self.scope_switch.isChecked() or not self._curves:
            return

        # Bước 3: Nạp điểm mới vào buffer đồ thị
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

        # Bước 4: Vẽ lại những curve có điểm mới
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

    def _on_scope_toggled(self, checked: bool) -> None:
        """Ẩn/hiện scope plot khi gạt switch."""
        self._plot.setVisible(checked)
        if checked:
            self._splitter.setSizes([320, 720])
        else:
            self._splitter.setSizes([1000, 0])


    def set_busy(self, busy: bool) -> None:
        """MainWindow gọi khi bắt đầu / kết thúc một tác vụ nền."""
        # Chỉ ảnh hưởng nút Start (Stop không cần disable khi bận)
        self.start_btn.setEnabled(not busy and not self._daq_running)

    # ── hành động người dùng ─────────────────────────────────────────────────

    def _on_load_click(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select A2L File", "", "A2L files (*.a2l);;All files (*)"
        )
        if path:
            self.a2l_load_requested.emit(path)

    def _on_start(self) -> None:
        lists = self._build_daq_lists()
        if not lists:
            self.status_label.setText(
                "Select at least one signal before starting acquisition."
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
                data = item.data(COL_NAME, Qt.UserRole)
                if isinstance(data, list):
                    names.extend(data)
                elif isinstance(data, str) and data:
                    names.append(data)
        return names


    def _build_daq_lists(self) -> list[DaqList]:
        """Dựng danh sách DaqList từ signals được tick.

        Array signal (MATRIX_DIM) tự động tách thành N DaqSignal riêng:
          torqueSamples[4] (FLOAT32_IEEE, 4B) →
            torqueSamples[0] @ addr+0
            torqueSamples[1] @ addr+4
            torqueSamples[2] @ addr+8
            torqueSamples[3] @ addr+12
        Scalar signal (matrix_dim rỗng) giữ nguyên.
        """
        checked = self._checked_names()
        if not checked:
            return []
        signals: list[DaqSignal] = []
        for name in checked:
            meas = self._db.measurements.get(name)
            if meas is None:
                continue
            n = meas.array_size       # 1 nếu scalar, >1 nếu array
            elem_size = meas.byte_size // n   # kích thước một phần tử (bytes)
            if n == 1:
                # Scalar — không thay đổi gì
                signals.append(DaqSignal(
                    name=meas.name,
                    address=meas.address,
                    ext=0,
                    size=elem_size,
                    datatype=meas.datatype,
                ))
            else:
                # Array — tách thành N phần tử riêng, tên = "name[i]"
                for i in range(n):
                    signals.append(DaqSignal(
                        name=f"{meas.name}[{i}]",
                        address=meas.address + i * elem_size,
                        ext=0,
                        size=elem_size,
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
