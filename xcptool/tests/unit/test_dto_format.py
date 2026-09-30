"""DtoFormat + make_key + effective_timestamp + TimestampAccumulator tổng quát."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from xcptool.master.daq import (
    DtoFormat,
    TimestampAccumulator,
    effective_timestamp,
    make_key,
)
from xcptool.session.api import DaqCaps


def _caps(**over: object) -> DaqCaps:
    base: dict[str, object] = dict(
        max_daq=0, max_event_channel=1, min_daq=0, dynamic_daq=True,
        timestamp_supported=True, timestamp_size=2, timestamp_unit_ns=1_000_000,
        timestamp_ticks=10, pid_off_supported=False,
        granularity_odt_entry_daq=1, max_odt_entry_size_daq=7,
        id_field_type=1, overload="none", timestamp_fixed=False,
    )
    base.update(over)
    return DaqCaps(**base)  # type: ignore[arg-type]


# ── DtoFormat ─────────────────────────────────────────────────────────────────

def test_default_format_reproduces_legacy_behaviour() -> None:
    fmt = DtoFormat()
    assert (fmt.id_type, fmt.byte_order, fmt.ts_size, fmt.unit_ns, fmt.ticks,
            fmt.overload, fmt.ts_always) == (0, "little", 4, 10, 1, "pid_msb", False)
    assert fmt.header_len == 1
    assert fmt.data_start(has_timestamp=True) == 5
    assert fmt.data_start(has_timestamp=False) == 1


@pytest.mark.parametrize("id_type,header", [(0, 1), (1, 2), (2, 3), (3, 4)])
def test_header_len_by_identification_field_type(id_type: int, header: int) -> None:
    assert DtoFormat(id_type=id_type).header_len == header


def test_data_start_adds_timestamp_only_when_present() -> None:
    fmt = DtoFormat(id_type=3, ts_size=2)
    assert fmt.data_start(True) == 6
    assert fmt.data_start(False) == 4


@pytest.mark.parametrize("bad", [-1, 4, 7])
def test_invalid_id_type_is_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="id_type"):
        DtoFormat(id_type=bad)


@pytest.mark.parametrize("bad", [3, 5, 8])
def test_invalid_ts_size_is_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="ts_size"):
        DtoFormat(ts_size=bad)


def test_from_caps_none_gives_default_with_given_byte_order() -> None:
    assert DtoFormat.from_caps(None) == DtoFormat()
    assert DtoFormat.from_caps(None, "big") == DtoFormat(byte_order="big")


def test_from_caps_maps_every_field() -> None:
    fmt = DtoFormat.from_caps(_caps(timestamp_fixed=True), "big")
    assert fmt == DtoFormat(id_type=1, byte_order="big", ts_size=2, unit_ns=1_000_000,
                            ticks=10, overload="none", ts_always=True)


def test_from_slave_caps_uses_daq_caps_and_byte_order() -> None:
    slave = SimpleNamespace(daq=_caps(), byte_order="big")
    assert DtoFormat.from_slave_caps(slave).byte_order == "big"   # type: ignore[arg-type]
    assert DtoFormat.from_slave_caps(slave).id_type == 1           # type: ignore[arg-type]


def test_from_slave_caps_none_or_without_daq_gives_default() -> None:
    assert DtoFormat.from_slave_caps(None) == DtoFormat()
    no_daq = SimpleNamespace(daq=None, byte_order="big")
    assert DtoFormat.from_slave_caps(no_daq) == DtoFormat(byte_order="big")  # type: ignore[arg-type]


# ── make_key ──────────────────────────────────────────────────────────────────

def test_make_key_absolute_uses_first_pid_plus_odt() -> None:
    assert make_key(DtoFormat(id_type=0), daq=7, odt=2, first_pid=10) == 12


@pytest.mark.parametrize("id_type", [1, 2, 3])
def test_make_key_relative_uses_daq_and_odt_and_ignores_first_pid(id_type: int) -> None:
    assert make_key(DtoFormat(id_type=id_type), daq=7, odt=2, first_pid=99) == (7, 2)


# ── effective_timestamp ───────────────────────────────────────────────────────

def test_effective_timestamp_follows_request_normally() -> None:
    fmt = DtoFormat()
    assert effective_timestamp(True, fmt) is True
    assert effective_timestamp(False, fmt) is False


def test_effective_timestamp_always_on_when_fixed() -> None:
    assert effective_timestamp(False, DtoFormat(ts_always=True)) is True


def test_effective_timestamp_off_when_ecu_has_no_timestamp() -> None:
    assert effective_timestamp(True, DtoFormat(ts_size=0)) is False


# ── TimestampAccumulator ──────────────────────────────────────────────────────

def test_accumulator_defaults_are_legacy_32bit_10ns() -> None:
    acc = TimestampAccumulator()
    assert (acc.width_bits, acc.unit_ns, acc.ticks) == (32, 10, 1)
    assert acc.to_ns(100) == 1_000


def test_accumulator_unit_and_ticks_per_spec_part5_example() -> None:
    """Part 5: unit 1 ms, TIMESTAMP_TICKS 10 → counter tăng 10 mỗi ms."""
    acc = TimestampAccumulator(unit_ns=1_000_000, ticks=10)
    assert acc.to_ns(10) == 1_000_000
    assert acc.to_ns(25) == 2_500_000


def test_accumulator_16bit_rollover() -> None:
    acc = TimestampAccumulator(width_bits=16)
    acc.to_ns(0xFF00)
    assert acc.to_ns(0x0100) == (0x1_0000 + 0x100) * 10


def test_accumulator_8bit_rollover() -> None:
    acc = TimestampAccumulator(width_bits=8)
    acc.to_ns(0xF0)
    assert acc.to_ns(0x05) == (0x100 + 0x05) * 10


def test_accumulator_small_backstep_is_not_a_rollover() -> None:
    """Review Focus #4: frame đến lệch thứ tự nhẹ không được cộng cả chu kỳ."""
    acc = TimestampAccumulator()
    assert acc.to_ns(1000) == 10_000
    assert acc.to_ns(990) == 9_900          # lùi 10 tick: không đổi epoch
    assert acc.to_ns(1010) == 10_100


