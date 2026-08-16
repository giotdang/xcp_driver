"""Protocol core XCP — thuần giao thức, không CAN, không GUI."""

from __future__ import annotations

from .constants import Cmd, ErrCode, Pid
from .core import Link, XcpMaster
from .errors import ERR_TABLE, error_name, make_slave_error
from .trace import DEFAULT_CAPACITY, TraceBuffer

__all__ = [
    "Cmd", "ErrCode", "Pid",
    "Link", "XcpMaster",
    "ERR_TABLE", "error_name", "make_slave_error",
    "TraceBuffer", "DEFAULT_CAPACITY",
]
