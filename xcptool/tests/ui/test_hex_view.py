"""HexView widget tests — headless via pytest-qt, mirrors the fixture
pattern already used in tests/ui/test_calibration_view.py."""
from __future__ import annotations

from xcptool.a2l.types import Characteristic
from xcptool.session.api import A2LDatabase, DatasetImportResult, SkipReason
from xcptool.ui.hex_view import HexView


def _make_view(qtbot):
    import_calls = []
    generate_calls = []
    view = HexView(
        import_dataset_cb=lambda payload: import_calls.append(payload),
        generate_cb=lambda patches, out: generate_calls.append((patches, out)),
    )
    qtbot.addWidget(view)
    return view, import_calls, generate_calls


def test_constructs_with_two_tables_and_expected_columns(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    for table in (view.origin_table, view.mod_table):
        assert table.columnCount() == 5
        headers = [table.horizontalHeaderItem(i).text() for i in range(5)]
        assert headers == ["Address", "Name", "Size", "Bytes", "Value"]


def test_generate_button_disabled_until_both_a2l_and_hex_loaded(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    assert not view.generate_btn.isEnabled()

    view.set_database(A2LDatabase())
    assert not view.generate_btn.isEnabled()  # A2L loaded, hex not yet

    view.set_hex_loaded("C:/proj/golden.hex")
    assert view.generate_btn.isEnabled()  # both loaded now


def test_set_byte_order_updates_combo_selection(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    view.set_byte_order("big")
    assert view.byte_order_combo.currentText() == "Big Endian"
    view.set_byte_order("little")
    assert view.byte_order_combo.currentText() == "Little Endian"


def test_current_byte_order_reflects_manual_combo_change(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    view.byte_order_combo.setCurrentText("Big Endian")
    assert view.current_byte_order() == "big"
