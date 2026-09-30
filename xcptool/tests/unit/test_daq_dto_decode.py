"""decode_dto với 4 kiểu identification field, overrun theo cách ECU báo,
timestamp nhiều kích thước. Không cần bus — thuần bytes.

Frame dùng ở đây dựng tay theo ASAM XCP v1.0 Part 2 mục 1.1.2:
    kiểu 0: PID | [TS] | data
    kiểu 1: ODT DAQ | [TS] | data
    kiểu 2: ODT DAQ_lo DAQ_hi | [TS] | data
    kiểu 3: ODT FILL DAQ_lo DAQ_hi | [TS] | data
"""

from __future__ import annotations

import pytest

from xcptool.master.daq import (
    DaqSignal,
    DtoFormat,
    OdtSignalLayout,
    PidEntry,
    TimestampAccumulator,
    decode_dto,
)


def _sig(name: str = "x", size: int = 1) -> DaqSignal:
    return DaqSignal(name=name, address=0x8000_0000, ext=0, size=size, datatype="UINT8")


def _entry(daq: int, odt: int, has_ts: bool, *placed: tuple[DaqSignal, int]) -> PidEntry:
    return PidEntry(daq_list=daq, odt_index=odt, has_timestamp=has_ts,
                    signals=[OdtSignalLayout(s, off) for s, off in placed])


def _acc(fmt: DtoFormat) -> TimestampAccumulator:
    return TimestampAccumulator.from_format(fmt)


# ── kiểu 0 (mặc định, hành vi cũ) ────────────────────────────────────────────

def test_absolute_type_default_format() -> None:
    table = {5: _entry(0, 5, False, (_sig("a", 2), 1))}
    frame = bytes([0x05, 0xAA, 0xBB, 0, 0, 0, 0, 0])
    samples = decode_dto(frame, table, TimestampAccumulator())
    assert [(s.name, s.value_raw) for s in samples] == [("a", b"\xAA\xBB")]


# ── kiểu 1 ────────────────────────────────────────────────────────────────────

def test_relative_byte_type_looks_up_daq_and_odt() -> None:
    fmt = DtoFormat(id_type=1, overload="none")
    table = {(3, 2): _entry(3, 2, False, (_sig("a", 2), 2))}
    frame = bytes([0x02, 0x03, 0x11, 0x22, 0, 0, 0, 0])     # ODT 2 của DAQ list 3
    samples = decode_dto(frame, table, _acc(fmt), fmt)
    assert [(s.name, s.value_raw) for s in samples] == [("a", b"\x11\x22")]


def test_relative_byte_type_other_daq_list_is_not_matched() -> None:
    fmt = DtoFormat(id_type=1, overload="none")
    table = {(3, 2): _entry(3, 2, False, (_sig("a"), 2))}
    frame = bytes([0x02, 0x04, 0x11, 0, 0, 0, 0, 0])        # DAQ list 4, không phải 3
    assert decode_dto(frame, table, _acc(fmt), fmt) == []


def test_relative_byte_type_timestamp_only_on_odt0_part5_units() -> None:
    """Part 5: timestamp 2 byte, unit 1 ms, ticks 10 → raw 10 = 1 ms."""
    fmt = DtoFormat(id_type=1, ts_size=2, unit_ns=1_000_000, ticks=10, overload="none")
    table = {
        (3, 0): _entry(3, 0, True, (_sig("a"), 4)),          # header 2 + TS 2 = offset 4
        (3, 1): _entry(3, 1, False, (_sig("b"), 2)),         # header 2 = offset 2
    }
    acc = _acc(fmt)
    odt0 = bytes([0x00, 0x03, 0x0A, 0x00, 0x55, 0, 0, 0])
    odt1 = bytes([0x01, 0x03, 0x66, 0, 0, 0, 0, 0])
    s0 = decode_dto(odt0, table, acc, fmt)
    s1 = decode_dto(odt1, table, acc, fmt)
    assert (s0[0].value_raw, s0[0].timestamp_ns) == (b"\x55", 1_000_000)
    assert (s1[0].value_raw, s1[0].timestamp_ns) == (b"\x66", 0)


# ── kiểu 2 và 3 ───────────────────────────────────────────────────────────────

def test_relative_word_type_little_endian() -> None:
    fmt = DtoFormat(id_type=2, overload="none")
    table = {(0x0103, 1): _entry(0x0103, 1, False, (_sig("a"), 3))}
    frame = bytes([0x01, 0x03, 0x01, 0x7F, 0, 0, 0, 0])      # DAQ = 0x0103 = 259
    samples = decode_dto(frame, table, _acc(fmt), fmt)
    assert [s.value_raw for s in samples] == [b"\x7F"]


def test_relative_word_daq_number_byte_order() -> None:
    """Review Focus #3: DAQ list ≥ 256 và slave big-endian."""
    fmt = DtoFormat(id_type=2, byte_order="big", overload="none")
    table = {(0x0103, 1): _entry(0x0103, 1, False, (_sig("a"), 3))}
    frame = bytes([0x01, 0x01, 0x03, 0x7F, 0, 0, 0, 0])      # big-endian: 01 03
    samples = decode_dto(frame, table, _acc(fmt), fmt)
    assert [s.value_raw for s in samples] == [b"\x7F"]


