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
- [x] **Đồng bộ theme cho cả 3 docking window (title bar + nền + tab bar)** (2026-08-22):
  - *Nguyên nhân thật* (khác hẳn phỏng đoán "Windows ép palette" trước đây): `QDockWidget` không có rule `background` trong `CHROME_QSS_DARK/LIGHT` (chỉ có `border`) — khi docked thì "chìm" trong nền tối của MainWindow nên không lộ ra, nhưng khi **float** thành cửa sổ top-level riêng thì phải tự vẽ nền của chính nó, và rơi về mặc định sáng của Windows.
  - Thêm `background`/`color` cho `QDockWidget` vào `theme.py`. Riêng dock "Memory / Debug" còn dùng title bar gốc của Qt (`QDockWidget::title`) — sub-control này **không tự kế thừa** `color`/`background` từ selector `QDockWidget` cha nên vẫn trắng dù đã sửa nền — chuyển nó sang title bar custom (QWidget/QLabel) giống "CAN Trace"/"Raw Commands" để cả 3 dock nhất quán.
  - Bonus: thêm QSS cho `QTabBar` (tab lúc các dock docked chung khay) — trước đó dùng giao diện tab mặc định Windows, lệch hẳn theme tối.
- [x] **Đồng bộ UX bật/tắt cho cả 3 dock** (2026-08-22): "CAN Trace"/"Raw Commands" giờ cũng `closable=True` (có nút ✕) như "Memory / Debug"; ngược lại "Memory / Debug" giờ cũng có nút mũi tên thu/mở vùng debug — cả 3 dock dùng chung `toggle_debug_area()` vì chúng tabify chung một vùng.
- [x] **Sửa desync giữa Navigation highlight và nội dung hiển thị** (2026-08-22):
  - *Nguyên nhân thật*: KHÔNG phải lỗi binding `NavigationInterface`↔`QStackedWidget` như phỏng đoán ban đầu (`switch_to()` + `onClick` đã đúng, có test cover). Thủ phạm là `_after_a2l_load()` gọi `switch_to(self.calibration_view)` **vô điều kiện** — kể cả khi được trigger bởi auto-load A2L lúc khởi động (`QTimer.singleShot(50, ...)` sau khi `_build_navigation()` đã restore đúng `active_route`), ghi đè tab vừa restore mà không đồng bộ lại `nav.setCurrentItem()`.
  - Fix: bỏ hẳn dòng auto-switch trong `_after_a2l_load()` — `set_database()` đã cập nhật dữ liệu cho cả Calibration lẫn Measurement view rồi nên không cần ép chuyển tab.

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

Không còn bug tồn đọng nào được ghi nhận tại đây — 2 bug trước đó (Window chính
không nhảy theo Navigation; Dark theme vỡ khi Dock floating) đã fix, xem mục
"Đã hoàn thành trong M5" ở trên.

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
| Winamp/Y2K skeuomorphic theme | Ý tưởng thẩm mỹ, không phục vụ mục tiêu M5; đọc số liệu chính xác quan trọng hơn hiệu ứng bevel/LCD font | Effort ước tính (2026-08-22): Mức 1 "retro tint" (chỉnh gradient trong `theme.py`) ~1–2 ngày; Mức 2 skeuomorphic đầy đủ (thay/custom-paint từng widget `qfluentwidgets`, vì lib này tự vẽ chứ không thuần QSS) ~1–2 tuần; Mức 3 "đúng chất" Winamp (borderless window tự vẽ, bitmap skin) ~3–4 tuần+, rủi ro cao |

---

## 10. Kế hoạch tiếp theo — A2L struct thật (TYPEDEF_STRUCTURE/INSTANCE)

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. Mark each `- [x]` as it lands.

**Trạng thái: hoàn thành (2026-09-16).** Full suite: 500/500 pass (`pytest tests/ -x -q`).

**Goal:** Thay `_group_by_prefix` (đoán "struct" từ tên tham số, 2 bản độc
lập ở `calibration_view.py`/`measurement_view.py`) bằng dữ liệu struct THẬT
đọc từ ASAP2 `TYPEDEF_STRUCTURE`/`STRUCTURE_COMPONENT`/`TYPEDEF_CHARACTERISTIC`/
`TYPEDEF_MEASUREMENT`/`INSTANCE` — không còn fallback đoán theo tên cho bất
kỳ file nào.

**Architecture:** `a2l/parser.py` đọc 5 block ASAP2 mới thành dataclass mới
trong `a2l/types.py`. `a2l/database.py` resolve đệ quy (struct lồng struct,
mảng struct/component) thành `Characteristic`/`Measurement` thật (địa chỉ
tuyệt đối) trong các dict hiện có — session/master/transport không đổi gì.
Resolve cũng dựng luôn cây hiển thị (`InstanceNode`) để `CalibrationView`/
`MeasurementView` không phải tự suy lại địa chỉ/tên phân cấp (xem spec §10 —
phát hiện lúc viết plan này, spec gốc để UI tự suy, rủi ro trùng logic 3 nơi).

**Tech Stack:** Python 3.12 dataclasses, parser tự viết sẵn có (không thêm
dependency), pytest + pytest-qt cho UI.

**Spec:** [`docs/superpowers/specs/2026-09-11-a2l-struct-typedef-design.md`](docs/superpowers/specs/2026-09-11-a2l-struct-typedef-design.md)
— đọc CẢ spec lẫn phần dưới đây; plan lập luận dựa trên spec, không lặp lại
phần lý thuyết (ngữ pháp ASAP2 đầy đủ nằm ở spec §3).

### Ràng buộc chung (áp dụng cho MỌI task dưới đây)

- Venv: `xcptool\.venv\Scripts\python.exe`, không phải `python` trần.
- `QT_QPA_PLATFORM=offscreen` cho mọi test UI (đã set sẵn trong
  `tests/ui/conftest.py` — không cần set tay).
- Sau MỖI task: chạy đúng test file vừa đụng trước, roll-up cả
  `pytest tests/ -x -q` cuối task 9 (hết phase 1), cuối task 12 (hết
  phase 2), cuối task 14 (hết phase 3) — không được đỏ mới coi task xong.
- Không renumber section nào trong `DEV_PLAN.md`/`DESIGN.md` — bị code
  comment tham chiếu theo số (`DEV_PLAN.md §3/§5.1/§6/§7`, `DESIGN.md §5`).
- Không sửa `examples/xcp_daq_example.a2l` (file chia sẻ, nhiều test khác
  đếm số lượng CHARACTERISTIC/MEASUREMENT cố định trong đó) — mọi A2L text
  dùng để test tính năng struct-typedef mới là snippet tự tạo trong test,
  không load từ file chung.

---

### Task 1: Data model — 5 dataclass mới + field mới trên `A2LDatabase`

**Files:**
- Modify: `src/xcptool/a2l/types.py` (chèn sau `Characteristic`, trước `XcpProtocolInfo` — hiện ở dòng 73; thêm field vào `A2LDatabase`, hiện bắt đầu dòng 85)
- Test: `tests/unit/test_a2l_parser.py` (thêm cuối file — dataclass thuần, không cần fixture `db`)

**Interfaces:**
- Produces: `StructComponent(name, type_name, offset, matrix_dim=[])` với `.array_size` (property); `StructTypeDef(name, size, components=[])`; `CharacteristicTypeDef(name, description, char_type, record_layout, lower_limit, upper_limit, compu_method="NO_COMPU_METHOD", array_size=1, datatype=None)`; `MeasurementTypeDef(name, description, datatype, lower_limit, upper_limit, compu_method="NO_COMPU_METHOD", matrix_dim=[])` với `.array_size`; `Instance(name, description, type_name, address, matrix_dim=[])` với `.array_size`; `InstanceNode(name, address, leaf_name, is_measurement, struct_size, children=[])`. `A2LDatabase` có thêm `struct_types`, `characteristic_types`, `measurement_types`, `instances`, `instance_trees` — đều `dict[str, T]` mặc định rỗng.

- [ ] **Step 1: Viết test thất bại**

```python
def test_struct_typedef_dataclasses_exist_with_defaults() -> None:
    from xcptool.a2l.types import (
        A2LDatabase, CharacteristicTypeDef, Instance, InstanceNode,
        MeasurementTypeDef, StructComponent, StructTypeDef,
    )
    comp = StructComponent(name="kp", type_name="T_Float", offset=0)
    assert comp.array_size == 1
    comp_arr = StructComponent(name="samples", type_name="T_I16", offset=4, matrix_dim=[3])
    assert comp_arr.array_size == 3

    struct = StructTypeDef(name="PidTelemetry_t", size=12, components=[comp, comp_arr])
    assert struct.components == [comp, comp_arr]

    ctd = CharacteristicTypeDef(
        name="T_Float", description="", char_type="VALUE",
        record_layout="RL_F32", lower_limit=0.0, upper_limit=1.0)
    assert ctd.array_size == 1 and ctd.datatype is None

    mtd = MeasurementTypeDef(
        name="T_I16", description="", datatype="SWORD",
        lower_limit=-100.0, upper_limit=100.0)
    assert mtd.array_size == 1

    inst = Instance(name="tel", description="", type_name="PidTelemetry_t", address=0x1000)
    assert inst.array_size == 1

    node = InstanceNode(name="tel", address=0x1000, leaf_name=None,
                        is_measurement=False, struct_size=12)
    assert node.children == []

    db = A2LDatabase()
    assert db.struct_types == {} and db.characteristic_types == {}
    assert db.measurement_types == {} and db.instances == {}
    assert db.instance_trees == {}
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_parser.py::test_struct_typedef_dataclasses_exist_with_defaults -v`
Expected: FAIL — `ImportError: cannot import name 'StructComponent'`

- [ ] **Step 3: Thêm dataclass vào `types.py`**

Chèn ngay sau dòng 71 (`return DATATYPE_SIZES.get(self.datatype, 1) * self.array_size` — cuối `Characteristic.byte_size`), trước `@dataclass\nclass XcpProtocolInfo:`:

