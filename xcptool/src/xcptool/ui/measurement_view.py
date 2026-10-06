"""Panel đo lường real-time — MEASUREMENT tree từ A2L, pyqtgraph scope."""

from __future__ import annotations

import logging
import os
import struct
import time
from collections import deque
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

import pyqtgraph as pg
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SwitchButton,
)

from ..a2l.events import EventOption, allowed_events, event_catalog, event_locked
from ..a2l.types import Measurement
from ..session.api import A2LDatabase, DaqList, DaqSignal, InstanceNode, SamplePoint

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
COL_EVENT = 3
COL_VALUE = 4

# Mục "chưa chọn" ở đầu combobox event. userData=None nên `currentData()` tự
# phân biệt được "chưa gán" với "đã gán event 0" — placeholder của ComboBox
# không mang được dữ liệu nên không dùng.
_EVENT_UNSET_TEXT = "— select event —"

# A2L không khai event nào (không có /begin EVENT, cũng không có
# MAX_EVENT_CHANNEL): vẫn phải đo được, nhưng nói thẳng trên UI là tool đang
# đoán kênh 0 chứ không phải A2L nói thế. ECU nào cũng có kênh 0 nếu nó có DAQ.
_FALLBACK_EVENT = EventOption(
    number=0, label="Event 0 (no event info in A2L)", cycle_ns=0,
    max_daq_list=0, described=False,
)


class _DaqSetupError(ValueError):
    """Cấu hình đo chưa hợp lệ — thông điệp đã viết cho người dùng đọc.

    `_on_start()` bắt riêng lớp này để hiện nguyên văn lên status bar: đây là
    lỗi của cấu hình (thiếu raster, vượt MAX_DAQ), phát hiện TRƯỚC khi gửi
    lệnh nào lên bus, không phải lỗi ECU trả về."""



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


