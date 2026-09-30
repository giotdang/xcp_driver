"""Fakeslave phải nói đúng caps và phát đúng DTO — nếu không, test end-to-end
ở Task 6 không có gì để kiểm chứng."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from xcptool.devtools.fakeslave import FakeSlave, SlaveConfig
from xcptool.session.api import BusConfig, SlaveError, SlaveCaps
from xcptool.session.real import RealSession


@contextmanager
def connected(cfg: SlaveConfig) -> Iterator[tuple[RealSession, SlaveCaps, FakeSlave]]:
    bus = BusConfig(backend="virtual", channel=cfg.channel, cro_id=cfg.cro_id,
                    dto_id=cfg.dto_id, pad_dlc=cfg.pad_dlc, t1_timeout_s=0.5)
    session = RealSession()
    try:
        with FakeSlave(cfg) as slave:
            yield session, session.connect(bus), slave
    finally:
        session.close()


@pytest.mark.parametrize("id_type", [0, 1, 2, 3])
def test_caps_report_identification_field_type(channel: str, id_type: int) -> None:
    with connected(SlaveConfig(channel=channel, id_field_type=id_type)) as (_, caps, _s):
        assert caps.daq is not None
        assert caps.daq.id_field_type == id_type


@pytest.mark.parametrize("overload", ["none", "pid_msb", "event"])
def test_caps_report_overload_indication(channel: str, overload: str) -> None:
    with connected(SlaveConfig(channel=channel, overload=overload)) as (_, caps, _s):
        assert caps.daq is not None
        assert caps.daq.overload == overload


def test_caps_report_timestamp_fixed(channel: str) -> None:
    with connected(SlaveConfig(channel=channel, timestamp_fixed=True)) as (_, caps, _s):
        assert caps.daq is not None
        assert caps.daq.timestamp_fixed is True


def test_timestamp_not_supported_is_reported_even_with_garbage_mode(channel: str) -> None:
    """Fakeslave vẫn trả TIMESTAMP_MODE (size 4) nhưng xoá bit TIMESTAMP_SUPPORTED."""
    cfg = SlaveConfig(channel=channel, timestamp_supported=False, timestamp_size=4)
    with connected(cfg) as (_, caps, _s):
        assert caps.daq is not None
        assert caps.daq.timestamp_supported is False
        assert caps.daq.timestamp_size == 0


def test_set_daq_list_mode_refuses_to_disable_fixed_timestamp(channel: str) -> None:
    cfg = SlaveConfig(channel=channel, timestamp_fixed=True)
    with connected(cfg) as (session, _caps, _s):
        master = session._master  # type: ignore[attr-defined]
        master.free_daq()
        master.alloc_daq(1)
        with pytest.raises(SlaveError):
            master.set_daq_list_mode(0, 0, 0x00, 1, 0)     # bit 4 = 0: tắt timestamp
        master.set_daq_list_mode(0, 0, 0x10, 1, 0)         # bật thì được


@pytest.mark.parametrize("byte_order,id_type,expected", [
    ("little", 0, bytes([12])),                 # PID = first_pid + odt
    ("little", 1, bytes([2, 3])),               # ODT, DAQ (BYTE)
    ("little", 2, bytes([2, 3, 1])),            # ODT, DAQ_lo, DAQ_hi (daq = 259)
    ("big",    2, bytes([2, 1, 3])),
    ("little", 3, bytes([2, 0, 3, 1])),         # ODT, FILL, DAQ_lo, DAQ_hi
    ("big",    3, bytes([2, 0, 1, 3])),
])
def test_dto_header_layout(channel: str, byte_order: str, id_type: int, expected: bytes) -> None:
    cfg = SlaveConfig(channel=channel, byte_order=byte_order, id_field_type=id_type)
    with FakeSlave(cfg) as slave:
        assert slave._dto_header(daq=259, odt_idx=2, first_pid=10) == expected


def test_timestamp_ticks_follow_unit_ticks_and_width(channel: str) -> None:
    """Đơn vị 1 ms, ticks 10, 2 byte: 2,5 ms → 25; 7 s → 70000 cắt 16 bit = 4464."""
    cfg = SlaveConfig(channel=channel, timestamp_size=2, timestamp_unit_code=0x6,
                      timestamp_ticks=10)
    with FakeSlave(cfg) as slave:
        assert slave._timestamp_ticks(2_500_000) == 25
        assert slave._timestamp_ticks(7_000_000_000) == 70000 & 0xFFFF


def test_timestamp_ticks_default_is_32bit_10ns(channel: str) -> None:
    with FakeSlave(SlaveConfig(channel=channel)) as slave:
        assert slave._timestamp_ticks(1_000) == 100
