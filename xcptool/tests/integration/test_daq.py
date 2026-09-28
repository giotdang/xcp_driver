"""D4b + D4c integration tests — DAQ allocation, configure_daq, DTO decode.

Chạy trên virtual bus với FakeSlave — đường code qua transport/ và master/
giống hệt lúc cắm ECU thật.
"""

from __future__ import annotations

import time

import can
import pytest

from xcptool.devtools.fakeslave import FakeSlave, SlaveConfig
from xcptool.master.constants import Cmd
from xcptool.master.daq import (
    DaqListConfig, DaqSignal, OdtSignalLayout, PredefinedDaqList,
    TimestampAccumulator,
    configure_daq, configure_daq_predefined, decode_dto, stop_daq,
)
from xcptool.session.api import BusConfig, StaticDaqCapacityError, UnsupportedByEcuError
from xcptool.session.real import RealSession


def _sig(name: str, size: int, addr: int = 0x8000_0000) -> DaqSignal:
    return DaqSignal(name=name, address=addr, ext=0, size=size, datatype="ULONG")


# ── fixture giúp lấy XcpMaster từ RealSession ────────────────────────────────

@pytest.fixture
def connected(channel: str) -> "Iterator[tuple]":
    from collections.abc import Iterator
    cfg = SlaveConfig(channel=channel)
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(bus)
        yield session, slave, cfg
    session.close()


# ── test trình tự lệnh ────────────────────────────────────────────────────────

def test_configure_daq_sends_correct_sequence(channel: str) -> None:
    """configure_daq() gửi đúng thứ tự lệnh: FREE→ALLOC→…→SYNCH."""
    cfg = SlaveConfig(channel=channel)
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]

        signals = [_sig("rpm", 4, 0x8000_0000), _sig("speed", 2, 0x8000_0004)]
        configs = [DaqListConfig(signals=signals, event=0, timestamp=True)]
        configure_daq(master, configs)

        cmds = list(slave.commands_seen)
        # Lọc bỏ lệnh của CONNECT và capability queries
        daq_cmds = [c for c in cmds if c in {
            int(Cmd.FREE_DAQ), int(Cmd.ALLOC_DAQ), int(Cmd.ALLOC_ODT),
            int(Cmd.ALLOC_ODT_ENTRY), int(Cmd.SET_DAQ_PTR), int(Cmd.WRITE_DAQ),
            int(Cmd.SET_DAQ_LIST_MODE), int(Cmd.START_STOP_DAQ_LIST),
            int(Cmd.START_STOP_SYNCH),
        }]

        # FREE_DAQ phải là lệnh đầu tiên trong chuỗi DAQ
        assert daq_cmds[0] == int(Cmd.FREE_DAQ)
        # START_STOP_SYNCH phải là lệnh cuối cùng
        assert daq_cmds[-1] == int(Cmd.START_STOP_SYNCH)
        # Phải có ít nhất một WRITE_DAQ
        assert int(Cmd.WRITE_DAQ) in daq_cmds

    session.close()


def test_configure_daq_returns_pid_table(channel: str) -> None:
    """PID table có đúng cấu trúc sau configure_daq().

    pack_odts với TS bật: first_budget=3B.
    - big(4B) > 3B → nhóm large → ODT 1
    - small(2B) ≤ 3B → nhóm small → ODT 0

    Kết quả: ODT 0 chứa small(2B), ODT 1 chứa big(4B).
    """
    cfg = SlaveConfig(channel=channel)
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]

        signals = [_sig("big", 4, 0x8000_0000), _sig("small", 2, 0x8000_0004)]
        configs = [DaqListConfig(signals=signals, event=0, timestamp=True)]
        pid_table = configure_daq(master, configs)

        # 2 ODT → 2 PID entry
        assert len(pid_table) == 2

        # ODT 0: small(2B) vào đây; has_timestamp=True
        pid0_entry = pid_table[0]
        assert pid0_entry.daq_list == 0
        assert pid0_entry.odt_index == 0
        assert pid0_entry.has_timestamp is True
        assert len(pid0_entry.signals) == 1
        assert pid0_entry.signals[0].signal.name == "small"

        # ODT 1: big(4B) vào đây; has_timestamp=False
        pid1_entry = pid_table[1]
        assert pid1_entry.odt_index == 1
        assert pid1_entry.has_timestamp is False
        assert len(pid1_entry.signals) == 1
        assert pid1_entry.signals[0].signal.name == "big"

    session.close()


