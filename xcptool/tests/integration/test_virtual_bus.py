"""B0 — khung package chạy được: bus ảo, ECU giả, CONNECT."""

from __future__ import annotations

import can
import pytest

from xcptool.devtools.fakeslave import FakeSlave, SlaveConfig
from xcptool.session.api import BusConfig, ConnState
from xcptool.session.real import RealSession
from xcptool.transport.registry import open_transport


def test_virtual_bus_carries_a_frame(channel: str) -> None:
    """Nền của mọi test backend: hai bus ảo cùng channel nói chuyện được."""
    a = can.Bus(interface="virtual", channel=channel, receive_own_messages=False)
    b = can.Bus(interface="virtual", channel=channel, receive_own_messages=False)
    try:
        a.send(can.Message(arbitration_id=0x123, data=bytes(range(8)),
                           is_extended_id=False))
        msg = b.recv(1.0)
        assert msg is not None
        assert msg.arbitration_id == 0x123
        assert bytes(msg.data) == bytes(range(8))
    finally:
        a.shutdown()
        b.shutdown()


def test_transport_send_pads_to_eight_bytes(bus_cfg: BusConfig, slave: FakeSlave) -> None:
    """ECU khai MAX_DLC_REQUIRED → CRO một byte vẫn phải lên dây đủ 8 byte."""
    transport = open_transport(bus_cfg)
    try:
        on_wire = transport.send(bus_cfg.cro_id, b"\xfe")
        assert on_wire == b"\xfe" + b"\x00" * 7
    finally:
        transport.close()


def test_transport_does_not_pad_when_disabled(bus_cfg: BusConfig) -> None:
    transport = open_transport(bus_cfg.__class__(**{**bus_cfg.__dict__,
                                                    "pad_dlc": False}))
    try:
        assert transport.send(bus_cfg.cro_id, b"\xfe") == b"\xfe"
    finally:
        transport.close()


def test_connect_reaches_the_fake_slave(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    caps = session.connect(bus_cfg)

    assert session.state is ConnState.CONNECTED
    assert caps.max_cto == slave.cfg.max_cto
    assert caps.max_dto == slave.cfg.max_dto
    assert session.caps == caps


def test_connect_without_a_slave_times_out(
    session: RealSession, bus_cfg: BusConfig
) -> None:
    """Không có ECU nào trên bus → hết T1, không đơ và không traceback lạ."""
    from xcptool.session.api import XcpTimeoutError

    with pytest.raises(XcpTimeoutError):
        session.connect(bus_cfg)
    assert session.state is ConnState.DISCONNECTED


def test_disconnect_then_close(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    session.connect(bus_cfg)
    session.disconnect()
    assert session.state is ConnState.DISCONNECTED
    from xcptool.master.constants import Cmd
    assert int(Cmd.DISCONNECT) in slave.commands_seen


def test_slave_config_drives_capabilities(channel: str) -> None:
    """Đổi ECU giả thì SlaveCaps đổi theo — bằng chứng master không hardcode."""
    cfg = SlaveConfig(channel=channel, max_cto=12, max_dto=16, cro_id=0x123,
                      dto_id=0x124)
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    try:
        with FakeSlave(cfg):
            caps = session.connect(bus)
        assert (caps.max_cto, caps.max_dto) == (12, 16)
    finally:
        session.close()
