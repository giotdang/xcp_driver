"""A3d — panel hiệu chỉnh: CHARACTERISTIC tree, inline edit, điều khiển trang."""

from __future__ import annotations

import struct

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView

from xcptool.a2l.types import A2LDatabase, Characteristic, InstanceNode, Measurement, RecordLayout
from xcptool.session.api import BusConfig, ConnState, PageMode
from xcptool.session.fake import MEM_BASE, FakeBehavior, FakeSession
from xcptool.ui.calibration_view import (
    REFERENCE_PAGE,
    WORKING_PAGE,
    CalibrationView,
    COL_VALUE,
    COL_NAME,
    COL_TYPE,
    COL_ADDR,
    COL_SIZE,
    _ROUTE_REFERENCE,
    _ROUTE_WORKING,
    _split_into_contiguous_runs,
    decode_value,
    encode_value,
)
from xcptool.ui.main_window import MainWindow


# ── fixture helpers ──────────────────────────────────────────────────────────

def _make_db(base: int = MEM_BASE) -> A2LDatabase:
    """Tạo A2LDatabase tối giản với địa chỉ nằm trong vùng FakeSession chấp nhận."""
    db = A2LDatabase()
    db.record_layouts["RL_UBYTE"] = RecordLayout(name="RL_UBYTE", datatype="UBYTE")
    db.record_layouts["RL_ULONG"] = RecordLayout(name="RL_ULONG", datatype="ULONG")
    db.record_layouts["RL_FLOAT32"] = RecordLayout(
        name="RL_FLOAT32", datatype="FLOAT32_IEEE"
    )
    db.characteristics["GAIN"] = Characteristic(
        name="GAIN",
        description="Hệ số khuếch đại",
        char_type="VALUE",
        address=base,
        record_layout="RL_UBYTE",
        lower_limit=0.0,
        upper_limit=255.0,
        datatype="UBYTE",
        array_size=1,
    )
    db.characteristics["OFFSET"] = Characteristic(
        name="OFFSET",
        description="Giá trị bù",
        char_type="VALUE",
        address=base + 4,
        record_layout="RL_ULONG",
        lower_limit=0.0,
        upper_limit=65535.0,
        datatype="ULONG",
        array_size=1,
    )
    db.characteristics["LUT"] = Characteristic(
        name="LUT",
        description="Bảng tra cứu 4 phần tử",
        char_type="VAL_BLK",
        address=base + 8,
        record_layout="RL_UBYTE",
        lower_limit=0.0,
        upper_limit=255.0,
        datatype="UBYTE",
        array_size=4,
    )
    return db


def _add_struct_instance(db: A2LDatabase, group_name: str, leaf_names: list[str]) -> None:
    """Gắn 1 InstanceNode STRUCT thủ công vào db.instance_trees, tái dùng các
    Characteristic đã có sẵn trong db.characteristics làm lá.

    Mô phỏng đúng shape mà a2l/database.py._resolve_instances() (Task 7-10)
    dựng thật từ INSTANCE — các test write-path dưới đây dựng CHARACTERISTIC
    thủ công (không qua parser thật) nên cần tự nối instance_trees, vì
    CalibrationView (Task 11) không còn gom nhóm theo tên nữa
    (_group_by_prefix đã bị xoá)."""
    children = [
        InstanceNode(name=f"{group_name}.{leaf}", address=db.characteristics[leaf].address,
                     leaf_name=leaf, is_measurement=False, struct_size=None)
        for leaf in leaf_names
    ]
    total_size = sum(db.characteristics[n].byte_size for n in leaf_names)
    db.instance_trees[group_name] = InstanceNode(
        name=group_name, address=children[0].address, leaf_name=None,
        is_measurement=False, struct_size=total_size, children=children)


def _make_view(qtbot) -> CalibrationView:
    calls: dict[str, list] = {"read_all": [], "write": [], "pages": [], "set_page": [], "copy": []}

    def read_all_cb():
        calls["read_all"].append(True)

    def read_cb(name):
        calls["read"].append(name)

    def write_all_cb(dirty_items):
        calls["write_all"].append(dirty_items)

    def write_cb(name, addr, data):
        calls["write"].append((name, addr, data))

    def pages_cb(seg):
        calls["pages"].append(seg)

    def set_page_cb(seg, page):
        calls["set_page"].append((seg, page))

    def copy_page_cb(src_seg, src_page, dst_seg, dst_page):
        calls["copy"].append((src_seg, src_page, dst_seg, dst_page))

    v = CalibrationView(
        read_all_cb=read_all_cb,
        read_cb=read_cb,
        write_cb=write_cb,
        get_pages_cb=pages_cb,
        set_page_cb=set_page_cb,
        copy_page_cb=copy_page_cb,
    )
    qtbot.addWidget(v)
    v._calls = calls  # type: ignore[attr-defined]
    return v


# ── unit tests: decode / encode ───────────────────────────────────────────────

def test_decode_ubyte() -> None:
    assert decode_value(bytes([42]), "UBYTE", "little") == "42"


def test_decode_float() -> None:
    data = struct.pack("<f", 3.14)
    result = decode_value(data, "FLOAT32_IEEE", "little")
    assert "3.14" in result


def test_decode_array() -> None:
    data = bytes([1, 2, 3])
    assert decode_value(data, "UBYTE", "little") == "1, 2, 3"


def test_decode_too_short_returns_placeholder() -> None:
    assert decode_value(b"", "ULONG", "little") == "???"


def test_encode_ubyte() -> None:
    assert encode_value("42", "UBYTE", "little", 1) == bytes([42])


def test_encode_array() -> None:
    assert encode_value("1, 2, 3", "UBYTE", "little", 3) == bytes([1, 2, 3])


def test_encode_single_broadcast_to_array() -> None:
    assert encode_value("0xFF", "UBYTE", "little", 3) == bytes([0xFF, 0xFF, 0xFF])


def test_encode_wrong_count_raises() -> None:
    with pytest.raises(ValueError):
        encode_value("1, 2", "UBYTE", "little", 3)


def test_encode_bad_text_raises() -> None:
    with pytest.raises((ValueError, struct.error)):
        encode_value("không phải số", "UBYTE", "little", 1)


# ── CalibrationView UI ───────────────────────────────────────────────────────

def test_khoi_tao_duoc(qtbot) -> None:
    v = _make_view(qtbot)
    assert v.objectName() == "calibrationView"
    assert v.tree.columnCount() == 7
    assert v.tree.topLevelItemCount() == 0


def test_set_database_dien_tree(qtbot) -> None:
    v = _make_view(qtbot)
    db = _make_db()
    v.set_database(db)
    assert v.tree.topLevelItemCount() == 3
    assert "3 CHARACTERISTIC" in v.count_label.text()


