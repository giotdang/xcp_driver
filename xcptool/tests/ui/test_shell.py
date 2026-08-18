"""F0 — khung app: cửa sổ chính, menu, status bar, điều hướng."""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow

from xcptool.session.api import ConnState
from xcptool.ui.main_window import TRACE_POLL_MS, MainWindow


def test_cua_so_dung_duoc(window: MainWindow) -> None:
    assert isinstance(window, QMainWindow)
    assert window.windowTitle()
    window.show()
    assert window.isVisible()


def test_co_du_ba_man_hinh(window: MainWindow) -> None:
    # Views được đặt trong dock widget ở đáy thay vì trong stack
    dm = window.dock_manager
    assert dm is not None
    assert dm.trace_dock is not None
    assert dm.trace_dock.widget() is window.trace_view
    assert dm.console_dock is not None
    assert dm.console_dock.widget() is window.console_view
    assert dm.memory_dock is not None
    assert dm.memory_dock.widget() is window.memory_view


def test_chuyen_man_hinh(window: MainWindow) -> None:
    # switch_to với dock view sẽ show + raise dock tương ứng.
    # Dùng isHidden() vì isVisible() phụ thuộc cả parent window được show().
    dm = window.dock_manager
    for view, dock in (
        (window.trace_view, dm.trace_dock),
        (window.console_view, dm.console_dock),
        (window.memory_view, dm.memory_dock),
    ):
        window.switch_to(view)
        assert not dock.isHidden(), f"dock cho {view.objectName()} phải không-ẩn sau switch_to"


def test_menu_du_ba_muc(window: MainWindow) -> None:
    titles = [a.text() for a in window.menuBar().actions()]
    assert any("Phiên" in t for t in titles)
    assert any("Xem" in t for t in titles)
    assert any("Trợ giúp" in t for t in titles)


def test_status_bar_hien_trang_thai_ban_dau(window: MainWindow) -> None:
    assert "Chưa kết nối" in window.state_label.text()
    assert window.caps_label.text() == ""
    assert window.session.state is ConnState.DISCONNECTED


def test_timer_trace_chay_trong_khoang_30_50ms(window: MainWindow) -> None:
    assert 30 <= TRACE_POLL_MS <= 50, "contract yêu cầu gom frame theo timer 30–50 ms"
    assert window.trace_timer.isActive()


def test_ngat_ket_noi_bi_khoa_khi_chua_ket_noi(window: MainWindow) -> None:
    assert not window.act_disconnect.isEnabled()


def test_dong_cua_so_goi_close(window: MainWindow, qtbot) -> None:
    window.show()
    window.close()
    assert window.session.state is ConnState.DISCONNECTED
    assert not window.trace_timer.isActive()


def test_vung_debug_mo_mac_dinh(window: MainWindow) -> None:
    assert not window.dock_manager.is_debug_area_collapsed()
    assert window.dock_manager.debug_toggle_symbol == "▲"


def test_nut_toggle_nam_tren_titlebar_cua_dock_khong_phai_status_bar(
    window: MainWindow,
) -> None:
    """User yêu cầu: nút phải nằm ở góc trên-phải của chính docking window (đi
    theo khi float/kéo), không phải một nút rời trong status bar."""
    dm = window.dock_manager
    assert len(dm._debug_arrow_btns) == 2  # type: ignore[attr-defined]
    for btn in dm._debug_arrow_btns:  # type: ignore[attr-defined]
        assert btn.parent() in (dm.trace_dock.titleBarWidget(), dm.console_dock.titleBarWidget())
    assert not hasattr(window, "debug_toggle_btn"), "nút cũ ở status bar phải được gỡ bỏ"


def test_toggle_vung_debug_thu_nho_khong_an_dock(window: MainWindow) -> None:
    """Bug đã sửa: trước đây toggle gọi hide() lên chính dock chứa nút — dock
    biến mất kéo theo nút, không còn cách nào bấm lại. Giờ dock LUÔN hiện
    diện (title bar + nút luôn bấm được), chỉ nội dung bị ẩn + chiều cao co
    lại bằng title bar, giống nút minimize."""
    dm = window.dock_manager
    window.toggle_debug_area()
    assert dm.is_debug_area_collapsed()
    assert not dm.trace_dock.isHidden(), "dock KHÔNG được hide() — nút title bar phải luôn bấm được"
    assert not dm.console_dock.isHidden()
    assert dm.trace_dock.widget().isHidden(), "nội dung (không phải dock) mới là thứ bị ẩn"
    assert dm.console_dock.widget().isHidden()
    assert dm.debug_toggle_symbol == "▼"


def test_toggle_vung_debug_khong_dung_memory_dock(window: MainWindow) -> None:
    # Memory dock có toggle riêng qua View menu — nút này không được đụng tới.
    assert window.dock_manager.memory_dock.isHidden()  # mặc định ẩn
    window.toggle_debug_area()
    assert window.dock_manager.memory_dock.isHidden(), "toggle vùng debug không được động vào Memory dock"


def test_toggle_vung_debug_bam_lai_thi_mo_lai(window: MainWindow) -> None:
    dm = window.dock_manager
    window.toggle_debug_area()
    window.toggle_debug_area()
    assert not dm.is_debug_area_collapsed()
    assert not dm.trace_dock.widget().isHidden()
    assert not dm.console_dock.widget().isHidden()
    assert dm.debug_toggle_symbol == "▲"


def test_toggle_qua_nut_that_su_tren_titlebar_van_hoat_dong(window: MainWindow) -> None:
    """Mô phỏng đúng thao tác user: bấm vào NÚT (không gọi thẳng API) — nút
    này vẫn phải bấm được sau khi đã thu nhỏ, vì nó không hề bị ẩn theo dock."""
    dm = window.dock_manager
    btn = dm._debug_arrow_btns[0]  # type: ignore[attr-defined]
    btn.click()
    assert dm.is_debug_area_collapsed()
    assert not btn.isHidden(), "nút phải còn hiện để bấm lại lần nữa"
    btn.click()
    assert not dm.is_debug_area_collapsed()


def test_switch_to_trace_mo_lai_vung_debug_da_thu_nho(window: MainWindow) -> None:
    window.toggle_debug_area()
    assert window.dock_manager.debug_toggle_symbol == "▼"
    window.switch_to(window.trace_view)
    assert window.dock_manager.debug_toggle_symbol == "▲", (
        "switch_to phải tự mở lại vùng debug đã thu nhỏ, không chỉ raise() một tab rỗng"
    )
    assert not window.dock_manager.trace_dock.widget().isHidden()


def test_trace_table_row_height_thu_gon(window: MainWindow) -> None:
    # Mặc định TableBase khoá 38px/dòng — quá cao cho log dày đặc (DESIGN.md
    # phản hồi người dùng: thu nhỏ để hiện nhiều dòng trace hơn cùng lúc).
    height = window.trace_view.table.verticalHeader().defaultSectionSize()
    assert height < 38
    assert height > 0


def test_viet_khung_vien_dock_va_resize_handle(window: MainWindow) -> None:
    """User không thấy được viền/resize-handle của dock — QSS phải có style
    cho QDockWidget (viền) và QMainWindow::separator (thanh kéo resize)."""
    qss = window.styleSheet()
    assert "QDockWidget" in qss and "border" in qss
    assert "QMainWindow::separator" in qss
