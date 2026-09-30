"""Tích hợp end-to-end: DTO theo caps của ECU, đi qua ĐÚNG RealSession.start_daq().

Fakeslave trên virtual bus phát DTO theo `id_field_type`, timestamp size/unit/ticks
cấu hình được; master phải tự suy ra layout từ caps rồi decode đúng mẫu.
"""

from __future__ import annotations

import time

import can
import pytest

from xcptool.devtools.fakeslave import FakeSlave, SlaveConfig
from xcptool.master.constants import Cmd
from xcptool.master.daq import (
    DaqSignal as MasterSignal,
    DtoFormat,
    OdtSignalLayout,
    PredefinedDaqList,
    TimestampAccumulator,
    configure_daq_predefined,
    decode_dto,
)
from xcptool.session.api import BusConfig, DaqList, DaqSignal, SamplePoint
from xcptool.session.real import RealSession


def _bus(channel: str, cfg: SlaveConfig) -> BusConfig:
    return BusConfig(backend="virtual", channel=channel, cro_id=cfg.cro_id,
                     dto_id=cfg.dto_id, t1_timeout_s=0.5)


def _collect(session: RealSession, name: str, want: int = 5,
             timeout: float = 2.0) -> list[SamplePoint]:
    deadline = time.perf_counter() + timeout
    got: list[SamplePoint] = []
    while time.perf_counter() < deadline and len(got) < want:
        time.sleep(0.02)
        got += [s for s in session.drain_daq(200) if s.name == name]
    return got


# (id_field_type, ts_size, unit_code, ticks, ODT 0 còn chỗ cho signal 1 B?)
_CASES = [
    (0, 4, 0x1, 1, True),
    (1, 2, 0x6, 10, True),
    (2, 1, 0x6, 1, True),
    (3, 2, 0x6, 10, True),
    (3, 4, 0x1, 1, False),   # header 4 B + TS 4 B = 8 B: ODT 0 hết chỗ, signal sang ODT 1 (không TS)
]


@pytest.mark.parametrize("id_type,ts_size,unit,ticks,ts_on_sample", _CASES)
def test_start_daq_decodes_every_header_type(
    channel: str, id_type: int, ts_size: int, unit: int, ticks: int, ts_on_sample: bool,
) -> None:
    cfg = SlaveConfig(channel=channel, id_field_type=id_type, timestamp_size=ts_size,
                      timestamp_unit_code=unit, timestamp_ticks=ticks)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(channel, cfg))
        assert session.caps is not None and session.caps.daq is not None
        assert session.caps.daq.id_field_type == id_type

        addr = cfg.mem_base
        slave.poke(addr, b"\x5A")
        session.start_daq([DaqList(signals=[DaqSignal("b", addr, 0, 1, "UINT8")],
                                   event=0, timestamp=True)])
        samples = _collect(session, "b")
        session.stop_daq()
    session.close()

    assert len(samples) >= 3, "không nhận đủ sample"
    assert all(s.value_raw == b"\x5A" for s in samples)
    stamps = [s.timestamp_ns for s in samples]
    if ts_on_sample:
        assert stamps == sorted(stamps)
        assert stamps[-1] > stamps[0]
    else:
        assert stamps == [0] * len(stamps)


@pytest.mark.parametrize("byte_order", ["little", "big"])
@pytest.mark.parametrize("id_type", [2, 3])
def test_word_daq_number_respects_slave_byte_order(
    channel: str, id_type: int, byte_order: str,
) -> None:
    cfg = SlaveConfig(channel=channel, id_field_type=id_type, byte_order=byte_order,
                      timestamp_size=2, timestamp_unit_code=0x6, timestamp_ticks=1)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(channel, cfg))
        addr = cfg.mem_base
        slave.poke(addr, b"\x5A")
        session.start_daq([DaqList(signals=[DaqSignal("b", addr, 0, 1, "UINT8")],
                                   event=0, timestamp=False)])
        samples = _collect(session, "b", want=3)
    session.close()
    assert samples and all(s.value_raw == b"\x5A" for s in samples)


@pytest.mark.parametrize("id_type", [1, 2, 3])
def test_static_ecu_relative_ids_use_the_physical_list_number(
    channel: str, id_type: int,
) -> None:
    """List 0 là predefined nên master dùng list vật lý 1: DTO kiểu 1–3 mang số 1
    (không phải số thứ tự trong cấu hình), nên decode đúng chứng tỏ khoá đúng."""
    cfg = SlaveConfig(channel=channel, daq_dynamic=False, min_daq=3, max_daq=3,
                      static_predefined_lists=frozenset({0}), id_field_type=id_type)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(channel, cfg))
        addr = cfg.mem_base
        slave.poke(addr, b"\x5A")
        session.start_daq([DaqList(signals=[DaqSignal("b", addr, 0, 1, "UINT8")],
                                   event=0, timestamp=False)])
        samples = _collect(session, "b", want=3)
        assert slave.daq_entries(1, 0), "signal phải nằm ở list vật lý 1"
        assert slave.daq_entries(0, 0) == []
    session.close()
    assert samples and all(s.value_raw == b"\x5A" for s in samples)


