"""F0 — FakeSession phải phủ hết contract, kể cả các hành vi tồi.

Nếu bản giả chỉ biết đường thành công thì nó vô dụng: cả GUI lẫn CLI sẽ chỉ được
test trên đường đẹp nhất, đúng đường mà bug không nằm ở đó.
"""

from __future__ import annotations

import threading
import time

import pytest

from xcptool.session.api import (
    BusConfig,
    BusError,
    BusyError,
    ConnState,
    NotConnectedError,
    OutOfRangeError,
    PageMode,
    Session,
    SlaveCaps,
    UnsupportedByEcuError,
    WriteProtectedError,
    XcpTimeoutError,
)
from xcptool.session.fake import MEM_BASE, MEM_SIZE, FakeBehavior, FakeSession


@pytest.fixture
def cfg() -> BusConfig:
    return BusConfig(backend="virtual", channel="fake0")


def test_khop_protocol() -> None:
    assert isinstance(FakeSession(), Session)


def test_list_devices_luon_co_hint_cho_kenh_hong() -> None:
    devices = FakeSession().list_devices()
    unavailable = [d for d in devices if not d.available]
    assert unavailable, "phải có kênh chưa cài driver — đó là đường CHÍNH, không phải biên"
    assert all(d.hint for d in unavailable), "kênh không dùng được phải nói rõ cần cài gì"
    assert any(d.available for d in devices)


def test_connect_tra_ve_caps_va_doi_theo_behavior(cfg: BusConfig) -> None:
    s = FakeSession(FakeBehavior(max_cto=12, max_dto=16))
    caps = s.connect(cfg)
    assert isinstance(caps, SlaveCaps)
    assert (caps.max_cto, caps.max_dto) == (12, 16)
    assert s.caps is caps
    assert s.state is ConnState.CONNECTED
    s.close()


def test_lenh_khi_chua_connect_nem_notconnected() -> None:
    s = FakeSession()
    with pytest.raises(NotConnectedError):
        s.read(MEM_BASE, 4)
    with pytest.raises(NotConnectedError):
        s.raw_command(b"\xff\x00")


def test_ghi_roi_doc_lai_dung_bit_for_bit(cfg: BusConfig) -> None:
    s = FakeSession()
    s.connect(cfg)
    payload = bytes(range(64))
    s.write(MEM_BASE + 0x100, payload)
    assert s.read(MEM_BASE + 0x100, 64) == payload
    s.close()


def test_doc_hai_lan_cho_cung_ket_qua(cfg: BusConfig) -> None:
    s = FakeSession()
    s.connect(cfg)
    assert s.read(MEM_BASE, 32) == s.read(MEM_BASE, 32)
    s.close()


def test_dia_chi_ngoai_vung_nem_outofrange(cfg: BusConfig) -> None:
    s = FakeSession()
    s.connect(cfg)
    with pytest.raises(OutOfRangeError):
        s.read(MEM_BASE + MEM_SIZE, 4)
    with pytest.raises(OutOfRangeError):
        s.read(0, 4)
    s.close()


def test_ghi_khi_xcp_o_reference_page_nem_writeprotected(cfg: BusConfig) -> None:
    s = FakeSession()
    s.connect(cfg)
    s.set_page(0, 1, PageMode.XCP)
    assert s.get_page(0, PageMode.XCP) == 1
    with pytest.raises(WriteProtectedError) as ei:
        s.write(MEM_BASE, b"\x01")
    assert ei.value.name == "CRC_WRITE_PROTECTED"
    # trang ECU độc lập với trang XCP
    assert s.get_page(0, PageMode.ECU) == 0
    s.close()


def test_copy_page_mang_du_lieu_sang_trang_khac(cfg: BusConfig) -> None:
    s = FakeSession()
    s.connect(cfg)
    s.write(MEM_BASE, b"\xaa\xbb")
    assert s.read(MEM_BASE, 2) == b"\xaa\xbb"
    s.copy_page(0, 1, 0, 0)                    # ROM → RAM: xoá thay đổi
    assert s.read(MEM_BASE, 2) != b"\xaa\xbb"
    s.close()


def test_ecu_khong_ho_tro_cal_pag(cfg: BusConfig) -> None:
    s = FakeSession(FakeBehavior(supports_cal_pag=False))
    s.connect(cfg)
    with pytest.raises(UnsupportedByEcuError):
        s.get_page(0, PageMode.XCP)
    s.close()