def test_configure_daq_frame_offsets(channel: str) -> None:
    """Frame offset trong PidEntry tính đúng bao gồm PID và timestamp bytes."""
    cfg = SlaveConfig(channel=channel)
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]

        # Hai signal 1B + 2B, TS bật → cả hai vào ODT 0 (1+2=3B ≤ budget 3B)
        s1 = _sig("a", 2, 0x8000_0000)  # 2B
        s2 = _sig("b", 1, 0x8000_0002)  # 1B
        configs = [DaqListConfig(signals=[s1, s2], event=0, timestamp=True)]
        pid_table = configure_daq(master, configs)

        # Chỉ ODT 0 (1 PID entry)
        assert len(pid_table) == 1
        entry = pid_table[0]
        assert entry.has_timestamp is True

        # Layout: [PID(1B)][TS(4B)][s2(2B → sorted desc)][s1(1B)]
        # — pack_odts sắp xếp descending by size: s1(2B) trước, s2(1B) sau
        offsets = [sl.frame_offset for sl in entry.signals]
        assert offsets[0] == 5   # 1 (PID) + 4 (TS) = 5
        assert offsets[1] == 7   # 5 + 2 = 7

    session.close()


def test_configure_daq_writes_signals_to_fakeslave(channel: str) -> None:
    """FakeSlave lưu đúng (size, ext, addr) của từng signal qua WRITE_DAQ."""
    cfg = SlaveConfig(channel=channel)
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]

        s = _sig("x", 4, 0x8000_0008)
        configs = [DaqListConfig(signals=[s], event=1, timestamp=False)]
        configure_daq(master, configs)

        # signal 4B, TS tắt → budget=7 → vào ODT 0
        entries = slave.daq_entries(daq=0, odt=0)
        assert len(entries) == 1
        bit_off, sz, ext, addr = entries[0]
        assert bit_off == 0xFF   # không dùng bit masking
        assert sz == 4
        assert ext == 0
        assert addr == 0x8000_0008

    session.close()


def test_stop_daq_sets_slave_not_running(channel: str) -> None:
    """stop_daq() gửi START_STOP_SYNCH(0) và fakeslave ghi nhận daq_running=False."""
    cfg = SlaveConfig(channel=channel)
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]

        s = _sig("y", 2, 0x8000_0000)
        configs = [DaqListConfig(signals=[s], event=0, timestamp=False)]
        configure_daq(master, configs)
        assert slave.daq_running is True

        stop_daq(master)
        assert slave.daq_running is False

    session.close()


def test_configure_daq_fails_when_daq_not_supported(channel: str) -> None:
    """ECU không có DAQ → UnsupportedByEcuError ngay từ free_daq()."""
    cfg = SlaveConfig(channel=channel, supports_daq=False)
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg):
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]

        with pytest.raises(UnsupportedByEcuError):
            configure_daq(master, [DaqListConfig(signals=[_sig("z", 1)], event=0)])

    session.close()


# ── D4c — DTO decode từ FakeSlave ────────────────────────────────────────────

def test_fakeslave_sends_dto_frames_when_running(channel: str) -> None:
    """Sau START_STOP_SYNCH(1), FakeSlave phát DTO frame lên bus."""
    cfg = SlaveConfig(channel=channel)
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]

        addr = cfg.mem_base
        slave.poke(addr, b"\x2A\x00")   # 42 as uint16 LE

        sig = DaqSignal("count", addr, 0, 2, "UINT16")
        configs = [DaqListConfig(signals=[sig], event=0, timestamp=False)]
        configure_daq(master, configs)
        # DAQ đang chạy — mở sniffer SAU configure để tránh nhận CRO responses

        sniffer = can.Bus(interface="virtual", channel=channel, receive_own_messages=False)
        try:
            deadline = time.perf_counter() + 1.0
            daq_frame: bytes | None = None
            while time.perf_counter() < deadline:
                msg = sniffer.recv(0.05)
                if (msg is not None
                        and msg.arbitration_id == cfg.dto_id
                        and (msg.data[0] & 0x7F) == 0):
                    daq_frame = bytes(msg.data)
                    break
            assert daq_frame is not None, "FakeSlave không gửi frame DAQ nào trong 1 giây"
        finally:
            sniffer.shutdown()

    session.close()


def test_decode_dto_matches_fakeslave_memory(channel: str) -> None:
    """decode_dto() trả về bytes khớp với giá trị đã poke vào FakeSlave memory."""
    cfg = SlaveConfig(channel=channel)
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]

        addr = cfg.mem_base
        expected = b"\x39\x05"   # 0x0539 = 1337 little-endian
        slave.poke(addr, expected)

        sig = DaqSignal("val", addr, 0, 2, "UINT16")
        configs = [DaqListConfig(signals=[sig], event=0, timestamp=False)]
        pid_table = configure_daq(master, configs)

        sniffer = can.Bus(interface="virtual", channel=channel, receive_own_messages=False)
        try:
            deadline = time.perf_counter() + 1.0
            daq_frame: bytes | None = None
            while time.perf_counter() < deadline:
                msg = sniffer.recv(0.05)
                if (msg is not None
                        and msg.arbitration_id == cfg.dto_id
                        and (msg.data[0] & 0x7F) == 0):
                    daq_frame = bytes(msg.data)
                    break
            assert daq_frame is not None, "Không nhận được frame DAQ"

            ts_accum = TimestampAccumulator(byte_order=cfg.byte_order)
            samples = decode_dto(daq_frame, pid_table, ts_accum)

            val_samples = [s for s in samples if s.name == "val"]
            assert val_samples, f"Không có sample 'val' trong {samples}"
            assert val_samples[0].value_raw == expected
        finally:
            sniffer.shutdown()

    session.close()


