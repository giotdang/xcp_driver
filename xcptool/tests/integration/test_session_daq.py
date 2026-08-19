"""D4d integration tests — Session DAQ contract: start_daq / drain_daq / stop_daq.

Kiểm tra qua `Session` protocol (session/api.py) — không import từ master/
hay transport/.  Dùng FakeSession + RealSession trên virtual bus với FakeSlave.
"""

from __future__ import annotations

import time

import pytest

from xcptool.devtools.fakeslave import FakeSlave, SlaveConfig
from xcptool.session.api import BusConfig, DaqList, DaqSignal, SamplePoint, UnsupportedByEcuError
from xcptool.session.fake import FakeSession
from xcptool.session.real import RealSession


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def fake() -> FakeSession:
    s = FakeSession()
    s.connect(BusConfig(backend="virtual", channel="fake0"))
    yield s
    s.close()


# ── FakeSession stubs ─────────────────────────────────────────────────────────

def test_fake_start_daq_sets_running(fake: FakeSession) -> None:
    sig = DaqSignal("x", 0x8000_0000, 0, 4, "UINT32")
    fake.start_daq([DaqList(signals=[sig], event=0)])
    assert fake._daq_running is True


def test_fake_stop_daq_clears_running(fake: FakeSession) -> None:
    sig = DaqSignal("x", 0x8000_0000, 0, 4, "UINT32")
    fake.start_daq([DaqList(signals=[sig], event=0)])
    fake.stop_daq()
    assert fake._daq_running is False


def test_fake_drain_daq_returns_empty(fake: FakeSession) -> None:
    """FakeSession không phát frame thật — drain luôn trả list rỗng."""
    sig = DaqSignal("x", 0x8000_0000, 0, 4, "UINT32")
    fake.start_daq([DaqList(signals=[sig], event=0)])
    assert fake.drain_daq(100) == []


def test_fake_start_daq_requires_daq_support() -> None:
    from xcptool.session.fake import FakeBehavior
    s = FakeSession(FakeBehavior(supports_daq=False))
    s.connect(BusConfig(backend="virtual", channel="fake0"))
    with pytest.raises(UnsupportedByEcuError):
        s.start_daq([DaqList(signals=[DaqSignal("x", 0x8000_0000, 0, 1, "UINT8")], event=0)])
    s.close()


# ── RealSession qua virtual bus ───────────────────────────────────────────────

def _make_real(channel: str, cfg: SlaveConfig) -> tuple[RealSession, BusConfig]:
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    return session, bus


def test_real_drain_daq_returns_sample_points(channel: str) -> None:
    """start_daq → đợi frames → drain_daq → có SamplePoint với bytes đúng."""
    cfg = SlaveConfig(channel=channel)
    session, bus = _make_real(channel, cfg)

    with FakeSlave(cfg) as slave:
        session.connect(bus)

        addr = cfg.mem_base
        expected = b"\xFF\x00"   # 255 as uint16 LE
        slave.poke(addr, expected)

        sig = DaqSignal("temp", addr, 0, 2, "UINT16")
        session.start_daq([DaqList(signals=[sig], event=0, timestamp=False)])

        # Đợi FakeSlave phát ít nhất một frame (100 Hz → 10ms mỗi frame)
        deadline = time.perf_counter() + 1.0
        samples: list[SamplePoint] = []
        while time.perf_counter() < deadline and not samples:
            time.sleep(0.02)
            samples = session.drain_daq(100)

        assert samples, "Không nhận được sample nào trong 1 giây"
        temp = [s for s in samples if s.name == "temp"]
        assert temp, f"Không tìm thấy sample 'temp' trong {[s.name for s in samples]}"
        assert temp[0].value_raw == expected

    session.close()


def test_real_stop_daq_stops_samples(channel: str) -> None:
    """Sau stop_daq(), drain_daq() không còn trả sample mới."""
    cfg = SlaveConfig(channel=channel)
    session, bus = _make_real(channel, cfg)

    with FakeSlave(cfg) as slave:
        session.connect(bus)

        sig = DaqSignal("x", cfg.mem_base, 0, 1, "UINT8")
        session.start_daq([DaqList(signals=[sig], event=0, timestamp=False)])
        time.sleep(0.05)   # nhận vài frame

        session.stop_daq()

        # Drain tất cả còn trong ring
        session.drain_daq(10_000)

        # Sau stop, không frame nào mới
        time.sleep(0.05)
        assert session.drain_daq(100) == [], "Vẫn còn sample sau stop_daq()"

    session.close()


def test_real_drain_daq_is_non_blocking(channel: str) -> None:
    """drain_daq() phải trả về ngay khi không có gì — không block."""
    cfg = SlaveConfig(channel=channel)
    session, bus = _make_real(channel, cfg)

    with FakeSlave(cfg) as slave:
        session.connect(bus)
        # Chưa start DAQ → drain phải trả []
        t0 = time.perf_counter()
        result = session.drain_daq(100)
        elapsed = time.perf_counter() - t0
        assert result == []
        assert elapsed < 0.05, f"drain_daq() bị block {elapsed:.3f}s"

    session.close()


def test_real_sample_has_correct_datatype(channel: str) -> None:
    """SamplePoint.datatype khớp với DaqSignal.datatype."""
    cfg = SlaveConfig(channel=channel)
    session, bus = _make_real(channel, cfg)

    with FakeSlave(cfg) as slave:
        session.connect(bus)

        sig = DaqSignal("rpm", cfg.mem_base, 0, 4, "FLOAT32")
        session.start_daq([DaqList(signals=[sig], event=0, timestamp=False)])

        deadline = time.perf_counter() + 1.0
        samples: list[SamplePoint] = []
        while time.perf_counter() < deadline and not samples:
            time.sleep(0.02)
            samples = session.drain_daq(100)

        assert samples
        rpm = [s for s in samples if s.name == "rpm"]
        assert rpm
        assert rpm[0].datatype == "FLOAT32"

    session.close()
