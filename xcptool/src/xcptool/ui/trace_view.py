"""Cửa sổ debug CAN — bảng trace thời gian thực.

Hai điều làm nên tốc độ ở đây:

  * MainWindow gom frame theo QTimer 30–50 ms rồi gọi `append()` một lần với cả
    lô. KHÔNG vẽ theo từng frame.
  * Model chèn/xoá dòng theo lô (`beginInsertRows` / `beginRemoveRows`) nên
    QTableView chỉ dựng lại đúng những ô đang nhìn thấy, không phải cả 20.000 dòng.
"""

from __future__ import annotations

import csv
import itertools
from collections import deque
from typing import Iterable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QHeaderView, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    TableView,
    isDarkTheme,
)

from ..session.api import TraceEntry

__all__ = ["TraceModel", "TraceView", "ALL_KINDS"]

ALL_KINDS: tuple[str, ...] = ("cmd", "res", "err", "ev", "serv", "daq", "other")

_KIND_LABEL = {
    "cmd": "CMD",
    "res": "RES",
    "err": "ERR",
    "ev": "EV",
    "serv": "SERV",
    "daq": "DAQ",
    "other": "Other",
}

_KIND_COLOR_DARK = {
    "cmd": QColor("#7EC8FF"),
    "res": QColor("#8FE388"),
    "err": QColor("#FF7B72"),
    "ev": QColor("#FFD866"),
    "serv": QColor("#FFD866"),
    "daq": QColor("#C0C0C0"),
    "other": QColor("#909090"),
}

_KIND_COLOR_LIGHT = {
    "cmd": QColor("#0B5CAD"),
    "res": QColor("#1E7A26"),
    "err": QColor("#B3261E"),
    "ev": QColor("#8A6100"),
    "serv": QColor("#8A6100"),
    "daq": QColor("#3C3C3C"),
    "other": QColor("#6B6B6B"),
}

_COLUMNS = ("#", "t (s)", "Dir", "CAN ID", "DLC", "Data", "Decoded")