```python
@dataclass
class StructComponent:
    """Một thành viên của TYPEDEF_STRUCTURE — ASAP2 STRUCTURE_COMPONENT."""
    name: str
    type_name: str        # -> StructTypeDef | CharacteristicTypeDef | MeasurementTypeDef, theo tên
    offset: int
    matrix_dim: list[int] = field(default_factory=list)

    @property
    def array_size(self) -> int:
        s = 1
        for d in self.matrix_dim:
            s *= d
        return s


@dataclass
class StructTypeDef:
    """ASAP2 TYPEDEF_STRUCTURE — một KIỂU struct, không phải instance đã đặt."""
    name: str
    size: int              # byte size khai thật trong A2L — không tự tính
    components: list[StructComponent] = field(default_factory=list)


@dataclass
class CharacteristicTypeDef:
    """ASAP2 TYPEDEF_CHARACTERISTIC — giống Characteristic, bỏ `address`
    (là template STRUCTURE_COMPONENT/INSTANCE tham chiếu tới, không phải giá
    trị đã đặt vào bộ nhớ)."""
    name: str
    description: str
    char_type: str
    record_layout: str
    lower_limit: float
    upper_limit: float
    compu_method: str = "NO_COMPU_METHOD"
    array_size: int = 1
    datatype: DataType | None = None


@dataclass
class MeasurementTypeDef:
    """ASAP2 TYPEDEF_MEASUREMENT — giống Measurement, bỏ `address`."""
    name: str
    description: str
    datatype: DataType
    lower_limit: float
    upper_limit: float
    compu_method: str = "NO_COMPU_METHOD"
    matrix_dim: list[int] = field(default_factory=list)

    @property
    def array_size(self) -> int:
        s = 1
        for d in self.matrix_dim:
            s *= d
        return s


@dataclass
class Instance:
    """ASAP2 INSTANCE — đặt một TYPEDEF_* vào địa chỉ ECU thật."""
    name: str
    description: str
    type_name: str          # -> StructTypeDef | CharacteristicTypeDef | MeasurementTypeDef
    address: int
    matrix_dim: list[int] = field(default_factory=list)

    @property
    def array_size(self) -> int:
        s = 1
        for d in self.matrix_dim:
            s *= d
        return s


@dataclass
class InstanceNode:
    """Cây đã resolve cho 1 INSTANCE — dựng bởi a2l/database.py duy nhất;
    UI chỉ đọc, không tự suy địa chỉ/tên phân cấp (xem spec §10)."""
    name: str                  # tên phân cấp đầy đủ, VD "grp.member[0]"
    address: int
    leaf_name: str | None      # key trong characteristics/measurements nếu là lá; None nếu là struct/mảng cha
    is_measurement: bool       # leaf_name thuộc measurements (True) hay characteristics (False) — vô nghĩa nếu leaf_name None
    struct_size: int | None    # StructTypeDef.size thật nếu node này là struct cha; None nếu không phải
    children: list["InstanceNode"] = field(default_factory=list)
```

Thêm field vào `A2LDatabase` (chèn trước `protocol_info`, giữ `protocol_info` là field cuối như hiện tại):

```python
@dataclass
class A2LDatabase:
    measurements: dict[str, Measurement] = field(default_factory=dict)
    characteristics: dict[str, Characteristic] = field(default_factory=dict)
    record_layouts: dict[str, RecordLayout] = field(default_factory=dict)
    struct_types: dict[str, StructTypeDef] = field(default_factory=dict)
    characteristic_types: dict[str, CharacteristicTypeDef] = field(default_factory=dict)
    measurement_types: dict[str, MeasurementTypeDef] = field(default_factory=dict)
    instances: dict[str, Instance] = field(default_factory=dict)
    instance_trees: dict[str, InstanceNode] = field(default_factory=dict)
    protocol_info: XcpProtocolInfo | None = None
```

- [ ] **Step 4: Chạy lại, xác nhận PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_parser.py -v`
Expected: PASS toàn bộ (test cũ + test mới)

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/a2l/types.py xcptool/tests/unit/test_a2l_parser.py
git commit -m "feat(xcptool): add ASAP2 struct-typedef dataclasses to a2l/types.py"
```

---

### Task 2: Parser — `TYPEDEF_STRUCTURE`/`STRUCTURE_COMPONENT` + gộp `MATRIX_DIM` helper

**Files:**
- Modify: `src/xcptool/a2l/parser.py`
- Test: `tests/unit/test_a2l_parser.py`

**Interfaces:**
- Consumes: `StructTypeDef`, `StructComponent` (Task 1).
- Produces: `_extract_matrix_dim(tokens: list[str]) -> list[int]` (helper dùng lại ở Task 4, Task 5); `_extract_struct_type(b: _Block) -> StructTypeDef | None`; `_extract_struct_component(b: _Block) -> StructComponent | None`; `db.struct_types[name] -> StructTypeDef` sau `parse()`.

- [ ] **Step 1: Viết test thất bại**

```python
def test_typedef_structure_parses_components_and_matrix_dim() -> None:
    from xcptool.a2l.parser import parse
    text = """
    /begin TYPEDEF_STRUCTURE PidTelemetry_t "PID telemetry" 0x10
        /begin STRUCTURE_COMPONENT error T_Float32 0x0
        /end STRUCTURE_COMPONENT
        /begin STRUCTURE_COMPONENT samples T_I16 0x4
            MATRIX_DIM 3
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    """
    db = parse(text)
    struct = db.struct_types["PidTelemetry_t"]
    assert struct.size == 0x10
    assert [c.name for c in struct.components] == ["error", "samples"]
    assert struct.components[0].type_name == "T_Float32"
    assert struct.components[0].offset == 0
    assert struct.components[0].matrix_dim == []
    assert struct.components[1].offset == 4
    assert struct.components[1].matrix_dim == [3]
    assert struct.components[1].array_size == 3
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_parser.py::test_typedef_structure_parses_components_and_matrix_dim -v`
Expected: FAIL — `KeyError: 'PidTelemetry_t'` (chưa parse block này, `struct_types` rỗng)

- [ ] **Step 3: Thêm helper `_extract_matrix_dim` + extractor, tái dùng cho `_extract_measurement`**

Trong `parser.py`, thêm helper NGAY TRƯỚC `_extract_measurement` (tránh trùng logic — `_extract_measurement` hiện tự lặp tìm `MATRIX_DIM` inline, sửa nó gọi helper chung):

```python
def _extract_matrix_dim(t: list[str]) -> list[int]:
    """MATRIX_DIM <n> [<m> …] — 0 hoặc nhiều số nguyên theo sau keyword."""
    for i, tok in enumerate(t):
        if tok == "MATRIX_DIM":
            dims: list[int] = []
            j = i + 1
            while j < len(t):
                try:
                    dims.append(int(t[j]))
                    j += 1
                except ValueError:
                    break
            return dims
    return []
```

Sửa `_extract_measurement` — thay đoạn vòng lặp `MATRIX_DIM` inline (dòng ~192-203 hiện tại) bằng:

```python
    matrix_dim = _extract_matrix_dim(t)
```

(xoá 10 dòng vòng lặp thủ công cũ, hành vi giữ nguyên y hệt — `test_torqueSamples_matrix_dim` đã cover).

Thêm 2 extractor mới, đặt ngay sau `_extract_measurement`:

```python
def _extract_struct_component(b: _Block) -> StructComponent | None:
    t = b.tokens
    if len(t) < 3:
        return None
    return StructComponent(
        name=t[0], type_name=t[1], offset=_to_int(t[2]),
        matrix_dim=_extract_matrix_dim(t),
    )


def _extract_struct_type(b: _Block) -> StructTypeDef | None:
    t = b.tokens
    if len(t) < 3:
        return None
    components = [
        c for c in (
            _extract_struct_component(child)
            for child in b.children if child.name == "STRUCTURE_COMPONENT"
        ) if c is not None
    ]
    return StructTypeDef(name=t[0], size=_to_int(t[2]), components=components)
```

Cập nhật import ở đầu file:
```python
from .types import (
    A2LDatabase, Characteristic, Instance, InstanceNode, Measurement,
    RecordLayout, StructComponent, StructTypeDef, XcpProtocolInfo,
)
```
(giữ chỗ cho `Instance`/`InstanceNode` — dùng ở Task 5; import thừa trước khi dùng không lỗi, chỉ là import sớm).

Thêm case trong `_visit()` (`parse()`), đặt cạnh case `RECORD_LAYOUT`:

```python
        elif block.name == "TYPEDEF_STRUCTURE":
            try:
                st = _extract_struct_type(block)
                if st:
                    db.struct_types[st.name] = st
            except Exception as exc:
                _log.warning("Skipping TYPEDEF_STRUCTURE %r: %s", bname, exc)
```

- [ ] **Step 4: Chạy lại toàn bộ file test, xác nhận PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_parser.py -v`
Expected: PASS toàn bộ, kể cả `test_torqueSamples_matrix_dim` (đảm bảo refactor helper không đổi hành vi)

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/a2l/parser.py xcptool/tests/unit/test_a2l_parser.py
git commit -m "feat(xcptool): parse TYPEDEF_STRUCTURE/STRUCTURE_COMPONENT"
```

---

### Task 3: Parser — `TYPEDEF_CHARACTERISTIC`

**Files:**
- Modify: `src/xcptool/a2l/parser.py`
- Test: `tests/unit/test_a2l_parser.py`

**Interfaces:**
- Consumes: `CharacteristicTypeDef` (Task 1), `_to_int`/`_to_float` (đã có).
- Produces: `_extract_characteristic_type(b: _Block) -> CharacteristicTypeDef | None`; `db.characteristic_types[name] -> CharacteristicTypeDef`.

- [ ] **Step 1: Viết test thất bại**

```python
def test_typedef_characteristic_parses_like_characteristic_minus_address() -> None:
    from xcptool.a2l.parser import parse
    text = """
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain leaf type" VALUE RL_F32 0 CM_LINEAR 0.0 10.0
    /end TYPEDEF_CHARACTERISTIC
    """
    db = parse(text)
    ct = db.characteristic_types["T_Gain"]
    assert ct.char_type == "VALUE"
    assert ct.record_layout == "RL_F32"
    assert ct.compu_method == "CM_LINEAR"
    assert ct.lower_limit == 0.0 and ct.upper_limit == 10.0
    assert ct.array_size == 1
    assert ct.datatype is None  # resolve() (Task 6) mới điền
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_parser.py::test_typedef_characteristic_parses_like_characteristic_minus_address -v`
Expected: FAIL — `KeyError: 'T_Gain'`

