# xcptool: decode và đóng gói DTO theo caps của ECU (generic)

- Ngày: 2026-09-30
- Phạm vi code: `xcptool/` (không đụng `driver/`)
- Trạng thái: chờ người dùng duyệt spec
- Tham chiếu chuẩn: ASAM MCD-1 XCP v1.0 Part 2 (mục 1.1.2 Identification Field, 1.1.2.2 Timestamp Field, `GET_DAQ_PROCESSOR_INFO`, `GET_DAQ_RESOLUTION_INFO`), Part 5 (mục 1.3.1, ví dụ frame). Bản PDF: `Doc/Specification/Version 1.0/`.

## 1. Mục tiêu

xcptool được dùng để test nhiều loại ECU, không chỉ driver trong repo này. Đường DAQ hiện còn nhiều giả định đúng riêng với driver đó, trái với nguyên tắc trong `ARCHITECTURE.md` (không hardcode MAX_DTO, byte order, đơn vị độ phân giải timestamp). Mục tiêu: **layout của gói DTO và cách đọc timestamp được suy ra hoàn toàn từ caps mà ECU báo**, không hardcode.

Tiêu chí thành công:

1. ECU báo `DAQ_KEY_BYTE` với bất kỳ kiểu identification field nào (0–3) thì xcptool cấu hình DAQ và decode đúng mẫu.
2. Timestamp dùng đúng size (1/2/4 byte), đơn vị, `TIMESTAMP_TICKS` và độ rộng rollover mà ECU báo.
3. Overrun được xử lý theo cách ECU báo, không còn mask cứng bit 7 của PID.
4. Toàn bộ test hiện có vẫn xanh, không phải sửa, kể cả `tests/test_boundaries.py`.
5. Các frame ví dụ trong Part 5 (`FF 11 00 00 01 00 00 40`, `FF 02 FD xx xx 62 0A 00`) cho ra `DaqCaps` đúng như giải thích trong spec.

## 2. Hiện trạng (những gì đang hardcode theo driver)

| Giả định hiện tại | Vị trí | Hệ quả với ECU khác |
|---|---|---|
| Byte 0 của DTO luôn là PID tuyệt đối; bảng tra khoá theo `PID` | `master/daq.py` (`decode_dto`, `_write_and_start`) | Sai hoàn toàn với kiểu header 1–3 |
| `DAQ_KEY_BYTE` (`proc[7]`) bị bỏ | `master/core.py` `_probe_daq_caps` | Không biết kiểu header |
| Timestamp luôn 4 byte (`frame[1:5]`), rollover 2^32, `× 10 ns` | `TimestampAccumulator`, `decode_dto` | Sai với timestamp 1/2 byte, đơn vị khác, ticks ≠ 1 |
| Ngân sách ODT trừ cứng "1 B PID + 4 B TS" | `pack_odts` | Đóng gói sai khi header/timestamp khác |
| `timestamp_supported = ts_size != 0` (không xét bit `TIMESTAMP_SUPPORTED`) | `_probe_daq_caps` | ECU không hỗ trợ timestamp nhưng trả `TIMESTAMP_MODE` rác bị coi là có |
| Mask `PID & 0x7F` bất kể cách báo overrun | `decode_dto` | Sai khi ECU không báo overrun bằng MSB của PID |
| Bit mode timestamp `0x10` luôn đặt theo `cfg.timestamp`, bỏ qua `TIMESTAMP_FIXED`/không hỗ trợ | `_write_and_start` | Lỗi `ERR_CMD_SYNTAX` hoặc layout lệch |
| `frame_offset` của list predefined do caller tự tính, ngầm giả định header 1 byte | `configure_daq_predefined` | Decode sai thầm lặng |

## 3. Ngoài phạm vi (không làm trong spec này)

- Ràng buộc phía cấu hình: `MAX_ODT_ENTRY_SIZE`, `GRANULARITY_ODT_ENTRY_SIZE`, address granularity, prescaler. Đây là spec riêng sau này.
- `PID_OFF` (DTO không có identification field), STIM.
- Decode gói event `EV_DAQ_OVERLOAD` (kiểu overrun `event` chỉ được "không mask").
- Đưa cờ overrun lên `SamplePoint`.
- Ràng buộc `Address_Extension_DAQ/ODT` của `DAQ_KEY_BYTE`.

## 4. Kiểu identification field (tham chiếu)

