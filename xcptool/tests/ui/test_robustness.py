"""F5 — "không crash" là tiêu chí nghiệm thu, không phải lời chúc.

Mỗi test dưới đây tương ứng một dòng trong bảng DEV_PLAN.md §6 thuộc phần
frontend. Chúng cố tình đi vào những đường mà app hay chết: lỗi lọt khỏi slot,
lỗi trong thread nền, đóng app lúc đang bận, backend cư xử sai contract.
"""

from __future__ import annotations

import logging
import threading
import time

import pytest

from xcptool.session.api import (
    BusError,
    BusyError,
    ConnState,
    DeviceNotFoundError,
    DriverMissingError,
    MalformedResponseError,
    NotConnectedError,
    OutOfRangeError,
    SlaveError,
    UnsupportedByEcuError,
    WriteProtectedError,
    XcpTimeoutError,
    XcpToolError,
)
from xcptool.session.fake import MEM_BASE, FakeBehavior, FakeSession
from xcptool.ui import errors
from xcptool.ui.logging_setup import install_excepthooks, setup_logging
from xcptool.ui.main_window import MainWindow

ALL_ERRORS = [
    XcpToolError("lỗi chung"),
    BusError("bus-off"),
    DeviceNotFoundError("rút dây rồi"),
    DriverMissingError("pcan", "PCAN-Basic driver"),
    XcpTimeoutError("hết T1"),
    MalformedResponseError("frame ngắn hơn dự kiến"),
    SlaveError(0x20, "CRC_CMD_UNKNOWN", "ECU không biết lệnh này"),
    WriteProtectedError(0x23, "CRC_WRITE_PROTECTED", "đang ở reference page"),
    OutOfRangeError(0x22, "CRC_OUT_OF_RANGE", "ngoài vùng"),
    NotConnectedError("chưa connect"),
    BusyError("đang bận"),
    UnsupportedByEcuError("DAQ"),
]


# ── mọi XcpToolError đều thành câu đọc được ─────────────────────────────────

@pytest.mark.parametrize("exc", ALL_ERRORS, ids=lambda e: type(e).__name__)
def test_moi_loi_luong_truoc_thanh_thong_bao_doc_duoc(exc: XcpToolError) -> None:
    title, body = errors.describe(exc)
    assert title and body
    assert "Traceback" not in body
    assert "Exception" not in title
    assert not title.endswith("Error"), f"'{title}' là tên lớp, không phải câu cho user"


def test_loi_thieu_driver_noi_ro_can_cai_goi_nao() -> None:
    _, body = errors.describe(DriverMissingError("vector", "Vector XL Driver Library"))
    assert "Vector XL Driver Library" in body


def test_write_protected_goi_y_chuyen_trang() -> None:
    _, body = errors.describe(
        WriteProtectedError(0x23, "CRC_WRITE_PROTECTED", "reference page")
    )
    assert "working page" in body


def test_ngoai_le_ngoai_du_kien_van_ra_cau_xin_loi() -> None:
    title, body = errors.describe(RuntimeError("một lỗi lạ"))
    assert "ngoài dự kiến" in title
    assert "log" in body


# ── excepthook ──────────────────────────────────────────────────────────────

def test_excepthook_bat_loi_trong_slot_va_app_van_song(qtbot, window: MainWindow,
                                                       caplog) -> None:
    caught: list[BaseException] = []
    install_excepthooks(caught.append)

    boom = ValueError("nổ trong slot")
    with caplog.at_level(logging.CRITICAL):
        import sys

        try:
            raise boom
        except ValueError:
            sys.excepthook(*sys.exc_info())

    assert caught == [boom], "excepthook phải báo lên UI, không nuốt im lặng"
    assert any("Ngoại lệ chưa bắt" in r.message for r in caplog.records)
    assert window.isEnabled(), "app phải còn sống sau khi excepthook chạy"


def test_excepthook_cua_thread_nen_cung_duoc_bat(qtbot, caplog) -> None:
    caught: list[BaseException] = []
    install_excepthooks(caught.append)

    def boom() -> None:
        raise RuntimeError("nổ trong thread nền")

    with caplog.at_level(logging.CRITICAL):
        t = threading.Thread(target=boom, name="test-boom")
        t.start()
        t.join(2.0)

    assert caught and isinstance(caught[0], RuntimeError)


def test_notify_cua_excepthook_loi_thi_khong_nem_tiep(caplog) -> None:
    install_excepthooks(lambda exc: (_ for _ in ()).throw(ValueError("notify hỏng")))
    import sys

    with caplog.at_level(logging.CRITICAL):
        try:
            raise RuntimeError("gốc")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())      # không được ném ra ngoài


def test_bao_loi_tu_thread_khac_van_ve_ui_thread(qtbot, window: MainWindow,
                                                 monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        errors, "show_unexpected",
        lambda parent, exc, path: seen.append(threading.current_thread().name),
    )
    threading.Thread(
        target=lambda: window.report_unexpected(RuntimeError("từ thread nền")),
        name="worker-x",
    ).start()
    qtbot.waitUntil(lambda: bool(seen), timeout=3000)
    assert seen[0] == threading.main_thread().name, (
        "hộp thoại phải dựng trên UI thread, không phải thread ném lỗi"
    )


# ── không đụng widget từ thread khác ─────────────────────────────────────────

