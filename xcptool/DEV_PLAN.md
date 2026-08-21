# xcptool — Kế hoạch phát triển

> **Trạng thái:** M1 ✅ M2 ✅ M3 ✅ M4 ✅ M5 (in progress) — 443 tests (2026-08-22)
> **Kiến trúc & quyết định thiết kế:** xem [DESIGN.md](DESIGN.md)
> **Contract chính thức:** `src/xcptool/session/api.py`

---

## 0. Prerequisites

```
xcptool/.venv/           Python 3.12 venv
pip install -e ".[dev]"  # python-can, PySide6, pytest, pytest-qt, pytest-timeout
```

Luôn chạy qua `xcptool\.venv\Scripts\python.exe` — không phải `python` trần.
`QT_QPA_PLATFORM=offscreen` cho headless test.

---

## 1. Hai nguyên tắc cốt lõi

**Boundary enforcement bằng AST, không bằng kỷ luật.** `tests/test_boundaries.py` quét import ở mức AST mỗi lần chạy test. Vi phạm → test đỏ ngay, không cần review. Điều này có nghĩa: thêm import mới → test chạy lại.

**FakeSession trước, RealSession sau.** Frontend và backend phát triển song song trên cùng contract. Frontend không bao giờ bị block chờ backend. Tích hợp chỉ là "đổi FakeSession lấy RealSession" — không có lần viết lại nào.

---

## 2. Cây module (cập nhật sau M4)

```
xcptool/
├── src/xcptool/
│   ├── session/
│   │   ├── api.py          ← CONTRACT — chỉ lead sửa
│   │   ├── fake.py         ← FakeSession (dùng cho test UI thuần, không cần bus)
│   │   └── real.py         ← RealSession (dùng master/ + transport/)
│   ├── a2l/                ← M3 ✅
│   │   ├── types.py        ← DataType, RecordLayout, Measurement, Characteristic, A2LDatabase
│   │   ├── parser.py       ← Block-tree parser (self-written, không dùng pya2l)
│   │   └── database.py     ← load(path) → A2LDatabase, _resolve() liên kết RecordLayout
│   ├── master/
│   │   ├── core.py         ← CONNECT/UPLOAD/DOWNLOAD/GET_CAL_PAGE/SET_CAL_PAGE/COPY_CAL_PAGE
│   │   └── daq.py          ← M4 ✅ pack_odts, configure_daq, decode_dto, TimestampAccumulator
│   ├── transport/
│   │   └── pycan.py        ← python-can bridge, pad DLC=8, detect_available_configs
│   ├── devtools/
│   │   ├── fakeslave.py    ← FakeSlave — ECU giả nói XCP thật qua virtual CAN bus
│   │   └── pid_plant.py    ← M4 ✅ PidPlant — mô phỏng measurement tính từ calibration
│   ├── ui/
│   │   ├── main_window.py  ← MainWindow(QMainWindow), TaskRunner, _call()
│   │   ├── calibration_view.py  ← M3 ✅ CalibrationView, decode/encode_value
│   │   ├── measurement_view.py  ← M4 ✅ signal tree + pyqtgraph scope, start/stop DAQ
│   │   ├── trace_view.py   ← Trace CAN
│   │   ├── memory_view.py  ← Memory/Debug
│   │   ├── dock_manager.py ← M3 ✅ DockManager, toggle collapse/expand
│   │   ├── session_factory.py ← M4 ✅ create_session("fake"|"real") — fake = RealSession
│   │   │                        + FakeSlave + PidPlant qua virtual bus (không phải stub)
│   │   └── theme.py        ← Fluent dark/light
│   └── cli/
│       └── main.py         ← `xcptool` entrypoint
├── tests/
│   ├── test_boundaries.py  ← AST boundary enforcement
│   ├── unit/                ← test_a2l_parser.py (M3), test_daq_packing.py / test_daq_decoder.py (M4 ✅)
│   ├── integration/         ← test_daq.py, test_session_daq.py (M4 ✅) — RealSession + FakeSlave qua virtual bus
│   └── ui/                  ← test_calibration_view.py, test_shell.py, test_console.py, test_measurement_view.py (M4 ✅)
└── (examples/xcp_daq_example.a2l ở NGOÀI xcptool/, cùng cấp repo root — A2L demo cho
     `--session fake`: CHARACTERISTIC speedPid_kp/_ki/_outMin/_outMax + MEASUREMENT liên quan)
```