Bit 7–6 của `DAQ_KEY_BYTE` (quy ước số 0–3 theo giá trị hai bit):

| Số | Bit 7–6 | Header DTO | `header_len` | Khoá tra bảng |
|---|---|---|---|---|
| 0 | `00` Absolute ODT number | `PID` | 1 | `PID` |
| 1 | `01` Relative ODT + DAQ (BYTE) | `ODT, DAQ` | 2 | `(DAQ, ODT)` |
| 2 | `10` Relative ODT + DAQ (WORD) | `ODT, DAQ_lo, DAQ_hi` | 3 | `(DAQ, ODT)` |
| 3 | `11` Relative ODT + DAQ (WORD, aligned) | `ODT, FILL, DAQ_lo, DAQ_hi` | 4 | `(DAQ, ODT)` |

Sau header: nếu là ODT đầu của DAQ list và list có timestamp thì đến timestamp, rồi đến dữ liệu. WORD theo byte order của slave. Byte FILL không mang dữ liệu.

## 5. Thiết kế

### 5.1 Mô hình dữ liệu

**`DaqCaps`** (`session/api.py`, stdlib thuần) thêm 3 trường, cuối dataclass, đều có mặc định (để `session/fake.py` và test hiện có không phải sửa):

| Trường | Kiểu | Nguồn | Mặc định |
|---|---|---|---|
| `id_field_type` | `int` (0–3) | `DAQ_KEY_BYTE` bit 7–6 | `0` |
| `overload` | `"none" \| "pid_msb" \| "event"` | `DAQ_PROPERTIES` bit 7–6: `00`→`none`, `01`→`pid_msb`, `10`→`event`, `11` (không hợp lệ)→`none` | `"pid_msb"` |
| `timestamp_fixed` | `bool` | `TIMESTAMP_MODE` bit 3 | `False` |

Sửa ngữ nghĩa trong `_probe_daq_caps` (`master/core.py`):

- `timestamp_supported = bool(DAQ_PROPERTIES & 0x10) and size in (1, 2, 4)`, với `size = TIMESTAMP_MODE & 0x07`.
- `timestamp_size = size` nếu `timestamp_supported`, ngược lại `0` (size `3`, `>4` hoặc bit 4 = 0 đều coi là không có timestamp).
- `timestamp_fixed = timestamp_supported and bool(TIMESTAMP_MODE & 0x08)`: `TIMESTAMP_MODE` chỉ hợp lệ khi ECU báo hỗ trợ timestamp (bổ sung sau review cuối).
- Các trường hiện có (`max_daq`, `max_event_channel`, `min_daq`, `dynamic_daq`, `timestamp_unit_ns`, `timestamp_ticks`, `pid_off_supported`, `granularity_odt_entry_daq`, `max_odt_entry_size_daq`) giữ nguyên cách decode.

**`DtoFormat`** (`master/daq.py`, dataclass bất biến) là nguồn sự thật duy nhất về layout DTO:

```
DtoFormat(
    id_type: int = 0,
    byte_order: Literal["little", "big"] = "little",
    ts_size: int = 4,          # 0 = không có timestamp
    unit_ns: int = 10,         # 0 = đơn vị không hợp lệ
    ticks: int = 1,            # 0 = không hợp lệ
    overload: Literal["none", "pid_msb", "event"] = "pid_msb",
    ts_always: bool = False,   # TIMESTAMP_FIXED
)
```

- `header_len`: property, `(1, 2, 3, 4)[id_type]`.
- `data_start(has_timestamp: bool) -> int`: `header_len + (ts_size if has_timestamp else 0)`.
- `DtoFormat.from_caps(daq_caps: DaqCaps | None, byte_order="little")`: `None` trả `DtoFormat(byte_order=byte_order)` (đúng hành vi cũ). Ngược lại lấy `id_type`, `ts_size = daq_caps.timestamp_size`, `unit_ns = daq_caps.timestamp_unit_ns`, `ticks = daq_caps.timestamp_ticks`, `overload`, `ts_always = daq_caps.timestamp_fixed`.
- `DtoFormat.from_slave_caps(caps: SlaveCaps | None)`: hàm **duy nhất** dựng `DtoFormat`; gọi `from_caps(caps.daq, caps.byte_order)` (hoặc mặc định nếu `caps is None`). `configure_daq` và `RealSession` đều dùng hàm này nên không thể lệch nhau.

