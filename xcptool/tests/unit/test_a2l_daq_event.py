"""DAQ_EVENT (ASAM MCD-2 MC) — event nào một signal được đồng bộ theo, và
catalog event của ECU đọc từ IF_DATA XCP / DAQ.

Trọng tâm: tool KHÔNG được tự đoán raster. A2L khai cố định thì theo A2L; A2L
cho nhiều lựa chọn thì để người dùng chọn (`event_channel is None`); A2L không
khai gì thì nói là không khai, chứ không trả về event 0.
"""
from __future__ import annotations

import pytest

from xcptool.a2l import (
    allowed_events,
    default_event_of,
    event_catalog,
    event_locked,
    format_cycle,
)
from xcptool.a2l import load
from xcptool.a2l.parser import parse
from xcptool.a2l.types import A2LDatabase, EventChannel, Measurement


def _text(module_body: str) -> str:
    return f"""
    /begin PROJECT p ""
      /begin MODULE m ""
    {module_body}
      /end MODULE
    /end PROJECT
    """


def _wrap(module_body: str) -> A2LDatabase:
    """Chỉ parse — đủ cho MEASUREMENT phẳng (không cần resolve INSTANCE)."""
    return parse(_text(module_body))


def _load(tmp_path, module_body: str) -> A2LDatabase:
    """Nạp qua `load()` — đường đi thật của app, có cả bước resolve INSTANCE."""
    path = tmp_path / "t.a2l"
    path.write_text(_text(module_body), encoding="utf-8")
    return load(path)


_DAQ_BLOCK = """
        /begin IF_DATA XCP
          /begin DAQ
            DYNAMIC 0x04 0x03 0x00
            /begin EVENT
              /begin EVENT "10 ms raster" "10ms" 0x00 DAQ 0x01 10 6 0 /end EVENT
              /begin EVENT "100 ms raster" "100ms" 0x01 DAQ 0x01 100 6 0 /end EVENT
              /begin EVENT "stim only" "stim" 0x02 STIM 0x01 1 6 0 /end EVENT
            /end EVENT
          /end DAQ
        /end IF_DATA
"""


def _meas(name: str, if_data: str = "") -> str:
    return f"""
        /begin MEASUREMENT {name}
          "{name}" UWORD NO_COMPU_METHOD 0 0 0 100
          ECU_ADDRESS 0x90000000
          {if_data}
        /end MEASUREMENT
"""


# ── FIXED_EVENT_LIST ────────────────────────────────────────────────────────

def test_fixed_single_event_is_preselected_and_locked() -> None:
    db = _wrap(_DAQ_BLOCK + _meas("sig", """
          /begin IF_DATA XCP
            /begin DAQ_EVENT
              /begin FIXED_EVENT_LIST EVENT 0x01 /end FIXED_EVENT_LIST
            /end DAQ_EVENT
          /end IF_DATA
    """))
    meas = db.measurements["sig"]
    assert meas.daq_event is not None
    assert meas.daq_event.mode == "fixed"
    assert meas.daq_event.fixed == (1,)
    assert meas.event_channel == 1                      # không có gì để chọn
    assert [o.number for o in allowed_events(meas, db)] == [1]
    assert event_locked(meas, db) is True


def test_fixed_multiple_events_needs_user_choice() -> None:
    """FIXED_EVENT_LIST nhiều EVENT: signal đo được ở cả hai, A2L không nói
    nên dùng cái nào → tool KHÔNG chọn hộ (trước đây lấy luôn cái đầu)."""
    db = _wrap(_DAQ_BLOCK + _meas("sig", """
          /begin IF_DATA XCP
            /begin DAQ_EVENT
              /begin FIXED_EVENT_LIST
                EVENT 0x00
                EVENT 0x01
              /end FIXED_EVENT_LIST
            /end DAQ_EVENT
          /end IF_DATA
    """))
    meas = db.measurements["sig"]
    assert meas.daq_event.fixed == (0, 1)
    assert meas.event_channel is None
    assert [o.number for o in allowed_events(meas, db)] == [0, 1]
    assert event_locked(meas, db) is False


