"""switch_page: đưa cả trang ECU lẫn trang XCP về một trang bằng MỘT lệnh SET_CAL_PAGE.

Part 2 v1.0 cho phép đặt cả hai cờ (bit 0 = ECU, bit 1 = XCP) trong cùng một
lệnh. Không phải ECU nào cũng nhận, nên master tự chuyển sang hai lệnh rời khi
ECU từ chối mode gộp — thứ tự XCP trước, ECU sau (an toàn hơn cho trang có
ECU_ACCESS_WITH_XCP_ONLY: ECU chỉ được dùng trang đó khi XCP cũng đang ở đó).

Fakeslave ghi lại mọi SET_CAL_PAGE nhận được vào `set_cal_page_log` dưới dạng
`(mode, segment, page)` để test khẳng định đúng số lệnh và thứ tự.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from xcptool.devtools.fakeslave import REFERENCE_PAGE, WORKING_PAGE, FakeSlave, SlaveConfig
from xcptool.session.api import BusConfig, PageMode, SlaveError, UnsupportedByEcuError
from xcptool.session.real import RealSession

BOTH = 0x03     # ECU | XCP
ECU = 0x01
XCP = 0x02
ERR_PAGE_NOT_VALID = 0x26


@contextmanager
def _connected(cfg: SlaveConfig) -> Iterator[tuple[RealSession, FakeSlave]]:
    bus = BusConfig(backend="virtual", channel=cfg.channel, cro_id=cfg.cro_id,
                    dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    try:
        with FakeSlave(cfg) as slave:
            session.connect(bus)
            yield session, slave
    finally:
        session.close()


def test_switch_page_sends_one_combined_command(channel: str) -> None:
    with _connected(SlaveConfig(channel=channel)) as (session, slave):
        session.switch_page(0, WORKING_PAGE)
        assert list(slave.set_cal_page_log) == [(BOTH, 0, WORKING_PAGE)]
        assert session.get_page(0, PageMode.ECU) == WORKING_PAGE
        assert session.get_page(0, PageMode.XCP) == WORKING_PAGE


def test_switch_page_falls_back_to_two_commands_xcp_first(channel: str) -> None:
    cfg = SlaveConfig(channel=channel, combined_page_switch=False)
    with _connected(cfg) as (session, slave):
        session.switch_page(0, WORKING_PAGE)
        assert list(slave.set_cal_page_log) == [
            (BOTH, 0, WORKING_PAGE),      # bị từ chối ERR_MODE_NOT_VALID
            (XCP, 0, WORKING_PAGE),       # XCP trước
            (ECU, 0, WORKING_PAGE),       # ECU sau
        ]
        assert session.get_page(0, PageMode.ECU) == WORKING_PAGE
        assert session.get_page(0, PageMode.XCP) == WORKING_PAGE


def test_fallback_decision_is_remembered_for_the_session(channel: str) -> None:
    cfg = SlaveConfig(channel=channel, combined_page_switch=False)
    with _connected(cfg) as (session, slave):
        session.switch_page(0, WORKING_PAGE)
        slave.set_cal_page_log.clear()
        session.switch_page(0, REFERENCE_PAGE)
        # lần sau không thử lại mode gộp đã biết bị từ chối
        assert list(slave.set_cal_page_log) == [
            (XCP, 0, REFERENCE_PAGE), (ECU, 0, REFERENCE_PAGE)]


def test_invalid_page_is_an_error_not_a_reason_to_fall_back(channel: str) -> None:
    """ERR_PAGE_NOT_VALID là lỗi thật: không được chuyển sang hai lệnh rời, và
    không được ghi nhớ nhầm là ECU không nhận mode gộp."""
    with _connected(SlaveConfig(channel=channel)) as (session, slave):
        with pytest.raises(SlaveError) as ei:
            session.switch_page(0, 5)
        assert ei.value.code == ERR_PAGE_NOT_VALID
        assert list(slave.set_cal_page_log) == [(BOTH, 0, 5)]
        slave.set_cal_page_log.clear()
        session.switch_page(0, WORKING_PAGE)
        assert list(slave.set_cal_page_log) == [(BOTH, 0, WORKING_PAGE)]


def test_failed_fallback_does_not_poison_the_cache(channel: str) -> None:
    """ECU từ chối mode gộp và trang sai: lỗi thật từ lệnh rời, nhưng chưa được
    kết luận 'ECU không nhận mode gộp' (fallback chưa thành công)."""
    cfg = SlaveConfig(channel=channel, combined_page_switch=False)
    with _connected(cfg) as (session, slave):
        with pytest.raises(SlaveError) as ei:
            session.switch_page(0, 5)
        assert ei.value.code == ERR_PAGE_NOT_VALID
        assert list(slave.set_cal_page_log) == [(BOTH, 0, 5), (XCP, 0, 5)]
        slave.set_cal_page_log.clear()
        session.switch_page(0, WORKING_PAGE)
        assert list(slave.set_cal_page_log)[0] == (BOTH, 0, WORKING_PAGE)


def test_switch_page_requires_cal_pag_support(channel: str) -> None:
    with _connected(SlaveConfig(channel=channel, supports_cal_pag=False)) as (session, slave):
        with pytest.raises(UnsupportedByEcuError):
            session.switch_page(0, WORKING_PAGE)
        assert list(slave.set_cal_page_log) == []
