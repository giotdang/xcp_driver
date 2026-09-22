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


def test_on_regions_ready_populates_origin_table(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    char = Characteristic(
        name="kp", description="", char_type="VALUE", address=0x1000,
        record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE",
    )
    db = A2LDatabase()
    db.characteristics["kp"] = char
    view.set_database(db)

    view.on_regions_ready({"kp": b"\x2A"})

    assert view.origin_table.rowCount() == 1
    assert view.origin_table.item(0, 0).text() == "0x00001000"
    assert view.origin_table.item(0, 1).text() == "kp"
    assert view.origin_table.item(0, 3).text() == "2A"
    assert view.origin_table.item(0, 4).text() == "42"


def test_on_regions_ready_shows_not_in_file_for_missing_address(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    char = Characteristic(
        name="kp", description="", char_type="VALUE", address=0x1000,
        record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE",
    )
    db = A2LDatabase()
    db.characteristics["kp"] = char
    view.set_database(db)

    view.on_regions_ready({"kp": None})

    assert view.origin_table.item(0, 3).text() == "— (not in file)"
    assert view.origin_table.item(0, 4).text() == "— (not in file)"


def test_generate_clicked_opens_dataset_file_dialog_and_calls_import_cb(qtbot, monkeypatch) -> None:
    view, import_calls, _ = _make_view(qtbot)
    db = A2LDatabase()
    view.set_database(db)
    view.set_hex_loaded("golden.hex")

    monkeypatch.setattr(
        "xcptool.ui.hex_view.QFileDialog.getOpenFileName",
        lambda *a, **k: ("dataset.json", ""),
    )
    monkeypatch.setattr(
        "xcptool.ui.hex_view.Path.read_text",
        lambda self, encoding="utf-8": '{"format_version": 1, "values": {"kp": "5"}}',
    )

    view.generate_btn.click()

    assert len(import_calls) == 1
    assert import_calls[0] == {"format_version": 1, "values": {"kp": "5"}}


def test_generate_clicked_cancel_dialog_does_not_call_import_cb(qtbot, monkeypatch) -> None:
    view, import_calls, _ = _make_view(qtbot)
    view.set_database(A2LDatabase())
    view.set_hex_loaded("golden.hex")
    monkeypatch.setattr(
        "xcptool.ui.hex_view.QFileDialog.getOpenFileName", lambda *a, **k: ("", "")
    )

    view.generate_btn.click()

    assert import_calls == []


def test_on_dataset_validated_builds_patches_from_matched_values(qtbot) -> None:
    # Task 11 scope: on_dataset_validated() computes _pending_patches and
    # stops (status label only) — Task 12 adds the save dialog + generate_cb
    # call after this same point, so this test predates that behavior.
    view, _, _ = _make_view(qtbot)
    char = Characteristic(
        name="kp", description="", char_type="VALUE", address=0x1000,
        record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE",
    )
    db = A2LDatabase()
    db.characteristics["kp"] = char
    view.set_database(db)

    result = DatasetImportResult(matched={"kp": "42"}, skipped=[], a2l_mismatch_warning=None)
    view.on_dataset_validated(result)

    assert view._pending_patches == [(0x1000, b"\x2A", "kp")]


def test_on_dataset_validated_empty_matched_shows_status_no_patches(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    view.set_database(A2LDatabase())

    result = DatasetImportResult(
        matched={}, skipped=[SkipReason(name="x", reason="not found in A2L")],
        a2l_mismatch_warning=None,
    )
    view.on_dataset_validated(result)

    assert view._pending_patches == []
    assert "0" in view.status_label.text() or "no" in view.status_label.text().lower()