Hai hàm module-level:

- `make_key(fmt, daq, odt, first_pid) -> int | tuple[int, int]`: kiểu 0 → `first_pid + odt`; kiểu 1–3 → `(daq, odt)`, bỏ qua `first_pid`.
- `effective_timestamp(requested: bool, fmt) -> bool`: `fmt.ts_size == 0` → `False` (kiểm tra trước, vì `TIMESTAMP_FIXED` không có nghĩa khi không có timestamp); `fmt.ts_always` → `True`; ngược lại `requested`.

Bảng tra: `DtoTable = dict[int | tuple[int, int], PidEntry]`. Hàng chục test hiện có truyền `dict[int, PidEntry]` vào `decode_dto`, nên với kiểu 0 khoá vẫn là `int`. Chỉ `daq.py` biết hai dạng khoá; `RealSession` coi bảng là đối tượng mờ.

### 5.2 Decode

`decode_dto(frame, pid_table, ts_accum, fmt=DtoFormat()) -> list[SamplePoint]`. Đường này chạy trên RX thread: **không raise**. Frame rỗng, quá ngắn (ngắn hơn `header_len`) hoặc khoá không có trong bảng thì trả `[]`.

1. Tách header theo `fmt.id_type` (bảng mục 4). WORD đọc bằng `fmt.byte_order`; byte FILL bị bỏ qua.
2. Byte đầu: nếu `fmt.overload == "pid_msb"` thì mask bit 7 (`& 0x7F`) và coi bit đó là cờ overrun; ngược lại dùng đủ 8 bit.
3. Khoá = `make_key`-tương đương: kiểu 0 → `pid`; kiểu 1–3 → `(daq, odt)`.
4. Timestamp (chỉ khi `entry.has_timestamp`): đọc `frame[header_len : header_len + ts_size]` bằng `ts_accum.byte_order`, đổi sang ns qua `ts_accum.to_ns(raw)`. Frame ngắn hơn `header_len + ts_size` thì `ts_ns = 0` (như hiện nay).
5. Signal: `frame_offset` giữ nguyên là tuyệt đối từ đầu frame; chỉ signal nằm gọn trong frame mới được decode.

Cờ overrun hiện bị bỏ (không thay đổi).

**`TimestampAccumulator(byte_order="little", width_bits=32, unit_ns=10, ticks=1)`**: mặc định giữ hành vi cũ. Thêm `TimestampAccumulator.from_format(fmt)` (lấy `byte_order`, `width_bits = 8 × ts_size`, `unit_ns`, `ticks`).

- `to_ns(raw) = update(raw) * unit_ns // ticks` (nếu `unit_ns == 0` hoặc `ticks == 0` thì trả `0`). Công thức theo spec: timestamp "tăng `TIMESTAMP_TICKS` cho mỗi `unit`". Ví dụ Part 5: unit 1 ms, ticks 10, raw 10 → 1 ms (100 µs mỗi tick).
- Rollover: chỉ khi `last − raw > 2^(width_bits − 1)` (tụt quá nửa chu kỳ) thì `epoch += 2^width_bits`. Bước lùi nhỏ hơn được coi là đến lệch thứ tự: không đổi epoch, không ép đơn điệu. Test hiện có (rollover từ `0xFFFF_FF00` về `0x100`) vẫn đúng. Lý do: với timestamp hẹp (8/16 bit) hoặc nhiều DAQ list dùng chung accumulator, `raw < last` đơn thuần nhầm bước lùi nhỏ thành rollover.
- Mỗi DAQ list có chuỗi theo dõi riêng (`to_ns(raw, stream=daq_list)`; `stream=None` là một chuỗi duy nhất như trước): frame của cùng một list đến đúng thứ tự, còn frame của các list khác nhau có thể đến lệch nhau ngay tại ranh giới rollover mà không được làm lệch cả chu kỳ về sau (bổ sung sau review cuối; quy tắc đối xứng theo giá trị không dùng được vì mâu thuẫn test cũ `test_ts_accum_two_rollovers`).
- Giới hạn cần ghi trong docstring: hai timestamp liên tiếp của cùng một chuỗi phải cách nhau dưới nửa chu kỳ, nếu không không phân biệt được bước tiến và bước lùi; timestamp 1 byte quay vòng rất nhanh nên ít hữu dụng.

### 5.3 Đóng gói và cấu hình DAQ

