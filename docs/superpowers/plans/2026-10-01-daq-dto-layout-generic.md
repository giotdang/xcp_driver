# xcptool: DTO layout generic theo caps ECU — Kế hoạch triển khai

> **Trạng thái: HOÀN THÀNH** — cả 7 task đã thực thi và merge, mỗi task một commit:
> `a9dc91a` (1) · `a71df84` (2) · `cc58564` (3) · `dd5cb13` (4) · `4d4ec02` (5) · `9c23319` (6) · `6b04ef6` (7).
> Theo sau còn `e1d0834` sửa timestamp theo từng DAQ list. Tra lại: `git log --oneline a9dc91a~1..6b04ef6`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đường DAQ của xcptool suy ra layout gói DTO (kiểu identification field 0–3, timestamp size/unit/ticks/rollover, cách báo overrun) hoàn toàn từ caps mà ECU báo, không hardcode theo driver trong repo.

**Architecture:** Thêm `DtoFormat` (dataclass bất biến, `master/daq.py`) dựng một lần từ `SlaveCaps` bằng `DtoFormat.from_slave_caps`. `pack_odts`, `configure_daq`, `configure_daq_predefined`, `decode_dto`, `TimestampAccumulator` và `RealSession` chỉ nhận `DtoFormat`, không tự đoán. `DaqCaps` (contract `session/api.py`) thêm 3 trường có mặc định. Tham số mới của mọi hàm hiện có đều có mặc định tái tạo đúng hành vi cũ, nên test cũ không phải sửa.

**Tech Stack:** Python 3.12, pytest (+ pytest-timeout 60 s mỗi test), python-can `virtual` bus cho test tích hợp. Lệnh chạy test: `.venv/Scripts/python.exe -m pytest ...` từ thư mục `xcptool/`.

**Spec:** `docs/superpowers/specs/2026-09-30-daq-dto-layout-generic-design.md` (người thực thi đọc cả spec lẫn kế hoạch này; spec giải thích *vì sao*, kế hoạch nói *làm gì*).

## Global Constraints

- `master/` không được import `can`, `PySide6`, `xcptool.ui`, `xcptool.cli`, `xcptool.transport`; `session/api.py` chỉ dùng stdlib; `session/fake.py` không import `xcptool.master`. **Không sửa `tests/test_boundaries.py`** (file do lead sở hữu).
- Toàn bộ test hiện có phải xanh **không sửa**. Baseline trước khi bắt đầu: `tests/unit tests/integration tests/test_boundaries.py` = **352 passed** (~92 s).
- `DtoFormat()` mặc định phải tái tạo hành vi cũ: `id_type=0, byte_order="little", ts_size=4, unit_ns=10, ticks=1, overload="pid_msb", ts_always=False`.
- `DaqCaps` thêm đúng 3 trường, mặc định: `id_field_type=0`, `overload="pid_msb"`, `timestamp_fixed=False`.
- Đường decode (`decode_dto`, chạy trên RX thread) **không bao giờ raise**: frame rỗng/ngắn/khoá lạ → `[]`; frame ngắn cho timestamp → `timestamp_ns = 0`.
- Không hardcode đặc tính ECU trong logic (`ARCHITECTURE.md` mục nguyên tắc: MAX_DTO, byte order, độ phân giải timestamp đều đến từ caps).
- Công thức timestamp theo spec ASAM: `ns = ticks_tích_lũy × unit_ns ÷ ticks` (bộ đếm tăng `TIMESTAMP_TICKS` mỗi `unit`).
- Rollover chỉ khi tụt quá nửa chu kỳ: `last − raw > 2^(width_bits−1)`.
- Comment/docstring viết tiếng Việt, theo phong cách file xung quanh. Không đụng `driver/`.
- Commit: chỉ `git add` đúng các file của task (working tree có nhiều file không liên quan, **không bao giờ** `git add .` / `-A`); trước `git commit` chạy `git diff --cached --name-only` và đối chiếu danh sách file của task. Mỗi commit kết thúc bằng dòng `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

Các đầu vào/điều kiện mà spec ngụ ý nhưng dễ bị bỏ sót nhất (mỗi dòng có test ghim ở task sở hữu code):

1. **ECU không trả lời `GET_DAQ_PROCESSOR_INFO`/`GET_DAQ_RESOLUTION_INFO` (`caps.daq is None`)** → phải chạy đúng như trước (header 1 B, timestamp 4 B/10 ns), không crash. Test: Task 6 `test_caps_daq_none_keeps_legacy_layout`.
2. **ECU báo `TIMESTAMP_TICKS = 0` hoặc mã unit ngoài 0–9** → `timestamp_ns = 0`, không `ZeroDivisionError`, vẫn bỏ qua đúng số byte timestamp. (`tests/ui/test_connect_flow.py` đã dùng `timestamp_ticks=0` thật.) Test: Task 2 `test_accumulator_invalid_unit_or_ticks_gives_zero`, Task 3 `test_decode_invalid_unit_still_skips_timestamp_bytes`.
3. **Số DAQ list ≥ 256 với kiểu 2/3 và ECU big-endian** → byte order của WORD phải theo slave. Test: Task 3 `test_decode_relative_word_daq_number_byte_order`.
4. **Hai frame timestamp đến lệch thứ tự nhẹ (bước lùi nhỏ)** không được bị coi là rollover (nhảy cả chu kỳ). Test: Task 2 `test_accumulator_small_backstep_is_not_a_rollover`.
5. **Frame DTO cũ/lạ sau `FREE_DAQ`, frame ngắn hơn header, khoá không có trong bảng** → trả `[]`, không raise. Test: Task 3 `test_decode_never_raises_on_short_or_unknown_frames`.

---

## File Structure

| File | Trách nhiệm | Thay đổi |
|---|---|---|
| `src/xcptool/session/api.py` | Contract thuần stdlib | `DaqCaps` thêm 3 trường mặc định |
| `src/xcptool/master/core.py` | Probe caps | `_probe_daq_caps` đọc `DAQ_KEY_BYTE`, overload, fixed, sửa `timestamp_supported` |
| `src/xcptool/master/daq.py` | DAQ engine | Thêm `DtoFormat`, `make_key`, `effective_timestamp`; sửa `TimestampAccumulator`, `decode_dto`, `pack_odts`, `configure_daq`, `_write_and_start`, `configure_daq_predefined` |
| `src/xcptool/master/__init__.py` | Re-export | Export tên mới |
| `src/xcptool/session/real.py` | Session thật | Dựng `DtoFormat` + accumulator lúc `start_daq` |
| `src/xcptool/devtools/fakeslave.py` | ECU giả trên virtual bus | Cấu hình + phát DTO theo 4 kiểu header, timestamp tổng quát |
| `tests/unit/test_daq_caps_probe.py` (mới) | Probe caps bằng frame Part 5 | |
| `tests/unit/test_dto_format.py` (mới) | `DtoFormat`, `make_key`, `effective_timestamp`, `TimestampAccumulator` | |
| `tests/unit/test_daq_dto_decode.py` (mới) | `decode_dto` nhiều kiểu header | |
| `tests/unit/test_daq_packing_fmt.py` (mới) | `pack_odts` theo `DtoFormat` | |
| `tests/unit/test_fakeslave_dto.py` (mới) | Fakeslave: caps + header + tick | |
| `tests/integration/test_daq_dto_formats.py` (mới) | End-to-end qua `RealSession.start_daq` | |
| `ARCHITECTURE.md`, docstring trong `daq.py` | Tài liệu | Task 7 |

Thứ tự task: 1 (caps) → 2 (DtoFormat + accumulator) → 3 (decode) → 4 (pack) → 5 (fakeslave) → 6 (configure + RealSession + tích hợp) → 7 (tài liệu + hồi quy toàn bộ). Mỗi task kết thúc bằng một commit và bộ test liên quan xanh.

---

### Task 1: `DaqCaps` mới và probe đọc `DAQ_KEY_BYTE`

**Files:**
- Modify: `src/xcptool/session/api.py` (class `DaqCaps`, ~dòng 181–198)
- Modify: `src/xcptool/master/core.py` (`_probe_daq_caps`, dòng 412–436)
- Create: `tests/unit/test_daq_caps_probe.py`

**Interfaces:**
- Consumes: `XcpMaster._optional(payload) -> bytes | None`, `XcpMaster._caps` (có `.byte_order`).
- Produces: `DaqCaps.id_field_type: int`, `DaqCaps.overload: Literal["none","pid_msb","event"]`, `DaqCaps.timestamp_fixed: bool`; `DaqCaps.timestamp_supported` nay = bit4 của `DAQ_PROPERTIES` **và** size ∈ {1,2,4}; `DaqCaps.timestamp_size = 0` khi không hỗ trợ.

- [x] **Step 1: Viết test đỏ**

Tạo `tests/unit/test_daq_caps_probe.py`:

```python
"""Probe DaqCaps từ frame GET_DAQ_PROCESSOR_INFO / GET_DAQ_RESOLUTION_INFO.

Dùng các frame ví dụ trong ASAM XCP v1.0 Part 5 (mục 1.3.1) làm dữ liệu thật.
Không cần bus: thay `_optional` bằng hàm trả bytes cho sẵn.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from xcptool.master.constants import Cmd
from xcptool.master.core import XcpMaster
from xcptool.session.api import DaqCaps


def _probe(proc: str, res: str, byte_order: str | None = None) -> DaqCaps | None:
    master = XcpMaster.__new__(XcpMaster)
    master._caps = SimpleNamespace(byte_order=byte_order) if byte_order else None

    def _optional(payload: bytes) -> bytes:
        raw = proc if payload[0] == Cmd.GET_DAQ_PROCESSOR_INFO else res
        return bytes.fromhex(raw)

    master._optional = _optional  # type: ignore[method-assign]
    return master._probe_daq_caps()


def test_new_daq_caps_fields_have_legacy_defaults() -> None:
    """Code cũ dựng DaqCaps không biết 3 trường mới phải vẫn chạy."""
    caps = DaqCaps(
        max_daq=1, max_event_channel=1, min_daq=0, dynamic_daq=True,
        timestamp_supported=True, timestamp_size=4, timestamp_unit_ns=10,
        timestamp_ticks=1, pid_off_supported=False,
        granularity_odt_entry_daq=1, max_odt_entry_size_daq=7,
    )
    assert caps.id_field_type == 0
    assert caps.overload == "pid_msb"
    assert caps.timestamp_fixed is False


def test_part5_dynamic_example() -> None:
    """Part 5: FF 11 00 00 01 00 00 40 + FF 02 FD xx xx 62 0A 00."""
    caps = _probe("FF11000001000040", "FF02FD0000620A00")
    assert caps is not None
    assert caps.dynamic_daq is True
    assert caps.max_daq == 0
    assert caps.max_event_channel == 1
    assert caps.min_daq == 0
    assert caps.id_field_type == 1                 # DAQ_KEY_BYTE 0x40
    assert caps.overload == "none"                 # DAQ_PROPERTIES 0x11: bit 7-6 = 00
    assert caps.timestamp_supported is True
    assert caps.timestamp_size == 2                # TIMESTAMP_MODE 0x62: size = 2
    assert caps.timestamp_unit_ns == 1_000_000     # unit code 6 = 1 ms
    assert caps.timestamp_ticks == 10
    assert caps.timestamp_fixed is False
    assert caps.granularity_odt_entry_daq == 2
    assert caps.max_odt_entry_size_daq == 253


def test_part5_static_example() -> None:
    """Part 5: FF 10 01 00 01 00 00 40 (static, 1 DAQ list)."""
    caps = _probe("FF10010001000040", "FF02FD0000620A00")
    assert caps is not None
    assert caps.dynamic_daq is False
    assert caps.max_daq == 1
    assert caps.id_field_type == 1


def test_driver_like_response() -> None:
    """Dạng driver trong repo: DAQ_PROPERTIES 0x51, key byte 0, TIMESTAMP_MODE 0x14."""
    caps = _probe("FF51000000000000", "FF01070100140100")
    assert caps is not None
    assert caps.id_field_type == 0
    assert caps.overload == "pid_msb"              # bit 6
    assert caps.timestamp_supported is True
    assert caps.timestamp_size == 4
    assert caps.timestamp_unit_ns == 10            # unit code 1 = 10 ns
    assert caps.timestamp_ticks == 1
    assert caps.pid_off_supported is False


@pytest.mark.parametrize("key_byte,expected", [(0x00, 0), (0x40, 1), (0x80, 2), (0xC0, 3)])
def test_id_field_type_comes_from_key_byte_bits_7_6(key_byte: int, expected: int) -> None:
    proc = bytes([0xFF, 0x01, 0, 0, 0, 0, 0, key_byte]).hex()
    caps = _probe(proc, "FF01070100140100")
    assert caps is not None
    assert caps.id_field_type == expected


@pytest.mark.parametrize("code,expected", [(0, "none"), (1, "pid_msb"), (2, "event"), (3, "none")])
def test_overload_comes_from_daq_properties_bits_7_6(code: int, expected: str) -> None:
    """Mã 3 không hợp lệ theo spec → coi là không báo overrun."""
    proc = bytes([0xFF, 0x01 | (code << 6), 0, 0, 0, 0, 0, 0]).hex()
    caps = _probe(proc, "FF01070100140100")
    assert caps is not None
    assert caps.overload == expected


def test_timestamp_fixed_flag() -> None:
    caps = _probe("FF11000000000000", "FF010701001C0100")
    assert caps is not None
    assert caps.timestamp_fixed is True            # TIMESTAMP_MODE 0x1C: bit 3
    assert caps.timestamp_size == 4


def test_timestamp_not_supported_when_bit4_clear_even_if_mode_looks_valid() -> None:
    """Spec: bit TIMESTAMP_SUPPORTED = 0 → TIMESTAMP_MODE/TICKS không hợp lệ."""
    caps = _probe("FF01000000000000", "FF01070100140100")   # DAQ_PROPERTIES bit 4 = 0
    assert caps is not None
    assert caps.timestamp_supported is False
    assert caps.timestamp_size == 0


def test_timestamp_size_3_is_invalid() -> None:
    """Size 3 'Not allowed' theo spec → không hỗ trợ timestamp."""
    caps = _probe("FF11000000000000", "FF01070100130100")   # TIMESTAMP_MODE 0x13
    assert caps is not None
    assert caps.timestamp_supported is False
    assert caps.timestamp_size == 0


def test_multi_byte_fields_follow_slave_byte_order() -> None:
    """Big-endian: MAX_DAQ = 00 05, MAX_EVENT = 00 02, TICKS = 00 0A."""
    caps = _probe("FF11000500020040", "FF0107010062000A", byte_order="big")
    assert caps is not None
    assert caps.max_daq == 5
    assert caps.max_event_channel == 2
    assert caps.timestamp_ticks == 10
```

- [x] **Step 2: Chạy test, xác nhận đỏ**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_daq_caps_probe.py -v`
Expected: FAIL — `AttributeError: 'DaqCaps' object has no attribute 'id_field_type'` (và `test_new_daq_caps_fields_have_legacy_defaults` cũng đỏ).

- [x] **Step 3: Thêm 3 trường vào `DaqCaps`**

Trong `src/xcptool/session/api.py`, thay docstring và thêm trường cuối class `DaqCaps`. Docstring cũ:

```python
    """Năng lực DAQ, đọc từ GET_DAQ_PROCESSOR_INFO + GET_DAQ_RESOLUTION_INFO.

    Ngoài phạm vi M1/M2 — khai báo sẵn để contract không phải đổi ở M4.
    `None` ở `SlaveCaps.daq` nghĩa là ECU không trả lời các lệnh này.
    """
```

thay bằng:

```python
    """Năng lực DAQ, đọc từ GET_DAQ_PROCESSOR_INFO + GET_DAQ_RESOLUTION_INFO.

    `None` ở `SlaveCaps.daq` nghĩa là ECU không trả lời các lệnh này — khi đó
    master dùng layout DTO mặc định (header 1 byte, timestamp 4 byte/10 ns).

    `id_field_type`, `overload`, `timestamp_fixed` quyết định layout DTO; xem
    `master.daq.DtoFormat`.
    """
```

Và ngay sau dòng `max_odt_entry_size_daq: int` (hết các trường không có mặc định) thêm:

```python
    id_field_type: int = 0          # DAQ_KEY_BYTE bit 7-6: 0 absolute ODT | 1 rel ODT + DAQ (BYTE)
                                    # | 2 rel ODT + DAQ (WORD) | 3 rel ODT + DAQ (WORD, aligned)
    overload: Literal["none", "pid_msb", "event"] = "pid_msb"   # DAQ_PROPERTIES bit 7-6
    timestamp_fixed: bool = False   # TIMESTAMP_MODE bit 3: DTO luôn có timestamp
```

(`Literal` đã được import ở đầu file vì `SlaveCaps.byte_order` đang dùng.)

- [x] **Step 4: Sửa `_probe_daq_caps`**

Trong `src/xcptool/master/core.py` thay toàn bộ hàm `_probe_daq_caps` (dòng 412–436) bằng:

```python
    def _probe_daq_caps(self) -> DaqCaps | None:
        proc = self._optional(bytes([Cmd.GET_DAQ_PROCESSOR_INFO]))
        res = self._optional(bytes([Cmd.GET_DAQ_RESOLUTION_INFO]))
        if proc is None or res is None or len(proc) < 8 or len(res) < 8:
            return None

        order = self._caps.byte_order if self._caps else "little"
        properties = proc[1]
        key_byte = proc[7]
        ts_mode = res[5]
        raw_ts_size = ts_mode & 0x07
        ts_unit_code = (ts_mode >> 4) & 0x0F

        # Spec: bit TIMESTAMP_SUPPORTED (bit 4 của DAQ_PROPERTIES) = 0 thì
        # TIMESTAMP_MODE/TICKS không hợp lệ; size 3 và > 4 cũng không hợp lệ.
        ts_supported = bool(properties & 0x10) and raw_ts_size in (1, 2, 4)
        overload = {0b00: "none", 0b01: "pid_msb", 0b10: "event"}.get(
            (properties >> 6) & 0x03, "none")   # 0b11 không hợp lệ → không báo

        return DaqCaps(
            max_daq=int.from_bytes(proc[2:4], order),        # type: ignore[arg-type]
            max_event_channel=int.from_bytes(proc[4:6], order),  # type: ignore[arg-type]
            min_daq=proc[6],
            dynamic_daq=bool(properties & 0x01),
            timestamp_supported=ts_supported,
            timestamp_size=raw_ts_size if ts_supported else 0,
            timestamp_unit_ns=TIMESTAMP_UNIT_NS.get(ts_unit_code, 0),
            timestamp_ticks=int.from_bytes(res[6:8], order),  # type: ignore[arg-type]
            pid_off_supported=bool(properties & 0x20),
            granularity_odt_entry_daq=res[1],
            max_odt_entry_size_daq=res[2],
            id_field_type=(key_byte >> 6) & 0x03,
            overload=overload,  # type: ignore[arg-type]
            timestamp_fixed=bool(ts_mode & 0x08),
        )
```

- [x] **Step 5: Giữ fakeslave khớp với cách tính `timestamp_supported` mới (sửa tối thiểu, hoàn thiện ở Task 5)**

Probe giờ đòi bit 4 (`TIMESTAMP_SUPPORTED`) của `DAQ_PROPERTIES`, nhưng fakeslave hiện không bao giờ đặt bit này nên `tests/unit/test_capabilities.py` (`assert daq.timestamp_supported is True`) sẽ đỏ. Trong `src/xcptool/devtools/fakeslave.py`, hàm `_cmd_daq_processor_info`, đổi:

```python
        properties = ((0x01 if self.cfg.daq_dynamic else 0)
                      | (0x20 if self.cfg.pid_off_supported else 0))
```

thành:

```python
        properties = ((0x01 if self.cfg.daq_dynamic else 0)
                      | 0x10                      # TIMESTAMP_SUPPORTED (Task 5 làm cấu hình được)
                      | (0x20 if self.cfg.pid_off_supported else 0))
```

- [x] **Step 6: Chạy test, xác nhận xanh**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_daq_caps_probe.py tests/unit/test_capabilities.py tests/unit/test_protocol_core.py tests/integration/test_daq.py tests/integration/test_session_daq.py -v`
Expected: tất cả PASS.

- [x] **Step 7: Commit**

```bash
git add src/xcptool/session/api.py src/xcptool/master/core.py src/xcptool/devtools/fakeslave.py tests/unit/test_daq_caps_probe.py
git diff --cached --name-only
git commit -m "feat(xcptool): probe DAQ_KEY_BYTE, overload, TIMESTAMP_FIXED; timestamp_supported theo bit 4" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

`git diff --cached --name-only` phải liệt kê đúng 4 file trên.

---

### Task 2: `DtoFormat`, `make_key`, `effective_timestamp`, `TimestampAccumulator` tổng quát

**Files:**
- Modify: `src/xcptool/master/daq.py` (imports, `__all__`, thêm khối mới sau `DaqSignal`, thay `TimestampAccumulator`)
- Create: `tests/unit/test_dto_format.py`

**Interfaces:**
- Consumes: `DaqCaps` (Task 1), `SlaveCaps` (`.daq`, `.byte_order`).
- Produces (dùng ở Task 3–6):
  - `DtoFormat(id_type=0, byte_order="little", ts_size=4, unit_ns=10, ticks=1, overload="pid_msb", ts_always=False)`; `.header_len -> int`; `.data_start(has_timestamp: bool) -> int`; `DtoFormat.from_caps(daq_caps: DaqCaps | None, byte_order="little") -> DtoFormat`; `DtoFormat.from_slave_caps(caps: SlaveCaps | None) -> DtoFormat`.
  - `DtoKey = int | tuple[int, int]`; `make_key(fmt, daq: int, odt: int, first_pid: int) -> DtoKey`.
  - `effective_timestamp(requested: bool, fmt: DtoFormat) -> bool`.
  - `TimestampAccumulator(byte_order="little", width_bits=32, unit_ns=10, ticks=1)`; `.from_format(fmt)`; `.to_ns(raw) -> int`.

- [x] **Step 1: Viết test đỏ**

Tạo `tests/unit/test_dto_format.py`:

```python
"""DtoFormat + make_key + effective_timestamp + TimestampAccumulator tổng quát."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from xcptool.master.daq import (
    DtoFormat,
    TimestampAccumulator,
    effective_timestamp,
    make_key,
)
from xcptool.session.api import DaqCaps


