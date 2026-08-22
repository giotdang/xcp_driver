# xcptool — Kiến trúc

> **Đối tượng đọc:** developer hoặc agent sẽ SỬA/MỞ RỘNG code, không phải end-user.
> Muốn dùng công cụ, xem `USER_MANUAL.md`.
>
> **Nguồn sự thật:** tài liệu này mô tả ĐÚNG code hiện có tại thời điểm hiện tại
> (sau khi M1→M6 hoàn tất, 2026-08-20). Khi hai tài liệu mâu thuẫn nhau, tin
> file này hoặc tin code, không tin DESIGN.md/DEV_PLAN.md.

---

## 1. Tổng quan

xcptool là công cụ PC (Python + PySide6) thay thế CANape/INCA cho việc đo
lường/hiệu chỉnh ECU qua giao thức XCP trên CAN. Hai nguyên tắc chi phối mọi
quyết định thiết kế:

1. **Độc lập với firmware trong `driver/`** — xcptool không import, không đọc,
   không giả định bất cứ thứ gì từ repo `driver/` (XCP slave TC2xx). Quan hệ
   duy nhất là giao thức XCP trên dây, giống hệt quan hệ với ECU của hãng khác.
2. **Độc lập với một ECU cụ thể** — không hardcode MAX_CTO, CAN ID, byte order,
   đơn vị timestamp ở bất cứ đâu trong logic. Mọi đặc tính ECU đến từ
   `BusConfig` (user cấu hình) hoặc `SlaveCaps` (hỏi ECU lúc CONNECT).

Cả hai nguyên tắc được **cưỡng chế bằng test** (`tests/test_boundaries.py`),
không phải bằng kỷ luật của người viết code — xem §9.

Phạm vi đã hoàn thành (M1 → M6):
- **Giao tiếp CAN & Thiết bị:** Chọn thiết bị đa hãng (PEAK, Vector, ETAS, slcan, virtual), CONNECT, capability discovery.
- **A2L Parser:** Tự viết block-tree parser chuẩn ASAM MCD-2 MC, phân tích CHARACTERISTIC, MEASUREMENT, RECORD_LAYOUT.
- **Calibration Engine & View:** Quản lý trang (Working/Reference), phân cấp Struct & Array `[0..N-1]`, sửa inline, dirty tracking, chống ghi reference page.
- **DAQ Engine & Scope:** Đóng gói ODT tối ưu (`pack_odts`), cấu hình DAQ (`configure_daq`), giải mã DTO (`decode_dto`) kèm rollover timestamp, scope đồ thị `pyqtgraph` tăng tốc OpenGL/NumPy, hiển thị live value thời gian thực.
- **Trace & Debug:** Trace CAN thời gian thực, lọc frame, batch throttling chống flood DTO, console lệnh thô, memory hex dump.
- **Giả lập xe & ECU:** `FakeSlave` + `PidPlant` chạy qua virtual CAN bus nội bộ cho chế độ `--session fake`.

---

## 2. Kiến trúc các lớp

```
┌────────────────────────────────────────────────────────────────────────┐
│  ui/          MainWindow, CalibrationView, MeasurementView,            │
│               TraceView, MemoryView, ConsoleView, DeviceDialog         │
│  cli/         lệnh `xcptool …` — consumer thứ hai của contract          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │  chỉ qua session.api.Session (Protocol)
┌───────────────────────────────────▼────────────────────────────────────┐
│  session/     api.py (CONTRACT) · real.py (backend) · fake.py          │
│               a2l/ (parser & database symbols)                         │
└───────┬────────────────────────────────────────────────┬───────────────┘
        │ RealSession dùng cả ba                         │ FakeSession
┌───────▼──────────────────┐  ┌────────────────────────┐ ┌───────▼───────┐
│  master/   protocol core │  │  a2l/                  │ │ (stub UI test │
│  - core.py (XcpMaster)   │  │  - parser.py           │ │  thuần)       │
│  - daq.py (DAQ engine)   │  │  - database.py         │ └───────────────┘
│  - codec.py, trace.py    │  │  - types.py            │
└───────┬──────────────────┘  └────────────────────────┘
        │ Link Protocol (send/recv/close)
┌───────▼──────────────────┐
│  transport/  registry đa │
│  backend, python-can     │
└──────────────────────────┘
```

