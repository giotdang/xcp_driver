"""B1 — demux CTO/DTO và chuỗi `decoded`."""

from __future__ import annotations

import pytest

from xcptool.master.codec import classify, describe_rx, describe_tx, hexs
from xcptool.master.constants import Cmd


@pytest.mark.parametrize(("byte0", "expected"), [
    (0xFF, "res"), (0xFE, "err"), (0xFD, "ev"), (0xFC, "serv"),
    (0xFB, "daq"), (0x00, "daq"), (0x01, "daq"), (0x7F, "daq"), (0x80, "daq"),
])
def test_classify_demuxes_by_first_byte(byte0: int, expected: str) -> None:
    """CRM và DTO dùng chung CAN ID — byte 0 là thứ duy nhất phân biệt được."""
    assert classify(bytes([byte0, 1, 2, 3])) == expected


def test_classify_empty_frame_is_not_a_response() -> None:
    assert classify(b"") == "daq"


def test_decoded_is_never_empty_even_for_garbage() -> None:
    """Contract: `decoded` LUÔN có giá trị, frontend không tự giải mã byte."""
    for data in (b"", b"\x00", b"\xab\xcd", bytes(range(8))):
        assert describe_rx(data)
        assert describe_tx(data) if data else describe_tx(data) == "(rỗng)"


def test_describe_tx_names_known_commands() -> None:
    assert describe_tx(bytes([Cmd.CONNECT, 0])) == "CONNECT mode=0"
    assert describe_tx(bytes([Cmd.DISCONNECT])) == "DISCONNECT"
    assert "SET_MTA" in describe_tx(bytes([Cmd.SET_MTA, 0, 0, 0, 0x00, 0x10, 0, 0x80]))


def test_describe_tx_unknown_command_falls_back_to_hex() -> None:
    assert describe_tx(b"\x01\x02") == "CMD? 01 02"


def test_describe_rx_names_error_codes() -> None:
    assert describe_rx(b"\xfe\x23") == "ERR ERR_WRITE_PROTECTED"
    assert describe_rx(b"\xfe\x7f") == "ERR ERR_UNKNOWN_0x7F"
    assert describe_rx(b"\xfe") == "ERR (thiếu mã lỗi)"


def test_describe_rx_expands_connect_response() -> None:
    resp = bytes([0xFF, 0x05, 0x00, 8, 8, 0, 1, 1])
    text = describe_rx(resp, pending_cmd=int(Cmd.CONNECT))
    assert "MAX_CTO=8" in text


def test_describe_rx_marks_daq_overrun() -> None:
    """Bit 7 của PID là cờ overrun, không phải một PID khác."""
    assert "pid=1 OVERRUN" in describe_rx(bytes([0x81, 1, 2, 3]))
    assert "OVERRUN" not in describe_rx(bytes([0x01, 1, 2, 3]))


def test_hexs_formatting() -> None:
    assert hexs(b"\x00\xab\xff") == "00 AB FF"