def _format_display_value(data: bytes, datatype: str, byte_order: str, radix: str = "DEC") -> str:
    """Định dạng giá trị byte thô theo hệ cơ số (DEC, HEX, BIN, ASCII)."""
    fmt = _DTYPE_FMT.get(datatype)
    if fmt is None:
        return "???"
    endian = _ENDIAN.get(byte_order, "<")
    size = struct.calcsize(fmt)
    if len(data) < size:
        return "???"
    is_float = datatype.startswith("FLOAT")

    if is_float:
        v = struct.unpack_from(endian + fmt, data, 0)[0]
        if radix == "HEX":
            int_fmt = "I" if datatype == "FLOAT32_IEEE" else "Q"
            raw_int = struct.unpack_from(endian + int_fmt, data, 0)[0]
            return f"0x{raw_int:0{size * 2}X}"
        elif radix == "BIN":
            int_fmt = "I" if datatype == "FLOAT32_IEEE" else "Q"
            raw_int = struct.unpack_from(endian + int_fmt, data, 0)[0]
            return f"0b{raw_int:0{size * 8}b}"
        elif radix == "ASCII":
            chars = [chr(b) if 32 <= b <= 126 else "." for b in data[:size]]
            return "".join(chars)
        else:
            return f"{v:.4g}"
    else:
        v = struct.unpack_from(endian + fmt, data, 0)[0]
        if radix == "HEX":
            mask = (1 << (size * 8)) - 1
            return f"0x{v & mask:X}"
        elif radix == "BIN":
            mask = (1 << (size * 8)) - 1
            return f"0b{v & mask:b}"
        elif radix == "ASCII":
            try:
                return chr(v) if 32 <= v <= 126 else "."
            except ValueError:
                return str(v)
        else:
            return str(v)


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
        self._radix = "DEC"
        self._is_expanded = True
        self._daq_running = False

        self._tree_items: dict[str, QTreeWidgetItem] = {}
        self._last_raw: dict[str, tuple[bytes, str]] = {}

        # ── Synchronous Event ───────────────────────────────────────────────
        # Nguồn sự thật DUY NHẤT cho "signal này đồng bộ theo event nào":
        # tên MEASUREMENT → số kênh event, None = chưa gán. Combobox chỉ là
        # cách hiển thị/sửa nó, `_build_daq_lists()` chỉ đọc dict này.
        self._event_of: dict[str, int | None] = {}
        self._catalog: dict[int, EventOption] = {}
        self._event_combos: dict[str, ComboBox] = {}
        # Combobox ở dòng STRUCT/ARRAY cha: gán một lúc cho mọi lá bên dưới.
        self._bulk_combos: list[tuple[ComboBox, tuple[str, ...]]] = []
        # Chặn vòng lặp signal khi code tự setCurrentIndex (bulk → lá → bulk).
        self._suppress_event_signals = False

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

        self.search_box = LineEdit(self)
        self.search_box.setPlaceholderText("Search...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search)

        self.expand_btn = PushButton("Collapse All", self)
        self.expand_btn.clicked.connect(self._on_expand_toggle)

        self.radix_combo = ComboBox(self)
        self.radix_combo.addItems(["DEC", "HEX", "BIN", "ASCII"])
        self.radix_combo.currentTextChanged.connect(self._on_radix_changed)

        self.count_label = BodyLabel("No A2L loaded.", self)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.load_btn)
        toolbar.addWidget(self.start_btn)
        toolbar.addWidget(self.stop_btn)
        toolbar.addWidget(self.scope_switch)
        toolbar.addWidget(self.search_box)
        toolbar.addWidget(self.expand_btn)
        toolbar.addWidget(self.radix_combo)
        toolbar.addWidget(self.count_label)
        toolbar.addStretch(1)

        # signal tree (left) — parameter table & live values
        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(
            ["Signal", "Type", "Address", "Synchronous Event", "Value"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(COL_NAME,  QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_DTYPE, QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_ADDR,  QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_EVENT, QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_VALUE, QHeaderView.Stretch)

        self.tree.setColumnWidth(COL_NAME, 200)
        self.tree.setColumnWidth(COL_DTYPE, 100)
        self.tree.setColumnWidth(COL_ADDR, 90)
        self.tree.setColumnWidth(COL_EVENT, 250)   # đủ cho "1 — 100 ms raster (100 ms)"

        # đồ thị (phải)
        # Mặc định vẽ bằng software. Viewport OpenGL (QOpenGLWidget) từng làm đồ thị đen
        # hoàn toàn và tràn log "QPainter: Painter not active" trên máy thật: framebuffer
        # không tạo được ("QOpenGLFramebufferObject: Framebuffer incomplete", "QOpenGLWidget:
        # Failed to create wrapper texture"), bất kể antialias. Máy nào chạy được GL ổn
        # thì bật bằng biến môi trường XCPTOOL_OPENGL=1 (cần PyOpenGL).
        use_gl = os.environ.get("XCPTOOL_OPENGL") == "1"
        if use_gl:
            try:
                import OpenGL  # noqa: F401
            except ImportError:
                log.warning("XCPTOOL_OPENGL=1 nhưng PyOpenGL chưa cài — dùng software rendering.")
                use_gl = False
        pg.setConfigOptions(antialias=use_gl, useOpenGL=use_gl)
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

    def _leaf_names(self, node: InstanceNode) -> list[str]:
        """Tên các lá MEASUREMENT (is_measurement=True) — dùng để loại các
        MEASUREMENT đã hiển thị qua INSTANCE khỏi vòng lặp phẳng bên dưới
        (`set_database`).

        Bug thật (final review, mirror-image của guard tương tự ở
        CalibrationView): trước đây hàm này trả về MỌI leaf_name bất kể
        `is_measurement`. Guard chống trùng tên trong a2l/database.py chỉ
        soát trùng tên TRONG CÙNG dict (`db.measurements` hoặc
        `db.characteristics`) — một MEASUREMENT ở đây có thể trùng tên với
        MỘT CHARACTERISTIC resolve-từ-INSTANCE mà không hề bị chặn khi parse.
        Nếu không lọc theo `is_measurement`, tên đó lọt vào `handled` chỉ vì
        trùng chữ với 1 CHARACTERISTIC, và MEASUREMENT phẳng cùng tên biến
        mất khỏi MeasurementView dù hoàn toàn hợp lệ."""
        if node.leaf_name is not None:
            return [node.leaf_name] if node.is_measurement else []
        names: list[str] = []
        for child in node.children:
            names.extend(self._leaf_names(child))
        return names

    def _build_tree_item_from_node(self, node: InstanceNode, top_level: bool) -> QTreeWidgetItem | None:
        """`top_level=True` CHỈ khi item này được add thẳng bằng
        `self.tree.addTopLevelItem(...)` — checkbox chỉ tồn tại ở đó, y hệt
        hành vi cũ (con của struct/mảng KHÔNG có checkbox riêng, xem
        `USER_MANUAL.md §6`). Không dùng cờ True/False nào khác để quyết
        checkbox — quyết định 100% bởi vị trí trong cây, không phải bởi
        node là lá hay không (một INSTANCE scalar độc lập, không thuộc
        struct nào, VẪN cần checkbox vì nó là top-level).

        MeasurementView chỉ hiển thị MEASUREMENT — một lá CHARACTERISTIC
        (`node.is_measurement is False`) thuộc phạm vi CalibrationView, không
        phải dữ liệu sai, nên bỏ qua êm (trả None), không log cảnh báo. Một
        node STRUCT/ARRAY cha mà MỌI con đều bị lọc bỏ (vd. struct toàn
        CHARACTERISTIC) cũng trả None — không hiện node rỗng (mirror-image
        của guard đã thêm cho CalibrationView ở Task 11)."""
        if node.leaf_name is not None:
            if not node.is_measurement:
                return None
            meas = self._db.measurements[node.leaf_name]
            item = QTreeWidgetItem()
            item.setData(COL_NAME, Qt.UserRole, node.leaf_name)
            item.setText(COL_NAME, node.name.rsplit(".", 1)[-1] if "." in node.name else node.name)
            if top_level:
                item.setCheckState(COL_NAME, Qt.Unchecked)
            friendly = _FRIENDLY_DTYPE.get(meas.datatype, meas.datatype)
            item.setText(
                COL_DTYPE,
                friendly if meas.array_size == 1 else f"{friendly}[{meas.array_size}]"
            )
            item.setText(COL_ADDR, f"0x{meas.address:08X}")
            item.setText(COL_VALUE, "-")
            item.setToolTip(COL_NAME, meas.description)

            if meas.array_size == 1:
                self._tree_items[node.leaf_name] = item
            else:
                # Bug thật (final review): trước fix, một MEASUREMENT array
                # (MATRIX_DIM) reach qua INSTANCE luôn dựng ĐÚNG 1 dòng scalar
                # và chỉ đăng ký self._tree_items[node.leaf_name] — không
                # dựng các dòng con [i] như nhánh phẳng bên dưới (~dòng 378)
                # vẫn làm. DAQ signal list vẫn đặt tên/địa chỉ đúng từng phần
                # tử ("tel.samples[0]"…), nhưng không có key nào trong
                # self._tree_items khớp — on_samples()'s live-value lookup
                # (self._tree_items.get(sp.name)) không bao giờ tìm thấy, cột
                # Live Value trống mãi dù DAQ đang chạy đúng. Mirror y hệt
                # nhánh phẳng: dựng dòng con [i], đăng ký theo "name[i]".
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
            return item

        # Dựng con TRƯỚC, lọc None — danh sách checkbox của dòng cha (dưới)
        # phải phản ánh ĐÚNG các con còn sống sót, không phải _leaf_names(node)
        # tính trên node gốc (sẽ lẫn cả tên CHARACTERISTIC không thuộc view này).
        child_items = [c for c in (
            self._build_tree_item_from_node(child_node, top_level=False)
            for child_node in node.children
        ) if c is not None]
        if not child_items:
            return None

        # leaves: gộp lại từ Qt.UserRole của TỪNG con còn sống sót — con lá
        # mang str (tên nó), con struct/mảng lồng mang list (đã tự lọc đệ quy)
        # -> list cuối cùng luôn chỉ chứa tên MEASUREMENT lá thật sự được add.
        leaves: list[str] = []
        for child_item in child_items:
            data = child_item.data(COL_NAME, Qt.UserRole)
            if isinstance(data, list):
                leaves.extend(data)
            elif isinstance(data, str):
                leaves.append(data)

        parent = QTreeWidgetItem()
        parent.setData(COL_NAME, Qt.UserRole, leaves)   # list -> _checked_names() extend hết
        parent.setText(COL_NAME, node.name.rsplit(".", 1)[-1] if "." in node.name else node.name)
        if top_level:
            parent.setCheckState(COL_NAME, Qt.Unchecked)
        parent.setText(COL_DTYPE,
            f"STRUCT ({len(child_items)})" if node.struct_size is not None
            else f"ARRAY[{len(child_items)}]")
        parent.setText(COL_ADDR, f"0x{node.address:08X}")
        parent.setText(COL_VALUE, "-")
        for child_item in child_items:
            parent.addChild(child_item)
        parent.setExpanded(True)
        return parent

    def set_database(self, db: A2LDatabase) -> None:
        """Điền tree từ A2LDatabase mới nạp — struct/array phân cấp dựng từ
        db.instance_trees (INSTANCE thật đã resolve), phần MEASUREMENT còn
        lại (không thuộc INSTANCE nào) hiện phẳng/array độc lập như cũ."""
        self._db = db
        self.tree.clear()
        self._tree_items.clear()
        self._reset_event_state()

        handled: set[str] = set()
        for node in db.instance_trees.values():
            item = self._build_tree_item_from_node(node, top_level=True)
            if item is not None:
                self.tree.addTopLevelItem(item)
            handled.update(self._leaf_names(node))

        for name in sorted(db.measurements):
            if name in handled:
                continue
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

        self._install_event_editors()

        n = len(db.measurements)
        self.count_label.setText(f"{n} MEASUREMENT(s)")
        unassigned = sum(1 for ev in self._event_of.values() if ev is None)
        if n == 0:
            self.status_label.setText("A2L file contains no MEASUREMENTs.")
        elif unassigned:
            self.status_label.setText(
                f"Select signals (check boxes) and pick a Synchronous Event for "
                f"{unassigned} signal(s) the A2L does not fix, then click "
                f"'Start Acquisition'."
            )
        else:
            self.status_label.setText(
                "Select signals (check boxes) then click 'Start Acquisition'.")


    # ── Synchronous Event (raster) ───────────────────────────────────────────
    #
    # Vì sao phải có cột này: `SET_DAQ_LIST_MODE` của XCP nhận ĐÚNG MỘT event
    # channel cho mỗi DAQ list, nên "signal này đo theo raster nào" là thông
    # tin BẮT BUỘC, không suy ra được từ địa chỉ hay kiểu dữ liệu. A2L nói
    # được điều đó (IF_DATA XCP / DAQ_EVENT) nhưng không bắt buộc phải nói —
    # và khi A2L cho nhiều lựa chọn thì chỉ người dùng mới biết chọn cái nào.
    # Trước đây view tự đẩy mọi signal về event 0: sai raster một cách im
    # lặng với mọi signal thuộc raster khác.

    def _reset_event_state(self) -> None:
        """Dựng lại catalog event + gán sẵn event cho từng measurement khi nạp
        A2L mới. Lựa chọn cũ KHÔNG được giữ: A2L mới có thể đánh số event khác
        hẳn, giữ lại là âm thầm đo theo raster của file trước."""
        self._catalog = {opt.number: opt for opt in event_catalog(self._db)}
        self._event_combos.clear()
        self._bulk_combos.clear()
        self._event_of = {}
        for name, meas in self._db.measurements.items():
            self._event_of[name] = self._initial_event(meas, self._options_for(name))

    def _options_for(self, name: str) -> list[EventOption]:
        """Các event hợp lệ cho một measurement, theo A2L.

        A2L không khai event nào ở bất cứ đâu → `_FALLBACK_EVENT`: tool vẫn đo
        được trên ECU chỉ có A2L tối giản, nhưng nhãn nói rõ kênh 0 là phỏng
        đoán của tool. Khác hẳn trường hợp A2L CÓ catalog nhưng DAQ_EVENT của
        signal không liệt kê event nào (A2L hỏng) — khi đó trả rỗng, không
        được lẳng lặng thay bằng kênh 0."""
        meas = self._db.measurements.get(name)
        if meas is None:
            return []
        options = allowed_events(meas, self._db, self._catalog)
        if options:
            return options
        return [] if self._catalog else [_FALLBACK_EVENT]

    def _initial_event(self, meas: Measurement, options: list[EventOption]) -> int | None:
        """Giá trị chọn sẵn: `DEFAULT_EVENT_LIST`/FIXED một phần tử (đã suy ra
        trong `Measurement.event_channel`), hoặc event duy nhất còn lại. Nhiều
        lựa chọn mà A2L không gợi ý → None, người dùng phải chọn."""
        numbers = [opt.number for opt in options]
        if meas.event_channel is not None and meas.event_channel in numbers:
            return meas.event_channel
        if len(numbers) == 1:
            return numbers[0]
        return None

    def _measurement_names_of(self, item: QTreeWidgetItem) -> list[str]:
        """Tên MEASUREMENT mà một dòng đại diện. Dòng phần tử mảng (`x[0]`)
        trả rỗng — nó không phải MEASUREMENT riêng, event của nó là event của
        cả mảng."""
        data = item.data(COL_NAME, Qt.UserRole)
        if isinstance(data, str):
            return [data] if data in self._db.measurements else []
        if isinstance(data, list):
            return [n for n in data if n in self._db.measurements]
        return []

    def _install_event_editors(self) -> None:
        """Gắn combobox vào cột Event cho mọi dòng tương ứng một MEASUREMENT;
        dòng STRUCT/ARRAY cha được combobox gán-hàng-loạt cho các lá bên dưới."""
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            for i in range(item.childCount()):
                stack.append(item.child(i))
            names = self._measurement_names_of(item)
            if not names:
                continue
            if len(names) == 1:
                self._install_signal_combo(item, names[0])
            else:
                self._install_bulk_combo(item, names)
        self._refresh_bulk_displays()

    def _install_signal_combo(self, item: QTreeWidgetItem, name: str) -> None:
        options = self._options_for(name)
        combo = ComboBox(self.tree)
        if not options:
            combo.addItem("no event allowed by A2L", userData=None)
            combo.setEnabled(False)
            combo.setToolTip(
                "The A2L declares a DAQ_EVENT for this signal but lists no event "
                "channel in it — nothing can be measured until the A2L is fixed.")
            self.tree.setItemWidget(item, COL_EVENT, combo)
            self._event_combos[name] = combo
            return

        current = self._event_of.get(name)
        if current is None:
            combo.addItem(_EVENT_UNSET_TEXT, userData=None)
        for opt in options:
            combo.addItem(opt.label, userData=opt.number)
        combo.setCurrentIndex(
            0 if current is None
            else next(i for i, opt in enumerate(options) if opt.number == current))

        meas = self._db.measurements[name]
        if event_locked(meas, self._db) or len(options) <= 1:
            # Không có gì để chọn — khoá lại thay vì giả vờ cho chọn.
            combo.setEnabled(False)
            if event_locked(meas, self._db):
                combo.setToolTip(
                    f"A2L fixes this signal to event {options[0].number} "
                    f"(FIXED_EVENT_LIST) — not selectable.")
            elif not options[0].described:
                combo.setToolTip(
                    "The A2L declares no event channels (no /begin EVENT, no "
                    "MAX_EVENT_CHANNEL). Event 0 is the tool's assumption, not "
                    "a value read from the A2L.")
        combo.currentIndexChanged.connect(
            lambda _idx, n=name, c=combo: self._on_signal_event_changed(n, c))
        self.tree.setItemWidget(item, COL_EVENT, combo)
        self._event_combos[name] = combo

    def _install_bulk_combo(self, item: QTreeWidgetItem, names: list[str]) -> None:
        """Dòng cha: chỉ chào những event mà MỌI lá bên dưới đều dùng được.

        A2L cố định raster cho một signal (FIXED_EVENT_LIST) vì ECU chỉ cập
        nhật biến đó trong ngữ cảnh raster ấy. Ép nó sang event khác thì ECU
        KHÔNG báo lỗi gì — nó vẫn lấy mẫu đều đặn, chỉ là lấy ra giá trị cũ.
        Lỗi im lặng kiểu đó phải chặn từ UI."""
        common: set[int] | None = None
        for name in names:
            numbers = {opt.number for opt in self._options_for(name)}
            common = numbers if common is None else (common & numbers)
        combo = ComboBox(self.tree)
        if not common:
            combo.addItem("members use different events", userData=None)
            combo.setEnabled(False)
            combo.setToolTip(
                "Members of this struct/array are fixed to different events by "
                "the A2L — set the Synchronous Event on each member row.")
            self.tree.setItemWidget(item, COL_EVENT, combo)
            return

        combo.addItem(_EVENT_UNSET_TEXT, userData=None)
        for number in sorted(common):
            opt = self._catalog.get(number)
            combo.addItem(opt.label if opt else f"Event {number}", userData=number)
        combo.currentIndexChanged.connect(
            lambda _idx, ns=tuple(names), c=combo: self._on_bulk_event_changed(ns, c))
        self.tree.setItemWidget(item, COL_EVENT, combo)
        self._bulk_combos.append((combo, tuple(names)))

    def _on_signal_event_changed(self, name: str, combo: ComboBox) -> None:
        if self._suppress_event_signals:
            return
        self._event_of[name] = combo.currentData()
        self._refresh_bulk_displays()

    def _on_bulk_event_changed(self, names: tuple[str, ...], combo: ComboBox) -> None:
        if self._suppress_event_signals:
            return
        number = combo.currentData()
        if number is None:          # người dùng chọn lại mục "— select event —"
            return
        self._assign_event(names, number)

    def _assign_event(self, names: tuple[str, ...] | list[str], number: int) -> None:
        """Gán event cho nhiều signal, bỏ qua signal mà A2L không cho phép."""
        changed = 0
        rejected: list[str] = []
        for name in names:
            if number not in {opt.number for opt in self._options_for(name)}:
                rejected.append(name)
                continue
            self._event_of[name] = number
            changed += 1
        self._sync_combos_from_state()
        if rejected:
            self.status_label.setText(
                f"Event {number} assigned to {changed} signal(s); not allowed by "
                f"the A2L for: {', '.join(sorted(rejected)[:5])}"
                + (" …" if len(rejected) > 5 else ""))
        else:
            self.status_label.setText(f"Event {number} assigned to {changed} signal(s).")

    def _sync_combos_from_state(self) -> None:
        """Đẩy `_event_of` ra mọi combobox. Có cờ chặn signal: setCurrentIndex
        phát currentIndexChanged, không chặn thì bulk → lá → bulk thành vòng."""
        self._suppress_event_signals = True
        try:
            for name, combo in self._event_combos.items():
                current = self._event_of.get(name)
                for i in range(combo.count()):
                    if combo.itemData(i) == current:
                        combo.setCurrentIndex(i)
                        break
        finally:
            self._suppress_event_signals = False
        self._refresh_bulk_displays()

    def _refresh_bulk_displays(self) -> None:
        """Dòng cha hiện event chung của các lá, hoặc "— select event —" khi
        các lá đang khác nhau."""
        self._suppress_event_signals = True
        try:
            for combo, names in self._bulk_combos:
                values = {self._event_of.get(n) for n in names}
                shared = values.pop() if len(values) == 1 else None
                for i in range(combo.count()):
                    if combo.itemData(i) == shared:
                        combo.setCurrentIndex(i)
                        break
        finally:
            self._suppress_event_signals = False

    def _set_event_editors_enabled(self, enabled: bool) -> None:
        """Khoá cột Event khi DAQ đang chạy: đổi raster chỉ có tác dụng ở lần
        cấu hình list kế tiếp, để sửa được giữa phiên là mời người dùng tin
        vào một thứ chưa xảy ra."""
        for name, combo in self._event_combos.items():
            if not enabled:
                combo.setEnabled(False)
                continue
            # Bật lại = khôi phục đúng trạng thái A2L quy định, không phải bật
            # hết: dòng bị FIXED_EVENT_LIST cố định vẫn phải khoá.
            meas = self._db.measurements.get(name)
            locked = meas is None or event_locked(meas, self._db) \
                or len(self._options_for(name)) <= 1
            combo.setEnabled(not locked)
        for combo, _names in self._bulk_combos:
            combo.setEnabled(enabled and combo.count() > 1)

    def _on_tree_context_menu(self, pos: QPoint) -> None:
        """"Assign Synchronous Event" cho mọi dòng đang chọn — gán từng
        combobox một cho cả struct lớn thì quá lặt nhặt."""
        if self._daq_running:
            return
        names: list[str] = []
        for item in self.tree.selectedItems():
            for name in self._measurement_names_of(item):
                if name not in names:
                    names.append(name)
        if not names:
            return

        common: set[int] | None = None
        for name in names:
            numbers = {opt.number for opt in self._options_for(name)}
            common = numbers if common is None else (common & numbers)

        menu = QMenu(self.tree)
        title = menu.addAction(f"Assign Synchronous Event — {len(names)} signal(s)")
        title.setEnabled(False)
        menu.addSeparator()
        if not common:
            none_action = menu.addAction("no event allowed for all selected signals")
            none_action.setEnabled(False)
        for number in sorted(common or ()):
            opt = self._catalog.get(number)
            action = QAction(opt.label if opt else f"Event {number}", menu)
            action.triggered.connect(
                lambda _checked=False, n=number, ns=tuple(names): self._assign_event(ns, n))
            menu.addAction(action)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def set_byte_order(self, byte_order: str) -> None:
        self._byte_order = byte_order

    @property
    def daq_running(self) -> bool:
        """MainWindow đọc cờ này để biết có cần reset UI khi mất kết nối
        (xem `_refresh_state()`) — không đụng trực tiếp `_daq_running`."""
        return self._daq_running

    def on_daq_started(self) -> None:
        """Called from MainWindow after start_daq() succeeds."""
        self._daq_running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._set_event_editors_enabled(False)
        self.status_label.setText("Acquiring DAQ data…")
        self._t0_ns = 0
        self._start_mono = time.perf_counter()

    def on_daq_stopped(self) -> None:
        """Called from MainWindow after stop_daq() succeeds."""
        self._daq_running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._set_event_editors_enabled(True)
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
                self._last_raw[sp.name] = (sp.value_raw, sp.datatype)
                tree_item = self._tree_items.get(sp.name)
                if tree_item is not None:
                    txt = _format_display_value(sp.value_raw, sp.datatype, self._byte_order, self._radix)
                    tree_item.setText(COL_VALUE, txt)

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
        try:
            lists = self._build_daq_lists()
        except _DaqSetupError as exc:
            # Cấu hình sai (thiếu raster, vượt MAX_DAQ) — nói đúng cái sai,
            # đừng để người dùng đoán, và đừng gửi gì lên bus.
            self.status_label.setText(str(exc))
            return
        if not lists:
            self.status_label.setText(
                "Select at least one signal before starting acquisition."
            )
            return
        self._setup_curves(lists)
        self.daq_start_requested.emit(lists)

    def _on_stop(self) -> None:
        self.daq_stop_requested.emit()

    def _on_search(self, text: str) -> None:
        text = text.lower()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            self._filter_tree_item(item, text)

    def _filter_tree_item(self, item: QTreeWidgetItem, text: str) -> bool:
        match = text in item.text(COL_NAME).lower()
        child_match = False
        for i in range(item.childCount()):
            if self._filter_tree_item(item.child(i), text):
                child_match = True
        
        show = match or child_match
        item.setHidden(not show)
        if show and text:
            item.setExpanded(True)
        return show

    def _on_expand_toggle(self) -> None:
        self._is_expanded = not self._is_expanded
        self.expand_btn.setText("Collapse All" if self._is_expanded else "Expand All")
        if self._is_expanded:
            self.tree.expandAll()
        else:
            self.tree.collapseAll()

    def _on_radix_changed(self, text: str) -> None:
        self._radix = text
        for name, (raw, dt) in self._last_raw.items():
            item = self._tree_items.get(name)
            if item is not None:
                item.setText(COL_VALUE, _format_display_value(raw, dt, self._byte_order, self._radix))
        self.status_label.setText(f"Radix changed to {text}.")

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
        """Dựng danh sách DaqList từ signal được tick, GOM THEO EVENT mà người
        dùng chọn ở cột "Synchronous Event" (`_event_of`).

        Một DaqList chỉ mang MỘT event vì `SET_DAQ_LIST_MODE` chỉ nhận một
        event channel cho mỗi list — signal thuộc raster khác nhau nhét chung
        một list thì ECU sample tất cả theo raster của event đó. Thứ tự list
        theo số event tăng dần, nên list vật lý thứ i trên ECU luôn ứng với
        event thứ i trong danh sách này (quan trọng khi ECU phát DTO của mỗi
        list trên một CAN ID riêng).

        Array signal (MATRIX_DIM) tách thành N DaqSignal riêng, tất cả dùng
        event của measurement mẹ (A2L khai DAQ_EVENT cho cả mảng, không cho
        từng phần tử):
          torqueSamples[4] (FLOAT32_IEEE, 4B) →
            torqueSamples[0] @ addr+0 … torqueSamples[3] @ addr+12

        Raises:
            _DaqSetupError: có signal chưa gán event, hoặc số DAQ list cần
                dùng vượt MAX_DAQ mà A2L khai. Phát hiện ở đây, trước khi gửi
                lệnh nào lên bus.
        """
        checked = self._checked_names()
        if not checked:
            return []
        by_event: dict[int, list[DaqSignal]] = {}
        missing: list[str] = []
        for name in checked:
            meas = self._db.measurements.get(name)
            if meas is None:
                continue
            event = self._event_of.get(name)
            if event is None:
                # KHÔNG mặc định về 0: xem khối "Synchronous Event" ở trên.
                missing.append(name)
                continue
            bucket = by_event.setdefault(event, [])
            n = meas.array_size       # 1 nếu scalar, >1 nếu array
            elem_size = meas.byte_size // n   # kích thước một phần tử (bytes)
            if n == 1:
                # Scalar — không thay đổi gì
                bucket.append(DaqSignal(
                    name=meas.name,
                    address=meas.address,
                    ext=0,
                    size=elem_size,
                    datatype=meas.datatype,
                ))
            else:
                # Array — tách thành N phần tử riêng, tên = "name[i]"
                for i in range(n):
                    bucket.append(DaqSignal(
                        name=f"{meas.name}[{i}]",
                        address=meas.address + i * elem_size,
                        ext=0,
                        size=elem_size,
                        datatype=meas.datatype,
                    ))

        if missing:
            shown = ", ".join(sorted(missing)[:6])
            more = f" (+{len(missing) - 6} more)" if len(missing) > 6 else ""
            raise _DaqSetupError(
                f"Pick a Synchronous Event for {len(missing)} selected signal(s) "
                f"first: {shown}{more}")

        lists = [DaqList(signals=sigs, event=event, timestamp=True)
                 for event, sigs in sorted(by_event.items()) if sigs]
        self._check_daq_capacity(lists)
        return lists

    def _check_daq_capacity(self, lists: list[DaqList]) -> None:
        """So số DAQ list cần dùng với MAX_DAQ mà A2L khai (`/begin DAQ`).

        Chỉ kiểm khi A2L có khai (`max_daq > 0`): ECU từ chối ALLOC_DAQ cũng
        ra lỗi, nhưng lúc đó người dùng chỉ thấy mã lỗi thô giữa chuỗi cấu
        hình, còn ở đây nói được chính xác cần mấy list và có mấy."""
        info = self._db.daq_info
        if info is None or info.max_daq <= 0 or len(lists) <= info.max_daq:
            return
        events = ", ".join(str(dl.event) for dl in lists)
        raise _DaqSetupError(
            f"{len(lists)} different events selected (event {events}) need "
            f"{len(lists)} DAQ lists, but the A2L declares MAX_DAQ="
            f"{info.max_daq}. Deselect signals from one of the rasters.")

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
