"""pack_odts tôn trọng độ dài header và kích thước timestamp của ECU."""

from __future__ import annotations

import pytest

from xcptool.master.daq import DaqSignal, DtoFormat, pack_odts


def sig(name: str, size: int) -> DaqSignal:
    return DaqSignal(name=name, address=0, ext=0, size=size, datatype="UBYTE")


def sizes(odts: list[list[DaqSignal]]) -> list[list[int]]:
    return [[s.size for s in odt] for odt in odts]


def test_default_format_keeps_legacy_budgets() -> None:
    """Header 1 B + TS 4 B: ODT 0 = 3 B, ODT 1+ = 7 B (như trước)."""
    assert sizes(pack_odts([sig("a", 3), sig("b", 7)], True)) == [[3], [7]]


def test_relative_byte_header_shrinks_budgets() -> None:
    """Kiểu 1 (header 2 B) + TS 4 B trên DTO 8 B: ODT 0 = 2 B, ODT 1+ = 6 B."""
    fmt = DtoFormat(id_type=1)
    assert sizes(pack_odts([sig("a", 2), sig("b", 6)], True, fmt=fmt)) == [[2], [6]]


def test_signal_larger_than_rest_budget_is_rejected_with_new_budget() -> None:
    fmt = DtoFormat(id_type=1)
    with pytest.raises(ValueError, match="7B > max 6B"):
        pack_odts([sig("big", 7)], True, fmt=fmt)


def test_odt0_can_be_empty_when_header_plus_timestamp_fill_the_dto() -> None:
    """Kiểu 3 (header 4 B) + TS 4 B trên DTO 8 B: ODT 0 ngân sách 0, ODT 1+ = 4 B."""
    fmt = DtoFormat(id_type=3)
    assert sizes(pack_odts([sig("a", 4)], True, fmt=fmt)) == [[], [4]]
    with pytest.raises(ValueError, match="5B > max 4B"):
        pack_odts([sig("b", 5)], True, fmt=fmt)


def test_timestamp_size_follows_ecu_not_four_bytes() -> None:
    """TS 2 B, header 1 B: ODT 0 = 5 B."""
    fmt = DtoFormat(ts_size=2)
    assert sizes(pack_odts([sig("a", 5), sig("b", 2)], True, fmt=fmt)) == [[5], [2]]


def test_timestamp_off_ignores_timestamp_size() -> None:
    fmt = DtoFormat(id_type=3)
    assert sizes(pack_odts([sig("a", 4)], False, fmt=fmt)) == [[4]]


def test_header_does_not_fit_in_dto_is_rejected() -> None:
    with pytest.raises(ValueError, match="header"):
        pack_odts([sig("a", 1)], False, max_dto=4, fmt=DtoFormat(id_type=3))


def test_header_plus_timestamp_larger_than_dto_is_rejected() -> None:
    with pytest.raises(ValueError, match="timestamp"):
        pack_odts([sig("a", 1)], True, max_dto=7, fmt=DtoFormat(id_type=3))
    # cùng DTO nhưng không timestamp thì hợp lệ
    assert sizes(pack_odts([sig("a", 1)], False, max_dto=7, fmt=DtoFormat(id_type=3))) == [[1]]


def test_can_fd_dto_uses_full_payload() -> None:
    fmt = DtoFormat(id_type=2)          # header 3 B, TS 4 B → ODT 0 = 57 B, ODT 1+ = 61 B
    assert sizes(pack_odts([sig("a", 57), sig("b", 61)], True, max_dto=64, fmt=fmt)) == [[57], [61]]
