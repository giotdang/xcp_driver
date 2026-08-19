"""Protocol core XCP — thuần giao thức, không CAN, không GUI."""

from __future__ import annotations

from .constants import Cmd, ErrCode, Pid
from .core import Link, XcpMaster
from .daq import (
    DaqListConfig, DaqSignal, OdtSignalLayout, PidEntry,
    SamplePoint, TimestampAccumulator,
    configure_daq, decode_dto, pack_odts, stop_daq,
)
from .errors import ERR_TABLE, error_name, make_slave_error
from .trace import DEFAULT_CAPACITY, TraceBuffer

__all__ = [
    "Cmd", "ErrCode", "Pid",
    "Link", "XcpMaster",
    "DaqSignal", "pack_odts",
    "DaqListConfig", "OdtSignalLayout", "PidEntry",
    "SamplePoint", "TimestampAccumulator",
    "configure_daq", "decode_dto", "stop_daq",
    "ERR_TABLE", "error_name", "make_slave_error",
    "TraceBuffer", "DEFAULT_CAPACITY",
]
