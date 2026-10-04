"""Bảng tra DTO định tuyến theo CAN ID: mỗi DAQ list có thể phát trên ID riêng, và
ECU không chuẩn có thể đánh PID lại từ đầu cho từng list — nên khoá phải có CAN ID."""

from __future__ import annotations

from xcptool.devtools.fakeslave import FakeSlave, SlaveConfig
from xcptool.master.daq import (
    DaqListConfig,
    DaqSignal,
    OdtSignalLayout,
    PidEntry,
    TimestampAccumulator,
    configure_daq,
    decode_dto,
    route_key,
)
from xcptool.session.api import BusConfig
from xcptool.session.real import RealSession


def _sig(name: str, size: int = 2, datatype: str = "UINT16") -> DaqSignal:
    return DaqSignal(name=name, address=0x8000_0000, ext=0, size=size, datatype=datatype)


def _entry(daq: int, name: str) -> PidEntry:
    return PidEntry(daq_list=daq, odt_index=0, has_timestamp=False,
                    signals=[OdtSignalLayout(_sig(name), 1)])


def test_cung_pid_tren_hai_can_id_ra_hai_list_khac_nhau() -> None:
    table = {route_key(0x6A2, 1): _entry(0, "list0"),
             route_key(0x6A3, 1): _entry(1, "list1")}
    frame = bytes([1, 0x34, 0x12])

    s0 = decode_dto(frame, table, TimestampAccumulator(), can_id=0x6A2)
    s1 = decode_dto(frame, table, TimestampAccumulator(), can_id=0x6A3)

    assert [p.name for p in s0] == ["list0"]
    assert [p.name for p in s1] == ["list1"]
    assert s0[0].value_raw == b"\x34\x12"


def test_can_id_la_khong_co_trong_bang_ra_rong() -> None:
    table = {route_key(0x6A2, 1): _entry(0, "list0")}
    assert decode_dto(bytes([1, 0, 0]), table, TimestampAccumulator(), can_id=0x6AF) == []


def test_can_id_none_dung_khoa_thuan() -> None:
    table = {1: _entry(0, "plain")}
    out = decode_dto(bytes([1, 0x01, 0x00]), table, TimestampAccumulator())
    assert [p.name for p in out] == ["plain"]


def test_route_key_la_cap_can_id_va_khoa() -> None:
    assert route_key(0x6A2, 5) == (0x6A2, 5)
    assert route_key(0x6A2, (3, 1)) == (0x6A2, (3, 1))


def test_route_of_dang_ky_theo_so_vat_ly(channel: str) -> None:
    """ECU static: list 0 predefined nên config đầu rơi vào list vật lý 1 — ID phải
    tra theo số vật lý (1), không theo vị trí trong `configs` (0)."""
    cfg = SlaveConfig(channel=channel, daq_dynamic=False, min_daq=2, max_daq=2,
                      static_predefined_lists=frozenset({0}))
    bus = BusConfig(backend="virtual", channel=channel, cro_id=cfg.cro_id,
                    dto_id=cfg.dto_id, t1_timeout_s=0.5)
    session = RealSession()
    with FakeSlave(cfg):
        session.connect(bus)
        master = session._master  # type: ignore[attr-defined]
        route_of = {0: 0x6A2, 1: 0x6A3}.__getitem__

        table = configure_daq(
            master, [DaqListConfig(signals=[_sig("x")], event=0, timestamp=False)],
            route_of=route_of)

        (key, entry), = table.items()
        assert entry.daq_list == 1
        assert key[0] == 0x6A3
    session.close()
