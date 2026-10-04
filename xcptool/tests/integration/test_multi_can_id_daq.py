"""RealSession đầu-cuối: mỗi DAQ list phát trên CAN ID riêng, master vẫn ra đủ mẫu.

Trước đây frame trên ID lạ bị bỏ im lặng ở filter phần cứng và `_on_frame`, nên
người dùng chỉ thấy "không có dữ liệu" mà không biết vì sao.
"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest

from xcptool.devtools.fakeslave import FakeSlave, SlaveConfig
from xcptool.session.api import (
    BusConfig, ConnState, DaqList, DaqSignal, SamplePoint, XcpToolError,
)
from xcptool.session.real import RealSession

IDS = {0: 0x611, 1: 0x612}


def _lists(cfg: SlaveConfig) -> list[DaqList]:
    a = DaqSignal("a", cfg.mem_base, 0, 2, "UINT16")
    b = DaqSignal("b", cfg.mem_base + 2, 0, 2, "UINT16")
    return [DaqList(signals=[a], event=0, timestamp=False),
            DaqList(signals=[b], event=0, timestamp=False)]


def _bus(cfg: SlaveConfig, **kw) -> BusConfig:
    return BusConfig(backend="virtual", channel=cfg.channel, cro_id=cfg.cro_id,
                     dto_id=cfg.dto_id, pad_dlc=cfg.pad_dlc, t1_timeout_s=0.5, **kw)


def _drain_until(session: RealSession, pred, timeout: float = 1.5) -> list[SamplePoint]:
    got: list[SamplePoint] = []
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        time.sleep(0.02)
        got += session.drain_daq(200)
        if pred(got):
            break
    return got


def test_hai_list_hai_can_id_ra_du_mau(channel: str) -> None:
    cfg = SlaveConfig(channel=channel, daq_can_ids=IDS, max_daq=2)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(cfg, daq_can_ids=tuple(IDS.items())))
        slave.poke(cfg.mem_base, b"\x11\x00\x22\x00")
        session.start_daq(_lists(cfg))

        got = _drain_until(session, lambda g: {s.name for s in g} >= {"a", "b"})

    assert {s.name: s.value_raw for s in got if s.name in ("a", "b")} == {
        "a": b"\x11\x00", "b": b"\x22\x00"}
    session.close()


def test_dto_sai_can_id_bi_bo_khong_giai_ma(channel: str) -> None:
    """Frame của list 0 (PID 0) tới trên ID của list 1 không được giải mã thành 'a'."""
    cfg = SlaveConfig(channel=channel, daq_can_ids=IDS, max_daq=2)
    session = RealSession()
    marker = bytes([0x12, 0x34])
    with FakeSlave(cfg):
        session.connect(_bus(cfg, daq_can_ids=tuple(IDS.items())))
        session.start_daq(_lists(cfg))
        session.drain_daq(10_000)

        session._on_daq_frame(bytes([0]) + marker, IDS[1])   # sai ID
        assert marker not in [s.value_raw for s in session.drain_daq(10_000)]

        session._on_daq_frame(bytes([0]) + marker, IDS[0])   # đúng ID
        assert marker in [s.value_raw for s in session.drain_daq(10_000)]
    session.close()


def test_ket_noi_tu_choi_khi_hai_list_cung_id(channel: str) -> None:
    cfg = SlaveConfig(channel=channel)
    session = RealSession()
    with FakeSlave(cfg):
        with pytest.raises(XcpToolError):
            session.connect(_bus(cfg, daq_can_ids=((0, 0x611), (1, 0x611))))
        assert session.state == ConnState.DISCONNECTED
    session.close()


def test_khong_cau_hinh_thi_nhu_cu(channel: str) -> None:
    cfg = SlaveConfig(channel=channel)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(cfg))
        slave.poke(cfg.mem_base, b"\xFF\x00")
        session.start_daq([DaqList(
            signals=[DaqSignal("temp", cfg.mem_base, 0, 2, "UINT16")],
            event=0, timestamp=False)])

        got = _drain_until(session, lambda g: any(s.name == "temp" for s in g))

    assert [s.value_raw for s in got if s.name == "temp"][0] == b"\xFF\x00"
    session.close()
