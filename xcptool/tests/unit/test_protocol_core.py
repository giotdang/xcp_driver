"""B1 — vòng lệnh: timeout T1, retry qua SYNCH, trace cho MỌI frame."""

from __future__ import annotations

import time

import pytest

from xcptool.devtools.fakeslave import FakeSlave, SlaveConfig
from xcptool.master.constants import Cmd, ErrCode
from xcptool.session.api import (
    BusConfig,
    NotConnectedError,
    SlaveError,
    WriteProtectedError,
    XcpTimeoutError,
)
from xcptool.session.real import RealSession


def test_trace_records_both_directions(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    session.connect(bus_cfg)
    entries = session.drain_trace()

    kinds = {e.kind for e in entries}
    assert "cmd" in kinds and "res" in kinds
    assert {e.direction for e in entries} == {"tx", "rx"}
    assert all(e.decoded for e in entries), "decoded không được rỗng"

    first_cmd = next(e for e in entries if e.kind == "cmd")
    assert first_cmd.can_id == bus_cfg.cro_id
    assert first_cmd.decoded == "CONNECT mode=0"
    # pad_dlc bật → frame trên dây đủ 8 byte, và trace ghi đúng thứ đã lên dây.
    assert len(first_cmd.data) == 8


def test_drain_trace_empties_the_buffer(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    session.connect(bus_cfg)
    assert session.drain_trace()
    assert session.drain_trace() == []


def test_frame_on_another_can_id_is_traced_as_other(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    """Frame lạ không được xử lý nhầm thành response của phiên."""
    session.connect(bus_cfg)
    session.drain_trace()

    stranger_id = bus_cfg.dto_id + 0x50
    slave.send_raw(stranger_id, b"\xff\x01\x02\x03")

    deadline = time.perf_counter() + 2.0
    others = []
    while time.perf_counter() < deadline and not others:
        others = [e for e in session.drain_trace() if e.kind == "other"]
        time.sleep(0.01)

    assert others, "frame trên CAN ID khác phải xuất hiện trong trace"
    assert others[0].can_id == stranger_id
    assert others[0].decoded == "FF 01 02 03"


def test_daq_frame_is_not_mistaken_for_a_response(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    """DTO và CRM dùng chung CAN ID — nhầm là hỏng cả phiên."""
    session.connect(bus_cfg)
    session.drain_trace()

    slave.send_raw(bus_cfg.dto_id, bytes([0x01, 1, 2, 3, 4, 5, 6, 7]))
    time.sleep(0.2)
    assert any(e.kind == "daq" for e in session.drain_trace())

    # Phiên vẫn khoẻ: lệnh kế tiếp vẫn nhận đúng response của nó.
    assert session.raw_command(bytes([Cmd.GET_STATUS]))[0] == 0xFF


def test_timeout_raises_and_retries_through_synch(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    """ECU nuốt một lệnh → master gửi SYNCH rồi thử lại, không bỏ cuộc ngay."""
    session.connect(bus_cfg)
    slave.poke(slave.cfg.mem_base, b"\xde\xad\xbe\xef")
    slave.commands_seen.clear()
    slave.cfg.drop_responses = 1

    assert session.read(slave.cfg.mem_base, 4) == b"\xde\xad\xbe\xef"
    assert int(Cmd.SYNCH) in slave.commands_seen
    assert slave.commands_seen.count(int(Cmd.SHORT_UPLOAD)) == 2


def test_raw_command_does_not_retry(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    """Console debug phải cho thấy đúng thứ đã xảy ra — tự thử lại là nói dối."""
    session.connect(bus_cfg)
    slave.commands_seen.clear()
    slave.cfg.drop_responses = 1

    with pytest.raises(XcpTimeoutError):
        session.raw_command(bytes([Cmd.GET_STATUS]))
    assert slave.commands_seen.count(int(Cmd.GET_STATUS)) == 1


def test_dead_ecu_gives_up_with_a_timeout_error(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    session.connect(bus_cfg)
    slave.cfg.drop_responses = 99

    started = time.perf_counter()
    with pytest.raises(XcpTimeoutError):
        session.read(slave.cfg.mem_base, 4)
    # Hai lần T1 chứ không phải treo vô hạn.
    assert time.perf_counter() - started < bus_cfg.t1_timeout_s * 4


def test_timeout_leaves_a_note_in_the_trace(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    session.connect(bus_cfg)
    session.drain_trace()
    slave.cfg.drop_responses = 1
    session.read(slave.cfg.mem_base, 4)

    notes = [e.note for e in session.drain_trace() if e.note]
    assert any("timeout T1" in n for n in notes)


def test_raw_command_returns_error_frames_instead_of_raising(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    """Console debug muốn nhìn byte thô, không muốn ngoại lệ."""
    session.connect(bus_cfg)
    resp = session.raw_command(b"\x01")           # lệnh không tồn tại
    assert resp[0] == 0xFE
    assert resp[1] == int(ErrCode.CMD_UNKNOWN)


def test_raw_command_can_raise_on_demand(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    session.connect(bus_cfg)
    with pytest.raises(SlaveError) as excinfo:
        session.raw_command(b"\x01", raise_on_error=True)
    assert excinfo.value.code == int(ErrCode.CMD_UNKNOWN)


def test_commands_before_connect_are_refused(session: RealSession) -> None:
    with pytest.raises(NotConnectedError):
        session.read(0x1000, 4)
    with pytest.raises(NotConnectedError):
        session.raw_command(b"\xfd")


def test_error_code_becomes_the_named_exception(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    session.connect(bus_cfg)
    slave.cfg.force_error = int(ErrCode.WRITE_PROTECTED)

    with pytest.raises(WriteProtectedError):
        session.write(slave.cfg.mem_base, b"\x01\x02")


def test_caps_is_none_before_connect(session: RealSession) -> None:
    assert session.caps is None
    assert session.dropped_frames == 0
    assert session.drain_trace() == []


def test_cto_is_clamped_to_what_a_frame_can_carry(channel: str) -> None:
    """ECU khai MAX_CTO=64 nhưng CAN chở 8 byte — hỏi 63 byte thì không ai trả lời được."""
    cfg = SlaveConfig(channel=channel, max_cto=64)
    bus = BusConfig(backend="virtual", channel=channel, cro_id=cfg.cro_id,
                    dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    try:
        with FakeSlave(cfg) as s:
            caps = session.connect(bus)
            s.poke(cfg.mem_base, bytes(range(16)))
            assert caps.max_cto == 64
            assert session.read(cfg.mem_base, 16) == bytes(range(16))
    finally:
        session.close()
