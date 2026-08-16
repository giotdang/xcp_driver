"""B1 — capability discovery: ECU tự khai nó là gì, master không đoán.

Đây là bài test giữ cho công cụ dùng lại được với ECU khác. Mọi khẳng định ở
đây đối chiếu `SlaveCaps` với `SlaveConfig` của ECU giả, KHÔNG với hằng số viết
tay — nên đổi ECU giả thì test đi theo, còn hardcode trong master thì test đỏ.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from xcptool.devtools.fakeslave import FakeSlave, SlaveConfig
from xcptool.session.api import BusConfig, SlaveCaps
from xcptool.session.real import RealSession


@contextmanager
def connected(cfg: SlaveConfig) -> Iterator[tuple[RealSession, SlaveCaps]]:
    bus = BusConfig(backend="virtual", channel=cfg.channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id,
                    pad_dlc=cfg.pad_dlc, t1_timeout_s=0.5)
    session = RealSession()
    try:
        with FakeSlave(cfg):
            yield session, session.connect(bus)
    finally:
        session.close()


def test_caps_match_the_slave_configuration(slave_cfg: SlaveConfig) -> None:
    with connected(slave_cfg) as (_, caps):
        assert caps.max_cto == slave_cfg.max_cto
        assert caps.max_dto == slave_cfg.max_dto
        assert caps.byte_order == slave_cfg.byte_order
        assert caps.address_granularity == slave_cfg.address_granularity
        assert caps.protocol_version == (slave_cfg.protocol_version, 0)
        assert caps.transport_version == (slave_cfg.transport_version, 0)
        assert caps.supports_cal_pag == slave_cfg.supports_cal_pag
        assert caps.supports_daq == slave_cfg.supports_daq
        assert caps.supports_stim == slave_cfg.supports_stim
        assert caps.supports_pgm == slave_cfg.supports_pgm
        assert caps.slave_block_mode == slave_cfg.slave_block_mode
        assert caps.optional_cmds == slave_cfg.optional_cmds
        assert caps.needs_seed_and_key is False


@pytest.mark.parametrize("max_cto", [8, 12, 255])
def test_max_cto_follows_the_ecu_not_a_constant(channel: str, max_cto: int) -> None:
    """Cổng của B1: đổi ECU giả sang MAX_CTO khác thì SlaveCaps đổi theo."""
    with connected(SlaveConfig(channel=channel, max_cto=max_cto)) as (_, caps):
        assert caps.max_cto == max_cto


def test_big_endian_slave_is_read_as_big_endian(channel: str) -> None:
    """MAX_DTO nằm ở byte 4-5 và đọc theo byte order khai ở byte 2 — nếu master
    cố định little-endian thì 0x0100 sẽ ra 256 thay vì 1."""
    cfg = SlaveConfig(channel=channel, byte_order="big", max_dto=0x0110)
    with connected(cfg) as (_, caps):
        assert caps.byte_order == "big"
        assert caps.max_dto == 0x0110


@pytest.mark.parametrize("granularity", [1, 2, 4])
def test_address_granularity_comes_from_comm_mode(
    channel: str, granularity: int
) -> None:
    cfg = SlaveConfig(channel=channel, address_granularity=granularity)
    with connected(cfg) as (_, caps):
        assert caps.address_granularity == granularity


def test_resource_bits_are_read_individually(channel: str) -> None:
    cfg = SlaveConfig(channel=channel, supports_cal_pag=False, supports_daq=False,
                      supports_stim=True, supports_pgm=True)
    with connected(cfg) as (_, caps):
        assert (caps.supports_cal_pag, caps.supports_daq) == (False, False)
        assert (caps.supports_stim, caps.supports_pgm) == (True, True)
        assert caps.daq is None       # không khai DAQ thì không hỏi DAQ info


def test_daq_caps_match_the_slave(slave_cfg: SlaveConfig) -> None:
    with connected(slave_cfg) as (_, caps):
        daq = caps.daq
        assert daq is not None
        assert daq.max_daq == slave_cfg.max_daq
        assert daq.max_event_channel == slave_cfg.max_event_channel
        assert daq.min_daq == slave_cfg.min_daq
        assert daq.dynamic_daq == slave_cfg.daq_dynamic
        assert daq.timestamp_supported is True
        assert daq.timestamp_size == slave_cfg.timestamp_size
        assert daq.timestamp_ticks == slave_cfg.timestamp_ticks
        assert daq.timestamp_unit_ns == 10          # mã 0x1 = 10 ns
        assert daq.granularity_odt_entry_daq == slave_cfg.granularity_odt_entry_daq
        assert daq.max_odt_entry_size_daq == slave_cfg.max_odt_entry_size_daq


def test_timestamp_unit_code_is_translated_to_nanoseconds(channel: str) -> None:
    cfg = SlaveConfig(channel=channel, timestamp_unit_code=0x6)   # 1 ms
    with connected(cfg) as (_, caps):
        assert caps.daq is not None
        assert caps.daq.timestamp_unit_ns == 1_000_000


def test_missing_daq_info_is_ignored_quietly(channel: str) -> None:
    """Nhiều ECU tắt GET_DAQ_*. Không được văng lỗi, chỉ đặt daq=None."""
    cfg = SlaveConfig(channel=channel, supports_daq=True, supports_daq_info=False)
    with connected(cfg) as (_, caps):
        assert caps.supports_daq is True
        assert caps.daq is None


def test_get_id_is_optional(channel: str) -> None:
    with connected(SlaveConfig(channel=channel, supports_get_id=False)) as (_, caps):
        assert caps.id_string is None


def test_id_string_is_uploaded_when_offered(channel: str) -> None:
    cfg = SlaveConfig(channel=channel, id_string="engine_ecu.a2l")
    with connected(cfg) as (_, caps):
        assert caps.id_string == "engine_ecu.a2l"


def test_missing_get_status_leaves_seed_and_key_unknown(channel: str) -> None:
    cfg = SlaveConfig(channel=channel, supports_get_status=False)
    with connected(cfg) as (_, caps):
        assert caps.needs_seed_and_key is False


def test_locked_ecu_is_refused_with_a_clear_message(channel: str) -> None:
    """DEV_PLAN §1.2: ECU bật seed & key thì báo rõ rồi ngắt sạch, không hỏng lặng lẽ."""
    from xcptool.session.api import ConnState, UnsupportedByEcuError

    cfg = SlaveConfig(channel=channel, resource_protection=0x01)
    bus = BusConfig(backend="virtual", channel=channel, cro_id=cfg.cro_id,
                    dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    try:
        with FakeSlave(cfg), pytest.raises(UnsupportedByEcuError, match="seed & key"):
            session.connect(bus)
        assert session.state is ConnState.DISCONNECTED
    finally:
        session.close()


def test_pgm_only_protection_does_not_block_calibration(channel: str) -> None:
    """Khoá riêng vùng flash không cản trở đo/hiệu chỉnh — đừng từ chối oan."""
    cfg = SlaveConfig(channel=channel, resource_protection=0x10)
    with connected(cfg) as (_, caps):
        assert caps.needs_seed_and_key is True
