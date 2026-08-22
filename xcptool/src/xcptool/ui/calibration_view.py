"""Panel hiệu chỉnh — CHARACTERISTIC tree từ A2L, inline edit, điều khiển trang."""

from __future__ import annotations

import struct
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
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
    ComboBox,
    LineEdit,
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


def decode_value(data: bytes, datatype: str, byte_order: str, radix: str = "DEC") -> str:
    """Giải mã bytes thành chuỗi đọc được.

    VAL_BLK / array: "v0, v1, v2, …".  VALUE scalar: "v".
    """
    fmt_char = _DTYPE_FMT.get(datatype, "B")
    endian = _ENDIAN.get(byte_order, "<")
    item_size = struct.calcsize(fmt_char)
    if item_size == 0 or len(data) < item_size:
        return "???"
    n = len(data) // item_size
    is_float = datatype.startswith("FLOAT")
    parts: list[str] = []

    for i in range(n):
        chunk = data[i * item_size : (i + 1) * item_size]
        if is_float:
            v = struct.unpack_from(endian + fmt_char, chunk)[0]
            if radix == "HEX":
                int_fmt = "I" if datatype == "FLOAT32_IEEE" else "Q"
                raw_int = struct.unpack_from(endian + int_fmt, chunk)[0]
                parts.append(f"0x{raw_int:0{item_size * 2}X}")
            elif radix == "BIN":
                int_fmt = "I" if datatype == "FLOAT32_IEEE" else "Q"
                raw_int = struct.unpack_from(endian + int_fmt, chunk)[0]
                parts.append(f"0b{raw_int:0{item_size * 8}b}")
            elif radix == "ASCII":
                chars = [chr(b) if 32 <= b <= 126 else "." for b in chunk]
                parts.append("".join(chars))
            else:
                parts.append(f"{v:.6g}")
        else:
            v = struct.unpack_from(endian + fmt_char, chunk)[0]
            if radix == "HEX":
                mask = (1 << (item_size * 8)) - 1
                parts.append(f"0x{v & mask:X}")
            elif radix == "BIN":
                mask = (1 << (item_size * 8)) - 1
                parts.append(f"0b{v & mask:b}")
            elif radix == "ASCII":
                try:
                    parts.append(chr(v) if 32 <= v <= 126 else ".")
                except ValueError:
                    parts.append(str(v))
            else:
                parts.append(str(v))
    return ", ".join(parts)


