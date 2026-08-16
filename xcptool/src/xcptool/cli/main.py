"""`xcptool …` — người tiêu thụ thứ hai của cùng contract.

Có hai người tiêu thụ độc lập là cách rẻ nhất để lộ chỗ contract thiết kế tệ:
cái gì CLI làm được mà GUI không, hoặc ngược lại, thì contract đang thiếu.

CLI chạy đồng bộ trên main thread nên KHÔNG có luật worker thread ở đây — luật
đó là của Qt. Nhưng `close()` vẫn phải gọi trên mọi đường thoát.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from ..session.api import (
    BusConfig,
    DeviceInfo,
    PageMode,
    SlaveCaps,
    XcpToolError,
)

__all__ = ["main"]


def _ensure_utf8_stdio() -> None:
    """Console Windows mặc định cp1252 — in tiếng Việt sẽ nổ UnicodeEncodeError.

    Đây là lỗi của môi trường, không phải của người dùng, nên công cụ tự xử lý
    thay vì bắt user đặt PYTHONIOENCODING.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def _create_session(kind: str) -> Any:
    if kind == "fake":
        from ..session.fake import FakeSession

        return FakeSession()
    try:
        from ..session.real import RealSession  # type: ignore[attr-defined]
    except ImportError:
        raise SystemExit(
            "Chưa có xcptool.session.real (backend đang viết). "
            "Dùng --session fake để chạy với bản giả."
        ) from None
    return RealSession()


def _parse_hex_id(text: str) -> int:
    return int(text.strip().lower().removeprefix("0x"), 16)


def _parse_hex_bytes(text: str) -> bytes:
    tokens = text.replace(",", " ").replace("0x", " ").split()
    out = bytearray()
    for tok in tokens:
        if len(tok) % 2:
            raise SystemExit(f"'{tok}' lẻ ký tự — mỗi byte phải đủ 2 chữ số hex")
        out.extend(int(tok[i:i + 2], 16) for i in range(0, len(tok), 2))
    if not out:
        raise SystemExit("Chưa nhập byte nào")
    return bytes(out)


def _build_parser() -> argparse.ArgumentParser:
    from .defaults import DEFAULT_BUS

    p = argparse.ArgumentParser(prog="xcptool", description="XCP master — dòng lệnh")
    p.add_argument("--session", choices=("fake", "real"), default="real")
    p.add_argument("--backend", default=None, help="pcan | vector | slcan | virtual …")
    p.add_argument("--channel", default=None)
    p.add_argument("--bitrate", type=int, default=DEFAULT_BUS.bitrate)
    p.add_argument("--cro", type=_parse_hex_id, default=DEFAULT_BUS.cro_id)
    p.add_argument("--dto", type=_parse_hex_id, default=DEFAULT_BUS.dto_id)
    p.add_argument("--timeout", type=float, default=DEFAULT_BUS.t1_timeout_s)

    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("devices", help="liệt kê kênh CAN dò được")
    sub.add_parser("connect", help="CONNECT rồi in năng lực ECU")

    read = sub.add_parser("read", help="đọc bộ nhớ")
    read.add_argument("address", type=lambda s: int(s, 16))
    read.add_argument("size", type=int)

    write = sub.add_parser("write", help="ghi bộ nhớ")
    write.add_argument("address", type=lambda s: int(s, 16))
    write.add_argument("data", help="chuỗi hex, ví dụ 'DE AD BE EF'")

    pages = sub.add_parser("pages", help="in trang ECU và trang XCP")
    pages.add_argument("--segment", type=int, default=0)

    setpage = sub.add_parser("set-page", help="đổi trang calibration")
    setpage.add_argument("page", type=int)
    setpage.add_argument("--segment", type=int, default=0)
    setpage.add_argument("--mode", choices=("ecu", "xcp"), default="xcp")

    raw = sub.add_parser("raw", help="gửi CTO thô")
    raw.add_argument("payload", help="chuỗi hex, ví dụ 'FF 00'")

    trace = sub.add_parser("trace", help="in frame trong N giây rồi thoát")
    trace.add_argument("--seconds", type=float, default=5.0)

    return p


def _print_devices(devices: list[DeviceInfo]) -> None:
    if not devices:
        print("Không dò được kênh nào.")
        return
    width = max(len(f"{d.backend}:{d.channel}") for d in devices)
    for d in devices:
        mark = "✔" if d.available else "✘"
        print(f"{mark} {d.backend + ':' + d.channel:<{width}}  {d.display_name}")
        if d.hint:
            print(f"    → {d.hint}")


