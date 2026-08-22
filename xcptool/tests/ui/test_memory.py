"""F4 — panel bộ nhớ: đọc/ghi theo địa chỉ và điều khiển trang calibration.

Cổng của mốc này có hai vế:
  * ghi một vùng rồi đọc lại thấy đúng giá trị;
  * `WriteProtectedError` → thông báo KÈM NÚT chuyển về working page. Chỉ in mã
    lỗi là hỏng gate, vì đây là điểm UX quan trọng nhất của panel.
"""

from __future__ import annotations

from xcptool.session.api import PageMode
from xcptool.session.fake import MEM_BASE
from xcptool.ui.main_window import MainWindow
from xcptool.ui.memory_view import BYTES_PER_ROW, WORKING_PAGE

ADDR = f"0x{MEM_BASE:08X}"


def _read(qtbot, w: MainWindow, addr: str = ADDR, size: int = 32) -> None:
    w.memory_view.addr_edit.setText(addr)
    w.memory_view.size_spin.setValue(size)
    w.memory_view.do_read()
    qtbot.waitUntil(lambda: not w.busy, timeout=5000)


def _edit_cell(w: MainWindow, index: int, value: int) -> None:
    row, col = divmod(index, BYTES_PER_ROW)
    w.memory_view.table.item(row, col).setText(f"{value:02X}")


def test_doc_hien_hex_dump(qtbot, connected_window: MainWindow) -> None:
    _read(qtbot, connected_window, size=32)
    v = connected_window.memory_view
    assert v.table.rowCount() == 2
    assert v.table.verticalHeaderItem(0).text() == f"{MEM_BASE:08X}"
    assert v.table.item(0, 0).text() != ""


def test_dia_chi_sai_dinh_dang_khong_lam_vo_app(qtbot, connected_window: MainWindow) -> None:
    v = connected_window.memory_view
    v.addr_edit.setText("không phải địa chỉ")
    v.do_read()
    qtbot.wait(100)
    assert "invalid" in v.status_label.text().lower()


def test_sua_o_bat_nut_ghi_va_danh_dau_thay_doi(qtbot, connected_window: MainWindow) -> None:
    _read(qtbot, connected_window)
    v = connected_window.memory_view
    assert not v.write_btn.isEnabled(), "chưa sửa gì thì không cho ghi"

    original = int(v.table.item(0, 0).text(), 16)
    _edit_cell(connected_window, 0, (original + 1) & 0xFF)

    assert v.write_btn.isEnabled()
    assert "1 byte(s) modified" in v.status_label.text()


def test_go_gia_tri_khong_hop_le_thi_tra_ve_gia_tri_cu(
    qtbot, connected_window: MainWindow
) -> None:
    _read(qtbot, connected_window)
    v = connected_window.memory_view
    before = v.table.item(0, 0).text()
    v.table.item(0, 0).setText("ZZ")
    assert v.table.item(0, 0).text() == before
    assert "not a valid hex byte" in v.status_label.text()


def test_bo_sua_khoi_phuc_noi_dung_da_doc(qtbot, connected_window: MainWindow) -> None:
    _read(qtbot, connected_window)
    v = connected_window.memory_view
    before = v.table.item(0, 0).text()
    _edit_cell(connected_window, 0, (int(before, 16) + 7) & 0xFF)
    v._revert()
    assert v.table.item(0, 0).text() == before
    assert not v.write_btn.isEnabled()


def test_ghi_roi_doc_lai_thay_dung_gia_tri(qtbot, connected_window: MainWindow) -> None:
    _read(qtbot, connected_window, size=16)
    v = connected_window.memory_view

    new_values = [0xDE, 0xAD, 0xBE, 0xEF]
    for i, val in enumerate(new_values):
        _edit_cell(connected_window, i, val)

    v.do_write()
    qtbot.waitUntil(lambda: not connected_window.busy, timeout=5000)
    qtbot.waitUntil(lambda: "Wrote" in v.status_label.text()
                    or "Read" in v.status_label.text(), timeout=5000)

    assert connected_window.session.read(MEM_BASE, 4) == bytes(new_values)
    _read(qtbot, connected_window, size=16)
    assert [v.table.item(0, i).text() for i in range(4)] == ["DE", "AD", "BE", "EF"]


