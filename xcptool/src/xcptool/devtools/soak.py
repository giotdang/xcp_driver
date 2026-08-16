"""Chạy dài để bắt loại lỗi mà test đơn vị không bao giờ thấy: rò bộ nhớ,
ring buffer phình dần, thread chết âm thầm sau vài phút.

    python -m xcptool.devtools.soak --minutes 5 --rate 2000

Kịch bản mô phỏng đúng hình dạng thật của app: ECU giả bắn DAQ liên tục, UI rút
trace theo nhịp 40 ms, người dùng thỉnh thoảng đọc/ghi calibration.

Thoát 0 khi mọi thứ ổn. Thoát 1 nếu có dòng log ERROR, RAM còn tăng ở đoạn đuôi,
hoặc lệnh nào đó hỏng — nghĩa là có việc phải sửa, đừng bỏ qua.
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys
import time
import tracemalloc

from ..session.api import BusConfig, XcpToolError
from ..session.real import RealSession
from .fakeslave import FakeSlave, SlaveConfig

UI_TICK_S = 0.04
"""Nhịp rút trace của frontend — 30..50 ms theo DEV_PLAN, lấy 40 ms."""

COMMAND_EVERY_S = 0.5
SAMPLE_EVERY_S = 5.0

GROWTH_LIMIT = 1.15
"""Trung vị 1/3 cuối chia trung vị 1/3 giữa. Vượt ngưỡng này là rò.

So đầu với cuối thì SAI: vài phút đầu RAM luôn tăng vì code path mới còn đang
chạy lần đầu (import chậm, cache ấm lên, arena cấp phát). Đường cong đó phẳng
dần rồi dừng. Rò thật thì không phẳng — nên phải đo ở đoạn ĐUÔI, và bỏ hẳn 1/3
đầu đi.
"""


class ErrorCounter(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(f"{record.name}: {record.getMessage()}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="xcptool.devtools.soak", description=__doc__)
    p.add_argument("--minutes", type=float, default=5.0)
    p.add_argument("--rate", type=float, default=2000.0,
                   help="số frame DAQ mỗi giây mà ECU giả bắn ra")
    p.add_argument("--capacity", type=int, default=20_000,
                   help="trần ring buffer trace")
    p.add_argument("--channel", default="xcptool-soak")
    p.add_argument("--quiet", action="store_true")
    return p.parse_args(argv)


def _force_utf8_output() -> None:
    """Console Windows mặc định cp1252 — in tiếng Việt sẽ nổ UnicodeEncodeError."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _force_utf8_output()
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    counter = ErrorCounter()
    logging.getLogger().addHandler(counter)

    slave_cfg = SlaveConfig(channel=args.channel, daq_flood_hz=args.rate)
    bus = BusConfig(backend="virtual", channel=args.channel,
                    cro_id=slave_cfg.cro_id, dto_id=slave_cfg.dto_id,
                    t1_timeout_s=1.0)

    session = RealSession(trace_capacity=args.capacity)
    tracemalloc.start()
    samples: list[float] = []
    frames = commands = failures = 0
    deadline = time.perf_counter() + args.minutes * 60.0

    try:
        with FakeSlave(slave_cfg):
            caps = session.connect(bus)
            if not args.quiet:
                print(f"ECU giả: MAX_CTO={caps.max_cto} MAX_DTO={caps.max_dto} "
                      f"DAQ={'có' if caps.daq else 'không'}")
                print(f"Chạy {args.minutes:g} phút, {args.rate:g} frame/s, "
                      f"trần trace {args.capacity}")

            next_cmd = time.perf_counter() + COMMAND_EVERY_S
            next_sample = time.perf_counter() + SAMPLE_EVERY_S
            started = time.perf_counter()

            while time.perf_counter() < deadline:
                time.sleep(UI_TICK_S)
                frames += len(session.drain_trace())

                now = time.perf_counter()
                if now >= next_cmd:
                    next_cmd = now + COMMAND_EVERY_S
                    commands += 1
                    payload = bytes([commands & 0xFF]) * 8
                    try:
                        session.write(slave_cfg.mem_base, payload)
                        if session.read(slave_cfg.mem_base, 8) != payload:
                            failures += 1
                            logging.error("đọc lại không khớp giá trị vừa ghi")
                    except XcpToolError:
                        failures += 1
                        logging.exception("lệnh calibration hỏng")

                if now >= next_sample:
                    next_sample = now + SAMPLE_EVERY_S
                    current, _peak = tracemalloc.get_traced_memory()
                    samples.append(current / 1024)
                    if not args.quiet:
                        print(f"  t={now - started:6.0f}s  RAM={current / 1024:8.1f} KiB"
                              f"  frame={frames:8d}  bỏ={session.dropped_frames:8d}"
                              f"  lệnh={commands}")
    finally:
        session.close()
        tracemalloc.stop()
        logging.getLogger().removeHandler(counter)

    return report(args, samples, frames, commands, failures, session, counter)


def tail_growth(samples: list[float]) -> tuple[float, str]:
    """(tỉ lệ tăng ở đuôi, mô tả để in). Bỏ 1/3 đầu vì đó là lúc ấm máy."""
    if len(samples) < 6:
        return 1.0, "chưa đủ mẫu để kết luận"
    third = len(samples) // 3
    middle = samples[third:2 * third]
    tail = samples[2 * third:]
    m, t = statistics.median(middle), statistics.median(tail)
    ratio = t / m if m else 1.0
    return ratio, f"giữa {m:.0f} KiB → đuôi {t:.0f} KiB, {ratio:.2f}×"


def report(
    args: argparse.Namespace, samples: list[float], frames: int, commands: int,
    failures: int, session: RealSession, counter: ErrorCounter,
) -> int:
    problems: list[str] = []

    if failures:
        problems.append(f"{failures} lệnh calibration hỏng")
    if counter.records:
        problems.append(f"{len(counter.records)} dòng log ERROR")
    if frames == 0 and args.rate > 0:
        problems.append("không nhận được frame nào — ECU giả hoặc bus có vấn đề")

    growth, verdict = tail_growth(samples)
    if growth > GROWTH_LIMIT:
        problems.append(f"RAM vẫn tăng ở đoạn đuôi ({verdict}) — nghi rò")

    print()
    print(f"frame đã rút   : {frames}")
    print(f"frame bị bỏ    : {session.dropped_frames}")
    print(f"lệnh cal       : {commands} ({failures} hỏng)")
    if samples:
        print(f"RAM            : {min(samples):.0f} … {max(samples):.0f} KiB, "
              f"trung vị {statistics.median(samples):.0f} KiB")
        print(f"RAM đoạn đuôi  : {verdict}")
    print(f"log ERROR      : {len(counter.records)}")
    for line in counter.records[:10]:
        print(f"  - {line}")

    if problems:
        print("\nSOAK ĐỎ:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nSOAK XANH")
    return 0


if __name__ == "__main__":
    sys.exit(main())