- [ ] **Step 3: Thêm extractor + hook `_visit()`**

Đặt ngay sau `_extract_characteristic`:

```python
def _extract_characteristic_type(b: _Block) -> CharacteristicTypeDef | None:
    t = b.tokens
    if len(t) < 8:
        return None
    number_tok = b.get("NUMBER", 1)
    return CharacteristicTypeDef(
        name=t[0], description=t[1].strip('"'), char_type=t[2],
        record_layout=t[3], compu_method=t[5],
        lower_limit=_to_float(t[6]), upper_limit=_to_float(t[7]),
        array_size=int(number_tok[0]) if number_tok else 1,
    )
```

Thêm `CharacteristicTypeDef` vào import từ `.types`. Thêm case trong `_visit()`:

```python
        elif block.name == "TYPEDEF_CHARACTERISTIC":
            try:
                ct = _extract_characteristic_type(block)
                if ct:
                    db.characteristic_types[ct.name] = ct
            except Exception as exc:
                _log.warning("Skipping TYPEDEF_CHARACTERISTIC %r: %s", bname, exc)
```

- [ ] **Step 4: Chạy lại, xác nhận PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_parser.py -v`
Expected: PASS toàn bộ

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/a2l/parser.py xcptool/tests/unit/test_a2l_parser.py
git commit -m "feat(xcptool): parse TYPEDEF_CHARACTERISTIC"
```

---

### Task 4: Parser — `TYPEDEF_MEASUREMENT`

**Files:**
- Modify: `src/xcptool/a2l/parser.py`
- Test: `tests/unit/test_a2l_parser.py`

**Interfaces:**
- Consumes: `MeasurementTypeDef` (Task 1), `_extract_matrix_dim` (Task 2).
- Produces: `_extract_measurement_type(b: _Block) -> MeasurementTypeDef | None`; `db.measurement_types[name] -> MeasurementTypeDef`.

- [ ] **Step 1: Viết test thất bại**

```python
def test_typedef_measurement_parses_matrix_dim() -> None:
    from xcptool.a2l.parser import parse
    text = """
    /begin TYPEDEF_MEASUREMENT T_Samples "sample leaf type" SWORD CM_NONE 0 0 -100 100
        MATRIX_DIM 4
    /end TYPEDEF_MEASUREMENT
    """
    db = parse(text)
    mt = db.measurement_types["T_Samples"]
    assert mt.datatype == "SWORD"
    assert mt.lower_limit == -100.0 and mt.upper_limit == 100.0
    assert mt.matrix_dim == [4]
    assert mt.array_size == 4
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_parser.py::test_typedef_measurement_parses_matrix_dim -v`
Expected: FAIL — `KeyError: 'T_Samples'`

- [ ] **Step 3: Thêm extractor + hook**

Đặt ngay sau `_extract_measurement`:

```python
def _extract_measurement_type(b: _Block) -> MeasurementTypeDef | None:
    t = b.tokens
    if len(t) < 8:
        return None
    return MeasurementTypeDef(
        name=t[0], description=t[1].strip('"'), datatype=t[2],
        compu_method=t[3], lower_limit=_to_float(t[6]), upper_limit=_to_float(t[7]),
        matrix_dim=_extract_matrix_dim(t),
    )
```

Thêm `MeasurementTypeDef` vào import từ `.types`. Thêm case trong `_visit()`:

```python
        elif block.name == "TYPEDEF_MEASUREMENT":
            try:
                mt = _extract_measurement_type(block)
                if mt:
                    db.measurement_types[mt.name] = mt
            except Exception as exc:
                _log.warning("Skipping TYPEDEF_MEASUREMENT %r: %s", bname, exc)
```

- [ ] **Step 4: Chạy lại, xác nhận PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_parser.py -v`

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/a2l/parser.py xcptool/tests/unit/test_a2l_parser.py
git commit -m "feat(xcptool): parse TYPEDEF_MEASUREMENT"
```

---

### Task 5: Parser — `INSTANCE`

**Files:**
- Modify: `src/xcptool/a2l/parser.py`
- Test: `tests/unit/test_a2l_parser.py`

**Interfaces:**
- Consumes: `Instance` (Task 1), `_extract_matrix_dim` (Task 2).
- Produces: `_extract_instance(b: _Block) -> Instance | None`; `db.instances[name] -> Instance`.

- [ ] **Step 1: Viết test thất bại**

```python
def test_instance_parses_type_ref_address_and_array() -> None:
    from xcptool.a2l.parser import parse
    text = """
    /begin INSTANCE speedPidTelemetry "PID telemetry instance" PidTelemetry_t 0x90001000
    /end INSTANCE
    /begin INSTANCE tempSensors "sensor array" T_Gain 0x90002000
        MATRIX_DIM 3
    /end INSTANCE
    """
    db = parse(text)
    inst = db.instances["speedPidTelemetry"]
    assert inst.type_name == "PidTelemetry_t"
    assert inst.address == 0x90001000
    assert inst.array_size == 1

    arr_inst = db.instances["tempSensors"]
    assert arr_inst.matrix_dim == [3]
    assert arr_inst.array_size == 3
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_parser.py::test_instance_parses_type_ref_address_and_array -v`
Expected: FAIL — `KeyError: 'speedPidTelemetry'`

- [ ] **Step 3: Thêm extractor + hook**

Đặt ngay sau `_extract_struct_type` (hoặc bất kỳ đâu cạnh nhóm extractor mới):

```python
def _extract_instance(b: _Block) -> Instance | None:
    t = b.tokens
    if len(t) < 4:
        return None
    return Instance(
        name=t[0], description=t[1].strip('"'), type_name=t[2],
        address=_to_int(t[3]), matrix_dim=_extract_matrix_dim(t),
    )
```

Thêm case trong `_visit()`:

```python
        elif block.name == "INSTANCE":
            try:
                inst = _extract_instance(block)
                if inst:
                    db.instances[inst.name] = inst
            except Exception as exc:
                _log.warning("Skipping INSTANCE %r: %s", bname, exc)
```

(`Instance` đã có sẵn trong import từ Task 2.)

- [ ] **Step 4: Chạy lại, xác nhận PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_parser.py -v`

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/a2l/parser.py xcptool/tests/unit/test_a2l_parser.py
git commit -m "feat(xcptool): parse INSTANCE"
```

---

### Task 6: Resolution — mở rộng `_resolve()` để resolve luôn `characteristic_types`

**Files:**
- Modify: `src/xcptool/a2l/database.py`
- Test: `tests/unit/test_a2l_database.py` (file mới — resolution chưa có test file riêng)

**Interfaces:**
- Consumes: `db.characteristic_types` (Task 3), `db.record_layouts` (đã có).
- Produces: `CharacteristicTypeDef.datatype` được điền — cần thiết TRƯỚC Task 8 (struct resolution cần biết size thật của leaf template).

- [ ] **Step 1: Viết test thất bại**

```python
"""Unit tests cho a2l/database.py — resolve() và struct-instance resolution."""
from __future__ import annotations

from xcptool.a2l.database import load
from xcptool.a2l.parser import parse
from xcptool.a2l.types import A2LDatabase


def _resolve(text: str) -> A2LDatabase:
    """Parse + chạy đúng pipeline resolve của load() (không cần file thật)."""
    from xcptool.a2l.database import _resolve as resolve_fn
    db = parse(text)
    resolve_fn(db)
    return db


def test_resolve_fills_datatype_for_characteristic_type_templates() -> None:
    db = _resolve("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_LINEAR 0.0 10.0
    /end TYPEDEF_CHARACTERISTIC
    """)
    assert db.characteristic_types["T_Gain"].datatype == "FLOAT32_IEEE"
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_database.py::test_resolve_fills_datatype_for_characteristic_type_templates -v`
Expected: FAIL — `assert None == "FLOAT32_IEEE"`

- [ ] **Step 3: Sửa `_resolve()`**

```python
def _resolve(db: A2LDatabase) -> None:
    """Propagate RecordLayout.datatype → Characteristic.datatype (và tương tự
    cho CharacteristicTypeDef — struct-leaf template cần datatype thật
    TRƯỚC khi _resolve_instances() cần tính byte size của nó)."""
    for char in db.characteristics.values():
        rl = db.record_layouts.get(char.record_layout)
        if rl:
            char.datatype = rl.datatype
    for tmpl in db.characteristic_types.values():
        rl = db.record_layouts.get(tmpl.record_layout)
        if rl:
            tmpl.datatype = rl.datatype
```

- [ ] **Step 4: Chạy lại, xác nhận PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_database.py tests/unit/test_a2l_parser.py -v`

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/a2l/database.py xcptool/tests/unit/test_a2l_database.py
git commit -m "feat(xcptool): resolve datatype for TYPEDEF_CHARACTERISTIC templates too"
```

---

### Task 7: Resolution — INSTANCE phẳng (không struct, không mảng), cả 2 nhánh char/measurement

**Files:**
- Modify: `src/xcptool/a2l/database.py`
- Test: `tests/unit/test_a2l_database.py`

**Interfaces:**
- Consumes: `Instance`, `CharacteristicTypeDef`, `MeasurementTypeDef`, `InstanceNode` (Task 1); `db.instances` (Task 5).
- Produces: `_resolve_instances(db) -> None`; `_resolve_one(db, type_name, base_addr, name, matrix_dim, seen) -> InstanceNode | None`; `_resolve_type(db, type_name, addr, name, seen) -> InstanceNode | None`; `_array_len(matrix_dim: list[int]) -> int`; ghi thẳng vào `db.characteristics`/`db.measurements`/`db.instance_trees`. `load()` gọi `_resolve_instances(db)` ngay sau `_resolve(db)`.

- [ ] **Step 1: Viết test thất bại**

