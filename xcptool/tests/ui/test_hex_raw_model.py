"""ui/hex_raw_model.py — lazy QAbstractTableModel for the Hex View Raw
tab. Needs a QApplication (via tests/ui/conftest.py's offscreen setup),
even though the model itself has no visible widget."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor

from xcptool.ui.hex_raw_model import HexRawTableModel

_BRUSH = QBrush(QColor("#5a3d00"))


def test_columns_are_address_and_bytes() -> None:
    model = HexRawTableModel(_BRUSH)
    assert model.columnCount() == 2
    assert model.headerData(0, Qt.Horizontal) == "Address"
    assert model.headerData(1, Qt.Horizontal) == "Bytes"


def test_set_rows_populates_row_count_and_cell_text() -> None:
    model = HexRawTableModel(_BRUSH)
    model.set_rows([(0x100, b"\x01\x02"), (0x200, b"\x03\x04\x05")])

    assert model.rowCount() == 2
    assert model.data(model.index(0, 0)) == "0x00000100"
    assert model.data(model.index(0, 1)) == "0102"
    assert model.data(model.index(1, 0)) == "0x00000200"
    assert model.data(model.index(1, 1)) == "030405"


def test_data_is_not_called_eagerly_for_a_large_row_count() -> None:
    # Laziness check without needing a real multi-MB fixture or a visible
    # QTableView: data() must not have been invoked at all just from
    # set_rows() — Qt only calls it per cell when something actually
    # asks (e.g. a view painting visible cells).
    model = HexRawTableModel(_BRUSH)
    calls = []
    original_data = model.data
    model.data = lambda index, role=Qt.DisplayRole: (calls.append(1), original_data(index, role))[1]

    model.set_rows([(i * 16, bytes(4)) for i in range(50_000)])

    assert model.rowCount() == 50_000
    assert calls == []


def test_set_diff_addresses_highlights_only_the_matching_rows() -> None:
    model = HexRawTableModel(_BRUSH)
    model.set_rows([(0x100, b"\x01"), (0x200, b"\x02")])
    model.set_diff_addresses({0x200})

    assert model.data(model.index(0, 0), Qt.BackgroundRole) is None
    assert model.data(model.index(1, 0), Qt.BackgroundRole) == _BRUSH
