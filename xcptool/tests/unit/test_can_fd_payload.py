"""Unit and integration tests for CAN FD 64-byte payload and Auto DLC mapping."""

from __future__ import annotations

import struct
import pytest

from xcptool.a2l.parser import parse
from xcptool.devtools.fakeslave import FakeSlave, SlaveConfig
from xcptool.master.core import XcpMaster
from xcptool.master.daq import DaqSignal, pack_odts
from xcptool.session.api import BusConfig
from xcptool.transport.base import round_to_can_fd_dlc
from xcptool.transport.virtual import open_virtual


# ── 1. CAN FD DLC Rounding ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "input_len,expected",
    [
        (0, 0),
        (1, 1),
        (8, 8),
        (9, 12),
        (10, 12),
        (12, 12),
        (13, 16),
        (16, 16),
        (17, 20),
        (20, 20),
        (21, 24),
        (24, 24),
        (25, 32),
        (32, 32),
        (33, 48),
        (48, 48),
        (49, 64),
        (64, 64),
        (100, 64),
    ],
)
def test_round_to_can_fd_dlc(input_len: int, expected: int) -> None:
    assert round_to_can_fd_dlc(input_len) == expected


# ── 2. Transport DLC Padding ─────────────────────────────────────────────────

def test_pycan_transport_can_fd_padding() -> None:
    cfg = BusConfig(backend="virtual", channel="test_fd_pad", is_fd=True, pad_dlc=True)
    transport = open_virtual(cfg)
    try:
        assert transport.max_frame_len == 64

        # 10 bytes -> pad to 64 bytes (as per new requirements)
        data10 = bytes(range(10))
        sent = transport.send(0x600, data10)
        assert len(sent) == 64
        assert sent[:10] == data10
        assert sent[10:] == b"\x00" * 54

        # 60 bytes -> pad to 64
        data60 = bytes(range(60))
        sent2 = transport.send(0x600, data60)
        assert len(sent2) == 64

        # 4 bytes -> pad to 64 bytes when pad_dlc=True and is_fd=True
        data4 = bytes([1, 2, 3, 4])
        sent = transport.send(0x600, data4)
        assert len(sent) == 64
        assert sent[:4] == data4
        assert sent[4:] == b"\x00" * 60

        # 30 bytes -> pad to 64 bytes
        data30 = bytes(range(30))
        sent30 = transport.send(0x600, data30)
        assert len(sent30) == 64
        assert sent30[:30] == data30
        assert sent30[30:] == b"\x00" * 34
    finally:
        transport.close()


def test_pycan_transport_classic_can_limit() -> None:
    cfg = BusConfig(backend="virtual", channel="test_classic_pad", is_fd=False, pad_dlc=True)
    transport = open_virtual(cfg)
    try:
        assert transport.max_frame_len == 8
        sent = transport.send(0x600, b"\xff\x00")
        assert len(sent) == 8
        assert sent == b"\xff\x00\x00\x00\x00\x00\x00\x00"
    finally:
        transport.close()


# ── 3. A2L Parser IF_DATA XCP_ON_CAN_FD ──────────────────────────────────────

def test_a2l_parser_extracts_can_fd_parameters() -> None:
    a2l_text = """
    ASAP2_VERSION 1 60
    /begin PROJECT test "Project"
      /begin MODULE test "Module"
        /begin IF_DATA XCP
          /begin PROTOCOL_LAYER
            0x0103
            1000 2000 0 0 0
            64 64
            BYTE_ORDER_MSB_LAST
          /end PROTOCOL_LAYER
          /begin XCP_ON_CAN_FD
            CAN_FD_MAX_DLC_64
            CAN_FD_MAX_DLC_REQUIRED
          /end XCP_ON_CAN_FD
        /end IF_DATA
      /end MODULE
    /end PROJECT
    """
    db = parse(a2l_text)
    assert db.protocol_info is not None
    assert db.protocol_info.max_cto == 64
    assert db.protocol_info.max_dto == 64
    assert db.protocol_info.is_fd is True
    assert db.protocol_info.can_fd_max_dlc == 64
    assert db.protocol_info.max_dlc_required is True
    assert db.protocol_info.byte_order == "little"


# ── 4. DAQ High Capacity ODT Packing ─────────────────────────────────────────

def test_pack_odts_large_arrays_with_can_fd_max_dto() -> None:
    # 1 mảng float32 10 phần tử = 40 bytes
    # Trên Classic CAN (max_dto=8), signal 40B sẽ bị lỗi ValueError vì vượt quá 7B.
    # Trên CAN FD (max_dto=64), signal 40B sẽ vừa vặn trong ODT 0 (ngân sách 59B).
    signals = [
        DaqSignal(name="largeArray", address=0x8000_0000, ext=0, size=40, datatype="FLOAT32_IEEE"),
        DaqSignal(name="sensor1", address=0x8000_0030, ext=0, size=4, datatype="FLOAT32_IEEE"),
        DaqSignal(name="sensor2", address=0x8000_0034, ext=0, size=4, datatype="FLOAT32_IEEE"),
    ]

    odts = pack_odts(signals, timestamp_on=True, max_dto=64)
    # Tổng size = 40 + 4 + 4 = 48 bytes <= first_budget (59 bytes) -> tất cả vào ODT 0
    assert len(odts) == 1
    assert len(odts[0]) == 3


# ── 5. End-to-End CAN FD 64-byte Read / Write / Handshake ───────────────────

def test_can_fd_master_slave_short_download_and_short_upload() -> None:
    channel = "can_fd_e2e_test"
    slave_cfg = SlaveConfig(
        channel=channel,
        max_cto=64,
        max_dto=64,
        is_fd=True,
    )
    bus_cfg = BusConfig(
        backend="virtual",
        channel=channel,
        is_fd=True,
        cro_id=slave_cfg.cro_id,
        dto_id=slave_cfg.dto_id,
        pad_dlc=slave_cfg.pad_dlc,
    )

    with FakeSlave(slave_cfg) as slave:
        transport = open_virtual(bus_cfg)
        master = XcpMaster(transport, bus_cfg)
        try:
            caps = master.connect()
            assert caps.max_cto == 64
            assert caps.max_dto == 64

            # Ghi 32 bytes qua SHORT_DOWNLOAD (khi CTO=64, short_capacity = 64 - 8 = 56 bytes)
            test_data = bytes(range(32))
            master.write(0x8000_0000, test_data)

            # Kiểm tra slave đã nhận đủ 32 bytes
            assert slave.peek(0x8000_0000, 32) == test_data

            # Đọc 32 bytes qua SHORT_UPLOAD (khi CTO=64, max_chunk = 64 - 1 = 63 bytes)
            read_back = master.read(0x8000_0000, 32)
            assert read_back == test_data

            # Ghi khối 120 bytes -> chia 2 chunk (62B + 58B) thay vì 20 chunk trên CAN cổ điển
            large_data = bytes((i * 7) & 0xFF for i in range(120))
            master.write(0x8000_0100, large_data)
            assert slave.peek(0x8000_0100, 120) == large_data

            large_read = master.read(0x8000_0100, 120)
            assert large_read == large_data
        finally:
            master.close()