```python
def test_flat_instance_of_characteristic_type_materializes_real_characteristic() -> None:
    db = _resolve("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_LINEAR 0.0 10.0
    /end TYPEDEF_CHARACTERISTIC
    /begin INSTANCE mainGain "main gain instance" T_Gain 0x80100000
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)

    char = db.characteristics["mainGain"]
    assert char.address == 0x80100000
    assert char.datatype == "FLOAT32_IEEE"
    assert char.char_type == "VALUE"

    node = db.instance_trees["mainGain"]
    assert node.leaf_name == "mainGain"
    assert node.is_measurement is False
    assert node.address == 0x80100000
    assert node.children == []


def test_flat_instance_of_measurement_type_materializes_real_measurement() -> None:
    db = _resolve("""
    /begin TYPEDEF_MEASUREMENT T_Speed "speed" FLOAT32_IEEE CM_NONE 0 0 0 300
    /end TYPEDEF_MEASUREMENT
    /begin INSTANCE vehicleSpeed "speed instance" T_Speed 0x90000000
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)

    meas = db.measurements["vehicleSpeed"]
    assert meas.address == 0x90000000
    assert meas.datatype == "FLOAT32_IEEE"

    node = db.instance_trees["vehicleSpeed"]
    assert node.leaf_name == "vehicleSpeed"
    assert node.is_measurement is True
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_database.py -k flat_instance -v`
Expected: FAIL — `ImportError: cannot import name '_resolve_instances'`

- [ ] **Step 3: Viết `_resolve_instances`/`_resolve_one`/`_resolve_type`**

Thêm vào `database.py` (import `InstanceNode` từ `.types` — đã import `A2LDatabase` sẵn, mở rộng dòng import):

```python
def _array_len(matrix_dim: list[int]) -> int:
    n = 1
    for d in matrix_dim:
        n *= d
    return n


def _resolve_instances(db: A2LDatabase) -> None:
    """Đệ quy flatten mọi INSTANCE thành Characteristic/Measurement thật
    (địa chỉ tuyệt đối) + InstanceNode (cây hiển thị cho UI). Struct lồng
    struct và mảng (component lẫn instance) xem Task 8/9/11."""
    for inst in db.instances.values():
        node = _resolve_one(db, inst.type_name, inst.address, inst.name,
                            inst.matrix_dim, frozenset())
        if node is not None:
            db.instance_trees[inst.name] = node


def _resolve_one(
    db: A2LDatabase, type_name: str, base_addr: int, name: str,
    matrix_dim: list[int], seen: frozenset[str],
) -> InstanceNode | None:
    n = _array_len(matrix_dim)
    if n == 1:
        return _resolve_type(db, type_name, base_addr, name, seen)
    return None  # mảng — xem Task 9


def _resolve_type(
    db: A2LDatabase, type_name: str, addr: int, name: str, seen: frozenset[str],
) -> InstanceNode | None:
    if type_name in db.characteristic_types:
        tmpl = db.characteristic_types[type_name]
        if name in db.characteristics:
            _log.warning("INSTANCE-resolved name %r collides with an existing "
                        "CHARACTERISTIC, skipping", name)
            return None
        db.characteristics[name] = Characteristic(
            name=name, description=tmpl.description, char_type=tmpl.char_type,
            address=addr, record_layout=tmpl.record_layout,
            lower_limit=tmpl.lower_limit, upper_limit=tmpl.upper_limit,
            compu_method=tmpl.compu_method, array_size=tmpl.array_size,
            datatype=tmpl.datatype)
        return InstanceNode(name=name, address=addr, leaf_name=name,
                            is_measurement=False, struct_size=None)
    if type_name in db.measurement_types:
        tmpl = db.measurement_types[type_name]
        if name in db.measurements:
            _log.warning("INSTANCE-resolved name %r collides with an existing "
                        "MEASUREMENT, skipping", name)
            return None
        db.measurements[name] = Measurement(
            name=name, description=tmpl.description, datatype=tmpl.datatype,
            address=addr, lower_limit=tmpl.lower_limit, upper_limit=tmpl.upper_limit,
            compu_method=tmpl.compu_method, matrix_dim=tmpl.matrix_dim)
        return InstanceNode(name=name, address=addr, leaf_name=name,
                            is_measurement=True, struct_size=None)
    _log.warning("INSTANCE/STRUCTURE_COMPONENT %r references unknown type %r, skipping",
                name, type_name)
    return None
```

(Nhánh struct trong `_resolve_type` thêm ở Task 8; nhánh mảng trong `_resolve_one` thêm ở Task 9; `seen` chưa dùng tới khi chưa có đệ quy struct — giữ tham số sẵn để Task 8/11 không phải đổi chữ ký.)

Sửa `load()` gọi thêm bước mới, ngay sau `_resolve(db)`:

```python
def load(path: str | Path) -> A2LDatabase:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    db = parse(text)
    _resolve(db)
    _resolve_instances(db)
    return db
```

- [ ] **Step 4: Chạy lại, xác nhận PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_database.py tests/unit/test_a2l_parser.py -v`

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/a2l/database.py xcptool/tests/unit/test_a2l_database.py
git commit -m "feat(xcptool): resolve flat INSTANCE into real Characteristic/Measurement"
```

---

### Task 8: Resolution — INSTANCE của struct (1 tầng, member scalar)

**Files:**
- Modify: `src/xcptool/a2l/database.py`
- Test: `tests/unit/test_a2l_database.py`

**Interfaces:**
- Consumes: `StructTypeDef`, `StructComponent` (Task 1/2); `_resolve_type` (Task 7).
- Produces: nhánh struct trong `_resolve_type` — member địa chỉ = `addr + component.offset`, tên = `f"{name}.{component.name}"`.

- [ ] **Step 1: Viết test thất bại**

```python
def test_struct_instance_resolves_each_member_to_a_real_address() -> None:
    db = _resolve("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_LINEAR 0.0 10.0
    /end TYPEDEF_CHARACTERISTIC
    /begin TYPEDEF_STRUCTURE Pid_t "pid gains" 8
        /begin STRUCTURE_COMPONENT kp T_Gain 0
        /end STRUCTURE_COMPONENT
        /begin STRUCTURE_COMPONENT ki T_Gain 4
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE speedPid "speed pid" Pid_t 0x80100000
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)

    assert db.characteristics["speedPid.kp"].address == 0x80100000
    assert db.characteristics["speedPid.ki"].address == 0x80100004

    node = db.instance_trees["speedPid"]
    assert node.leaf_name is None
    assert node.struct_size == 8
    assert [c.name for c in node.children] == ["speedPid.kp", "speedPid.ki"]
    assert all(c.leaf_name == c.name for c in node.children)
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_database.py::test_struct_instance_resolves_each_member_to_a_real_address -v`
Expected: FAIL — `KeyError: 'speedPid.kp'` (rơi vào nhánh "unknown type" vì chưa có nhánh struct)

- [ ] **Step 3: Thêm nhánh struct vào `_resolve_type`, TRƯỚC 2 nhánh `if type_name in ...types`**

```python
def _resolve_type(
    db: A2LDatabase, type_name: str, addr: int, name: str, seen: frozenset[str],
) -> InstanceNode | None:
    if type_name in db.struct_types:
        struct = db.struct_types[type_name]
        children: list[InstanceNode] = []
        for comp in struct.components:
            child = _resolve_one(db, comp.type_name, addr + comp.offset,
                                 f"{name}.{comp.name}", comp.matrix_dim,
                                 seen | {type_name})
            if child is not None:
                children.append(child)
        return InstanceNode(name=name, address=addr, leaf_name=None,
                            is_measurement=False, struct_size=struct.size,
                            children=children)
    if type_name in db.characteristic_types:
        ...  # giữ nguyên Task 7
```

(`seen | {type_name}` chưa được `_resolve_type` kiểm tra — vòng lặp thật sự chỉ chặn ở Task 11; ở đây chỉ cần TRUYỀN đúng `seen` xuống để chữ ký nhất quán, không phá test Task 7.)

- [ ] **Step 4: Chạy lại, xác nhận PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_database.py -v`

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/a2l/database.py xcptool/tests/unit/test_a2l_database.py
git commit -m "feat(xcptool): resolve struct INSTANCE members to real addresses"
```

---

### Task 9: Resolution — mảng (component có `MATRIX_DIM`, và instance có `MATRIX_DIM`)

**Files:**
- Modify: `src/xcptool/a2l/database.py`
- Test: `tests/unit/test_a2l_database.py`

**Interfaces:**
- Consumes: `_resolve_one` (Task 7), `_size_of` (mới).
- Produces: `_size_of(db, type_name) -> int | None`; nhánh `n > 1` trong `_resolve_one` — dùng CHUNG cho mảng ở cấp component lẫn cấp instance (cùng một hàm, không code riêng cho 2 case).

- [ ] **Step 1: Viết test thất bại**

```python
def test_array_component_expands_to_indexed_addresses() -> None:
    db = _resolve("""
    /begin RECORD_LAYOUT RL_I16
        FNC_VALUES 1 SWORD ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_I16 "i16" VALUE RL_I16 0 CM_NONE -100 100
    /end TYPEDEF_CHARACTERISTIC
    /begin TYPEDEF_STRUCTURE WithArray_t "has array member" 6
        /begin STRUCTURE_COMPONENT samples T_I16 0
            MATRIX_DIM 3
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE grp "grp" WithArray_t 0x80100000
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)

    assert db.characteristics["grp.samples[0]"].address == 0x80100000
    assert db.characteristics["grp.samples[1]"].address == 0x80100002
    assert db.characteristics["grp.samples[2]"].address == 0x80100004

    node = db.instance_trees["grp"]
    samples_node = node.children[0]
    assert samples_node.leaf_name is None  # mảng — không phải lá
    assert [c.name for c in samples_node.children] == [
        "grp.samples[0]", "grp.samples[1]", "grp.samples[2]"]


def test_array_instance_of_struct_expands_each_element() -> None:
    db = _resolve("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin TYPEDEF_STRUCTURE Pid_t "pid" 4
        /begin STRUCTURE_COMPONENT kp T_Gain 0
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE pids "array of pid" Pid_t 0x80100000
        MATRIX_DIM 2
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)

    assert db.characteristics["pids[0].kp"].address == 0x80100000
    assert db.characteristics["pids[1].kp"].address == 0x80100004
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_database.py -k array -v`
Expected: FAIL — `KeyError: 'grp.samples[0]'` (nhánh `n > 1` trong `_resolve_one` hiện `return None`)

- [ ] **Step 3: Thêm `_size_of` + sửa nhánh mảng trong `_resolve_one`**