---

## 3. Contract tóm tắt

`session/api.py` là ranh giới duy nhất giữa frontend và backend. Không file nào ở `ui/` hoặc `cli/` được import từ `master/`, `transport/`, hay `a2l/` trực tiếp.

**Luồng chặn (chạy qua `TaskRunner`, không trên UI thread):**

| Method | Mô tả |
|---|---|
| `connect(cfg: BusConfig)` | CONNECT, đọc SlaveCaps |
| `disconnect()` | DISCONNECT |
| `upload(addr, ext, size) → bytes` | SET_MTA + UPLOAD |
| `download(addr, ext, data: bytes)` | SET_MTA + DOWNLOAD |
| `get_cal_page(segment, mode) → int` | GET_CAL_PAGE |
| `set_cal_page(segment, mode, page)` | SET_CAL_PAGE |
| `copy_cal_page(src_seg, src_page, dst_seg, dst_page)` | COPY_CAL_PAGE |
| `load_a2l(path: str \| Path)` | parse A2L, populate `symbols` |
| `start_daq(lists: list[DaqList])` | M4: cấu hình + khởi động DAQ |
| `stop_daq()` | M4: dừng DAQ |

**Non-blocking (gọi được từ UI thread):**

| Property/Method | Mô tả |
|---|---|
| `symbols: A2LDatabase` | Sau `load_a2l()` — dict CHAR/MEAS; `None` trước đó |
| `caps: SlaveCaps` | Sau `connect()` — `None` trước đó |
| `drain_trace(n) → list[TraceEntry]` | Pop tối đa n entry từ ring buffer |
| `load_config() → BusConfig` | Đọc `~/.xcptool/config.toml` |

Thread safety: mọi `Session.method()` chặn đều chạy trong `QRunnable` qua `TaskRunner`. Không gọi trực tiếp trên UI thread trừ `drain_trace()` và `load_config()`.

---

## 4. Milestone đã hoàn thành

### M1 + M2 (2026-08-16)

Backend (B0–B4): transport PEAK/Vector/slcan/virtual, master protocol core, RealSession, FakeSession contract, cfg_store.
Frontend (F0–F5): DeviceDialog, MainWindow Fluent shell, TraceView, MemoryView, ConsoleView, theme.
Tích hợp: J1 pass 10/10, 265 test xanh → 266 sau fix `load_config()` bug (hai cơ chế nhớ device độc lập, không đồng bộ).
Tài liệu: `ARCHITECTURE.md`, `USER_MANUAL.md`, `docs/*.html`.

### M3 (2026-08-17 → commit 2026-08-18, `672f530`)

**A3a** — A2L parser: `a2l/parser.py` block-tree, `a2l/types.py` dataclass, `a2l/database.py` load + resolve.
**A3b** — Session contract: `load_a2l(path)` + `symbols: A2LDatabase` property vào `api.py`, `fake.py`, `real.py`.
**A3c** — CalibrationView: 7-column QTreeWidget, `decode/encode_value`, dirty indicator, page model Working/Reference, WriteProtectedError flow.
**A3d** — DockManager + tích hợp: collapse/expand dock bottom bằng `resizeDocks()` (không dùng `hide()` — nút arrow biến mất theo), `main_window.py` kết nối tất cả.

346 test pass. Race condition connect (`_refresh_pages_after_connect` gọi hai lần worker song song) đã sửa — gom thành một worker call.

### M4 (2026-08-18 → 2026-08-19, chưa commit)

**D4a** — `pack_odts()`: tách small/large theo `first_budget`, ODT 0 riêng, ODT 1+
first-fit-decreasing. `master/daq.py`, `tests/unit/test_daq_packing.py`.

**D4b** — DAQ allocation: `configure_daq()` chạy đúng trình tự
`FREE_DAQ → ALLOC_DAQ → ALLOC_ODT → ALLOC_ODT_ENTRY → SET_DAQ_PTR → WRITE_DAQ →
SET_DAQ_LIST_MODE → START_STOP_DAQ_LIST(select) → START_STOP_SYNCH`. Dựng bảng
`pid → PidEntry` từ `first_pid` trả về ở bước select. `master/core.py` thêm các
lệnh DAQ nguyên tố (`free_daq`, `alloc_daq`, `alloc_odt`, `alloc_odt_entry`,
`set_daq_ptr`, `write_daq`, `set_daq_list_mode`, `start_stop_daq_list`,
`start_stop_synch`).