def test_relative_word_aligned_type_ignores_fill_byte() -> None:
    fmt = DtoFormat(id_type=3, overload="none")
    table = {(0x0103, 1): _entry(0x0103, 1, False, (_sig("a"), 4))}
    frame = bytes([0x01, 0xEE, 0x03, 0x01, 0x7F, 0, 0, 0])   # FILL = 0xEE
    samples = decode_dto(frame, table, _acc(fmt), fmt)
    assert [s.value_raw for s in samples] == [b"\x7F"]


# ── overrun theo cách ECU báo ────────────────────────────────────────────────

def test_overrun_pid_msb_is_masked_for_odt_byte() -> None:
    fmt = DtoFormat(id_type=1, overload="pid_msb")
    table = {(3, 2): _entry(3, 2, False, (_sig("a"), 2))}
    frame = bytes([0x82, 0x03, 0x11, 0, 0, 0, 0, 0])         # MSB = overrun
    assert [s.value_raw for s in decode_dto(frame, table, _acc(fmt), fmt)] == [b"\x11"]


def test_overload_none_uses_full_byte() -> None:
    fmt = DtoFormat(id_type=1, overload="none")
    table = {(3, 0x82): _entry(3, 0x82, False, (_sig("a"), 2))}
    frame = bytes([0x82, 0x03, 0x11, 0, 0, 0, 0, 0])
    assert [s.value_raw for s in decode_dto(frame, table, _acc(fmt), fmt)] == [b"\x11"]


def test_overload_event_uses_full_byte() -> None:
    fmt = DtoFormat(id_type=0, overload="event")
    table = {0x85: _entry(0, 0x85, False, (_sig("a"), 1))}
    frame = bytes([0x85, 0x11, 0, 0, 0, 0, 0, 0])
    assert [s.value_raw for s in decode_dto(frame, table, _acc(fmt), fmt)] == [b"\x11"]


# ── timestamp size khác 4 byte (kiểu 0) ──────────────────────────────────────

def test_absolute_type_one_byte_timestamp() -> None:
    fmt = DtoFormat(ts_size=1, unit_ns=1000, ticks=1)
    table = {0: _entry(0, 0, True, (_sig("a"), 2))}
    frame = bytes([0x00, 0x07, 0xAA, 0, 0, 0, 0, 0])
    samples = decode_dto(frame, table, _acc(fmt), fmt)
    assert (samples[0].value_raw, samples[0].timestamp_ns) == (b"\xAA", 7_000)


# ── không bao giờ raise ──────────────────────────────────────────────────────

@pytest.mark.parametrize("id_type", [0, 1, 2, 3])
def test_decode_never_raises_on_short_or_unknown_frames(id_type: int) -> None:
    """Review Focus #5."""
    fmt = DtoFormat(id_type=id_type)
    table = {(0, 0) if id_type else 0: _entry(0, 0, True, (_sig("a"), 6))}
    acc = _acc(fmt)
    for frame in (b"", b"\x00", b"\x00\x00", b"\x00\x00\x00", b"\xFF" * 8,
                  bytes(range(8))):
        assert isinstance(decode_dto(frame, table, acc, fmt), list)   # không raise


def test_frame_shorter_than_header_returns_empty() -> None:
    fmt = DtoFormat(id_type=3)
    assert decode_dto(b"\x01\x00", {(0, 1): _entry(0, 1, False)}, _acc(fmt), fmt) == []


def test_frame_too_short_for_timestamp_gives_zero_and_skips_signals() -> None:
    fmt = DtoFormat(id_type=2, ts_size=4)
    table = {(0, 0): _entry(0, 0, True, (_sig("a"), 7))}     # header 3 + TS 4 = 7
    frame = bytes([0x00, 0x00, 0x00, 0x01, 0x02])            # 5 byte: thiếu TS
    assert decode_dto(frame, table, _acc(fmt), fmt) == []


def test_decode_invalid_unit_still_skips_timestamp_bytes() -> None:
    """Review Focus #2: ticks = 0 → timestamp_ns = 0 nhưng signal vẫn đúng offset."""
    fmt = DtoFormat(ts_size=2, unit_ns=1000, ticks=0)
    table = {0: _entry(0, 0, True, (_sig("a"), 3))}          # header 1 + TS 2 = offset 3
    frame = bytes([0x00, 0x34, 0x12, 0x99, 0, 0, 0, 0])
    samples = decode_dto(frame, table, _acc(fmt), fmt)
    assert (samples[0].value_raw, samples[0].timestamp_ns) == (b"\x99", 0)


def test_decode_keeps_timestamps_of_each_daq_list_independent() -> None:
    """Final review: hai list dùng chung accumulator, list 1 có frame muộn sau khi list 0
    rollover. decode_dto phải theo dõi timestamp theo từng DAQ list."""
    fmt = DtoFormat(id_type=1, ts_size=2, unit_ns=10, ticks=1, overload="none")
    table = {
        (0, 0): _entry(0, 0, True, (_sig("a"), 4)),
        (1, 0): _entry(1, 0, True, (_sig("b"), 4)),
    }
    acc = _acc(fmt)

    def stamp(daq: int, raw: int) -> int:
        frame = bytes([0x00, daq]) + raw.to_bytes(2, "little") + b"\x01\x00\x00\x00"
        return decode_dto(frame, table, acc, fmt)[0].timestamp_ns // 10

    got = [stamp(0, 0xFFF0), stamp(1, 0xFFE0), stamp(0, 0x0010),
           stamp(1, 0xFFF8), stamp(0, 0x0020), stamp(1, 0x0008)]
    assert got == [65520, 65504, 65552, 65528, 65568, 65544]