**Vì sao tách lớp thế này:**

- `master/` không import `can` — sau này thêm transport XCP-on-Ethernet chỉ
  cần một `Link` mới, protocol core và DAQ engine dùng lại nguyên vẹn.
- `a2l/` là parser độc lập, không phụ thuộc vào `can` hay Qt, tự parse block-tree không dùng thư viện ngoài.
- `ui/`/`cli/` không import `xcptool.master`, `xcptool.transport`, `xcptool.a2l` trực tiếp — chỉ nói
  chuyện qua `session.api.Session`.
- `session/api.py` là ranh giới duy nhất, chỉ chứa kiểu dữ liệu/ngoại lệ/chữ ký Protocol.

### Ranh giới ép bằng AST (`tests/test_boundaries.py`)

| Package | Cấm import |
|---|---|
| `master/` | `can`, `PySide6`, `xcptool.ui`, `xcptool.cli`, `xcptool.transport` |
| `transport/` | `PySide6`, `xcptool.ui`, `xcptool.cli`, `xcptool.master` |
| `a2l/` | `can`, `PySide6`, `xcptool.ui`, `xcptool.cli`, `xcptool.master`, `xcptool.transport` |
| `ui/` | `can`, `xcptool.master`, `xcptool.transport`, `xcptool.a2l` |
| `cli/` | `can`, `xcptool.master`, `xcptool.transport`, `xcptool.a2l` |
| `session/api.py`, `session/fake.py` | `can`, `PySide6`, `xcptool.master`, `xcptool.transport` |

---

## 3. Contract — `session/api.py`

File này định nghĩa API hợp đồng giữa UI/CLI và Backend.

### 3.1 Luật thread

- **Session không biết Qt tồn tại.** Không bao giờ gọi ngược lên UI.
- **Nhóm chặn** — mọi phương thức thao tác bus (`connect`, `read`, `write`, `get_page`, `set_page`, `copy_page`, `load_a2l`, `start_daq`, `stop_daq`, `raw_command`): Phải gọi từ worker thread (`TaskRunner`) và marshal kết quả về UI thread bằng Qt signal.
- **Nhóm không chặn, an toàn thread** — gọi thẳng từ UI thread: `state`, `caps`, `symbols`, `dropped_frames`, `drain_trace()`, `drain_daq()`, `load_config()`.
- **Session không reentrant** — có lệnh đang chờ response mà bị gọi lệnh khác chồng lên → `BusyError` ngay lập tức.
- **`close()` idempotent, KHÔNG BAO GIỜ ném.**

### 3.2 Cây ngoại lệ

```
XcpToolError
├── TransportError              (lỗi tầng bus, chưa đụng XCP)
│   ├── DeviceNotFoundError     kênh đã chọn không còn tồn tại
│   ├── DriverMissingError      thiếu driver hãng — có .package_hint
│   └── BusError                bus lỗi lúc đang chạy
├── ProtocolError                (lỗi tầng XCP)
│   ├── XcpTimeoutError          hết T1, ECU không trả lời
│   ├── MalformedResponseError   frame ngắn/sai định dạng
│   └── SlaveError               ECU trả 0xFE — có .code/.name/.description
│       ├── WriteProtectedError  CRC_WRITE_PROTECTED — kèm nút chuyển working page
│       ├── OutOfRangeError      CRC_OUT_OF_RANGE
│       └── SequenceError        CRC_SEQUENCE
├── NotConnectedError            gọi lệnh khi chưa CONNECT
├── BusyError                    lệnh chồng lên lệnh đang chạy
└── UnsupportedByEcuError        gọi tính năng ECU không có theo SlaveCaps
```

### 3.3 Dataclass & Types quan trọng

- **`BusConfig`** — cấu hình mở bus CAN (`backend`, `channel`, `bitrate`, `cro_id`, `dto_id`, `is_fd`, `timeout_s`).
- **`SlaveCaps`** — năng lực ECU đọc từ CONNECT (`max_cto`, `max_dto`, `byte_order`, `supports_cal_pag`, `supports_daq`, `supports_stim`, `supports_pgm`, `daq_caps`).
- **`A2LDatabase`** — cơ sở dữ liệu symbols sau khi nạp A2L (`characteristics`, `measurements`, `record_layouts`).
- **`DaqList` / `DaqSignal`** — danh sách và tín hiệu cần đăng ký đo lường DAQ.
- **`SamplePoint`** — một điểm đo sau giải mã DTO (`name`, `timestamp_ns`, `value_raw`, `datatype`).