def _caps(**over: object) -> DaqCaps:
    base: dict[str, object] = dict(
        max_daq=0, max_event_channel=1, min_daq=0, dynamic_daq=True,
        timestamp_supported=True, timestamp_size=2, timestamp_unit_ns=1_000_000,
        timestamp_ticks=10, pid_off_supported=False,
        granularity_odt_entry_daq=1, max_odt_entry_size_daq=7,
        id_field_type=1, overload="none", timestamp_fixed=False,
    )
    base.update(over)
    return DaqCaps(**base)  # type: ignore[arg-type]


# ── DtoFormat ─────────────────────────────────────────────────────────────────

def test_default_format_reproduces_legacy_behaviour() -> None:
    fmt = DtoFormat()
    assert (fmt.id_type, fmt.byte_order, fmt.ts_size, fmt.unit_ns, fmt.ticks,
            fmt.overload, fmt.ts_always) == (0, "little", 4, 10, 1, "pid_msb", False)
    assert fmt.header_len == 1
    assert fmt.data_start(has_timestamp=True) == 5
    assert fmt.data_start(has_timestamp=False) == 1


@pytest.mark.parametrize("id_type,header", [(0, 1), (1, 2), (2, 3), (3, 4)])
def test_header_len_by_identification_field_type(id_type: int, header: int) -> None:
    assert DtoFormat(id_type=id_type).header_len == header


def test_data_start_adds_timestamp_only_when_present() -> None:
    fmt = DtoFormat(id_type=3, ts_size=2)
    assert fmt.data_start(True) == 6
    assert fmt.data_start(False) == 4


@pytest.mark.parametrize("bad", [-1, 4, 7])
def test_invalid_id_type_is_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="id_type"):
        DtoFormat(id_type=bad)


@pytest.mark.parametrize("bad", [3, 5, 8])
def test_invalid_ts_size_is_rejected(bad: int) -> None:
    with pytest.raises(ValueError, match="ts_size"):
        DtoFormat(ts_size=bad)


def test_from_caps_none_gives_default_with_given_byte_order() -> None:
    assert DtoFormat.from_caps(None) == DtoFormat()
    assert DtoFormat.from_caps(None, "big") == DtoFormat(byte_order="big")


def test_from_caps_maps_every_field() -> None:
    fmt = DtoFormat.from_caps(_caps(timestamp_fixed=True), "big")
    assert fmt == DtoFormat(id_type=1, byte_order="big", ts_size=2, unit_ns=1_000_000,
                            ticks=10, overload="none", ts_always=True)


def test_from_slave_caps_uses_daq_caps_and_byte_order() -> None:
    slave = SimpleNamespace(daq=_caps(), byte_order="big")
    assert DtoFormat.from_slave_caps(slave).byte_order == "big"   # type: ignore[arg-type]
    assert DtoFormat.from_slave_caps(slave).id_type == 1           # type: ignore[arg-type]


def test_from_slave_caps_none_or_without_daq_gives_default() -> None:
    assert DtoFormat.from_slave_caps(None) == DtoFormat()
    no_daq = SimpleNamespace(daq=None, byte_order="big")
    assert DtoFormat.from_slave_caps(no_daq) == DtoFormat(byte_order="big")  # type: ignore[arg-type]


# ── make_key ──────────────────────────────────────────────────────────────────

def test_make_key_absolute_uses_first_pid_plus_odt() -> None:
    assert make_key(DtoFormat(id_type=0), daq=7, odt=2, first_pid=10) == 12


@pytest.mark.parametrize("id_type", [1, 2, 3])
def test_make_key_relative_uses_daq_and_odt_and_ignores_first_pid(id_type: int) -> None:
    assert make_key(DtoFormat(id_type=id_type), daq=7, odt=2, first_pid=99) == (7, 2)


# ── effective_timestamp ───────────────────────────────────────────────────────

def test_effective_timestamp_follows_request_normally() -> None:
    fmt = DtoFormat()
    assert effective_timestamp(True, fmt) is True
    assert effective_timestamp(False, fmt) is False


