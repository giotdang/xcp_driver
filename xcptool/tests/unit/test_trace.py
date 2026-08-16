"""B1 — ring buffer trace: có trần, đếm drop, pull-based, an toàn thread."""

from __future__ import annotations

import threading

import pytest

from xcptool.master.trace import TraceBuffer


def add(buf: TraceBuffer, n: int) -> None:
    for i in range(n):
        buf.add("rx", 0x100, bytes([i & 0xFF]), "daq", f"frame {i}")


def test_drain_returns_nothing_when_empty() -> None:
    assert TraceBuffer(10).drain() == []


def test_seq_is_monotonic_and_unique() -> None:
    buf = TraceBuffer(100)
    add(buf, 50)
    seqs = [e.seq for e in buf.drain()]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == 50


def test_buffer_drops_oldest_and_counts_it() -> None:
    """Quá trần thì bỏ entry CŨ nhất — entry mới là thứ user đang nhìn."""
    buf = TraceBuffer(10)
    add(buf, 25)

    assert buf.dropped == 15
    items = buf.drain()
    assert len(items) == 10
    assert items[0].decoded == "frame 15"
    assert items[-1].decoded == "frame 24"


def test_ram_stays_flat_under_flood() -> None:
    buf = TraceBuffer(100)
    add(buf, 50_000)
    assert buf.dropped == 49_900
    assert len(buf.drain(1_000_000)) == 100


def test_drain_respects_max_items_and_keeps_the_rest() -> None:
    buf = TraceBuffer(100)
    add(buf, 30)

    first = buf.drain(10)
    assert [e.decoded for e in first] == [f"frame {i}" for i in range(10)]
    assert len(buf.drain(1000)) == 20


def test_drain_zero_is_a_noop() -> None:
    buf = TraceBuffer(10)
    add(buf, 5)
    assert buf.drain(0) == []
    assert len(buf.drain()) == 5


def test_concurrent_add_and_drain_lose_nothing() -> None:
    """Một producer (RX thread) + một consumer (UI timer) — đúng mô hình thật."""
    buf = TraceBuffer(100_000)
    total = 20_000
    collected: list[int] = []
    done = threading.Event()

    def producer() -> None:
        add(buf, total)
        done.set()

    t = threading.Thread(target=producer)
    t.start()
    while True:
        # Đọc cờ TRƯỚC khi rút, nếu không vòng cuối sẽ bỏ sót entry vừa thêm.
        finished = done.is_set()
        collected.extend(e.seq for e in buf.drain())
        if finished:
            break
    t.join()

    assert buf.dropped == 0
    assert sorted(collected) == list(range(1, total + 1))


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError):
        TraceBuffer(0)
