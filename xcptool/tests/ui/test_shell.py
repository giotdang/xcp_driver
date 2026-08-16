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
    names = {window.stack.widget(i).objectName() for i in range(window.stack.count())}
    assert names == {"traceView", "consoleView", "memoryView"}


def test_chuyen_man_hinh(window: MainWindow) -> None:
    for view in (window.console_view, window.memory_view, window.trace_view):
        window.switch_to(view)
        assert window.stack.currentWidget() is view


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