Thêm ngay trước `_resolve_one` (cần `DATATYPE_SIZES` — mở rộng import từ `.types`):

```python
def _size_of(db: A2LDatabase, type_name: str) -> int | None:
    """Byte size của 1 phần tử — cần để stride qua mảng."""
    if type_name in db.struct_types:
        return db.struct_types[type_name].size
    if type_name in db.characteristic_types:
        tmpl = db.characteristic_types[type_name]
        if tmpl.datatype is None:
            return None
        return DATATYPE_SIZES.get(tmpl.datatype, 1) * tmpl.array_size
    if type_name in db.measurement_types:
        tmpl = db.measurement_types[type_name]
        return DATATYPE_SIZES.get(tmpl.datatype, 1) * tmpl.array_size
    return None
```

Sửa `_resolve_one`:

```python
def _resolve_one(
    db: A2LDatabase, type_name: str, base_addr: int, name: str,
    matrix_dim: list[int], seen: frozenset[str],
) -> InstanceNode | None:
    n = _array_len(matrix_dim)
    if n == 1:
        return _resolve_type(db, type_name, base_addr, name, seen)

    size = _size_of(db, type_name)
    if size is None:
        _log.warning("Cannot size array element type %r for %r, skipping", type_name, name)
        return None
    children: list[InstanceNode] = []
    for i in range(n):
        child = _resolve_type(db, type_name, base_addr + i * size, f"{name}[{i}]", seen)
        if child is not None:
            children.append(child)
    if not children:
        return None
    return InstanceNode(name=name, address=base_addr, leaf_name=None,
                        is_measurement=False, struct_size=None, children=children)
```

- [ ] **Step 4: Chạy lại, xác nhận PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_database.py -v`

- [ ] **Step 5: Chạy full suite Phase 1 — chốt phase 1**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ -x -q`
Expected: PASS toàn bộ (phase 1 chưa đụng UI — không có test nào khác nên đỏ)

- [ ] **Step 6: Commit**

```bash
git add xcptool/src/xcptool/a2l/database.py xcptool/tests/unit/test_a2l_database.py
git commit -m "feat(xcptool): resolve array components and array instances"
```

---

### Task 10: Resolution — struct lồng struct + guard (circular / unknown type / collision)

**Files:**
- Modify: `src/xcptool/a2l/database.py`
- Test: `tests/unit/test_a2l_database.py`

**Interfaces:**
- Consumes: `_resolve_type` struct branch (Task 8), `seen: frozenset[str]` (đã truyền sẵn từ Task 8, giờ mới THẬT SỰ kiểm tra).
- Produces: struct-trong-struct hoạt động đúng; 3 guard ném warning + trả `None`, không crash, không đè dữ liệu.

- [ ] **Step 1: Viết test thất bại (4 case trong 1 task — cùng 1 mạch guard)**

```python
def test_nested_struct_resolves_recursively() -> None:
    db = _resolve("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin TYPEDEF_STRUCTURE Inner_t "inner" 4
        /begin STRUCTURE_COMPONENT val T_Gain 0
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin TYPEDEF_STRUCTURE Outer_t "outer" 4
        /begin STRUCTURE_COMPONENT inner Inner_t 0
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE thing "nested" Outer_t 0x80100000
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)
    assert db.characteristics["thing.inner.val"].address == 0x80100000


def test_circular_struct_reference_warns_and_skips(caplog) -> None:
    db = _resolve("""
    /begin TYPEDEF_STRUCTURE A_t "a" 4
        /begin STRUCTURE_COMPONENT b B_t 0
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin TYPEDEF_STRUCTURE B_t "b" 4
        /begin STRUCTURE_COMPONENT a A_t 0
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE thing "circular" A_t 0x80100000
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)  # KHÔNG được raise / đệ quy vô hạn
    assert db.characteristics == {}
    assert "circular" in caplog.text.lower() or "recursion" in caplog.text.lower()


def test_unknown_type_name_warns_and_skips(caplog) -> None:
    db = _resolve("""
    /begin INSTANCE thing "bad type ref" NotDefinedAnywhere_t 0x80100000
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)
    assert db.instance_trees == {}
    assert "unknown" in caplog.text.lower() or "NotDefinedAnywhere_t" in caplog.text


def test_name_collision_keeps_original_and_warns(caplog) -> None:
    db = _resolve("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin CHARACTERISTIC dup "already exists" VALUE 0x12345678 RL_F32 0 CM_NONE 0 10
    /end CHARACTERISTIC
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin INSTANCE dup "collides with the CHARACTERISTIC above" T_Gain 0x80100000
    /end INSTANCE
    """)
    from xcptool.a2l.database import _resolve_instances
    _resolve_instances(db)
    assert db.characteristics["dup"].address == 0x12345678  # KHÔNG bị ghi đè
    assert "collide" in caplog.text.lower() or "collision" in caplog.text.lower()
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_database.py -k "nested or circular or unknown_type or collision" -v`
Expected: `test_nested_struct_resolves_recursively` đã PASS (Task 8 đã handle đệ quy struct-tầng-nào-cũng-được về mặt cơ chế); `test_circular_...` FAIL — `RecursionError` (chưa chặn); 2 test còn lại đã PASS sẵn (Task 7 guard đã viết). Nếu `nested`/`unknown_type`/`collision` đã xanh — bỏ qua Step 3 phần tương ứng, chỉ cần thêm chặn circular.

- [ ] **Step 3: Thêm guard circular vào nhánh struct của `_resolve_type`**

```python
    if type_name in db.struct_types:
        if type_name in seen:
            _log.warning("Circular TYPEDEF_STRUCTURE reference at %r via %r, skipping",
                        name, type_name)
            return None
        struct = db.struct_types[type_name]
        ...  # phần còn lại giữ nguyên Task 8
```

- [ ] **Step 4: Chạy lại toàn bộ, xác nhận PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/unit/test_a2l_database.py -v`

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/a2l/database.py xcptool/tests/unit/test_a2l_database.py
git commit -m "feat(xcptool): guard circular TYPEDEF_STRUCTURE references"
```

**→ Phase 1 xong khi Task 10 commit xanh.** `a2l/` giờ đọc được toàn bộ ASAP2
struct-typedef thật, độc lập UI, test riêng đầy đủ.

---

### Task 11: `CalibrationView` — dựng cây từ `db.instance_trees`, bỏ `_group_by_prefix`

**Files:**
- Modify: `src/xcptool/ui/calibration_view.py` (`set_database()` hiện ở dòng 445; `_group_by_prefix` hiện ở dòng 216 — xoá; hàm mới `_build_tree_item_from_node`)
- Test: `tests/ui/test_calibration_view.py`

**Interfaces:**
- Consumes: `InstanceNode` (Task 1), `db.instance_trees` (Task 7-10), `_make_item`/`_build_array_children` (đã có, KHÔNG đổi chữ ký).
- Produces: `CalibrationView._build_tree_item_from_node(node: InstanceNode) -> QTreeWidgetItem`. `set_database()` không còn gọi `_group_by_prefix`.

- [ ] **Step 1: Viết test thất bại**

Thay thế hoàn toàn `test_set_database_groups_struct_characteristics` (đang assert đúng hành vi bị xoá) bằng:

```python
def test_set_database_builds_struct_tree_from_instance_data(qtbot) -> None:
    """Thay test cũ (đoán struct theo tên) — giờ struct đến từ INSTANCE thật."""
    from xcptool.a2l.database import load as a2l_load
    import tempfile, textwrap
    a2l_text = textwrap.dedent("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin TYPEDEF_STRUCTURE Pid_t "pid" 8
        /begin STRUCTURE_COMPONENT kp T_Gain 0
        /end STRUCTURE_COMPONENT
        /begin STRUCTURE_COMPONENT ki T_Gain 4
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE speedPid "speed pid" Pid_t 0x80100000
    /end INSTANCE
    """)
    with tempfile.NamedTemporaryFile("w", suffix=".a2l", delete=False) as f:
        f.write(a2l_text)
        path = f.name
    db = a2l_load(path)

    v = _make_view(qtbot)
    v.set_database(db)

    assert v.tree.topLevelItemCount() == 1
    parent = v.tree.topLevelItem(0)
    assert parent.text(COL_NAME) == "speedPid"
    assert "STRUCT" in parent.text(COL_TYPE)
    assert parent.text(COL_SIZE) == "8"
    assert parent.childCount() == 2
    assert {parent.child(i).data(COL_NAME, Qt.UserRole) for i in range(2)} == {
        "speedPid.kp", "speedPid.ki"}


def test_set_database_no_instance_renders_flat_even_with_shared_name_prefix(qtbot) -> None:
    """Quyết định spec §6: CHARACTERISTIC không có INSTANCE hiện phẳng, dù
    tên trùng tiền tố — KHÔNG còn heuristic đoán theo tên."""
    db = A2LDatabase()
    for param in ("kp", "ki", "kd"):
        db.characteristics[f"speedPid_{param}"] = Characteristic(
            name=f"speedPid_{param}", description="", char_type="VALUE",
            address=MEM_BASE, record_layout="RL_F32", lower_limit=-10.0,
            upper_limit=10.0, datatype="FLOAT32_IEEE")
    v = _make_view(qtbot)
    v.set_database(db)

    assert v.tree.topLevelItemCount() == 3  # KHÔNG gộp — trước đây sẽ là 1
    names = {v.tree.topLevelItem(i).text(COL_NAME) for i in range(3)}
    assert names == {"speedPid_kp", "speedPid_ki", "speedPid_kd"}
```

Xoá hẳn `test_set_database_groups_struct_characteristics` (thay bằng 2 test trên).

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ui/test_calibration_view.py -k "instance_data or shared_name_prefix" -v`
Expected: `no_instance_renders_flat` đã PASS (nếu `_group_by_prefix` vẫn còn thì FAIL — group thành 1 node); `instance_data` FAIL vì `set_database` chưa đọc `db.instance_trees`.

- [ ] **Step 3: Sửa `set_database()`, thêm `_build_tree_item_from_node`, xoá `_group_by_prefix`**

Thay toàn bộ khối `groups = _group_by_prefix(...)` … hết vòng `for group_name, members in groups:` (dòng 455-494 hiện tại) bằng:

```python
            handled: set[str] = set()
            for inst_name, node in db.instance_trees.items():
                item = self._build_tree_item_from_node(node)
                self.tree.addTopLevelItem(item)
                handled |= self._leaf_names(node)

            for name, char in sorted(db.characteristics.items()):
                if name in handled:
                    continue
                item = self._make_item(name, char)
                self.tree.addTopLevelItem(item)
                self._char_items[name] = item
                if char.array_size > 1:
                    self._build_array_children(item, char)