def test_fixed_event_list_inline_without_nested_block() -> None:
    """Dạng không lồng block (`FIXED_EVENT_LIST` chỉ là keyword) cũng phải
    đọc được — A2L ngoài thực tế viết cả hai kiểu."""
    db = _wrap(_DAQ_BLOCK + _meas("sig", """
          /begin IF_DATA XCP
            /begin DAQ_EVENT FIXED_EVENT_LIST EVENT 0x01 /end DAQ_EVENT
          /end IF_DATA
    """))
    assert db.measurements["sig"].daq_event.fixed == (1,)
    assert db.measurements["sig"].event_channel == 1


# ── VARIABLE + AVAILABLE/DEFAULT ────────────────────────────────────────────

def test_variable_event_list_uses_default_and_offers_available() -> None:
    db = _wrap(_DAQ_BLOCK + _meas("sig", """
          /begin IF_DATA XCP
            /begin DAQ_EVENT VARIABLE
              /begin AVAILABLE_EVENT_LIST
                EVENT 0x00
                EVENT 0x01
              /end AVAILABLE_EVENT_LIST
              /begin DEFAULT_EVENT_LIST EVENT 0x01 /end DEFAULT_EVENT_LIST
            /end DAQ_EVENT
          /end IF_DATA
    """))
    meas = db.measurements["sig"]
    assert meas.daq_event.mode == "variable"
    assert meas.daq_event.available == (0, 1)
    assert meas.daq_event.default == (1,)
    assert meas.event_channel == 1                      # DEFAULT_EVENT_LIST
    assert [o.number for o in allowed_events(meas, db)] == [0, 1]
    assert event_locked(meas, db) is False


def test_variable_without_available_list_offers_whole_catalog() -> None:
    """VARIABLE không giới hạn → mọi event ĐO ĐƯỢC của ECU (bỏ event STIM)."""
    db = _wrap(_DAQ_BLOCK + _meas("sig", """
          /begin IF_DATA XCP
            /begin DAQ_EVENT VARIABLE /end DAQ_EVENT
          /end IF_DATA
    """))
    meas = db.measurements["sig"]
    assert meas.event_channel is None
    assert [o.number for o in allowed_events(meas, db)] == [0, 1]


# ── không khai DAQ_EVENT ────────────────────────────────────────────────────

def test_measurement_without_daq_event_offers_catalog_but_no_default() -> None:
    db = _wrap(_DAQ_BLOCK + _meas("sig"))
    meas = db.measurements["sig"]
    assert meas.daq_event is None
    assert meas.event_channel is None                   # KHÔNG mặc định về 0
    assert [o.number for o in allowed_events(meas, db)] == [0, 1]


# ── TYPEDEF_MEASUREMENT / INSTANCE ──────────────────────────────────────────

_TYPEDEF_BODY = """
        /begin TYPEDEF_MEASUREMENT tm_t
          "typedef" UWORD NO_COMPU_METHOD 0 0 0 100
          /begin IF_DATA XCP
            /begin DAQ_EVENT
              /begin FIXED_EVENT_LIST EVENT 0x00 /end FIXED_EVENT_LIST
            /end DAQ_EVENT
          /end IF_DATA
        /end TYPEDEF_MEASUREMENT
        /begin TYPEDEF_STRUCTURE st_t "struct" 4
          /begin STRUCTURE_COMPONENT a tm_t 0 /end STRUCTURE_COMPONENT
          /begin STRUCTURE_COMPONENT b tm_t 2 /end STRUCTURE_COMPONENT
        /end TYPEDEF_STRUCTURE
"""