def test_multiple_daq_lists_get_sequential_pids(channel: str) -> None:
    """Hai DAQ list → PID đầu tiên của list 1 = n_odts_of_list_0."""
    cfg = SlaveConfig(channel=channel)
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]

        # List 0: 1 signal 4B, TS=True → 2 ODT (ODT 0 rỗng + ODT 1 với signal)
        # List 1: 1 signal 2B, TS=False → 1 ODT
        configs = [
            DaqListConfig(signals=[_sig("a", 4, 0x8000_0000)], event=0, timestamp=True),
            DaqListConfig(signals=[_sig("b", 2, 0x8000_0004)], event=1, timestamp=False),
        ]
        pid_table = configure_daq(master, configs)

        # List 0 có 2 ODT → PID 0 và 1
        # List 1 có 1 ODT → PID 2
        pid_list0 = {pid for pid, e in pid_table.items() if e.daq_list == 0}
        pid_list1 = {pid for pid, e in pid_table.items() if e.daq_list == 1}

        assert pid_list0 == {0, 1}
        assert pid_list1 == {2}

    session.close()


# ── D4d — Static DAQ (dynamic_daq=False) ────────────────────────────────────

def test_configure_daq_static_ecu_uses_existing_list(channel: str) -> None:
    """ECU static (dynamic_daq=False) không bao giờ gửi FREE_DAQ/ALLOC_* —
    dùng CLEAR_DAQ_LIST + GET_DAQ_LIST_INFO trên list có sẵn thay vào đó."""
    cfg = SlaveConfig(channel=channel, daq_dynamic=False, min_daq=1, max_daq=1)
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]
        assert master.caps.daq is not None
        assert master.caps.daq.dynamic_daq is False

        configs = [DaqListConfig(signals=[_sig("rpm", 2)], event=0, timestamp=False)]
        pid_table = configure_daq(master, configs)

        assert len(pid_table) == 1
        assert pid_table[0].daq_list == 0
        assert slave.daq_running is True

        cmds = set(slave.commands_seen)
        assert int(Cmd.FREE_DAQ) not in cmds
        assert int(Cmd.ALLOC_DAQ) not in cmds
        assert int(Cmd.ALLOC_ODT) not in cmds
        assert int(Cmd.ALLOC_ODT_ENTRY) not in cmds
        assert int(Cmd.CLEAR_DAQ_LIST) in cmds
        assert int(Cmd.GET_DAQ_LIST_INFO) in cmds
        assert int(Cmd.WRITE_DAQ) in cmds

    session.close()


def test_configure_daq_static_raises_when_no_list_free(channel: str) -> None:
    """Chỉ 1 list tĩnh nhưng cần 2 (2 DaqListConfig riêng) → StaticDaqCapacityError
    rõ ràng, không phải mã lỗi ECU thô hay treo giữa chừng."""
    cfg = SlaveConfig(channel=channel, daq_dynamic=False, min_daq=1, max_daq=1)
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg):
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]

        configs = [
            DaqListConfig(signals=[_sig("a", 2)], event=0, timestamp=False),
            DaqListConfig(signals=[_sig("b", 2)], event=0, timestamp=False),
        ]
        with pytest.raises(StaticDaqCapacityError):
            configure_daq(master, configs)

    session.close()


def test_configure_daq_unknown_caps_on_static_ecu_raises_clear_error(channel: str) -> None:
    """caps.daq is None (ECU không trả GET_DAQ_PROCESSOR_INFO) trên một ECU thật
    ra là static (từ chối FREE_DAQ bằng UNKNOWN_CMD) → UnsupportedByEcuError với
    thông điệp giải thích rõ, không phải SlaveError thô của FREE_DAQ lộ ra ngoài."""
    cfg = SlaveConfig(channel=channel, daq_dynamic=False, supports_daq_info=False)
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg):
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]
        assert master.caps.daq is None   # xác nhận đúng tình huống test nhắm tới

        with pytest.raises(UnsupportedByEcuError) as exc_info:
            configure_daq(master, [DaqListConfig(signals=[_sig("z", 1)], event=0)])

        assert "GET_DAQ_PROCESSOR_INFO" in str(exc_info.value)

    session.close()


