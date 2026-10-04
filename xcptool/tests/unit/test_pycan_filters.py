"""Filter phần cứng phải cho qua MỌI CAN ID master cần nghe — nếu chỉ `dto_id`,
DTO phát trên ID riêng của DAQ list bị loại trước khi tới master."""

from __future__ import annotations

from xcptool.session.api import BusConfig
from xcptool.transport.pycan import rx_filters


def _cfg(**kw) -> BusConfig:
    return BusConfig(backend="virtual", channel="c", **kw)


def test_mot_filter_khi_chi_co_dto_id() -> None:
    assert rx_filters(_cfg()) == [{"can_id": 0x7E1, "can_mask": 0x7FF, "extended": False}]


def test_moi_id_mot_filter() -> None:
    cfg = _cfg(dto_id=0x6A1, daq_can_ids=((1, 0x6A3), (0, 0x6A2)))
    assert [f["can_id"] for f in rx_filters(cfg)] == [0x6A1, 0x6A2, 0x6A3]


def test_mask_29_bit_khi_extended_id() -> None:
    (flt,) = rx_filters(_cfg(extended_id=True, dto_id=0x18DAF110))
    assert flt == {"can_id": 0x18DAF110, "can_mask": 0x1FFFFFFF, "extended": True}
