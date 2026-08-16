"""F1 — dialog chọn thiết bị + luồng CONNECT qua worker thread.

Cổng của mốc này: FakeSession trễ 3 giây → UI KHÔNG đơ, có spinner, huỷ được.
"UI không đơ" ở đây được đo bằng việc event loop vẫn xử lý được sự kiện trong
lúc lệnh đang chạy — chính là thứ mà một lời gọi thẳng trên UI thread phá vỡ.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from xcptool.session.api import BusConfig, ConnState, DriverMissingError
from xcptool.session.fake import FakeBehavior, FakeSession
from xcptool.ui.device_dialog import DeviceDialog
from xcptool.ui.main_window import MainWindow

SLOW_S = 3.0


def test_dialog_hien_ca_kenh_khong_dung_duoc(qtbot, host, session: FakeSession) -> None:
    dlg = DeviceDialog(host)
    devices = session.list_devices()
    dlg.set_devices(devices)
    assert dlg.list.count() == len(devices), "kênh thiếu driver vẫn phải hiện"


def test_chon_kenh_hong_thi_hien_hint_va_khoa_nut_ket_noi(
    qtbot, host, session: FakeSession
) -> None:
    dlg = DeviceDialog(host)
    devices = session.list_devices()
    dlg.set_devices(devices)

    broken = next(i for i, d in enumerate(devices) if not d.available)
    dlg.list.setCurrentRow(broken)
    assert not dlg.yesButton.isEnabled()
    assert devices[broken].hint in dlg.hint_label.text()

    good = next(i for i, d in enumerate(devices) if d.available)
    dlg.list.setCurrentRow(good)
    assert dlg.yesButton.isEnabled()


def test_nho_lua_chon_lan_truoc(qtbot, host) -> None:
    """"Nhớ lựa chọn" đi qua `Session.load_config()`, không qua file riêng của
    UI — dialog chỉ tự điền từ `initial` được truyền vào, xem session/api.py."""
    cfg = BusConfig(backend="virtual", channel="fake1", bitrate=250_000,
                    cro_id=0x600, dto_id=0x601)
    dlg = DeviceDialog(host, initial=cfg)
    assert dlg.cro_edit.text().lower().endswith("600")
    assert dlg.bitrate_combo.currentData() == 250_000


def test_khong_co_initial_thi_dung_mac_dinh_khong_vo(qtbot, host) -> None:
    """Không truyền `initial` (vd. `load_config()` chưa từng lưu gì) → mặc định
    từ `BusConfig`, dialog vẫn dựng được bình thường, không ném."""
    dlg = DeviceDialog(host)
    assert dlg.cro_edit.text() != ""
    assert dlg.bitrate_combo.currentData() == 500_000


def test_main_window_truyen_load_config_vao_dialog(qtbot, cfg: BusConfig, monkeypatch) -> None:
    """`open_device_dialog()` phải lấy `initial` từ `session.load_config()`,
    không tự đọc file — đây là điểm ép ranh giới thật của bản sửa này."""
    session = FakeSession()
    window = MainWindow(session)
    qtbot.addWidget(window)

    window.connect_to(cfg)
    qtbot.waitUntil(lambda: not window.busy, timeout=5000)
    assert session.load_config() == cfg

    from xcptool.ui import device_dialog as dd_mod

    seen: list[BusConfig | None] = []
    real_init = dd_mod.DeviceDialog.__init__

    def spy_init(self, parent=None, initial=None):
        seen.append(initial)
        real_init(self, parent, initial=initial)

    monkeypatch.setattr(dd_mod.DeviceDialog, "__init__", spy_init)
    monkeypatch.setattr(dd_mod.DeviceDialog, "exec", lambda self: False)

    window.open_device_dialog()

    assert seen == [cfg]
    window.close()


def test_detect_chay_tren_worker_khong_dong_bang_ui(qtbot, session: FakeSession) -> None:
    session.behavior.list_devices_delay_s = 0.8
    window = MainWindow(session)
    qtbot.addWidget(window)
    dlg = DeviceDialog(window)
    window._dialog = dlg

    ticks = []
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: ticks.append(time.monotonic()))
    heartbeat.start(20)

    window._detect_devices()
    assert not dlg.spinner.isHidden(), "phải có spinner trong lúc dò"
    qtbot.waitUntil(lambda: dlg.list.count() > 0, timeout=5000)
    heartbeat.stop()

    assert len(ticks) > 10, "event loop phải vẫn chạy trong lúc list_devices() chặn"
    assert dlg.spinner.isHidden()
    window.close()


def test_connect_cham_3_giay_khong_lam_don_ui(qtbot, cfg: BusConfig) -> None:
    session = FakeSession(FakeBehavior(connect_delay_s=SLOW_S))
    window = MainWindow(session)
    qtbot.addWidget(window)

    ticks: list[float] = []
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: ticks.append(time.monotonic()))
    heartbeat.start(20)

    started = time.monotonic()
    window.connect_to(cfg)
    assert window.busy
    assert not window.busy_ring.isHidden(), "phải có spinner"
    assert not window.cancel_btn.isHidden(), "phải huỷ được"

    qtbot.waitUntil(lambda: not window.busy, timeout=int(SLOW_S * 2000))
    heartbeat.stop()

    elapsed = time.monotonic() - started
    assert elapsed >= SLOW_S * 0.8, "test này chỉ có nghĩa nếu lệnh thật sự chậm"
    assert len(ticks) > SLOW_S * 1000 / 20 * 0.5, (
        f"event loop bị chặn: chỉ chạy {len(ticks)} nhịp trong {elapsed:.1f}s"
    )
    assert session.state is ConnState.CONNECTED
    window.close()


def test_huy_giua_chung_khong_treo_va_khong_ket_noi(qtbot, cfg: BusConfig) -> None:
    session = FakeSession(FakeBehavior(connect_delay_s=SLOW_S))
    window = MainWindow(session)
    qtbot.addWidget(window)

    window.connect_to(cfg)
    qtbot.wait(200)
    assert window.busy

    started = time.monotonic()
    window.cancel_busy()
    qtbot.waitUntil(lambda: not window.busy, timeout=3000)

    assert time.monotonic() - started < SLOW_S, "huỷ phải phản hồi ngay, không chờ hết 3s"
    assert session.state is not ConnState.CONNECTED
    window.close()


def test_status_bar_hien_caps_sau_khi_connect(qtbot, connected_window: MainWindow) -> None:
    caps = connected_window.session.caps
    text = connected_window.caps_label.text()
    assert f"MAX_CTO {caps.max_cto}" in text
    assert f"MAX_DTO {caps.max_dto}" in text
    assert "CAL" in text and "DAQ" in text
    assert "Đã kết nối" in connected_window.state_label.text()


def test_caps_khong_hardcode_ma_lay_tu_ecu(qtbot, cfg: BusConfig) -> None:
    session = FakeSession(FakeBehavior(max_cto=12, max_dto=32, supports_daq=False))
    window = MainWindow(session)
    qtbot.addWidget(window)
    window.connect_to(cfg)
    qtbot.waitUntil(lambda: not window.busy, timeout=5000)

    text = window.caps_label.text()
    assert "MAX_CTO 12" in text and "MAX_DTO 32" in text
    assert "DAQ" not in text, "ECU tắt DAQ thì status bar không được khoe DAQ"
    window.close()


def test_loi_thieu_driver_hien_hint_chu_khong_phai_traceback(
    qtbot, cfg: BusConfig, monkeypatch
) -> None:
    from xcptool.ui import errors

    exc = DriverMissingError("pcan", "PCAN-Basic driver")
    session = FakeSession(FakeBehavior(connect_error=exc))
    window = MainWindow(session)
    qtbot.addWidget(window)

    shown: list[BaseException] = []
    monkeypatch.setattr(errors, "show_error", lambda parent, e: shown.append(e))

    window.connect_to(cfg)
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)

    title, body = errors.describe(shown[0])
    assert "driver" in title.lower()
    assert "PCAN-Basic driver" in body
    assert "Traceback" not in body
    window.close()
