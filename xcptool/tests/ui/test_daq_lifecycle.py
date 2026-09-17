"""DAQ Start/Stop lifecycle wiring ở MainWindow — 2 bug thật:

1. `stop_daq()` không có `on_err` — ECU trả lỗi cho STOP_SYNCH thì
   `measurement_view.on_daq_stopped()` không bao giờ chạy, UI kẹt ở trạng
   thái "đang đo", nút Start vẫn bị khoá.
2. `do_disconnect()`/mất kết nối không reset `measurement_view` — nếu DAQ
   đang chạy lúc disconnect (bấm nút hay rớt kết nối), UI vẫn hiện "đang đo"
   dù phiên đã đóng.

RealSession.stop_daq()/_teardown() đã tự dọn state của CHÍNH NÓ (callback,
pid table) đúng cách từ trước — 2 bug này thuần là thiếu dây nối ở tầng UI
(MainWindow), không phải lỗi ở session/protocol.
"""

from __future__ import annotations

from xcptool.session.api import ConnState, XcpToolError
from xcptool.ui.main_window import MainWindow


def test_stop_daq_error_still_resets_measurement_view(
    qtbot, connected_window: MainWindow, monkeypatch
) -> None:
    """ECU trả lỗi cho STOP_SYNCH -> UI vẫn phải reset về 'không chạy' để
    Start Acquisition dùng lại được ngay, không được kẹt."""
    window = connected_window
    mv = window.measurement_view

    # Giả lập đang đo (không cần start_daq() thật — chỉ cần đúng state UI).
    mv.on_daq_started()
    assert mv.daq_running is True
    assert not mv.start_btn.isEnabled()
    assert mv.stop_btn.isEnabled()

    def _raise(*_a: object, **_k: object) -> None:
        raise XcpToolError("ECU từ chối STOP_SYNCH")

    monkeypatch.setattr(window.session, "stop_daq", _raise)

    window.stop_daq()
    qtbot.waitUntil(lambda: not window.busy, timeout=3000)

    assert mv.daq_running is False
    assert mv.start_btn.isEnabled()
    assert not mv.stop_btn.isEnabled()


def test_disconnect_resets_measurement_view_even_without_stop(
    qtbot, connected_window: MainWindow
) -> None:
    """Disconnect khi DAQ đang chạy — CHƯA bấm Stop trước đó — vẫn phải reset
    measurement_view, vì phiên đã đóng thì chắc chắn không còn đọc được gì."""
    window = connected_window
    mv = window.measurement_view

    mv.on_daq_started()
    assert mv.daq_running is True

    window.do_disconnect()
    qtbot.waitUntil(lambda: not window.busy, timeout=3000)
    qtbot.waitUntil(lambda: window.session.state is ConnState.DISCONNECTED, timeout=3000)

    assert mv.daq_running is False
    assert mv.start_btn.isEnabled()
    assert not mv.stop_btn.isEnabled()


def test_stop_daq_success_still_resets_measurement_view(
    qtbot, connected_window: MainWindow
) -> None:
    """Hồi quy — đường thành công (đã có sẵn) không được vỡ khi thêm on_err."""
    window = connected_window
    mv = window.measurement_view

    mv.on_daq_started()
    window.stop_daq()
    qtbot.waitUntil(lambda: not window.busy, timeout=3000)

    assert mv.daq_running is False
    assert mv.start_btn.isEnabled()
    assert not mv.stop_btn.isEnabled()
