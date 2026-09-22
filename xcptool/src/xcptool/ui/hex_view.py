"""Hex View — load a calibration ECU's hex/s19 image, merge a previously
exported calibration dataset into it, preview the result next to the
original with differences highlighted. See
docs/superpowers/specs/2026-09-21-hexfile-generate-design.md.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import PushButton

from ..session.api import A2LDatabase, DatasetImportResult
from .leaf_enum import LeafInfo, enumerate_leaves
from .value_codec import decode_value, encode_value

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
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Calibration Dataset", "", "JSON (*.json)",
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            self.status_label.setText(f"Failed to read dataset file: {e}")
            return
        self._import_dataset_cb(payload)

    def on_dataset_validated(self, result: DatasetImportResult) -> None:
        assert self._db is not None  # generate_btn is disabled otherwise
        by_name = {leaf.name: leaf for leaf in self._leaves}
        byte_order = self.current_byte_order()
        patches: list[tuple[int, bytes, str]] = []
        errors: list[str] = []
        for name, text in result.matched.items():
            leaf = by_name.get(name)
            if leaf is None:
                continue  # not a leaf HexView knows about (e.g. a MEASUREMENT-only name)
            try:
                data = encode_value(text, leaf.datatype, byte_order, array_size=1)
            except ValueError as e:
                errors.append(f"{name}: {e}")
                continue
            patches.append((leaf.address, data, name))

        self._pending_patches = patches
        if errors:
            self.status_label.setText(f"{len(errors)} value(s) failed to encode: {errors[0]}")
            self._pending_patches = []
            return
        if not patches:
            self.status_label.setText("Nothing to patch — dataset matched 0 known parameter(s).")
            return
        self.status_label.setText(f"{len(patches)} parameter(s) ready — choose where to save.")

        hex_path = Path(self._hex_path_str)
        default_path = str(hex_path.with_name(hex_path.stem + "_mod" + hex_path.suffix))
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Patched Hex/S-record File", default_path,
            "Hex / S-record (*.hex *.ihex *.s19 *.s28 *.s37 *.srec *.mot)",
        )
        if not out_path:
            return
        self._generate_cb(patches, out_path)

    def on_generate_done(self, output_path: str) -> None:
        patched_bytes = {name: data for _addr, data, name in self._pending_patches}
        mod_values: dict[str, bytes | None] = dict(self._origin_bytes)
        mod_values.update(patched_bytes)
        self._render_table(self.mod_table, mod_values)

        changed = {
            name for name in patched_bytes
            if self._origin_bytes.get(name) != patched_bytes[name]
        }
        for row, leaf in enumerate(self._leaves):
            if leaf.name in changed:
                for col in range(len(_COLUMNS)):
                    self.mod_table.item(row, col).setBackground(_DIFF_BRUSH)

        self.status_label.setText(f"Patched {len(self._pending_patches)} parameter(s) into {Path(output_path).name}.")
        self._pending_patches = []

    def on_generate_error(self, exc: Exception) -> None:
        self.status_label.setText(f"Generate failed: {exc}")
        QMessageBox.critical(self, "Generate Failed", str(exc))
