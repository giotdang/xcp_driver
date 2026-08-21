"""D4e — MeasurementView: signal tree, pyqtgraph scope, DAQ start/stop wiring."""

from __future__ import annotations

import struct

import pytest
from PySide6.QtCore import Qt

from xcptool.a2l.types import A2LDatabase, Measurement
from xcptool.session.api import DaqList, DaqSignal, SamplePoint
from xcptool.session.fake import FakeBehavior, FakeSession, MEM_BASE
from xcptool.ui.measurement_view import COL_ADDR, COL_DTYPE, COL_NAME, COL_VALUE, MeasurementView


# ── fixture helpers ──────────────────────────────────────────────────────────

def _make_db() -> A2LDatabase:
    db = A2LDatabase()
    db.measurements["speed"] = Measurement(
        name="speed", description="Vận tốc xe",
        datatype="UWORD",           # A2L dùng UWORD, không phải UINT16
        address=MEM_BASE,
        lower_limit=0.0, upper_limit=300.0,
    )
    db.measurements["temp"] = Measurement(
        name="temp", description="Nhiệt độ động cơ",
        datatype="FLOAT32_IEEE",
        address=MEM_BASE + 4,
        lower_limit=-40.0, upper_limit=150.0,
    )
    return db


# Fixture: MeasurementView không parent, offscreen
@pytest.fixture
def view(qtbot) -> MeasurementView:
    v = MeasurementView()
    qtbot.addWidget(v)
    v.show()
    return v


# ── tree population ──────────────────────────────────────────────────────────

def test_set_database_populates_tree(view: MeasurementView) -> None:
    db = _make_db()
    view.set_database(db)
    assert view.tree.topLevelItemCount() == 2
    names = {
        view.tree.topLevelItem(i).text(COL_NAME)
        for i in range(view.tree.topLevelItemCount())
    }
    assert names == {"speed", "temp"}


def test_set_database_shows_measurement_count(view: MeasurementView) -> None:
    db = _make_db()
    view.set_database(db)
    assert "2 MEASUREMENT" in view.count_label.text()


def test_set_database_items_have_datatype(view: MeasurementView) -> None:
    db = _make_db()
    view.set_database(db)
    dtypes = {
        view.tree.topLevelItem(i).text(COL_DTYPE)
        for i in range(view.tree.topLevelItemCount())
    }
    assert "UINT16" in dtypes or "FLOAT32" in dtypes or "UWORD" in dtypes


def test_set_database_unchecked_by_default(view: MeasurementView) -> None:
    view.set_database(_make_db())
    for i in range(view.tree.topLevelItemCount()):
        assert view.tree.topLevelItem(i).checkState(COL_NAME) == Qt.Unchecked


# ── start / stop controls ────────────────────────────────────────────────────

def test_start_without_selection_shows_status(view: MeasurementView) -> None:
    view.set_database(_make_db())
    view.start_btn.click()
    assert "select" in view.status_label.text().lower() or \
           "signal" in view.status_label.text().lower()


def test_start_emits_daq_start_requested(qtbot, view: MeasurementView) -> None:
    view.set_database(_make_db())
    # check "speed"
    for i in range(view.tree.topLevelItemCount()):
        if view.tree.topLevelItem(i).text(COL_NAME) == "speed":
            view.tree.topLevelItem(i).setCheckState(COL_NAME, Qt.Checked)

    emitted: list[list[DaqList]] = []
    view.daq_start_requested.connect(emitted.append)
    view.start_btn.click()

    assert len(emitted) == 1
    lists = emitted[0]
    assert isinstance(lists, list)
    assert len(lists) == 1
    sigs = lists[0].signals
    assert any(s.name == "speed" for s in sigs)


def test_stop_emits_daq_stop_requested(qtbot, view: MeasurementView) -> None:
    # Giả lập DAQ đang chạy
    view.on_daq_started()

    emitted: list[object] = []
    view.daq_stop_requested.connect(lambda: emitted.append(True))
    view.stop_btn.click()
    assert emitted


def test_on_daq_started_updates_buttons(view: MeasurementView) -> None:
    view.on_daq_started()
    assert not view.start_btn.isEnabled()
    assert view.stop_btn.isEnabled()


