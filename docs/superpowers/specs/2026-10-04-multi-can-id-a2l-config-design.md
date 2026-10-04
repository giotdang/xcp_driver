# xcptool — Nhận DAQ trên nhiều CAN ID và cấu hình CAN từ A2L

Ngày: 2026-10-04 · Trạng thái: **bản nháp chờ duyệt** · Phạm vi: phần 1 + phần 2
(phần 3 — `GET_DAQ_ID`/`SET_DAQ_ID` cho `VARIABLE` — nằm ngoài spec này).

## 1. Bối cảnh và mục tiêu

Quan sát từ các ECU thật: thông tin CAN (baudrate, CAN classic/FD, CAN ID) nằm
sẵn trong block `XCP_ON_CAN` của A2L, và một XCP slave có thể phát trên **nhiều
CAN ID**: một ID cho response/event (vd 0x6A1), mỗi DAQ list một ID riêng (vd
0x6A2 cho list 0, 0x6A3 cho list 1).

xcptool hiện chỉ có một cặp `cro_id`/`dto_id` do người dùng nhập tay. Hậu quả:

- ECU phát DAQ trên ID riêng → frame bị **bỏ im lặng** ở hai tầng:
  bộ lọc phần cứng (`transport/pycan.py:51`, một filter duy nhất = `dto_id`) và
  `XcpMaster._on_frame` (`master/core.py:177`, `can_id != dto_id → return`).
- Người dùng phải đọc A2L rồi gõ lại từng số vào dialog Connect.

**Mục tiêu**

1. (Phần 1) Master nhận và giải mã DTO từ tập CAN ID tuỳ ý: `dto_id` cho
   response/event + mỗi DAQ list có thể có ID riêng.
2. (Phần 2) Đọc cấu hình CAN từ A2L và áp vào kết nối bằng một checkbox trong
   dialog Connect.

**Tiêu chí thành công**

- Với `daq_can_ids` rỗng, hành vi **y hệt hiện tại** (không hồi quy).
- Fakeslave phát DTO của list 0/1 trên hai ID riêng → `drain_daq()` ra đủ mẫu của
  cả hai list; frame lạ vẫn bị bỏ.
- Tích "Config CAN from A2L" → Connect dùng đúng ID/bitrate/FD của A2L mà người
  dùng không gõ gì; bỏ tích → giá trị nhập tay còn nguyên.

**Không làm (YAGNI)**: `GET_DAQ_ID`/`SET_DAQ_ID`, ô nhập tay `daq_can_ids` trong
dialog, đổi `t1_timeout_s` theo A2L, tuỳ chọn CLI `--can-from-a2l`, đọc
`CAN_ID_BROADCAST` (chưa có luồng nào dùng), STIM.

## 2. Điều chưa xác nhận (đọc trước khi duyệt)

Repo không có A2L thật chứa `DAQ_LIST_CAN_ID`/block CAN FD. Đã đối chiếu với
grammar AML công khai của pyxcp/pyA2L (nguồn ở cuối mục). Kết quả:

| # | Giả định | Trạng thái | Cách xử lý nếu sai |
|---|----------|-----------|--------------------|
| A1 | `DAQ_LIST_CAN_ID <list> VARIABLE` hoặc `FIXED <can_id>`; `VARIABLE` không kèm ID. | **Đã xác nhận** (AML XCP on CAN v1.0). Hiệu chỉnh: đây là **block con** `/begin DAQ_LIST_CAN_ID … /end DAQ_LIST_CAN_ID` lồng trong `XCP_ON_CAN`, không phải token rời. Parser phải đọc qua `children`. | — |
| A2 | CAN ID có bit 31 = 1 nghĩa là 29-bit. | **Đã xác nhận** (comment AML của `CAN_ID_BROADCAST/MASTER/SLAVE`). Parser bỏ bit 31 khi lưu ID, ghi vào cờ `extended`. | — |
| A3 | Block CAN FD (XCP ≥ 1.2). | **Chưa xác nhận từ nguồn gốc.** Nguồn thứ cấp nói có từ khoá/block `CAN_FD` trong `XCP_ON_CAN` với `MAX_DLC`, `CAN_FD_DATA_TRANSFER_BAUDRATE`, `SAMPLE_POINT`, `SECONDARY_SAMPLE_POINT`, `TRANSCEIVER_DELAY_COMPENSATION`. Parser hiện tại lại tìm block tên `XCP_ON_CAN_FD`. Chưa tìm được AML hay A2L CAN FD thật. | Parser nhận **cả hai** tên block, đọc theo từ khoá; trường thiếu → `None`, giữ giá trị nhập tay. Cần một A2L CAN FD thật để chốt. |
| A4 | Số DAQ list trong `DAQ_LIST_CAN_ID` = số DAQ list vật lý mà `configure_daq`/`make_key` dùng. | **Chưa xác nhận.** AML chỉ ghi "reference to DAQ_LIST_NUMBER". | Một hàm duy nhất đổi index→số vật lý; sửa tại đó. |
| A5 | ECU đánh PID tuyệt đối duy nhất toàn ECU (đúng spec); ECU không chuẩn có thể đánh lại theo list. | Theo chuẩn. | Khoá tra bảng gồm cả CAN ID (mục 3.3) chịu được cả hai. |

