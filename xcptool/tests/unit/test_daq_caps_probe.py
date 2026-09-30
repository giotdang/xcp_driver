"""Probe DaqCaps từ frame GET_DAQ_PROCESSOR_INFO / GET_DAQ_RESOLUTION_INFO.

Dùng các frame ví dụ trong ASAM XCP v1.0 Part 5 (mục 1.3.1) làm dữ liệu thật.
Không cần bus: thay `_optional` bằng hàm trả bytes cho sẵn.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from xcptool.master.constants import Cmd
from xcptool.master.core import XcpMaster
from xcptool.session.api import DaqCaps


def _probe(proc: str, res: str, byte_order: str | None = None) -> DaqCaps | None:
    master = XcpMaster.__new__(XcpMaster)
    master._caps = SimpleNamespace(byte_order=byte_order) if byte_order else None

    def _optional(payload: bytes) -> bytes:
        raw = proc if payload[0] == Cmd.GET_DAQ_PROCESSOR_INFO else res
        return bytes.fromhex(raw)

    master._optional = _optional  # type: ignore[method-assign]
    return master._probe_daq_caps()


def test_new_daq_caps_fields_have_legacy_defaults() -> None:
    """Code cũ dựng DaqCaps không biết 3 trường mới phải vẫn chạy."""
    caps = DaqCaps(
        max_daq=1, max_event_channel=1, min_daq=0, dynamic_daq=True,
        timestamp_supported=True, timestamp_size=4, timestamp_unit_ns=10,
        timestamp_ticks=1, pid_off_supported=False,
        granularity_odt_entry_daq=1, max_odt_entry_size_daq=7,
    )
    assert caps.id_field_type == 0
    assert caps.overload == "pid_msb"
    assert caps.timestamp_fixed is False


def test_part5_dynamic_example() -> None:
    """Part 5: FF 11 00 00 01 00 00 40 + FF 02 FD xx xx 62 0A 00."""
    caps = _probe("FF11000001000040", "FF02FD0000620A00")
    assert caps is not None
    assert caps.dynamic_daq is True
    assert caps.max_daq == 0
    assert caps.max_event_channel == 1
    assert caps.min_daq == 0
    assert caps.id_field_type == 1                 # DAQ_KEY_BYTE 0x40
    assert caps.overload == "none"                 # DAQ_PROPERTIES 0x11: bit 7-6 = 00
    assert caps.timestamp_supported is True
    assert caps.timestamp_size == 2                # TIMESTAMP_MODE 0x62: size = 2
    assert caps.timestamp_unit_ns == 1_000_000     # unit code 6 = 1 ms
    assert caps.timestamp_ticks == 10
    assert caps.timestamp_fixed is False
    assert caps.granularity_odt_entry_daq == 2
    assert caps.max_odt_entry_size_daq == 253


def test_part5_static_example() -> None:
    """Part 5: FF 10 01 00 01 00 00 40 (static, 1 DAQ list)."""
    caps = _probe("FF10010001000040", "FF02FD0000620A00")
    assert caps is not None
    assert caps.dynamic_daq is False
    assert caps.max_daq == 1
    assert caps.id_field_type == 1


def test_driver_like_response() -> None:
    """Dạng driver trong repo: DAQ_PROPERTIES 0x51, key byte 0, TIMESTAMP_MODE 0x14."""
    caps = _probe("FF51000000000000", "FF01070100140100")
    assert caps is not None
    assert caps.id_field_type == 0
    assert caps.overload == "pid_msb"              # bit 6
    assert caps.timestamp_supported is True
    assert caps.timestamp_size == 4
    assert caps.timestamp_unit_ns == 10            # unit code 1 = 10 ns
    assert caps.timestamp_ticks == 1
    assert caps.pid_off_supported is False


@pytest.mark.parametrize("key_byte,expected", [(0x00, 0), (0x40, 1), (0x80, 2), (0xC0, 3)])
def test_id_field_type_comes_from_key_byte_bits_7_6(key_byte: int, expected: int) -> None:
    proc = bytes([0xFF, 0x01, 0, 0, 0, 0, 0, key_byte]).hex()
    caps = _probe(proc, "FF01070100140100")
    assert caps is not None
    assert caps.id_field_type == expected


@pytest.mark.parametrize("code,expected", [(0, "none"), (1, "pid_msb"), (2, "event"), (3, "none")])
def test_overload_comes_from_daq_properties_bits_7_6(code: int, expected: str) -> None:
    """Mã 3 không hợp lệ theo spec → coi là không báo overrun."""
    proc = bytes([0xFF, 0x01 | (code << 6), 0, 0, 0, 0, 0, 0]).hex()
    caps = _probe(proc, "FF01070100140100")
    assert caps is not None
    assert caps.overload == expected


def test_timestamp_fixed_flag() -> None:
    caps = _probe("FF11000000000000", "FF010701001C0100")
    assert caps is not None
    assert caps.timestamp_fixed is True            # TIMESTAMP_MODE 0x1C: bit 3
    assert caps.timestamp_size == 4


def test_timestamp_not_supported_when_bit4_clear_even_if_mode_looks_valid() -> None:
    """Spec: bit TIMESTAMP_SUPPORTED = 0 → TIMESTAMP_MODE/TICKS không hợp lệ."""
    caps = _probe("FF01000000000000", "FF01070100140100")   # DAQ_PROPERTIES bit 4 = 0
    assert caps is not None
    assert caps.timestamp_supported is False
    assert caps.timestamp_size == 0


def test_timestamp_size_3_is_invalid() -> None:
    """Size 3 'Not allowed' theo spec → không hỗ trợ timestamp."""
    caps = _probe("FF11000000000000", "FF01070100130100")   # TIMESTAMP_MODE 0x13
    assert caps is not None
    assert caps.timestamp_supported is False
    assert caps.timestamp_size == 0


def test_multi_byte_fields_follow_slave_byte_order() -> None:
    """Big-endian: MAX_DAQ = 00 05, MAX_EVENT = 00 02, TICKS = 00 0A."""
    caps = _probe("FF11000500020040", "FF0107010062000A", byte_order="big")
    assert caps is not None
    assert caps.max_daq == 5
    assert caps.max_event_channel == 2
    assert caps.timestamp_ticks == 10