def test_effective_timestamp_always_on_when_fixed() -> None:
    assert effective_timestamp(False, DtoFormat(ts_always=True)) is True


def test_effective_timestamp_off_when_ecu_has_no_timestamp() -> None:
    assert effective_timestamp(True, DtoFormat(ts_size=0)) is False


# ── TimestampAccumulator ──────────────────────────────────────────────────────

def test_accumulator_defaults_are_legacy_32bit_10ns() -> None:
    acc = TimestampAccumulator()
    assert (acc.width_bits, acc.unit_ns, acc.ticks) == (32, 10, 1)
    assert acc.to_ns(100) == 1_000


def test_accumulator_unit_and_ticks_per_spec_part5_example() -> None:
    """Part 5: unit 1 ms, TIMESTAMP_TICKS 10 → counter tăng 10 mỗi ms."""
    acc = TimestampAccumulator(unit_ns=1_000_000, ticks=10)
    assert acc.to_ns(10) == 1_000_000
    assert acc.to_ns(25) == 2_500_000


def test_accumulator_16bit_rollover() -> None:
    acc = TimestampAccumulator(width_bits=16)
    acc.to_ns(0xFF00)
    assert acc.to_ns(0x0100) == (0x1_0000 + 0x100) * 10


def test_accumulator_8bit_rollover() -> None:
    acc = TimestampAccumulator(width_bits=8)
    acc.to_ns(0xF0)
    assert acc.to_ns(0x05) == (0x100 + 0x05) * 10


def test_accumulator_small_backstep_is_not_a_rollover() -> None:
    """Review Focus #4: frame đến lệch thứ tự nhẹ không được cộng cả chu kỳ."""
    acc = TimestampAccumulator()
    assert acc.to_ns(1000) == 10_000
    assert acc.to_ns(990) == 9_900          # lùi 10 tick: không đổi epoch
    assert acc.to_ns(1010) == 10_100


def test_accumulator_backstep_just_over_half_range_is_a_rollover() -> None:
    acc = TimestampAccumulator(width_bits=8)
    acc.to_ns(200)
    # 200 → 50: tụt 150 > 128 (nửa chu kỳ) → rollover
    assert acc.to_ns(50) == (0x100 + 50) * 10
    acc2 = TimestampAccumulator(width_bits=8)
    acc2.to_ns(200)
    # 200 → 100: tụt 100 ≤ 128 → lệch thứ tự, không rollover
    assert acc2.to_ns(100) == 100 * 10


@pytest.mark.parametrize("unit_ns,ticks", [(0, 1), (10, 0), (0, 0)])
def test_accumulator_invalid_unit_or_ticks_gives_zero(unit_ns: int, ticks: int) -> None:
    """Review Focus #2: không ZeroDivisionError, trả 0 ns."""
    acc = TimestampAccumulator(unit_ns=unit_ns, ticks=ticks)
    assert acc.to_ns(12345) == 0


def test_accumulator_from_format() -> None:
    fmt = DtoFormat(ts_size=2, byte_order="big", unit_ns=100, ticks=2)
    acc = TimestampAccumulator.from_format(fmt)
    assert (acc.byte_order, acc.width_bits, acc.unit_ns, acc.ticks) == ("big", 16, 100, 2)


def test_accumulator_from_format_without_timestamp_keeps_32bit_width() -> None:
    acc = TimestampAccumulator.from_format(DtoFormat(ts_size=0))
    assert acc.width_bits == 32
```

- [x] **Step 2: Chạy test, xác nhận đỏ**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_dto_format.py -v`
Expected: FAIL — `ImportError: cannot import name 'DtoFormat' from 'xcptool.master.daq'`.

- [x] **Step 3: Sửa imports và `__all__` trong `daq.py`**

Trong `src/xcptool/master/daq.py`:

Đổi dòng `from typing import TYPE_CHECKING` thành:

```python
from typing import TYPE_CHECKING, Literal
```

Đổi khối import `..session.api`:

```python
from ..session.api import (
    DaqCaps,
    NotConnectedError,
    SlaveError,
    StaticDaqCapacityError,
    UnsupportedByEcuError,
)
```

thành:

```python
from ..session.api import (
    DaqCaps,
    NotConnectedError,
    SlaveCaps,
    SlaveError,
    StaticDaqCapacityError,
    UnsupportedByEcuError,
)
```

Đổi `__all__` (thêm 4 tên mới):

```python
__all__ = [
    "DaqSignal", "pack_odts",
    "DtoFormat", "DtoKey", "make_key", "effective_timestamp",
    "DaqListConfig", "OdtSignalLayout", "PidEntry",
    "configure_daq", "stop_daq",
    "PredefinedDaqList", "configure_daq_predefined",
    "SamplePoint", "TimestampAccumulator", "decode_dto",
]
```

- [x] **Step 4: Thêm `DtoFormat`, `make_key`, `effective_timestamp`**

Chèn ngay **sau** class `DaqSignal` (trước `@dataclass class DaqListConfig`):

```python
_HEADER_LEN = (1, 2, 3, 4)   # theo id_type 0..3


@dataclass(frozen=True)
class DtoFormat:
    """Layout gói DTO mà ECU dùng — suy ra một lần từ caps, không hardcode.

    id_type:   kiểu identification field (DAQ_KEY_BYTE bit 7-6):
               0 = absolute ODT number            → header `PID`
               1 = relative ODT + DAQ list (BYTE) → header `ODT, DAQ`
               2 = relative ODT + DAQ list (WORD) → header `ODT, DAQ_lo, DAQ_hi`
               3 = như 2 kèm byte FILL            → header `ODT, FILL, DAQ_lo, DAQ_hi`
    byte_order: thứ tự byte của slave (WORD số DAQ list, timestamp).
    ts_size:   0 (không có timestamp) | 1 | 2 | 4 byte.
    unit_ns, ticks: bộ đếm tăng `ticks` mỗi `unit_ns` ns (0 = không hợp lệ).
    overload:  cách ECU báo overrun: "pid_msb" (MSB của PID) | "event" | "none".
    ts_always: TIMESTAMP_FIXED — mọi DTO đều mang timestamp, master không tắt được.

    `DtoFormat()` mặc định tái tạo đúng hành vi cũ của xcptool (header 1 byte,
    timestamp 4 byte/10 ns, overrun ở MSB của PID) — dùng khi ECU không trả lời
    GET_DAQ_PROCESSOR_INFO/GET_DAQ_RESOLUTION_INFO.
    """
    id_type: int = 0
    byte_order: Literal["little", "big"] = "little"
    ts_size: int = 4
    unit_ns: int = 10
    ticks: int = 1
    overload: Literal["none", "pid_msb", "event"] = "pid_msb"
    ts_always: bool = False

    def __post_init__(self) -> None:
        if self.id_type not in (0, 1, 2, 3):
            raise ValueError(f"id_type phải là 0..3, nhận {self.id_type}")
        if self.ts_size not in (0, 1, 2, 4):
            raise ValueError(f"ts_size phải là 0, 1, 2 hoặc 4, nhận {self.ts_size}")

    @property
    def header_len(self) -> int:
        return _HEADER_LEN[self.id_type]

    def data_start(self, has_timestamp: bool) -> int:
        """Offset (từ đầu frame) của byte dữ liệu đầu tiên."""
        return self.header_len + (self.ts_size if has_timestamp else 0)

    @classmethod
    def from_caps(cls, daq_caps: DaqCaps | None,
                  byte_order: Literal["little", "big"] = "little") -> DtoFormat:
        if daq_caps is None:
            return cls(byte_order=byte_order)
        return cls(
            id_type=daq_caps.id_field_type,
            byte_order=byte_order,
            ts_size=daq_caps.timestamp_size,
            unit_ns=daq_caps.timestamp_unit_ns,
            ticks=daq_caps.timestamp_ticks,
            overload=daq_caps.overload,
            ts_always=daq_caps.timestamp_fixed,
        )

    @classmethod
    def from_slave_caps(cls, caps: SlaveCaps | None) -> DtoFormat:
        """Hàm DUY NHẤT dựng DtoFormat từ caps — `configure_daq` và
        `RealSession` đều dùng nên hai bên không thể lệch nhau."""
        if caps is None:
            return cls()
        return cls.from_caps(caps.daq, caps.byte_order)


DtoKey = int | tuple[int, int]
"""Khoá bảng tra DTO: `PID` (kiểu 0) hoặc `(số DAQ list, số ODT tương đối)` (kiểu 1–3)."""


def make_key(fmt: DtoFormat, daq: int, odt: int, first_pid: int) -> DtoKey:
    """Khoá bảng tra cho ODT `odt` của DAQ list vật lý `daq`.

    Kiểu 0: PID tuyệt đối = `first_pid + odt`. Kiểu 1–3: DTO mang sẵn số DAQ
    list và ODT tương đối, `first_pid` không dùng.
    """
    if fmt.id_type == 0:
        return first_pid + odt
    return (daq, odt)


def effective_timestamp(requested: bool, fmt: DtoFormat) -> bool:
    """Timestamp thực sự có trong DTO của một DAQ list.

    - TIMESTAMP_FIXED: luôn có (master không tắt được), bất kể `requested`.
    - ECU không hỗ trợ timestamp (`ts_size == 0`): không có — hạ xuống tắt
      im lặng, kết quả giống `timestamp=False` (`timestamp_ns = 0`).
    - Còn lại: theo `requested`.
    """
    if fmt.ts_always:
        return True
    if fmt.ts_size == 0:
        return False
    return requested
```

- [x] **Step 5: Thay `TimestampAccumulator`**

Thay toàn bộ class `TimestampAccumulator` hiện có (từ `class TimestampAccumulator:` đến hết method `to_ns`) bằng:

```python
class TimestampAccumulator:
    """Bộ tích lũy timestamp ECU → nanosecond tuyệt đối, bù rollover.

    byte_order: thứ tự byte trong frame DTO — lấy từ SlaveCaps.byte_order.
    width_bits: độ rộng bộ đếm của ECU (8 × ts_size).
    unit_ns, ticks: bộ đếm tăng `ticks` mỗi `unit_ns` ns (theo spec ASAM), nên
        ns = tick_tích_lũy × unit_ns ÷ ticks. Giá trị 0 nghĩa là không hợp lệ →
        `to_ns` trả 0.

    Rollover chỉ được ghi nhận khi giá trị tụt quá NỬA chu kỳ
    (`last − raw > 2^(width_bits−1)`). Bước lùi nhỏ hơn là hai frame đến lệch
    thứ tự (hay gặp khi nhiều DAQ list dùng chung bộ tích lũy): epoch không đổi.

    Giới hạn: nếu hai lần nhận timestamp cách nhau quá một chu kỳ đầy đủ thì
    không phân biệt được; timestamp 1 byte quay vòng rất nhanh nên ít hữu dụng.
    """

    def __init__(self, byte_order: str = "little", width_bits: int = 32,
                 unit_ns: int = 10, ticks: int = 1) -> None:
        self.byte_order = byte_order
        self.width_bits = width_bits
        self.unit_ns = unit_ns
        self.ticks = ticks
        self._last: int | None = None
        self._epoch: int = 0   # số lần tràn × 2^width_bits

    @classmethod
    def from_format(cls, fmt: DtoFormat) -> TimestampAccumulator:
        return cls(
            byte_order=fmt.byte_order,
            width_bits=8 * fmt.ts_size if fmt.ts_size else 32,
            unit_ns=fmt.unit_ns,
            ticks=fmt.ticks,
        )

    def update(self, raw: int) -> int:
        """Nhận giá trị thô của bộ đếm, trả về tick tích lũy (không tràn)."""
        wrap = 1 << self.width_bits
        if (self._last is not None and raw < self._last
                and (self._last - raw) > wrap // 2):
            self._epoch += wrap
        self._last = raw
        return self._epoch + raw

    def to_ns(self, raw: int) -> int:
        """Trả về timestamp tuyệt đối tính bằng nanosecond."""
        total = self.update(raw)
        if self.unit_ns == 0 or self.ticks == 0:
            return 0
        return total * self.unit_ns // self.ticks
```

- [x] **Step 6: Chạy test, xác nhận xanh**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_dto_format.py tests/unit/test_daq_decoder.py tests/unit/test_daq_packing.py -v`
Expected: tất cả PASS (test decoder/packing cũ phải xanh không sửa — `test_ts_accum_*` dùng mặc định 32 bit/10 ns).

- [x] **Step 7: Commit**

```bash
git add src/xcptool/master/daq.py tests/unit/test_dto_format.py
git diff --cached --name-only
git commit -m "feat(xcptool): DtoFormat, make_key, effective_timestamp; TimestampAccumulator theo width/unit/ticks" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `decode_dto` theo `DtoFormat`

**Files:**
- Modify: `src/xcptool/master/daq.py` (`decode_dto`)
- Create: `tests/unit/test_daq_dto_decode.py`

**Interfaces:**
- Consumes: `DtoFormat`, `DtoKey`, `TimestampAccumulator` (Task 2), `PidEntry`, `OdtSignalLayout`, `DaqSignal`, `SamplePoint` (hiện có).
- Produces: `decode_dto(frame: bytes, pid_table: Mapping[DtoKey, PidEntry], ts_accum: TimestampAccumulator, fmt: DtoFormat | None = None) -> list[SamplePoint]`.