```

Thêm 2 method mới trong class (cạnh `_make_item`):

```python
    def _leaf_names(self, node: "InstanceNode") -> set[str]:
        if node.leaf_name is not None:
            return {node.leaf_name}
        names: set[str] = set()
        for child in node.children:
            names |= self._leaf_names(child)
        return names

    def _build_tree_item_from_node(self, node: "InstanceNode") -> QTreeWidgetItem:
        """Dựng QTreeWidgetItem từ InstanceNode đã resolve (a2l/database.py) —
        KHÔNG tự suy địa chỉ hay tên, chỉ đọc lại những gì resolve() đã
        quyết định (xem spec §10)."""
        if node.leaf_name is not None:
            char = self._db.characteristics[node.leaf_name]
            item = self._make_item(node.leaf_name, char,
                                   display_name=node.name.rsplit(".", 1)[-1])
            self._char_items[node.leaf_name] = item
            if char.array_size > 1:
                self._build_array_children(item, char)
            return item

        item = QTreeWidgetItem()
        item.setData(COL_NAME, Qt.UserRole, node.name)
        item.setText(COL_NAME, node.name.rsplit(".", 1)[-1] if "." in node.name else node.name)
        if node.struct_size is not None:
            item.setText(COL_TYPE, f"STRUCT ({len(node.children)})")
            item.setText(COL_SIZE, str(node.struct_size))
        else:
            item.setText(COL_TYPE, f"ARRAY[{len(node.children)}]")
        item.setText(COL_ADDR, f"0x{node.address:08X}")
        item.setText(COL_VALUE, "—")
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self._char_items[node.name] = item
        for child_node in node.children:
            item.addChild(self._build_tree_item_from_node(child_node))
        item.setExpanded(True)
        return item
```

Xoá hoàn toàn hàm `_group_by_prefix` (dòng 216-247 hiện tại). Thêm `InstanceNode` vào import từ `..session.api` (kiểm tra `session/api.py` đã re-export `InstanceNode` chưa — nếu chưa, dùng `from ..a2l.types import InstanceNode` trực tiếp; `a2l.types` là stdlib-thuần, không vi phạm ranh giới `ui/` cấm import `xcptool.a2l` theo `test_boundaries.py` §... — **CHỖ NÀY CẦN QUYẾT ĐỊNH TRƯỚC KHI CODE**: `test_boundaries.py` cấm `ui/` import `xcptool.a2l` (xem hàng `ui/` trong bảng FORBIDDEN của `tests/test_boundaries.py`) — `InstanceNode` PHẢI được re-export qua `session/api.py` giống `A2LDatabase` đã làm, KHÔNG import thẳng từ `a2l.types`. Thêm `from ..a2l.types import InstanceNode` vào `session/api.py` và thêm `InstanceNode` vào `__all__` của `api.py` (file lead-owned — xin duyệt trước khi sửa nếu làm việc theo quy trình nhóm; ở đây tự làm vì đang là agent duy nhất). `ui/calibration_view.py` import `from ..session.api import A2LDatabase, DeviceInfo, InstanceNode`.

- [ ] **Step 4: Chạy lại toàn bộ file test, xác nhận PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ui/test_calibration_view.py -v`
Expected: PASS toàn bộ — kể cả các test write-path cũ (`_split_into_contiguous_runs`, `on_write_done` parent color) không đổi hành vi, vì chúng test `_write_parent`/`on_write_done` trực tiếp, không phụ thuộc `set_database()`.