def test_on_daq_stopped_updates_buttons(view: MeasurementView) -> None:
    view.on_daq_started()
    view.on_daq_stopped()
    assert view.start_btn.isEnabled()
    assert not view.stop_btn.isEnabled()


# ── on_samples ───────────────────────────────────────────────────────────────

def test_on_samples_with_no_curves_is_safe(view: MeasurementView) -> None:
    """on_samples không crash khi chưa có curves (chưa start DAQ)."""
    sp = SamplePoint(name="x", timestamp_ns=1_000_000, value_raw=b"\x01\x00", datatype="UINT16")
    view.on_samples([sp])   # không raise


def test_on_samples_stores_decoded_data(qtbot, view: MeasurementView) -> None:
    """on_samples decode bytes thành float và điền vào buffer."""
    db = _make_db()
    view.set_database(db)
    # Chọn "speed" và setup curves thủ công qua _on_start flow
    for i in range(view.tree.topLevelItemCount()):
        if view.tree.topLevelItem(i).text(COL_NAME) == "speed":
            view.tree.topLevelItem(i).setCheckState(COL_NAME, Qt.Checked)

    captured: list = []
    def _capture(lists):
        captured.append(lists)
    view.daq_start_requested.connect(_capture)
    view.start_btn.click()   # triggers _setup_curves + emit

    assert captured, "start_btn.click() không emit daq_start_requested"

    # Gửi sample — UWORD = unsigned 16-bit
    raw = struct.pack("<H", 1234)
    sp = SamplePoint(name="speed", timestamp_ns=500_000, value_raw=raw, datatype="UWORD")
    view.on_daq_started()
    view.on_samples([sp])

    # Sau Fix 1: buffer tách thành _xs / _ys riêng thay vì _data[deque[tuple]]
    xs_buf = view._xs.get("speed")
    ys_buf = view._ys.get("speed")
    assert xs_buf is not None and len(xs_buf) > 0, "_xs buffer trống"
    assert ys_buf is not None and len(ys_buf) > 0, "_ys buffer trống"
    assert abs(ys_buf[-1] - 1234.0) < 1e-3


def test_start_emits_daq_start_requested_for_array(qtbot, view: MeasurementView) -> None:
    """Kiểm tra MEASUREMENT dạng array (MATRIX_DIM) được tự động tách thành N DaqSignal."""
    db = A2LDatabase()
    db.measurements["torqueSamples"] = Measurement(
        name="torqueSamples",
        description="Torque samples array",
        datatype="FLOAT32_IEEE",
        address=MEM_BASE + 0x1C,
        lower_limit=0.0,
        upper_limit=100.0,
        matrix_dim=[4],
    )
    view.set_database(db)

    # Check torqueSamples
    item = view.tree.topLevelItem(0)
    assert item.text(COL_NAME) == "torqueSamples"
    item.setCheckState(COL_NAME, Qt.Checked)

    emitted: list[list[DaqList]] = []
    view.daq_start_requested.connect(emitted.append)
    view.start_btn.click()

    assert len(emitted) == 1
    sigs = emitted[0][0].signals
    assert len(sigs) == 4
    for i in range(4):
        assert sigs[i].name == f"torqueSamples[{i}]"
        assert sigs[i].address == (MEM_BASE + 0x1C) + i * 4
        assert sigs[i].size == 4
        assert sigs[i].datatype == "FLOAT32_IEEE"


def test_on_samples_updates_live_value_in_tree(view: MeasurementView) -> None:
    """on_samples cập nhật giá trị hiển thị cột Giá trị trực tiếp trên Tree."""
    db = _make_db()
    view.set_database(db)

    item = view._tree_items.get("speed")
    assert item is not None
    assert item.text(COL_VALUE) == "-"

    raw = struct.pack("<H", 85)
    sp = SamplePoint(name="speed", timestamp_ns=1000, value_raw=raw, datatype="UWORD")
    view.on_samples([sp])

    assert "85" in item.text(COL_VALUE)