- [x] **Step 1: Viết test đỏ**

Tạo `tests/unit/test_daq_dto_decode.py`:

```python
"""decode_dto với 4 kiểu identification field, overrun theo cách ECU báo,
timestamp nhiều kích thước. Không cần bus — thuần bytes.

Frame dùng ở đây dựng tay theo ASAM XCP v1.0 Part 2 mục 1.1.2:
    kiểu 0: PID | [TS] | data
    kiểu 1: ODT DAQ | [TS] | data
    kiểu 2: ODT DAQ_lo DAQ_hi | [TS] | data
    kiểu 3: ODT FILL DAQ_lo DAQ_hi | [TS] | data
"""

from __future__ import annotations

import pytest

from xcptool.master.daq import (
    DaqSignal,
    DtoFormat,
    OdtSignalLayout,
    PidEntry,
    TimestampAccumulator,
    decode_dto,
)


def _sig(name: str = "x", size: int = 1) -> DaqSignal:
    return DaqSignal(name=name, address=0x8000_0000, ext=0, size=size, datatype="UINT8")


def _entry(daq: int, odt: int, has_ts: bool, *placed: tuple[DaqSignal, int]) -> PidEntry:
    return PidEntry(daq_list=daq, odt_index=odt, has_timestamp=has_ts,
                    signals=[OdtSignalLayout(s, off) for s, off in placed])


def _acc(fmt: DtoFormat) -> TimestampAccumulator:
    return TimestampAccumulator.from_format(fmt)


# ── kiểu 0 (mặc định, hành vi cũ) ────────────────────────────────────────────

def test_absolute_type_default_format() -> None:
    table = {5: _entry(0, 5, False, (_sig("a", 2), 1))}
    frame = bytes([0x05, 0xAA, 0xBB, 0, 0, 0, 0, 0])
    samples = decode_dto(frame, table, TimestampAccumulator())
    assert [(s.name, s.value_raw) for s in samples] == [("a", b"\xAA\xBB")]


# ── kiểu 1 ────────────────────────────────────────────────────────────────────

def test_relative_byte_type_looks_up_daq_and_odt() -> None:
    fmt = DtoFormat(id_type=1, overload="none")
    table = {(3, 2): _entry(3, 2, False, (_sig("a", 2), 2))}
    frame = bytes([0x02, 0x03, 0x11, 0x22, 0, 0, 0, 0])     # ODT 2 của DAQ list 3
    samples = decode_dto(frame, table, _acc(fmt), fmt)
    assert [(s.name, s.value_raw) for s in samples] == [("a", b"\x11\x22")]


def test_relative_byte_type_other_daq_list_is_not_matched() -> None:
    fmt = DtoFormat(id_type=1, overload="none")
    table = {(3, 2): _entry(3, 2, False, (_sig("a"), 2))}
    frame = bytes([0x02, 0x04, 0x11, 0, 0, 0, 0, 0])        # DAQ list 4, không phải 3
    assert decode_dto(frame, table, _acc(fmt), fmt) == []


def test_relative_byte_type_timestamp_only_on_odt0_part5_units() -> None:
    """Part 5: timestamp 2 byte, unit 1 ms, ticks 10 → raw 10 = 1 ms."""
    fmt = DtoFormat(id_type=1, ts_size=2, unit_ns=1_000_000, ticks=10, overload="none")
    table = {
        (3, 0): _entry(3, 0, True, (_sig("a"), 4)),          # header 2 + TS 2 = offset 4
        (3, 1): _entry(3, 1, False, (_sig("b"), 2)),         # header 2 = offset 2
    }
    acc = _acc(fmt)
    odt0 = bytes([0x00, 0x03, 0x0A, 0x00, 0x55, 0, 0, 0])
    odt1 = bytes([0x01, 0x03, 0x66, 0, 0, 0, 0, 0])
    s0 = decode_dto(odt0, table, acc, fmt)
    s1 = decode_dto(odt1, table, acc, fmt)
    assert (s0[0].value_raw, s0[0].timestamp_ns) == (b"\x55", 1_000_000)
    assert (s1[0].value_raw, s1[0].timestamp_ns) == (b"\x66", 0)


# ── kiểu 2 và 3 ───────────────────────────────────────────────────────────────

def test_relative_word_type_little_endian() -> None:
    fmt = DtoFormat(id_type=2, overload="none")
    table = {(0x0103, 1): _entry(0x0103, 1, False, (_sig("a"), 3))}
    frame = bytes([0x01, 0x03, 0x01, 0x7F, 0, 0, 0, 0])      # DAQ = 0x0103 = 259
    samples = decode_dto(frame, table, _acc(fmt), fmt)
    assert [s.value_raw for s in samples] == [b"\x7F"]


def test_relative_word_daq_number_byte_order() -> None:
    """Review Focus #3: DAQ list ≥ 256 và slave big-endian."""
    fmt = DtoFormat(id_type=2, byte_order="big", overload="none")
    table = {(0x0103, 1): _entry(0x0103, 1, False, (_sig("a"), 3))}
    frame = bytes([0x01, 0x01, 0x03, 0x7F, 0, 0, 0, 0])      # big-endian: 01 03
    samples = decode_dto(frame, table, _acc(fmt), fmt)
    assert [s.value_raw for s in samples] == [b"\x7F"]


def test_relative_word_aligned_type_ignores_fill_byte() -> None:
    fmt = DtoFormat(id_type=3, overload="none")
    table = {(0x0103, 1): _entry(0x0103, 1, False, (_sig("a"), 4))}
    frame = bytes([0x01, 0xEE, 0x03, 0x01, 0x7F, 0, 0, 0])   # FILL = 0xEE
    samples = decode_dto(frame, table, _acc(fmt), fmt)
    assert [s.value_raw for s in samples] == [b"\x7F"]


# ── overrun theo cách ECU báo ────────────────────────────────────────────────

def test_overrun_pid_msb_is_masked_for_odt_byte() -> None:
    fmt = DtoFormat(id_type=1, overload="pid_msb")
    table = {(3, 2): _entry(3, 2, False, (_sig("a"), 2))}
    frame = bytes([0x82, 0x03, 0x11, 0, 0, 0, 0, 0])         # MSB = overrun
    assert [s.value_raw for s in decode_dto(frame, table, _acc(fmt), fmt)] == [b"\x11"]


def test_overload_none_uses_full_byte() -> None:
    fmt = DtoFormat(id_type=1, overload="none")
    table = {(3, 0x82): _entry(3, 0x82, False, (_sig("a"), 2))}
    frame = bytes([0x82, 0x03, 0x11, 0, 0, 0, 0, 0])
    assert [s.value_raw for s in decode_dto(frame, table, _acc(fmt), fmt)] == [b"\x11"]


def test_overload_event_uses_full_byte() -> None:
    fmt = DtoFormat(id_type=0, overload="event")
    table = {0x85: _entry(0, 0x85, False, (_sig("a"), 1))}
    frame = bytes([0x85, 0x11, 0, 0, 0, 0, 0, 0])
    assert [s.value_raw for s in decode_dto(frame, table, _acc(fmt), fmt)] == [b"\x11"]


# ── timestamp size khác 4 byte (kiểu 0) ──────────────────────────────────────

def test_absolute_type_one_byte_timestamp() -> None:
    fmt = DtoFormat(ts_size=1, unit_ns=1000, ticks=1)
    table = {0: _entry(0, 0, True, (_sig("a"), 2))}
    frame = bytes([0x00, 0x07, 0xAA, 0, 0, 0, 0, 0])
    samples = decode_dto(frame, table, _acc(fmt), fmt)
    assert (samples[0].value_raw, samples[0].timestamp_ns) == (b"\xAA", 7_000)


# ── không bao giờ raise ──────────────────────────────────────────────────────

@pytest.mark.parametrize("id_type", [0, 1, 2, 3])
def test_decode_never_raises_on_short_or_unknown_frames(id_type: int) -> None:
    """Review Focus #5."""
    fmt = DtoFormat(id_type=id_type)
    table = {(0, 0) if id_type else 0: _entry(0, 0, True, (_sig("a"), 6))}
    acc = _acc(fmt)
    for frame in (b"", b"\x00", b"\x00\x00", b"\x00\x00\x00", b"\xFF" * 8,
                  bytes(range(8))):
        assert isinstance(decode_dto(frame, table, acc, fmt), list)   # không raise


def test_frame_shorter_than_header_returns_empty() -> None:
    fmt = DtoFormat(id_type=3)
    assert decode_dto(b"\x01\x00", {(0, 1): _entry(0, 1, False)}, _acc(fmt), fmt) == []


def test_frame_too_short_for_timestamp_gives_zero_and_skips_signals() -> None:
    fmt = DtoFormat(id_type=2, ts_size=4)
    table = {(0, 0): _entry(0, 0, True, (_sig("a"), 7))}     # header 3 + TS 4 = 7
    frame = bytes([0x00, 0x00, 0x00, 0x01, 0x02])            # 5 byte: thiếu TS
    assert decode_dto(frame, table, _acc(fmt), fmt) == []


def test_decode_invalid_unit_still_skips_timestamp_bytes() -> None:
    """Review Focus #2: ticks = 0 → timestamp_ns = 0 nhưng signal vẫn đúng offset."""
    fmt = DtoFormat(ts_size=2, unit_ns=1000, ticks=0)
    table = {0: _entry(0, 0, True, (_sig("a"), 3))}          # header 1 + TS 2 = offset 3
    frame = bytes([0x00, 0x34, 0x12, 0x99, 0, 0, 0, 0])
    samples = decode_dto(frame, table, _acc(fmt), fmt)
    assert (samples[0].value_raw, samples[0].timestamp_ns) == (b"\x99", 0)
```

- [x] **Step 2: Chạy test, xác nhận đỏ**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_daq_dto_decode.py -v`
Expected: FAIL — `TypeError: decode_dto() takes 3 positional arguments but 4 were given`.

- [x] **Step 3: Thay `decode_dto`**

Thêm vào đầu file `daq.py` (cạnh `from dataclasses import ...`):

```python
from collections.abc import Mapping
```

Thay toàn bộ hàm `decode_dto` hiện có bằng:

```python
def decode_dto(
    frame: bytes,
    pid_table: Mapping[DtoKey, PidEntry],
    ts_accum: TimestampAccumulator,
    fmt: DtoFormat | None = None,
) -> list[SamplePoint]:
    """Decode một DTO frame thành list SamplePoint theo layout `fmt`.

    Chạy trên RX thread: KHÔNG bao giờ raise — frame rỗng, ngắn hơn header,
    hoặc khoá không có trong bảng → `[]`.

    Header theo `fmt.id_type` (xem DtoFormat). Bảng tra khoá bằng PID tuyệt đối
    (kiểu 0) hoặc `(số DAQ list, số ODT)` (kiểu 1–3). Nếu `fmt.overload` là
    "pid_msb", bit 7 của byte đầu là cờ overrun — mask trước khi tra bảng.
    Timestamp chỉ có ở ODT 0 (`has_timestamp=True`), ngay sau header; frame
    ngắn hơn `header + ts_size` thì `timestamp_ns = 0`.
    Frame quá ngắn cho một signal → signal đó bị bỏ qua.
    """
    if fmt is None:
        fmt = DtoFormat()
    header_len = fmt.header_len
    if len(frame) < header_len:
        return []

    first = frame[0]
    odt_or_pid = first & 0x7F if fmt.overload == "pid_msb" else first
    key: DtoKey
    if fmt.id_type == 0:
        key = odt_or_pid
    else:
        if fmt.id_type == 1:
            daq = frame[1]
        elif fmt.id_type == 2:
            daq = int.from_bytes(frame[1:3], fmt.byte_order)
        else:                                   # kiểu 3: frame[1] là byte FILL
            daq = int.from_bytes(frame[2:4], fmt.byte_order)
        key = (daq, odt_or_pid)

    entry = pid_table.get(key)
    if entry is None:
        return []

    ts_ns = 0
    if entry.has_timestamp and fmt.ts_size > 0 and len(frame) >= header_len + fmt.ts_size:
        raw_ts = int.from_bytes(
            frame[header_len:header_len + fmt.ts_size],
            ts_accum.byte_order,  # type: ignore[arg-type]
        )
        ts_ns = ts_accum.to_ns(raw_ts)

    samples: list[SamplePoint] = []
    for layout in entry.signals:
        end = layout.frame_offset + layout.signal.size
        if end > len(frame):
            continue
        samples.append(SamplePoint(
            name=layout.signal.name,
            timestamp_ns=ts_ns,
            value_raw=frame[layout.frame_offset:end],
            datatype=layout.signal.datatype,
        ))
    return samples
```

- [x] **Step 4: Chạy test, xác nhận xanh**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_daq_dto_decode.py tests/unit/test_daq_decoder.py tests/unit/test_dto_format.py -v`
Expected: tất cả PASS (test decoder cũ vẫn xanh vì `fmt=None` → `DtoFormat()`).

- [x] **Step 5: Commit**