def encode_value(text: str, datatype: str, byte_order: str, array_size: int) -> bytes:
    """Mã hoá chuỗi nhập từ người dùng thành bytes để ghi xuống ECU.

    Hỗ trợ cả định dạng số (DEC, HEX, BIN) lẫn ký tự/chuỗi ASCII.

    Raises:
        ValueError: chuỗi không parse được hoặc số lượng phần tử không khớp.
        struct.error: giá trị nằm ngoài khoảng kiểu dữ liệu.
    """
    fmt_char = _DTYPE_FMT.get(datatype)
    if fmt_char is None:
        raise ValueError(f"Unsupported datatype: {datatype}")
    endian = _ENDIAN.get(byte_order, "<")
    item_size = struct.calcsize(fmt_char)
    raw = [p.strip() for p in text.split(",")]
    if len(raw) == 1 and array_size > 1:
        raw = raw * array_size
    if len(raw) != array_size:
        raise ValueError(f"Expected {array_size} values, received {len(raw)}")
    is_float = datatype.startswith("FLOAT")
    buf = bytearray()

    for part in raw:
        if is_float:
            part_lower = part.lower()
            if part_lower.startswith("0x") or part_lower.startswith("0b"):
                int_fmt = "I" if datatype == "FLOAT32_IEEE" else "Q"
                raw_int = int(part, 0)
                buf += struct.pack(endian + int_fmt, raw_int)
            else:
                try:
                    v = float(part)
                    buf += struct.pack(endian + fmt_char, v)
                except ValueError:
                    encoded_bytes = part.encode("latin-1")
                    if len(encoded_bytes) > item_size:
                        raise ValueError(f"ASCII string '{part}' too long for {datatype} (max {item_size} bytes)")
                    padded = encoded_bytes.ljust(item_size, b"\x00") if endian == "<" else encoded_bytes.rjust(item_size, b"\x00")
                    buf += padded
        else:
            try:
                v = int(part, 0)
                buf += struct.pack(endian + fmt_char, v)
            except ValueError:
                # Không phải số (Dec/Hex/Bin) -> parse theo ký tự / chuỗi ASCII
                encoded_bytes = part.encode("latin-1")
                if len(encoded_bytes) > item_size:
                    raise ValueError(f"ASCII string '{part}' too long for {datatype} (max {item_size} bytes)")
                padded = encoded_bytes.ljust(item_size, b"\x00") if endian == "<" else encoded_bytes.rjust(item_size, b"\x00")
                buf += padded

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
        read_cb: Callable[[str], None],                # (name)
        write_cb: Callable[[str, int, bytes], None],   # (name, addr, data)
        get_pages_cb: Callable[[int], None],           # (segment)
        set_page_cb: Callable[[int, int], None],        # (segment, page) — set CẢ ECU lẫn XCP
        copy_page_cb: Callable[[int, int, int, int], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("calibrationView")
        self._read_all_cb = read_all_cb
        self._read_cb = read_cb
        self._write_cb = write_cb
        self._get_pages_cb = get_pages_cb
        self._set_page_cb = set_page_cb
        self._copy_page_cb = copy_page_cb

        self._db: A2LDatabase = A2LDatabase()
        self._byte_order = "little"
        self._radix = "DEC"
        self._is_expanded = True
        self._char_items: dict[str, QTreeWidgetItem] = {}   # name → item
        self._original: dict[str, str] = {}                 # name → giá trị khi vừa đọc
        self._raw_data: dict[str, bytes] = {}               # name → raw bytes đã đọc
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

        self.read_btn = PushButton("Read", self)
        self.read_btn.clicked.connect(self._on_read)
        self.read_btn.setEnabled(False)

        self.write_btn = PushButton("Write Selected", self)
        self.write_btn.clicked.connect(self._on_write)
        self.write_btn.setEnabled(False)

        self.write_all_btn = PushButton("Write All", self)
        self.write_all_btn.clicked.connect(self._on_write_all)
        self.write_all_btn.setEnabled(False)

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
        toolbar.addWidget(self.read_all_btn)
        toolbar.addWidget(self.read_btn)
        toolbar.addWidget(self.write_btn)
        toolbar.addWidget(self.write_all_btn)
        toolbar.addWidget(self.search_box)
        toolbar.addWidget(self.expand_btn)
        toolbar.addWidget(self.radix_combo)
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
                    chars.sort(key=lambda c: c.address)
                    min_addr = chars[0].address
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
                    
                    self._char_items[group_name] = parent

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
        text = decode_value(data, char.datatype, self._byte_order, self._radix)
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
        self._raw_data[name] = data
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
            item.setForeground(COL_NAME, self.tree.palette().text())
            for i in range(item.childCount()):
                item.child(i).setForeground(COL_VALUE, self.tree.palette().text())
        finally:
            self._suspend_signals = False
            
        if item.childCount() > 0:
            if item.text(COL_TYPE).startswith("STRUCT"):
                for i in range(item.childCount()):
                    child = item.child(i)
                    child_name = child.data(COL_NAME, Qt.UserRole)
                    if child.childCount() > 0:
                        child_vals = [child.child(j).text(COL_VALUE) for j in range(child.childCount())]
                        self._original[child_name] = ", ".join(child_vals)
                    else:
                        self._original[child_name] = child.text(COL_VALUE)
                    self._dirty.discard(child_name)
            else:
                child_vals = [item.child(i).text(COL_VALUE) for i in range(item.childCount())]
                self._original[name] = ", ".join(child_vals)
        else:
            self._original[name] = item.text(COL_VALUE)
            
        self._dirty.discard(name)
        self._update_write_btn()
        self.status_label.setText(f"Successfully wrote '{name}' to ECU.")
        
        if hasattr(self, '_write_queue') and self._write_queue:
            self._process_write_queue()

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
            self.read_btn, self.write_btn, self.write_all_btn,
        ):
            w.setEnabled(not busy)
        if busy:
            self.write_btn.setEnabled(False)
            self.write_all_btn.setEnabled(False)
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

    def _on_read(self) -> None:
        """Read only the selected parent characteristic."""
        char_name = self._selected_char_name()
        if not char_name:
            return
            
        self._read_cb(char_name)

    def _on_write(self) -> None:
        """Called when 'Write Selected' is clicked."""
        char_name = self._selected_char_name()
        if not char_name:
            return
            
        item = self._char_items.get(char_name)
        if item:
            self._write_parent(char_name, item)

    def _on_write_all(self) -> None:
        """Called when 'Write All' is clicked."""
        dirty_names = list(self._dirty)
        items_to_write = set()
        for char_name in dirty_names:
            item = self._char_items.get(char_name)
            if not item: continue
            
            if item.parent() is not None and item.parent().text(COL_TYPE).startswith("STRUCT"):
                items_to_write.add(item.parent())
            else:
                items_to_write.add(item)
                
        self._write_queue = list(items_to_write)
        self._process_write_queue()
        
    def _process_write_queue(self) -> None:
        if not hasattr(self, '_write_queue') or not self._write_queue:
            return
            
        item = self._write_queue.pop(0)
        char_name = item.data(COL_NAME, Qt.UserRole)
        self._write_parent(char_name, item)

    def _write_parent(self, char_name: str, item: QTreeWidgetItem) -> None:
        if item.text(COL_TYPE).startswith("STRUCT"):
            try:
                min_addr = int(item.text(COL_ADDR), 16)
                total_size = int(item.text(COL_SIZE))
                buf = bytearray(total_size)
                
                for i in range(item.childCount()):
                    child = item.child(i)
                    c_name = child.data(COL_NAME, Qt.UserRole)
                    c_def = self._db.characteristics.get(c_name)
                    if not c_def: continue
                    
                    if c_def.array_size > 1 and child.childCount() > 0:
                        children_values = [child.child(j).text(COL_VALUE) for j in range(child.childCount())]
                        val_bytes = encode_value(",".join(children_values), c_def.datatype, self._byte_order, c_def.array_size)
                    else:
                        val_bytes = encode_value(child.text(COL_VALUE).strip(), c_def.datatype, self._byte_order, c_def.array_size)
                        
                    offset = c_def.address - min_addr
                    if offset + len(val_bytes) > total_size:
                        raise ValueError(f"Size overflow for {c_name} in struct {char_name}")
                    buf[offset:offset+len(val_bytes)] = val_bytes
                    
                self._write_cb(char_name, min_addr, bytes(buf))
                
                # Cleanup dirty state
                for i in range(item.childCount()):
                    c_name = item.child(i).data(COL_NAME, Qt.UserRole)
                    self._dirty.discard(c_name)
                    item.child(i).setForeground(COL_VALUE, QBrush())
                self._update_write_btn()
                if not self._dirty:
                    self.write_all_btn.setEnabled(False)
            except ValueError as e:
                self.status_label.setText(f"Invalid value in STRUCT: {e}")
                if hasattr(self, '_write_queue') and self._write_queue:
                    self._process_write_queue()
            return

        char_def = self._db.characteristics.get(char_name)
        if not char_def:
            return
        try:
            if char_def.array_size > 1 and item.childCount() > 0:
                children_values = [item.child(i).text(COL_VALUE) for i in range(item.childCount())]
                raw_bytes = encode_value(",".join(children_values), char_def.datatype, self._byte_order, char_def.array_size)
            else:
                raw_bytes = encode_value(item.text(COL_VALUE).strip(), char_def.datatype, self._byte_order, char_def.array_size)
            
            self._write_cb(char_name, char_def.address, raw_bytes)
            
            # Cleanup dirty state
            self._dirty.discard(char_name)
            item.setForeground(COL_VALUE, QBrush())
            self._update_write_btn()
            if not self._dirty:
                self.write_all_btn.setEnabled(False)
        except ValueError as e:
            self.status_label.setText(f"Invalid value: {e}")
            if hasattr(self, '_write_queue') and self._write_queue:
                self._process_write_queue()

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

    def _on_search(self, text: str) -> None:
        text = text.lower()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            self._filter_tree_item(item, text)

    def _filter_tree_item(self, item: QTreeWidgetItem, text: str) -> bool:
        """Trả về True nếu item hoặc con của nó match."""
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
        for name, data in self._raw_data.items():
            if name not in self._dirty:
                self.on_read_done(name, data)
        self.status_label.setText(f"Radix changed to {text}.")

    # ── nội bộ ───────────────────────────────────────────────────────────────

    def _selected_char_name(self) -> str | None:
        item = self.tree.currentItem()
        if not item: return None
        
        data = item.data(0, Qt.UserRole)
        if not data: return None
        
        if isinstance(data, tuple):
            if data[0] == "array_elem":
                return data[1]
            return data[0]
            
        return data

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

    def _on_item_selection_changed(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            self.write_btn.setEnabled(False)
            self.read_btn.setEnabled(False)
            return

        item = items[0]
        data_role = item.data(0, Qt.UserRole)
        is_child = isinstance(data_role, tuple) or (isinstance(data_role, str) and item.parent() is not None)

        self.read_btn.setEnabled(not is_child)

        if is_child:
            self.write_btn.setEnabled(False)
        else:
            char_name = data_role
            if char_name:
                self.write_btn.setEnabled(char_name in self._dirty)
            else:
                self.write_btn.setEnabled(False)

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
            
            if item.childCount() > 0 and current == "—":
                return
                
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

            struct_parent = item.parent()
            if struct_parent is not None:
                any_dirty = is_dirty
                if not is_dirty:
                    for i in range(struct_parent.childCount()):
                        child_name = struct_parent.child(i).data(COL_NAME, Qt.UserRole)
                        if isinstance(child_name, str) and child_name in self._dirty:
                            any_dirty = True
                            break
                struct_parent.setForeground(COL_NAME, dirty_color if any_dirty else neutral)

        self._update_write_btn()

    def _update_write_btn(self) -> None:
        char_name = self._selected_char_name()
        if not char_name:
            self.write_btn.setEnabled(False)
            return
            
        item = self._char_items.get(char_name)
        if item and item.text(COL_TYPE).startswith("STRUCT"):
            enable = False
            for i in range(item.childCount()):
                child_name = item.child(i).data(COL_NAME, Qt.UserRole)
                if isinstance(child_name, str) and child_name in self._dirty:
                    enable = True
                    break
            self.write_btn.setEnabled(enable)
        else:
            self.write_btn.setEnabled(char_name in self._dirty)
