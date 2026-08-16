"""Từ điển mã lỗi CRC_* → lớp ngoại lệ có tên trong `session.api`.

Frontend không bao giờ phải nhìn mã thô. Mọi mã lỗi — kể cả mã lạ ngoài spec —
đều thành một `SlaveError` có `name` và `description` đọc được.
"""

from __future__ import annotations

from ..session.api import (
    AccessDeniedError,
    OutOfRangeError,
    SequenceError,
    SlaveError,
    WriteProtectedError,
)
from .constants import ErrCode

__all__ = ["ERR_TABLE", "error_name", "make_slave_error"]

# mã → (tên trong spec, mô tả cho user, lớp ngoại lệ)
ERR_TABLE: dict[int, tuple[str, str, type[SlaveError]]] = {
    ErrCode.CMD_SYNCH: (
        "ERR_CMD_SYNCH", "Đồng bộ lại lệnh (trả lời của SYNCH)", SlaveError),
    ErrCode.CMD_BUSY: (
        "ERR_CMD_BUSY", "ECU đang bận với lệnh trước", SlaveError),
    ErrCode.DAQ_ACTIVE: (
        "ERR_DAQ_ACTIVE", "DAQ đang chạy, phải dừng trước", SlaveError),
    ErrCode.PGM_ACTIVE: (
        "ERR_PGM_ACTIVE", "Phiên lập trình flash đang chạy", SlaveError),
    ErrCode.CMD_UNKNOWN: (
        "ERR_CMD_UNKNOWN", "ECU không hỗ trợ lệnh này", SlaveError),
    ErrCode.CMD_SYNTAX: (
        "ERR_CMD_SYNTAX", "Cú pháp lệnh sai", SlaveError),
    ErrCode.OUT_OF_RANGE: (
        "ERR_OUT_OF_RANGE", "Tham số nằm ngoài khoảng cho phép", OutOfRangeError),
    ErrCode.WRITE_PROTECTED: (
        "ERR_WRITE_PROTECTED",
        "Vùng nhớ đang chống ghi — thường do XCP đang trỏ reference page",
        WriteProtectedError),
    ErrCode.ACCESS_DENIED: (
        "ERR_ACCESS_DENIED", "Không được phép truy cập", AccessDeniedError),
    ErrCode.ACCESS_LOCKED: (
        "ERR_ACCESS_LOCKED", "Tài nguyên đang khoá, cần seed & key", AccessDeniedError),
    ErrCode.PAGE_NOT_VALID: (
        "ERR_PAGE_NOT_VALID", "Trang không tồn tại trong segment này", SlaveError),
    ErrCode.MODE_NOT_VALID: (
        "ERR_MODE_NOT_VALID", "Chế độ không hợp lệ", SlaveError),
    ErrCode.SEGMENT_NOT_VALID: (
        "ERR_SEGMENT_NOT_VALID", "Segment không tồn tại", SlaveError),
    ErrCode.SEQUENCE: (
        "ERR_SEQUENCE", "Sai thứ tự lệnh", SequenceError),
    ErrCode.DAQ_CONFIG: (
        "ERR_DAQ_CONFIG", "Cấu hình DAQ không hợp lệ", SlaveError),
    ErrCode.MEMORY_OVERFLOW: (
        "ERR_MEMORY_OVERFLOW", "Tràn bộ nhớ trong ECU", SlaveError),
    ErrCode.GENERIC: (
        "ERR_GENERIC", "Lỗi chung, ECU không nói rõ nguyên nhân", SlaveError),
    ErrCode.VERIFY: (
        "ERR_VERIFY", "Kiểm tra lại sau khi ghi không khớp", SlaveError),
    ErrCode.RESOURCE_TEMPORARY_NOT_ACCESSIBLE: (
        "ERR_RESOURCE_TEMPORARY_NOT_ACCESSIBLE",
        "Tài nguyên tạm thời chưa dùng được", SlaveError),
}


def error_name(code: int) -> str:
    entry = ERR_TABLE.get(code)
    return entry[0] if entry else f"ERR_UNKNOWN_0x{code:02X}"


def make_slave_error(code: int) -> SlaveError:
    """Dựng ngoại lệ đúng lớp cho một mã lỗi, kể cả mã ngoài spec."""
    name, desc, cls = ERR_TABLE.get(
        code, (error_name(code), "Mã lỗi không có trong spec XCP 1.0", SlaveError))
    return cls(code, name, desc)