```bash
git add src/xcptool/master/daq.py tests/unit/test_daq_dto_decode.py
git diff --cached --name-only
git commit -m "feat(xcptool): decode_dto theo DtoFormat (4 kiểu identification field, overrun theo caps)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `pack_odts` theo `DtoFormat`

**Files:**
- Modify: `src/xcptool/master/daq.py` (`pack_odts`: signature, docstring, tính ngân sách)
- Create: `tests/unit/test_daq_packing_fmt.py`

**Interfaces:**
- Consumes: `DtoFormat` (Task 2).
- Produces: `pack_odts(signals: list[DaqSignal], timestamp_on: bool, max_dto: int = 8, *, fmt: DtoFormat | None = None) -> list[list[DaqSignal]]`; ngân sách ODT đầu = `max_dto − header_len − (ts_size nếu timestamp_on)`, các ODT còn lại = `max_dto − header_len`; `ValueError` khi `max_dto − header_len ≤ 0` hoặc `timestamp_on` và `header_len + ts_size > max_dto`.

- [x] **Step 1: Viết test đỏ**

Tạo `tests/unit/test_daq_packing_fmt.py`:

```python
"""pack_odts tôn trọng độ dài header và kích thước timestamp của ECU."""

from __future__ import annotations

import pytest

from xcptool.master.daq import DaqSignal, DtoFormat, pack_odts


def sig(name: str, size: int) -> DaqSignal:
    return DaqSignal(name=name, address=0, ext=0, size=size, datatype="UBYTE")


def sizes(odts: list[list[DaqSignal]]) -> list[list[int]]:
    return [[s.size for s in odt] for odt in odts]


def test_default_format_keeps_legacy_budgets() -> None:
    """Header 1 B + TS 4 B: ODT 0 = 3 B, ODT 1+ = 7 B (như trước)."""
    assert sizes(pack_odts([sig("a", 3), sig("b", 7)], True)) == [[3], [7]]


def test_relative_byte_header_shrinks_budgets() -> None:
    """Kiểu 1 (header 2 B) + TS 4 B trên DTO 8 B: ODT 0 = 2 B, ODT 1+ = 6 B."""
    fmt = DtoFormat(id_type=1)
    assert sizes(pack_odts([sig("a", 2), sig("b", 6)], True, fmt=fmt)) == [[2], [6]]


def test_signal_larger_than_rest_budget_is_rejected_with_new_budget() -> None:
    fmt = DtoFormat(id_type=1)
    with pytest.raises(ValueError, match="7B > max 6B"):
        pack_odts([sig("big", 7)], True, fmt=fmt)


def test_odt0_can_be_empty_when_header_plus_timestamp_fill_the_dto() -> None:
    """Kiểu 3 (header 4 B) + TS 4 B trên DTO 8 B: ODT 0 ngân sách 0, ODT 1+ = 4 B."""
    fmt = DtoFormat(id_type=3)
    assert sizes(pack_odts([sig("a", 4)], True, fmt=fmt)) == [[], [4]]
    with pytest.raises(ValueError, match="5B > max 4B"):
        pack_odts([sig("b", 5)], True, fmt=fmt)


def test_timestamp_size_follows_ecu_not_four_bytes() -> None:
    """TS 2 B, header 1 B: ODT 0 = 5 B."""
    fmt = DtoFormat(ts_size=2)
    assert sizes(pack_odts([sig("a", 5), sig("b", 2)], True, fmt=fmt)) == [[5], [2]]


def test_timestamp_off_ignores_timestamp_size() -> None:
    fmt = DtoFormat(id_type=3)
    assert sizes(pack_odts([sig("a", 4)], False, fmt=fmt)) == [[4]]


def test_header_does_not_fit_in_dto_is_rejected() -> None:
    with pytest.raises(ValueError, match="header"):
        pack_odts([sig("a", 1)], False, max_dto=4, fmt=DtoFormat(id_type=3))


def test_header_plus_timestamp_larger_than_dto_is_rejected() -> None:
    with pytest.raises(ValueError, match="timestamp"):
        pack_odts([sig("a", 1)], True, max_dto=7, fmt=DtoFormat(id_type=3))
    # cùng DTO nhưng không timestamp thì hợp lệ
    assert sizes(pack_odts([sig("a", 1)], False, max_dto=7, fmt=DtoFormat(id_type=3))) == [[1]]


def test_can_fd_dto_uses_full_payload() -> None:
    fmt = DtoFormat(id_type=2)          # header 3 B, TS 4 B → ODT 0 = 57 B, ODT 1+ = 61 B
    assert sizes(pack_odts([sig("a", 57), sig("b", 61)], True, max_dto=64, fmt=fmt)) == [[57], [61]]
```

- [x] **Step 2: Chạy test, xác nhận đỏ**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_daq_packing_fmt.py -v`
Expected: FAIL — `TypeError: pack_odts() got an unexpected keyword argument 'fmt'`.

- [x] **Step 3: Sửa `pack_odts`**

Thay signature, docstring và khối tính ngân sách (từ `def pack_odts(` đến hết vòng `for s in signals: if s.size > rest_budget: raise ...`) bằng:

```python
def pack_odts(
    signals: list[DaqSignal],
    timestamp_on: bool,
    max_dto: int = 8,
    *,
    fmt: DtoFormat | None = None,
) -> list[list[DaqSignal]]:
    """Nhét signals vào các ODT, tôn trọng ngân sách byte từng ODT.

    Ngân sách tính từ layout DTO của ECU (`fmt`, mặc định `DtoFormat()`):
        first_budget = max_dto − header_len − (ts_size nếu timestamp_on)
        rest_budget  = max_dto − header_len
    Ví dụ CAN 8 B, header 1 B, TS 4 B: ODT 0 = 3 B, ODT 1+ = 7 B.

    Thuật toán: tách signals thành hai nhóm theo first_budget, xử lý ODT 0
    riêng (first-fit-decreasing), sau đó xử lý ODT 1+ (large trước, remaining small).

    Trả về list các ODT; ODT 0 CÓ THỂ RỖNG — không phải lỗi, xảy ra khi tất cả
    signals đều lớn hơn first_budget.

    Raises:
        ValueError: DTO không đủ chỗ cho header (hoặc header + timestamp), hoặc
            một signal lớn hơn rest_budget — không thể nhét vào bất kỳ ODT nào.
    """
    if fmt is None:
        fmt = DtoFormat()
    header = fmt.header_len
    ts = fmt.ts_size if timestamp_on else 0
    rest_budget = max_dto - header
    first_budget = rest_budget - ts
    if rest_budget <= 0:
        raise ValueError(
            f"max_dto={max_dto}B không đủ chỗ cho header DTO {header}B")
    if first_budget < 0:
        raise ValueError(
            f"max_dto={max_dto}B không đủ chỗ cho header {header}B + timestamp {ts}B")

    for s in signals:
        if s.size > rest_budget:
            raise ValueError(
                f"{s.name}: {s.size}B > max {rest_budget}B/ODT — phải tách nhỏ hơn"
            )
```

Phần còn lại của hàm (từ `small = sorted(...)` trở xuống) giữ nguyên.

- [x] **Step 4: Chạy test, xác nhận xanh**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_daq_packing_fmt.py tests/unit/test_daq_packing.py -v`
Expected: tất cả PASS (test packing cũ xanh không sửa, kể cả `match="8B > max 7B"`).

- [x] **Step 5: Commit**

```bash
git add src/xcptool/master/daq.py tests/unit/test_daq_packing_fmt.py
git diff --cached --name-only
git commit -m "feat(xcptool): pack_odts tính ngân sách ODT theo header và timestamp thật của ECU" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Fakeslave phát DTO theo caps cấu hình được

**Files:**
- Modify: `src/xcptool/devtools/fakeslave.py`
- Create: `tests/unit/test_fakeslave_dto.py`

**Interfaces:**
- Consumes: `TIMESTAMP_UNIT_NS` từ `master.constants` (có sẵn).
- Produces: `SlaveConfig.id_field_type: int = 0`, `.overload: str = "pid_msb"`, `.timestamp_supported: bool = True`, `.timestamp_fixed: bool = False`; `FakeSlave._dto_header(daq, odt_idx, first_pid) -> bytes`; `FakeSlave._timestamp_ticks(elapsed_ns) -> int`. `GET_DAQ_PROCESSOR_INFO` trả bit 4 theo `timestamp_supported`, bit 7–6 theo `overload`, key byte `id_field_type << 6`; `GET_DAQ_RESOLUTION_INFO` trả bit 3 (`TIMESTAMP_FIXED`); `SET_DAQ_LIST_MODE` trả `ERR_CMD_SYNTAX` nếu `timestamp_fixed` mà master tắt timestamp.

- [x] **Step 1: Viết test đỏ**

Tạo `tests/unit/test_fakeslave_dto.py`:

```python
"""Fakeslave phải nói đúng caps và phát đúng DTO — nếu không, test end-to-end
ở Task 6 không có gì để kiểm chứng."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from xcptool.devtools.fakeslave import FakeSlave, SlaveConfig
from xcptool.session.api import BusConfig, SlaveError, SlaveCaps
from xcptool.session.real import RealSession


@contextmanager
def connected(cfg: SlaveConfig) -> Iterator[tuple[RealSession, SlaveCaps, FakeSlave]]:
    bus = BusConfig(backend="virtual", channel=cfg.channel, cro_id=cfg.cro_id,
                    dto_id=cfg.dto_id, pad_dlc=cfg.pad_dlc, t1_timeout_s=0.5)
    session = RealSession()
    try:
        with FakeSlave(cfg) as slave:
            yield session, session.connect(bus), slave
    finally:
        session.close()


@pytest.mark.parametrize("id_type", [0, 1, 2, 3])
def test_caps_report_identification_field_type(channel: str, id_type: int) -> None:
    with connected(SlaveConfig(channel=channel, id_field_type=id_type)) as (_, caps, _s):
        assert caps.daq is not None
        assert caps.daq.id_field_type == id_type


@pytest.mark.parametrize("overload", ["none", "pid_msb", "event"])
def test_caps_report_overload_indication(channel: str, overload: str) -> None:
    with connected(SlaveConfig(channel=channel, overload=overload)) as (_, caps, _s):
        assert caps.daq is not None
        assert caps.daq.overload == overload


def test_caps_report_timestamp_fixed(channel: str) -> None:
    with connected(SlaveConfig(channel=channel, timestamp_fixed=True)) as (_, caps, _s):
        assert caps.daq is not None
        assert caps.daq.timestamp_fixed is True


def test_timestamp_not_supported_is_reported_even_with_garbage_mode(channel: str) -> None:
    """Fakeslave vẫn trả TIMESTAMP_MODE (size 4) nhưng xoá bit TIMESTAMP_SUPPORTED."""
    cfg = SlaveConfig(channel=channel, timestamp_supported=False, timestamp_size=4)
    with connected(cfg) as (_, caps, _s):
        assert caps.daq is not None
        assert caps.daq.timestamp_supported is False
        assert caps.daq.timestamp_size == 0


def test_set_daq_list_mode_refuses_to_disable_fixed_timestamp(channel: str) -> None:
    cfg = SlaveConfig(channel=channel, timestamp_fixed=True)
    with connected(cfg) as (session, _caps, _s):
        master = session._master  # type: ignore[attr-defined]
        master.free_daq()
        master.alloc_daq(1)
        with pytest.raises(SlaveError):
            master.set_daq_list_mode(0, 0, 0x00, 1, 0)     # bit 4 = 0: tắt timestamp
        master.set_daq_list_mode(0, 0, 0x10, 1, 0)         # bật thì được


@pytest.mark.parametrize("byte_order,id_type,expected", [
    ("little", 0, bytes([12])),                 # PID = first_pid + odt
    ("little", 1, bytes([2, 3])),               # ODT, DAQ (BYTE)
    ("little", 2, bytes([2, 3, 1])),            # ODT, DAQ_lo, DAQ_hi (daq = 259)
    ("big",    2, bytes([2, 1, 3])),
    ("little", 3, bytes([2, 0, 3, 1])),         # ODT, FILL, DAQ_lo, DAQ_hi
    ("big",    3, bytes([2, 0, 1, 3])),
])
def test_dto_header_layout(channel: str, byte_order: str, id_type: int, expected: bytes) -> None:
    cfg = SlaveConfig(channel=channel, byte_order=byte_order, id_field_type=id_type)
    with FakeSlave(cfg) as slave:
        assert slave._dto_header(daq=259, odt_idx=2, first_pid=10) == expected


def test_timestamp_ticks_follow_unit_ticks_and_width(channel: str) -> None:
    """Đơn vị 1 ms, ticks 10, 2 byte: 2,5 ms → 25; 7 s → 70000 cắt 16 bit = 4464."""
    cfg = SlaveConfig(channel=channel, timestamp_size=2, timestamp_unit_code=0x6,
                      timestamp_ticks=10)
    with FakeSlave(cfg) as slave:
        assert slave._timestamp_ticks(2_500_000) == 25
        assert slave._timestamp_ticks(7_000_000_000) == 70000 & 0xFFFF


def test_timestamp_ticks_default_is_32bit_10ns(channel: str) -> None:
    with FakeSlave(SlaveConfig(channel=channel)) as slave:
        assert slave._timestamp_ticks(1_000) == 100
```

