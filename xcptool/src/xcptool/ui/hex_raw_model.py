"""HexRawTableModel — lazy (address, bytes) table for the Hex View Raw
tab. Qt only calls data() for rows actually being painted, so this scales
to real flash-image row counts (tens to hundreds of thousands) without
eagerly building anything — unlike CalibrationView/Hex View's Calibration
tab, both of which use the eager QTableWidget (fine there: row count is
bounded by A2L calibration parameter count, tens to low hundreds).
"""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush

__all__ = ["HexRawTableModel"]

_COLUMNS = ["Address", "Bytes"]


class HexRawTableModel(QAbstractTableModel):
    def __init__(self, diff_brush: QBrush, parent=None) -> None:
        super().__init__(parent)
        self._diff_brush = diff_brush
        self._rows: list[tuple[int, bytes]] = []
        self._diff_addresses: set[int] = set()

    def set_rows(self, rows: list[tuple[int, bytes]]) -> None:
        self.beginResetModel()
        self._rows = rows
        self._diff_addresses = set()
        self.endResetModel()

    def set_diff_addresses(self, addresses: set[int]) -> None:
        self._diff_addresses = addresses
        if not self._rows:
            return
        top_left = self.index(0, 0)
        bottom_right = self.index(len(self._rows) - 1, len(_COLUMNS) - 1)
        self.dataChanged.emit(top_left, bottom_right, [Qt.BackgroundRole])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(_COLUMNS)

    def headerData(self, section: int, orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return _COLUMNS[section]

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        address, raw = self._rows[index.row()]
        if role == Qt.DisplayRole:
            return f"0x{address:08X}" if index.column() == 0 else raw.hex().upper()
        if role == Qt.BackgroundRole and address in self._diff_addresses:
            return self._diff_brush
        return None