def test_typedef_measurement_daq_event_reaches_instance_leaves(tmp_path) -> None:
    """Lá resolve từ INSTANCE trước đây LUÔN mất event (Measurement dựng trong
    database.py không mang field này) → bị UI đẩy hết về event 0."""
    db = _load(tmp_path, _DAQ_BLOCK + _TYPEDEF_BODY + """
        /begin INSTANCE inst "instance" st_t 0x90001000 /end INSTANCE
    """)
    assert db.measurements["inst.a"].event_channel == 0
    assert db.measurements["inst.b"].event_channel == 0


def test_instance_daq_event_overrides_typedef(tmp_path) -> None:
    db = _load(tmp_path, _DAQ_BLOCK + _TYPEDEF_BODY + """
        /begin INSTANCE inst "instance" st_t 0x90001000
          /begin IF_DATA XCP
            /begin DAQ_EVENT
              /begin FIXED_EVENT_LIST EVENT 0x01 /end FIXED_EVENT_LIST
            /end DAQ_EVENT
          /end IF_DATA
        /end INSTANCE
    """)
    assert db.measurements["inst.a"].event_channel == 1
    assert db.measurements["inst.b"].event_channel == 1


# ── catalog event ───────────────────────────────────────────────────────────

def test_catalog_skips_stim_only_event_and_labels_cycle() -> None:
    db = _wrap(_DAQ_BLOCK)
    catalog = event_catalog(db)
    assert [o.number for o in catalog] == [0, 1]        # event 2 chỉ STIM
    assert catalog[0].label == "0 — 10 ms raster (10 ms)"
    assert catalog[0].cycle_ns == 10_000_000
    assert catalog[0].max_daq_list == 1
    assert all(o.described for o in catalog)


def test_catalog_falls_back_to_max_event_channel_when_no_event_blocks() -> None:
    """A2L khai số kênh nhưng không mô tả từng event — vẫn phải chọn được
    kênh theo số, nhãn nói rõ là A2L không mô tả."""
    db = _wrap("""
        /begin IF_DATA XCP
          /begin DAQ
            DYNAMIC 0x02 0x03 0x00
          /end DAQ
        /end IF_DATA
    """)
    catalog = event_catalog(db)
    assert [o.number for o in catalog] == [0, 1, 2]
    assert not any(o.described for o in catalog)


def test_catalog_empty_when_a2l_says_nothing_about_events() -> None:
    db = _wrap(_meas("sig"))
    assert event_catalog(db) == []
    assert allowed_events(db.measurements["sig"], db) == []


def test_allowed_events_keeps_event_not_described_in_catalog() -> None:
    """A2L gán event cho signal mà thiếu /begin EVENT tương ứng: event đó vẫn
    là lựa chọn hợp lệ, chỉ là nhãn không có tên/chu kỳ."""
    db = A2LDatabase()
    meas = Measurement(name="m", description="", datatype="UWORD", address=0,
                       lower_limit=0.0, upper_limit=1.0, event_channel=7)
    db.measurements["m"] = meas
    assert [o.number for o in allowed_events(meas, db)] == [7]
    assert allowed_events(meas, db)[0].label == "Event 7"


# ── tiện ích ────────────────────────────────────────────────────────────────

def test_default_event_of_does_not_guess() -> None:
    assert default_event_of(None) is None


@pytest.mark.parametrize("cycle_ns,text", [
    (0, ""), (250_000, "250 µs"), (10_000_000, "10 ms"), (1_000_000_000, "1 s"),
])
def test_format_cycle(cycle_ns: int, text: str) -> None:
    assert format_cycle(cycle_ns) == text


def test_event_channel_direction_and_cycle() -> None:
    ch = EventChannel(name="e", short_name="e", number=0, max_daq_list=1,
                      time_cycle=5, time_unit=6, priority=0, direction="DAQ_STIM")
    assert ch.supports_daq is True
    assert ch.cycle_ns == 5_000_000
    assert EventChannel(name="e", short_name="e", number=0, max_daq_list=1,
                        time_cycle=1, time_unit=6, priority=0,
                        direction="STIM").supports_daq is False
