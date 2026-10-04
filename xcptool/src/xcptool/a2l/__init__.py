"""A2L file parsing — standalone, stdlib-only.

Public API
----------
load(path)  →  A2LDatabase
"""
from .database import load
from .types import (
    A2LDatabase,
    Characteristic,
    DataType,
    DATATYPE_SIZES,
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
    "EventChannel",
    "Measurement",
    "RecordLayout",
    "StaticDaqList",
    "XcpCanInfo",
    "XcpDaqInfo",
    "DaqListCanId",
]
