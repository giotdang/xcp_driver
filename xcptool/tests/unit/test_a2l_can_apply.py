"""`apply_a2l_can`: A2L thắng ở các trường CAN, trường thiếu giữ giá trị tay, và
KHÔNG đụng phần cứng PC (backend/channel/clock) hay timing thủ công."""

from __future__ import annotations

from dataclasses import replace

from xcptool.a2l.types import DaqListCanId, XcpCanInfo
from xcptool.session.a2l_can import apply_a2l_can
from xcptool.session.api import BusConfig


def _info(**kw) -> XcpCanInfo:
    base = dict(master_id=0x6A0, slave_id=0x6A1, extended=False, baudrate=250_000,
                sample_point=80.0, is_fd=False, fd_data_baudrate=None,
                fd_data_sample_point=None, max_dlc_required=False)
    base.update(kw)
    return XcpCanInfo(**base)


def _cfg(**kw) -> BusConfig:
    return BusConfig(backend="pcan", channel="PCAN_USBBUS1", **kw)


def test_ghi_de_id_bitrate_va_fd() -> None:
    cfg = _cfg(is_fd=False)
    eff, _notes = apply_a2l_can(cfg, _info(
        is_fd=True, fd_data_baudrate=4_000_000, fd_data_sample_point=70.0,
        max_dlc_required=True))

    assert (eff.cro_id, eff.dto_id) == (0x6A0, 0x6A1)
    assert (eff.bitrate, eff.sample_point) == (250_000, 80.0)
    assert (eff.is_fd, eff.data_bitrate, eff.data_sample_point) == (True, 4_000_000, 70.0)
    assert eff.pad_dlc is True


def test_truong_none_giu_gia_tri_cu_va_co_ghi_chu() -> None:
    cfg = _cfg(bitrate=125_000, sample_point=87.5)
    eff, notes = apply_a2l_can(cfg, _info(baudrate=None, sample_point=None))

    assert (eff.bitrate, eff.sample_point) == (125_000, 87.5)
    assert any("BAUDRATE" in n for n in notes)
    assert any("SAMPLE_POINT" in n for n in notes)


def test_chi_list_fixed_vao_daq_can_ids() -> None:
    info = _info(daq_list_ids=(DaqListCanId(0, True, 0x6A2), DaqListCanId(1, False, None),
                               DaqListCanId(2, True, 0x6A4)))
    eff, _ = apply_a2l_can(_cfg(), info)

    assert eff.daq_can_ids == ((0, 0x6A2), (2, 0x6A4))


def test_variable_co_ghi_chu_khong_vao_cau_hinh() -> None:
    eff, notes = apply_a2l_can(_cfg(), _info(daq_list_ids=(DaqListCanId(1, False, None),)))

    assert eff.daq_can_ids == ()
    assert any("list 1" in n and "VARIABLE" in n and "SET_DAQ_ID" in n for n in notes)


def test_custom_bit_timing_thang_va_co_canh_bao() -> None:
    cfg = _cfg(bitrate=500_000, custom_bit_timing=True, brp=3, tseg1=12)
    eff, notes = apply_a2l_can(cfg, _info(baudrate=250_000))

    assert eff.bitrate == 500_000
    assert (eff.custom_bit_timing, eff.brp, eff.tseg1) == (True, 3, 12)
    assert any("timing thủ công" in n for n in notes)


def test_khong_dung_backend_channel_f_clock() -> None:
    cfg = _cfg(f_clock=40_000_000, brp=5, t1_timeout_s=2.0, use_a2l_can=True)
    eff, _ = apply_a2l_can(cfg, _info())

    assert (eff.backend, eff.channel, eff.f_clock, eff.brp, eff.t1_timeout_s) == (
        "pcan", "PCAN_USBBUS1", 40_000_000, 5, 2.0)
    assert eff.use_a2l_can is True


def test_id_29_bit_dat_extended_id() -> None:
    eff, _ = apply_a2l_can(_cfg(), _info(extended=True, master_id=0x123, slave_id=0x124))

    assert eff.extended_id is True
    assert (eff.cro_id, eff.dto_id) == (0x123, 0x124)


def test_ghi_chu_cua_parser_duoc_noi_vao_cuoi() -> None:
    _eff, notes = apply_a2l_can(_cfg(), _info(notes=("CAN_ID_MASTER_INCREMENTAL: x",)))

    assert notes[-1] == "CAN_ID_MASTER_INCREMENTAL: x"
