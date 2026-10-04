"""`use_a2l_can`: connect() lấy ID/bitrate/DAQ_LIST_CAN_ID từ A2L, giữ nguyên giá
trị nhập tay để người dùng bỏ tích thì quay lại được."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from xcptool.devtools.fakeslave import FakeSlave, SlaveConfig
from xcptool.session.api import BusConfig, ConnState, DaqList, DaqSignal, XcpToolError
from xcptool.session.fake import FakeSession
from xcptool.session.real import RealSession

IDS = {0: 0x611, 1: 0x612}


def _a2l_text(cfg: SlaveConfig, with_can: bool = True) -> str:
    can = f"""
/begin XCP_ON_CAN
  0x0100
  CAN_ID_MASTER 0x{cfg.cro_id:X}
  CAN_ID_SLAVE 0x{cfg.dto_id:X}
  BAUDRATE 500000
  MAX_DLC_REQUIRED
  /begin DAQ_LIST_CAN_ID 0 FIXED 0x611 /end DAQ_LIST_CAN_ID
  /begin DAQ_LIST_CAN_ID 1 FIXED 0x612 /end DAQ_LIST_CAN_ID
/end XCP_ON_CAN""" if with_can else "/begin PROTOCOL_LAYER 0x0100 /end PROTOCOL_LAYER"
    return f"""/begin PROJECT p ""
  /begin MODULE m ""
    /begin IF_DATA XCP
{can}
    /end IF_DATA
  /end MODULE
/end PROJECT
"""


def _a2l_file(tmp_path: Path, cfg: SlaveConfig, with_can: bool = True) -> Path:
    p = tmp_path / "ecu.a2l"
    p.write_text(_a2l_text(cfg, with_can), encoding="utf-8")
    return p


def _wrong_ids_cfg(channel: str) -> BusConfig:
    """ID tay SAI hoàn toàn — chỉ kết nối được nếu thật sự dùng ID của A2L."""
    return BusConfig(backend="virtual", channel=channel, cro_id=0x100, dto_id=0x101,
                     t1_timeout_s=0.5, use_a2l_can=True)


def test_use_a2l_can_ket_noi_duoc_du_cfg_tay_sai_id(channel: str, tmp_path: Path) -> None:
    cfg = SlaveConfig(channel=channel, daq_can_ids=IDS, max_daq=2)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.load_a2l(_a2l_file(tmp_path, cfg))
        session.connect(_wrong_ids_cfg(channel))
        slave.poke(cfg.mem_base, b"\x11\x00\x22\x00")
        session.start_daq([
            DaqList([DaqSignal("a", cfg.mem_base, 0, 2, "UINT16")], event=0, timestamp=False),
            DaqList([DaqSignal("b", cfg.mem_base + 2, 0, 2, "UINT16")], event=0, timestamp=False),
        ])
        names: set[str] = set()
        end = time.perf_counter() + 1.5
        while time.perf_counter() < end and not names >= {"a", "b"}:
            time.sleep(0.02)
            names |= {s.name for s in session.drain_daq(200)}

    assert names >= {"a", "b"}
    session.close()


def test_khong_a2l_thi_loi_ro_rang(channel: str) -> None:
    session = RealSession()
    with pytest.raises(XcpToolError, match="A2L"):
        session.connect(_wrong_ids_cfg(channel))
    assert session.state == ConnState.DISCONNECTED
    session.close()


def test_a2l_khong_co_xcp_on_can_thi_loi(channel: str, tmp_path: Path) -> None:
    cfg = SlaveConfig(channel=channel)
    session = RealSession()
    session.load_a2l(_a2l_file(tmp_path, cfg, with_can=False))
    with pytest.raises(XcpToolError, match="XCP_ON_CAN"):
        session.connect(_wrong_ids_cfg(channel))
    assert session.state == ConnState.DISCONNECTED
    session.close()


def test_remember_luu_cfg_goc(channel: str, tmp_path: Path) -> None:
    cfg = SlaveConfig(channel=channel)
    session = RealSession()
    with FakeSlave(cfg):
        session.load_a2l(_a2l_file(tmp_path, cfg))
        session.connect(_wrong_ids_cfg(channel))

        saved = session.load_config()
    assert (saved.cro_id, saved.dto_id) == (0x100, 0x101)   # tay, không phải của A2L
    assert saved.use_a2l_can is True
    session.close()


def test_trace_ghi_dong_cau_hinh_tu_a2l(channel: str, tmp_path: Path) -> None:
    cfg = SlaveConfig(channel=channel)
    session = RealSession()
    with FakeSlave(cfg):
        session.load_a2l(_a2l_file(tmp_path, cfg))
        session.connect(_wrong_ids_cfg(channel))

        entries = [e for e in session.drain_trace() if e.kind == "other"]
    assert entries and entries[0].decoded.startswith("CAN config từ A2L")
    session.close()


def test_fake_session_cung_quy_tac(tmp_path: Path) -> None:
    session = FakeSession()
    with pytest.raises(XcpToolError, match="A2L"):
        session.connect(BusConfig(backend="virtual", channel="fake0", use_a2l_can=True))
    session.close()