def test_moi_callback_cua_worker_chay_tren_ui_thread(qtbot, window: MainWindow,
                                                     cfg) -> None:
    threads: list[str] = []

    def record(_: object) -> None:
        threads.append(threading.current_thread().name)

    for _ in range(5):
        window.runner.run(window.session.list_devices, on_ok=record)
    qtbot.waitUntil(lambda: len(threads) == 5, timeout=5000)
    assert set(threads) == {threading.main_thread().name}


def test_loi_cua_worker_cung_ve_ui_thread(qtbot, window: MainWindow) -> None:
    threads: list[str] = []
    window.runner.run(
        lambda: (_ for _ in ()).throw(XcpTimeoutError("hết giờ")),
        on_err=lambda _: threads.append(threading.current_thread().name),
    )
    qtbot.waitUntil(lambda: bool(threads), timeout=5000)
    assert threads[0] == threading.main_thread().name


# ── đóng app ────────────────────────────────────────────────────────────────

def test_dong_app_khi_dang_ban_khong_treo(qtbot, cfg) -> None:
    session = FakeSession(FakeBehavior(connect_delay_s=3.0))
    window = MainWindow(session)
    qtbot.addWidget(window)
    window.connect_to(cfg)
    qtbot.wait(200)
    assert window.busy

    started = time.monotonic()
    window.close()
    elapsed = time.monotonic() - started

    assert elapsed < 3.0, f"đóng app mất {elapsed:.1f}s — đang chờ lệnh chạy xong"
    assert session.state is ConnState.DISCONNECTED


def test_dong_app_khi_bus_dang_loi(qtbot, cfg) -> None:
    session = FakeSession(FakeBehavior(fail_after_commands=0))
    window = MainWindow(session)
    qtbot.addWidget(window)
    window.connect_to(cfg)
    qtbot.waitUntil(lambda: not window.busy, timeout=5000)
    with pytest.raises(BusError):
        session.read(MEM_BASE, 4)
    assert session.state is ConnState.ERROR

    window.close()          # không được ném
    assert session.state is ConnState.DISCONNECTED


def test_backend_co_close_hong_thi_app_van_dong_duoc(qtbot, cfg) -> None:
    """`close()` ném là bug của backend, nhưng app không được chết theo."""
    session = FakeSession()

    def broken_close() -> None:
        raise RuntimeError("backend viết sai contract")

    session.close = broken_close  # type: ignore[method-assign]
    window = MainWindow(session)
    qtbot.addWidget(window)
    window.close()              # không ném ra ngoài là đạt


def test_drain_trace_hong_thi_dung_timer_chu_khong_spam_loi(qtbot, window: MainWindow,
                                                            caplog) -> None:
    def broken_drain(max_items: int = 5000):
        raise RuntimeError("backend hỏng")

    window.session.drain_trace = broken_drain  # type: ignore[method-assign]
    with caplog.at_level(logging.ERROR):
        window._poll_trace()
    assert not window.trace_timer.isActive()
    assert any("drain_trace" in r.message for r in caplog.records)


# ── trạng thái lỗi hiện lên UI ──────────────────────────────────────────────

def test_rut_day_giua_phien_hien_thong_bao_khong_traceback(
    qtbot, cfg, monkeypatch
) -> None:
    shown: list[BaseException] = []
    monkeypatch.setattr(errors, "show_error", lambda parent, e: shown.append(e))

    # Kết nối được, nhưng lệnh đầu tiên sau đó gặp "dây bị rút".
    session = FakeSession(FakeBehavior(fail_after_commands=0))
    window = MainWindow(session)
    qtbot.addWidget(window)
    window.connect_to(cfg)
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)

    assert isinstance(shown[0], BusError)
    _, body = errors.describe(shown[0])
    assert "Traceback" not in body
    qtbot.waitUntil(lambda: "LỖI" in window.state_label.text(), timeout=2000)

    # Lệnh tiếp theo bị chặn êm, không nổ thêm lần nữa.
    window.read_memory(MEM_BASE, 16)
    qtbot.wait(200)
    assert len(shown) == 1
    window.close()


def test_goi_lenh_chong_nhau_khong_deadlock(qtbot, connected_window: MainWindow) -> None:
    w = connected_window
    w.session.behavior.command_delay_s = 0.4
    w.read_memory(MEM_BASE, 16)
    assert w.busy
    w.read_memory(MEM_BASE, 16)          # bị chặn ngay bởi _guard, không xếp hàng
    qtbot.waitUntil(lambda: not w.busy, timeout=5000)
    assert w.session.state is ConnState.CONNECTED


# ── log ─────────────────────────────────────────────────────────────────────

def test_log_ghi_ra_file(tmp_path, monkeypatch) -> None:
    import xcptool.ui.logging_setup as ls

    monkeypatch.setattr(ls, "_log_path", None)
    monkeypatch.setattr(ls, "LOG_DIR", tmp_path)
    path = setup_logging(logging.INFO, log_dir=tmp_path)
    logging.getLogger("xcptool.test").error("một dòng lỗi")

    for handler in logging.getLogger().handlers:
        handler.flush()
    assert path.exists()
    assert "một dòng lỗi" in path.read_text(encoding="utf-8")


def test_thu_muc_log_khong_ghi_duoc_thi_van_chay(tmp_path, monkeypatch) -> None:
    import xcptool.ui.logging_setup as ls

    monkeypatch.setattr(ls, "_log_path", None)
    blocked = tmp_path / "khong-tao-duoc"
    blocked.write_text("đây là file, không phải thư mục", encoding="utf-8")
    setup_logging(logging.INFO, log_dir=blocked)     # không được ném