def _print_caps(caps: SlaveCaps) -> None:
    res = ", ".join(n for n, on in (
        ("CAL/PAG", caps.supports_cal_pag), ("DAQ", caps.supports_daq),
        ("STIM", caps.supports_stim), ("PGM", caps.supports_pgm),
    ) if on) or "(không có)"
    print(f"  MAX_CTO            : {caps.max_cto}")
    print(f"  MAX_DTO            : {caps.max_dto}")
    print(f"  Byte order         : {caps.byte_order}-endian")
    print(f"  Address granularity: {caps.address_granularity}")
    print(f"  Protocol / transport: {caps.protocol_version} / {caps.transport_version}")
    print(f"  Resource           : {res}")
    print(f"  Seed & key         : {'CÓ — công cụ chưa hỗ trợ' if caps.needs_seed_and_key else 'không'}")
    print(f"  Block mode         : {'có' if caps.slave_block_mode else 'không'}")
    if caps.id_string:
        print(f"  ID                 : {caps.id_string}")
    if caps.daq is None:
        print("  DAQ info           : ECU không trả lời GET_DAQ_* (bỏ qua êm)")
    else:
        d = caps.daq
        print(f"  DAQ                : max_daq={d.max_daq} events={d.max_event_channel} "
              f"{'dynamic' if d.dynamic_daq else 'static'} "
              f"timestamp={d.timestamp_size}B/{d.timestamp_unit_ns}ns")


def _hexdump(base: int, data: bytes) -> None:
    for off in range(0, len(data), 16):
        chunk = data[off:off + 16]
        hexed = " ".join(f"{b:02X}" for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"{base + off:08X}  {hexed:<47}  |{text}|")


def _dump_trace(session: Any) -> None:
    for e in session.drain_trace():
        arrow = "→" if e.direction == "tx" else "←"
        hexed = " ".join(f"{b:02X}" for b in e.data)
        print(f"  {e.t_mono:12.4f} {arrow} 0x{e.can_id:03X} [{e.kind:5}] "
              f"{hexed:<24} {e.decoded}")


def _pick_device(session: Any, args: argparse.Namespace) -> BusConfig:
    """--backend/--channel do user chỉ định, không thì lấy kênh dùng được đầu tiên."""
    if args.backend and args.channel:
        backend, channel = args.backend, args.channel
    else:
        usable = [d for d in session.list_devices() if d.available]
        if not usable:
            raise SystemExit(
                "Không có kênh CAN nào dùng được. Chạy 'xcptool devices' để xem "
                "cần cài driver gì."
            )
        backend, channel = usable[0].backend, usable[0].channel
        print(f"Dùng kênh dò được đầu tiên: {backend}:{channel}")
    return BusConfig(
        backend=backend, channel=channel, bitrate=args.bitrate,
        cro_id=args.cro, dto_id=args.dto, t1_timeout_s=args.timeout,
    )


def _run(session: Any, args: argparse.Namespace) -> int:
    if args.command == "devices":
        _print_devices(session.list_devices())
        return 0

    cfg = _pick_device(session, args)
    caps = session.connect(cfg)
    print(f"Đã CONNECT tới {cfg.backend}:{cfg.channel}")
    _print_caps(caps)

    if args.command == "connect":
        pass
    elif args.command == "read":
        _hexdump(args.address, session.read(args.address, args.size))
    elif args.command == "write":
        data = _parse_hex_bytes(args.data)
        session.write(args.address, data)
        print(f"Đã ghi {len(data)} byte tại 0x{args.address:08X}")
        _hexdump(args.address, session.read(args.address, len(data)))
    elif args.command == "pages":
        print(f"  Trang ECU đang chạy : {session.get_page(args.segment, PageMode.ECU)}")
        print(f"  Trang XCP đang nhìn : {session.get_page(args.segment, PageMode.XCP)}")
    elif args.command == "set-page":
        mode = PageMode.ECU if args.mode == "ecu" else PageMode.XCP
        session.set_page(args.segment, args.page, mode)
        print(f"Đã đặt trang {args.page} cho {mode.name}")
    elif args.command == "raw":
        payload = _parse_hex_bytes(args.payload)
        res = session.raw_command(payload)
        tag = "ERR" if res and res[0] == 0xFE else "OK"
        print(f">>> {' '.join(f'{b:02X}' for b in payload)}")
        print(f"<<< {' '.join(f'{b:02X}' for b in res)}   [{tag}]")
    elif args.command == "trace":
        import time

        print(f"Nghe bus {args.seconds:.1f} giây…")
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            _dump_trace(session)
            time.sleep(0.05)
        print(f"Frame bị ring buffer bỏ: {session.dropped_frames}")
        return 0

    print("\nTrace của phiên:")
    _dump_trace(session)
    return 0


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    args = _build_parser().parse_args(argv)
    session = _create_session(args.session)
    try:
        return _run(session, args)
    except XcpToolError as exc:
        # Lỗi lường trước được → một dòng đọc được, không traceback.
        print(f"Lỗi: {exc.user_message}", file=sys.stderr)
        hint = getattr(exc, "package_hint", None)
        if hint:
            print(f"Cần cài: {hint}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nĐã dừng.", file=sys.stderr)
        return 130
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