- [x] **Step 2: Chạy test, xác nhận đỏ**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_fakeslave_dto.py -v`
Expected: FAIL — `TypeError: SlaveConfig.__init__() got an unexpected keyword argument 'id_field_type'`.

- [x] **Step 3: Sửa `SlaveConfig`**

Trong `src/xcptool/devtools/fakeslave.py`, dòng import:

```python
from ..master.constants import Cmd, ErrCode
```

thành:

```python
from ..master.constants import TIMESTAMP_UNIT_NS, Cmd, ErrCode
```

Ngay sau `log = logging.getLogger("xcptool.devtools.fakeslave")` thêm:

```python
# DAQ_PROPERTIES bit 7-6: cách ECU báo overrun
_OVERLOAD_BITS = {"none": 0x00, "pid_msb": 0x40, "event": 0x80}
```

Trong `SlaveConfig`, ngay sau dòng `timestamp_ticks: int = 1` thêm:

```python
    timestamp_supported: bool = True      # bit TIMESTAMP_SUPPORTED trong DAQ_PROPERTIES
    timestamp_fixed: bool = False         # bit TIMESTAMP_FIXED: DTO luôn có timestamp
    id_field_type: int = 0                # 0 absolute | 1 rel+DAQ BYTE | 2 rel+DAQ WORD | 3 WORD aligned
    overload: str = "pid_msb"             # "none" | "pid_msb" | "event"
```

- [x] **Step 4: Sửa các lệnh info và `SET_DAQ_LIST_MODE`**

`_cmd_daq_processor_info` — thay toàn bộ thân (kể cả sửa tạm ở Task 1 Step 5b) bằng:

```python
    def _cmd_daq_processor_info(self, data: bytes) -> None:
        if not (self.cfg.supports_daq and self.cfg.supports_daq_info):
            self._err(ErrCode.CMD_UNKNOWN)
            return
        properties = ((0x01 if self.cfg.daq_dynamic else 0)
                      | (0x10 if self.cfg.timestamp_supported else 0)
                      | (0x20 if self.cfg.pid_off_supported else 0)
                      | _OVERLOAD_BITS[self.cfg.overload])
        key_byte = (self.cfg.id_field_type & 0x03) << 6
        self._reply(bytes([0xFF, properties])
                    + self._u16(self.cfg.max_daq)
                    + self._u16(self.cfg.max_event_channel)
                    + bytes([self.cfg.min_daq, key_byte]))
```

`_cmd_daq_resolution_info` — đổi dòng tính `ts_mode`:

```python
        ts_mode = (self.cfg.timestamp_size & 0x07) | ((self.cfg.timestamp_unit_code
                                                       & 0x0F) << 4)
```

thành:

```python
        ts_mode = ((self.cfg.timestamp_size & 0x07)
                   | (0x08 if self.cfg.timestamp_fixed else 0)
                   | ((self.cfg.timestamp_unit_code & 0x0F) << 4))
```

`_cmd_set_daq_list_mode` — ngay sau khối kiểm `if daq >= len(self._daq_lists): ... return` thêm:

```python
        if (self.cfg.timestamp_fixed and self.cfg.timestamp_supported
                and not (mode & 0x10)):
            # Spec: TIMESTAMP_FIXED thì master không được tắt timestamp.
            self._err(ErrCode.CMD_SYNTAX)
            return
```

- [x] **Step 5: Thêm helper và sửa vòng phát DTO**

Thay hai hàm `_daq_send_loop` và `_send_daq_frames` (từ `def _daq_send_loop` đến hết `_send_daq_frames`, ngay trước `# ── xử lý lệnh`) bằng:

```python
    def _timestamp_ticks(self, elapsed_ns: float) -> int:
        """Giá trị bộ đếm timestamp của ECU giả: tăng `timestamp_ticks` mỗi
        `unit` (theo `timestamp_unit_code`), cắt theo `timestamp_size` byte."""
        unit_ns = TIMESTAMP_UNIT_NS.get(self.cfg.timestamp_unit_code, 0)
        size = self.cfg.timestamp_size
        if unit_ns == 0 or self.cfg.timestamp_ticks == 0 or size == 0:
            return 0
        ticks = int(elapsed_ns * self.cfg.timestamp_ticks / unit_ns)
        return ticks & ((1 << (8 * size)) - 1)

    def _dto_header(self, daq: int, odt_idx: int, first_pid: int) -> bytes:
        """Header identification field của DTO theo `id_field_type`."""
        kind = self.cfg.id_field_type
        if kind == 0:
            return bytes([(first_pid + odt_idx) & 0xFF])
        odt = bytes([odt_idx & 0xFF])
        if kind == 1:
            return odt + bytes([daq & 0xFF])
        word = daq.to_bytes(2, self.cfg.byte_order)  # type: ignore[arg-type]
        if kind == 2:
            return odt + word
        return odt + b"\x00" + word                  # kiểu 3: byte FILL

    def _daq_send_loop(self) -> None:
        """Gửi DTO frame 100 Hz cho mỗi DAQ list đang chạy."""
        period = 0.01   # 10ms = 100 Hz
        next_at = time.perf_counter()
        while not self._daq_stop.is_set() and not self._stop.is_set():
            now = time.perf_counter()
            if now < next_at:
                time.sleep(min(next_at - now, 0.005))
                continue
            next_at += period
            elapsed_ns = (now - self._daq_t0) * 1e9
            self._send_daq_frames(self._timestamp_ticks(elapsed_ns))

    def _send_daq_frames(self, ts_ticks: int) -> None:
        """Đọc bộ nhớ ECU giả, đóng gói frame DTO và gửi lên bus."""
        try:
            snap = list(zip(self._daq_lists, self._daq_modes, self._daq_first_pids))
        except Exception:  # noqa: BLE001
            return
        bo = self.cfg.byte_order
        ts_size = self.cfg.timestamp_size if self.cfg.timestamp_supported else 0
        for daq, (odts, mode_info, first_pid) in enumerate(snap):
            has_ts = ts_size > 0 and (self.cfg.timestamp_fixed
                                      or bool(mode_info.get("mode", 0) & 0x10))
            try:
                odt_list = list(enumerate(odts))
            except Exception:  # noqa: BLE001
                continue
            for odt_idx, entries in odt_list:
                frame = bytearray(self._dto_header(daq, odt_idx, first_pid))
                if odt_idx == 0 and has_ts:
                    frame += ts_ticks.to_bytes(ts_size, bo)  # type: ignore[arg-type]
                for _bit_off, sz, _ext, addr in entries:
                    off = addr - self.cfg.mem_base
                    if 0 <= off and off + sz <= self.cfg.mem_size:
                        frame += self.memory[off:off + sz]
                    else:
                        frame += bytes(sz)
                if self.cfg.is_fd:
                    target_len = round_to_can_fd_dlc(len(frame))
                    if self.cfg.pad_dlc and target_len < 8:
                        target_len = 8
                    if len(frame) < target_len:
                        frame = frame.ljust(target_len, b"\x00")
                    payload = bytes(frame[:self.cfg.max_dto])
                else:
                    if self.cfg.pad_dlc and len(frame) < 8:
                        frame = frame.ljust(8, b"\x00")
                    payload = bytes(frame[:8])
                try:
                    self._bus.send(can.Message(
                        arbitration_id=self.cfg.dto_id, data=payload,
                        is_extended_id=self.cfg.extended_id,
                        is_fd=self.cfg.is_fd,
                        bitrate_switch=self.cfg.is_fd))
                except Exception:  # noqa: BLE001
                    return
```

- [x] **Step 6: Chạy test, xác nhận xanh**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_fakeslave_dto.py tests/unit/test_capabilities.py tests/integration/test_daq.py tests/integration/test_session_daq.py -v`
Expected: tất cả PASS — đặc biệt các test tích hợp DAQ cũ phải xanh không sửa (cấu hình mặc định của fakeslave phát đúng như trước: header 1 B, TS 4 B, 10 ns).

- [x] **Step 7: Commit**

```bash
git add src/xcptool/devtools/fakeslave.py tests/unit/test_fakeslave_dto.py
git diff --cached --name-only
git commit -m "feat(xcptool): fakeslave phát DTO theo id_field_type, timestamp size/unit/ticks, overload, TIMESTAMP_FIXED" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `configure_daq`, `configure_daq_predefined`, `RealSession` theo `DtoFormat` + tích hợp end-to-end

**Files:**
- Modify: `src/xcptool/master/daq.py` (`configure_daq`, `_write_and_start`, `configure_daq_predefined`)
- Modify: `src/xcptool/session/real.py` (import, `__init__`, `start_daq`, `_on_daq_frame`)
- Create: `tests/integration/test_daq_dto_formats.py`

**Interfaces:**
- Consumes: `DtoFormat.from_slave_caps`, `make_key`, `effective_timestamp`, `pack_odts(..., fmt=)`, `decode_dto(..., fmt)`, `TimestampAccumulator.from_format` (Task 2–4); fakeslave cấu hình mới (Task 5).
- Produces: `configure_daq(master, configs) -> dict[DtoKey, PidEntry]` (chữ ký không đổi); `_write_and_start(master, configs, packed, daq_indices, fmt, eff_ts)`; `RealSession._daq_fmt: DtoFormat`.

- [x] **Step 1: Viết test đỏ**

Tạo `tests/integration/test_daq_dto_formats.py`:

