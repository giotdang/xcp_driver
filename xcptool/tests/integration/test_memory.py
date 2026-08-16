"""B3 — read/write tự chia khối, và điều khiển trang calibration."""

from __future__ import annotations

import math

import pytest

from xcptool.devtools.fakeslave import (
    REFERENCE_PAGE,
    WORKING_PAGE,
    FakeSlave,
    SlaveConfig,
)
from xcptool.master.constants import Cmd
from xcptool.session.api import (
    BusConfig,
    OutOfRangeError,
    PageMode,
    UnsupportedByEcuError,
    WriteProtectedError,
)
from xcptool.session.real import RealSession

PATTERN_64 = bytes((i * 7 + 13) & 0xFF for i in range(64))


def test_write_then_read_back_64_bytes_bit_for_bit(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    """Cổng của B3."""
    session.connect(bus_cfg)
    addr = slave.cfg.mem_base + 16

    session.write(addr, PATTERN_64)

    assert session.read(addr, 64) == PATTERN_64
    assert slave.peek(addr, 64) == PATTERN_64


def test_neighbouring_bytes_are_untouched(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    session.connect(bus_cfg)
    base = slave.cfg.mem_base
    slave.poke(base, b"\xaa" * 128)

    session.write(base + 32, b"\x01\x02\x03\x04")

    assert slave.peek(base + 28, 4) == b"\xaa" * 4
    assert slave.peek(base + 36, 4) == b"\xaa" * 4


@pytest.mark.parametrize("size", [1, 6, 7, 8, 13, 14, 15, 64, 255])
def test_any_size_round_trips(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave, size: int
) -> None:
    """Kích thước quanh ranh giới khối là chỗ lỗi off-by-one hay trốn."""
    session.connect(bus_cfg)
    addr = slave.cfg.mem_base
    payload = bytes((i * 3 + 1) & 0xFF for i in range(size))

    session.write(addr, payload)
    assert session.read(addr, size) == payload


def test_zero_length_is_a_noop(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    session.connect(bus_cfg)
    slave.commands_seen.clear()

    assert session.read(slave.cfg.mem_base, 0) == b""
    session.write(slave.cfg.mem_base, b"")

    assert not slave.commands_seen


def test_small_read_uses_one_command_not_two(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    """Vừa một CTO thì SHORT_UPLOAD rẻ hơn SET_MTA + UPLOAD."""
    session.connect(bus_cfg)
    slave.commands_seen.clear()

    session.read(slave.cfg.mem_base, slave.cfg.max_cto - 1)

    assert slave.commands_seen.count(int(Cmd.SHORT_UPLOAD)) == 1
    assert int(Cmd.SET_MTA) not in slave.commands_seen


def test_block_split_follows_the_declared_cto(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    """Số lệnh phải bằng đúng phép chia theo MAX_CTO, không phải con số viết tay."""
    session.connect(bus_cfg)
    cto = slave.cfg.max_cto
    size = 64

    slave.commands_seen.clear()
    session.write(slave.cfg.mem_base, PATTERN_64)
    assert slave.commands_seen.count(int(Cmd.SET_MTA)) == 1
    assert slave.commands_seen.count(int(Cmd.DOWNLOAD)) == math.ceil(size / (cto - 2))

    slave.commands_seen.clear()
    session.read(slave.cfg.mem_base, size)
    assert slave.commands_seen.count(int(Cmd.SET_MTA)) == 1
    assert slave.commands_seen.count(int(Cmd.UPLOAD)) == math.ceil(size / (cto - 1))


def test_reading_past_the_end_is_a_named_error(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    session.connect(bus_cfg)
    with pytest.raises(OutOfRangeError):
        session.read(slave.cfg.mem_base + slave.cfg.mem_size - 2, 32)


# ── trang calibration ────────────────────────────────────────────────────────


def test_pages_start_where_the_ecu_says(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    session.connect(bus_cfg)
    assert session.get_page(0, PageMode.ECU) == slave.cfg.ecu_page
    assert session.get_page(0, PageMode.XCP) == slave.cfg.xcp_page


def test_ecu_page_and_xcp_page_move_independently(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    """Trang ECU đang chạy và trang XCP đang nhìn là hai thứ khác nhau —
    nhầm hai cái này là hiểu sai cả mô hình calibration."""
    session.connect(bus_cfg)

    session.set_page(0, REFERENCE_PAGE, PageMode.XCP)

    assert session.get_page(0, PageMode.XCP) == REFERENCE_PAGE
    assert session.get_page(0, PageMode.ECU) == WORKING_PAGE


def test_writing_to_the_reference_page_is_refused(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    """Cổng của B3: không phải bug, mà là XCP đang trỏ reference page."""
    session.connect(bus_cfg)
    session.set_page(0, REFERENCE_PAGE, PageMode.XCP)

    with pytest.raises(WriteProtectedError) as excinfo:
        session.write(slave.cfg.mem_base, b"\x01\x02\x03\x04")
    assert "chống ghi" in excinfo.value.description

    # Về working page là dùng lại được ngay — đó là nút mà frontend sẽ hiện.
    session.set_page(0, WORKING_PAGE, PageMode.XCP)
    session.write(slave.cfg.mem_base, b"\x01\x02\x03\x04")
    assert slave.peek(slave.cfg.mem_base, 4) == b"\x01\x02\x03\x04"


def test_reference_page_shows_the_golden_values(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    """So working với reference là thao tác kỹ sư hiệu chỉnh dùng liên tục."""
    session.connect(bus_cfg)
    addr = slave.cfg.mem_base
    slave.poke(addr, b"\x11\x11\x11\x11", page=WORKING_PAGE)
    slave.poke(addr, b"\x22\x22\x22\x22", page=REFERENCE_PAGE)

    assert session.read(addr, 4) == b"\x11\x11\x11\x11"
    session.set_page(0, REFERENCE_PAGE, PageMode.XCP)
    assert session.read(addr, 4) == b"\x22\x22\x22\x22"


def test_copy_page_overwrites_the_working_page(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    session.connect(bus_cfg)
    addr = slave.cfg.mem_base
    slave.poke(addr, b"\x99" * 8, page=REFERENCE_PAGE)

    session.copy_page(0, REFERENCE_PAGE, 0, WORKING_PAGE)

    assert session.read(addr, 8) == b"\x99" * 8


def test_page_commands_are_refused_when_the_ecu_lacks_cal_pag(channel: str) -> None:
    """Kiểm tra bằng SlaveCaps trước khi gửi, để user nhận thông báo rõ ràng
    thay vì một mã lỗi mơ hồ từ ECU."""
    cfg = SlaveConfig(channel=channel, supports_cal_pag=False)
    bus = BusConfig(backend="virtual", channel=channel, cro_id=cfg.cro_id,
                    dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    try:
        with FakeSlave(cfg):
            session.connect(bus)
            with pytest.raises(UnsupportedByEcuError):
                session.get_page(0, PageMode.XCP)
            with pytest.raises(UnsupportedByEcuError):
                session.set_page(0, 0, PageMode.XCP)
            with pytest.raises(UnsupportedByEcuError):
                session.copy_page(0, 1, 0, 0)
    finally:
        session.close()