- [ ] **Step 5: Chạy `test_boundaries.py` — xác nhận không phá ranh giới**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/test_boundaries.py -v`
Expected: PASS — đặc biệt `test_package_boundary[ui]` (nếu lỡ import thẳng `a2l.types` thay vì qua `session.api` thì đỏ ngay đây)

- [ ] **Step 6: Commit**

```bash
git add xcptool/src/xcptool/ui/calibration_view.py xcptool/src/xcptool/session/api.py xcptool/tests/ui/test_calibration_view.py
git commit -m "feat(xcptool): CalibrationView builds STRUCT tree from real INSTANCE data"
```

---

### Task 12: `CalibrationView` — struct lồng/mảng trong cây UI + hồi quy toàn diện

**Files:**
- Modify: `src/xcptool/ui/calibration_view.py` (không đổi code — `_build_tree_item_from_node` ở Task 11 đã đệ quy đúng cho mọi độ sâu/mảng, vì nó chỉ đi theo `InstanceNode.children` đã resolve sẵn)
- Test: `tests/ui/test_calibration_view.py`

**Interfaces:**
- Consumes: `_build_tree_item_from_node` (Task 11) — không đổi.

- [ ] **Step 1: Viết test xác nhận hành vi đã đúng (không cần sửa code nếu Task 11 đúng)**

```python
def test_set_database_renders_nested_and_array_struct(qtbot) -> None:
    import tempfile, textwrap
    from xcptool.a2l.database import load as a2l_load
    a2l_text = textwrap.dedent("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin TYPEDEF_STRUCTURE Inner_t "inner" 4
        /begin STRUCTURE_COMPONENT val T_Gain 0
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin TYPEDEF_STRUCTURE Outer_t "outer" 4
        /begin STRUCTURE_COMPONENT inner Inner_t 0
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE pids "array of outer" Outer_t 0x80100000
        MATRIX_DIM 2
    /end INSTANCE
    """)
    with tempfile.NamedTemporaryFile("w", suffix=".a2l", delete=False) as f:
        f.write(a2l_text)
        path = f.name
    db = a2l_load(path)

    v = _make_view(qtbot)
    v.set_database(db)

    assert v.tree.topLevelItemCount() == 1
    array_parent = v.tree.topLevelItem(0)
    assert array_parent.childCount() == 2  # pids[0], pids[1]
    outer0 = array_parent.child(0)
    assert outer0.childCount() == 1        # inner
    inner0 = outer0.child(0)
    assert inner0.childCount() == 1        # val
    leaf = inner0.child(0)
    assert leaf.data(COL_NAME, Qt.UserRole) == "pids[0].inner.val"
```

- [ ] **Step 2: Chạy test**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ui/test_calibration_view.py::test_set_database_renders_nested_and_array_struct -v`
Expected: PASS ngay (Task 11 đã tổng quát đúng) — nếu FAIL, lỗi nằm ở `_build_tree_item_from_node`, sửa tại đó cho tới khi xanh.

- [ ] **Step 3: Lỗ hổng thật cần vá — mảng scalar KHÔNG bọc trong struct (bare array INSTANCE) chưa ghi được**

`_build_tree_item_from_node` (Task 11) gắn `COL_TYPE = f"ARRAY[{n}]"` (không
phải `"STRUCT (...)"`) khi `INSTANCE` có `MATRIX_DIM` nhưng `type_name` trỏ
tới `CharacteristicTypeDef` (scalar), không phải struct — VD `INSTANCE
tempSensors "..." T_Gain 0x80100000 MATRIX_DIM 3`. `_write_parent`/
`on_write_done`/`_on_write_all` hiện chỉ nhận diện combine-write qua
`item.text(COL_TYPE).startswith("STRUCT")` — node "ARRAY[3]" này sẽ KHÔNG
đi qua nhánh combine, rơi vào nhánh scalar đơn, tìm
`self._db.characteristics.get("tempSensors")` → `None` (chỉ có
`"tempSensors[0]"`, `"tempSensors[1]"`, `"tempSensors[2]"` là key thật) →
ghi không làm gì, không lỗi, không thông báo — loại bug im lặng nguy hiểm
nhất. Struct-lồng-mảng (test Step 1-2) KHÔNG dính lỗi này vì nó luôn có 1
struct cha thật (`COL_TYPE` bắt đầu bằng `"STRUCT"`) bọc ngoài mảng.

Viết test thất bại trước:

```python
def test_write_bare_array_instance_without_enclosing_struct(qtbot) -> None:
    """INSTANCE ... MATRIX_DIM của kiểu scalar (không bọc trong struct nào)
    vẫn phải ghi được qua đúng cơ chế combine-write, y hệt STRUCT."""
    import tempfile, textwrap
    from xcptool.a2l.database import load as a2l_load
    a2l_text = textwrap.dedent("""
    /begin RECORD_LAYOUT RL_F32
        FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT
    /end RECORD_LAYOUT
    /begin TYPEDEF_CHARACTERISTIC T_Gain "gain" VALUE RL_F32 0 CM_NONE 0 10
    /end TYPEDEF_CHARACTERISTIC
    /begin INSTANCE tempSensors "3 sensor gains, no struct" T_Gain 0x80100000
        MATRIX_DIM 3
    /end INSTANCE
    """)
    with tempfile.NamedTemporaryFile("w", suffix=".a2l", delete=False) as f:
        f.write(a2l_text)
        path = f.name
    db = a2l_load(path)

    v = _make_view(qtbot)
    v.set_database(db)
    parent = v._char_items["tempSensors"]
    assert parent.text(COL_TYPE).startswith("ARRAY")

    for i in range(3):
        parent.child(i).setText(COL_VALUE, str(1.0 + i))

    writes: list[tuple[str, int, bytes]] = []
    v._write_cb = lambda name, addr, data: writes.append((name, addr, data))
    v._write_parent("tempSensors", parent)

    assert len(writes) == 1          # 3 phần tử liền khít -> 1 lần ghi
    name, addr, data = writes[0]
    assert addr == 0x80100000
    assert len(data) == 12            # 3 x FLOAT32 (4 byte)
```

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ui/test_calibration_view.py::test_write_bare_array_instance_without_enclosing_struct -v`
Expected: FAIL — `writes == []` (rơi vào nhánh scalar, `char_def` là `None`, `_write_parent` return sớm không làm gì)

Sửa 3 chỗ trong `calibration_view.py` — mở rộng điều kiện nhận diện "node
combine-write được" từ chỉ `"STRUCT"` sang `"STRUCT"` HOẶC `"ARRAY["`:

```python
# _write_parent — dòng đầu hàm
if item.text(COL_TYPE).startswith("STRUCT") or item.text(COL_TYPE).startswith("ARRAY["):
```
```python
# on_write_done — nhánh dọn dirty cho parent nhiều con
if item.text(COL_TYPE).startswith("STRUCT") or item.text(COL_TYPE).startswith("ARRAY["):
```
```python
# _on_write_all — điều kiện promote dirty child lên parent
if item.parent() is not None and (
    item.parent().text(COL_TYPE).startswith("STRUCT")
    or item.parent().text(COL_TYPE).startswith("ARRAY[")
):
```

Chạy lại test vừa viết + toàn bộ `test_calibration_view.py`, xác nhận PASS.
`_split_into_contiguous_runs`/`_pending_struct_runs` không cần đổi gì — cả
hai chỉ quan tâm (address, bytes) của từng con, không quan tâm parent là
"STRUCT" hay "ARRAY[" về mặt ngữ nghĩa.

- [ ] **Step 4: Roll-up Phase 2 — full suite**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ -x -q`
Expected: PASS toàn bộ.

- [ ] **Step 5: Commit**

```bash
git add xcptool/src/xcptool/ui/calibration_view.py xcptool/tests/ui/test_calibration_view.py
git commit -m "fix(xcptool): route bare array-of-scalar INSTANCE writes through combine-write"
```

**→ Phase 2 xong khi Task 12 commit xanh.**

---

### Task 13: `MeasurementView` — bỏ `_group_by_prefix` (bản riêng), dùng `db.instance_trees`

**Files:**
- Modify: `src/xcptool/ui/measurement_view.py` (`_group_by_prefix` ở dòng 129 — bản ĐỘC LẬP với bản trong `calibration_view.py`, xoá; `set_database()` ở dòng 310; `_checked_names()` ở dòng 535)
- Test: `tests/ui/test_measurement_view.py` — fixture view có sẵn: `view(qtbot) -> MeasurementView` (dòng 36-41, dùng `MeasurementView()` trực tiếp, không cần factory riêng)

**⚠️ Chi tiết dễ bỏ sót — đọc trước khi code:** tick checkbox ở dòng CHA
(struct/mảng) phải kéo theo TẤT CẢ signal con vào DAQ list khi bấm "Bắt đầu
đo" — cơ chế này KHÔNG phải duyệt cây lúc bấm nút, mà đọc thẳng
`item.data(COL_NAME, Qt.UserRole)` trong `_checked_names()` (dòng 535-545):
nếu giá trị là `list` thì `extend` cả list đó vào signal cần gửi, nếu là
`str` thì `append` đúng 1 tên. `_build_tree_item_from_node` PHẢI giữ đúng
hợp đồng này — node struct/mảng set `Qt.UserRole` = **list tên MEASUREMENT
lá thật** (không phải tên hiển thị của node), node lá set `Qt.UserRole` =
tên nó (`str`, y hệt hiện tại). Bỏ qua chi tiết này thì tick dòng cha xong
bấm "Bắt đầu đo" sẽ gửi DAQ list RỖNG — không lỗi, không crash, chỉ âm
thầm không đo được gì (loại lỗi khó phát hiện nếu không có test).

**Interfaces:**
- Consumes: `InstanceNode`, `db.instance_trees` (Task 11, re-export qua `session/api.py`); `_leaf_names()` — VIẾT LẠI Ở ĐÂY (không import từ `calibration_view.py`, 2 file không phụ thuộc nhau).
- Produces: `MeasurementView._build_tree_item_from_node(node) -> QTreeWidgetItem`; `MeasurementView._leaf_names(node) -> list[str]`.

- [ ] **Step 1: Đọc lại nguyên văn `set_database()` + `_checked_names()`/`_build_daq_lists()` thật trước khi sửa**

Dùng tool đọc file (không dùng lại mô tả trong plan này) — file có thể đã
đổi khác chút kể từ lúc viết plan.

- [ ] **Step 2: Viết test thất bại — thay `test_set_database_groups_struct_measurements` (dòng 241)**

Xoá `test_set_database_groups_struct_measurements` hiện có (đang assert
hành vi `_group_by_prefix` sẽ bị xoá), thay bằng:

```python
def test_set_database_builds_struct_tree_from_instance_data(view: MeasurementView) -> None:
    """Thay test cũ (đoán struct theo tên) — struct từ INSTANCE thật, và
    tick dòng cha vẫn phải kéo đủ cả 3 signal con vào DAQ list."""
    import tempfile, textwrap
    from xcptool.a2l.database import load as a2l_load
    a2l_text = textwrap.dedent("""
    /begin TYPEDEF_MEASUREMENT T_F32 "f32" FLOAT32_IEEE CM_NONE 0 0 -100 100
    /end TYPEDEF_MEASUREMENT
    /begin TYPEDEF_STRUCTURE Telemetry_t "telemetry" 12
        /begin STRUCTURE_COMPONENT error T_F32 0
        /end STRUCTURE_COMPONENT
        /begin STRUCTURE_COMPONENT integral T_F32 4
        /end STRUCTURE_COMPONENT
        /begin STRUCTURE_COMPONENT output T_F32 8
        /end STRUCTURE_COMPONENT
    /end TYPEDEF_STRUCTURE
    /begin INSTANCE speedPidTelemetry "telemetry instance" Telemetry_t 0x90001000
    /end INSTANCE
    """)
    with tempfile.NamedTemporaryFile("w", suffix=".a2l", delete=False) as f:
        f.write(a2l_text)
        path = f.name
    db = a2l_load(path)
    view.set_database(db)

    assert view.tree.topLevelItemCount() == 1
    parent = view.tree.topLevelItem(0)
    assert parent.text(COL_NAME) == "speedPidTelemetry"
    assert "STRUCT" in parent.text(COL_DTYPE)
    assert parent.childCount() == 3

    for i in range(3):
        child = parent.child(i)
        assert child.checkState(COL_NAME) == Qt.Unchecked or child.data(COL_NAME, Qt.CheckStateRole) is None

    parent.setCheckState(COL_NAME, Qt.Checked)
    emitted: list[list] = []
    view.daq_start_requested.connect(emitted.append)
    view.start_btn.click()

    assert len(emitted) == 1
    sigs = emitted[0][0].signals
    assert len(sigs) == 3
    assert {s.name for s in sigs} == {
        "speedPidTelemetry.error", "speedPidTelemetry.integral", "speedPidTelemetry.output",
    }
```

(Tên leaf giờ có dấu `.` — `speedPidTelemetry.error`, không phải
`speedPidTelemetry_error` như test cũ, vì đây là tên do `_resolve_type`
sinh ra — spec §5. Import `MeasurementView` đã có sẵn ở đầu file test.)

- [ ] **Step 3: Chạy test, xác nhận FAIL**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ui/test_measurement_view.py::test_set_database_builds_struct_tree_from_instance_data -v`
Expected: FAIL — cây rỗng hoặc lỗi import, vì `set_database()` chưa đọc `instance_trees`.

- [ ] **Step 4: Sửa `set_database()`, thêm `_build_tree_item_from_node`/`_leaf_names`, xoá `_group_by_prefix`**

Thay khối `groups = _group_by_prefix(...)` … hết vòng lặp (dòng ~316-369
hiện tại) bằng cấu trúc giống Task 11 (`handled` set, loop
`db.instance_trees` trước, `db.measurements` còn lại sau) — nhưng dựng
node theo ĐÚNG cột/checkbox của file này:

```python
    def _leaf_names(self, node) -> list[str]:
        if node.leaf_name is not None:
            return [node.leaf_name]
        names: list[str] = []
        for child in node.children:
            names.extend(self._leaf_names(child))
        return names

    def _build_tree_item_from_node(self, node, top_level: bool) -> QTreeWidgetItem:
        """`top_level=True` CHỈ khi item này được add thẳng bằng
        `self.tree.addTopLevelItem(...)` — checkbox chỉ tồn tại ở đó, y hệt
        hành vi cũ (con của struct/mảng KHÔNG có checkbox riêng, xem
        `USER_MANUAL.md §6`). Không dùng cờ True/False nào khác để quyết
        checkbox — quyết định 100% bởi vị trí trong cây, không phải bởi
        node là lá hay không (một INSTANCE scalar độc lập, không thuộc
        struct nào, VẪN cần checkbox vì nó là top-level)."""
        if node.leaf_name is not None:
            meas = self._db.measurements[node.leaf_name]
            item = QTreeWidgetItem()
            item.setData(COL_NAME, Qt.UserRole, node.leaf_name)
            item.setText(COL_NAME, node.name.rsplit(".", 1)[-1] if "." in node.name else node.name)
            if top_level:
                item.setCheckState(COL_NAME, Qt.Unchecked)
            friendly = _FRIENDLY_DTYPE.get(meas.datatype, meas.datatype)
            item.setText(COL_DTYPE, friendly)
            item.setText(COL_ADDR, f"0x{meas.address:08X}")
            item.setText(COL_VALUE, "-")
            item.setToolTip(COL_NAME, meas.description)
            self._tree_items[node.leaf_name] = item
            return item

        leaves = self._leaf_names(node)
        parent = QTreeWidgetItem()
        parent.setData(COL_NAME, Qt.UserRole, leaves)   # list -> _checked_names() extend hết
        parent.setText(COL_NAME, node.name.rsplit(".", 1)[-1] if "." in node.name else node.name)
        if top_level:
            parent.setCheckState(COL_NAME, Qt.Unchecked)
        parent.setText(COL_DTYPE,
            f"STRUCT ({len(node.children)})" if node.struct_size is not None
            else f"ARRAY[{len(node.children)}]")
        parent.setText(COL_ADDR, f"0x{node.address:08X}")
        parent.setText(COL_VALUE, "-")
        for child_node in node.children:
            parent.addChild(self._build_tree_item_from_node(child_node, top_level=False))
        return parent
```

Trong `set_database()`:

```python
        handled: set[str] = set()
        for node in db.instance_trees.values():
            item = self._build_tree_item_from_node(node, top_level=True)
            self.tree.addTopLevelItem(item)
            handled.update(self._leaf_names(node))

        for name in sorted(db.measurements):
            if name in handled:
                continue
            meas = db.measurements[name]
            item = QTreeWidgetItem()
            item.setData(COL_NAME, Qt.UserRole, name)
            item.setText(COL_NAME, name)
            item.setCheckState(COL_NAME, Qt.Unchecked)
            friendly = _FRIENDLY_DTYPE.get(meas.datatype, meas.datatype)
            item.setText(
                COL_DTYPE,
                friendly if meas.array_size == 1 else f"{friendly}[{meas.array_size}]"
            )
            item.setText(COL_ADDR, f"0x{meas.address:08X}")
            item.setText(COL_VALUE, "-")
            item.setToolTip(COL_NAME, meas.description)
            self.tree.addTopLevelItem(item)
            if meas.array_size == 1:
                self._tree_items[name] = item
            else:
                elem_size = meas.byte_size // meas.array_size
                for i in range(meas.array_size):
                    child_name = f"{meas.name}[{i}]"
                    # … giữ NGUYÊN VĂN logic mở rộng mảng độc lập đã có (đọc ở Step 1),
                    # chỉ thay phần group-by-prefix ở trên, không đụng phần này.
```

(Đoạn mở rộng mảng độc lập `elem_size = meas.byte_size // meas.array_size`
trở xuống giữ y hệt code hiện tại — chỉ paste lại nguyên văn sau khi đọc ở
Step 1, không viết lại từ đầu.)

Xoá hoàn toàn `_group_by_prefix` (dòng 129 hiện tại — bản của file NÀY;
bản trong `calibration_view.py` đã xoá ở Task 11, không liên quan).

- [ ] **Step 5: Chạy lại toàn bộ file test, xác nhận PASS**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ui/test_measurement_view.py -v`
Expected: PASS toàn bộ — đặc biệt các test KHÔNG liên quan struct (scalar
tree, array độc lập `torqueSamples`, scope, DAQ start/stop) không được đổi
hành vi.

- [ ] **Step 6: `test_boundaries.py`**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/test_boundaries.py -v`

- [ ] **Step 7: Commit**

```bash
git add xcptool/src/xcptool/ui/measurement_view.py xcptool/tests/ui/test_measurement_view.py
git commit -m "feat(xcptool): MeasurementView builds STRUCT tree from real INSTANCE data"
```

---

### Task 14: Hồi quy toàn bộ + cập nhật trạng thái tài liệu

**Files:**
- Modify: `DEV_PLAN.md` (mục này — đổi "chưa bắt đầu" thành xong), `DESIGN.md §8`, `ARCHITECTURE.md §7`, `USER_MANUAL.md` (bỏ ghi chú "📌 Sắp thay đổi" — hành vi mới đã là hiện tại)

- [ ] **Step 1: Full suite + tiêu chí "không crash" liên quan A2L**

Run: `xcptool\.venv\Scripts\python.exe -m pytest tests/ -x -q`
Expected: PASS toàn bộ, không test nào bị skip ngoài dự kiến.

Thủ công (mục 5 trong `DEV_PLAN.md §6` — nạp A2L không hợp lệ): nạp 1 file A2L có `INSTANCE` tham chiếu `type_name` không tồn tại → app không crash, hiện cảnh báo qua log, CHARACTERISTIC/MEASUREMENT khác trong file vẫn nạp bình thường.

- [ ] **Step 2: Cập nhật trạng thái 4 doc**

`DEV_PLAN.md` §10 — sửa dòng `**Trạng thái: chưa bắt đầu.**` thành `**Trạng thái: hoàn thành (YYYY-MM-DD).**` kèm số test cuối cùng.

`DESIGN.md §8` — sửa `> **Trạng thái: kế hoạch — spec đã duyệt...**` thành mô tả kiến trúc chính thức (bỏ chữ "kế hoạch"), giữ nguyên phần giải thích lý do.

`ARCHITECTURE.md §7.1` — sửa `**Trạng thái: spec đã duyệt..., chưa triển khai.**` thành đã triển khai; cân nhắc gộp nội dung §7.1 vào §2.1/§4.2 chính thức rồi xoá §7 nếu không còn mục nào khác trong "kế hoạch chờ triển khai" (kiểm tra trước khi xoá — không tự xoá section nếu còn nội dung khác).

`USER_MANUAL.md` — xoá khối `> 📌 **Sắp thay đổi...**` (hành vi mới đã là hành vi hiện tại, không còn "sắp").

- [ ] **Step 3: Commit**

```bash
git add xcptool/DEV_PLAN.md xcptool/DESIGN.md xcptool/ARCHITECTURE.md xcptool/USER_MANUAL.md
git commit -m "docs(xcptool): mark ASAP2 struct-typedef feature as shipped"
```

**→ Toàn bộ tính năng xong khi Task 14 commit xanh.** `_group_by_prefix` không còn tồn tại ở đâu trong codebase (`grep -rn "_group_by_prefix" src/` phải ra rỗng).

---

## 11. Kế hoạch tiếp theo — Multi-select & Calibration Dataset (spec 2026-09-19)

**Trạng thái: mục (1), (2) và (3) đã triển khai xong.** 3 tính năng liên
quan, làm theo đúng thứ tự phụ thuộc dưới đây (branch `feature`).

1. **Multi-select trong CalibrationView (Read/Write Selected theo nhiều dòng)**
   — spec: [`docs/superpowers/specs/2026-09-19-calibration-multiselect-design.md`](docs/superpowers/specs/2026-09-19-calibration-multiselect-design.md).
   Tính năng nền tảng, không phụ thuộc gì — làm trước tiên. Đổi tree sang
   `ExtendedSelection` (Ctrl/Shift chọn nhiều dòng), thêm helper
   `_resolve_leaf_names()` dùng chung, mở rộng "Read" và "Write Selected"
   ăn theo tập đang chọn thay vì chỉ 1 dòng.
2. **Export / Import Calibration Dataset** — spec:
   [`docs/superpowers/specs/2026-09-19-calibration-dataset-export-import-design.md`](docs/superpowers/specs/2026-09-19-calibration-dataset-export-import-design.md),
   plan: [`docs/superpowers/plans/2026-09-21-calibration-dataset-export-import-plan.md`](docs/superpowers/plans/2026-09-21-calibration-dataset-export-import-plan.md).
   Phụ thuộc mục (1) — "Export Selected to File" cần multi-select. Chuột
   phải trên tree: Export All / Export Selected / Import Dataset (file
   JSON), module mới `a2l/dataset.py`.

   **Triển khai thật (khác spec ở một điểm, bắt buộc bởi kiến trúc):**
   `calibration_view.py` không gọi `a2l.dataset.build_dataset`/`apply_dataset`
   trực tiếp như spec mô tả — `tests/test_boundaries.py` cấm `ui/` import
   `xcptool.a2l`. Hai hàm đó được gọi qua `Session.export_dataset()`/
   `import_dataset()` mới (giống hệt cách `load_a2l()` đã làm) — xem plan ở
   trên cho lý do đầy đủ. `apply_dataset()` cũng nhận thêm `a2l_path`
   (không có trong signature gốc của spec) vì việc so checksum với A2L đang
   nạp cần đọc lại file đó — `A2LDatabase` không tự lưu checksum của chính
   nó. Test: 565 test pass (`pytest tests/ -x -q`), `--selftest --session
   fake` xanh 15/15 bước qua event loop thật.
3. **Generate hex/s19 file** (calib đã hiệu chỉnh → merge vào file hex/s19
   gốc nạp ECU) — spec:
   [`docs/superpowers/specs/2026-09-21-hexfile-generate-design.md`](docs/superpowers/specs/2026-09-21-hexfile-generate-design.md),
   plan: [`docs/superpowers/plans/2026-09-21-hexview-generate-hex-plan.md`](docs/superpowers/plans/2026-09-21-hexview-generate-hex-plan.md).

   **Triển khai thật (khác dự kiến ban đầu ở dòng trên, chốt lại lúc
   brainstorm):** không tái dùng dataset engine của mục (2) làm nguồn giá
   trị trực tiếp trong CalibrationView như dự kiến — thay vào đó là một
   **view mới hoàn toàn, "Hex View"**, ngang hàng Calibration/Measurement
   trên nav rail. Luồng: menu Session → "Load Hex/S19…" nạp file gốc vào
   session state (`Session.load_hex_file()`), hiển thị 2 bảng
   Origin/Mod song song (1 dòng/leaf calibration, không phải hex-dump toàn
   file); nút "Generate hex from dataset" đọc 1 file dataset JSON đã
   export từ mục (2), validate qua `Session.import_dataset()` (dùng lại y
   nguyên), UI tự encode bằng `encode_value()` (mới tách ra
   `ui/value_codec.py` dùng chung Calibration/Hex View) rồi patch qua
   `Session.generate_hex_from_dataset()`. Module mới `a2l/hexfile.py`
   (bọc `bincopy`) thuần address/bytes, không biết gì về A2L — giữ đúng
   nguyên tắc "UI tự encode, backend chỉ patch thô" đã dùng cho mục (2).
   Địa chỉ không khớp file gốc → dừng toàn bộ, liệt kê đủ lỗi (không
   silent-skip như mismatch A2L của mục 2).

   Bắt được 1 bug thật lúc code: `bincopy.BinFile.as_binary(min, max)` độn
   `0xFF` tới `max` khi có segment thật nằm sau khoảng hỏi — kể cả khi
   toàn bộ khoảng hỏi nằm *trước* segment thấp nhất — nên coverage-check
   không được suy từ độ dài kết quả trả về, phải soi trực tiếp
   `bf.segments`. Cũng phát hiện `QFileDialog`/`QMessageBox` treo vô thời
   hạn dưới `QT_QPA_PLATFORM=offscreen` nếu test không mock — không timeout
   sạch, cả suite trông như "chạy chậm" chứ không fail rõ ràng. Test: 621
   test pass (`pytest tests/ -q`), `--selftest --session fake` xanh 15/15
   bước qua event loop thật (không thêm bước riêng cho Hex View vào
   selftest — đúng tiền lệ mục (2) cũng không thêm, pytest là nơi verify
   theo tính năng).