```python
"""Tích hợp end-to-end: DTO theo caps của ECU, đi qua ĐÚNG RealSession.start_daq().

Fakeslave trên virtual bus phát DTO theo `id_field_type`, timestamp size/unit/ticks
cấu hình được; master phải tự suy ra layout từ caps rồi decode đúng mẫu.
"""

from __future__ import annotations

import time

import can
import pytest

from xcptool.devtools.fakeslave import FakeSlave, SlaveConfig
from xcptool.master.constants import Cmd
from xcptool.master.daq import (
    DaqSignal as MasterSignal,
    DtoFormat,
    OdtSignalLayout,
    PredefinedDaqList,
    TimestampAccumulator,
    configure_daq_predefined,
    decode_dto,
)
from xcptool.session.api import BusConfig, DaqList, DaqSignal, SamplePoint
from xcptool.session.real import RealSession


def _bus(channel: str, cfg: SlaveConfig) -> BusConfig:
    return BusConfig(backend="virtual", channel=channel, cro_id=cfg.cro_id,
                     dto_id=cfg.dto_id, t1_timeout_s=0.5)


def _collect(session: RealSession, name: str, want: int = 5,
             timeout: float = 2.0) -> list[SamplePoint]:
    deadline = time.perf_counter() + timeout
    got: list[SamplePoint] = []
    while time.perf_counter() < deadline and len(got) < want:
        time.sleep(0.02)
        got += [s for s in session.drain_daq(200) if s.name == name]
    return got


# (id_field_type, ts_size, unit_code, ticks, ODT 0 còn chỗ cho signal 1 B?)
_CASES = [
    (0, 4, 0x1, 1, True),
    (1, 2, 0x6, 10, True),
    (2, 1, 0x6, 1, True),
    (3, 2, 0x6, 10, True),
    (3, 4, 0x1, 1, False),   # header 4 B + TS 4 B = 8 B: ODT 0 hết chỗ, signal sang ODT 1 (không TS)
]


@pytest.mark.parametrize("id_type,ts_size,unit,ticks,ts_on_sample", _CASES)
def test_start_daq_decodes_every_header_type(
    channel: str, id_type: int, ts_size: int, unit: int, ticks: int, ts_on_sample: bool,
) -> None:
    cfg = SlaveConfig(channel=channel, id_field_type=id_type, timestamp_size=ts_size,
                      timestamp_unit_code=unit, timestamp_ticks=ticks)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(channel, cfg))
        assert session.caps is not None and session.caps.daq is not None
        assert session.caps.daq.id_field_type == id_type

        addr = cfg.mem_base
        slave.poke(addr, b"\x5A")
        session.start_daq([DaqList(signals=[DaqSignal("b", addr, 0, 1, "UINT8")],
                                   event=0, timestamp=True)])
        samples = _collect(session, "b")
        session.stop_daq()
    session.close()

    assert len(samples) >= 3, "không nhận đủ sample"
    assert all(s.value_raw == b"\x5A" for s in samples)
    stamps = [s.timestamp_ns for s in samples]
    if ts_on_sample:
        assert stamps == sorted(stamps)
        assert stamps[-1] > stamps[0]
    else:
        assert stamps == [0] * len(stamps)


@pytest.mark.parametrize("byte_order", ["little", "big"])
@pytest.mark.parametrize("id_type", [2, 3])
def test_word_daq_number_respects_slave_byte_order(
    channel: str, id_type: int, byte_order: str,
) -> None:
    cfg = SlaveConfig(channel=channel, id_field_type=id_type, byte_order=byte_order,
                      timestamp_size=2, timestamp_unit_code=0x6, timestamp_ticks=1)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(channel, cfg))
        addr = cfg.mem_base
        slave.poke(addr, b"\x5A")
        session.start_daq([DaqList(signals=[DaqSignal("b", addr, 0, 1, "UINT8")],
                                   event=0, timestamp=False)])
        samples = _collect(session, "b", want=3)
    session.close()
    assert samples and all(s.value_raw == b"\x5A" for s in samples)


@pytest.mark.parametrize("id_type", [1, 2, 3])
def test_static_ecu_relative_ids_use_the_physical_list_number(
    channel: str, id_type: int,
) -> None:
    """List 0 là predefined nên master dùng list vật lý 1: DTO kiểu 1–3 mang số 1
    (không phải số thứ tự trong cấu hình), nên decode đúng chứng tỏ khoá đúng."""
    cfg = SlaveConfig(channel=channel, daq_dynamic=False, min_daq=3, max_daq=3,
                      static_predefined_lists=frozenset({0}), id_field_type=id_type)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(channel, cfg))
        addr = cfg.mem_base
        slave.poke(addr, b"\x5A")
        session.start_daq([DaqList(signals=[DaqSignal("b", addr, 0, 1, "UINT8")],
                                   event=0, timestamp=False)])
        samples = _collect(session, "b", want=3)
        assert slave.daq_entries(1, 0), "signal phải nằm ở list vật lý 1"
        assert slave.daq_entries(0, 0) == []
    session.close()
    assert samples and all(s.value_raw == b"\x5A" for s in samples)


def test_caps_daq_none_keeps_legacy_layout(channel: str) -> None:
    """Review Focus #1: ECU không trả lời GET_DAQ_PROCESSOR_INFO → layout cũ."""
    cfg = SlaveConfig(channel=channel, supports_daq_info=False)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(channel, cfg))
        assert session.caps is not None and session.caps.daq is None
        addr = cfg.mem_base
        slave.poke(addr, b"\x5A")
        session.start_daq([DaqList(signals=[DaqSignal("b", addr, 0, 1, "UINT8")],
                                   event=0, timestamp=True)])
        samples = _collect(session, "b")
    session.close()
    assert len(samples) >= 3 and all(s.value_raw == b"\x5A" for s in samples)
    stamps = [s.timestamp_ns for s in samples]
    assert stamps == sorted(stamps) and stamps[-1] > stamps[0]


def test_timestamp_fixed_is_enabled_even_when_not_requested(channel: str) -> None:
    cfg = SlaveConfig(channel=channel, timestamp_fixed=True)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(channel, cfg))
        addr = cfg.mem_base
        slave.poke(addr, b"\x5A")
        session.start_daq([DaqList(signals=[DaqSignal("b", addr, 0, 1, "UINT8")],
                                   event=0, timestamp=False)])     # master KHÔNG xin timestamp
        samples = _collect(session, "b")
    session.close()
    assert len(samples) >= 3 and all(s.value_raw == b"\x5A" for s in samples)
    stamps = [s.timestamp_ns for s in samples]
    assert stamps == sorted(stamps) and stamps[-1] > stamps[0]


def test_timestamp_request_is_dropped_when_ecu_has_none(channel: str) -> None:
    cfg = SlaveConfig(channel=channel, timestamp_supported=False, timestamp_size=4)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(channel, cfg))
        addr = cfg.mem_base
        slave.poke(addr, b"\x5A")
        session.start_daq([DaqList(signals=[DaqSignal("b", addr, 0, 1, "UINT8")],
                                   event=0, timestamp=True)])
        samples = _collect(session, "b", want=3)
        assert slave._daq_modes[0]["mode"] & 0x10 == 0     # master không đặt bit timestamp
    session.close()
    assert samples and all(s.value_raw == b"\x5A" for s in samples)
    assert all(s.timestamp_ns == 0 for s in samples)


# ── list predefined ──────────────────────────────────────────────────────────

def _predefined_cfg(channel: str, **extra: object) -> SlaveConfig:
    return SlaveConfig(channel=channel, daq_dynamic=False, min_daq=1, max_daq=1,
                       static_predefined_lists=frozenset({0}), **extra)  # type: ignore[arg-type]


def test_predefined_list_with_relative_header(channel: str) -> None:
    cfg = _predefined_cfg(channel, id_field_type=1)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(channel, cfg))
        master = session._master  # type: ignore[attr-defined]
        addr = cfg.mem_base
        expected = b"\x39\x05"
        slave.poke(addr, expected)
        slave.set_predefined_daq_content(0, 0, [(0xFF, 2, 0, addr)])

        sig = MasterSignal("val", addr, 0, 2, "UINT16")
        layout = OdtSignalLayout(signal=sig, frame_offset=2)    # header 2 B, không timestamp
        pl = PredefinedDaqList(daq=0, odts=[[layout]], event=0, timestamp=False)
        table = configure_daq_predefined(master, [pl])
        assert set(table) == {(0, 0)}

        fmt = DtoFormat.from_slave_caps(master.caps)
        sniffer = can.Bus(interface="virtual", channel=channel, receive_own_messages=False)
        try:
            deadline = time.perf_counter() + 1.0
            frame: bytes | None = None
            while time.perf_counter() < deadline and frame is None:
                msg = sniffer.recv(0.05)
                if (msg is not None and msg.arbitration_id == cfg.dto_id
                        and msg.data[0] == 0 and msg.data[1] == 0):
                    frame = bytes(msg.data)
            assert frame is not None, "không nhận được DTO"
            samples = decode_dto(frame, table, TimestampAccumulator.from_format(fmt), fmt)
            assert [s.value_raw for s in samples if s.name == "val"] == [expected]
        finally:
            sniffer.shutdown()
    session.close()


def test_predefined_offset_overlapping_header_is_rejected_before_any_command(
    channel: str,
) -> None:
    cfg = _predefined_cfg(channel, id_field_type=1)
    session = RealSession()
    with FakeSlave(cfg) as slave:
        session.connect(_bus(channel, cfg))
        master = session._master  # type: ignore[attr-defined]
        sig = MasterSignal("val", cfg.mem_base, 0, 2, "UINT16")
        layout = OdtSignalLayout(signal=sig, frame_offset=1)    # header kiểu 1 là 2 B
        pl = PredefinedDaqList(daq=0, odts=[[layout]], event=0, timestamp=False)
        with pytest.raises(ValueError, match="frame_offset"):
            configure_daq_predefined(master, [pl])
        assert int(Cmd.SET_DAQ_LIST_MODE) not in slave.commands_seen
    session.close()
```

- [x] **Step 2: Chạy test, xác nhận đỏ**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_daq_dto_formats.py -v -x`
Expected: FAIL — kiểu 1–3 không decode được (samples rỗng → `assert len(samples) >= 3`), và `test_predefined_offset_overlapping_header...` đỏ vì chưa có guard.

- [x] **Step 3: Sửa `configure_daq`**

Trong `daq.py`, thân `configure_daq`, thay đoạn từ `caps = master.caps` đến hết `return _write_and_start(...)`. Đoạn cũ:

```python
    caps = master.caps
    if caps is None:
        raise NotConnectedError("Chưa CONNECT tới ECU")

    max_dto = caps.max_dto
    daq_caps = caps.daq
    ts_size = (daq_caps.timestamp_size if daq_caps else 4)  # byte, thường 4 trên ECU tham chiếu

    # Đóng gói signals vào ODTs theo ngân sách từng ODT
    packed: list[list[list[DaqSignal]]] = [
        pack_odts(cfg.signals, cfg.timestamp, max_dto) for cfg in configs
    ]

    if daq_caps is not None and not daq_caps.dynamic_daq:
        daq_indices = _reserve_static_lists(master, packed, daq_caps)
    else:
        daq_indices = _reserve_dynamic_lists(master, configs, packed, daq_caps)

    return _write_and_start(master, configs, packed, daq_indices, ts_size)
```

thay bằng:

```python
    caps = master.caps
    if caps is None:
        raise NotConnectedError("Chưa CONNECT tới ECU")

    max_dto = caps.max_dto
    daq_caps = caps.daq
    fmt = DtoFormat.from_slave_caps(caps)
    # Timestamp thực sự có trong DTO của từng list (TIMESTAMP_FIXED / ECU không
    # hỗ trợ / theo yêu cầu) — quyết định ngân sách ODT, offset và bit mode.
    eff_ts = [effective_timestamp(cfg.timestamp, fmt) for cfg in configs]

    # Đóng gói signals vào ODTs theo ngân sách từng ODT
    packed: list[list[list[DaqSignal]]] = [
        pack_odts(cfg.signals, ts_on, max_dto, fmt=fmt)
        for cfg, ts_on in zip(configs, eff_ts)
    ]

    if daq_caps is not None and not daq_caps.dynamic_daq:
        daq_indices = _reserve_static_lists(master, packed, daq_caps)
    else:
        daq_indices = _reserve_dynamic_lists(master, configs, packed, daq_caps)

    return _write_and_start(master, configs, packed, daq_indices, fmt, eff_ts)
```

Đổi annotation kiểu trả về của `configure_daq` và `configure_daq_predefined` từ `dict[int, PidEntry]` thành `dict[DtoKey, PidEntry]`.

- [x] **Step 4: Sửa `_write_and_start`**

Thay signature và hai vòng xây bảng. Signature cũ:

```python
def _write_and_start(
    master: "XcpMaster",
    configs: list[DaqListConfig],
    packed: list[list[list[DaqSignal]]],
    daq_indices: list[int],
    ts_size: int,
) -> dict[int, PidEntry]:
```

thành:

```python
def _write_and_start(
    master: "XcpMaster",
    configs: list[DaqListConfig],
    packed: list[list[list[DaqSignal]]],
    daq_indices: list[int],
    fmt: DtoFormat,
    eff_ts: list[bool],
) -> dict[DtoKey, PidEntry]:
```

Trong thân, đổi vòng `# ── SET_DAQ_LIST_MODE + START_STOP_DAQ_LIST(select)`:

```python
    pid_table: dict[int, PidEntry] = {}

    for i, (cfg, odts) in enumerate(zip(configs, packed)):
        daq_idx = daq_indices[i]
        daq_mode = 0x10 if cfg.timestamp else 0x00   # bit4 = timestamp enable
        master.set_daq_list_mode(daq_idx, cfg.event, daq_mode, cfg.prescaler, cfg.priority)
        first_pid = master.start_stop_daq_list(mode=2, daq=daq_idx)

        for odt_idx, odt in enumerate(odts):
            pid = first_pid + odt_idx
            has_ts = (odt_idx == 0 and cfg.timestamp)
            base = 1 + (ts_size if has_ts else 0)   # byte 0 = PID, bytes 1..ts_size = TS

            layouts: list[OdtSignalLayout] = []
            cur = base
            for sig in odt:
                layouts.append(OdtSignalLayout(signal=sig, frame_offset=cur))
                cur += sig.size

            pid_table[pid] = PidEntry(
                daq_list=daq_idx,
                odt_index=odt_idx,
                has_timestamp=has_ts,
                signals=layouts,
            )
```

thành:

```python
    pid_table: dict[DtoKey, PidEntry] = {}

    for i, (cfg, odts) in enumerate(zip(configs, packed)):
        daq_idx = daq_indices[i]
        daq_mode = 0x10 if eff_ts[i] else 0x00   # bit4 = timestamp enable
        master.set_daq_list_mode(daq_idx, cfg.event, daq_mode, cfg.prescaler, cfg.priority)
        first_pid = master.start_stop_daq_list(mode=2, daq=daq_idx)

        for odt_idx, odt in enumerate(odts):
            has_ts = (odt_idx == 0 and eff_ts[i])
            cur = fmt.data_start(has_ts)   # sau header (+ timestamp nếu có)

            layouts: list[OdtSignalLayout] = []
            for sig in odt:
                layouts.append(OdtSignalLayout(signal=sig, frame_offset=cur))
                cur += sig.size

            pid_table[make_key(fmt, daq_idx, odt_idx, first_pid)] = PidEntry(
                daq_list=daq_idx,
                odt_index=odt_idx,
                has_timestamp=has_ts,
                signals=layouts,
            )
```

- [x] **Step 5: Sửa `configure_daq_predefined`**

Thêm hàm kiểm tra ngay trước `def configure_daq_predefined(`:

```python
def _check_predefined_offsets(pl: PredefinedDaqList, fmt: DtoFormat, ts_on: bool) -> None:
    """Mọi `frame_offset` phải nằm sau header (và timestamp ở ODT 0) — nếu
    không, decode sẽ sai thầm lặng khi ECU có header dài hơn caller giả định."""
    for odt_idx, layouts in enumerate(pl.odts):
        start = fmt.data_start(odt_idx == 0 and ts_on)
        for layout in layouts:
            if layout.frame_offset < start:
                raise ValueError(
                    f"DAQ list {pl.daq} ODT {odt_idx}: signal '{layout.signal.name}' có "
                    f"frame_offset={layout.frame_offset} < {start} — chồng lên header "
                    f"{fmt.header_len}B/timestamp của DTO"
                )
```

Trong thân `configure_daq_predefined`, đổi phần đầu vòng lặp. Đoạn cũ:

```python
    pid_table: dict[int, PidEntry] = {}

    for pl in lists:
        info = master.get_daq_list_info(pl.daq)
```

thành:

```python
    fmt = DtoFormat.from_slave_caps(master.caps)
    # Kiểm tra offset của MỌI list trước khi gửi bất kỳ lệnh nào
    for pl in lists:
        _check_predefined_offsets(pl, fmt, effective_timestamp(pl.timestamp, fmt))

    pid_table: dict[DtoKey, PidEntry] = {}

    for pl in lists:
        ts_on = effective_timestamp(pl.timestamp, fmt)
        info = master.get_daq_list_info(pl.daq)
```

Đổi dòng `daq_mode = 0x10 if pl.timestamp else 0x00` thành `daq_mode = 0x10 if ts_on else 0x00`, và vòng xây bảng:

