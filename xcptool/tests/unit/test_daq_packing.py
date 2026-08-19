"""Unit tests cho pack_odts() — D4a.

Chạy trước khi viết bất cứ dòng code DAQ nào khác.
Xem DEV_PLAN.md §7 D4a cho danh sách test bắt buộc.
"""

import pytest

from xcptool.master.daq import DaqSignal, pack_odts


def sig(name: str, size: int, datatype: str = "UBYTE") -> DaqSignal:
    return DaqSignal(name=name, address=0, ext=0, size=size, datatype=datatype)


# ── test bắt buộc từ DEV_PLAN.md §7 D4a ──────────────────────────────────────

def test_small_signals_fit_in_odt0_with_timestamp():
    """1B + 2B, timestamp bật → ODT 0 = [2B, 1B], tổng 3B ≤ budget (3)."""
    result = pack_odts([sig("a", 1), sig("b", 2)], timestamp_on=True)
    assert len(result) == 1  # chỉ ODT 0
    sizes = sorted([s.size for s in result[0]], reverse=True)
    assert sizes == [2, 1]


def test_large_signal_goes_to_odt1_with_timestamp():
    """Signal 4B, timestamp bật → ODT 0 rỗng, 4B ở ODT 1 — KHÔNG raise."""
    result = pack_odts([sig("x", 4)], timestamp_on=True)
    assert len(result) == 2
    assert result[0] == []
    assert len(result[1]) == 1
    assert result[1][0].size == 4


def test_oversized_signal_raises():
    """Signal 8B → ValueError (max 7B/ODT với max_dto=8)."""
    with pytest.raises(ValueError, match="8B > max 7B"):
        pack_odts([sig("big", 8)], timestamp_on=False, max_dto=8)


def test_timestamp_off_uses_full_budget():
    """Timestamp tắt → first_budget = rest_budget = 7; signal 4B vừa ODT 0."""
    result = pack_odts([sig("x", 4)], timestamp_on=False)
    assert len(result) == 1
    assert result[0][0].size == 4


def test_mix_signals_with_timestamp():
    """4B + 2B + 1B, timestamp bật → ODT 0: [2B,1B], ODT 1: [4B]."""
    result = pack_odts(
        [sig("a", 4), sig("b", 2), sig("c", 1)], timestamp_on=True
    )
    assert len(result) == 2
    odt0_sizes = sorted([s.size for s in result[0]], reverse=True)
    assert odt0_sizes == [2, 1]
    odt1_sizes = [s.size for s in result[1]]
    assert odt1_sizes == [4]


# ── test bổ sung ──────────────────────────────────────────────────────────────

def test_empty_signals_returns_one_empty_odt():
    """Không có signal nào → trả về [[]] (ODT 0 rỗng, không có ODT 1+)."""
    result = pack_odts([], timestamp_on=True)
    assert result == [[]]


def test_signal_exactly_fills_rest_budget():
    """Signal vừa đúng rest_budget (7B) → không raise, vào ODT 1 khi TS bật."""
    result = pack_odts([sig("s", 7)], timestamp_on=True)
    assert len(result) == 2
    assert result[0] == []
    assert result[1][0].size == 7


def test_multiple_signals_split_across_odts():
    """6 signal mỗi 4B, timestamp tắt → 4B/ODT 1+, cần 6 ODT (ODT 0 + 5 ODT 1+)."""
    signals = [sig(f"s{i}", 4) for i in range(6)]
    result = pack_odts(signals, timestamp_on=False)
    # ODT 0: 4B (timestamp off → budget 7, một signal 4B vừa)
    # ODT 1–5: mỗi ODT một signal 4B
    assert result[0] != []
    total_signals = sum(len(odt) for odt in result)
    assert total_signals == 6


def test_all_signals_fit_in_odt0_no_timestamp():
    """Ba signal 2B, timestamp tắt → tất cả vào ODT 0 (2+2+2=6 ≤ 7)."""
    result = pack_odts([sig("a", 2), sig("b", 2), sig("c", 2)], timestamp_on=False)
    assert len(result) == 1
    assert len(result[0]) == 3


def test_timestamp_on_odt0_budget_is_3():
    """Ba signal 1B, timestamp bật → budget ODT 0 là 3B: cả ba vừa."""
    result = pack_odts([sig("a", 1), sig("b", 1), sig("c", 1)], timestamp_on=True)
    assert len(result) == 1
    assert len(result[0]) == 3


def test_timestamp_on_odt0_budget_overflow_goes_to_next():
    """Bốn signal 1B, timestamp bật → 3 vào ODT 0 (budget 3B), 1 vào ODT 1."""
    result = pack_odts(
        [sig("a", 1), sig("b", 1), sig("c", 1), sig("d", 1)], timestamp_on=True
    )
    assert len(result) == 2
    assert len(result[0]) == 3
    assert len(result[1]) == 1


def test_signal_order_preserved_within_odt():
    """Signal lớn hơn đứng trước trong cùng ODT (descending sort)."""
    result = pack_odts(
        [sig("small", 1), sig("medium", 2)], timestamp_on=True
    )
    assert result[0][0].size == 2  # medium trước
    assert result[0][1].size == 1  # small sau


def test_custom_max_dto():
    """max_dto=4 → rest_budget=3; signal 4B → ValueError."""
    with pytest.raises(ValueError):
        pack_odts([sig("x", 4)], timestamp_on=False, max_dto=4)


def test_custom_max_dto_small_frame():
    """max_dto=4, timestamp tắt → budget 3; signal 3B vừa ODT 0."""
    result = pack_odts([sig("x", 3)], timestamp_on=False, max_dto=4)
    assert len(result) == 1
    assert result[0][0].size == 3
