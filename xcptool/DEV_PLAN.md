# Development Plan — M1 + M2, hai agent làm song song

Bản này thay cho lộ trình 7 ngày tuần tự trước đó. Ba thứ đã thay đổi *mục tiêu*,
không chỉ thay đổi lịch:

| | Trước | Bây giờ |
|---|---|---|
| Quan hệ với firmware trong repo | Biên dịch `Xcp_Handler.c` thành `xcp_sim.exe` để test | **Không dính gì tới `driver/`.** Công cụ độc lập, dùng lại được cho ECU khác |
| Đặc tính ECU | Hardcode theo slave TC2xx trong repo | **Hỏi ECU lúc CONNECT.** Không hằng số nào của một ECU cụ thể nằm trong logic |
| Đích của đợt này | GUI đầy đủ + DAQ + A2L | **M1 + M2**: chọn thiết bị → CONNECT → cửa sổ debug CAN → đọc/ghi theo địa chỉ. Chạy ổn định, không crash |

Ra khỏi phạm vi đợt này: `driver/port/pc_sim/`, stub header iLLD, MinGW, A2L parser,
DAQ engine, scope, MDF4, kiểm tra trên board thật.
Hệ quả thực tế: **không cần trình biên dịch C nữa.**

> **Cơ sở:** `DESIGN.md` (kiến trúc) · `src/xcptool/session/api.py` (contract, lead sở hữu)

---

## 0. Điều kiện tiên quyết — chưa xong thì chưa spawn agent

| | Trạng thái |
|---|---|
| Python 3.12.10 tại `C:\Program Files\Python312\` | ✅ đã cài |
| venv tại `xcptool/.venv/` | ✅ đã tạo |
| `pip install -e ".[dev]"` — python-can 4.6.1, PySide6 6.11.1, pytest 9.1.1 | ✅ đã cài |
| `pytest tests/test_boundaries.py` | ✅ 6 passed, và đã kiểm chứng nó **bắt được** vi phạm thật |
| gcc / MinGW | ✅ **không cần nữa** |
| Phần cứng CAN | ✅ không cần — dùng `virtual` bus |

**Mọi lệnh phải chạy bằng interpreter của venv**, không phải `python` trên PATH:

```
G:\@Autosar\xcp\xcp_driver\xcptool\.venv\Scripts\python.exe -m pytest -q
```

Kích hoạt venv cho tiện: `.venv\Scripts\Activate.ps1`.

---

## 1. Hai nguyên tắc chi phối mọi quyết định

### 1.1 Độc lập với firmware

`xcptool/` không được import, đọc, hay giả định bất cứ thứ gì trong `driver/`.
Ràng buộc duy nhất giữa hai bên là **giao thức XCP trên dây** — đúng như quan hệ
với một ECU của hãng khác.

Cưỡng chế bằng `tests/test_boundaries.py`, không bằng kỷ luật.

### 1.2 Độc lập với một ECU cụ thể

`DESIGN.md` §1 liệt kê đặc tính của slave trong repo này. Từ nay coi bảng đó là
**giá trị kỳ vọng của ECU tham chiếu để đối chiếu khi test**, không phải hằng số
để code theo. Mọi thứ trong bảng đều hỏi được:

| Đặc tính | Lấy từ |
|---|---|
| MAX_CTO, MAX_DTO | byte 3 và 4–5 của response CONNECT |
| Byte order, block mode | byte 2 (comm_mode_basic) |
| CAL/PAG, DAQ, STIM, PGM, Seed&Key | byte 1 (resource) |
| Phiên bản protocol / transport | byte 6, 7 |
| DAQ dynamic/static, kiểu PID | `GET_DAQ_PROCESSOR_INFO` |
| Kích thước và đơn vị timestamp | `GET_DAQ_RESOLUTION_INFO` |
| CRO / DTO CAN ID, bitrate | `BusConfig` — user cấu hình, lưu ở `~/.xcptool/config.toml` |

ECU không trả lời `GET_DAQ_*`? Bỏ qua êm, đặt `SlaveCaps.daq = None`. Không được
văng lỗi — nhiều ECU tắt các lệnh này.

ECU bật Seed & Key? Không được lặng lẽ hỏng: báo rõ *"ECU yêu cầu seed & key,
công cụ chưa hỗ trợ"* rồi ngắt sạch.

---

## 2. Cây thư mục và quyền sở hữu

Mỗi file có đúng **một** chủ. Đụng file của agent khác = xung đột, không phải giúp đỡ.

```
xcptool/
├── DESIGN.md                          lead
├── DEV_PLAN.md                        lead
├── pyproject.toml                     lead   ← cần thêm dependency thì NHẮN LEAD
├── tests/
│   ├── test_boundaries.py             lead
│   ├── unit/                          backend
│   ├── integration/                   backend
│   └── ui/                            frontend
└── src/xcptool/
    ├── session/
    │   ├── api.py                     lead   ← CONTRACT. Chỉ đọc.
    │   ├── real.py                    backend
    │   └── fake.py                    frontend
    ├── transport/                     backend    registry, virtual, pcan,
    │                                             vector, etas, slcan, replay,
    │                                             config.py (đọc/ghi config.toml)
    ├── master/                        backend    protocol core, capability
    │                                             discovery, từ điển lỗi, codec
    ├── devtools/                      backend    fake slave, script soak
    ├── ui/                            frontend   cửa sổ chính, dialog thiết bị,
    │                                             cửa sổ debug, console lệnh thô,
    │                                             panel bộ nhớ
    └── cli/                           frontend   lệnh `xcptool …`