Phát hiện thêm: ví dụ `ifdata_CAN.a2l` của pyxcp có `CAN_ID_MASTER_INCREMENTAL`
(không có giá trị). Parser đọc và bỏ qua, ghi chú "master ID tăng dần theo từng
slave" vào `notes`; không dùng ở phần 1–2.

Nguồn đối chiếu (đọc ngày 2026-10-04):
- AML XCP on CAN v1.0: `christoph2/pyA2L` → `examples/xcp_aml_def.AML`, `examples/xcp100.aml`
- Ví dụ A2L có `FIXED`: `christoph2/pyxcp` → `pyxcp/aml/ifdata_CAN.a2l`
  (ba block `DAQ_LIST_CAN_ID`, list 0/1/2 → 0x310/0x320/0x330; đây là A2L ví dụ
  của thư viện, dùng làm mẫu cú pháp, không phải A2L của ECU thật)
- CAN FD (thứ cấp, chưa kiểm chứng): bài iCC 2013 "Speed up your calibration with
  CAN FD" và tài liệu CSS Electronics

## 3. Phần 1 — Nhận DAQ trên nhiều CAN ID

### 3.1 Cấu hình

`BusConfig` (`session/api.py:125`) thêm:

```python
daq_can_ids: tuple[tuple[int, int], ...] = ()   # ((số DAQ list vật lý, can_id), ...)
```

- Tuple các cặp (không dùng dict) vì `BusConfig` là `frozen` + hashable.
- Thuộc tính dẫn xuất `rx_ids -> frozenset[int]` = `{dto_id} ∪ {id ...}`.
- Lưu trong `config.toml` dạng chuỗi sửa tay được: `daq_can_ids = "0:0x6A2,1:0x6A3"`
  (`transport/config.py`: thêm vào `_coerce_bus` và `dumps_bus_config`; chuỗi sai
  định dạng → bỏ qua, như các khoá sai kiểu khác).
- Hai list không được cùng ID, và không được trùng `cro_id`; vi phạm → lỗi rõ
  ràng lúc Connect (`XcpToolError`), không để chạy rồi mất dữ liệu.

### 3.2 Tầng nhận frame

- `transport/pycan.py`: `can_filters` thành **một filter cho mỗi ID** trong
  `cfg.rx_ids` (cùng mask 11/29-bit như cũ).
- `XcpMaster._on_frame` (`master/core.py:175`):
  - `can_id not in cfg.rx_ids` → bỏ (giữ nguyên ý nghĩa cũ).
  - Frame trên `dto_id`: `classify()` như hiện tại (res/err/ev/serv/daq).
  - Frame trên ID riêng của một DAQ list: **luôn là `daq`**, không `classify()`
    (ID đó chỉ chở DTO; byte 0xFF/0xFE trong dữ liệu không được hiểu nhầm là
    response).
  - Trace ghi đúng `can_id` của frame (cột CAN ID đã có sẵn).
- Callback DAQ đổi chữ ký `cb(data)` → `cb(data, can_id)`. `RealSession` là nơi
  duy nhất đăng ký callback (`real.py:349`) nên chi phí đổi thấp.

### 3.3 Khoá tra bảng DTO

Hiện `DtoKey = int | tuple[int, int]` (PID, hoặc `(daq, odt)`).

Đổi bảng tra thành khoá **`(can_id, DtoKey)`**:

- `configure_daq`/`configure_predefined` biết list n phát trên ID nào:
  `can_id(n) = dict(cfg.daq_can_ids).get(n, cfg.dto_id)`; mỗi `PidEntry` được đăng
  ký dưới `(can_id(n), make_key(...))`.
