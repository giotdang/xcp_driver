"""B2 — backend `replay`: xem lại một phiên đã ghi, không cần bus."""

from __future__ import annotations

import pytest

from xcptool.session.api import BusConfig, DeviceNotFoundError
from xcptool.transport.registry import open_transport
from xcptool.transport.replay import ReplayTransport, parse_trace_log

LOG = """
# phiên hôm qua
0.000 tx 600 FF 00
0.010 rx 601 FF 05 00 08 08 00 01 01
0.020 rx 601 01 02 03
"""


def test_parser_keeps_only_received_frames() -> None:
    """Frame tx trong file là của phiên cũ — phát lại chúng là tự nói với mình."""
    frames = parse_trace_log(LOG)
    assert [f[1] for f in frames] == [0x601, 0x601]
    assert frames[0][2] == bytes([0xFF, 0x05, 0x00, 0x08, 0x08, 0x00, 0x01, 0x01])


def test_parser_survives_junk() -> None:
    frames = parse_trace_log(
        "không phải một dòng hợp lệ\n"
        "abc rx 601 FF\n"          # timestamp hỏng
        "0.1 rx ZZZ FF\n"          # CAN ID hỏng
        "0.2 rx 601 GG\n"          # byte hỏng
        "0.3 rx 601 AB\n"          # dòng tốt duy nhất
    )
    assert frames == [(0.3, 0x601, b"\xab")]


def test_transport_replays_in_order() -> None:
    transport = ReplayTransport(parse_trace_log(LOG), realtime=False)
    try:
        first = transport.recv(1.0)
        second = transport.recv(1.0)
        assert first is not None and second is not None
        assert first.data[0] == 0xFF
        assert second.data == b"\x01\x02\x03"
        assert transport.recv(0.05) is None      # hết file, không phải lỗi
    finally:
        transport.close()


def test_sending_into_a_replay_is_harmless() -> None:
    """Không có ai ở đầu kia, nhưng gửi cũng không được nổ."""
    transport = ReplayTransport([], realtime=False)
    try:
        assert transport.send(0x600, b"\xff\x00") == b"\xff\x00"
    finally:
        transport.close()


def test_missing_file_is_a_named_error(tmp_path) -> None:
    with pytest.raises(DeviceNotFoundError):
        open_transport(BusConfig(backend="replay",
                                 channel=str(tmp_path / "không-có.log")))


def test_opening_a_real_file_works(tmp_path) -> None:
    path = tmp_path / "trace.log"
    path.write_text(LOG, encoding="utf-8")
    transport = open_transport(BusConfig(backend="replay", channel=str(path)))
    try:
        assert transport.recv(2.0) is not None
    finally:
        transport.close()
