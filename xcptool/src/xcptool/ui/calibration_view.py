"""Panel hiệu chỉnh — CHARACTERISTIC tree từ A2L, inline edit, điều khiển trang."""

from __future__ import annotations

import struct
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
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
    SegmentedWidget,
    SpinBox,
    isDarkTheme,
)

from ..session.api import A2LDatabase

__all__ = ["CalibrationView", "WORKING_PAGE", "REFERENCE_PAGE"]

WORKING_PAGE = 0
REFERENCE_PAGE = 1

# UI chỉ phân biệt Working/Reference (DESIGN.md §5) — routeKey của SegmentedWidget
# ánh xạ trực tiếp tới hai giá trị trang duy nhất mà xcptool set (luôn set cả
# ECU lẫn XCP cùng lúc, không lộ khái niệm "trang XCP"/"trang ECU" ra UI).
_ROUTE_WORKING = "working"
_ROUTE_REFERENCE = "reference"
_ROUTE_BY_PAGE = {WORKING_PAGE: _ROUTE_WORKING, REFERENCE_PAGE: _ROUTE_REFERENCE}

# Ánh xạ datatype A2L → format character của struct
_ENDIAN: dict[str, str] = {"little": "<", "big": ">"}
_DTYPE_FMT: dict[str, str] = {
    "UBYTE": "B", "SBYTE": "b",
    "UWORD": "H", "SWORD": "h",
    "ULONG": "I", "SLONG": "i",
    "FLOAT32_IEEE": "f", "FLOAT64_IEEE": "d",
}

# Tên thân thiện cho kiểu dữ liệu A2L → kiểu C quen thuộc
_FRIENDLY_DTYPE: dict[str, str] = {
    "UBYTE": "UINT8", "SBYTE": "INT8",
    "UWORD": "UINT16", "SWORD": "INT16",
    "ULONG": "UINT32", "SLONG": "INT32",
    "FLOAT32_IEEE": "FLOAT32", "FLOAT64_IEEE": "FLOAT64",
}

# Chỉ số cột trong QTreeWidget
COL_NAME = 0
COL_TYPE = 1
COL_ADDR = 2
COL_SIZE = 3
COL_VALUE = 4
COL_RANGE = 5
COL_DESC = 6
_HEADERS = ["Name", "Type", "Address", "Size", "Value", "Range", "Description"]


def decode_value(data: bytes, datatype: str, byte_order: str) -> str:
    """Giải mã bytes thành chuỗi đọc được.

    VAL_BLK / array: "v0, v1, v2, …".  VALUE scalar: "v".
    """
    fmt_char = _DTYPE_FMT.get(datatype, "B")
    endian = _ENDIAN.get(byte_order, "<")
    item_size = struct.calcsize(fmt_char)
    if item_size == 0 or len(data) < item_size:
        return "???"
    n = len(data) // item_size
    values = [
        struct.unpack_from(endian + fmt_char, data, i * item_size)[0]
        for i in range(n)
    ]
    if datatype.startswith("FLOAT"):
        parts = [f"{v:.6g}" for v in values]
    else:
        parts = [str(v) for v in values]
    return ", ".join(parts)


def encode_value(text: str, datatype: str, byte_order: str, array_size: int) -> bytes:
    """Mã hoá chuỗi nhập từ người dùng thành bytes để ghi xuống ECU.

    Raises:
        ValueError: chuỗi không parse được hoặc số lượng phần tử không khớp.
        struct.error: giá trị nằm ngoài khoảng kiểu dữ liệu.
    """
    fmt_char = _DTYPE_FMT.get(datatype)
    if fmt_char is None:
        raise ValueError(f"Unsupported datatype: {datatype}")
    endian = _ENDIAN.get(byte_order, "<")
    raw = [p.strip() for p in text.split(",")]
    if len(raw) == 1 and array_size > 1:
        raw = raw * array_size
    if len(raw) != array_size:
        raise ValueError(f"Expected {array_size} values, received {len(raw)}")
    is_float = datatype.startswith("FLOAT")
    buf = bytearray()
    for part in raw:
        v = float(part) if is_float else int(part, 0)
        buf += struct.pack(endian + fmt_char, v)
    return bytes(buf)