**`pack_odts(signals, timestamp_on, max_dto=8, *, fmt=None)`** (`fmt=None` → `DtoFormat()`):

- Ngân sách ODT đầu: `max_dto − header_len − (ts_size nếu timestamp_on)`. Các ODT còn lại: `max_dto − header_len`. Mặc định cho ra 3 và 7 như hiện nay.
- `ValueError` kèm thông báo rõ khi `max_dto − header_len ≤ 0`, hoặc khi `timestamp_on` và `header_len + ts_size > max_dto`. Ngân sách ODT đầu bằng 0 là hợp lệ (ODT 0 rỗng như hiện nay), ví dụ kiểu 3 cộng timestamp 4 byte trên DTO 8 byte.

**`configure_daq`:**

- `fmt = DtoFormat.from_slave_caps(master.caps)`.
- `eff = [effective_timestamp(cfg.timestamp, fmt) for cfg in configs]`; `eff[i]` quyết định bit `0x10` của `SET_DAQ_LIST_MODE`, ngân sách ODT, offset và `has_timestamp` của ODT 0.
- Nếu `fmt.ts_size == 0` (ECU không hỗ trợ) mà `cfg.timestamp = True`: hạ xuống tắt im lặng, kết quả như `timestamp=False` hiện nay (`timestamp_ns = 0`).
- `frame_offset` của signal = `data_start(has_timestamp của ODT) + vị trí trong ODT`.
- Khoá bảng: `make_key(fmt, daq_indices[i], odt_idx, first_pid)`. Với kiểu 1–3, số DAQ dùng là list **vật lý** (`daq_indices`, kể cả khi ECU static chọn list không liền kề), còn `first_pid` bị bỏ qua.
- Kiểu trả về vẫn là `dict` (chữ ký không đổi).
- `_write_and_start` (hàm nội bộ) nhận `fmt` và `eff` thay cho `ts_size`.

**`configure_daq_predefined`:**

- Dùng cùng `fmt` và `make_key`; bit mode `0x10` theo `effective_timestamp(pl.timestamp, fmt)`.
- `OdtSignalLayout.frame_offset` giữ nguyên nghĩa tuyệt đối từ đầu frame (tương thích). Thêm guard: với mỗi ODT, mọi `frame_offset` phải `≥ data_start(has_timestamp của ODT)`; nếu không thì `ValueError("offset chồng lên header hoặc timestamp …")`. Đây là kiểm tra rẻ chặn decode sai thầm lặng khi header dài hơn giả định của caller.

**`RealSession`** (`session/real.py`): `start_daq` dựng `self._daq_fmt = DtoFormat.from_slave_caps(master.caps)` và `TimestampAccumulator.from_format(fmt)`; `_on_daq_frame` gọi `decode_dto(frame, table, accum, self._daq_fmt)`. `master/__init__.py` export `DtoFormat` nếu cần.

### 5.4 Fakeslave (`devtools/fakeslave.py`)

`FakeSlaveConfig` thêm: `id_field_type` (0–3), `overload` (`none`/`pid_msb`/`event`), `timestamp_fixed`, `timestamp_supported`. Giữ `timestamp_size`, `timestamp_unit_code`, `timestamp_ticks` hiện có.

- `GET_DAQ_PROCESSOR_INFO`: đặt bit 4 (timestamp) khi hỗ trợ, bit 7–6 theo `overload`, `DAQ_KEY_BYTE = id_field_type << 6`. (Hiện fakeslave không bao giờ đặt bit 4, tức chính nó lệch spec.)
- `GET_DAQ_RESOLUTION_INFO`: thêm bit `TIMESTAMP_FIXED`.
- `SET_DAQ_LIST_MODE`: nếu `timestamp_fixed` mà master tắt timestamp thì trả `ERR_CMD_SYNTAX`.
- Phát DTO: dựng header theo kiểu (kiểu 1–3 dùng số DAQ list vật lý; kiểu 3 có FILL), timestamp `ts_size` byte với số tick = `elapsed_ns × ticks / unit_ns` cắt theo độ rộng.

### 5.5 Xử lý lỗi

- Đường decode (RX thread): không raise; dữ liệu lạ → `[]` hoặc `ts_ns = 0`.
- Đường cấu hình: `ValueError` cho tổ hợp không đóng gói được (header/timestamp quá lớn so với `max_dto`, guard predefined); lỗi ECU vẫn theo cây ngoại lệ hiện có (`SlaveError`, `UnsupportedByEcuError`, …).
- Unit/ticks không hợp lệ (mã unit ngoài 0–9, `ticks = 0`): timestamp vẫn được bỏ qua đúng số byte, `timestamp_ns = 0`.