def test_raw_command_tra_ve_frame_loi_thay_vi_nem(cfg: BusConfig) -> None:
    s = FakeSession()
    s.connect(cfg)
    res = s.raw_command(b"\x55")               # lệnh không tồn tại
    assert res[0] == 0xFE, "raise_on_error=False thì lỗi phải TRẢ VỀ, không ném"
    with pytest.raises(Exception):
        s.raw_command(b"\x55", raise_on_error=True)
    s.close()


def test_raw_command_connect_tra_ve_ff(cfg: BusConfig) -> None:
    s = FakeSession()
    s.connect(cfg)
    assert s.raw_command(b"\xff\x00")[0] == 0xFF
    s.close()


def test_lenh_chong_nhau_nem_busy(cfg: BusConfig) -> None:
    s = FakeSession(FakeBehavior(command_delay_s=0.3))
    s.connect(cfg)
    errors: list[BaseException] = []
    started = threading.Event()

    def slow() -> None:
        started.set()
        try:
            s.read(MEM_BASE, 4)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t = threading.Thread(target=slow)
    t.start()
    started.wait(1.0)
    time.sleep(0.05)
    with pytest.raises(BusyError):
        s.read(MEM_BASE, 4)
    t.join(2.0)
    assert not errors
    s.close()


def test_rut_day_giua_chung_chuyen_sang_error(cfg: BusConfig) -> None:
    s = FakeSession(FakeBehavior(fail_after_commands=2))
    s.connect(cfg)
    s.read(MEM_BASE, 4)
    s.read(MEM_BASE, 4)
    with pytest.raises(BusError):
        s.read(MEM_BASE, 4)
    assert s.state is ConnState.ERROR
    s.close()


def test_connect_co_the_nem_loi_da_cau_hinh(cfg: BusConfig) -> None:
    s = FakeSession(FakeBehavior(connect_error=XcpTimeoutError("ECU im lặng")))
    with pytest.raises(XcpTimeoutError):
        s.connect(cfg)
    assert s.state is ConnState.ERROR
    s.close()


def test_close_idempotent_va_khong_bao_gio_nem(cfg: BusConfig) -> None:
    s = FakeSession()
    s.close()                                   # chưa từng connect
    s.connect(cfg)
    s.close()
    s.close()                                   # gọi lại
    assert s.state is ConnState.DISCONNECTED


def test_close_cat_ngang_connect_dang_cho(cfg: BusConfig) -> None:
    s = FakeSession(FakeBehavior(connect_delay_s=3.0))
    result: list[object] = []

    def worker() -> None:
        try:
            result.append(s.connect(cfg))
        except BaseException as exc:  # noqa: BLE001
            result.append(exc)

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.2)
    started = time.monotonic()
    s.close()
    t.join(2.0)
    assert not t.is_alive(), "close() phải cắt ngang connect đang chờ"
    assert time.monotonic() - started < 2.0
    assert isinstance(result[0], BusError)


def test_session_dung_lai_duoc_sau_close(cfg: BusConfig) -> None:
    """UI huỷ kết nối bằng close() rồi cho user bấm Kết nối lại — phải chạy được."""
    s = FakeSession()
    s.connect(cfg)
    s.close()
    caps = s.connect(cfg)
    assert caps is not None and s.state is ConnState.CONNECTED
    s.close()


def test_drain_trace_khong_chan_va_ro_dan(cfg: BusConfig) -> None:
    s = FakeSession()
    assert s.drain_trace() == []
    s.connect(cfg)
    first = s.drain_trace()
    assert first, "CONNECT phải sinh trace"
    assert s.drain_trace() == [], "drain phải XOÁ entry đã lấy"
    assert [e.seq for e in first] == sorted(e.seq for e in first)
    s.close()


def test_ring_buffer_co_tran_va_dem_dropped(cfg: BusConfig) -> None:
    s = FakeSession(FakeBehavior(trace_capacity=100))
    s.connect(cfg)
    s.start_flood(rate_hz=20_000)
    time.sleep(0.4)
    s.stop_flood()
    assert s.dropped_frames > 0, "quá trần phải tăng dropped_frames"
    assert len(s.drain_trace(10_000)) <= 100, "RAM không được phình quá trần"
    s.close()


def test_flood_dung_han_khi_close(cfg: BusConfig) -> None:
    s = FakeSession()
    s.connect(cfg)
    s.start_flood(rate_hz=5000)
    time.sleep(0.1)
    s.close()
    assert all(not t.name.startswith("fake-flood") for t in threading.enumerate())
