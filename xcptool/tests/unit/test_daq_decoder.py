"""D4c unit tests — SamplePoint + TimestampAccumulator + decode_dto.

Không cần bus: test thuần logic decode trên bytes.
"""

from __future__ import annotations

import pytest

from xcptool.master.daq import (
    DaqSignal,
    OdtSignalLayout,
    PidEntry,
    SamplePoint,
    TimestampAccumulator,
    decode_dto,
)


def _sig(name: str, size: int, datatype: str = "UINT8") -> DaqSignal:
    return DaqSignal(name=name, address=0x8000_0000, ext=0, size=size, datatype=datatype)


def _pid_table(
    pid: int,
    odt_index: int,
    has_timestamp: bool,
    signals: list[tuple[DaqSignal, int]],
) -> dict[int, PidEntry]:
    return {
        pid: PidEntry(
            daq_list=0,
            odt_index=odt_index,
            has_timestamp=has_timestamp,
            signals=[OdtSignalLayout(sig, off) for sig, off in signals],
        )
    }


# ── TimestampAccumulator ──────────────────────────────────────────────────────

def test_ts_accum_normal_increment() -> None:
    acc = TimestampAccumulator()
    assert acc.to_ns(100) == 1_000    # 100 ticks × 10 ns
    assert acc.to_ns(200) == 2_000
    assert acc.to_ns(1_000) == 10_000


def test_ts_accum_rollover_detected() -> None:
    acc = TimestampAccumulator()
    acc.to_ns(0xFFFF_FF00)
    result = acc.to_ns(0x0000_0100)   # wrapped
    # Sau rollover: epoch = 2^32; accumulated = 2^32 + 0x100
    expected = (0x1_0000_0000 + 0x100) * 10
    assert result == expected


def test_ts_accum_two_rollovers() -> None:
    acc = TimestampAccumulator()
    acc.to_ns(0xFFFF_FF00)
    acc.to_ns(0x0000_0100)   # rollover 1
    acc.to_ns(0xFFFF_FF00)
    result = acc.to_ns(0x0000_0200)   # rollover 2
    expected = (2 * 0x1_0000_0000 + 0x200) * 10
    assert result == expected


def test_ts_accum_monotone_across_rollover() -> None:
    acc = TimestampAccumulator()
    ns1 = acc.to_ns(0xFFFF_FF00)
    ns2 = acc.to_ns(0x0000_0100)
    assert ns2 > ns1


def test_ts_accum_byte_order_stored() -> None:
    acc = TimestampAccumulator(byte_order="big")
    assert acc.byte_order == "big"


# ── decode_dto — edge cases ───────────────────────────────────────────────────

def test_decode_empty_frame_returns_empty() -> None:
    assert decode_dto(b"", {}, TimestampAccumulator()) == []


def test_decode_unknown_pid_returns_empty() -> None:
    frame = bytes([0x05, 0x01, 0x02, 0x03, 0x04, 0x05, 0x00, 0x00])
    assert decode_dto(frame, {}, TimestampAccumulator()) == []