def test_caps_daq_none_keeps_legacy_layout(channel: str) -> None:
    """Review Focus #1: ECU không trả lời GET_DAQ_PROCESSOR_INFO → layout cũ."""
    cfg = SlaveConfig(channel=channel, supports_daq_info=False)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(channel, cfg))
        assert session.caps is not None and session.caps.daq is None
        addr = cfg.mem_base
        slave.poke(addr, b"\x5A")
        session.start_daq([DaqList(signals=[DaqSignal("b", addr, 0, 1, "UINT8")],
                                   event=0, timestamp=True)])
        samples = _collect(session, "b")
    session.close()
    assert len(samples) >= 3 and all(s.value_raw == b"\x5A" for s in samples)
    stamps = [s.timestamp_ns for s in samples]
    assert stamps == sorted(stamps) and stamps[-1] > stamps[0]


def test_timestamp_fixed_is_enabled_even_when_not_requested(channel: str) -> None:
    cfg = SlaveConfig(channel=channel, timestamp_fixed=True)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(channel, cfg))
        addr = cfg.mem_base
        slave.poke(addr, b"\x5A")
        session.start_daq([DaqList(signals=[DaqSignal("b", addr, 0, 1, "UINT8")],
                                   event=0, timestamp=False)])     # master KHÔNG xin timestamp
        samples = _collect(session, "b")
    session.close()
    assert len(samples) >= 3 and all(s.value_raw == b"\x5A" for s in samples)
    stamps = [s.timestamp_ns for s in samples]
    assert stamps == sorted(stamps) and stamps[-1] > stamps[0]


def test_timestamp_request_is_dropped_when_ecu_has_none(channel: str) -> None:
    cfg = SlaveConfig(channel=channel, timestamp_supported=False, timestamp_size=4)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(channel, cfg))
        addr = cfg.mem_base
        slave.poke(addr, b"\x5A")
        session.start_daq([DaqList(signals=[DaqSignal("b", addr, 0, 1, "UINT8")],
                                   event=0, timestamp=True)])
        samples = _collect(session, "b", want=3)
        assert slave._daq_modes[0]["mode"] & 0x10 == 0     # master không đặt bit timestamp
    session.close()
    assert samples and all(s.value_raw == b"\x5A" for s in samples)
    assert all(s.timestamp_ns == 0 for s in samples)


# ── list predefined ──────────────────────────────────────────────────────────

def _predefined_cfg(channel: str, **extra: object) -> SlaveConfig:
    return SlaveConfig(channel=channel, daq_dynamic=False, min_daq=1, max_daq=1,
                       static_predefined_lists=frozenset({0}), **extra)  # type: ignore[arg-type]


def test_predefined_list_with_relative_header(channel: str) -> None:
    cfg = _predefined_cfg(channel, id_field_type=1)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(channel, cfg))
        master = session._master  # type: ignore[attr-defined]
        addr = cfg.mem_base
        expected = b"\x39\x05"
        slave.poke(addr, expected)
        slave.set_predefined_daq_content(0, 0, [(0xFF, 2, 0, addr)])

        sig = MasterSignal("val", addr, 0, 2, "UINT16")
        layout = OdtSignalLayout(signal=sig, frame_offset=2)    # header 2 B, không timestamp
        pl = PredefinedDaqList(daq=0, odts=[[layout]], event=0, timestamp=False)
        table = configure_daq_predefined(master, [pl])
        assert set(table) == {(0, 0)}

        fmt = DtoFormat.from_slave_caps(master.caps)
        sniffer = can.Bus(interface="virtual", channel=channel, receive_own_messages=False)
        try:
            deadline = time.perf_counter() + 1.0
            frame: bytes | None = None
            while time.perf_counter() < deadline and frame is None:
                msg = sniffer.recv(0.05)
                if (msg is not None and msg.arbitration_id == cfg.dto_id
                        and msg.data[0] == 0 and msg.data[1] == 0):
                    frame = bytes(msg.data)
            assert frame is not None, "không nhận được DTO"
            samples = decode_dto(frame, table, TimestampAccumulator.from_format(fmt), fmt)
            assert [s.value_raw for s in samples if s.name == "val"] == [expected]
        finally:
            sniffer.shutdown()
    session.close()


def test_predefined_offset_overlapping_header_is_rejected_before_any_command(
    channel: str,
) -> None:
    cfg = _predefined_cfg(channel, id_field_type=1)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(channel, cfg))
        master = session._master  # type: ignore[attr-defined]
        sig = MasterSignal("val", cfg.mem_base, 0, 2, "UINT16")
        layout = OdtSignalLayout(signal=sig, frame_offset=1)    # header kiểu 1 là 2 B
        pl = PredefinedDaqList(daq=0, odts=[[layout]], event=0, timestamp=False)
        with pytest.raises(ValueError, match="frame_offset"):
            configure_daq_predefined(master, [pl])
        assert int(Cmd.SET_DAQ_LIST_MODE) not in slave.commands_seen
    session.close()
