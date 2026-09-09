"""transport/bit_timing — adapter mỏng quanh `can.BitTiming.from_sample_point`.

Việc tính là của python-can; ở đây chỉ kiểm: field map đúng, rẽ nhánh FD đúng,
và `ValueError` của python-can được dịch sang `BitTimingError` có `user_message`.
"""

from __future__ import annotations

import pytest

from xcptool.session.bit_timing import BitTimingError, solve

F_CLOCK = 80_000_000


def test_classic_hits_exact_bitrate_near_requested_sample_point() -> None:
    sol = solve(F_CLOCK, 500_000, 87.5)
    assert sol.nom_bitrate == 500_000
    assert abs(sol.nom_sample_point - 87.5) <= 2.0
    assert sol.data is None
    n = sol.nominal
    # bitrate = f_clock / (brp * (1 + tseg1 + tseg2))
    assert n.brp * (1 + n.tseg1 + n.tseg2) == F_CLOCK // 500_000


def test_reported_sample_point_matches_tseg_ratio() -> None:
    sol = solve(F_CLOCK, 250_000, 80.0)
    n = sol.nominal
    ratio = (1 + n.tseg1) / (1 + n.tseg1 + n.tseg2) * 100
    assert abs(ratio - sol.nom_sample_point) < 0.01


def test_fd_solves_both_phases() -> None:
    sol = solve(F_CLOCK, 500_000, 87.5, data_bitrate=2_000_000, data_sample_point=70.0)
    assert sol.nom_bitrate == 500_000
    assert sol.data_bitrate == 2_000_000
    assert sol.data is not None
    d = sol.data
    assert d.brp * (1 + d.tseg1 + d.tseg2) == F_CLOCK // 2_000_000


def test_impossible_bitrate_raises_bit_timing_error() -> None:
    with pytest.raises(BitTimingError) as exc:
        solve(F_CLOCK, 3_000_000, 75.0)  # 80 MHz / 3 Mbps → không chia hết
    assert exc.value.user_message
    assert "3000000" in exc.value.user_message


def test_fd_without_data_sample_point_raises() -> None:
    with pytest.raises(BitTimingError):
        solve(F_CLOCK, 500_000, 87.5, data_bitrate=2_000_000)
