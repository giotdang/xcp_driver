"""Ring buffer trace có trần — pull-based, an toàn thread.

Contract: `drain_trace()` không chặn. Quá trần thì bỏ entry CŨ nhất và tăng
`dropped_frames`; RAM không bao giờ phình dù bus flood.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from ..session.api import Direction, FrameKind, TraceEntry

__all__ = ["TraceBuffer", "DEFAULT_CAPACITY"]

DEFAULT_CAPACITY = 20_000


class TraceBuffer:
    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("capacity phải ≥ 1")
        self._capacity = capacity
        self._lock = threading.Lock()
        self._items: deque[TraceEntry] = deque()
        self._seq = 0
        self._dropped = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped

    def add(
        self,
        direction: Direction,
        can_id: int,
        data: bytes,
        kind: FrameKind,
        decoded: str,
        note: str | None = None,
        t_mono: float | None = None,
    ) -> TraceEntry:
        entry_time = time.perf_counter() if t_mono is None else t_mono
        with self._lock:
            self._seq += 1
            entry = TraceEntry(
                seq=self._seq,
                t_mono=entry_time,
                direction=direction,
                can_id=can_id,
                data=bytes(data),
                kind=kind,
                decoded=decoded,
                note=note,
            )
            if len(self._items) >= self._capacity:
                self._items.popleft()
                self._dropped += 1
            self._items.append(entry)
            return entry

    def drain(self, max_items: int = 5000) -> list[TraceEntry]:
        if max_items <= 0:
            return []
        with self._lock:
            n = min(max_items, len(self._items))
            if n == len(self._items):
                out = list(self._items)
                self._items.clear()
                return out
            return [self._items.popleft() for _ in range(n)]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
