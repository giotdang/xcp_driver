""" B4 — "không crash" là tiêu chí nghiệm thu, không phải lời chúc.

Mỗi test dưới đây là một dòng trong bảng DEV_PLAN.md §6 thuộc phần backend.
"""

from __future__ import annotations

import threading
import time

import pytest

from xcptool.devtools.fakeslave import FakeSlave, SlaveConfig
from xcptool.master.constants import Cmd
from xcptool.session.api import (
    BusConfig,
    BusError,
    BusyError,
    ConnState,
    DeviceNotFoundError,
    MalformedResponseError,
    TransportError,
    XcpTimeoutError,
    XcpToolError,
)
from xcptool.session.real import RealSession
from xcptool.transport import registry
from xcptool.transport.base import CanFrame, Transport


class FaultyTransport(Transport):
    """Bọc một transport thật, hỏng theo lệnh của test."""

    def __init__(self, inner: Transport) -> None:
        self._inner = inner
        self.recv_raises: BaseException | None = None
        self.send_raises: BaseException | None = None

    def send(self, can_id: int, data: bytes) -> bytes:
        if self.send_raises is not None:
            raise self.send_raises
        return self._inner.send(can_id, data)

    def recv(self, timeout: float) -> CanFrame | None:
        if self.recv_raises is not None:
            raise self.recv_raises
        return self._inner.recv(timeout)

    def close(self) -> None:
        self._inner.close()


@pytest.fixture
def faulty(monkeypatch) -> list[FaultyTransport]:
    """Bắt transport mà RealSession mở được, để test bơm lỗi vào."""
    made: list[FaultyTransport] = []
    real_open = registry.open_transport

    def wrapper(cfg: BusConfig) -> Transport:
        t = FaultyTransport(real_open(cfg))
        made.append(t)
        return t

    monkeypatch.setattr(registry, "open_transport", wrapper)
    return made


def wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# ── exception trong RX thread ────────────────────────────────────────────────


def test_unexpected_exception_in_rx_thread_does_not_kill_the_process(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave,
    faulty: list[FaultyTransport],
) -> None:
    """Lỗi lạ (không phải XcpToolError) trong RX thread → state=ERROR, app sống."""
    session.connect(bus_cfg)
    before = threading.active_count()

    faulty[0].recv_raises = RuntimeError("driver nổ tung")

    assert wait_until(lambda: session.state is ConnState.ERROR)
    assert threading.active_count() <= before
    # Và mọi lệnh sau đó báo lỗi tử tế thay vì treo.
    with pytest.raises(XcpToolError):
        session.read(slave.cfg.mem_base, 4)


def test_rx_thread_failure_wakes_the_waiting_command(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave,
    faulty: list[FaultyTransport],
) -> None:
    """Không được bắt lệnh đang chờ ngồi hết T1 khi đã biết link chết."""
    session.connect(bus_cfg)
    slave.cfg.response_delay_s = 2.0        # lâu hơn T1 để lệnh chắc chắn đang chờ

    result: list[BaseException] = []

    def command() -> None:
        try:
            session.read(slave.cfg.mem_base, 4)
        except BaseException as exc:  # noqa: BLE001
            result.append(exc)

    t = threading.Thread(target=command)
    t.start()
    time.sleep(0.1)
    faulty[0].recv_raises = RuntimeError("rút dây")
    t.join(timeout=3.0)

    assert not t.is_alive(), "lệnh đang chờ bị treo khi RX thread chết"
    assert result and isinstance(result[0], XcpToolError)


# ── rút dây ──────────────────────────────────────────────────────────────────


def test_device_disappearing_surfaces_as_a_named_transport_error(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave,
    faulty: list[FaultyTransport],
) -> None:
    session.connect(bus_cfg)
    faulty[0].recv_raises = DeviceNotFoundError("thiết bị đã bị rút")

    assert wait_until(lambda: session.state is ConnState.ERROR)
    with pytest.raises(TransportError):
        session.read(slave.cfg.mem_base, 4)


def test_send_failure_is_a_bus_error_not_a_traceback(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave,
    faulty: list[FaultyTransport],
) -> None:
    session.connect(bus_cfg)
    faulty[0].send_raises = BusError("hàng gửi đầy")

    with pytest.raises(BusError):
        session.read(slave.cfg.mem_base, 4)


# ── ECU không trả lời ────────────────────────────────────────────────────────