---

## 4. Protocol Core & DAQ Engine — `master/`

### 4.1 XcpMaster (`master/core.py`)

- **RX Thread riêng (`_rx_loop`)**: liên tục đọc CAN frame, phân loại (`classify()`), đẩy vào `TraceBuffer` và route:
  - Nếu là CTO response (`RES` / `ERR`) → đẩy vào `Queue` cho lệnh đang chờ.
  - Nếu là DTO frame (`PID` khác `0xFF..0xFC`) → gọi callback DAQ (`set_daq_callback()`).
- **Thao tác đồng bộ (`transact`)**: bảo vệ bằng `threading.Lock(blocking=False)` → `BusyError` nếu reentrant.
- **Các hàm DAQ nguyên tố**: `free_daq()`, `alloc_daq()`, `alloc_odt()`, `alloc_odt_entry()`, `set_daq_ptr()`, `write_daq()`, `set_daq_list_mode()`, `start_stop_daq_list()`, `start_stop_synch()`.

### 4.2 DAQ Engine (`master/daq.py`)

- **Thuật toán đóng gói ODT (`pack_odts`)**:
  - Khi bật timestamp trên ODT 0: PID (1B) + Timestamp (4B) = 5B overhead $\rightarrow$ `first_budget = 3` byte (với CAN DLC=8). Các ODT 1+ có `rest_budget = 7` byte.
  - Tách tín hiệu nhỏ ($\le 3$B) và lớn ($> 3$B). Đóng gói ODT 0 trước bằng first-fit-decreasing; các ODT sau ưu tiên tín hiệu lớn trước. ODT 0 có thể rỗng nếu tất cả tín hiệu đều $> 3$B.
- **Cấu hình DAQ (`configure_daq`)**:
  - Thực thi tuần tự chuẩn ASAM: `FREE_DAQ` $\rightarrow$ `ALLOC_DAQ` $\rightarrow$ `ALLOC_ODT` $\rightarrow$ `ALLOC_ODT_ENTRY` $\rightarrow$ `SET_DAQ_PTR` + `WRITE_DAQ` $\rightarrow$ `SET_DAQ_LIST_MODE` $\rightarrow$ `START_STOP_DAQ_LIST(select)` $\rightarrow$ `START_STOP_SYNCH(start)`.
  - Xây dựng bảng tra cứu nhanh $O(1)$: `pid -> PidEntry` dựa trên `first_pid` từ response `START_STOP_DAQ_LIST`.
- **Giải mã DTO (`decode_dto`) & Timestamp Rollover (`TimestampAccumulator`)**:
  - Mask `PID & 0x7F` (bỏ cờ overrun bit 7).
  - Trích xuất timestamp 4 byte ở ODT 0. Bộ tích lũy theo dõi bộ đếm 32-bit (10ns/tick), khi phát hiện tràn $raw < last$, tự động cộng dồn epoch $2^{32}$, giữ timestamp tăng đơn điệu tuyệt đối.

---

## 5. Parser A2L — `a2l/`

Xây dựng độc lập, không phụ thuộc thư viện ngoài:
- **`parser.py`**: Block-tree parser tokenizer, bóc tách các khối `/begin CHARACTERISTIC ... /end CHARACTERISTIC`, `/begin MEASUREMENT ...`, `/begin RECORD_LAYOUT ...`, `IF_DATA`.
- **`types.py`**: Các dataclass `Measurement`, `Characteristic`, `RecordLayout`, `A2LDatabase`, kiểu dữ liệu chuẩn (`UBYTE`, `FLOAT32_IEEE`, v.v.).
- **`database.py`**: Nạp file A2L và hàm liên kết `_resolve()` liên kết `RecordLayout` vào `Characteristic` để xác định chính xác kiểu dữ liệu, kích thước byte và layout nhớ.

---

## 6. Transport Layer — `transport/`