def _group_by_prefix(names: list[str]) -> list[tuple[str | None, list[str]]]:
    """Gom nhóm các tên theo struct prefix (dấu '.' hoặc tiền tố '_' nếu có >= 2 biến).

    Trả về danh sách (group_name, [full_name1, full_name2, ...]):
    - Nếu là struct: ("speedPid", ["speedPid_kp", "speedPid_ki", ...])
    - Nếu là biến đơn/mảng: (None, ["tempCompTable"])
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


class CalibrationView(QWidget):
    """Panel hiệu chỉnh — xem và sửa CHARACTERISTIC từ A2L.

    Callback do MainWindow cấp — mọi lời gọi Session đều chạy trên worker.
    """

    a2l_load_requested = Signal(str)  # path: str — user đã chọn file A2L

    def __init__(
        self,
        read_all_cb: Callable[[], None],
        write_cb: Callable[[str, int, bytes], None],   # (name, addr, data)
        get_pages_cb: Callable[[int], None],           # (segment)
        set_page_cb: Callable[[int, int], None],        # (segment, page) — set CẢ ECU lẫn XCP
        copy_page_cb: Callable[[int, int, int, int], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("calibrationView")
        self._read_all_cb = read_all_cb
        self._write_cb = write_cb
        self._get_pages_cb = get_pages_cb
        self._set_page_cb = set_page_cb
        self._copy_page_cb = copy_page_cb

        self._db: A2LDatabase = A2LDatabase()
        self._byte_order = "little"
        self._char_items: dict[str, QTreeWidgetItem] = {}   # name → item
        self._original: dict[str, str] = {}                 # name → giá trị khi vừa đọc
        self._dirty: set[str] = set()                       # tên characteristic đang sửa
        self._suspend_signals = False
        self._last_ecu_page: int | None = None
        self._last_xcp_page: int | None = None

        self._build_ui()

    # ── dựng giao diện ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── toolbar ──────────────────────────────────────────────────────────
        self.load_btn = PushButton("Load A2L…", self)
        self.load_btn.clicked.connect(self._on_load_click)

        self.read_all_btn = PrimaryPushButton("Read All", self)
        self.read_all_btn.clicked.connect(self._on_read_all)

        self.write_btn = PushButton("Write Changes", self)
        self.write_btn.clicked.connect(self._on_write)
        self.write_btn.setEnabled(False)

        self.count_label = BodyLabel("No A2L loaded.", self)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.load_btn)
        toolbar.addWidget(self.read_all_btn)
        toolbar.addWidget(self.write_btn)
        toolbar.addWidget(self.count_label)
        toolbar.addStretch(1)

        # ── tree ─────────────────────────────────────────────────────────────
        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(len(_HEADERS))
        self.tree.setHeaderLabels(_HEADERS)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        # Chỉ cho sửa khi double-click cột Value — xem _start_value_edit
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.itemDoubleClicked.connect(self._start_value_edit)
        self.tree.itemSelectionChanged.connect(self._update_write_btn)
        self.tree.itemChanged.connect(self._on_item_changed)


        hdr = self.tree.header()
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_TYPE, QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_ADDR, QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_SIZE, QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_VALUE, QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_RANGE, QHeaderView.Interactive)
        hdr.setSectionResizeMode(COL_DESC, QHeaderView.Stretch)

        self.tree.setColumnWidth(COL_NAME, 200)
        self.tree.setColumnWidth(COL_TYPE, 100)
        self.tree.setColumnWidth(COL_ADDR, 90)
        self.tree.setColumnWidth(COL_SIZE, 50)
        self.tree.setColumnWidth(COL_VALUE, 120)
        self.tree.setColumnWidth(COL_RANGE, 120)

        # ── điều khiển trang ─────────────────────────────────────────────────
        # UI chỉ có khái niệm Working/Reference (DESIGN.md §5) — không hiện
        # riêng "trang ECU"/"trang XCP". SegmentedWidget tự vẽ chỉ báo màu accent
        # trượt sang mục đang chọn, đúng hiệu ứng "chuyển sang xanh" khi active.
        self.segment_spin = SpinBox(self)
        self.segment_spin.setRange(0, 255)
        self.segment_spin.lineEdit().setMinimumWidth(40)

        self.page_toggle = SegmentedWidget(self)
        self.page_toggle.addItem(
            routeKey=_ROUTE_WORKING, text="Working (RAM)", onClick=self._on_toggle_working
        )
        self.page_toggle.addItem(
            routeKey=_ROUTE_REFERENCE, text="Reference (ROM)", onClick=self._on_toggle_reference
        )

        self.refresh_pages_btn = PushButton("Read Page Status", self)
        self.refresh_pages_btn.clicked.connect(self._on_refresh_pages)

        self.copy_ref_btn = PushButton("Copy Ref→Working", self)
        self.copy_ref_btn.setToolTip(
            "Copy reference page → working page (reset all to ROM defaults)"
        )
        self.copy_ref_btn.clicked.connect(self._on_copy_ref_to_working)

        page_row = QHBoxLayout()
        page_row.addWidget(BodyLabel("Segment:", self))
        page_row.addWidget(self.segment_spin)
        page_row.addWidget(self.page_toggle)
        page_row.addWidget(self.refresh_pages_btn)
        page_row.addWidget(self.copy_ref_btn)
        page_row.addStretch(1)

        # Only shown when GET_CAL_PAGE reports ECU ≠ XCP
        self.sync_warning_label = CaptionLabel("", self)
        self.sync_warning_label.hide()
        self.sync_btn = PushButton("Re-synchronize", self)
        self.sync_btn.clicked.connect(self._on_sync_click)
        self.sync_btn.hide()

        sync_row = QHBoxLayout()
        sync_row.addWidget(self.sync_warning_label, 1)
        sync_row.addWidget(self.sync_btn)

        self.status_label = CaptionLabel("", self)
        self.status_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(toolbar)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.status_label)
        layout.addLayout(page_row)
        layout.addLayout(sync_row)

    # ── cập nhật dữ liệu (gọi từ MainWindow, UI thread) ─────────────────────

    def set_database(self, db: A2LDatabase) -> None:
        """Điền tree từ A2LDatabase mới nạp. Gom nhóm Struct và phân rã Array."""
        self._db = db
        self._char_items.clear()
        self._original.clear()
        self._dirty.clear()

        self._suspend_signals = True
        try:
            self.tree.clear()
            groups = _group_by_prefix(sorted(db.characteristics.keys()))
            for group_name, members in groups:
                if group_name is not None and len(members) >= 2:
                    # ── STRUCT / GROUP ──────────────────────────────────────
                    chars = [db.characteristics[m] for m in members]
                    min_addr = min(c.address for c in chars)
                    total_size = sum(c.byte_size for c in chars)

                    parent = QTreeWidgetItem()
                    parent.setData(COL_NAME, Qt.UserRole, group_name)
                    parent.setText(COL_NAME, group_name)
                    parent.setText(COL_TYPE, f"STRUCT ({len(members)})")
                    parent.setText(COL_ADDR, f"0x{min_addr:08X}")
                    parent.setText(COL_SIZE, str(total_size))
                    parent.setText(COL_VALUE, "—")
                    parent.setText(COL_RANGE, "")
                    parent.setText(COL_DESC, f"Group of {len(members)} parameters")
                    parent.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    self.tree.addTopLevelItem(parent)

                    for c in chars:
                        disp_name = c.name[len(group_name):].lstrip("._") or c.name
                        child = self._make_item(c.name, c, display_name=disp_name)
                        parent.addChild(child)
                        self._char_items[c.name] = child
                        if c.array_size > 1:
                            self._build_array_children(child, c)
                    parent.setExpanded(True)
                else:
                    # ── SCALAR hoặc ARRAY ĐỘC LẬP ───────────────────────────
                    name = members[0]
                    char = db.characteristics[name]
                    item = self._make_item(name, char)
                    self.tree.addTopLevelItem(item)
                    self._char_items[name] = item
                    if char.array_size > 1:
                        self._build_array_children(item, char)
        finally:
            self._suspend_signals = False

        n = len(db.characteristics)
        self.count_label.setText(f"{n} CHARACTERISTIC(s)")
        self.status_label.setText(
            "A2L loaded. Connect to ECU and click 'Read All' to fetch current values."
            if n > 0 else "A2L file contains no CHARACTERISTICs."
        )
        self.write_btn.setEnabled(False)

    def set_byte_order(self, byte_order: str) -> None:
        """Cập nhật byte order sau khi CONNECT thành công (từ SlaveCaps)."""
        self._byte_order = byte_order

    def on_read_done(self, name: str, data: bytes) -> None:
        """Cập nhật giá trị hiển thị cho một CHARACTERISTIC sau khi đọc từ ECU."""
        item = self._char_items.get(name)
        char = self._db.characteristics.get(name)
        if item is None or char is None or char.datatype is None:
            return
        text = decode_value(data, char.datatype, self._byte_order)
        self._suspend_signals = True
        try:
            if char.array_size > 1 and item.childCount() > 0:
                # Array: cha giữ "—", từng con hiện giá trị riêng
                item.setText(COL_VALUE, "—")
                item.setForeground(COL_VALUE, self.tree.palette().text())
                parts = [p.strip() for p in text.split(",")]
                for i in range(min(item.childCount(), len(parts))):
                    child = item.child(i)
                    child.setText(COL_VALUE, parts[i])
                    child.setForeground(COL_VALUE, self.tree.palette().text())
            else:
                # Scalar
                item.setText(COL_VALUE, text)
                item.setForeground(COL_VALUE, self.tree.palette().text())
        finally:
            self._suspend_signals = False
        self._original[name] = text  # aggregated string — dùng cho dirty tracking
        self._dirty.discard(name)
        self._update_write_btn()

    def on_batch_read_done(self, results: dict[str, bytes | None]) -> None:
        """Update all CHARACTERISTICs after a batch read."""
        ok = sum(1 for data in results.values() if data is not None)
        for name, data in results.items():
            if data is not None:
                self.on_read_done(name, data)
        total = len(results)
        fail = total - ok
        self.status_label.setText(
            f"Read {ok}/{total} parameters."
            + (f" {fail} failed (out of range or ECU rejected)." if fail else "")
        )

    def on_write_done(self, name: str) -> None:
        """Clear dirty indicator after successful write."""
        item = self._char_items.get(name)
        if item is None:
            return
        self._suspend_signals = True
        try:
            item.setForeground(COL_VALUE, self.tree.palette().text())
            for i in range(item.childCount()):
                item.child(i).setForeground(COL_VALUE, self.tree.palette().text())
        finally:
            self._suspend_signals = False
        self._original[name] = item.text(COL_VALUE)
        self._dirty.discard(name)
        self._update_write_btn()
        self.status_label.setText(f"Successfully wrote '{name}' to ECU.")

    def on_pages(self, segment: int, ecu_page: int | None, xcp_page: int | None) -> None:
        """Update page indicator from GET_CAL_PAGE response."""
        self._last_ecu_page = ecu_page
        self._last_xcp_page = xcp_page

        if ecu_page is None or xcp_page is None:
            self._set_sync_warning(None)
            self.status_label.setText("Failed to read page status.")
            return

        route = _ROUTE_BY_PAGE.get(xcp_page)
        if route is not None:
            self.page_toggle.setCurrentItem(route)

        if ecu_page == xcp_page:
            self._set_sync_warning(None)
            self.status_label.setText(
                "Active on Reference (ROM) — read-only, write operations will be rejected."
                if xcp_page == REFERENCE_PAGE
                else "Active on Working (RAM) — ready to write."
            )
        else:
            self._set_sync_warning(f"⚠ Pages desynchronized (ECU: {ecu_page}, XCP: {xcp_page})")

    def set_page_indicator(self, page: int) -> None:
        """Cập nhật chỉ báo sau khi ECU ack cả hai SET_CAL_PAGE, không cần đọc lại.

        Vì hành động luôn set cả ECU lẫn XCP cùng lúc, ack thành công nghĩa là
        hai trang đã đồng bộ — khỏi tốn một lượt GET_CAL_PAGE để xác nhận.
        """
        route = _ROUTE_BY_PAGE.get(page)
        if route is not None:
            self.page_toggle.setCurrentItem(route)
        self._last_ecu_page = page
        self._last_xcp_page = page
        self._set_sync_warning(None)

    def set_busy(self, busy: bool) -> None:
        for w in (
            self.read_all_btn, self.refresh_pages_btn,
            self.page_toggle, self.copy_ref_btn, self.sync_btn,
        ):
            w.setEnabled(not busy)
        if busy:
            self.write_btn.setEnabled(False)
        else:
            self._update_write_btn()

    # ── hành động người dùng ─────────────────────────────────────────────────

    def _on_load_click(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select A2L File", "", "A2L files (*.a2l);;All files (*)"
        )
        if path:
            self.a2l_load_requested.emit(path)

    def _on_read_all(self) -> None:
        if not self._db.characteristics:
            self.status_label.setText("No A2L loaded — click 'Load A2L…' first.")
            return
        self.status_label.setText("Reading all parameters…")
        self._read_all_cb()

    def _on_write(self) -> None:
        name = self._selected_char_name()
        if name is None or name not in self._dirty:
            self.status_label.setText("Select a modified CHARACTERISTIC to write.")
            return
        item = self._char_items[name]
        char = self._db.characteristics[name]
        if char.datatype is None:
            self.status_label.setText(f"'{name}' datatype not resolved (check A2L).")
            return
        text = item.text(COL_VALUE).strip()
        try:
            if char.array_size > 1 and item.childCount() > 0:
                # Array: read from children instead of parent (parent shows "—")
                parts = [item.child(i).text(COL_VALUE) for i in range(item.childCount())]
                text = ", ".join(parts)
            else:
                text = item.text(COL_VALUE).strip()
            data = encode_value(text, char.datatype, self._byte_order, char.array_size)
        except (ValueError, struct.error) as exc:
            self.status_label.setText(f"Invalid value: {exc}")
            return
        self._write_cb(name, char.address, data)

    def _on_refresh_pages(self) -> None:
        self._get_pages_cb(self.segment_spin.value())

    def _on_toggle_working(self) -> None:
        self._set_page_cb(self.segment_spin.value(), WORKING_PAGE)

    def _on_toggle_reference(self) -> None:
        self._set_page_cb(self.segment_spin.value(), REFERENCE_PAGE)

    def _on_sync_click(self) -> None:
        """Đồng bộ lại — set cả hai về trang XCP, vì XCP là phía master đang
        kiểm soát (DESIGN.md §5)."""
        if self._last_xcp_page is None:
            return
        self._set_page_cb(self.segment_spin.value(), self._last_xcp_page)

    def _on_copy_ref_to_working(self) -> None:
        seg = self.segment_spin.value()
        self._copy_page_cb(seg, REFERENCE_PAGE, seg, WORKING_PAGE)

    def _set_sync_warning(self, text: str | None) -> None:
        if text is None:
            self.sync_warning_label.hide()
            self.sync_btn.hide()
        else:
            self.sync_warning_label.setText(text)
            self.sync_warning_label.show()
            self.sync_btn.show()

    # ── nội bộ ───────────────────────────────────────────────────────────────

    def _make_item(self, name: str, char: Any, display_name: str | None = None) -> QTreeWidgetItem:
        item = QTreeWidgetItem()
        item.setData(COL_NAME, Qt.UserRole, name)
        item.setText(COL_NAME, display_name or name)
        dtype_str = _FRIENDLY_DTYPE.get(char.datatype or "", char.datatype or char.char_type)
        if char.array_size > 1:
            dtype_str = f"{dtype_str}[{char.array_size}]"
        item.setText(COL_TYPE, dtype_str)
        item.setText(COL_ADDR, f"0x{char.address:08X}")

        item.setText(COL_SIZE, str(char.byte_size))
        item.setText(COL_VALUE, "—")
        lo = f"{char.lower_limit:.6g}"
        hi = f"{char.upper_limit:.6g}"
        item.setText(COL_RANGE, f"[{lo} … {hi}]")
        item.setText(COL_DESC, char.description)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        return item

    def _build_array_children(self, parent_item: QTreeWidgetItem, char: Any) -> None:
        """Tạo các node con hiển thị từng phần tử của Array."""
        elem_size = char.byte_size // char.array_size
        for i in range(char.array_size):
            child = QTreeWidgetItem()
            child.setData(COL_NAME, Qt.UserRole, ("array_elem", char.name, i))
            child.setText(COL_NAME, f"[{i}]")
            child.setText(COL_TYPE, _FRIENDLY_DTYPE.get(char.datatype or "", char.datatype or "ELEMENT"))
            child.setText(COL_ADDR, f"0x{(char.address + i * elem_size):08X}")
            child.setText(COL_SIZE, str(elem_size))
            child.setText(COL_VALUE, "—")
            child.setText(COL_RANGE, parent_item.text(COL_RANGE))
            child.setText(COL_DESC, f"{char.name}[{i}]")
            child.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            parent_item.addChild(child)
        parent_item.setExpanded(True)

    def _start_value_edit(self, item: QTreeWidgetItem, column: int) -> None:
        """Cho phép sửa inline khi double-click đúng cột Giá trị."""
        if column != COL_VALUE:
            return
        if item.text(COL_TYPE).startswith("STRUCT"):
            return   # Không sửa trực tiếp dòng cha STRUCT
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self.tree.editItem(item, COL_VALUE)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._suspend_signals or column != COL_VALUE:
            return
        # Khoá edit sau khi người dùng commit — tránh vô tình sửa tiếp
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)

        data_role = item.data(COL_NAME, Qt.UserRole)
        if data_role is None:
            return

        dirty_color = QColor("#FFB86C") if isDarkTheme() else QColor("#B35C00")
        neutral = self.tree.palette().text().color()

        if isinstance(data_role, tuple) and data_role[0] == "array_elem":
            # ── SỬA PHẦN TỬ CON CỦA ARRAY ──────────────────────────────────
            _, char_name, idx = data_role
            parent_item = self._char_items.get(char_name)
            if parent_item is None:
                return

            # Dựng lại chuỗi tóm tắt của dòng cha
            child_vals = [parent_item.child(i).text(COL_VALUE) for i in range(parent_item.childCount())]
            parent_text = ", ".join(child_vals)

            original = self._original.get(char_name)
            is_dirty = original is not None and parent_text != original

            self._suspend_signals = True
            try:
                parent_item.setForeground(COL_VALUE, dirty_color if is_dirty else neutral)
                item.setForeground(COL_VALUE, dirty_color if is_dirty else neutral)
            finally:
                self._suspend_signals = False

            if is_dirty:
                self._dirty.add(char_name)
            else:
                self._dirty.discard(char_name)
        else:
            # ── SỬA SCALAR HOẶC DÒNG CHA ARRAY ──────────────────────────────
            char_name = data_role
            if not isinstance(char_name, str):
                return
            current = item.text(COL_VALUE)
            original = self._original.get(char_name)
            is_dirty = original is not None and current != original
            item.setForeground(COL_VALUE, dirty_color if is_dirty else neutral)

            # Nếu là array, cập nhật các con tương ứng
            if item.childCount() > 0:
                parts = [p.strip() for p in current.split(",")]
                self._suspend_signals = True
                try:
                    for i in range(min(item.childCount(), len(parts))):
                        child = item.child(i)
                        child.setText(COL_VALUE, parts[i])
                        child.setForeground(COL_VALUE, dirty_color if is_dirty else neutral)
                finally:
                    self._suspend_signals = False

            if is_dirty:
                self._dirty.add(char_name)
            else:
                self._dirty.discard(char_name)

        self._update_write_btn()

    def _selected_char_name(self) -> str | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        data_role = item.data(COL_NAME, Qt.UserRole)
        if isinstance(data_role, tuple) and data_role[0] == "array_elem":
            return data_role[1]
        if isinstance(data_role, str):
            return data_role
        return None

    def _update_write_btn(self) -> None:
        name = self._selected_char_name()
        self.write_btn.setEnabled(name is not None and name in self._dirty)