def test_silent_ecu_times_out_without_hanging(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    session.connect(bus_cfg)
    slave.cfg.drop_responses = 999

    started = time.perf_counter()
    with pytest.raises(XcpTimeoutError):
        session.read(slave.cfg.mem_base, 4)
    elapsed = time.perf_counter() - started

    assert elapsed < bus_cfg.t1_timeout_s * 5
    # Sau khi ECU tỉnh lại, phiên dùng tiếp được — không cần connect lại.
    slave.cfg.drop_responses = 0
    assert len(session.read(slave.cfg.mem_base, 4)) == 4


# ── frame méo ────────────────────────────────────────────────────────────────


def test_truncated_response_is_malformed_not_indexerror(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    """Bắt buộc là MalformedResponseError, KHÔNG phải struct.error / IndexError."""
    session.connect(bus_cfg)
    slave.cfg.truncate_responses = 1

    with pytest.raises(MalformedResponseError):
        session.read(slave.cfg.mem_base, 4)


def test_truncated_connect_response_is_malformed(
    channel: str, session: RealSession
) -> None:
    cfg = SlaveConfig(channel=channel, truncate_responses=1)
    bus = BusConfig(backend="virtual", channel=channel, cro_id=cfg.cro_id,
                    dto_id=cfg.dto_id, t1_timeout_s=0.5)
    with FakeSlave(cfg), pytest.raises(MalformedResponseError):
        session.connect(bus)
    assert session.state is ConnState.DISCONNECTED


@pytest.mark.parametrize("garbage", [b"\xff", b"\xfe", b"", b"\xff\x00"])
def test_garbage_frames_never_escape_as_low_level_errors(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave, garbage: bytes
) -> None:
    """ECU của hãng khác gửi rác — mọi thứ lọt ra phải là XcpToolError."""
    session.connect(bus_cfg)
    slave.cfg.drop_responses = 99          # response thật bị nuốt

    def inject() -> None:
        time.sleep(0.05)
        slave.send_raw(bus_cfg.dto_id, garbage)

    threading.Thread(target=inject, daemon=True).start()
    with pytest.raises(XcpToolError):
        session.read(slave.cfg.mem_base, 4)


def test_unknown_can_id_is_traced_as_other_and_ignored(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    session.connect(bus_cfg)
    session.drain_trace()
    stranger = bus_cfg.dto_id + 0x100

    slave.send_raw(stranger, b"\xff\xff\xff\xff\xff\xff\xff\xff")
    others: list = []

    def seen() -> bool:
        others.extend(e for e in session.drain_trace() if e.kind == "other")
        return bool(others)

    assert wait_until(seen)
    assert others and others[0].can_id == stranger
    # Không bị nhận nhầm thành response: lệnh kế tiếp vẫn chạy đúng.
    assert session.read(slave.cfg.mem_base, 4) is not None


# ── flood ────────────────────────────────────────────────────────────────────


def test_flood_caps_the_ring_buffer_and_counts_drops(channel: str) -> None:
    """5000 frame/s → bỏ entry cũ, tăng dropped_frames, RAM phẳng."""
    cfg = SlaveConfig(channel=channel, daq_flood_hz=5000)
    bus = BusConfig(backend="virtual", channel=channel, cro_id=cfg.cro_id,
                    dto_id=cfg.dto_id, t1_timeout_s=0.5)
    capacity = 500
    session = RealSession(trace_capacity=capacity)
    try:
        with FakeSlave(cfg):
            session.connect(bus)
            # Cố tình KHÔNG rút trace — mô phỏng UI đang bận / bị treo.
            time.sleep(2.0)

            assert session.dropped_frames > 0, "phải có frame bị bỏ khi flood"
            batch = session.drain_trace(1_000_000)
            assert len(batch) <= capacity, "ring buffer vượt trần → RAM sẽ phình"
            # Giữ entry MỚI nhất, bỏ entry cũ nhất.
            assert batch == sorted(batch, key=lambda e: e.seq)
    finally:
        session.close()


def test_flood_does_not_break_normal_commands(channel: str) -> None:
    """DAQ bắn liên tục trong khi user vẫn đọc/ghi calibration."""
    cfg = SlaveConfig(channel=channel, daq_flood_hz=2000)
    bus = BusConfig(backend="virtual", channel=channel, cro_id=cfg.cro_id,
                    dto_id=cfg.dto_id, t1_timeout_s=1.0)
    session = RealSession(trace_capacity=2000)
    try:
        with FakeSlave(cfg) as slave:
            session.connect(bus)
            for i in range(10):
                payload = bytes([i]) * 8
                session.write(cfg.mem_base, payload)
                assert session.read(cfg.mem_base, 8) == payload
            assert slave is not None
    finally:
        session.close()


# ── lệnh chồng nhau ──────────────────────────────────────────────────────────


def test_overlapping_commands_raise_busy_immediately(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    """Không xếp hàng, không deadlock — ném BusyError ngay."""
    session.connect(bus_cfg)
    slave.cfg.response_delay_s = bus_cfg.t1_timeout_s / 2

    errors: list[BaseException] = []
    started = threading.Event()

    def slow() -> None:
        started.set()
        try:
            session.read(slave.cfg.mem_base, 4)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t = threading.Thread(target=slow)
    t.start()
    started.wait(1.0)
    time.sleep(0.1)                      # chắc chắn lệnh kia đã cầm bus

    began = time.perf_counter()
    with pytest.raises(BusyError):
        session.read(slave.cfg.mem_base, 4)
    assert time.perf_counter() - began < 0.2, "BusyError phải tức thì, không chờ"

    t.join(timeout=5.0)
    assert not errors


def test_bus_is_usable_again_after_busy(
    session: RealSession, bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    """BusyError không được để lại lock treo."""
    session.connect(bus_cfg)
    slave.cfg.response_delay_s = 0.3

    t = threading.Thread(target=lambda: session.read(slave.cfg.mem_base, 4))
    t.start()
    time.sleep(0.05)
    with pytest.raises(BusyError):
        session.read(slave.cfg.mem_base, 4)
    t.join(timeout=5.0)

    slave.cfg.response_delay_s = 0.0
    assert len(session.read(slave.cfg.mem_base, 4)) == 4


# ── close() ──────────────────────────────────────────────────────────────────


def test_close_before_connect_is_silent() -> None:
    RealSession().close()


def test_close_is_idempotent(bus_cfg: BusConfig, slave: FakeSlave) -> None:
    s = RealSession()
    s.connect(bus_cfg)
    s.close()
    s.close()
    s.close()
    assert s.state is ConnState.DISCONNECTED


def test_close_on_a_broken_bus_does_not_raise(
    bus_cfg: BusConfig, slave: FakeSlave, faulty: list[FaultyTransport]
) -> None:
    s = RealSession()
    s.connect(bus_cfg)
    faulty[0].recv_raises = RuntimeError("bus chết")
    faulty[0].send_raises = BusError("bus chết")
    wait_until(lambda: s.state is ConnState.ERROR)
    s.close()
    s.close()


def test_close_sends_disconnect(bus_cfg: BusConfig, slave: FakeSlave) -> None:
    """Quên DISCONNECT thì ECU cứ tiếp tục bắn DAQ lên bus sau khi app thoát."""
    s = RealSession()
    s.connect(bus_cfg)
    slave.commands_seen.clear()
    s.close()

    assert wait_until(lambda: int(Cmd.DISCONNECT) in slave.commands_seen)


def test_close_while_busy_finishes_quickly_and_quietly(
    bus_cfg: BusConfig, slave: FakeSlave
) -> None:
    """User đóng app giữa lúc đang đọc — không treo, không ném."""
    s = RealSession()
    s.connect(bus_cfg)
    # Phải nhỏ hơn hẳn T1: nếu lệnh kia rơi vào retry-sau-SYNCH thì nó giữ bus
    # tới 2×T1 và close() bỏ DISCONNECT một cách chính đáng — khi đó test này
    # đo nhầm thứ khác.
    slave.cfg.response_delay_s = bus_cfg.t1_timeout_s / 3
    slave.commands_seen.clear()

    t = threading.Thread(target=lambda: _swallow(lambda: s.read(slave.cfg.mem_base, 4)))
    t.start()
    time.sleep(0.1)

    began = time.perf_counter()
    s.close()
    assert time.perf_counter() - began < 5.0, "close() treo"

    t.join(timeout=5.0)
    assert not t.is_alive()
    assert int(Cmd.DISCONNECT) in slave.commands_seen


def test_no_thread_is_left_behind(bus_cfg: BusConfig, slave: FakeSlave) -> None:
    before = threading.active_count()
    for _ in range(5):
        s = RealSession()
        s.connect(bus_cfg)
        s.close()
    assert wait_until(lambda: threading.active_count() <= before)


def _swallow(fn) -> None:
    try:
        fn()
    except XcpToolError:
        pass
