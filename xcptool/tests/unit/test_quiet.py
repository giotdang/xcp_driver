"""B2 — bắt tiếng ồn của python-can và lọc ra đúng dòng đáng thành `hint`."""

from __future__ import annotations

import logging
import sys

from xcptool.transport.quiet import capture_can_logs


def emit(name: str, message: str, level: int = logging.WARNING) -> None:
    logging.getLogger(name).log(level, message)


def test_nothing_reaches_stderr_inside_the_block(capsys) -> None:
    with capture_can_logs():
        emit("can.interfaces.vector.canlib", "Could not import vxlapi")
        print("thẳng ra stderr", file=sys.stderr)
    assert capsys.readouterr().err == ""


def test_captured_lines_are_available_afterwards() -> None:
    with capture_can_logs() as cap:
        emit("can.interfaces.vector.canlib", "Could not import vxlapi: not found")
    assert cap.messages_for("vector") == ["Could not import vxlapi: not found"]


def test_harmless_advice_does_not_become_a_hint() -> None:
    """python-can nói cả những thứ vô hại. Nếu lấy bừa dòng đầu tiên thì hint
    của PEAK sẽ nói về timestamp thay vì nói cần cài PCAN-Basic."""
    with capture_can_logs() as cap:
        emit("can.interfaces.pcan.pcan",
             "uptime library not available, timestamps are relative to boot time")
    assert cap.messages_for("pcan") == []
    assert cap.messages_for("pcan", blocking_only=False)


def test_blocking_lines_are_kept() -> None:
    with capture_can_logs() as cap:
        emit("can.interfaces.slcan",
             "You won't be able to use the slcan can backend without the serial module")
        emit("can.interfaces.pcan.pcan", "Cannot load PCANBasic library")
    assert len(cap.messages_for("slcan")) == 1
    assert len(cap.messages_for("pcan")) == 1


def test_debug_lines_are_not_hints() -> None:
    with capture_can_logs() as cap:
        emit("can.interface", "Could not import something", level=logging.DEBUG)
    assert cap.messages_for("can") == []


def test_logging_state_is_restored() -> None:
    can_log = logging.getLogger("can")
    before = (can_log.propagate, can_log.level, len(can_log.handlers))
    with capture_can_logs():
        pass
    assert (can_log.propagate, can_log.level, len(can_log.handlers)) == before


def test_state_is_restored_even_after_an_exception() -> None:
    can_log = logging.getLogger("can")
    before = (can_log.propagate, can_log.level, len(can_log.handlers))
    try:
        with capture_can_logs():
            raise RuntimeError("dò thiết bị nổ")
    except RuntimeError:
        pass
    assert (can_log.propagate, can_log.level, len(can_log.handlers)) == before
