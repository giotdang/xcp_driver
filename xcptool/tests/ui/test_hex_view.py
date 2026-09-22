"""HexView widget tests — headless via pytest-qt, mirrors the fixture
pattern already used in tests/ui/test_calibration_view.py."""
from __future__ import annotations

from xcptool.a2l.types import Characteristic
from xcptool.session.api import A2LDatabase, DatasetImportResult, SkipReason
from xcptool.ui.hex_raw_model import HexRawTableModel
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


def test_on_dataset_validated_builds_patches_from_matched_values(qtbot, monkeypatch) -> None:
    # Since Task 12, on_dataset_validated() opens a save dialog right after
    # computing _pending_patches — QFileDialog.getSaveFileName hangs under
    # the offscreen QPA platform without a mock (confirmed empirically while
    # implementing Task 12), so every test reaching this point must patch it.
    # Cancelling it here isolates this test to just the patch-building step.
    monkeypatch.setattr("xcptool.ui.hex_view.QFileDialog.getSaveFileName", lambda *a, **k: ("", ""))
    view, _, generate_calls = _make_view(qtbot)
    char = Characteristic(
        name="kp", description="", char_type="VALUE", address=0x1000,
        record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE",
    )
    db = A2LDatabase()
    db.characteristics["kp"] = char
    view.set_database(db)
    view.set_hex_loaded("C:/proj/golden.hex")

    result = DatasetImportResult(matched={"kp": "42"}, skipped=[], a2l_mismatch_warning=None)
    view.on_dataset_validated(result)

    assert view._pending_patches == [(0x1000, b"\x2A", "kp")]
    assert generate_calls == []  # dialog was cancelled, generate_cb never called


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


def test_on_dataset_validated_opens_prefilled_save_dialog_and_calls_generate_cb(qtbot, monkeypatch) -> None:
    view, _, generate_calls = _make_view(qtbot)
    char = Characteristic(
        name="kp", description="", char_type="VALUE", address=0x1000,
        record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE",
    )
    db = A2LDatabase()
    db.characteristics["kp"] = char
    view.set_database(db)
    view.set_hex_loaded("C:/proj/golden.hex")

    captured_default = {}

    def fake_save_dialog(parent, title, default_path, filt):
        captured_default["path"] = default_path
        return ("C:/proj/golden_mod.hex", "")

    monkeypatch.setattr("xcptool.ui.hex_view.QFileDialog.getSaveFileName", fake_save_dialog)

    result = DatasetImportResult(matched={"kp": "42"}, skipped=[], a2l_mismatch_warning=None)
    view.on_dataset_validated(result)

    assert "golden_mod.hex" in captured_default["path"]
    assert len(generate_calls) == 1
    patches, out_path = generate_calls[0]
    assert patches == [(0x1000, b"\x2A", "kp")]
    assert out_path == "C:/proj/golden_mod.hex"


def test_on_dataset_validated_cancel_save_dialog_does_not_call_generate_cb(qtbot, monkeypatch) -> None:
    view, _, generate_calls = _make_view(qtbot)
    char = Characteristic(
        name="kp", description="", char_type="VALUE", address=0x1000,
        record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE",
    )
    db = A2LDatabase()
    db.characteristics["kp"] = char
    view.set_database(db)
    view.set_hex_loaded("C:/proj/golden.hex")
    monkeypatch.setattr("xcptool.ui.hex_view.QFileDialog.getSaveFileName", lambda *a, **k: ("", ""))

    result = DatasetImportResult(matched={"kp": "42"}, skipped=[], a2l_mismatch_warning=None)
    view.on_dataset_validated(result)

    assert generate_calls == []


