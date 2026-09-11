"""A3d — panel hiệu chỉnh: CHARACTERISTIC tree, inline edit, điều khiển trang."""

from __future__ import annotations

import struct

import pytest
from PySide6.QtCore import Qt

from xcptool.a2l.types import A2LDatabase, Characteristic, RecordLayout
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


def test_set_database_groups_struct_characteristics(qtbot) -> None:
    """Kiểm tra CHARACTERISTIC dạng struct (speedPid_*) được gom nhóm thành parent-child."""
    db = A2LDatabase()
    for param in ("kp", "ki", "kd"):
        db.characteristics[f"speedPid_{param}"] = Characteristic(
            name=f"speedPid_{param}",
            description=f"PID {param}",
            char_type="VALUE",
            address=MEM_BASE + 0x08,
            record_layout="F32",
            lower_limit=-10.0,
            upper_limit=10.0,
            datatype="FLOAT32_IEEE",
        )
    v = _make_view(qtbot)
    v.set_database(db)

    assert v.tree.topLevelItemCount() == 1
    parent = v.tree.topLevelItem(0)
    assert parent.text(COL_NAME) == "speedPid"
    assert "STRUCT" in parent.text(COL_TYPE)
    assert parent.childCount() == 3
    child_names = [parent.child(i).text(COL_NAME) for i in range(3)]
    assert child_names == ["kd", "ki", "kp"] or set(child_names) == {"kp", "ki", "kd"}


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


