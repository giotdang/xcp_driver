"""B2 — `list_devices()` trên máy thật.

Trên máy dev điển hình chưa cài driver hãng nào, nên đường `available=False`
+ `hint` là đường CHÍNH chứ không phải trường hợp biên (DEV_PLAN §5.1).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from xcptool.session.api import BusConfig, DeviceInfo, DriverMissingError
from xcptool.session.real import RealSession
from xcptool.transport.registry import SPECS, list_devices, open_transport


@pytest.fixture(scope="module")
def devices() -> list[DeviceInfo]:
    return list_devices()


def test_listing_never_raises(devices: list[DeviceInfo]) -> None:
    assert devices


def test_every_backend_appears(devices: list[DeviceInfo]) -> None:
    """Im lặng bỏ qua backend thiếu driver là thiết kế tồi — user không biết vì sao."""
    assert {d.backend for d in devices} == set(SPECS)


def test_virtual_is_always_usable(devices: list[DeviceInfo]) -> None:
    virtual = [d for d in devices if d.backend == "virtual"]
    assert len(virtual) == 1
    assert virtual[0].available is True
    assert virtual[0].channel
    assert virtual[0].display_name


def test_unavailable_backends_explain_themselves(devices: list[DeviceInfo]) -> None:
    for dev in devices:
        if dev.available:
            continue
        assert dev.hint, f"{dev.backend}: available=False mà không có hint"
        # Hint phải nói được cần cài gì hoặc vì sao không dùng được,
        # không phải một chuỗi rỗng cho có.
        assert len(dev.hint) > 20


def test_display_names_are_ready_to_show(devices: list[DeviceInfo]) -> None:
    for dev in devices:
        assert dev.display_name.strip()
        assert dev.display_name != dev.backend


def test_listing_is_stable_across_calls(devices: list[DeviceInfo]) -> None:
    """Cảnh báo của python-can chỉ phát ra ở lần import đầu — lần gọi thứ hai
    vẫn phải có hint như lần đầu, nếu không user bấm Detect lần hai sẽ thấy
    thông báo nghèo đi một cách khó hiểu."""
    again = list_devices()
    assert [(d.backend, d.available) for d in again] == \
           [(d.backend, d.available) for d in devices]
    for before, after in zip(devices, again, strict=True):
        assert bool(before.hint) == bool(after.hint)


def test_detection_leaks_nothing_to_stderr() -> None:
    """Cổng của B2, chạy trong tiến trình con vì cảnh báo của python-can phát ra
    đúng MỘT lần lúc import — thử trong tiến trình này sẽ xanh giả."""
    code = (
        "from xcptool.transport.registry import list_devices\n"
        "devs = list_devices()\n"
        "assert any(d.backend == 'virtual' and d.available for d in devs)\n"
        "print(len(devs))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=120, check=False)

    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == "", f"python-can làm rò cảnh báo ra stderr:\n{proc.stderr}"


def test_session_lists_devices_without_a_bus(session: RealSession) -> None:
    assert any(d.backend == "virtual" for d in session.list_devices())


def test_unknown_backend_is_a_named_error() -> None:
    with pytest.raises(DriverMissingError):
        open_transport(BusConfig(backend="nope", channel="x"))