# ── D4d — Static DAQ với list nội dung cố định (predefined=True) ────────────

def test_configure_daq_skips_predefined_list_when_searching(channel: str) -> None:
    """configure_daq() (nhánh static thường, tự WRITE_DAQ) bỏ qua list
    predefined=True khi tìm chỗ ghi tự do — list 0 predefined, list 1 không,
    kết quả phải rơi vào list 1."""
    cfg = SlaveConfig(channel=channel, daq_dynamic=False, min_daq=2, max_daq=2,
                       static_predefined_lists=frozenset({0}))
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]

        configs = [DaqListConfig(signals=[_sig("rpm", 2)], event=0, timestamp=False)]
        pid_table = configure_daq(master, configs)

        assert pid_table[0].daq_list == 1   # list 0 predefined bị bỏ qua
        assert slave.write_daq_to_predefined == set()

    session.close()


def test_configure_daq_static_capacity_error_when_only_predefined_available(
    channel: str,
) -> None:
    """Chỉ có 1 list tĩnh và nó predefined=True → StaticDaqCapacityError rõ
    ràng, không âm thầm WRITE_DAQ vào nội dung cố định."""
    cfg = SlaveConfig(channel=channel, daq_dynamic=False, min_daq=1, max_daq=1,
                       static_predefined_lists=frozenset({0}))
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]

        configs = [DaqListConfig(signals=[_sig("rpm", 2)], event=0, timestamp=False)]
        with pytest.raises(StaticDaqCapacityError):
            configure_daq(master, configs)

        assert slave.write_daq_to_predefined == set()

    session.close()


def test_configure_daq_predefined_starts_fixed_list_without_writing(channel: str) -> None:
    """configure_daq_predefined() khởi động list nội dung cố định mà không
    hề gọi WRITE_DAQ — decode ra đúng giá trị "firmware" đã wire sẵn."""
    cfg = SlaveConfig(channel=channel, daq_dynamic=False, min_daq=1, max_daq=1,
                       static_predefined_lists=frozenset({0}))
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]

        addr = cfg.mem_base
        expected = b"\x39\x05"   # 0x0539 = 1337 little-endian
        slave.poke(addr, expected)
        # "Firmware" đã wire sẵn: ODT 0 của list 0 chứa 1 entry 2 byte tại addr
        slave.set_predefined_daq_content(0, 0, [(0xFF, 2, 0, addr)])

        sig = DaqSignal("val", addr, 0, 2, "UINT16")
        layout = OdtSignalLayout(signal=sig, frame_offset=1)   # byte 0=PID, không timestamp
        pl = PredefinedDaqList(daq=0, odts=[[layout]], event=0, timestamp=False)
        pid_table = configure_daq_predefined(master, [pl])

        assert slave.write_daq_to_predefined == set()
        assert slave.daq_running is True

        sniffer = can.Bus(interface="virtual", channel=channel, receive_own_messages=False)
        try:
            deadline = time.perf_counter() + 1.0
            daq_frame: bytes | None = None
            while time.perf_counter() < deadline:
                msg = sniffer.recv(0.05)
                if (msg is not None
                        and msg.arbitration_id == cfg.dto_id
                        and (msg.data[0] & 0x7F) == 0):
                    daq_frame = bytes(msg.data)
                    break
            assert daq_frame is not None, "Không nhận được frame DAQ"

            ts_accum = TimestampAccumulator(byte_order=cfg.byte_order)
            samples = decode_dto(daq_frame, pid_table, ts_accum)

            val_samples = [s for s in samples if s.name == "val"]
            assert val_samples, f"Không có sample 'val' trong {samples}"
            assert val_samples[0].value_raw == expected
        finally:
            sniffer.shutdown()

    session.close()


def test_configure_daq_predefined_rejects_non_predefined_list(channel: str) -> None:
    """configure_daq_predefined() từ chối list không thực sự predefined —
    tránh nhầm sang list mà đáng lẽ phải tự WRITE_DAQ qua configure_daq()."""
    cfg = SlaveConfig(channel=channel, daq_dynamic=False, min_daq=1, max_daq=1)
    bus = BusConfig(backend="virtual", channel=channel,
                    cro_id=cfg.cro_id, dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg):
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]

        sig = DaqSignal("x", cfg.mem_base, 0, 2, "UINT16")
        layout = OdtSignalLayout(signal=sig, frame_offset=1)
        pl = PredefinedDaqList(daq=0, odts=[[layout]], event=0, timestamp=False)

        with pytest.raises(ValueError):
            configure_daq_predefined(master, [pl])

    session.close()
