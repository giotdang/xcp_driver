"""Tập CAN ID nhận của `BusConfig` — response/event trên `dto_id`, mỗi DAQ list
có thể có thêm ID riêng. Rỗng thì phải y hệt cấu hình một ID cũ."""

from __future__ import annotations

import pytest

from xcptool.session.api import BusConfig, XcpToolError


def _cfg(**kw) -> BusConfig:
    return BusConfig(backend="v", channel="c", **kw)


def test_rx_ids_chi_co_dto_id_khi_khong_cau_hinh() -> None:
    assert _cfg().rx_ids == frozenset({0x7E1})


def test_rx_ids_gom_id_rieng_cua_tung_list() -> None:
    cfg = _cfg(dto_id=0x6A1, daq_can_ids=((0, 0x6A2), (1, 0x6A3)))
    assert cfg.rx_ids == frozenset({0x6A1, 0x6A2, 0x6A3})
    assert cfg.daq_can_id_of(1) == 0x6A3
    assert cfg.daq_can_id_of(5) == 0x6A1   # list không khai báo → dto_id


def test_validate_ids_bao_loi_khi_hai_list_cung_id() -> None:
    cfg = _cfg(daq_can_ids=((0, 0x6A2), (1, 0x6A2)))
    with pytest.raises(XcpToolError):
        cfg.validate_ids()


def test_validate_ids_bao_loi_khi_trung_cro_id() -> None:
    cfg = _cfg(cro_id=0x7E0, daq_can_ids=((0, 0x7E0),))
    with pytest.raises(XcpToolError):
        cfg.validate_ids()


def test_validate_ids_chap_nhan_cau_hinh_hop_le() -> None:
    _cfg(daq_can_ids=((0, 0x6A2), (1, 0x6A3))).validate_ids()
    _cfg().validate_ids()
