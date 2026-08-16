"""B1 — từ điển CRC_* → lớp ngoại lệ có tên.

Frontend bắt theo lớp, không bao giờ so mã thô. Nếu ánh xạ này sai thì hộp
thoại "vùng nhớ chống ghi, bấm đây để về working page" sẽ không bao giờ hiện.
"""

from __future__ import annotations

import pytest

from xcptool.master.constants import ErrCode
from xcptool.master.errors import ERR_TABLE, error_name, make_slave_error
from xcptool.session.api import (
    AccessDeniedError,
    OutOfRangeError,
    SequenceError,
    SlaveError,
    WriteProtectedError,
    XcpToolError,
)


@pytest.mark.parametrize(("code", "cls"), [
    (ErrCode.WRITE_PROTECTED, WriteProtectedError),
    (ErrCode.OUT_OF_RANGE, OutOfRangeError),
    (ErrCode.SEQUENCE, SequenceError),
    (ErrCode.ACCESS_DENIED, AccessDeniedError),
    (ErrCode.ACCESS_LOCKED, AccessDeniedError),
    (ErrCode.CMD_UNKNOWN, SlaveError),
])
def test_code_maps_to_named_exception(code: int, cls: type[SlaveError]) -> None:
    exc = make_slave_error(int(code))
    assert isinstance(exc, cls)
    assert exc.code == int(code)
    assert exc.name.startswith("ERR_")
    assert exc.description


def test_unknown_code_still_produces_a_readable_error() -> None:
    """ECU của hãng khác có thể trả mã ngoài spec — không được vỡ vì thế."""
    exc = make_slave_error(0x7F)
    assert isinstance(exc, SlaveError)
    assert exc.code == 0x7F
    assert exc.name == "ERR_UNKNOWN_0x7F"
    assert "0x7F" in str(exc)


def test_every_error_is_an_xcptool_error() -> None:
    for code in list(ERR_TABLE) + [0x7F, 0xFF]:
        assert isinstance(make_slave_error(code), XcpToolError)


def test_error_name_covers_the_whole_spec_table() -> None:
    for code in ErrCode:
        assert error_name(int(code)) == code_name(code)


def code_name(code: ErrCode) -> str:
    return f"ERR_{code.name}"