- **Registry Pattern (`registry.py`)**: Quản lý danh sách `BackendSpec`. Thêm backend mới chỉ cần khai báo spec và hàm khởi tạo, không sửa protocol core.
- **Backend hỗ trợ**:
  - `pcan`: PEAK PCAN-USB qua `PCANBasic`.
  - `vector`: Vector VN16xx qua XL Driver Library.
  - `etas`: ETAS ES58x qua BOA.
  - `slcan`: CANable / thiết bị nối tiếp COM ảo.
  - `virtual`: Bus CAN ảo nội bộ của python-can.
  - `replay`: Phát lại file trace text.
- **Bắt log êm (`quiet.py`)**: Chặn stderr và logger nội bộ của python-can khi dò thiết bị, chỉ giữ lại thông báo lỗi thực tế.

---

## 7. Giao diện người dùng — `ui/`

### 7.1 Điều phối & Luồng dữ liệu (`MainWindow`)
- **`TaskRunner` (`workers.py`)**: Điều phối tác vụ nền qua `QThreadPool`. Mọi thao tác I/O chạy trên worker thread, callback bắn về UI thread qua Qt signal.
- **Nhịp Drain 40ms (`_poll_trace`)**:
  - `drain_trace(200)`: Giới hạn tối đa 200 frame/tick để làm mượt tải giao diện, tránh hiện tượng đơ lag khi vừa khởi động DAQ.
  - `drain_daq()`: Lấy dữ liệu sample từ ring buffer 10.000 phần tử và chuyển cho `MeasurementView.on_samples()`.

### 7.2 Panel Hiệu chỉnh (`CalibrationView`)
- **Phân cấp Struct & Array**: Gom nhóm các biến tiền tố struct thành node cha `STRUCT (N)`. Array được mở rộng thành `[0..N-1]`. Dòng cha array hiển thị `"—"`, các dòng con hiển thị giá trị riêng.
- **Kiểu dữ liệu thân thiện**: Chuyển đổi kiểu A2L sang chuẩn C (`UINT8`, `INT16`, `FLOAT32`, `FLOAT32[4]`).
- **Sửa inline & Dirty Tracking**: Double-click vào ô giá trị để sửa, hiển thị màu cam nổi bật. Khi ghi array, hệ thống đọc trực tiếp từ các node con để đóng gói dữ liệu chính xác.
- **Quản lý trang Working / Reference**: Tự động nhận diện `WriteProtectedError` khi ghi nhầm vào Reference page (ROM) và đưa ra hộp thoại chuyển sang Working page (RAM) 1-click.

### 7.3 Panel Đo lường (`MeasurementView`)
- **Hiển thị Signal & Live Value**: Cây tín hiệu gom nhóm struct và array, cột "Giá trị" cập nhật số thực real-time theo chu kỳ 40ms.
- **Đồ thị Scope Real-time (`pyqtgraph`)**:
  - Tối ưu hiệu năng cao với `np.fromiter()` và bộ đệm ring `deque(maxlen=3000)`.
  - Tăng tốc phần cứng GPU qua PyOpenGL (tự động fallback về software rendering nếu không có PyOpenGL).
  - Bỏ qua vẽ (`setData`) nếu không có dữ liệu mới trong tick.
  - Switch bật/tắt đồ thị: Tắt scope sẽ ẩn hoàn toàn widget vẽ đồ thị và ngắt 100% việc tính toán curve, siêu tiết kiệm CPU/GPU.
- **Tự động tách Array**: Tự động phân rã array `MATRIX_DIM` thành các signal DAQ con để phù hợp ngân sách ODT của XCP.

### 7.4 Panel Debug & Trace (`TraceView`, `ConsoleView`, `MemoryView`)
- **`TraceView`**:
  - Mặc định **tắt bộ lọc DAQ** nhằm loại bỏ tình trạng flood 50–100 frame DTO/giây gây nghẽn UI thread.
  - Tối ưu lazy `scrollToBottom()`: Chỉ cuộn bảng khi tab Trace đang thực sự hiển thị trên màn hình.
- **`DockManager`**: Quản lý dock trace/console/memory ở cạnh dưới, hỗ trợ collapse/expand mượt mà qua `setMaximumHeight(0)`.