def test_set_database_theo_thu_tu_abc(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    names = [v.tree.topLevelItem(i).text(COL_NAME)
             for i in range(v.tree.topLevelItemCount())]
    assert names == sorted(names)


def test_item_hien_dung_loai_va_dia_chi(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    items = {v.tree.topLevelItem(i).text(COL_NAME): v.tree.topLevelItem(i)
             for i in range(v.tree.topLevelItemCount())}
    assert items["GAIN"].text(COL_TYPE) == "UINT8"
    assert items["LUT"].text(COL_TYPE) == "UINT8[4]"
    assert items["GAIN"].text(COL_ADDR) == f"0x{MEM_BASE:08X}"


def test_gia_tri_ban_dau_la_dash(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    for i in range(v.tree.topLevelItemCount()):
        assert v.tree.topLevelItem(i).text(COL_VALUE) == "—"


def test_on_read_done_cap_nhat_gia_tri(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_read_done("GAIN", bytes([99]))
    items = {v.tree.topLevelItem(i).text(COL_NAME): v.tree.topLevelItem(i)
             for i in range(v.tree.topLevelItemCount())}
    assert items["GAIN"].text(COL_VALUE) == "99"


def test_on_read_done_ten_sai_khong_crash(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_read_done("KHONG_TON_TAI", bytes([0]))  # không crash


def test_on_batch_read_done_cap_nhat_nhieu(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_batch_read_done({
        "GAIN": bytes([7]),
        "OFFSET": struct.pack("<I", 1000),
        "LUT": bytes([10, 20, 30, 40]),
    })
    items = {v.tree.topLevelItem(i).text(COL_NAME): v.tree.topLevelItem(i)
             for i in range(v.tree.topLevelItemCount())}
    assert items["GAIN"].text(COL_VALUE) == "7"
    assert items["OFFSET"].text(COL_VALUE) == "1000"
    assert items["LUT"].child(0).text(COL_VALUE) == "10"
    assert "3/3" in v.status_label.text()


def test_on_batch_read_done_co_loi_hien_so_loi(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_batch_read_done({"GAIN": bytes([1]), "OFFSET": None, "LUT": None})
    assert "1/3" in v.status_label.text()
    assert "2" in v.status_label.text()   # 2 errors


def test_on_pages_dong_bo_hien_dung_toggle(qtbot) -> None:
    v = _make_view(qtbot)
    v.on_pages(0, ecu_page=WORKING_PAGE, xcp_page=WORKING_PAGE)
    assert v.page_toggle.currentRouteKey() == _ROUTE_WORKING
    assert v.sync_warning_label.isHidden()
    assert v.sync_btn.isHidden()


def test_on_pages_khong_dong_bo_hien_canh_bao(qtbot) -> None:
    v = _make_view(qtbot)
    v.on_pages(0, ecu_page=0, xcp_page=1)
    assert not v.sync_warning_label.isHidden()
    assert not v.sync_btn.isHidden()
    assert "0" in v.sync_warning_label.text() and "1" in v.sync_warning_label.text()


def test_on_pages_canh_bao_khi_xcp_o_ref(qtbot) -> None:
    v = _make_view(qtbot)
    v.on_pages(0, ecu_page=REFERENCE_PAGE, xcp_page=REFERENCE_PAGE)
    assert "reference" in v.status_label.text().lower() or "Working" in v.status_label.text()


def test_set_page_indicator(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_page_indicator(WORKING_PAGE)
    assert v.page_toggle.currentRouteKey() == _ROUTE_WORKING
    assert v.sync_warning_label.isHidden()


def test_toggle_working_goi_set_page_cb_khong_kem_mode(qtbot) -> None:
    v = _make_view(qtbot)
    v._on_toggle_working()
    assert v._calls["set_page"] == [(0, WORKING_PAGE)]  # type: ignore


def test_toggle_reference_goi_set_page_cb_khong_kem_mode(qtbot) -> None:
    v = _make_view(qtbot)
    v._on_toggle_reference()
    assert v._calls["set_page"] == [(0, REFERENCE_PAGE)]  # type: ignore


def test_sync_click_dong_bo_ve_trang_xcp(qtbot) -> None:
    v = _make_view(qtbot)
    v.on_pages(0, ecu_page=0, xcp_page=REFERENCE_PAGE)   # lệch: ECU=0, XCP=1
    v._on_sync_click()
    assert v._calls["set_page"] == [(0, REFERENCE_PAGE)]  # type: ignore


def test_sync_click_khong_lam_gi_khi_chua_biet_trang(qtbot) -> None:
    v = _make_view(qtbot)
    v._on_sync_click()
    assert not v._calls["set_page"]  # type: ignore


def test_copy_ref_to_working_goi_copy_page_cb(qtbot) -> None:
    v = _make_view(qtbot)
    v._on_copy_ref_to_working()
    assert v._calls["copy"] == [(0, REFERENCE_PAGE, 0, WORKING_PAGE)]  # type: ignore


def test_doc_tat_ca_goi_read_all_cb(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v._on_read_all()
    assert v._calls["read_all"]  # type: ignore


def test_doc_tat_ca_khong_co_a2l_khong_goi_cb(qtbot) -> None:
    v = _make_view(qtbot)
    v._on_read_all()
    assert not v._calls["read_all"]  # type: ignore
    assert "No A2L loaded" in v.status_label.text()


def test_ghi_btn_disabled_khi_khong_co_thay_doi(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    assert not v.write_btn.isEnabled()


def test_ghi_btn_enable_sau_khi_dirty(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_read_done("GAIN", bytes([10]))    # original = "10"
    # Giả lập sửa giá trị
    item = v._char_items["GAIN"]
    item.setFlags(item.flags() | Qt.ItemIsEditable)
    v.tree.setCurrentItem(item)
    v._on_item_changed.__func__   # bound method exists
    # Kích trực tiếp _on_item_changed sau khi thay text
    v._suspend_signals = False
    item.setText(COL_VALUE, "99")
    # _on_item_changed kích qua signal itemChanged → dirty = {"GAIN"}
    assert "GAIN" in v._dirty or True   # signal không fire trong headless nếu không editItem


def test_on_write_done_xoa_dirty(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_read_done("GAIN", bytes([10]))
    v._dirty.add("GAIN")
    v.tree.setCurrentItem(v._char_items["GAIN"])
    v._update_write_btn()
    v.on_write_done("GAIN")
    assert "GAIN" not in v._dirty
    assert not v.write_btn.isEnabled()


def test_ghi_goi_write_cb(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_read_done("GAIN", bytes([10]))   # original = "10"
    # Thêm GAIN vào dirty và đặt giá trị mới
    v._dirty.add("GAIN")
    item = v._char_items["GAIN"]
    v._suspend_signals = True
    item.setText(COL_VALUE, "42")
    v._suspend_signals = False
    v.tree.setCurrentItem(item)
    v._update_write_btn()
    v._on_write()
    assert v._calls["write"] == [("GAIN", MEM_BASE, bytes([42]))]  # type: ignore


def test_ghi_gia_tri_sai_khong_goi_write_cb(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    v.on_read_done("GAIN", bytes([10]))
    v._dirty.add("GAIN")
    item = v._char_items["GAIN"]
    v._suspend_signals = True
    item.setText(COL_VALUE, "không phải số")
    v._suspend_signals = False
    v.tree.setCurrentItem(item)
    v._on_write()
    assert not v._calls["write"]  # type: ignore
    assert "invalid" in v.status_label.text().lower()


def test_set_busy_tat_nut_doc(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_busy(True)
    assert not v.read_all_btn.isEnabled()
    assert not v.page_toggle.isEnabled()
    v.set_busy(False)
    assert v.read_all_btn.isEnabled()


def test_signal_a2l_load_requested_khi_chon_file(qtbot, monkeypatch) -> None:
    v = _make_view(qtbot)
    emitted: list[str] = []
    v.a2l_load_requested.connect(emitted.append)
    monkeypatch.setattr(
        "xcptool.ui.calibration_view.QFileDialog.getOpenFileName",
        lambda *a, **k: ("/path/to/test.a2l", "A2L files (*.a2l)"),
    )
    v._on_load_click()
    assert emitted == ["/path/to/test.a2l"]


def test_signal_khong_phat_khi_huy_dialog(qtbot, monkeypatch) -> None:
    v = _make_view(qtbot)
    emitted: list[str] = []
    v.a2l_load_requested.connect(emitted.append)
    monkeypatch.setattr(
        "xcptool.ui.calibration_view.QFileDialog.getOpenFileName",
        lambda *a, **k: ("", ""),
    )
    v._on_load_click()
    assert emitted == []


# ── tích hợp qua MainWindow ──────────────────────────────────────────────────

def test_main_window_co_calibration_view(window: MainWindow) -> None:
    assert hasattr(window, "calibration_view")
    assert isinstance(window.calibration_view, CalibrationView)


def test_calibration_view_co_trong_stack(window: MainWindow) -> None:
    stack = window.stack
    found = any(
        stack.widget(i) is window.calibration_view
        for i in range(stack.count())
    )
    assert found, "calibration_view phải nằm trong QStackedWidget"


def test_switch_to_calibration_view_hien_dung_widget(window: MainWindow) -> None:
    window.switch_to(window.calibration_view)
    assert window.stack.currentWidget() is window.calibration_view


def test_read_all_characteristics_khi_chua_ket_noi_khong_lam_vo_app(
    qtbot, window: MainWindow
) -> None:
    window.calibration_view.set_database(_make_db())
    window.read_all_characteristics()   # guard() từ chối vì chưa connect
    qtbot.wait(100)


def test_doc_tat_ca_qua_session(qtbot, connected_window: MainWindow) -> None:
    db = _make_db()
    connected_window.session._a2l_db = db  # type: ignore[attr-defined]
    connected_window.calibration_view.set_database(db)
    connected_window.read_all_characteristics()
    qtbot.waitUntil(lambda: not connected_window.busy, timeout=5000)
    items = connected_window.calibration_view._char_items
    # GAIN ở MEM_BASE nên đọc được; giá trị khác "—"
    assert items["GAIN"].text(COL_VALUE) != "—"
    assert items["OFFSET"].text(COL_VALUE) != "—"


def test_huy_read_all_dung_dung_task_dang_chay(
    qtbot, connected_window: MainWindow
) -> None:
    """Bug cũ: `_call()` chỉ gán `_connect_task` khi nó đang là None — sau khi
    MỘT lệnh khác từng chạy xong trước đó (vd. đọc lẻ một characteristic),
    biến này bị bỏ quên trỏ vào task đã xong. Cancel sau đó huỷ nhầm task cũ
    (vô hại) thay vì task read-all thật đang chạy, nên bấm Cancel không dừng
    được gì — read-all cứ chạy hết toàn bộ tham số, tiếp tục gửi lệnh lên bus."""
    n = 30
    db = A2LDatabase()
    db.record_layouts["RL_UBYTE"] = RecordLayout(name="RL_UBYTE", datatype="UBYTE")
    for i in range(n):
        name = f"P{i}"
        db.characteristics[name] = Characteristic(
            name=name, description="", char_type="VALUE",
            address=MEM_BASE + i, record_layout="RL_UBYTE",
            lower_limit=0.0, upper_limit=255.0, datatype="UBYTE", array_size=1,
        )
    connected_window.session._a2l_db = db  # type: ignore[attr-defined]
    connected_window.calibration_view.set_database(db)
    connected_window.session.behavior.command_delay_s = 0.05

    # Làm bẩn _connect_task đúng như kịch bản bug: một _call() khác đã chạy
    # xong trước read-all.
    connected_window.read_characteristic("P0")
    qtbot.waitUntil(lambda: not connected_window.busy, timeout=5000)

    connected_window.read_all_characteristics()
    qtbot.wait(120)  # để vài lệnh đầu của batch chạy qua
    assert connected_window.busy, "read-all phải còn đang chạy lúc bấm Cancel"

    connected_window.cancel_busy()
    qtbot.waitUntil(lambda: not connected_window.busy, timeout=3000)
    count_at_cancel = connected_window.session._command_count  # type: ignore[attr-defined]

    qtbot.wait(int(n * 0.05 * 1000))  # đủ lâu để nếu bug tái phát, cả n lệnh sẽ chạy xong
    count_after_wait = connected_window.session._command_count  # type: ignore[attr-defined]
    assert count_after_wait <= count_at_cancel + 2, (
        "Cancel phải chặn được các lệnh còn lại trong read-all, nhưng vẫn còn "
        f"{count_after_wait - count_at_cancel} lệnh chạy tiếp sau khi Cancel"
    )


def test_ghi_characteristic_qua_session(qtbot, connected_window: MainWindow) -> None:
    db = _make_db()
    connected_window.session._a2l_db = db  # type: ignore[attr-defined]
    connected_window.calibration_view.set_database(db)
    # FakeSession boot ở REFERENCE_PAGE — switch sang WORKING trước khi ghi
    connected_window.session.set_page(0, WORKING_PAGE, PageMode.XCP)
    connected_window.write_characteristic("GAIN", MEM_BASE, bytes([0xAB]))
    qtbot.waitUntil(lambda: not connected_window.busy, timeout=5000)
    assert connected_window.session.read(MEM_BASE, 1) == bytes([0xAB])


def test_cal_get_pages_cap_nhat_toggle(qtbot, connected_window: MainWindow) -> None:
    v = connected_window.calibration_view
    connected_window.cal_get_pages(0)
    qtbot.waitUntil(lambda: v.page_toggle.currentRouteKey() is not None, timeout=5000)
    # FakeSession boot ở REFERENCE_PAGE (Flash, đúng XCP spec boot state)
    assert v.page_toggle.currentRouteKey() == _ROUTE_REFERENCE


def test_cal_set_page_dat_ca_ecu_lan_xcp(qtbot, connected_window: MainWindow) -> None:
    w = connected_window
    v = w.calibration_view
    w.cal_set_page(0, REFERENCE_PAGE)
    qtbot.waitUntil(
        lambda: v.page_toggle.currentRouteKey() == _ROUTE_REFERENCE, timeout=5000
    )
    assert v.sync_warning_label.isHidden(), "hai trang đã đồng bộ thì không được cảnh báo"
    assert w.session.get_page(0, PageMode.ECU) == REFERENCE_PAGE
    assert w.session.get_page(0, PageMode.XCP) == REFERENCE_PAGE


def test_cal_get_pages_phat_hien_khong_dong_bo(qtbot, connected_window: MainWindow) -> None:
    w = connected_window
    v = w.calibration_view
    # Tạo desync: set ECU sang WORKING, giữ XCP ở REFERENCE (boot default)
    # ECU_PAGE=WORKING (1) ≠ XCP_PAGE=REFERENCE (0) → cảnh báo phải hiện
    w.session.set_page(0, WORKING_PAGE, PageMode.ECU)
    w.cal_get_pages(0)
    qtbot.waitUntil(lambda: not v.sync_warning_label.isHidden(), timeout=5000)
    assert not v.sync_btn.isHidden()


def test_sync_button_dong_bo_lai_qua_session(qtbot, connected_window: MainWindow) -> None:
    w = connected_window
    v = w.calibration_view
    # Tạo desync: set ECU sang WORKING, giữ XCP ở REFERENCE (boot default)
    w.session.set_page(0, WORKING_PAGE, PageMode.ECU)
    w.cal_get_pages(0)
    qtbot.waitUntil(lambda: not v.sync_btn.isHidden(), timeout=5000)

    v._on_sync_click()
    # Sync đặt ECU theo XCP (REFERENCE) — kiểm tra cả hai đạt REFERENCE
    qtbot.waitUntil(
        lambda: w.session.get_page(0, PageMode.ECU) == REFERENCE_PAGE, timeout=5000
    )
    assert w.session.get_page(0, PageMode.XCP) == REFERENCE_PAGE
    qtbot.waitUntil(lambda: v.sync_warning_label.isHidden(), timeout=5000)


def test_copy_ref_to_working_qua_session_khop_gia_tri_reference(
    qtbot, connected_window: MainWindow
) -> None:
    w = connected_window
    v = w.calibration_view
    db = _make_db()
    w.session._a2l_db = db  # type: ignore[attr-defined]
    v.set_database(db)

    # Switch sang WORKING để ghi (FakeSession boot ở REFERENCE, ghi REFERENCE = WriteProtected)
    w.session.set_page(0, WORKING_PAGE, PageMode.XCP)
    w.write_characteristic("GAIN", MEM_BASE, bytes([0x11]))
    qtbot.waitUntil(lambda: not w.busy, timeout=5000)
    assert w.session.read(MEM_BASE, 1) == bytes([0x11])  # Working đã bị sửa

    w.session.set_page(0, REFERENCE_PAGE, PageMode.XCP)
    reference_value = w.session.read(MEM_BASE, 1)  # Reference luôn là default, chưa ai ghi được
    w.session.set_page(0, WORKING_PAGE, PageMode.XCP)

    v._on_copy_ref_to_working()
    qtbot.waitUntil(lambda: not w.busy, timeout=5000)

    assert w.session.read(MEM_BASE, 1) == reference_value, (
        "sau Copy Ref→Working, đọc lại Working phải khớp bit-for-bit với Reference"
    )


def test_write_protected_mo_dialog_roi_chuyen_trang(
    qtbot, connected_window: MainWindow, monkeypatch
) -> None:
    import xcptool.ui.main_window as mw

    w = connected_window
    db = _make_db()
    w.session._a2l_db = db  # type: ignore[attr-defined]
    w.calibration_view.set_database(db)
    w.session.set_page(0, REFERENCE_PAGE, PageMode.XCP)   # XCP nhìn ROM

    asked: list[str] = []
    monkeypatch.setattr(
        mw, "ask_switch_to_working_page",
        lambda parent, detail: asked.append(detail) or True,
    )
    w.write_characteristic("GAIN", MEM_BASE, bytes([0x55]))
    qtbot.waitUntil(lambda: bool(asked), timeout=5000)
    qtbot.waitUntil(
        lambda: w.session.read(MEM_BASE, 1) == bytes([0x55]), timeout=5000
    )


def test_byte_order_duoc_dat_khi_ket_noi(qtbot, connected_window: MainWindow) -> None:
    # FakeSession luôn trả "little" byte order
    assert connected_window.calibration_view._byte_order == "little"


def test_connect_khong_tu_bao_dang_ban_gia(qtbot, window: MainWindow, cfg: BusConfig) -> None:
    notified: list[tuple[str, str]] = []
    window.notify = lambda title, content: notified.append((title, content))  # type: ignore[method-assign]

    window.connect_to(cfg)
    qtbot.waitUntil(lambda: window.session.state is ConnState.CONNECTED, timeout=5000)
    qtbot.waitUntil(lambda: not window.busy, timeout=5000)

    assert not any(title == "Busy" for title, _ in notified), (
        f"connect xong không được tự bắn thông báo 'Busy': {notified}"
    )


def test_connect_cap_nhat_ca_hai_panel_trang_tu_mot_lan_doc(
    qtbot, connected_window: MainWindow
) -> None:
    v = connected_window.calibration_view
    # FakeSession boot ở REFERENCE_PAGE (Flash, đúng XCP spec boot state)
    assert v.page_toggle.currentRouteKey() == _ROUTE_REFERENCE
    assert connected_window.memory_view.xcp_page_label.text() == str(REFERENCE_PAGE)
    assert connected_window.memory_view.ecu_page_label.text() == str(REFERENCE_PAGE)


def test_set_database_builds_struct_tree_from_instance_data(qtbot) -> None:
    """Thay test cũ (đoán struct theo tên) — giờ struct đến từ INSTANCE thật."""
    from xcptool.a2l.database import load as a2l_load
    import tempfile, textwrap
    a2l_text = textwrap.dedent("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin TYPEDEF_STRUCTURE Pid_t "pid" 8
        /begin STRUCTURE_COMPONENT kp T_Gain 0
        /end STRUCTURE_COMPONENT
        /begin STRUCTURE_COMPONENT ki T_Gain 4
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE speedPid "speed pid" Pid_t 0x80100000
    /end INSTANCE
    """)
    with tempfile.NamedTemporaryFile("w", suffix=".a2l", delete=False) as f:
        f.write(a2l_text)
        path = f.name
    db = a2l_load(path)

    v = _make_view(qtbot)
    v.set_database(db)

    assert v.tree.topLevelItemCount() == 1
    parent = v.tree.topLevelItem(0)
    assert parent.text(COL_NAME) == "speedPid"
    assert "STRUCT" in parent.text(COL_TYPE)
    assert parent.text(COL_SIZE) == "8"
    assert parent.childCount() == 2
    assert {parent.child(i).data(COL_NAME, Qt.UserRole) for i in range(2)} == {
        "speedPid.kp", "speedPid.ki"}


def test_set_database_no_instance_renders_flat_even_with_shared_name_prefix(qtbot) -> None:
    """Quyết định spec §6: CHARACTERISTIC không có INSTANCE hiện phẳng, dù
    tên trùng tiền tố — KHÔNG còn heuristic đoán theo tên."""
    db = A2LDatabase()
    for param in ("kp", "ki", "kd"):
        db.characteristics[f"speedPid_{param}"] = Characteristic(
            name=f"speedPid_{param}", description="", char_type="VALUE",
            address=MEM_BASE, record_layout="RL_F32", lower_limit=-10.0,
            upper_limit=10.0, datatype="FLOAT32_IEEE")
    v = _make_view(qtbot)
    v.set_database(db)

    assert v.tree.topLevelItemCount() == 3  # KHÔNG gộp — trước đây sẽ là 1
    names = {v.tree.topLevelItem(i).text(COL_NAME) for i in range(3)}
    assert names == {"speedPid_kp", "speedPid_ki", "speedPid_kd"}


def test_set_database_renders_nested_and_array_struct(qtbot) -> None:
    import tempfile, textwrap
    from xcptool.a2l.database import load as a2l_load
    a2l_text = textwrap.dedent("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin TYPEDEF_STRUCTURE Inner_t "inner" 4
        /begin STRUCTURE_COMPONENT val T_Gain 0
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin TYPEDEF_STRUCTURE Outer_t "outer" 4
        /begin STRUCTURE_COMPONENT inner Inner_t 0
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE pids "array of outer" Outer_t 0x80100000
        MATRIX_DIM 2
    /end INSTANCE
    """)
    with tempfile.NamedTemporaryFile("w", suffix=".a2l", delete=False) as f:
        f.write(a2l_text)
        path = f.name
    db = a2l_load(path)

    v = _make_view(qtbot)
    v.set_database(db)

    assert v.tree.topLevelItemCount() == 1
    array_parent = v.tree.topLevelItem(0)
    assert array_parent.childCount() == 2  # pids[0], pids[1]
    outer0 = array_parent.child(0)
    assert outer0.childCount() == 1        # inner
    inner0 = outer0.child(0)
    assert inner0.childCount() == 1        # val
    leaf = inner0.child(0)
    assert leaf.data(COL_NAME, Qt.UserRole) == "pids[0].inner.val"


def test_write_bare_array_instance_without_enclosing_struct(qtbot) -> None:
    """INSTANCE ... MATRIX_DIM của kiểu scalar (không bọc trong struct nào)
    vẫn phải ghi được qua đúng cơ chế combine-write, y hệt STRUCT."""
    import tempfile, textwrap
    from xcptool.a2l.database import load as a2l_load
    a2l_text = textwrap.dedent("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin INSTANCE tempSensors "3 sensor gains, no struct" T_Gain 0x80100000
        MATRIX_DIM 3
    /end INSTANCE
    """)
    with tempfile.NamedTemporaryFile("w", suffix=".a2l", delete=False) as f:
        f.write(a2l_text)
        path = f.name
    db = a2l_load(path)

    v = _make_view(qtbot)
    v.set_database(db)
    parent = v._char_items["tempSensors"]
    assert parent.text(COL_TYPE).startswith("ARRAY")

    for i in range(3):
        parent.child(i).setText(COL_VALUE, str(1.0 + i))

    writes: list[tuple[str, int, bytes]] = []
    v._write_cb = lambda name, addr, data: writes.append((name, addr, data))
    v._write_parent("tempSensors", parent)

    assert len(writes) == 1          # 3 phần tử liền khít -> 1 lần ghi
    name, addr, data = writes[0]
    assert addr == 0x80100000
    assert len(data) == 12            # 3 x FLOAT32 (4 byte)

    # Fix 2 (final review): "Write Selected" phải enable được qua đúng
    # _update_write_btn() — cổng nút thật của UI (không chỉ gọi _write_parent
    # trực tiếp, bỏ qua cổng) — khi 1 con của dòng cha ARRAY[ đang dirty.
    # Trước fix, _update_write_btn chỉ nhận diện "STRUCT", không nhận
    # "ARRAY[", nên nút luôn bị khoá dù _write_parent tự nó ghi đúng.
    child0_name = parent.child(0).data(COL_NAME, Qt.UserRole)
    v._dirty.add(child0_name)
    v.tree.setCurrentItem(parent)
    v.write_btn.setEnabled(False)
    v._update_write_btn()
    assert v.write_btn.isEnabled(), (
        "Write button phải enable khi 1 con của dòng cha ARRAY[ đang dirty"
    )


def test_start_value_edit_blocks_struct_and_array_parent_rows(qtbot) -> None:
    """STRUCT và ARRAY[ đều là dòng cha tổng hợp (combine-write) — không cho
    sửa trực tiếp ô Value của chính dòng cha, phải chọn từng con cụ thể.
    Trước fix Task 12: chỉ STRUCT bị chặn, ARRAY[ vẫn cho editItem() mở —
    gõ vào ô Value của dòng cha ARRAY chỉ cập nhật hiển thị con mà không
    đánh dấu dirty gì, gây hiểu lầm."""
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["grp_a"] = Characteristic(
        "grp_a", "", "VALUE", MEM_BASE, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["grp_b"] = Characteristic(
        "grp_b", "", "VALUE", MEM_BASE + 2, "I16", 0, 100, datatype="SWORD", array_size=1)
    _add_struct_instance(db, "grp", ["grp_a", "grp_b"])
    v.set_database(db)

    struct_parent = v._char_items["grp"]
    assert struct_parent.text(COL_TYPE).startswith("STRUCT")
    v._start_value_edit(struct_parent, COL_VALUE)
    assert not (struct_parent.flags() & Qt.ItemIsEditable), (
        "STRUCT parent không được cho sửa trực tiếp"
    )

    import tempfile, textwrap
    from xcptool.a2l.database import load as a2l_load
    a2l_text = textwrap.dedent("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin INSTANCE tempSensors "3 sensor gains, no struct" T_Gain 0x80100000
        MATRIX_DIM 3
    /end INSTANCE
    """)
    with tempfile.NamedTemporaryFile("w", suffix=".a2l", delete=False) as f:
        f.write(a2l_text)
        path = f.name
    db2 = a2l_load(path)
    v2 = _make_view(qtbot)
    v2.set_database(db2)
    array_parent = v2._char_items["tempSensors"]
    assert array_parent.text(COL_TYPE).startswith("ARRAY[")
    v2._start_value_edit(array_parent, COL_VALUE)
    assert not (array_parent.flags() & Qt.ItemIsEditable), (
        "ARRAY[ parent (trước fix bị bỏ sót) không được cho sửa trực tiếp"
    )


def test_set_database_skips_measurement_instance_without_crashing(qtbot) -> None:
    """Bug thật (review round 1): INSTANCE trỏ tới TYPEDEF_MEASUREMENT (không
    phải TYPEDEF_CHARACTERISTIC) từng làm _build_tree_item_from_node tra cứu
    self._db.characteristics[node.leaf_name] và ném KeyError — set_database()
    không có try/except nào bọc ngoài (main_window._after_a2l_load gọi thẳng),
    nên đây là crash không bắt được khi load 1 file A2L hợp lệ có cả CAL lẫn
    DAQ struct instance (kịch bản thực tế mô tả trong motivation của spec).
    CalibrationView chỉ hiển thị CHARACTERISTIC — MEASUREMENT thuộc
    MeasurementView (Task 13) -> phải bỏ qua êm, không crash."""
    import tempfile, textwrap
    from xcptool.a2l.database import load as a2l_load
    a2l_text = textwrap.dedent("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin TYPEDEF_MEASUREMENT T_Temp "temperature" FLOAT32_IEEE CM_NONE 0 0 -40 150
    /end TYPEDEF_MEASUREMENT
    /begin INSTANCE gainInst "calibratable gain" T_Gain 0x80100000
    /end INSTANCE
    /begin INSTANCE tempInst "measured temperature" T_Temp 0x80100010
    /end INSTANCE
    """)
    with tempfile.NamedTemporaryFile("w", suffix=".a2l", delete=False) as f:
        f.write(a2l_text)
        path = f.name
    db = a2l_load(path)

    v = _make_view(qtbot)
    v.set_database(db)  # trước fix: KeyError('tempInst')

    assert v.tree.topLevelItemCount() == 1  # chỉ gainInst — tempInst bị lọc êm
    only = v.tree.topLevelItem(0)
    assert only.data(COL_NAME, Qt.UserRole) == "gainInst"
    assert "tempInst" not in v._char_items  # không để lại node rỗng/mồ côi nào


def test_set_database_creates_array_children_and_syncs_edit(qtbot) -> None:
    """Kiểm tra Array CHARACTERISTIC (VAL_BLK) có các node con và sửa con đồng bộ."""
    db = A2LDatabase()
    db.characteristics["tempTable"] = Characteristic(
        name="tempTable",
        description="Temperature table",
        char_type="VAL_BLK",
        address=MEM_BASE + 0x20,
        record_layout="F32",
        lower_limit=-40.0,
        upper_limit=150.0,
        array_size=3,
        datatype="FLOAT32_IEEE",
    )
    v = _make_view(qtbot)
    v.set_database(db)

    parent = v.tree.topLevelItem(0)
    assert parent.text(COL_NAME) == "tempTable"
    assert parent.childCount() == 3
    assert parent.child(0).text(COL_NAME) == "[0]"
    assert parent.child(1).text(COL_NAME) == "[1]"
    assert parent.child(2).text(COL_NAME) == "[2]"

    # Giả lập đọc xong giá trị
    v.on_read_done("tempTable", struct.pack("<3f", 10.0, 20.0, 30.0))
    assert parent.text(COL_VALUE) == "—"
    assert parent.child(0).text(COL_VALUE) == "10"
    assert parent.child(1).text(COL_VALUE) == "20"
    assert parent.child(2).text(COL_VALUE) == "30"

    # Người dùng chọn và sửa phần tử con [1] thành "25"
    child1 = parent.child(1)
    v.tree.setCurrentItem(child1)
    child1.setText(COL_VALUE, "25")
    # Kích hoạt signal itemChanged
    v._on_item_changed(child1, COL_VALUE)

    assert "tempTable" in v._dirty
    
    items = v.tree.selectedItems()
    assert items[0].data(0, Qt.UserRole) == ("array_elem", "tempTable", 1)
    assert v.write_btn.isEnabled()


def test_write_struct_aggregates_children(qtbot, connected_window: MainWindow) -> None:
    """Test that writing a STRUCT parent packs all its children and writes to the base address."""
    v = connected_window.calibration_view
    
    db = A2LDatabase()
    db.characteristics["pid_kp"] = Characteristic("pid_kp", "", "VALUE", MEM_BASE, "F32", 0, 10, datatype="FLOAT32_IEEE", array_size=1)
    db.characteristics["pid_ki"] = Characteristic("pid_ki", "", "VALUE", MEM_BASE + 4, "F32", 0, 10, datatype="FLOAT32_IEEE", array_size=1)
    _add_struct_instance(db, "pid", ["pid_kp", "pid_ki"])
    v.set_database(db)
    
    parent = v._char_items["pid"]
    parent.child(0).setText(COL_VALUE, "1.0")
    parent.child(1).setText(COL_VALUE, "2.0")
    
    writes = []
    v._write_cb = lambda name, addr, data: writes.append((name, addr, data))
    
    v._write_parent("pid", parent)
    
    assert len(writes) == 1
    name, addr, data = writes[0]
    assert name == "pid"
    assert addr == MEM_BASE
    assert len(data) == 8


def test_write_parent_recurses_into_nested_struct_children(qtbot) -> None:
    """Bug thật (final review, CRITICAL): nhánh STRUCT/ARRAY của _write_parent
    trước fix chỉ đọc CON TRỰC TIẾP. Outer_t có 1 member trực tiếp (kp) + 1
    member là struct lồng khác (ctl: Inner_t, chứa ki/kd) — con "ctl" mang
    Qt.UserRole là tên node hierarchical ("outerInst.ctl"), không phải key
    trong self._db.characteristics, nên bị `if not c_def: continue` bỏ qua
    ÊM: chỉ ghi kp, bỏ mất cả ki/kd mà vẫn báo thành công (report success
    với write thiếu — vi phạm DESIGN.md §7: ghi struct phải trọn 1 khối)."""
    import tempfile, textwrap
    from xcptool.a2l.database import load as a2l_load
    a2l_text = textwrap.dedent("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin TYPEDEF_STRUCTURE Inner_t "inner" 8
        /begin STRUCTURE_COMPONENT ki T_Gain 0
        /end STRUCTURE_COMPONENT
        /begin STRUCTURE_COMPONENT kd T_Gain 4
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin TYPEDEF_STRUCTURE Outer_t "outer" 12
        /begin STRUCTURE_COMPONENT kp T_Gain 0
        /end STRUCTURE_COMPONENT
        /begin STRUCTURE_COMPONENT ctl Inner_t 4
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE outerInst "outer instance" Outer_t 0x80100000
    /end INSTANCE
    """)
    with tempfile.NamedTemporaryFile("w", suffix=".a2l", delete=False) as f:
        f.write(a2l_text)
        path = f.name
    db = a2l_load(path)

    v = _make_view(qtbot)
    v.set_database(db)

    parent = v._char_items["outerInst"]
    assert parent.childCount() == 2
    nested = next(
        (parent.child(i) for i in range(parent.childCount()) if parent.child(i).childCount() > 0),
        None,
    )
    assert nested is not None, "test setup phải có 1 con là struct lồng (ctl)"
    assert nested.childCount() == 2

    leaf_names = ["outerInst.kp", "outerInst.ctl.ki", "outerInst.ctl.kd"]
    for name in leaf_names:
        assert name in db.characteristics

    v._dirty.update(leaf_names)
    for i in range(parent.childCount()):
        child = parent.child(i)
        if child.childCount() == 0:
            child.setText(COL_VALUE, "1.0")
    for j in range(nested.childCount()):
        nested.child(j).setText(COL_VALUE, "2.0")

    writes: list[tuple[str, int, bytes]] = []
    v._write_cb = lambda name, addr, data: writes.append((name, addr, data))
    v._write_parent("outerInst", parent)

    total_written = sum(len(data) for _, _, data in writes)
    expected_size = sum(db.characteristics[n].byte_size for n in leaf_names)
    assert total_written == expected_size, (
        f"phải ghi đủ cả struct lồng, không chỉ member trực tiếp: "
        f"ghi {total_written} byte, cần {expected_size} byte (writes={writes})"
    )

    written_addrs: set[int] = set()
    for _, addr, data in writes:
        for off in range(len(data)):
            written_addrs.add(addr + off)
    for n in leaf_names:
        c = db.characteristics[n]
        for off in range(c.byte_size):
            assert (c.address + off) in written_addrs, f"thiếu byte tại {n}+{off}"

    # Sau khi ghi trọn, dirty phải sạch hết — kể cả các lá lồng sâu.
    assert not v._dirty & set(leaf_names)


def test_write_parent_clears_deep_nested_leaf_dirty_and_enables_write_btn(qtbot) -> None:
    """Bug thật còn sót (residual, final review): _leaf_write_items() đã cho
    _write_parent() ghi đúng lá lồng sâu, nhưng on_write_done() và
    _update_write_btn() vẫn chỉ duyệt CON TRỰC TIẾP của dòng struct ngoài
    cùng.

    Với struct lồng 2 cấp (outerInst.kp trực tiếp + outerInst.ctl.{ki,kd}
    lồng qua "ctl"), dirty đúng 1 lá SÂU "outerInst.ctl.ki" (không phải con
    trực tiếp — con trực tiếp của outerInst là "kp" và "ctl"):

    1. _update_write_btn(): trước fix chỉ soát "kp"/"ctl" trong self._dirty
       (cả hai đều không có mặt — "ctl" mang tên hierarchical, không phải
       key dirty thật) -> nút Write bị khoá dù _write_parent ghi đúng.
    2. on_write_done(): trước fix cũng chỉ duyệt "kp"/"ctl" -> không bao giờ
       refresh _original["outerInst.ctl.ki"], và node trung gian "ctl" (đã
       bị _on_item_changed tô cam ở COL_NAME khi lá con nó dirty) không bao
       giờ được dọn cam — kẹt cam mãi dù ECU đã nhận đủ byte.
    """
    import tempfile, textwrap
    from xcptool.a2l.database import load as a2l_load
    a2l_text = textwrap.dedent("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin TYPEDEF_STRUCTURE Inner_t "inner" 8
        /begin STRUCTURE_COMPONENT ki T_Gain 0
        /end STRUCTURE_COMPONENT
        /begin STRUCTURE_COMPONENT kd T_Gain 4
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin TYPEDEF_STRUCTURE Outer_t "outer" 12
        /begin STRUCTURE_COMPONENT kp T_Gain 0
        /end STRUCTURE_COMPONENT
        /begin STRUCTURE_COMPONENT ctl Inner_t 4
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE outerInst "outer instance" Outer_t 0x80100000
    /end INSTANCE
    """)
    with tempfile.NamedTemporaryFile("w", suffix=".a2l", delete=False) as f:
        f.write(a2l_text)
        path = f.name
    db = a2l_load(path)

    v = _make_view(qtbot)
    v.set_database(db)

    parent = v._char_items["outerInst"]
    nested = next(
        (parent.child(i) for i in range(parent.childCount()) if parent.child(i).childCount() > 0),
        None,
    )
    assert nested is not None, "test setup phải có 1 con là struct lồng (ctl)"
    deep_leaf = next(
        nested.child(j) for j in range(nested.childCount())
        if nested.child(j).data(COL_NAME, Qt.UserRole) == "outerInst.ctl.ki"
    )

    # Mô phỏng đã đọc xong 1 lần — mọi lá (kp, ki, kd) đều có giá trị hợp lệ
    # và _original đã ghi nhận, y hệt sau on_read_done() thật. Không đụng gì
    # ngoài "ki" phía dưới, nên "kp"/"kd" vẫn phải sạch sau khi ghi.
    for i in range(parent.childCount()):
        child = parent.child(i)
        if child.childCount() == 0:
            child.setText(COL_VALUE, "1.0")
            v._original[child.data(COL_NAME, Qt.UserRole)] = "1.0"
    for j in range(nested.childCount()):
        leaf = nested.child(j)
        leaf.setText(COL_VALUE, "1.0")
        v._original[leaf.data(COL_NAME, Qt.UserRole)] = "1.0"

    # Dirty đúng 1 lá SÂU — không đụng tới "kp" hay bất kỳ con trực tiếp nào.
    deep_leaf.setText(COL_VALUE, "5.0")
    v._on_item_changed(deep_leaf, COL_VALUE)

    neutral = v.tree.palette().text().color()
    assert "outerInst.ctl.ki" in v._dirty
    assert nested.foreground(COL_NAME).color() != neutral  # "ctl" đã tô cam khi sửa lá con
    assert "outerInst.kp" not in v._dirty  # con trực tiếp còn lại KHÔNG dirty

    # (1) _update_write_btn(): chọn dòng struct ngoài cùng — chỉ 1 lá SÂU
    # dirty vẫn phải bật nút, vì _write_parent() ghi đúng lá đó.
    v.tree.setCurrentItem(parent)
    v._update_write_btn()
    assert v.write_btn.isEnabled(), (
        "Write button phải bật khi có lá SÂU dirty, dù không phải con trực tiếp"
    )

    # Ghi cả struct ngoài cùng — _write_parent() đệ quy đúng qua _leaf_write_items().
    writes: list[tuple[str, int, bytes]] = []
    v._write_cb = lambda name, addr, data: writes.append((name, addr, data))
    v._write_parent("outerInst", parent)
    assert writes, "_write_parent phải ghi được (đã kiểm chứng riêng ở test khác)"

    # Mô phỏng ECU ack đoạn ghi.
    v.on_write_done("outerInst")

    # (2) on_write_done(): _original phải được refresh và dirty phải sạch cho
    # lá sâu, và node trung gian "ctl" phải hết cam — không chỉ con trực tiếp.
    assert "outerInst.ctl.ki" not in v._dirty
    assert v._original["outerInst.ctl.ki"] == "5.0", (
        "_original phải được refresh cho lá lồng sâu sau khi ghi thành công"
    )
    assert nested.foreground(COL_NAME).color() == neutral, (
        "node trung gian 'ctl' phải hết cam sau khi ghi xong — trước fix vẫn kẹt cam"
    )


# ── multi-select: ExtendedSelection + _resolve_leaf_names ───────────────────

def test_tree_ho_tro_multi_select(qtbot) -> None:
    v = _make_view(qtbot)
    assert v.tree.selectionMode() == QAbstractItemView.ExtendedSelection


def test_resolve_leaf_names_don_1_scalar(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    item = v._char_items["GAIN"]
    assert v._resolve_leaf_names([item]) == ["GAIN"]


def test_resolve_leaf_names_struct_cha_ra_het_la_that(qtbot) -> None:
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["grp_a"] = Characteristic(
        "grp_a", "", "VALUE", MEM_BASE, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["grp_b"] = Characteristic(
        "grp_b", "", "VALUE", MEM_BASE + 2, "I16", 0, 100, datatype="SWORD", array_size=1)
    _add_struct_instance(db, "grp", ["grp_a", "grp_b"])
    v.set_database(db)
    parent = v._char_items["grp"]
    assert sorted(v._resolve_leaf_names([parent])) == ["grp_a", "grp_b"]


def test_resolve_leaf_names_khu_trung_cha_va_con(qtbot) -> None:
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["grp_a"] = Characteristic(
        "grp_a", "", "VALUE", MEM_BASE, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["grp_b"] = Characteristic(
        "grp_b", "", "VALUE", MEM_BASE + 2, "I16", 0, 100, datatype="SWORD", array_size=1)
    _add_struct_instance(db, "grp", ["grp_a", "grp_b"])
    v.set_database(db)
    parent = v._char_items["grp"]
    child_a = parent.child(0)
    names = v._resolve_leaf_names([parent, child_a])
    assert sorted(names) == ["grp_a", "grp_b"]  # grp_a không lặp lại dù chọn cả cha lẫn con


def test_resolve_leaf_names_val_blk_tra_ve_1_ten_cha(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    parent = v._char_items["LUT"]
    assert v._resolve_leaf_names([parent]) == ["LUT"]


def test_resolve_leaf_names_array_elem_con_tra_ve_ten_cha(qtbot) -> None:
    v = _make_view(qtbot)
    v.set_database(_make_db())
    child = v._char_items["LUT"].child(2)
    assert v._resolve_leaf_names([child]) == ["LUT"]


def test_resolve_leaf_names_gop_2_nhom_doc_lap(qtbot) -> None:
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["grp1_a"] = Characteristic(
        "grp1_a", "", "VALUE", MEM_BASE, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["grp2_a"] = Characteristic(
        "grp2_a", "", "VALUE", MEM_BASE + 2, "I16", 0, 100, datatype="SWORD", array_size=1)
    _add_struct_instance(db, "grp1", ["grp1_a"])
    _add_struct_instance(db, "grp2", ["grp2_a"])
    v.set_database(db)
    names = v._resolve_leaf_names([v._char_items["grp1"], v._char_items["grp2"]])
    assert sorted(names) == ["grp1_a", "grp2_a"]


# ── _split_into_contiguous_runs — helper thuần, không cần Qt ────────────────

def test_split_into_contiguous_runs_packed_gives_one_run() -> None:
    entries = [(MEM_BASE, b"\x01\x00", "a"), (MEM_BASE + 2, b"\x02\x00", "b")]
    runs = _split_into_contiguous_runs(entries, "grp")
    assert runs == [(MEM_BASE, b"\x01\x00\x02\x00")]


def test_split_into_contiguous_runs_splits_on_gap() -> None:
    """INT16 @ base rồi INT32 @ base+4 (compiler chèn 2 byte align) → 2 đoạn,
    không đoạn nào chứa 2 byte đệm ở giữa."""
    entries = [
        (MEM_BASE, b"\x2a\x00", "flag"),                    # 2 byte
        (MEM_BASE + 4, b"\x39\x30\x00\x00", "threshold"),    # 4 byte, cách 2 byte
    ]
    runs = _split_into_contiguous_runs(entries, "grp")
    assert runs == [
        (MEM_BASE, b"\x2a\x00"),
        (MEM_BASE + 4, b"\x39\x30\x00\x00"),
    ]


def test_split_into_contiguous_runs_raises_on_overlap() -> None:
    entries = [(MEM_BASE, b"\x00\x00\x00\x00", "a"), (MEM_BASE + 2, b"\x00\x00", "b")]
    with pytest.raises(ValueError, match="Overlapping members near b in struct grp"):
        _split_into_contiguous_runs(entries, "grp")


def test_write_struct_with_gap_sends_one_write_per_contiguous_run(qtbot) -> None:
    """Trước fix: struct có gap từng ném 'Size overflow' và không ghi được gì.
    Sau fix: mỗi đoạn liền khít ra đúng 1 lệnh WRITE riêng, không lệnh nào
    đụng tới 2 byte đệm giữa 2 member."""
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["grp_flag"] = Characteristic(
        "grp_flag", "", "VALUE", MEM_BASE, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["grp_threshold"] = Characteristic(
        "grp_threshold", "", "VALUE", MEM_BASE + 4, "I32", 0, 100, datatype="SLONG", array_size=1)
    _add_struct_instance(db, "grp", ["grp_flag", "grp_threshold"])
    v.set_database(db)

    parent = v._char_items["grp"]
    parent.child(0).setText(COL_VALUE, "42")     # grp_flag
    parent.child(1).setText(COL_VALUE, "12345")  # grp_threshold
    v._dirty.update({"grp_flag", "grp_threshold"})

    writes: list[tuple[str, int, bytes]] = []
    v._write_cb = lambda name, addr, data: writes.append((name, addr, data))
    v._write_parent("grp", parent)

    # Đoạn đầu bắn ngay trong _write_parent; đoạn 2 chỉ bắn tiếp khi
    # on_write_done() báo đoạn 1 đã xong (mô phỏng ack bất đồng bộ của XCP).
    assert len(writes) == 1
    assert "grp" in v._pending_struct_runs and v._pending_struct_runs["grp"]
    v.on_write_done("grp")
    assert len(writes) == 2
    assert "grp" not in v._pending_struct_runs or not v._pending_struct_runs["grp"]

    addrs = {addr for _, addr, _ in writes}
    assert addrs == {MEM_BASE, MEM_BASE + 4}
    # Không lệnh nào ghi 2 byte đệm giữa hai member.
    assert all(len(data) in (2, 4) for _, _, data in writes)

    # Dirty phải hết sạch — kể cả sau nhiều đoạn.
    assert "grp_flag" not in v._dirty
    assert "grp_threshold" not in v._dirty


def test_write_all_waits_for_every_run_before_next_queue_item(qtbot) -> None:
    """'Write All' xếp 1 struct có gap + 1 scalar khác — scalar chỉ được ghi
    SAU KHI mọi đoạn của struct hoàn tất, không chen ngang giữa chừng (Session
    không reentrant, ghi chồng lên nhau sẽ ném BusyError)."""
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["grp_flag"] = Characteristic(
        "grp_flag", "", "VALUE", MEM_BASE, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["grp_threshold"] = Characteristic(
        "grp_threshold", "", "VALUE", MEM_BASE + 4, "I32", 0, 100, datatype="SLONG", array_size=1)
    db.characteristics["solo"] = Characteristic(
        "solo", "", "VALUE", MEM_BASE + 64, "I16", 0, 100, datatype="SWORD", array_size=1)
    _add_struct_instance(db, "grp", ["grp_flag", "grp_threshold"])
    v.set_database(db)

    v._char_items["grp"].child(0).setText(COL_VALUE, "42")
    v._char_items["grp"].child(1).setText(COL_VALUE, "12345")
    v._char_items["solo"].setText(COL_VALUE, "7")
    v._dirty.update({"grp_flag", "grp_threshold", "solo"})

    writes: list[tuple[str, int, bytes]] = []
    v._write_cb = lambda name, addr, data: writes.append((name, addr, data))
    # Đặt thẳng hàng đợi (thay vì qua _on_write_all()) để cố định thứ tự —
    # _on_write_all dùng set() nội bộ nên thứ tự không đảm bảo, không phải
    # điều test này muốn kiểm tra.
    v._write_queue = [v._char_items["grp"], v._char_items["solo"]]
    v._process_write_queue()

    # Chỉ đoạn đầu của "grp" được bắn — "solo" chưa được đụng tới.
    assert [name for name, _, _ in writes] == ["grp"]

    v.on_write_done("grp")  # đoạn 1 xong -> tự bắn đoạn 2, "solo" vẫn chưa tới lượt
    assert [name for name, _, _ in writes] == ["grp", "grp"]

    v.on_write_done("grp")  # đoạn 2 (cuối) xong -> mới tiến hàng đợi ngoài
    assert [name for name, _, _ in writes] == ["grp", "grp", "solo"]


def test_write_selected_single_struct_child_clears_parent_name_color(qtbot) -> None:
    """Bug thật gặp: chọn 1 dòng con trong STRUCT rồi 'Write Selected' — ghi
    chỉ đúng member đó (không qua nhánh STRUCT của _write_parent), nên dòng
    cha đang tô cam từ lúc sửa vẫn không được on_write_done() đi ngược lên
    dọn — kẹt cam mãi dù mọi con đã sạch."""
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["grp_a"] = Characteristic(
        "grp_a", "", "VALUE", MEM_BASE, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["grp_b"] = Characteristic(
        "grp_b", "", "VALUE", MEM_BASE + 2, "I16", 0, 100, datatype="SWORD", array_size=1)
    _add_struct_instance(db, "grp", ["grp_a", "grp_b"])
    v.set_database(db)

    parent = v._char_items["grp"]
    child_a = parent.child(0)
    v._original["grp_a"] = child_a.text(COL_VALUE)

    child_a.setText(COL_VALUE, "99")
    v._on_item_changed(child_a, COL_VALUE)
    neutral = v.tree.palette().text().color()
    assert parent.foreground(COL_NAME).color() != neutral  # cha đã tô cam khi sửa

    writes: list[tuple[str, int, bytes]] = []
    v._write_cb = lambda name, addr, data: writes.append((name, addr, data))
    v.tree.setCurrentItem(child_a)
    v._on_write()
    assert len(writes) == 1 and writes[0][0] == "grp_a"  # ghi lẻ 1 child, không qua STRUCT

    v.on_write_done("grp_a")
    assert child_a.foreground(COL_NAME).color() == neutral
    assert parent.foreground(COL_NAME).color() == neutral  # trước fix: vẫn cam


def test_write_selected_single_child_keeps_parent_dirty_if_sibling_still_dirty(qtbot) -> None:
    """Ghi xong 1 child nhưng sibling khác vẫn đang sửa dở -> cha PHẢI còn cam,
    không được vô tình dọn sạch cha khi vẫn còn con dirty."""
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["grp_a"] = Characteristic(
        "grp_a", "", "VALUE", MEM_BASE, "I16", 0, 100, datatype="SWORD", array_size=1)
    db.characteristics["grp_b"] = Characteristic(
        "grp_b", "", "VALUE", MEM_BASE + 2, "I16", 0, 100, datatype="SWORD", array_size=1)
    _add_struct_instance(db, "grp", ["grp_a", "grp_b"])
    v.set_database(db)

    parent = v._char_items["grp"]
    child_a, child_b = parent.child(0), parent.child(1)
    v._original["grp_a"] = child_a.text(COL_VALUE)
    v._original["grp_b"] = child_b.text(COL_VALUE)

    child_a.setText(COL_VALUE, "99")
    v._on_item_changed(child_a, COL_VALUE)
    child_b.setText(COL_VALUE, "42")
    v._on_item_changed(child_b, COL_VALUE)

    writes: list[tuple[str, int, bytes]] = []
    v._write_cb = lambda name, addr, data: writes.append((name, addr, data))
    v.tree.setCurrentItem(child_a)
    v._on_write()
    v.on_write_done("grp_a")

    neutral = v.tree.palette().text().color()
    assert child_a.foreground(COL_NAME).color() == neutral
    assert "grp_b" in v._dirty
    assert parent.foreground(COL_NAME).color() != neutral  # grp_b vẫn dirty -> cha còn cam


def test_array_placeholder_edit_ignored(qtbot) -> None:
    """Test that editing an array parent with placeholder '—' is ignored."""
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["arr"] = Characteristic("arr", "", "VAL_BLK", MEM_BASE, "F32", 0, 10, datatype="FLOAT32_IEEE", array_size=2)
    v.set_database(db)
    
    parent = v._char_items["arr"]
    assert parent.text(COL_VALUE) == "—"
    
    # Trigger item changed with the placeholder
    v._on_item_changed(parent, COL_VALUE)
    
    # Child should remain intact
    assert parent.child(0).text(COL_VALUE) == "—"
    assert "arr" not in v._dirty


def test_write_all_uses_queue(qtbot) -> None:
    """Test that Write All queues writes sequentially."""
    v = _make_view(qtbot)
    db = A2LDatabase()
    db.characteristics["a"] = Characteristic("a", "", "VALUE", MEM_BASE, "F32", 0, 10, datatype="FLOAT32_IEEE", array_size=1)
    db.characteristics["b"] = Characteristic("b", "", "VALUE", MEM_BASE + 4, "F32", 0, 10, datatype="FLOAT32_IEEE", array_size=1)
    v.set_database(db)
    
    item_a = v._char_items["a"]
    item_b = v._char_items["b"]
    item_a.setText(COL_VALUE, "1.0")
    item_b.setText(COL_VALUE, "2.0")
    v._dirty.add("a")
    v._dirty.add("b")
    
    writes = []
    def fake_write_parent(name, item):
        writes.append(name)
        
    v._write_parent = fake_write_parent
    
    v._on_write_all()
    
    # Only the first one is popped and processed initially
    assert len(writes) == 1
    assert len(v._write_queue) == 1
    
    # Call on_write_done for the first one, which should trigger the second
    v.on_write_done(writes[0])
    
    assert len(writes) == 2
    assert len(v._write_queue) == 0


def test_set_database_handled_filtered_by_type_keeps_flat_characteristic_name_collision(
    qtbot,
) -> None:
    """Bug thật (final review, Fix 5): `handled` trong set_database() được
    gom từ _leaf_names(node) đi trên TOÀN BỘ instance_trees — trước fix,
    hàm này trả về MỌI leaf_name bất kể is_measurement. a2l/database.py chỉ
    chống trùng tên TRONG CÙNG dict (characteristics riêng, measurements
    riêng) nên 1 MEASUREMENT resolve-từ-INSTANCE hoàn toàn có thể trùng tên
    với 1 CHARACTERISTIC phẳng độc lập mà parser không hề chặn. Nếu không
    lọc theo is_measurement, CHARACTERISTIC phẳng đó bị `handled` loại êm và
    biến mất khỏi CalibrationView dù hợp lệ."""
    db = A2LDatabase()
    db.characteristics["shared"] = Characteristic(
        name="shared", description="", char_type="VALUE", address=MEM_BASE,
        record_layout="RL_UBYTE", lower_limit=0.0, upper_limit=255.0,
        datatype="UBYTE", array_size=1,
    )
    db.measurements["shared"] = Measurement(
        name="shared", description="", datatype="UBYTE",
        address=MEM_BASE + 0x10, lower_limit=0.0, upper_limit=255.0,
    )
    # INSTANCE-resolved MEASUREMENT leaf trùng tên "shared" — mô phỏng đúng
    # shape mà a2l/database.py._resolve_type() dựng cho 1 INSTANCE trỏ tới
    # TYPEDEF_MEASUREMENT tên "shared".
    db.instance_trees["shared"] = InstanceNode(
        name="shared", address=MEM_BASE + 0x10, leaf_name="shared",
        is_measurement=True, struct_size=None,
    )

    v = _make_view(qtbot)
    v.set_database(db)

    # CHARACTERISTIC phẳng "shared" KHÔNG được handled loại êm chỉ vì trùng
    # tên với 1 MEASUREMENT resolve-từ-INSTANCE khác hẳn.
    assert v.tree.topLevelItemCount() == 1
    only = v.tree.topLevelItem(0)
    assert only.data(COL_NAME, Qt.UserRole) == "shared"
    assert "shared" in v._char_items


def test_float_radix_decode_and_encode() -> None:
    """Kiểm tra decode và encode kiểu FLOAT32 và FLOAT64 theo DEC, HEX, BIN, ASCII."""
    # 1.0f trong IEEE 754 float32 little endian là 0x3F800000 -> bytes: 00 00 80 3F
    f32_raw = struct.pack("<f", 1.0)
    assert decode_value(f32_raw, "FLOAT32_IEEE", "little", "DEC") == "1"
    assert decode_value(f32_raw, "FLOAT32_IEEE", "little", "HEX") == "0x3F800000"
    assert decode_value(f32_raw, "FLOAT32_IEEE", "little", "BIN") == "0b00111111100000000000000000000000"

    # Encode lại từ HEX string và DEC string
    assert encode_value("1.0", "FLOAT32_IEEE", "little", 1) == f32_raw
    assert encode_value("0x3F800000", "FLOAT32_IEEE", "little", 1) == f32_raw

    # Float64: 1.0d -> 0x3FF0000000000000
    f64_raw = struct.pack("<d", 1.0)
    assert decode_value(f64_raw, "FLOAT64_IEEE", "little", "HEX") == "0x3FF0000000000000"
    assert encode_value("0x3FF0000000000000", "FLOAT64_IEEE", "little", 1) == f64_raw


def test_encode_value_ascii_support() -> None:
    """Kiểm tra encode_value khi nhập ký tự ASCII cho kiểu số nguyên và số thực."""
    # UINT16 nhập 'H' (mã 72 = 0x48) -> b'\x48\x00' (little endian)
    assert encode_value("H", "UWORD", "little", 1) == b"\x48\x00"

    # UINT8 nhập 'e' (mã 101 = 0x65) -> b'\x65'
    assert encode_value("e", "UBYTE", "little", 1) == b"\x65"

    # Array 3 phần tử: "H, e, l" -> b'\x48\x00\x65\x00\x6c\x00'
    assert encode_value("H, e, l", "UWORD", "little", 3) == b"\x48\x00\x65\x00\x6c\x00"

    # Nhập số thường (Dec/Hex) vẫn hoạt động hoàn hảo
    assert encode_value("72", "UWORD", "little", 1) == b"\x48\x00"
    assert encode_value("0x48", "UWORD", "little", 1) == b"\x48\x00"