- `decode_dto(frame, table, ts, fmt, can_id)` tra `(can_id, key)`.
- **Chỉnh khi lập kế hoạch:** khoá chỉ thành `(can_id, key)` (`RouteKey`) khi caller
  truyền `route_of` (tức `daq_can_ids` không rỗng). Khi rỗng, bảng giữ khoá thuần như
  cũ — hành vi tương đương nhưng không phải sửa ~70 chỗ test đang đọc/dựng bảng với
  khoá thuần. Một bảng chỉ chứa một dạng khoá nên không nhập nhằng với khoá
  `(daq, odt)` của id_type 1–3.

Lý do chọn khoá gộp thay vì chỉ kiểm tra "list khớp ID": chịu được ECU đánh PID
lại theo từng list (giả định A5) mà không cần heuristic. Đổi lại phải sửa các test
đang đọc trực tiếp `pid_table` (`tests/integration/test_daq*.py`).

`TimestampAccumulator` giữ nguyên (đã tách theo `stream=entry.daq_list`).

### 3.4 Fakeslave / FakeSession

- `devtools/fakeslave.py`: `SlaveConfig.daq_can_ids`; DTO của list n phát trên
  `daq_can_ids.get(n, dto_id)`; response vẫn trên `dto_id`.
- `session/fake.py:737`: tương tự cho `_emit` của luồng DAQ giả.

## 4. Phần 2 — Cấu hình CAN từ A2L

### 4.1 Parser

`a2l/types.py` thêm:

```python
@dataclass(frozen=True)
class DaqListCanId:
    daq_list: int
    fixed: bool            # True = FIXED, False = VARIABLE
    can_id: int | None     # None khi VARIABLE (giả định A1)

@dataclass(frozen=True)
class XcpCanInfo:
    master_id: int | None
    slave_id: int | None
    extended: bool | None
    baudrate: int | None
    sample_point: float | None      # %
    is_fd: bool
    fd_data_baudrate: int | None
    fd_data_sample_point: float | None
    max_dlc_required: bool
    daq_list_ids: tuple[DaqListCanId, ...]
```

`A2LDatabase.can_info: XcpCanInfo | None`. `a2l/parser.py` đọc từ block
`XCP_ON_CAN` theo **từ khoá**; các `DAQ_LIST_CAN_ID` là **block con** nên đọc qua
`children`; ID có bit 31 thì bỏ bit đó và đặt `extended=True`; block CAN FD nhận cả
tên `CAN_FD` lẫn `XCP_ON_CAN_FD` (A3), theo đúng cách
`_extract_xcp_protocol_info` đang neo `BYTE_ORDER_*`. Giá trị hỏng/thiếu → trường
đó `None`; lỗi cả block → `can_info=None` + `_log.warning` (cùng kiểu
"Skipping IF_DATA XCP" hiện có). `XcpProtocolInfo.is_fd`/`max_dlc_required` giữ
nguyên, `can_info` đọc từ cùng nguồn nên không lệch nhau.

### 4.2 Hàm áp cấu hình (thuần, không UI)

`session/a2l_can.py`:

```python
def apply_a2l_can(cfg: BusConfig, info: XcpCanInfo) -> tuple[BusConfig, list[str]]
```

- Ghi đè: `cro_id`←master, `dto_id`←slave, `extended_id`, `bitrate`,
  `sample_point`, `is_fd`, `data_bitrate`, `data_sample_point`,
  `pad_dlc`←`max_dlc_required`, `daq_can_ids`←các list `FIXED`.
- Trường A2L là `None` → giữ giá trị của `cfg`, ghi một dòng vào danh sách ghi chú.
- List `VARIABLE` → **không** thêm vào `daq_can_ids`; ghi chú
  "list N: VARIABLE — cần SET_DAQ_ID (chưa hỗ trợ)".
- Không đụng: `backend`, `channel`, `f_clock`, `brp/tseg*`, `t1_timeout_s`.
  Nếu `custom_bit_timing=True` thì timing thủ công vẫn thắng và ghi chú cảnh báo
  "bitrate A2L chưa được dùng".
- Trả về `(cfg_hiệu_lực, ghi_chú)`; không đọc file, không I/O → test dễ.

### 4.3 Luồng Connect

`BusConfig.use_a2l_can: bool = False` (lưu `config.toml`).

`RealSession.connect(cfg)` (`session/real.py:168`):