def test_scope_toggle_hides_plot_and_skips_curve_data(view: MeasurementView) -> None:
    """Khi tắt scope switch, đồ thị ẩn đi và on_samples không nạp điểm vào curve."""
    db = _make_db()
    view.set_database(db)
    view.start_btn.click()

    # Tắt scope switch
    view.scope_switch.setChecked(False)
    assert not view._plot.isVisible()

    raw = struct.pack("<H", 100)
    sp = SamplePoint(name="speed", timestamp_ns=1000, value_raw=raw, datatype="UWORD")
    view.on_samples([sp])

    # Tree vẫn được cập nhật live value
    item = view._tree_items.get("speed")
    assert item is not None
    assert "100" in item.text(COL_VALUE)

    # Nhưng curve không nạp thêm điểm
    assert len(view._xs.get("speed", [])) == 0


def test_set_database_groups_struct_measurements(view: MeasurementView) -> None:
    """Kiểm tra MEASUREMENT dạng struct (speedPidTelemetry_*) được gom nhóm thành parent-child."""
    db = A2LDatabase()
    db.measurements["speedPidTelemetry_error"] = Measurement(
        name="speedPidTelemetry_error",
        description="PID Error",
        datatype="FLOAT32_IEEE",
        address=MEM_BASE + 0x10,
        lower_limit=-100.0,
        upper_limit=100.0,
    )
    db.measurements["speedPidTelemetry_integral"] = Measurement(
        name="speedPidTelemetry_integral",
        description="PID Integral",
        datatype="FLOAT32_IEEE",
        address=MEM_BASE + 0x14,
        lower_limit=-100.0,
        upper_limit=100.0,
    )
    db.measurements["speedPidTelemetry_output"] = Measurement(
        name="speedPidTelemetry_output",
        description="PID Output",
        datatype="FLOAT32_IEEE",
        address=MEM_BASE + 0x18,
        lower_limit=-100.0,
        upper_limit=100.0,
    )
    view.set_database(db)

    # Cây chỉ có 1 top-level item là struct parent
    assert view.tree.topLevelItemCount() == 1
    parent = view.tree.topLevelItem(0)
    assert parent.text(COL_NAME) == "speedPidTelemetry"
    assert "STRUCT" in parent.text(COL_DTYPE)
    assert parent.childCount() == 3

    # Các trường con không có Checkbox
    for i in range(3):
        child = parent.child(i)
        assert child.checkState(COL_NAME) == Qt.Unchecked or child.data(COL_NAME, Qt.CheckStateRole) is None

    # Khi tick dòng cha -> _build_daq_lists sinh ra cả 3 signals
    parent.setCheckState(COL_NAME, Qt.Checked)
    emitted: list[list[DaqList]] = []
    view.daq_start_requested.connect(emitted.append)
    view.start_btn.click()

    assert len(emitted) == 1
    sigs = emitted[0][0].signals
    assert len(sigs) == 3
    assert {s.name for s in sigs} == {
        "speedPidTelemetry_error",
        "speedPidTelemetry_integral",
        "speedPidTelemetry_output",
    }


def test_radix_change_updates_float_and_int_live_values(view: MeasurementView) -> None:
    """Kiểm tra thay đổi Radix (HEX/BIN) lập tức cập nhật lại hiển thị cả kiểu FLOAT và INT."""
    db = _make_db()
    view.set_database(db)

    # Nạp mẫu đo cho speed (int) và temp (float)
    raw_int = struct.pack("<H", 0x1234)
    raw_float = struct.pack("<f", 1.0)
    sp_int = SamplePoint(name="speed", timestamp_ns=1000, value_raw=raw_int, datatype="UWORD")
    sp_float = SamplePoint(name="temp", timestamp_ns=1000, value_raw=raw_float, datatype="FLOAT32_IEEE")

    view.on_samples([sp_int, sp_float])

    # Đổi sang HEX
    view.radix_combo.setCurrentText("HEX")
    item_int = view._tree_items["speed"]
    item_float = view._tree_items["temp"]
    assert item_int.text(COL_VALUE) == "0x1234"
    assert item_float.text(COL_VALUE) == "0x3F800000"

    # Đổi sang BIN
    view.radix_combo.setCurrentText("BIN")
    assert item_float.text(COL_VALUE) == "0b00111111100000000000000000000000"