def test_accumulator_backstep_just_over_half_range_is_a_rollover() -> None:
    acc = TimestampAccumulator(width_bits=8)
    acc.to_ns(200)
    # 200 → 50: tụt 150 > 128 (nửa chu kỳ) → rollover
    assert acc.to_ns(50) == (0x100 + 50) * 10
    acc2 = TimestampAccumulator(width_bits=8)
    acc2.to_ns(200)
    # 200 → 100: tụt 100 ≤ 128 → lệch thứ tự, không rollover
    assert acc2.to_ns(100) == 100 * 10


@pytest.mark.parametrize("unit_ns,ticks", [(0, 1), (10, 0), (0, 0)])
def test_accumulator_invalid_unit_or_ticks_gives_zero(unit_ns: int, ticks: int) -> None:
    """Review Focus #2: không ZeroDivisionError, trả 0 ns."""
    acc = TimestampAccumulator(unit_ns=unit_ns, ticks=ticks)
    assert acc.to_ns(12345) == 0


def test_accumulator_from_format() -> None:
    fmt = DtoFormat(ts_size=2, byte_order="big", unit_ns=100, ticks=2)
    acc = TimestampAccumulator.from_format(fmt)
    assert (acc.byte_order, acc.width_bits, acc.unit_ns, acc.ticks) == ("big", 16, 100, 2)


def test_accumulator_from_format_without_timestamp_keeps_32bit_width() -> None:
    acc = TimestampAccumulator.from_format(DtoFormat(ts_size=0))
    assert acc.width_bits == 32


# ── Final review: frame muộn sau rollover + TIMESTAMP_FIXED không hỗ trợ ─────

def test_accumulator_tracks_each_stream_so_late_frames_do_not_shift_later_ones() -> None:
    """Hai DAQ list dùng chung một accumulator: list B có frame đến muộn ngay sau khi
    list A đã rollover. Mỗi list được theo dõi riêng nên chuỗi của B vẫn đúng."""
    acc = TimestampAccumulator(width_bits=16)
    a1 = acc.to_ns(0xFFF0, stream="A")
    b1 = acc.to_ns(0xFFE0, stream="B")
    a2 = acc.to_ns(0x0010, stream="A")     # A đã rollover
    b2 = acc.to_ns(0xFFF8, stream="B")     # B: frame đến muộn, vẫn ở chu kỳ trước
    a3 = acc.to_ns(0x0020, stream="A")
    b3 = acc.to_ns(0x0008, stream="B")     # B rollover
    assert [t // 10 for t in (a1, b1, a2, b2, a3, b3)] == [
        65520, 65504, 65552, 65528, 65568, 65544]


def test_accumulator_default_stream_keeps_single_stream_behaviour() -> None:
    """Không truyền stream → một chuỗi duy nhất như trước (test cũ phụ thuộc vào đây)."""
    acc = TimestampAccumulator()
    for raw, expected in ((0xFFFF_FF00, 0xFFFF_FF00), (0x100, 0x1_0000_0100),
                          (0xFFFF_FF00, 0x1_FFFF_FF00), (0x200, 0x2_0000_0200)):
        assert acc.to_ns(raw) // 10 == expected


def test_effective_timestamp_off_when_fixed_but_ecu_has_no_timestamp() -> None:
    """TIMESTAMP_FIXED không có nghĩa khi không có timestamp (ts_size == 0)."""
    assert effective_timestamp(False, DtoFormat(ts_size=0, ts_always=True)) is False
    assert effective_timestamp(True, DtoFormat(ts_size=0, ts_always=True)) is False
