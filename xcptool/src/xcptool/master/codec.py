"""Giải mã frame thành chuỗi đọc được cho cửa sổ debug, và đóng gói CRO.

Quy tắc của contract: `TraceEntry.decoded` LUÔN có giá trị. Không giải mã được
thì trả chuỗi hex — frontend không bao giờ phải tự đọc byte.
"""

from __future__ import annotations

from ..session.api import FrameKind
from .constants import CMD_NAMES, Cmd, Pid
from .errors import error_name

__all__ = ["hexs", "classify", "describe_tx", "describe_rx", "u16", "u32", "pack_u32"]

_CTO_PIDS = frozenset({int(p) for p in Pid})


def hexs(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def u16(data: bytes, off: int, byte_order: str) -> int:
    return int.from_bytes(data[off:off + 2], byte_order)  # type: ignore[arg-type]


def u32(data: bytes, off: int, byte_order: str) -> int:
    return int.from_bytes(data[off:off + 4], byte_order)  # type: ignore[arg-type]


def pack_u32(value: int, byte_order: str) -> bytes:
    return value.to_bytes(4, byte_order)  # type: ignore[arg-type]


def classify(data: bytes) -> FrameKind:
    """Demux CRM và DTO trên cùng một CAN ID — xem DEV_PLAN.md §7.

    Byte 0 thuộc {0xFF,0xFE,0xFD,0xFC} là CTO, còn lại là dữ liệu DAQ.
    """
    if not data:
        return "daq"
    b0 = data[0]
    if b0 not in _CTO_PIDS:
        return "daq"
    return {
        int(Pid.RES): "res",
        int(Pid.ERR): "err",
        int(Pid.EV): "ev",
        int(Pid.SERV): "serv",
    }[b0]  # type: ignore[return-value]


def describe_tx(data: bytes) -> str:
    """Mô tả một CRO đang gửi đi."""
    if not data:
        return "(rỗng)"
    name = CMD_NAMES.get(data[0])
    if name is None:
        return f"CMD? {hexs(data)}"

    cmd = data[0]
    tail = data[1:]
    if cmd == Cmd.CONNECT and tail:
        return f"CONNECT mode={tail[0]}"
    if cmd == Cmd.GET_ID and tail:
        return f"GET_ID type={tail[0]}"
    if cmd in (Cmd.UPLOAD, Cmd.DOWNLOAD) and tail:
        return f"{name} size={tail[0]}"
    if cmd in (Cmd.SET_MTA, Cmd.SHORT_UPLOAD, Cmd.SHORT_DOWNLOAD) and len(data) >= 8:
        # Địa chỉ theo byte order của ECU; hiển thị cả hai cách đọc là thừa,
        # dùng little-endian cho dễ nhìn và kèm hex thô để đối chiếu.
        addr = int.from_bytes(data[4:8], "little")
        if cmd == Cmd.SET_MTA:
            return f"SET_MTA addr=0x{addr:08X} ext={data[3]}"
        return f"{name} size={data[1]} ext={data[3]} addr=0x{addr:08X}"
    if cmd in (Cmd.GET_CAL_PAGE, Cmd.SET_CAL_PAGE) and len(data) >= 3:
        extra = f" page={data[3]}" if cmd == Cmd.SET_CAL_PAGE and len(data) >= 4 else ""
        return f"{name} mode={data[1]} seg={data[2]}{extra}"
    if cmd == Cmd.COPY_CAL_PAGE and len(data) >= 5:
        return (f"COPY_CAL_PAGE {data[1]}:{data[2]} → {data[3]}:{data[4]}")
    return name if not tail else f"{name} {hexs(tail)}"


def describe_rx(data: bytes, pending_cmd: int | None = None) -> str:
    """Mô tả một frame nhận được. `pending_cmd` là lệnh đang chờ trả lời."""
    if not data:
        return "(rỗng)"
    kind = classify(data)

    if kind == "err":
        code = data[1] if len(data) >= 2 else -1
        if code < 0:
            return "ERR (thiếu mã lỗi)"
        return f"ERR {error_name(code)}"

    if kind == "ev":
        code = data[1] if len(data) >= 2 else -1
        return f"EV 0x{code:02X} {hexs(data[2:])}".rstrip() if code >= 0 else "EV (rỗng)"

    if kind == "serv":
        code = data[1] if len(data) >= 2 else -1
        return f"SERV 0x{code:02X} {hexs(data[2:])}".rstrip() if code >= 0 else "SERV"

    if kind == "daq":
        return f"DAQ pid={data[0] & 0x7F}{' OVERRUN' if data[0] & 0x80 else ''} " \
               f"{hexs(data[1:])}".rstrip()

    # kind == 'res'
    if pending_cmd == Cmd.CONNECT and len(data) >= 8:
        return (f"RES CONNECT res=0x{data[1]:02X} mode=0x{data[2]:02X} "
                f"MAX_CTO={data[3]} MAX_DTO={hexs(data[4:6])} "
                f"proto=v{data[6]} transport=v{data[7]}")
    who = CMD_NAMES.get(pending_cmd, "") if pending_cmd is not None else ""
    body = hexs(data[1:])
    return f"RES {who} {body}".replace("  ", " ").strip()
