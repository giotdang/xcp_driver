"""A2L file parsing — standalone, stdlib-only.

Public API
----------
load(path)  →  A2LDatabase
"""
from .database import load
from .events import (
    EventOption,
    allowed_events,
    default_event_of,
    event_catalog,
    event_locked,
    format_cycle,
)
from .types import (
    A2LDatabase,
    Characteristic,
    DataType,
    DATATYPE_SIZES,
    DaqEventSpec,
    DaqListCanId,
    EventChannel,
    Measurement,
    RecordLayout,
    StaticDaqList,
    XcpCanInfo,
    XcpDaqInfo,
)

__all__ = [
    "load",
    "A2LDatabase",
    "Characteristic",
    "DataType",
    "DATATYPE_SIZES",
    "DaqEventSpec",
    "EventChannel",
    "EventOption",
    "allowed_events",
    "default_event_of",
    "event_catalog",
    "event_locked",
    "format_cycle",
    "Measurement",
    "RecordLayout",
    "StaticDaqList",
    "XcpCanInfo",
    "XcpDaqInfo",
    "DaqListCanId",
]