def test_on_generate_done_populates_mod_table_with_patched_and_unchanged_values(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    kp = Characteristic(name="kp", description="", char_type="VALUE", address=0x1000,
                         record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE")
    ki = Characteristic(name="ki", description="", char_type="VALUE", address=0x1001,
                         record_layout="", lower_limit=0.0, upper_limit=10.0, datatype="UBYTE")
    db = A2LDatabase()
    db.characteristics.update({"kp": kp, "ki": ki})
    view.set_database(db)
    view.on_regions_ready({"kp": b"\x01", "ki": b"\x02"})
    view._pending_patches = [(0x1000, b"\x2A", "kp")]

    view.on_generate_done("C:/proj/golden_mod.hex")

    assert view.mod_table.rowCount() == 2
    rows = {view.mod_table.item(r, 1).text(): r for r in range(view.mod_table.rowCount())}
    assert view.mod_table.item(rows["kp"], 3).text() == "2A"   # patched
    assert view.mod_table.item(rows["ki"], 3).text() == "02"   # unchanged, mirrors origin

    from xcptool.ui.hex_view import _DIFF_BRUSH
    assert view.mod_table.item(rows["kp"], 0).background().color() == _DIFF_BRUSH.color()
    assert view.mod_table.item(rows["ki"], 0).background().color() != _DIFF_BRUSH.color()
    assert "golden_mod.hex" in view.status_label.text()


def test_on_generate_error_shows_critical_dialog_leaves_mod_table_unchanged(qtbot, monkeypatch) -> None:
    view, _, _ = _make_view(qtbot)
    view.set_database(A2LDatabase())
    view.mod_table.setRowCount(0)

    shown = {}
    monkeypatch.setattr(
        "xcptool.ui.hex_view.QMessageBox.critical",
        lambda parent, title, text: shown.update(title=title, text=text),
    )

    view.on_generate_error(Exception("Address(es) not found in golden.hex: kp (0x00001000, 1 byte(s))"))

    assert shown["text"]
    assert view.mod_table.rowCount() == 0


def test_on_dataset_validated_builds_one_patch_for_a_whole_val_blk_array(qtbot, monkeypatch) -> None:
    """Regression: a dataset entry keyed by an array's bare name (e.g.
    "adcCalPoints": "1, 2, 4, 5" — exactly how a2l/dataset.py exports a
    VAL_BLK) must resolve to one patch covering the whole array, not be
    silently dropped because by-name lookup only knew per-element names.
    """
    monkeypatch.setattr("xcptool.ui.hex_view.QFileDialog.getSaveFileName", lambda *a, **k: ("", ""))
    view, _, _ = _make_view(qtbot)
    char = Characteristic(
        name="adcCalPoints", description="", char_type="VAL_BLK", address=0x2000,
        record_layout="", lower_limit=0.0, upper_limit=4095.0,
        datatype="UWORD", array_size=4,
    )
    db = A2LDatabase()
    db.characteristics["adcCalPoints"] = char
    view.set_database(db)
    view.set_hex_loaded("C:/proj/golden.hex")

    result = DatasetImportResult(
        matched={"adcCalPoints": "1, 2, 4, 5"}, skipped=[], a2l_mismatch_warning=None,
    )
    view.on_dataset_validated(result)

    assert view._pending_patches == [
        (0x2000, b"\x01\x00\x02\x00\x04\x00\x05\x00", "adcCalPoints"),
    ]


def test_raw_tab_exists_alongside_calibration_tab(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    assert isinstance(view.raw_origin_model, HexRawTableModel)
    assert isinstance(view.raw_mod_model, HexRawTableModel)
    assert view.raw_origin_view.model() is view.raw_origin_model
    assert view.raw_mod_view.model() is view.raw_mod_model


def test_on_raw_origin_ready_populates_the_raw_origin_model(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    view.on_raw_origin_ready([(0x100, b"\x01\x02"), (0x200, b"\x03\x04")])

    assert view.raw_origin_model.rowCount() == 2
    assert view.raw_origin_model.data(view.raw_origin_model.index(0, 1)) == "0102"


def test_on_raw_mod_ready_populates_and_highlights_only_changed_rows(qtbot) -> None:
    view, _, _ = _make_view(qtbot)
    view.on_raw_origin_ready([(0x100, b"\x01\x02"), (0x200, b"\x03\x04")])
    view.on_raw_mod_ready([(0x100, b"\xAA\xBB"), (0x200, b"\x03\x04")])

    from PySide6.QtCore import Qt
    model = view.raw_mod_model
    assert model.data(model.index(0, 0), Qt.BackgroundRole) is not None  # 0x100 changed
    assert model.data(model.index(1, 0), Qt.BackgroundRole) is None      # 0x200 unchanged