class TraceModel(QAbstractTableModel):
    """Ring buffer có trần — RAM phẳng kể cả khi bus flood hàng giờ."""

    def __init__(self, capacity: int = 20_000, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cap = capacity
        self._all: deque[TraceEntry] = deque(maxlen=capacity)
        self._rows: deque[TraceEntry] = deque()
        self._kinds: set[str] = set(ALL_KINDS)
        self._t0: float | None = None

    # ── Qt model ─────────────────────────────────────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        e = self._rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return e.seq
            if col == 1:
                base = self._t0 if self._t0 is not None else e.t_mono
                return f"{e.t_mono - base:9.4f}"
            if col == 2:
                return "→" if e.direction == "tx" else "←"
            if col == 3:
                return f"0x{e.can_id:03X}"
            if col == 4:
                return len(e.data)
            if col == 5:
                return " ".join(f"{b:02X}" for b in e.data)
            if col == 6:
                return e.decoded if e.note is None else f"{e.decoded}   [{e.note}]"
        elif role == Qt.ForegroundRole:
            table = _KIND_COLOR_DARK if isDarkTheme() else _KIND_COLOR_LIGHT
            return table.get(e.kind)
        elif role == Qt.TextAlignmentRole and col in (0, 1, 4):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        elif role == Qt.UserRole:
            return e
        return None

    # ── nạp dữ liệu ──────────────────────────────────────────────────────────

    def append(self, entries: Iterable[TraceEntry]) -> None:
        batch = [e for e in entries if e.kind in self._kinds]
        if not batch:
            return
        if self._t0 is None:
            self._t0 = batch[0].t_mono

        # Một lô lớn hơn cả trần: chỉ phần đuôi sống sót. Phải cắt TRƯỚC khi
        # tính số dòng bị đẩy ra, nếu không `_rows` sẽ dài hơn `_all`.
        if len(batch) > self._cap:
            batch = batch[len(batch) - self._cap:]

        n_evict = max(0, len(self._all) + len(batch) - self._cap)
        if n_evict:
            evicted = itertools.islice(self._all, 0, n_evict)
            visible_evicted = sum(1 for e in evicted if e.kind in self._kinds)
            if visible_evicted:
                self.beginRemoveRows(QModelIndex(), 0, visible_evicted - 1)
                for _ in range(visible_evicted):
                    self._rows.popleft()
                self.endRemoveRows()

        self._all.extend(batch)

        start = len(self._rows)
        self.beginInsertRows(QModelIndex(), start, start + len(batch) - 1)
        self._rows.extend(batch)
        self.endInsertRows()

    def set_capacity(self, capacity: int) -> None:
        if capacity == self._cap:
            return
        self._cap = capacity
        self.beginResetModel()
        self._all = deque(self._all, maxlen=capacity)
        self._rows = deque(e for e in self._all if e.kind in self._kinds)
        self.endResetModel()

    def set_kinds(self, kinds: set[str]) -> None:
        if kinds == self._kinds:
            return
        self._kinds = set(kinds)
        self.beginResetModel()
        self._rows = deque(e for e in self._all if e.kind in self._kinds)
        self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel()
        self._all.clear()
        self._rows.clear()
        self._t0 = None
        self.endResetModel()

    @property
    def total_held(self) -> int:
        return len(self._all)

    def visible_entries(self) -> list[TraceEntry]:
        return list(self._rows)


class TraceView(QWidget):
    """Bảng trace + thanh công cụ: lọc, tạm dừng, tự cuộn, xoá, xuất file."""

    def __init__(self, capacity: int = 20_000, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("traceView")

        self.model = TraceModel(capacity, self)
        self._paused = False
        self._skipped_while_paused = 0
        self._received = 0

        self.table = TableView(self)
        self.table.setModel(self.model)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(9)
        self.table.setFont(mono)
        # qfluentwidgets.TableBase khoá sẵn 38px/dòng (đủ cho control cảm ứng)
        # — quá cao cho bảng log dày đặc muốn nhìn nhiều dòng cùng lúc.
        self.table.verticalHeader().setDefaultSectionSize(22)
        header = self.table.horizontalHeader()
        for i, mode in enumerate((
            QHeaderView.ResizeToContents, QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents, QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents, QHeaderView.Interactive,
            QHeaderView.Stretch,
        )):
            header.setSectionResizeMode(i, mode)
        self.table.setColumnWidth(5, 220)

        self.pause_btn = PushButton("Pause", self)
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._on_pause)

        self.autoscroll_cb = CheckBox("Auto-scroll", self)
        self.autoscroll_cb.setChecked(True)

        self.clear_btn = PushButton("Clear", self)
        self.clear_btn.clicked.connect(self.clear)

        self.export_btn = PushButton("Export CSV…", self)
        self.export_btn.clicked.connect(self._on_export)

        self.cap_spin = SpinBox(self)
        self.cap_spin.setRange(1000, 500_000)
        self.cap_spin.setSingleStep(1000)
        self.cap_spin.setValue(capacity)
        self.cap_spin.setToolTip("Maximum row retention capacity — older frames will be evicted")

        self.kind_boxes: dict[str, CheckBox] = {}
        filter_row = QHBoxLayout()
        filter_row.addWidget(BodyLabel("Filter:", self))
        for kind in ALL_KINDS:
            cb = CheckBox(_KIND_LABEL[kind], self)
            cb.setChecked(kind != "daq")  # DAQ off by default — DTO floods at 50–100Hz
            cb.toggled.connect(self._on_filter)
            self.kind_boxes[kind] = cb
            filter_row.addWidget(cb)
        filter_row.addStretch(1)
        filter_row.addWidget(BodyLabel("Row limit:", self))
        filter_row.addWidget(self.cap_spin)
        
        # Apply initial filter state to the model (since toggled wasn't fired)
        self._on_filter()

        tool_row = QHBoxLayout()
        tool_row.addWidget(self.pause_btn)
        tool_row.addWidget(self.autoscroll_cb)
        tool_row.addWidget(self.clear_btn)
        tool_row.addWidget(self.export_btn)
        tool_row.addStretch(1)
        self.counter_label = StrongBodyLabel("", self)
        tool_row.addWidget(self.counter_label)

        self.note_label = CaptionLabel(
            "Timestamp quality varies by device: hardware timestamps from PEAK/Vector; "
            "software timestamps from slcan and virtual buses may exhibit jitter.",
            self,
        )
        self.note_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(tool_row)
        layout.addLayout(filter_row)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.note_label)

        self._update_counters(0)

    # ── API for MainWindow ───────────────────────────────────────────────────

    def feed(self, entries: list[TraceEntry], dropped: int) -> None:
        """Receive a batched block of trace entries. Called from UI thread."""
        self._received += len(entries)
        if self._paused:
            self._skipped_while_paused += len(entries)
        else:
            self.model.set_capacity(self.cap_spin.value())
            at_bottom = self.autoscroll_cb.isChecked()
            self.model.append(entries)
            if at_bottom and entries and self.isVisible():
                self.table.scrollToBottom()
        self._update_counters(dropped)

    def clear(self) -> None:
        self.model.clear()
        self._received = 0
        self._skipped_while_paused = 0
        self._update_counters(0)

    # ── internal ─────────────────────────────────────────────────────────────

    def _on_pause(self, paused: bool) -> None:
        self._paused = paused
        self.pause_btn.setText("Resume" if paused else "Pause")

    def _on_filter(self) -> None:
        self.model.set_kinds({k for k, cb in self.kind_boxes.items() if cb.isChecked()})

    def _update_counters(self, dropped: int) -> None:
        self.counter_label.setText(
            f"Rx {self._received}  ·  Buffer {self.model.total_held}  ·  "
            f"Shown {self.model.rowCount()}  ·  Dropped {dropped}  ·  "
            f"Paused {self._skipped_while_paused}"
        )

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Trace", "trace.csv", "CSV (*.csv)"
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["seq", "t_mono", "direction", "can_id", "dlc", "data", "kind",
                        "decoded", "note"])
            for e in self.model.visible_entries():
                w.writerow([
                    e.seq, f"{e.t_mono:.6f}", e.direction, f"0x{e.can_id:03X}",
                    len(e.data), " ".join(f"{b:02X}" for b in e.data), e.kind,
                    e.decoded, e.note or "",
                ])