### 7.5 Mô phỏng & Demo (`session_factory.py` & `devtools/`)
- Khi chạy với `--session fake`, hệ thống khởi tạo `_FakeEcuSession` gồm `RealSession` thật + `FakeSlave` + `PidPlant` chạy trên virtual bus.
- `PidPlant` (`devtools/pid_plant.py`): Mô phỏng xe hơi và thuật toán PID ở tần số 50Hz, tính toán measurement thực tế từ các giá trị calibration `speedPid_kp`, `speedPid_ki`, v.v.

---

## 8. CLI — `cli/`

Công cụ dòng lệnh `xcptool` là consumer thứ hai của `Session` contract:
- Các lệnh: `devices`, `connect`, `read`, `write`, `pages`, `set-page`, `raw`, `trace`.
- Hỗ trợ đầy đủ tham số `--session fake` và `--session real`.

---

## 9. Chiến lược kiểm thử

Toàn bộ dự án được bảo vệ bởi bộ test tự động nghiêm ngặt:
1. **Ranh giới kiến trúc (`tests/test_boundaries.py`)**: Quét AST kiểm tra import hợp lệ giữa các module và cấm hardcode địa chỉ CAN.
2. **Unit tests (`tests/unit/`)**: Kiểm tra thuật toán A2L parser, ODT packing (`test_daq_packing.py`), DTO decoder (`test_daq_decoder.py`), v.v.
3. **Integration tests (`tests/integration/`)**: Kiểm tra luồng `RealSession` + `FakeSlave` trên virtual bus cho cả calibration và DAQ.
4. **UI tests (`tests/ui/`)**: Kiểm tra `CalibrationView`, `MeasurementView`, `ConsoleView`, `TraceView` qua `pytest-qt` ở chế độ headless.

---

## 10. Bản đồ file mã nguồn

```
xcptool/
├── ARCHITECTURE.md              tài liệu kiến trúc hệ thống
├── USER_MANUAL.md                hướng dẫn sử dụng cho người dùng
├── DESIGN.md, DEV_PLAN.md        tài liệu thiết kế và kế hoạch
├── pyproject.toml                cấu hình dự án & dependencies
├── tests/                        bộ kiểm thử toàn diện (>405 tests)
└── src/xcptool/
    ├── session/                  CONTRACT & Session implementations
    │   ├── api.py                Contract chính thức (Protocol, dataclasses)
    │   ├── real.py               RealSession (CAN thật & virtual bus)
    │   └── fake.py               FakeSession (stub test)
    ├── a2l/                      ASAM MCD-2 MC Parser
    │   ├── parser.py             Block-tree parser
    │   ├── types.py              Dataclasses & DataTypes
    │   └── database.py           Database loader & resolver
    ├── master/                   XCP Protocol Core & DAQ Engine
    │   ├── core.py               XcpMaster (giao thức XCP thuần)
    │   ├── daq.py                DAQ allocation, ODT packing, DTO decoding
    │   ├── codec.py              Frame classifier & text encoder
    │   ├── constants.py          XCP Command / PID / Error enums
    │   ├── errors.py             Bảng ánh xạ mã lỗi CRC_*
    │   └── trace.py              TraceBuffer ring buffer
    ├── transport/                Tầng giao tiếp phần cứng CAN
    │   ├── registry.py           Đăng ký đa backend
    │   ├── pycan.py              PyCanTransport wrapper
    │   └── virtual.py, pcan.py, vector.py, etas.py, slcan.py, replay.py
    ├── devtools/                 Mô phỏng & Kiểm thử
    │   ├── fakeslave.py          ECU giả lập giao thức XCP
    │   └── pid_plant.py          Mô phỏng vật lý xe & thuật toán PID
    ├── ui/                       Giao diện đồ họa Fluent
    │   ├── main_window.py        Điều phối giao diện chính & task runner
    │   ├── calibration_view.py   Panel hiệu chỉnh tham số A2L
    │   ├── measurement_view.py   Panel đo lường & Scope thời gian thực
    │   ├── trace_view.py         Panel theo dõi frame CAN (Trace)
    │   ├── memory_view.py        Panel đọc/ghi bộ nhớ hex
    │   ├── console_view.py       Panel lệnh thô
    │   ├── device_dialog.py      Hộp thoại cấu hình thiết bị CAN
    │   ├── dock_manager.py       Quản lý dock phía dưới
    │   └── session_factory.py    Khởi tạo Session theo chế độ
    └── cli/                      Giao diện dòng lệnh
```