## 6. Quyết định có thể đảo

1. Hạ timestamp xuống tắt im lặng khi ECU không hỗ trợ (thay vì raise `UnsupportedByEcuError`).
2. Rollover chỉ khi tụt quá nửa chu kỳ.
3. Giữ `frame_offset` tuyệt đối của predefined kèm guard (thay vì đổi sang offset tương đối so với `data_start`).

## 7. Kế hoạch test (TDD: test đỏ trước, rồi mới sửa code)

1. **Probe caps** (`tests/unit/`, file mới): frame Part 5 (`FF 11 00 00 01 00 00 40` + `FF 02 FD .. 62 0A 00` → kiểu 1, timestamp 2 byte, 1 ms, ticks 10, dynamic); dạng driver (`FF 51 …` + `0x14` → kiểu 0, `pid_msb`, 4 byte, 10 ns); key byte `0x00/0x40/0x80/0xC0`; overload `00/01/10/11`; cờ fixed; bit 4 = 0 với `TIMESTAMP_MODE` rác → `timestamp_supported = False`, `timestamp_size = 0`.
2. **`DtoFormat`**: `from_caps` (header theo kiểu, `ts_size = 0`, `caps.daq is None`), `data_start`, `make_key`, `effective_timestamp` (fixed / không hỗ trợ / bình thường).
3. **`TimestampAccumulator`**: độ rộng 8/16/32, unit và ticks (Part 5: raw 10 → 1 ms), rollover theo nửa chu kỳ, bước lùi nhỏ không đổi epoch. Test cũ giữ nguyên.
4. **`decode_dto`** (mở rộng `tests/unit/test_daq_decoder.py`): 4 kiểu header có/không timestamp, timestamp chỉ ở ODT 0, mask overrun theo từng chế độ, frame ngắn, khoá lạ, byte order big/little cho DAQ WORD, FILL bị bỏ qua.
5. **`pack_odts`** (mở rộng `tests/unit/test_daq_packing.py`): ngân sách theo header/timestamp, các trường hợp `ValueError`, mặc định không đổi.
6. **Predefined**: guard `frame_offset < data_start`.
7. **Tích hợp** qua fakeslave trên virtual bus (`tests/integration/`, file mới): `configure_daq` → DTO → `decode_dto` → giá trị khớp bộ nhớ; tham số hoá `id_field_type` 0–3 × `ts_size` 0/1/2/4; `timestamp_fixed`; ECU static với list không liền kề dùng kiểu 1–3 (xác nhận dùng số list vật lý).
8. **Hồi quy**: chạy toàn bộ suite hiện có, kể cả `tests/test_boundaries.py` (`DtoFormat` ở `master/`, `DaqCaps` ở `session/api.py` thuần stdlib, nên không vi phạm ranh giới).

## 8. Tài liệu cần cập nhật

- `ARCHITECTURE.md` mục 4.4: bỏ mô tả cố định "1B PID + 4B TS", mô tả `DtoFormat`.
- Docstring đầu `master/daq.py`, `DaqCaps` (hiện ghi "Ngoài phạm vi M1/M2"), `OdtSignalLayout`, `TimestampAccumulator`, `PredefinedDaqList`.
- `DEV_PLAN.md` nếu có mục liên quan.

## 9. Rủi ro còn lại

- Driver trong repo chỉ có kiểu 0. Kiểu 1–3 không kiểm chứng được với ECU thật, và fakeslave dựa trên cùng cách hiểu spec. Test dựa thêm vào văn bản spec và frame ví dụ Part 5, nhưng khi có ECU thật dùng kiểu 1–3 thì cần chạy thử lại.
- Kiểu overrun `event` mới chỉ "không mask", chưa decode gói EV.
- Hạ timestamp im lặng có thể che việc ECU không hỗ trợ timestamp nếu người dùng không để ý `timestamp_ns = 0`.

## 10. Việc tiếp theo (tách riêng)

Spec về ràng buộc phía cấu hình DAQ: `MAX_ODT_ENTRY_SIZE`, granularity, address granularity, prescaler, `TIMESTAMP_FIXED`/`PID_OFF` khi cấu hình.
