"""Hex View — load a calibration ECU's hex/s19 image, merge a previously
exported calibration dataset into it, preview the result next to the
original with differences highlighted. See
docs/superpowers/specs/2026-09-21-hexfile-generate-design.md.
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import PushButton

from ..session.api import A2LDatabase, DatasetImportResult
from .leaf_enum import LeafInfo, enumerate_leaves
from .value_codec import decode_value

__all__ = ["HexView"]

_COLUMNS = ["Address", "Name", "Size", "Bytes", "Value"]
_BYTE_ORDER_LABELS = {"little": "Little Endian", "big": "Big Endian"}
_BYTE_ORDER_VALUES = {v: k for k, v in _BYTE_ORDER_LABELS.items()}
_DIFF_BRUSH = QBrush(QColor("#5a3d00"))  # dark amber — visible in both light/dark themes


def _make_table() -> QTableWidget:
    table = QTableWidget(0, len(_COLUMNS))
    table.setHorizontalHeaderLabels(_COLUMNS)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    return table


class HexView(QWidget):
    regions_requested = Signal(list)  # list[tuple[int, int, str]] -> MainWindow calls session.hex_regions

    def __init__(
        self,
        import_dataset_cb: Callable[[dict], None],
        generate_cb: Callable[[list[tuple[int, bytes, str]], str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._import_dataset_cb = import_dataset_cb
        self._generate_cb = generate_cb

        self._db: A2LDatabase | None = None
        self._leaves: list[LeafInfo] = []
        self._hex_loaded = False
        self._hex_path_str = ""
        self._origin_bytes: dict[str, bytes | None] = {}
        self._pending_patches: list[tuple[int, bytes, str]] = []

        top = QHBoxLayout()
        top.addWidget(QLabel("Byte order:"))
        self.byte_order_combo = QComboBox()
        self.byte_order_combo.addItems(list(_BYTE_ORDER_LABELS.values()))
        top.addWidget(self.byte_order_combo)
        top.addStretch(1)
        self.generate_btn = PushButton("Generate hex from dataset")
        self.generate_btn.setEnabled(False)
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        top.addWidget(self.generate_btn)
        self.status_label = QLabel("Load an A2L and a hex/s19 file to begin.")

        tables = QHBoxLayout()
        self.origin_table = _make_table()
        self.mod_table = _make_table()
        tables.addWidget(self.origin_table)
        tables.addWidget(self.mod_table)

        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addLayout(tables)
        root.addWidget(self.status_label)

    # ── public state transitions ────────────────────────────────────────────

    def set_database(self, db: A2LDatabase) -> None:
        self._db = db
        self._leaves = enumerate_leaves(db)
        self._update_generate_enabled()
        self._request_regions_if_ready()

    def set_hex_loaded(self, path: str) -> None:
        self._hex_loaded = True
        self._hex_path_str = path
        self._update_generate_enabled()
        self._request_regions_if_ready()

    def set_byte_order(self, byte_order: str) -> None:
        label = _BYTE_ORDER_LABELS.get(byte_order, _BYTE_ORDER_LABELS["little"])
        self.byte_order_combo.setCurrentText(label)

    def current_byte_order(self) -> str:
        return _BYTE_ORDER_VALUES.get(self.byte_order_combo.currentText(), "little")

    def on_regions_ready(self, regions: dict[str, bytes | None]) -> None:
        self._origin_bytes = regions
        self._render_table(self.origin_table, regions)

    def _render_table(self, table: QTableWidget, values: dict[str, bytes | None]) -> None:
        table.setRowCount(len(self._leaves))
        byte_order = self.current_byte_order()
        for row, leaf in enumerate(self._leaves):
            data = values.get(leaf.name)
            table.setItem(row, 0, QTableWidgetItem(f"0x{leaf.address:08X}"))
            table.setItem(row, 1, QTableWidgetItem(leaf.name))
            table.setItem(row, 2, QTableWidgetItem(str(leaf.size)))
            if data is None:
                table.setItem(row, 3, QTableWidgetItem("— (not in file)"))
                table.setItem(row, 4, QTableWidgetItem("— (not in file)"))
            else:
                table.setItem(row, 3, QTableWidgetItem(data.hex().upper()))
                value_text = decode_value(data, leaf.datatype, byte_order)
                table.setItem(row, 4, QTableWidgetItem(value_text))

    # ── internal ─────────────────────────────────────────────────────────────

    def _update_generate_enabled(self) -> None:
        self.generate_btn.setEnabled(self._db is not None and self._hex_loaded)

    def _request_regions_if_ready(self) -> None:
        if self._db is None or not self._hex_loaded or not self._leaves:
            return
        addresses = [(leaf.address, leaf.size, leaf.name) for leaf in self._leaves]
        self.regions_requested.emit(addresses)

    def _on_generate_clicked(self) -> None:
        raise NotImplementedError  # wired in Task 12