def test_decode_overrun_bit_masked() -> None:
    """PID với bit 7 set (= overrun flag) vẫn decode được qua real pid."""
    sig = _sig("x", 1)
    table = _pid_table(0, 0, False, [(sig, 1)])
    frame = bytes([0x80, 0xAB, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    # PID byte = 0x80 → real pid = 0x80 & 0x7F = 0
    samples = decode_dto(frame, table, TimestampAccumulator())
    assert len(samples) == 1
    assert samples[0].name == "x"
    assert samples[0].value_raw == b"\xAB"


# ── decode_dto — timestamp handling ──────────────────────────────────────────

def test_decode_no_timestamp_signal_at_offset1() -> None:
    sig = _sig("speed", 2, "UINT16")
    table = _pid_table(0, 0, False, [(sig, 1)])
    frame = bytes([0x00, 0x34, 0x12, 0x00, 0x00, 0x00, 0x00, 0x00])
    acc = TimestampAccumulator()
    samples = decode_dto(frame, table, acc)
    assert len(samples) == 1
    assert samples[0].name == "speed"
    assert samples[0].value_raw == b"\x34\x12"
    assert samples[0].timestamp_ns == 0
    assert samples[0].datatype == "UINT16"


def test_decode_with_timestamp_odt0() -> None:
    sig = _sig("rpm", 2)
    # offset 5 = 1 (PID) + 4 (TS)
    table = _pid_table(0, 0, True, [(sig, 5)])
    # TS = 100 ticks LE
    frame = bytes([0x00]) + (100).to_bytes(4, "little") + bytes([0xBB, 0xAA, 0x00])
    samples = decode_dto(frame, table, TimestampAccumulator())
    assert len(samples) == 1
    assert samples[0].timestamp_ns == 100 * 10
    assert samples[0].value_raw == b"\xBB\xAA"


def test_decode_timestamp_monotone_two_frames() -> None:
    sig = _sig("a", 1)
    table = _pid_table(0, 0, True, [(sig, 5)])
    acc = TimestampAccumulator()
    frame1 = bytes([0x00]) + (10).to_bytes(4, "little") + bytes([0xAA, 0x00, 0x00])
    frame2 = bytes([0x00]) + (20).to_bytes(4, "little") + bytes([0xBB, 0x00, 0x00])
    s1 = decode_dto(frame1, table, acc)[0]
    s2 = decode_dto(frame2, table, acc)[0]
    assert s2.timestamp_ns > s1.timestamp_ns


def test_decode_timestamp_rollover_monotone() -> None:
    """Timestamp tràn 32-bit → elapsed_ns không nhảy âm."""
    sig = _sig("x", 1)
    table = _pid_table(0, 0, True, [(sig, 5)])
    acc = TimestampAccumulator()
    # Frame gần cuối vòng
    ts1 = 0xFFFF_FF00
    frame1 = bytes([0x00]) + ts1.to_bytes(4, "little") + bytes([0x01, 0x00, 0x00])
    # Frame đã quay vòng
    ts2 = 0x0000_0100
    frame2 = bytes([0x00]) + ts2.to_bytes(4, "little") + bytes([0x02, 0x00, 0x00])
    s1 = decode_dto(frame1, table, acc)[0]
    s2 = decode_dto(frame2, table, acc)[0]
    assert s2.timestamp_ns > s1.timestamp_ns


def test_decode_non_odt0_no_timestamp() -> None:
    """ODT index > 0 có has_timestamp=False dù list bật timestamp mode."""
    sig = _sig("x", 2)
    table = _pid_table(1, 1, False, [(sig, 1)])
    frame = bytes([0x01, 0x11, 0x22, 0x00, 0x00, 0x00, 0x00, 0x00])
    samples = decode_dto(frame, table, TimestampAccumulator())
    assert len(samples) == 1
    assert samples[0].timestamp_ns == 0
    assert samples[0].value_raw == b"\x11\x22"


# ── decode_dto — multi-signal và truncation ───────────────────────────────────

def test_decode_two_signals_in_odt() -> None:
    sig1 = _sig("a", 2)
    sig2 = DaqSignal("b", 0x8000_0002, 0, 1, "UINT8")
    table = _pid_table(0, 0, False, [(sig1, 1), (sig2, 3)])
    frame = bytes([0x00, 0xAA, 0xBB, 0xCC, 0x00, 0x00, 0x00, 0x00])
    samples = decode_dto(frame, table, TimestampAccumulator())
    assert len(samples) == 2
    assert samples[0].name == "a"
    assert samples[0].value_raw == b"\xAA\xBB"
    assert samples[1].name == "b"
    assert samples[1].value_raw == b"\xCC"


def test_decode_frame_too_short_signal_skipped() -> None:
    """Frame bị cắt — signal yêu cầu bytes ngoài frame → bỏ qua, không raise."""
    sig = _sig("x", 4)
    table = _pid_table(0, 0, False, [(sig, 1)])
    frame = bytes([0x00, 0x01, 0x02])   # 3 bytes, signal cần offset 1+4=5
    assert decode_dto(frame, table, TimestampAccumulator()) == []


def test_decode_frame_too_short_for_timestamp() -> None:
    """Frame < 5 byte khi has_timestamp=True → timestamp=0, không crash."""
    sig = _sig("x", 1)
    table = _pid_table(0, 0, True, [(sig, 5)])
    frame = bytes([0x00, 0x01])   # không đủ 5 byte cho TS
    # Signal cũng không lấy được (offset 5 > len=2)
    samples = decode_dto(frame, table, TimestampAccumulator())
    assert samples == []


def test_sample_point_fields() -> None:
    """SamplePoint có đủ 4 field và là frozen dataclass."""
    sp = SamplePoint(name="v", timestamp_ns=1000, value_raw=b"\x01", datatype="UINT8")
    assert sp.name == "v"
    assert sp.timestamp_ns == 1000
    assert sp.value_raw == b"\x01"
    assert sp.datatype == "UINT8"
    with pytest.raises((AttributeError, TypeError)):
        sp.name = "y"  # type: ignore[misc]