```python
        for odt_idx, layouts in enumerate(pl.odts):
            pid_table[first_pid + odt_idx] = PidEntry(
                daq_list=pl.daq,
                odt_index=odt_idx,
                has_timestamp=(odt_idx == 0 and pl.timestamp),
                signals=layouts,
            )
```

thành:

```python
        for odt_idx, layouts in enumerate(pl.odts):
            pid_table[make_key(fmt, pl.daq, odt_idx, first_pid)] = PidEntry(
                daq_list=pl.daq,
                odt_index=odt_idx,
                has_timestamp=(odt_idx == 0 and ts_on),
                signals=layouts,
            )
```

- [x] **Step 6: Sửa `RealSession`**

Trong `src/xcptool/session/real.py`:

Khối import `..master.daq`:

```python
from ..master.daq import (
    DaqListConfig,
    DaqSignal as _MasterDaqSignal,
    PidEntry,
    SamplePoint as _MasterSamplePoint,
    TimestampAccumulator,
    configure_daq,
    decode_dto,
    stop_daq as _master_stop_daq,
)
```

thành:

```python
from ..master.daq import (
    DaqListConfig,
    DaqSignal as _MasterDaqSignal,
    DtoFormat,
    DtoKey,
    PidEntry,
    SamplePoint as _MasterSamplePoint,
    TimestampAccumulator,
    configure_daq,
    decode_dto,
    stop_daq as _master_stop_daq,
)
```

Trong `__init__`, hai dòng:

```python
        self._daq_pid_table: dict[int, PidEntry] | None = None
        self._daq_ts_accum: TimestampAccumulator = TimestampAccumulator()
```

thành:

```python
        self._daq_pid_table: dict[DtoKey, PidEntry] | None = None
        self._daq_fmt: DtoFormat = DtoFormat()
        self._daq_ts_accum: TimestampAccumulator = TimestampAccumulator()
```

Trong `start_daq`, đoạn:

```python
        master = self._require_master()
        caps = master.caps
        byte_order = caps.byte_order if caps else "little"

        # Reset trước khi configure để không trộn mẫu từ phiên cũ
        master.set_daq_callback(None)
        self._daq_pid_table = None
        with self._daq_lock:
            self._daq_ring.clear()
        self._daq_ts_accum = TimestampAccumulator(byte_order=byte_order)
```

thành:

```python
        master = self._require_master()
        fmt = DtoFormat.from_slave_caps(master.caps)

        # Reset trước khi configure để không trộn mẫu từ phiên cũ
        master.set_daq_callback(None)
        self._daq_pid_table = None
        with self._daq_lock:
            self._daq_ring.clear()
        self._daq_fmt = fmt
        self._daq_ts_accum = TimestampAccumulator.from_format(fmt)
```

Trong `_on_daq_frame`, dòng `samples = decode_dto(frame, pid_table, self._daq_ts_accum)` thành:

```python
        samples = decode_dto(frame, pid_table, self._daq_ts_accum, self._daq_fmt)
```

- [x] **Step 7: Chạy test, xác nhận xanh**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_daq_dto_formats.py tests/integration/test_daq.py tests/integration/test_session_daq.py -v`
Expected: tất cả PASS. Nếu một test trong `test_daq_dto_formats.py` chập chờn vì thời gian (thiếu sample trong 2 s), chạy lại riêng test đó 3 lần trước khi kết luận lỗi thật.

- [x] **Step 8: Commit**

```bash
git add src/xcptool/master/daq.py src/xcptool/session/real.py tests/integration/test_daq_dto_formats.py
git diff --cached --name-only
git commit -m "feat(xcptool): configure_daq/predefined/RealSession dùng DtoFormat; guard offset predefined" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Export, tài liệu và hồi quy toàn bộ

**Files:**
- Modify: `src/xcptool/master/__init__.py`
- Modify: `src/xcptool/master/daq.py` (docstring đầu file, `OdtSignalLayout`, `PredefinedDaqList`)
- Modify: `ARCHITECTURE.md` (mục 4.4)

**Interfaces:**
- Consumes: mọi thứ ở Task 1–6.
- Produces: không có API mới; chỉ export và tài liệu.

- [x] **Step 1: Export tên mới từ `master/__init__.py`**

Thay khối import từ `.daq` và `__all__`:

```python
from .daq import (
    DaqListConfig, DaqSignal, DtoFormat, OdtSignalLayout, PidEntry,
    SamplePoint, TimestampAccumulator,
    configure_daq, decode_dto, effective_timestamp, make_key, pack_odts, stop_daq,
)
```

và trong `__all__` thêm `"DtoFormat", "make_key", "effective_timestamp",` (cùng nhóm với `"DaqSignal", "pack_odts",`).

- [x] **Step 2: Cập nhật docstring trong `daq.py`**

Docstring đầu file — thêm dòng `D4f` vào danh sách:

```python
"""DAQ engine — packing, allocation, DTO decoding.

D4a: DaqSignal + pack_odts()
D4b: DaqListConfig, OdtSignalLayout, PidEntry, configure_daq, stop_daq
D4c: SamplePoint, TimestampAccumulator, decode_dto
D4f: DtoFormat — layout DTO (kiểu identification field, timestamp, overrun) suy ra
     từ caps của ECU; pack_odts/configure_daq/decode_dto/TimestampAccumulator
     đều nhận DtoFormat thay vì giả định header 1 byte + timestamp 4 byte/10 ns.

Nguyên tắc: không import can, không import PySide6, không import ui/transport.
"""
```

`OdtSignalLayout` — đổi dòng `frame_offset: byte offset tính từ đầu frame (byte 0 = PID).` thành:

```python
    frame_offset: byte offset tính từ đầu frame (byte 0 = byte đầu của header DTO;
    dữ liệu bắt đầu ở `DtoFormat.data_start(has_timestamp)`).
```

`PredefinedDaqList` — trong docstring, đổi đoạn `với \`frame_offset\` đã tính sẵn (byte 0 = PID, cộng thêm timestamp nếu có — xem \`OdtSignalLayout\`).` thành:

```python
    với `frame_offset` đã tính sẵn: tuyệt đối từ đầu frame, phải ≥
    `DtoFormat.data_start(has_timestamp)` — header dài 1–4 byte tuỳ kiểu
    identification field của ECU, cộng timestamp nếu có ở ODT 0
    (`configure_daq_predefined` báo `ValueError` nếu offset chồng lên).
```

- [x] **Step 3: Cập nhật `ARCHITECTURE.md` mục 4.4**

Sửa đúng các dòng sau (copy nguyên văn chuỗi cũ để tìm):

| Chuỗi cũ | Chuỗi mới |
|---|---|
| `RS->>DAQ: pack_odts(daq_lists, max_dto=8, timestamp=True)` | `RS->>DAQ: DtoFormat.from_slave_caps(caps) → pack_odts(daq_lists, max_dto, timestamp, fmt)` |
| `Note over DAQ: ODT 0: budget 3B (do trừ 1B PID + 4B TS)\nODT 1+: budget 7B (First-Fit-Decreasing)` | `Note over DAQ: Ngân sách ODT tính từ DtoFormat: header 1–4B (kiểu identification field từ DAQ_KEY_BYTE) và timestamp 0/1/2/4B\nVí dụ CAN 8B, header 1B, TS 4B: ODT 0 = 3B, ODT 1+ = 7B (First-Fit-Decreasing)` |
| `DAQ->>DAQ: Dựng bảng tra cứu phẳng O(1): pid -> (signals, offsets, datatypes)` | `DAQ->>DAQ: Dựng bảng tra cứu phẳng O(1): khoá = PID (kiểu header 0) hoặc (DAQ list, ODT) (kiểu 1-3) -> (signals, offsets, datatypes)` |
| `ECU->>RX: DTO Frame (PID + TS + Payload)` | `ECU->>RX: DTO Frame (Header + TS + Payload)` |
| `DAQ->>DAQ: Trừ cờ overrun, giải mã timestamp qua TimestampAccumulator\n(tự cộng 2^32 khi tràn chu kỳ 42.9s)` | `DAQ->>DAQ: Tách header theo DtoFormat, trừ cờ overrun (nếu ECU báo ở MSB của PID), giải mã timestamp qua TimestampAccumulator\n(tự cộng 2^độ_rộng khi tràn chu kỳ)` |

Sau khi sửa, tìm trong `ARCHITECTURE.md` mọi chỗ còn ghi cứng "1B PID + 4B TS" cho đường DAQ chung: `grep -n "4B TS\|PID + TS" ARCHITECTURE.md` — còn dòng nào mô tả hành vi hiện tại (không phải lịch sử) thì sửa tương tự.

- [x] **Step 4: Chạy hồi quy toàn bộ**

Run (unit + integration + ranh giới kiến trúc):
`.venv/Scripts/python.exe -m pytest tests/unit tests/integration tests/test_boundaries.py -q -p no:cacheprovider`
Expected: toàn bộ PASS. Số test phải ≥ 352 (baseline) + test mới; **không test cũ nào bị sửa hay bỏ**. `tests/test_boundaries.py` xanh (xác nhận `DtoFormat` ở `master/` và `DaqCaps` ở `session/api.py` không vi phạm ranh giới).

Run (UI, liên quan DAQ/`DaqCaps`):
`QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest tests/ui/test_fake_session.py tests/ui/test_daq_lifecycle.py tests/ui/test_measurement_view.py tests/ui/test_connect_flow.py -q -p no:cacheprovider`
Expected: PASS. Nếu môi trường không chạy được UI headless, ghi rõ trong báo cáo và bỏ qua bước này (không coi là lỗi của thay đổi).

- [x] **Step 5: Kiểm tra tay bằng frame Part 5**

Run:

```bash
.venv/Scripts/python.exe - <<'EOF'
from xcptool.master.daq import DtoFormat, DaqSignal, OdtSignalLayout, PidEntry, TimestampAccumulator, decode_dto
fmt = DtoFormat(id_type=1, ts_size=2, unit_ns=1_000_000, ticks=10, overload="none")
sig = DaqSignal("a", 0, 0, 1, "UINT8")
table = {(3, 0): PidEntry(3, 0, True, [OdtSignalLayout(sig, 4)])}
print(decode_dto(bytes.fromhex("0003 0A00 55 000000".replace(" ", "")), table, TimestampAccumulator.from_format(fmt), fmt))
EOF
```

Expected: in ra một `SamplePoint(name='a', timestamp_ns=1000000, value_raw=b'U', datatype='UINT8')` (raw timestamp 10 tick, unit 1 ms, ticks 10 → 1 ms).

- [x] **Step 6: Commit**

```bash
git add src/xcptool/master/__init__.py src/xcptool/master/daq.py ARCHITECTURE.md
git diff --cached --name-only
git commit -m "docs(xcptool): DtoFormat — export, docstring và ARCHITECTURE mục 4.4" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Self-Review (đã chạy)

**1. Spec coverage**

| Yêu cầu spec | Task |
|---|---|
| §5.1 `DaqCaps` 3 trường + sửa `timestamp_supported`/`timestamp_size` | 1 |
| §5.1 `DtoFormat`, `from_caps`, `from_slave_caps`, `make_key`, `effective_timestamp` | 2 |
| §5.2 `decode_dto` 4 kiểu, overrun theo caps, timestamp theo size | 3 |
| §5.2 `TimestampAccumulator` width/unit/ticks + ngưỡng nửa chu kỳ | 2 |
| §5.3 `pack_odts` ngân sách + `ValueError` | 4 |
| §5.3 `configure_daq`, `configure_daq_predefined` + guard, `RealSession` | 6 |
| §5.4 fakeslave (caps, header, tick, `ERR_CMD_SYNTAX` khi fixed) | 5 |
| §5.5 xử lý lỗi (decode không raise; unit/ticks không hợp lệ → 0) | 2, 3 |
| §7 kế hoạch test 1–8 | 1–7 |
| §8 tài liệu | 7 |

**2. Quét placeholder:** không có "TBD/TODO/tương tự Task N"; mọi bước code có mã đầy đủ.

**3. Nhất quán kiểu/tên:** `DtoFormat(id_type, byte_order, ts_size, unit_ns, ticks, overload, ts_always)`, `.header_len`, `.data_start(has_timestamp)`, `from_caps`, `from_slave_caps`, `make_key(fmt, daq, odt, first_pid)`, `effective_timestamp(requested, fmt)`, `TimestampAccumulator.from_format(fmt)`, `DtoKey` — cùng tên ở Task 2, 3, 4, 6, 7. `decode_dto(frame, pid_table, ts_accum, fmt=None)` nhất quán giữa Task 3, 6. `_write_and_start(..., fmt, eff_ts)` khớp lời gọi trong `configure_daq`. Tên trường `SlaveConfig` (`id_field_type`, `overload`, `timestamp_supported`, `timestamp_fixed`) khớp giữa Task 5 và Task 6. Lưu ý kỹ thuật: dataclass cấu hình của fakeslave tên là `SlaveConfig` (không phải `FakeSlaveConfig` như spec nói lỏng).

**4. Review Focus:** 5 dòng ở đầu đều có test gắn với task sở hữu code (Task 2, 3, 6).

**Quyết định còn lại cho người thực thi (đã chốt trong spec mục 6, không hỏi lại):** hạ timestamp im lặng khi ECU không hỗ trợ; rollover theo nửa chu kỳ; giữ `frame_offset` tuyệt đối của predefined kèm guard.