def test_hien_trang_ecu_va_trang_xcp(qtbot, connected_window: MainWindow) -> None:
    v = connected_window.memory_view
    v.refresh_pages()
    qtbot.waitUntil(lambda: v.xcp_page_label.text() not in ("", "—"), timeout=5000)
    assert v.ecu_page_label.text() == str(WORKING_PAGE)
    assert v.xcp_page_label.text() == str(WORKING_PAGE)


def test_doi_trang_xcp_cap_nhat_chi_bao(qtbot, connected_window: MainWindow) -> None:
    v = connected_window.memory_view
    v.page_spin.setValue(1)
    v.mode_combo.setCurrentIndex(0)                # trang XCP
    v._on_set_page()
    qtbot.waitUntil(lambda: v.xcp_page_label.text() == "1", timeout=5000)
    assert v.ecu_page_label.text() == "0", "đổi trang XCP không được đụng trang ECU"
    assert "reference page" in v.status_label.text()


def test_write_protected_hien_nut_chuyen_ve_working_page(
    qtbot, connected_window: MainWindow, monkeypatch
) -> None:
    import xcptool.ui.main_window as mw

    w = connected_window
    w.session.set_page(0, 1, PageMode.XCP)          # XCP nhìn vào ROM
    _read(qtbot, w, size=16)

    asked: list[str] = []
    monkeypatch.setattr(mw, "ask_switch_to_working_page",
                        lambda parent, detail: asked.append(detail) or True)

    _edit_cell(w, 0, 0x42)
    w.memory_view.do_write()
    qtbot.waitUntil(lambda: bool(asked), timeout=5000)

    assert "reference page" in asked[0].lower() or "ROM" in asked[0]

    # user đồng ý → công cụ tự chuyển trang rồi ghi lại, không bắt làm thủ công
    qtbot.waitUntil(lambda: w.session.get_page(0, PageMode.XCP) == WORKING_PAGE,
                    timeout=5000)
    qtbot.waitUntil(lambda: w.session.read(MEM_BASE, 1) == b"\x42", timeout=5000)


def test_write_protected_tu_choi_thi_khong_doi_gi(
    qtbot, connected_window: MainWindow, monkeypatch
) -> None:
    import xcptool.ui.main_window as mw

    w = connected_window
    w.session.set_page(0, 1, PageMode.XCP)
    _read(qtbot, w, size=16)
    monkeypatch.setattr(mw, "ask_switch_to_working_page", lambda parent, detail: False)

    _edit_cell(w, 0, 0x99)
    w.memory_view.do_write()
    qtbot.wait(300)

    assert w.session.get_page(0, PageMode.XCP) == 1, "user nói không thì đừng đổi trang"


def test_copy_page_chay_qua_session(qtbot, connected_window: MainWindow) -> None:
    w = connected_window
    w.session.write(MEM_BASE, b"\x11\x22")
    v = w.memory_view
    v.copy_src_spin.setValue(1)                     # ROM
    v.copy_dst_spin.setValue(0)                     # → RAM
    v._on_copy_page()
    qtbot.waitUntil(lambda: not w.busy, timeout=5000)
    assert w.session.read(MEM_BASE, 2) != b"\x11\x22", "copy page phải xoá thay đổi"


def test_ecu_khong_ho_tro_cal_pag_thi_bao_ro(qtbot, cfg, monkeypatch) -> None:
    from xcptool.session.fake import FakeBehavior, FakeSession
    from xcptool.ui import errors

    session = FakeSession(FakeBehavior(supports_cal_pag=False))
    w = MainWindow(session)
    qtbot.addWidget(w)
    w.connect_to(cfg)
    qtbot.waitUntil(lambda: not w.busy, timeout=5000)

    shown: list[BaseException] = []
    monkeypatch.setattr(errors, "show_error", lambda parent, e: shown.append(e))
    w.memory_view.refresh_pages()
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)

    title, body = errors.describe(shown[0])
    assert "not supported" in title.lower()
    assert "CAL/PAG" in body
    w.close()


def test_doc_khi_chua_ket_noi_khong_lam_vo_app(qtbot, window: MainWindow) -> None:
    window.memory_view.addr_edit.setText(ADDR)
    window.memory_view.do_read()
    qtbot.wait(200)
    assert window.memory_view.table.rowCount() == 0