**D4c** — `decode_dto()` + `TimestampAccumulator`: mask `PID & 0x7F`, timestamp
4 byte @ offset 1 chỉ ở ODT 0, rollover 32-bit cộng dồn epoch không reset về 0.
`tests/unit/test_daq_decoder.py`.

**D4d** — Session contract: `start_daq`/`stop_daq`/`drain_daq` (non-blocking,
ring buffer 10 000 sample) vào `api.py`, `fake.py` (stub), `real.py` (dùng
`XcpMaster.set_daq_callback()` từ RX thread). `tests/integration/test_daq.py`,
`test_session_daq.py`.

**D4e** — `MeasurementView`: checkbox tree từ `session.symbols.measurements`,
pyqtgraph scope nhiều đường, nút Start/Stop, `QTimer 40ms` → `drain_daq()` cùng
nhịp với `drain_trace()` (một nơi drain duy nhất, theo luật đã có từ M1).
Nav sidebar thêm tab "Đo lường". `tests/ui/test_measurement_view.py`.

**Ngoài kế hoạch ban đầu, phát sinh khi test bằng tay:**

- **Kiến trúc `--session fake` đổi hẳn.** Bản kế hoạch D4d chỉ định "cập nhật
  `fake.py` cho phù hợp" — thực tế `FakeSession` (Python thuần, tự chế
  trạng thái) không đủ giá trị cho DAQ: nó chỉ gửi 1 frame giả `START_DAQ`,
  không chạy `configure_daq()` thật, `drain_daq()` luôn rỗng. Theo yêu cầu
  người dùng ("Master vẫn phải gửi đủ lệnh như thật, Slave phải phản hồi
  tương đương"), `ui/session_factory.py::create_session("fake")` đổi sang
  trả về `_FakeEcuSession` — wrapper `RealSession` thật nối với `FakeSlave`
  qua virtual CAN bus nội bộ. `FakeSession` (`session/fake.py`) giữ nguyên,
  vẫn dùng cho test UI không liên quan DAQ.
- **`FakeSlave` phải trung thực khi địa chỉ ngoài vùng nhớ.** Thử nghiệm đầu
  tiên thêm cờ `daq_synthetic` (sóng sine giả cho địa chỉ ngoài
  `mem_base`/`mem_size`) đã bị bác bỏ và revert — một ECU giả bịa dữ liệu
  hợp lý cho địa chỉ sai thì che giấu đúng loại lỗi nó nên phơi ra. Giờ trả
  `0x00` cho ngoài vùng, đúng ECU thật (uninitialized RAM).
- **Race condition thật trong `FakeSlave._cmd_start_stop_synch()`**: thread
  gửi DAQ được start trước khi gửi RES cho chính START_STOP_SYNCH, khiến
  đôi khi frame DAQ đến trước RES trong Trace CAN — đã sửa thứ tự.
- **`devtools/pid_plant.py` (`PidPlant`)**: measurement tính TỪ calibration
  thật (không phải bịa) — đọc `speedPid_kp/_ki/_outMin/_outMax` qua
  `FakeSlave.peek()`, chạy PID + mô hình vật lý xe đơn giản 50Hz, ghi
  `vehicleSpeedKph`/`engineRpm`/`speedPidTelemetry_*`/`torqueSamples` qua
  `poke()`. `coolantTempC` = trung bình cộng CHARACTERISTIC `tempCompTable`
  (công thức đơn giản, dễ verify tay). Đặt trong `devtools/`, không đụng
  `fakeslave.py` (core vẫn ECU-agnostic) — chỉ `session_factory.py` biết cụ
  thể về `examples/xcp_daq_example.a2l`.
- **Bug UI đã sửa cùng đợt (không thuộc DAQ)**: nút toggle vùng debug
  (`dock_manager.py`) — mũi tên ngược chiều trực quan, và `hide()` nội dung
  lúc collapse làm co luôn CHIỀU RỘNG dock (để trống khoảng lớn bên phải,
  không phải chỉ chiều cao) — đổi sang `setMaximumHeight(0)`.

405 test pass (404 + 1 flaky độc lập với M4, xanh khi chạy riêng —
`test_console.py::test_nut_lenh_nhanh_dien_vao_o_nhap`). `--selftest` qua
GUI thật (`--session fake`) xanh toàn bộ 15 bước.

---

## 5. Validate trước khi merge

Chạy trong venv sau mỗi PR:

```bash
python -m pytest tests/ -x -q
```

`tests/integration/` tự khởi động `FakeSlave` trong từng test (context manager
trên virtual bus, xem fixture `connected` trong `test_daq.py`) — không cần chạy
`fakeslave.py` như một tiến trình nền riêng.

Tất cả phải xanh. Không merge khi test đỏ, kể cả nếu là test ngoài scope thay đổi.
`tests/ui/test_console.py::test_nut_lenh_nhanh_dien_vao_o_nhap` có tiền sử flaky
khi chạy CHUNG cả suite (pass 100% khi chạy riêng) — nếu chỉ mỗi test này đỏ, chạy
lại riêng file đó trước khi kết luận có regression thật.

---

## 6. Tiêu chí "không crash" (áp dụng cho mọi milestone)

Test này không tự động — chạy thủ công trước release:

1. Rút dây CAN giữa chừng (trong khi đang CONNECT)
2. Cắm lại dây — app vẫn cho reconnect mà không cần restart
3. Flood bus 1000 frame/s liên tục 5 phút — RAM không tăng, `dropped_frames` tăng monoton, không crash
4. Đóng cửa sổ trong khi đang upload — `closeEvent()` gọi `disconnect()` trước
5. Nạp file A2L không hợp lệ — hiện thông báo, app tiếp tục dùng được
6. Kết nối ECU không có CAL page — không crash, ẩn/disable tính năng calibration
7. Ghi giá trị vượt range (trên Reference page) — `WriteProtectedError` flow
8. Timestamp rollover (giả lập bằng fakeslave) — elapsed time không reset về 0 hoặc nhảy âm
9. Mở/đóng connection nhanh 10 lần liên tiếp — không deadlock, không leak thread
10. `Ctrl+C` trong terminal khi app đang chạy — thoát clean

---

## 7. M4 — DAQ engine + Measurement scope (kế hoạch gốc, ĐÃ XONG — xem §4)

Giữ lại nguyên văn bản kế hoạch gốc (D4a–D4e) làm tài liệu tham chiếu thiết kế —
kết quả thực tế, kể cả những gì phát sinh ngoài kế hoạch, nằm ở §4.

**Mục tiêu:** Người dùng chọn signals từ A2L → xcptool cấu hình DAQ list trên ECU → hiển thị real-time trên pyqtgraph scope.

**Thứ tự bắt buộc: D4a phải xong + test xanh trước khi bắt đầu D4b.**

<details>
<summary>D4a–D4e (bấm để xem chi tiết kế hoạch gốc)</summary>

### D4a — `pack_odts()` + unit tests (backend)

File: `master/daq.py` (mới) — chỉ logic packing, không đụng bus.

Implement thuật toán đã fix trong `DESIGN.md §4.3` — tách `small/large`, ODT 0 riêng, ODT 1+ first-fit-decreasing. Không copy thuật toán cũ trong DESIGN.md — cái đó có bug (ODT 0 rỗng hệ thống).

Unit test bắt buộc trước khi viết gì thêm:
- Hai signal 1B+2B, timestamp bật → ODT 0 = `[2B, 1B]` (tổng 3B ≤ budget)
- Signal 4B, timestamp bật → ODT 0 rỗng, signal 4B ở ODT 1 — KHÔNG raise
- Signal 8B → `ValueError`
- Timestamp tắt → first_budget = rest_budget = 7
- Mix: signal 4B + 2B + 1B, timestamp bật → ODT 0: `[2B,1B]`, ODT 1: `[4B]`

### D4b — DAQ allocation + `start_daq` / `stop_daq` (backend)

File: `master/daq.py` — thêm `alloc_daq`, `configure_daq`, `start_daq`, `stop_daq`.

Trình tự cấu hình: `FREE_DAQ → ALLOC_DAQ → ALLOC_ODT → ALLOC_ODT_ENTRY → WRITE_DAQ → SET_DAQ_LIST_MODE → START_STOP_DAQ_LIST(select) → START_STOP_SYNCH`. Sai thứ tự → `CRC_SEQUENCE` từ slave.

Thu thập `first_pid` từ `START_STOP_DAQ_LIST(mode=2)`. Dựng bảng phẳng `pid → (daq_list, odt_idx, signals, frame_offset)` — tra bảng O(1) trong RX loop.

Integration test với fakeslave.

### D4c — DTO decoder + timestamp rollover (backend)

File: `master/daq.py` — `decode_dto(frame, pid_table) → list[SamplePoint]`.

- Mask `PID & 0x7F` (bit 7 = overrun).
- Timestamp chỉ có trong ODT 0 — đọc 4 byte @ offset 1, unit 10ns/tick.
- Rollover 32-bit sau 42,9 giây: cộng dồn số lần tràn, không để `elapsed` reset.
- `SamplePoint(name, timestamp_ns, value_raw: bytes, datatype)` — UI tự decode hiển thị.

### D4d — Session contract additions (lead)

File: `session/api.py` (lead-owned).

Thêm:
- `start_daq(lists: list[DaqList])` — chặn, cấu hình + START_STOP_SYNCH
- `stop_daq()` — chặn, STOP_SYNCH
- `drain_daq(n) → list[SamplePoint]` — non-blocking, pop từ DAQ ring buffer

Cập nhật `fake.py`, `real.py` cho phù hợp.

### D4e — MeasurementView + tích hợp UI

File: `ui/measurement_view.py` (mới).

- Signal tree: checkbox chọn signals từ `session.symbols.measurements`
- pyqtgraph `PlotWidget`, nhiều đường (mỗi signal 1 màu)
- `QTimer 40ms` → `drain_daq()` → append điểm → `update()`
- Nút Start/Stop DAQ trong MainWindow (hoặc trong MeasurementView toolbar)
- Navigation sidebar: tab "Đo lường" cạnh "Hiệu chỉnh"

</details>

---

## 8. Kế hoạch M5 (Fix bug, UX & Performance Improvement)

Đã hoàn thành trong M5:
- [x] **Tối ưu hiệu năng MeasurementView**:
  - Dùng NumPy `np.fromiter()` thay list comprehension, tránh allocate list 3000 phần tử mỗi 40ms.
  - Bật `useOpenGL=True` (PyOpenGL) offload render sang GPU, giảm tải tối đa cho UI thread.
  - Bỏ qua `setData()` khi không có điểm mới (`_drawn_len`).
- [x] **Tự động mở rộng Array signal (`MATRIX_DIM`)**:
  - Tự động tách `torqueSamples[4]` thành `[0]..[3]` với địa chỉ và size chuẩn, khắc phục `ValueError: 16B > max 7B/ODT`.
- [x] **Cột Live Value & Nút Switch bật/tắt đồ thị (Scope)**:
  - Thêm cột `Giá trị` (COL_VALUE) hiển thị trực tiếp số thực thời gian thực trên tree widget.
  - Thêm `SwitchButton` bật/tắt đồ thị: khi tắt, ẩn scope và bỏ qua 100% việc vẽ curve, siêu nhẹ CPU/GPU.
- [x] **Phân cấp Struct & Array cho cả MeasurementView và CalibrationView**:
  - `MeasurementView`: Tự động gom nhóm các signal struct (`speedPidTelemetry_*`) thành node cha có 1 Checkbox duy nhất, các con không checkbox; Array `[0]..[n-1]` mở rộng dưới cha.
  - `CalibrationView`: Gom nhóm struct `speedPid_*` thành node cha `STRUCT (N)`; Array `VAL_BLK` mở rộng thành các dòng con `[0]..[n-1]` cho phép double-click sửa riêng từng ô giá trị và tự động đồng bộ dòng cha.
- [x] **Đồng bộ trạng thái Data Bitrate khi bật Custom Bit Timing**:
  - Tự động khóa `data_bitrate_combo` khi bật chế độ bit timing tùy chỉnh; áp dụng pattern đồng bộ trạng thái trung tâm `ui_state_sync`.
- [x] **Hỗ trợ định dạng & nhập liệu HEX / BIN / ASCII cho Float và Int**:
  - Hỗ trợ xem bit pattern IEEE 754 cho `FLOAT32_IEEE` và `FLOAT64_IEEE` dưới dạng HEX, BIN, ASCII.
  - Hỗ trợ gõ trực tiếp ký tự ASCII (ví dụ: `'H'`) khi hiệu chỉnh ghi xuống ECU.
- [x] **Hiển thị tên phần cứng chi tiết của CAN Channel**:
  - Trích xuất tên thiết bị cụ thể từ driver (ví dụ: `Vector XL — 4 · VN5620A Channel 5`) giúp nhận diện trực quan trên danh sách thiết bị.

### 📌 Vấn đề cần đào sâu nghiên cứu tiếp (Session tiếp theo):
- **Hiện tượng**: Ngay sau khi bấm "Bắt đầu đo" (Start DAQ), UI bị lag / khựng một khoảng thời gian ngắn rồi mới dần ổn định (kể cả khi đã tắt chế độ vẽ Scope).
- **Nguyên nhân nghi vấn**:
  1. *Flood frame DTO vào `TraceView`*: DTO frame bắn về liên tục 100Hz–200Hz. Mặc định `TraceView` đang tick bật loại `DAQ`, dẫn đến `TraceModel.append()` và `table.scrollToBottom()` bị gọi dồn dập trên UI thread dù user đang ở tab khác.
  2. *Backlog bộ đệm RX*: Trong thời gian worker gửi chuỗi lệnh XCP cấu hình DAQ (`FREE_DAQ` $\rightarrow$ `ALLOC_*` $\rightarrow$ `START_STOP_SYNCH`), CAN frames dồn ứ lại và bị `drain_trace()` / `drain_daq()` xả một lượng khổng lồ ở 1–2 nhịp timer đầu tiên.
- **Hướng giải pháp dự kiến**:
  - Bỏ chọn mặc định loại `DAQ` trong bộ lọc `TraceView` (chỉ bật `CMD`, `RES`, `ERR`, `EV`).
  - Không gọi `table.scrollToBottom()` / repaint khi `TraceView` đang bị ẩn (không active).
  - Áp dụng batch throttling khi xả hàng đợi trace lúc khởi động.

### 🐛 Danh sách Bug tạm hoãn để fix sau:
1. **Window chính không nhảy theo menu Navigation**:
   - *Hiện tượng*: Khi click chuyển tab trên thanh Navigation bên trái (hoặc lúc khởi động), widget chính trong `QStackedWidget` không chuyển đổi tương ứng.
   - *Hướng xử lý*: Kiểm tra lại cơ chế binding / signal routing giữa `NavigationInterface` của `qfluentwidgets` và `QStackedWidget`.
2. **Lỗi Dark Theme khi DockWidget ở chế độ Floating**:
   - *Hiện tượng*: Khi kéo `QDockWidget` ("CAN Trace", "Raw Commands") ra ngoài thành cửa sổ nổi (floating/top-level window), Windows ép palette về mặc định gây hiện tượng nền trắng chữ trắng.
   - *Hướng xử lý*: Bắt signal `topLevelChanged(bool)` trên các `QDockWidget` để áp dụng theme động hoặc cấu hình lại stylesheet/palette cấp OS-window khi dock chuyển trạng thái float.

---

## 9. Deferred (ứng viên cho M5+, chưa ưu tiên)

| Hạng mục | Lý do hoãn | Ghi chú |
|---|---|---|
| MDF4 export | Cần thư viện asammdf (~10MB), không cần cho demo | M5 |
| Scripting / automation | Scope mở rộng, cần thiết kế API riêng | M5 |
| XCP on Ethernet | Transport khác, không ảnh hưởng core | M5 |
| Multi-window INCA style | Cần QMdiArea hoặc multiple MainWindow | Sau M5 |
| Test trên board AURIX thật | Cần hardware, CI không có | Manual |
| CLI xcptool command | Low priority, FakeSession test đủ | M5 |
| Soak 30 phút đầy đủ (J2) | Đã có 5 phút sạch, đủ cho M1–M3 | Trước release |
| PySide6-Fluent-Widgets license | Dual GPLv3/thương mại | Xác nhận trước M5 nếu dùng thương mại |