```

**Vì sao CLI thuộc frontend:** nó là *người tiêu thụ thứ hai* của cùng contract.
Có hai người tiêu thụ độc lập sẽ lộ ngay chỗ contract thiết kế tệ, và cho frontend
thứ chạy được từ giờ đầu — sớm hơn nhiều so với lúc GUI hoàn chỉnh.

---

## 3. Contract — đọc `src/xcptool/session/api.py` trước khi viết dòng nào

Lead đã viết sẵn toàn bộ contract: kiểu dữ liệu, cây ngoại lệ, chữ ký hàm, luật
thread. **Không agent nào được sửa file đó.** Cần đổi → nhắn lead, chờ duyệt;
lead sửa và báo cả hai bên cùng lúc.

Ba luật quan trọng nhất, nhắc lại vì đây là chỗ hay hỏng:

1. **Session không biết Qt tồn tại.** Nó không bao giờ gọi ngược lên UI.
   Frontend gọi các phương thức chặn từ worker thread, đẩy kết quả về UI thread
   bằng Qt signal.
2. **Trace là pull-based.** `drain_trace()` không chặn, an toàn thread; frontend
   gọi theo QTimer 30–50 ms. Không vẽ theo từng frame.
3. **`close()` idempotent và không bao giờ ném.** Frontend gọi nó trong
   `closeEvent()` kể cả khi bus đang lỗi.

### Hai bản giả khác nhau — đừng nhầm

| | `session/fake.py` — **FakeSession** | `devtools/fakeslave.py` — **fake slave** |
|---|---|---|
| Chủ | frontend | backend |
| Là gì | Hiện thực `Session` bằng Python thuần, **không có bus nào** | Một node XCP trên `virtual` bus, trả lời như ECU thật |
| Để làm gì | GUI + CLI chạy và test không cần python-can, không cần backend | Backend test protocol core; và là ECU trong bài test tích hợp |
| Sinh dữ liệu | trace giả, giá trị bộ nhớ giả | frame CAN thật qua `can.Bus(interface='virtual')` |

Cả hai đều phải **mô phỏng được hành vi tồi**, đó là lý do chúng tồn tại:
timeout, response méo, ngắt kết nối giữa chừng, flood bus, mã lỗi lạ.

### Mối lo xuyên suốt — mỗi thứ đúng một chủ

| Mối lo | Chủ | Ghi chú |
|---|---|---|
| Contract, `pyproject.toml`, test ranh giới | lead | agent chỉ đọc |
| Schema và đọc/ghi `~/.xcptool/config.toml` | backend | frontend chỉ gọi qua session |
| Từ điển `CRC_*` → lớp ngoại lệ có tên | backend | frontend không bao giờ nhìn mã thô |
| Chuỗi `TraceEntry.decoded` | backend | frontend **không tự giải mã byte** |
| Ring buffer có trần + đếm `dropped_frames` | backend | bỏ entry cũ nhất, RAM không phình |
| Marshal worker thread → Qt signal | frontend | |
| `sys.excepthook` + `threading.excepthook` + log ra file | frontend | sở hữu entry point app |
| Gọi `close()` khi thoát, kể cả khi thoát do lỗi | frontend | backend đảm bảo `close()` làm đúng |
| Thông báo khi thiếu driver hãng | backend sinh `hint`, frontend hiển thị | |

---

## 4. Hai nhánh mốc — chạy song song, không chặn nhau

Điểm mấu chốt: **nhánh F không phụ thuộc nhánh B cho tới J1.** Frontend build trên
`FakeSession` ngay từ F0.

### Nhánh Backend

| Mốc | Nội dung | Cổng — chứng minh bằng lệnh |
|---|---|---|
| **B0** | Khung package, `transport/virtual.py`, fake slave tối thiểu trả lời CONNECT | `pytest tests/integration/test_virtual_bus.py -q` xanh |
| **B1** | Protocol core: CONNECT / DISCONNECT / GET_STATUS / SYNC, timeout T1, phát `TraceEntry`, từ điển lỗi, **capability discovery** | `pytest tests/unit -q` xanh; test khẳng định `SlaveCaps` khớp cấu hình fake slave, và đổi fake slave sang MAX_CTO=12 thì `SlaveCaps` đổi theo |
| **B2** | `transport/registry.py` đa backend, `list_devices()`, `config.py` đọc/ghi `config.toml` | `list_devices()` liệt kê `virtual` là available và các backend chưa cài driver là unavailable **kèm `hint`**, không ném lỗi, và **không để lọt một dòng cảnh báo nào của python-can ra stderr** (xem §5.1) |
| **B3** | `read()` / `write()` tự chia khối theo MAX_CTO thật; `get_page` / `set_page` / `copy_page` | ghi rồi đọc lại 64 byte khớp bit-for-bit qua fake slave; fake slave ở reference page → nhận đúng `WriteProtectedError` |
| **B4** | Hardening: excepthook trong RX thread, `close()` idempotent, ring buffer có trần, `BusyError` khi gọi chồng | `pytest tests/integration/test_robustness.py -q` — xem §6 |

### Nhánh Frontend

| Mốc | Nội dung | Cổng — chứng minh bằng lệnh |
|---|---|---|
| **F0** | `session/fake.py` đầy đủ contract + khung app PySide6 (cửa sổ chính, status bar, menu) | `pytest tests/ui/test_shell.py -q` (offscreen) xanh; `python -m xcptool.ui.app --session fake` mở được cửa sổ |
| **F1** | Dialog chọn thiết bị (list + nút Detect + nhớ lựa chọn), luồng CONNECT qua worker thread, status bar hiện `SlaveCaps` | click Connect khi FakeSession trễ 3 giây → **UI không đơ**, có spinner, huỷ được |
| **F2** | **Cửa sổ debug CAN**: bảng trace, cột time/dir/ID/hex/decoded, lọc theo kind, tạm dừng, tự cuộn, xoá, xuất file | FakeSession bơm 2000 frame/s trong 60 s → UI vẫn mượt, RAM không tăng, số đếm khớp với `dropped_frames` |
| **F3** | Console lệnh thô: gõ hex → `raw_command()` → hiện response thô | gửi `FF 00` thấy response `FF …` trong console và trong cửa sổ debug |
| **F4** | Panel bộ nhớ: đọc/ghi theo địa chỉ (hex dump có sửa được), điều khiển trang CAL, chỉ báo trang ECU / trang XCP | ghi một vùng rồi đọc lại thấy đúng; FakeSession ném `WriteProtectedError` → hiện thông báo **kèm nút chuyển về working page** |
| **F5** | Hardening: excepthook toàn cục + log file, `closeEvent` gọi `close()`, mọi `XcpToolError` thành thông báo | `pytest tests/ui/test_robustness.py -q` — xem §6 |

### Mốc chung

| Mốc | Nội dung | Cổng |
|---|---|---|
| **J1** | Đổi `FakeSession` → `RealSession` (một dòng), chạy lại toàn bộ kịch bản F1–F4 trên `virtual` bus với fake slave của backend | Mọi thao tác GUI cho kết quả giống hệt lúc chạy trên FakeSession |
| **J2** | Soak 30 phút, đối chiếu contract, cross-review | §6 xanh hết; không dòng ERROR nào trong log |

**Đối chiếu contract trước J1** (skill yêu cầu): backend in ra chữ ký thật của
`RealSession`, frontend in ra danh sách lời gọi thật của mình — lead so hai bên
trước khi ghép. Rẻ hơn debug lúc đã ghép.

---

## 5. Lệnh validate — agent chạy trước khi báo done

Không mốc nào được báo xong nếu còn một lệnh đỏ.

**Backend:**
```
pytest tests/unit tests/integration -q
pytest tests/test_boundaries.py -q
python -m xcptool.devtools.soak --minutes 5 --rate 2000
```

**Frontend:**
```
pytest tests/ui -q                      # QT_QPA_PLATFORM=offscreen
pytest tests/test_boundaries.py -q
python -m xcptool.cli.main --session fake devices
python -m xcptool.cli.main --session fake connect
python -m xcptool.ui.app --session fake --selftest    # mở, thao tác, đóng, thoát 0
```

Test ranh giới chạy ở **cả hai bên** — nó bắt đúng loại lỗi mà agent tự tin nhất
là mình không mắc.

### 5.1 Ba thứ đã đo trên máy này, đừng phát hiện lại

Lead đã chạy thử stack ngày 2026-08-16, kết quả:

- ✅ `can.Bus(interface='virtual')` gửi/nhận được frame 8 byte trong cùng tiến trình.
  Đây là nền của toàn bộ test backend — không cần UDP, không cần phần cứng.
- ✅ PySide6 6.11.1 / Qt 6.11.1 chạy được headless với `QT_QPA_PLATFORM=offscreen`.
  Test GUI tự động chạy được. Có cảnh báo *"Cannot find font directory"* — vô hại
  với offscreen, đừng mất thời gian sửa.
- ⚠️ **`can.detect_available_configs()` phun ~20 dòng cảnh báo ra stderr** cho mọi
  backend chưa cài driver (Kvaser, IXXAT, NI-CAN, Vector, slcan, SYSTEC…). Đây
  không phải lỗi, nhưng nếu để nguyên thì cửa sổ debug và log của công cụ sẽ ngập
  rác ngay lần chạy đầu. Backend phải bắt các cảnh báo này (`logging` capture của
  python-can) và **chuyển thành `DeviceInfo.hint`** đúng như contract yêu cầu —
  đây chính là lý do trường `hint` tồn tại.
- Trên máy này hiện chỉ dò ra `virtual`; chưa cắm PEAK/Vector/ETAS và chưa cài
  driver hãng nào. Đường `available=False` + `hint` vì thế là đường **chính**, không
  phải trường hợp biên.

---

## 6. "Không crash" là tiêu chí nghiệm thu, không phải lời chúc

Đây là yêu cầu ngang hàng với tính năng, nên nó phải kiểm tra được. Mỗi dòng dưới
là một test có thật, không phải nguyên tắc chung chung.

| Tình huống | Hành vi bắt buộc | Chủ |
|---|---|---|
| Exception trong RX thread | Ghi log, chuyển `state = ERROR`, **app vẫn sống** | backend |
| Rút dây thiết bị giữa phiên | `BusError` nổi lên thành thông báo, không traceback | backend + frontend |
| ECU không trả lời | Hết T1 → `XcpTimeoutError`, UI không đơ | backend |
| Frame ngắn hơn dự kiến / méo | `MalformedResponseError`, **không** `struct.error` hay `IndexError` | backend |
| Frame lạ trên CAN ID khác | Ghi trace `kind='other'`, không xử lý nhầm | backend |
| Flood 5000 frame/s | Ring buffer chạm trần → bỏ entry cũ, tăng `dropped_frames`, RAM phẳng | backend |
| Gọi lệnh chồng lên nhau | `BusyError` ngay, không xếp hàng, không deadlock | backend |
| Đóng app khi đang bận | `close()` gửi DISCONNECT, join thread, không treo, không ném | backend |
| Đụng widget từ thread khác | Không bao giờ xảy ra — mọi cập nhật UI qua Qt signal | frontend |
| `XcpToolError` bất kỳ thoát lên UI | Thành hộp thoại có nội dung đọc được, không phải traceback | frontend |
| Ngoại lệ ngoài dự kiến | `excepthook` bắt, ghi log kèm traceback, hiện lời xin lỗi, app không biến mất im lặng | frontend |
| Soak 30 phút, 2000 frame/s | RAM không tăng đơn điệu, không dòng ERROR nào trong log | cả hai |

Log ghi ra `~/.xcptool/logs/` kèm `faulthandler.enable()` — crash không tái hiện
được vẫn phải để lại dấu vết.

---

## 7. Bẫy còn nguyên giá trị

Giữ lại từ bản trước, những cái vẫn đúng trong phạm vi M1/M2:

| Bẫy | Cách tránh |
|---|---|
| **Demux nhầm DTO thành response** | CRM và DTO dùng chung CAN ID. Byte 0 ∈ `{0xFF,0xFE,0xFD,0xFC}` → CTO, còn lại → DAQ |
| **Frame ngắn hơn 8 byte** | ECU có thể khai `MAX_DLC_REQUIRED`. `BusConfig.pad_dlc` điều khiển, mặc định bật |
| **Bỏ qua DISCONNECT khi thoát** | Bắt cả trường hợp thoát do lỗi, không chỉ nút đóng |
| **Vẽ theo từng frame** | Gom vào buffer, repaint theo timer 30–50 ms. Repaint 100 Hz làm GUI đứng và rất dễ đổ oan cho CAN chậm |
| **Im lặng khi thiếu driver hãng** | Hiện đúng tên gói cần cài. Đây là lỗi user gặp nhiều nhất với công cụ loại này |
| **Timestamp của thiết bị khác nhau về chất lượng** | PEAK/Vector có timestamp phần cứng, slcan do phần mềm sinh. Ghi rõ trong UI |

---

## 8. Hoãn có chủ đích

| Hoãn tới | Nội dung |
|---|---|
| M3 | A2L parser → làm việc theo tên, cây signal, bảng calibration |
| M4 | DAQ engine, scope pyqtgraph — **nhớ: ngân sách 3 byte của ODT 0, và bản `pack_odts` trong `DESIGN.md` §4.3 đang sinh ODT 0 rỗng, phải sửa cùng test** |
| M5 | MDF4, xuất/nhập bộ tham số, XCP on Ethernet, đóng gói .exe |
| Giai đoạn sau | Kiểm tra trên board thật; `driver/port/pc_sim/` nếu vẫn còn muốn |

---

## 9. Vì sao chia đúng hai agent như thế này

| Anti-pattern của skill | Bản này tránh bằng cách |
|---|---|
| Spawn song song mà không có contract | Lead viết xong `session/api.py` **trước** khi spawn |
| Agent B chờ agent A mãi mãi | Nhánh F chạy trên `FakeSession`, không chặn tới J1 |
| Ranh giới mơ hồ ("giúp phần backend") | §2 liệt kê từng thư mục kèm chủ sở hữu |
| Mối lo xuyên suốt không ai nhận | §3 gán từng thứ cho đúng một agent |
| Contract ngầm ("API trả về session") | `api.py` là dataclass và chữ ký thật, không phải văn xuôi |
| Hai agent cùng sửa file dùng chung | `pyproject.toml` và `api.py` do lead sở hữu |