1. `use_a2l_can` và chưa nạp A2L, hoặc A2L không có `can_info` → `XcpToolError`
   nêu rõ nguyên nhân (không mở bus, không đoán).
2. `eff, notes = apply_a2l_can(cfg, db.can_info)`; mở transport và `XcpMaster`
   bằng `eff`; `notes` ghi vào trace (một dòng `other`) để biết đang dùng cấu
   hình từ A2L.
3. `_remember(cfg)` lưu `cfg` **gốc** (giá trị nhập tay + cờ `use_a2l_can`), không
   lưu `eff` — để bỏ tích sau đó không mất số đã nhập tay.

`FakeSession.connect` làm giống hệt để UI test dùng được.

### 4.4 Dialog Connect

`DeviceDialog(parent, initial, a2l_can: XcpCanInfo | None)`; `main_window.py:498`
truyền `self.session.symbols.can_info`.

- Checkbox "Config CAN from A2L": **bật được khi `a2l_can` không rỗng**; ngược lại
  xám và tooltip nêu lý do (chưa nạp A2L / A2L không có XCP_ON_CAN).
- Khi tích: cất giá trị nhập tay hiện tại, rồi hiển thị giá trị hiệu lực
  (`apply_a2l_can` trên cfg đang nhập) trong các ô CRO, DTO, 11/29-bit, bitrate,
  data bitrate, FD, sample point — **khoá chỉnh sửa**. Bitrate A2L không có trong
  combo → thêm mục tạm để hiển thị đúng.
- Một dòng tóm tắt dưới checkbox: ID, bitrate, số DAQ list có ID riêng, kèm các
  ghi chú (VARIABLE, trường thiếu).
- Bỏ tích: mở khoá, trả giá trị đã cất.
- `build_config()` luôn trả giá trị **nhập tay** + `use_a2l_can`; phần ghi đè do
  `connect()` làm (mục 4.3). Nhờ vậy dialog và session không lệch nhau.

## 5. Xử lý lỗi

| Tình huống | Hành vi |
|------------|---------|
| `use_a2l_can` nhưng thiếu A2L / thiếu `XCP_ON_CAN` | `XcpToolError` rõ lý do, không mở bus |
| Hai list cùng CAN ID, hoặc trùng `cro_id` | `XcpToolError` lúc Connect |
| Frame ID ngoài `rx_ids` | Bỏ (filter phần cứng + `_on_frame`) |
| A2L hỏng một trường | Trường đó `None`, dùng giá trị nhập tay, có ghi chú |
| `daq_can_ids` trong TOML sai định dạng | Bỏ qua khoá, dùng `()` |

## 6. Kiểm thử

- **Unit `a2l`**: A2L tự viết (gắn nhãn là giả định, mục 2) có `FIXED`, `VARIABLE`,
  ID 29-bit, thiếu `SAMPLE_POINT`, block CAN FD; A2L hiện có
  (`examples/xcp_daq_example.a2l`) → `can_info` đúng 0x7E0/0x7E1/500000.
- **Unit `apply_a2l_can`**: từng trường ghi đè/giữ; `VARIABLE`; `custom_bit_timing`;
  không đụng `backend/channel`.
- **Unit config**: `daq_can_ids` và `use_a2l_can` round-trip TOML, chuỗi sai bị bỏ.
- **Unit `decode_dto`**: cùng PID trên hai CAN ID → hai list khác nhau; ID lạ → `[]`.
- **Integration (fakeslave)**: hai list trên hai ID, `drain_daq()` đủ mẫu của cả
  hai; response không lẫn với DAQ; `daq_can_ids` rỗng → kết quả giống test cũ.
- **Transport**: `can_filters` có đủ ID; mask 11/29-bit đúng.
- **UI**: checkbox xám khi không có A2L; tích → ô khoá + tóm tắt; bỏ tích → giá trị
  tay trở lại; `build_config()` giữ giá trị tay; Connect không A2L với cờ bật → thông
  báo lỗi, không traceback.
- Hồi quy: chạy toàn bộ `tests/` (theo skill `test_strategy`).

## 7. Thứ tự thực hiện gợi ý

1. `BusConfig` + TOML + `rx_ids` (không đổi hành vi).
2. Filter phần cứng + `_on_frame` + chữ ký callback + khoá `(can_id, key)` +
   fakeslave → **sửa lỗi mất DAQ**, có thể phát hành riêng.
3. `XcpCanInfo` + parser.
4. `apply_a2l_can` + `connect()` của Real/Fake.
5. Dialog + checkbox.
