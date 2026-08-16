"""Bài soak 60 giây @ 2000 frame/s cho cửa sổ trace (chạy tay, pytest không thu).

    QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe tests/ui/soak_trace.py --seconds 60

In RAM Python theo từng giây: con số phải đi ngang sau khi bảng chạm trần.
Thoát 0 = đạt.
"""

from __future__ import annotations

import argparse
import sys
import time
import tracemalloc

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from xcptool.session.api import BusConfig
from xcptool.session.fake import FakeSession
from xcptool.ui.app import ensure_utf8_stdio
from xcptool.ui.main_window import MainWindow


def main() -> int:
    ensure_utf8_stdio()
    p = argparse.ArgumentParser()
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--rate", type=float, default=2000.0)
    args = p.parse_args()

    app = QApplication.instance() or QApplication(sys.argv[:1])
    session = FakeSession()
    window = MainWindow(session)
    window.show()
    window.connect_to(BusConfig(backend="virtual", channel="fake0"))

    tracemalloc.start()
    samples: list[tuple[float, int, int]] = []
    started = time.monotonic()

    def sample() -> None:
        current, _ = tracemalloc.get_traced_memory()
        elapsed = time.monotonic() - started
        samples.append((elapsed, current, window.trace_view._received))
        print(f"  {elapsed:5.1f}s  RAM {current / 1e6:7.2f} MB  "
              f"nhận {window.trace_view._received:8d}  "
              f"giữ {window.trace_view.model.total_held:6d}  "
              f"session bỏ {session.dropped_frames}")
        if elapsed >= args.seconds:
            app.quit()

    session.start_flood(rate_hz=args.rate)
    ticker = QTimer()
    ticker.timeout.connect(sample)
    ticker.start(1000)
    app.exec()

    session.stop_flood()
    window.close()

    # So nửa sau với nửa đầu: sau khi chạm trần, RAM phải đi ngang.
    half = len(samples) // 2
    first = sum(s[1] for s in samples[1:half]) / max(half - 1, 1)
    second = sum(s[1] for s in samples[half:]) / max(len(samples) - half, 1)
    growth = (second - first) / max(first, 1)
    received = samples[-1][2]
    expected = args.rate * args.seconds

    print(f"\nRAM nửa đầu {first / 1e6:.2f} MB → nửa sau {second / 1e6:.2f} MB "
          f"({growth:+.1%})")
    print(f"Rút được {received} / {expected:.0f} frame "
          f"({received / expected:.0%}), session bỏ {session.dropped_frames}")

    ok = growth < 0.15 and received > expected * 0.5
    print("SOAK OK" if ok else "SOAK HỎNG")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
