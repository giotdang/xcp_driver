"""Event channel (raster) của DAQ — lựa chọn hợp lệ cho từng signal.

Logic thuần, chỉ đọc A2L: không Qt, không session, không transport. UI gọi
`event_catalog()` để dựng combobox "Synchronous Event", `allowed_events()` để
biết signal nào được phép đồng bộ theo event nào, `default_event_of()` để chọn
sẵn giá trị ban đầu.

Cơ sở (ASAM MCD-2 MC / ASAM MCD-1 XCP Part 5 — IF_DATA XCP):

* `/begin DAQ ... /begin EVENT ... /end EVENT ... /end DAQ` (cấp MODULE) khai
  CATALOG event của ECU: số kênh, tên, DAQ|STIM|DAQ_STIM, MAX_DAQ_LIST,
  TIME_CYCLE/TIME_UNIT, PRIORITY.
* `DAQ_EVENT` trong IF_DATA XCP của từng MEASUREMENT khai signal ĐÓ được
  đồng bộ theo event nào (FIXED_EVENT_LIST / VARIABLE + AVAILABLE + DEFAULT).
* `SET_DAQ_LIST_MODE` nhận ĐÚNG MỘT event channel cho mỗi DAQ list ⇒ signal
  khác event phải nằm ở DAQ list khác. Đó là lý do tầng UI gom theo event
  trước khi dựng DaqList.

Nguyên tắc: A2L không khai thì tool KHÔNG đoán. Không có chỗ nào ở đây trả về
event 0 làm mặc định — một signal không gán raster là lỗi cấu hình của người
dùng, không phải thứ im lặng đo bừa theo raster của người khác.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import A2LDatabase, DaqEventSpec, Measurement

__all__ = [
    "EventOption",
    "default_event_of",
    "event_catalog",
    "allowed_events",
    "event_locked",
    "format_cycle",
]


@dataclass(frozen=True)
class EventOption:
    """Một lựa chọn trong combobox "Synchronous Event"."""
    number: int
    label: str          # "0 — 10 ms raster (10 ms)" | "Event 3 (not described in A2L)"
    cycle_ns: int       # 0 = không tuần hoàn / không rõ
    max_daq_list: int   # 0 = A2L không khai (không suy ra được giới hạn)
    described: bool     # có /begin EVENT tương ứng trong A2L hay không


def default_event_of(spec: DaqEventSpec | None) -> int | None:
    """Event được chọn sẵn cho một signal, hoặc None nếu KHÔNG suy ra được.

    Theo ASAM: `DEFAULT_EVENT_LIST` là gợi ý của nhà cung cấp ECU; một
    `FIXED_EVENT_LIST` đúng một phần tử thì signal không có lựa chọn nào
    khác. Mọi trường hợp còn lại (fixed nhiều event, variable không có
    default, không khai gì) là quyết định của người dùng — tool KHÔNG đoán.
    """
    if spec is None:
        return None
    if spec.default:
        return spec.default[0]
    if spec.mode == "fixed" and len(spec.fixed) == 1:
        return spec.fixed[0]
    return None


def format_cycle(cycle_ns: int) -> str:
    """ns → chuỗi người đọc được ("10 ms", "1 s", "250 µs"); "" khi không rõ."""
    if cycle_ns <= 0:
        return ""
    for unit_ns, suffix in ((1_000_000_000, "s"), (1_000_000, "ms"),
                            (1_000, "µs"), (1, "ns")):
        if cycle_ns >= unit_ns:
            value = cycle_ns / unit_ns
            text = f"{value:.0f}" if value == int(value) else f"{value:g}"
            return f"{text} {suffix}"
    return ""


def event_catalog(db: A2LDatabase) -> list[EventOption]:
    """Mọi event dùng được để ĐO, sắp theo số kênh.

    Nguồn 1 — `/begin EVENT` trong IF_DATA XCP / DAQ: có tên và chu kỳ, bỏ
    event chỉ-STIM (`direction == "STIM"`).
    Nguồn 2 — `MAX_EVENT_CHANNEL` của `/begin DAQ` khi A2L khai số kênh
    nhưng KHÔNG mô tả từng event (A2L tối giản, hoàn toàn hợp lệ): vẫn phải
    cho người dùng chọn được kênh theo số, nên sinh option `described=False`.

    Rỗng = A2L không nói gì về event. Khi đó UI báo rõ cho người dùng thay vì
    tự bịa ra kênh; `GET_DAQ_EVENT_INFO` (hỏi trực tiếp ECU) là đợt sau.
    """
    options: list[EventOption] = []
    for number in sorted(db.events):
        ch = db.events[number]
        if not ch.supports_daq:
            continue
        name = ch.name or ch.short_name
        cycle = format_cycle(ch.cycle_ns)
        label = f"{number} — {name}" if name else f"Event {number}"
        if cycle:
            label = f"{label} ({cycle})"
        options.append(EventOption(number=number, label=label, cycle_ns=ch.cycle_ns,
                                   max_daq_list=ch.max_daq_list, described=True))

    if not options and db.daq_info is not None and db.daq_info.max_event_channel > 0:
        options = [
            EventOption(number=n, label=f"Event {n} (not described in A2L)",
                        cycle_ns=0, max_daq_list=0, described=False)
            for n in range(db.daq_info.max_event_channel)
        ]
    return options


def allowed_events(
    meas: Measurement, db: A2LDatabase,
    catalog: dict[int, EventOption] | None = None,
) -> list[EventOption]:
    """Các event mà `meas` được phép đồng bộ theo, sắp theo số kênh.

    * `FIXED_EVENT_LIST` → đúng các event đó, không hơn.
    * `VARIABLE` + `AVAILABLE_EVENT_LIST` → các event trong danh sách.
    * `VARIABLE` không có AVAILABLE, hoặc A2L không khai `DAQ_EVENT` → toàn
      bộ catalog (spec không giới hạn gì thì tool cũng không được giới hạn).

    Event mà signal khai nhưng catalog không mô tả vẫn được trả về (A2L khai
    `DAQ_EVENT` mà thiếu `/begin EVENT` là chuyện thường gặp) — khi đó label
    chỉ có số kênh.

    `catalog`: kết quả `event_catalog()` đã tính sẵn (số kênh → option).
    Caller gọi cho hàng trăm measurement nên truyền vào để không dựng lại
    catalog mỗi lần; None = tự dựng.
    """
    if catalog is None:
        catalog = {opt.number: opt for opt in event_catalog(db)}
    spec = meas.daq_event

    if spec is not None and spec.mode == "fixed":
        wanted: tuple[int, ...] = spec.fixed
    elif spec is not None and spec.available:
        wanted = spec.available
    else:
        wanted = tuple(catalog)
        # `event_channel` được gán trực tiếp (A2L tối giản, hoặc caller tự
        # dựng Measurement) mà catalog không biết → vẫn phải là lựa chọn.
        if meas.event_channel is not None and meas.event_channel not in catalog:
            wanted = wanted + (meas.event_channel,)

    out: list[EventOption] = []
    for number in sorted(set(wanted)):
        opt = catalog.get(number)
        out.append(opt if opt is not None else EventOption(
            number=number, label=f"Event {number}", cycle_ns=0,
            max_daq_list=0, described=False))
    return out


def event_locked(meas: Measurement, db: A2LDatabase) -> bool:
    """True khi người dùng không có gì để chọn: A2L đã cố định đúng một event
    (`FIXED_EVENT_LIST` một phần tử). UI khoá combobox lại thay vì giả vờ cho
    chọn rồi ECU từ chối."""
    spec = meas.daq_event
    if spec is None or spec.mode != "fixed":
        return False
    return len(spec.fixed) == 1
