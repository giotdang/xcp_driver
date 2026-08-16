"""Hằng số của ASAM XCP Part 2 (Protocol Layer) v1.0.

Chỉ có hằng số của *chuẩn*. Không đặc tính nào của một ECU cụ thể nằm ở đây —
MAX_CTO, CAN ID, byte order đều đến từ `BusConfig` hoặc `SlaveCaps`.
"""

from __future__ import annotations

from enum import IntEnum

__all__ = ["Cmd", "Pid", "ErrCode", "CMD_NAMES", "TIMESTAMP_UNIT_NS"]


class Cmd(IntEnum):
    """Mã lệnh CRO (byte 0 của frame host → ECU)."""

    CONNECT = 0xFF
    DISCONNECT = 0xFE
    GET_STATUS = 0xFD
    SYNCH = 0xFC
    GET_COMM_MODE_INFO = 0xFB
    GET_ID = 0xFA
    SET_REQUEST = 0xF9
    GET_SEED = 0xF8
    UNLOCK = 0xF7
    SET_MTA = 0xF6
    UPLOAD = 0xF5
    SHORT_UPLOAD = 0xF4
    BUILD_CHECKSUM = 0xF3
    TRANSPORT_LAYER_CMD = 0xF2
    USER_CMD = 0xF1
    DOWNLOAD = 0xF0
    DOWNLOAD_NEXT = 0xEF
    DOWNLOAD_MAX = 0xEE
    SHORT_DOWNLOAD = 0xED
    MODIFY_BITS = 0xEC
    SET_CAL_PAGE = 0xEB
    GET_CAL_PAGE = 0xEA
    GET_PAG_PROCESSOR_INFO = 0xE9
    GET_SEGMENT_INFO = 0xE8
    GET_PAGE_INFO = 0xE7
    SET_SEGMENT_MODE = 0xE6
    GET_SEGMENT_MODE = 0xE5
    COPY_CAL_PAGE = 0xE4
    CLEAR_DAQ_LIST = 0xE3
    SET_DAQ_PTR = 0xE2
    WRITE_DAQ = 0xE1
    SET_DAQ_LIST_MODE = 0xE0
    GET_DAQ_LIST_MODE = 0xDF
    START_STOP_DAQ_LIST = 0xDE
    START_STOP_SYNCH = 0xDD
    GET_DAQ_CLOCK = 0xDC
    READ_DAQ = 0xDB
    GET_DAQ_PROCESSOR_INFO = 0xDA
    GET_DAQ_RESOLUTION_INFO = 0xD9
    GET_DAQ_LIST_INFO = 0xD8
    GET_DAQ_EVENT_INFO = 0xD7
    FREE_DAQ = 0xD6
    ALLOC_DAQ = 0xD5
    ALLOC_ODT = 0xD4
    ALLOC_ODT_ENTRY = 0xD3


CMD_NAMES: dict[int, str] = {int(c): c.name for c in Cmd}


class Pid(IntEnum):
    """Byte 0 của frame ECU → host. Ngoài bốn giá trị này là dữ liệu DAQ."""

    RES = 0xFF
    ERR = 0xFE
    EV = 0xFD
    SERV = 0xFC


class ErrCode(IntEnum):
    """Mã lỗi đi kèm packet 0xFE."""

    CMD_SYNCH = 0x00
    CMD_BUSY = 0x10
    DAQ_ACTIVE = 0x11
    PGM_ACTIVE = 0x12
    CMD_UNKNOWN = 0x20
    CMD_SYNTAX = 0x21
    OUT_OF_RANGE = 0x22
    WRITE_PROTECTED = 0x23
    ACCESS_DENIED = 0x24
    ACCESS_LOCKED = 0x25
    PAGE_NOT_VALID = 0x26
    MODE_NOT_VALID = 0x27
    SEGMENT_NOT_VALID = 0x28
    SEQUENCE = 0x29
    DAQ_CONFIG = 0x2A
    MEMORY_OVERFLOW = 0x30
    GENERIC = 0x31
    VERIFY = 0x32
    RESOURCE_TEMPORARY_NOT_ACCESSIBLE = 0x33


# Mã đơn vị timestamp của GET_DAQ_RESOLUTION_INFO → nano giây.
# Các đơn vị dưới 1 ns (pico giây) làm tròn xuống 0 — không ECU CAN nào dùng.
TIMESTAMP_UNIT_NS: dict[int, int] = {
    0x0: 1,             # 1 ns
    0x1: 10,            # 10 ns
    0x2: 100,           # 100 ns
    0x3: 1_000,         # 1 us
    0x4: 10_000,        # 10 us
    0x5: 100_000,       # 100 us
    0x6: 1_000_000,     # 1 ms
    0x7: 10_000_000,    # 10 ms
    0x8: 100_000_000,   # 100 ms
    0x9: 1_000_000_000,  # 1 s
    0xA: 0,             # 1 ps
    0xB: 0,             # 10 ps
    0xC: 0,             # 100 ps
}
