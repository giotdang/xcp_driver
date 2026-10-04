"""Master nhận DTO trên CAN ID riêng của DAQ list.

ID riêng chỉ chở DTO, nên byte 0xFF/0xFE trong dữ liệu không được hiểu là
response — nếu không, một giá trị đo trùng 0xFF làm hỏng lệnh đang chờ.
"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest

from xcptool.devtools.fakeslave import REFERENCE_PAGE, WORKING_PAGE, FakeSlave, SlaveConfig
from xcptool.session.api import BusConfig
from xcptool.session.real import RealSession


@pytest.fixture
def daq_id(slave_cfg: SlaveConfig) -> int:
    return slave_cfg.dto_id + 0x10


@pytest.fixture
def routed_cfg(bus_cfg: BusConfig, daq_id: int) -> BusConfig:
    return replace(bus_cfg, daq_can_ids=((0, daq_id),))


def _collect(session: RealSession) -> list[tuple[bytes, int]]:
    got: list[tuple[bytes, int]] = []
    session._master.set_daq_callback(lambda data, can_id: got.append((data, can_id)))
    return got


def _wait(pred, timeout: float = 1.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def test_frame_tren_id_rieng_toi_callback_kem_can_id(
    session: RealSession, routed_cfg: BusConfig, slave: FakeSlave, daq_id: int
) -> None:
    session.connect(routed_cfg)
    got = _collect(session)

    slave.send_raw(daq_id, b"\x01\x02\x03\x04")

    assert _wait(lambda: got)
    assert got[0] == (b"\x01\x02\x03\x04", daq_id)


def test_frame_id_rieng_byte_dau_0xFF_van_la_daq(
    session: RealSession, routed_cfg: BusConfig, slave: FakeSlave, daq_id: int
) -> None:
    session.connect(routed_cfg)
    session.drain_trace()
    got = _collect(session)

    slave.send_raw(daq_id, b"\xFF\xFE\x01\x02")

    assert _wait(lambda: got)
    entry = next(e for e in session.drain_trace() if e.can_id == daq_id)
    assert entry.kind == "daq"
    # Hàng đợi response không bị nhiễm: lệnh kế tiếp vẫn nhận đúng response của nó.
    for page in (REFERENCE_PAGE, WORKING_PAGE):   # ECU đang đọc trang nào cũng được
        slave.poke(slave.cfg.mem_base, b"\xAB\xCD", page)
    assert session.read(slave.cfg.mem_base, 2) == b"\xAB\xCD"


def test_frame_ngoai_rx_ids_van_bi_bo(
    session: RealSession, routed_cfg: BusConfig, slave: FakeSlave
) -> None:
    session.connect(routed_cfg)
    session.drain_trace()
    got = _collect(session)

    slave.send_raw(routed_cfg.dto_id + 0x50, b"\x01\x02\x03\x04")
    time.sleep(0.2)

    assert got == []
    assert session.drain_trace() == []


def test_khong_cau_hinh_id_rieng_thi_nhu_cu(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    session.connect(bus_cfg)
    got = _collect(session)

    slave.send_raw(bus_cfg.dto_id, b"\x01\x02\x03\x04")

    assert _wait(lambda: got)
    assert got[0] == (b"\x01\x02\x03\x04", bus_cfg.dto_id)
