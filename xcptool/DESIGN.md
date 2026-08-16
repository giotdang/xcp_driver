# XCP Master cho AURIX — Design & Implementation Plan

Công cụ PC thay thế CANape/INCA, viết riêng cho XCP slave TC2xx trong repo này.

> **Trạng thái:** design đã chốt (2026-08-16). Chưa viết code.
> **Artifact bản đẹp:** https://claude.ai/code/artifact/c3d6c050-7ecd-41c1-8f36-43bbb467a3f3
> **Cơ sở đối chiếu:** `driver/xcp_cfg.h`, `driver/Xcp_Handler.c`, `driver/port/tricore_illd/xcp_can_tricore.c`, `examples/xcp_daq_example.a2l` @ commit `f48153d`

---

## 1. ECU tham chiếu — giá trị kỳ vọng, KHÔNG phải hằng số để code theo

> ⚠️ **Đọc kỹ trước khi dùng bảng này** *(cập nhật 2026-08-16)*
>
> Bản design gốc đặt tên mục này là *"slave đã quyết định hộ phần lớn thiết kế"* và
> chủ ý hardcode theo slave TC2xx trong repo. **Chủ trương đã đổi:** công cụ phải
> dùng lại được cho nhiều ECU khác nhau, nên không giá trị nào dưới đây được nằm
> trong logic — tất cả hỏi ECU lúc CONNECT, hoặc do user cấu hình.
>
> Bảng này từ nay có hai công dụng hợp lệ:
> 1. Giá trị **kỳ vọng** để đối chiếu khi test với ECU tham chiếu
> 2. Cấu hình mặc định cho fake slave
>
> Xem `DEV_PLAN.md` §1.2 để biết lấy từng đặc tính từ lệnh XCP nào.

Mọi dòng dưới đây trích từ code của slave tham chiếu, không phải giả định.

| Đặc tính | Giá trị | Hệ quả cho master |
|---|---|---|
| Transport | CAN 11-bit, 500 kbps<br>CRO → `0x7E0`, DTO/CRM ← `0x7E1` | Response và DAQ data **dùng chung một CAN ID** → phải demux theo byte 0 |
| MAX_CTO / MAX_DTO | 8 / 8 | Không block mode. UPLOAD tối đa 7 byte/lần |
| DLC | luôn = 8 | `MAX_DLC_REQUIRED` — pad đủ 8 byte kể cả lệnh 1 byte |
| Byte order | little-endian | `struct.unpack('<...')` |
| DAQ config | DYNAMIC | Master tự cấp phát qua `FREE_DAQ → ALLOC_*` |
| DAQ identification | ABSOLUTE (PID 1 byte) | `PID = firstPid(list) + odt_index` |
| Timestamp | DWORD, 10 ns/tick, ticks=1 | 4 byte, **chỉ có trong ODT đầu tiên** của mỗi list |
| Overrun indication | bit 7 của PID | Mask `PID & 0x7F` khi tra bảng |
| Calibration page | 0 = RAM (working), 1 = ROM (reference) | Địa chỉ A2L luôn là ROM; slave tự remap sang RAM |

### Resource và feature

| Feature | Trạng thái | Ghi chú |
|---|---|---|
| CAL/PAG | ✅ bật | |
| DAQ | ✅ bật | |
| STIM | ❌ tắt | |
| PGM (flash) | ❌ tắt | |
| Seed & Key | ❌ tắt | Connect là dùng được ngay |
| `BUILD_CHECKSUM` | ❌ tắt | Không verify vùng nhớ bằng checksum → phải UPLOAD rồi diff trên PC |
| `GET_DAQ_EVENT_INFO` | ❌ tắt | **Không dò được event lúc runtime** |

### ⚠️ Điểm mấu chốt

Vì `GET_DAQ_EVENT_INFO` tắt (`kXcpMaxEvent` không được define), **A2L là nguồn sự thật bắt buộc**,
không phải tuỳ chọn cho tiện: nó là nơi *duy nhất* master biết event 0 = "10 ms raster",
event 1 = "100 ms raster". → A2L parser nằm trên đường tới hạn, không được để tới phase cuối.

---

## 2. Kiến trúc — 5 lớp

Nguyên tắc: **protocol core không biết gì về GUI, và cũng không biết gì về CAN.**

```
ui/  cli/    Scope, bảng calibration, cây signal, cửa sổ debug CAN
             CHỈ gọi session/ qua giao diện trong session/api.py.
             Không import master/, transport/ hay a2l/ — test ranh giới ép luật
   ▲ session/api.py — Session Protocol, dataclass, cây ngoại lệ
session/     Kết dính A2L với slave. "Đo engineRpm" → tra symbol →
             tính ODT layout → gọi DAQ engine. Nghiệp vụ, không có byte
   ▲ symbol table + measurement request
a2l/         Parser + symbol database. MEASUREMENT, CHARACTERISTIC,
             COMPU_METHOD, RECORD_LAYOUT, IF_DATA XCP → dict tra theo tên
   ▲ ────────────── (độc lập hoàn toàn) ──────────────
master/      Protocol core. CONNECT/UPLOAD/DOWNLOAD, DAQ allocation,
             DTO decoder, timeout T1, retry qua SYNC.
             KHÔNG import GUI, KHÔNG import python-can
   ▲ send(bytes) / on_frame(bytes)
transport/   Backend hoán đổi được: pcan, vector, slcan,
             udp (cho sim), replay (đọc lại log để debug offline)
```

### Ba luồng chạy song song

Chỗ dễ sai nhất về kiến trúc — DAQ có thể bắn 100 frame/s trong khi user đang ghi calibration.

- **RX thread** — `bus.recv()`, phân loại frame, đẩy DTO vào ring buffer, đẩy CRM vào `queue.Queue(maxsize=1)`
- **Command (luồng gọi)** — gửi CRO rồi `get(timeout=T1)`. Đồng bộ, dễ test
- **UI thread** — mỗi 30–50 ms rút hết ring buffer và vẽ. *Không* vẽ theo từng frame

---

## 3. Năm quyết định đã chốt

### QĐ1 — Stack: **Python + PySide6**

- `python-can` — PEAK, Vector XL, Kvaser, SocketCAN, slcan trên cùng một API
- `pyqtgraph` — scope thời gian thực
- `asammdf` — ghi MDF4 (đúng định dạng CANape xuất ra)
- `PySide6-Fluent-Widgets` (zhiyiYo) — bộ widget Fluent Design (nav sidebar, table, card...) cho lớp `ui/` *(chốt 2026-08-16, xem QĐ5)*

C#/WPF là lựa chọn thứ hai nếu muốn single .exe, nhưng phải tự wrap từng driver CAN.
C++/Qt chỉ đáng cân nhắc nếu cần DAQ > 10 kHz — CAN 500 kbps trần vật lý ~4000 frame/s, Python thừa sức.

### QĐ2 — Protocol core: **tự viết**, tham khảo `pyxcp`

Slave dùng tập lệnh hẹp và ta kiểm soát cả hai đầu → core chỉ ~600–800 dòng.
Tự viết = debug được tận byte, không phải uốn theo cách cấu hình của thư viện.
Giá trị dự án nằm ở DAQ packing + A2L + GUI, không ở việc lặp lại khung lệnh.

### QĐ3 — Phần cứng: **đa nền tảng, user chọn lúc setup** *(chốt 2026-08-16)*

Không khoá vào một hãng. PEAK, Vector và ETAS đều nằm sau cùng một API của `python-can`,
nên đây là việc cấu hình chứ không phải viết ba driver.

| Backend | `interface=` | Nền tảng | Cần cài trước |
|---|---|---|---|
| PEAK PCAN-USB | `pcan` | Win / Linux | PCAN-Basic driver |
| Vector VN16xx | `vector` | Windows | XL Driver Library |
| ETAS ES58x / ES5xx | `etas` | **Windows only** | ETAS Distribution Package (BOA) |
| CANable / slcan | `slcan` | Win / Linux | driver COM ảo |
| Sim nội bộ | `udp` | mọi nơi | không |
| Phát lại trace | `replay` | mọi nơi | không |

`transport/registry.py` giữ bảng đăng ký; `can.detect_available_configs()` dò thiết bị đang cắm;
`~/.xcptool/config.toml` nhớ lựa chọn. Thêm hãng mới = thêm một entry, không đụng `master/`.

Chi tiết thiết kế lớp thiết bị: xem [DEV_PLAN.md §6](DEV_PLAN.md).

### QĐ4 — ~~Biên dịch chính slave này thành sim~~ → **hoãn sang giai đoạn sau**

> ⚠️ **Đã đảo lại** *(2026-08-16)*. Công cụ nay độc lập hoàn toàn với `driver/`, và
> mục tiêu trước mắt là **GUI ổn định**, không phải đối chiếu độ đúng giao thức với
> slave thật. Cho mục tiêu đó, fake slave viết bằng Python **tốt hơn** sim C: nó cố
> tình cư xử tệ được — timeout, frame méo, ngắt giữa chừng, flood bus — thứ mà slave
> thật rất khó ép làm, mà lại chính là thứ làm lộ crash.
>
> Chạy trên `can.Bus(interface='virtual')` chứ không phải UDP, nên đường code của
> tầng transport y hệt lúc cắm PCAN thật.
>
> Lập luận bên dưới vẫn đúng **cho việc kiểm chứng độ đúng giao thức** — sẽ quay lại
> khi tới giai đoạn đó. Xem `DEV_PLAN.md` §3 và §8.

**Đừng viết slave giả lập bằng Python** — nó sẽ mô phỏng lại *cách ta hiểu* giao thức,
nên sẽ đồng ý với mọi lỗi mà master mắc phải.

Thay vào đó: `Xcp_Handler.c` đã tách sạch phần cứng qua `Xcp_ConfigType`. Viết thêm port
`driver/port/pc_sim/`:

| Callback | Implement trên PC |
|---|---|
| `Transmit` / `Receive` | UDP datagram về localhost thay vì MultiCAN |
| `GetTimestamp` | đồng hồ hệ thống, quy về đơn vị 10 ns |
| `EnterCritical` / `ExitCritical` | để rỗng (single-thread) |

Biên dịch MinGW → `xcp_sim.exe`. Master nói chuyện với **đúng protocol core sẽ chạy trên xe**,
chạy được trong CI, không cần board. Skill `xcp-porting-guide` trong repo đã mô tả sẵn quy trình.

### QĐ5 — Giao diện: **PySide6-Fluent-Widgets** *(chốt 2026-08-16)*

Ưu tiên độ đẹp/tốc độ dựng UI hơn là widget QWidget trần. Thay `QTreeView`/`QTableView`/`QPushButton`
chuẩn bằng bản Fluent (`TreeView`, `TableWidget`, `NavigationInterface`...) của thư viện; `pyqtgraph`
vẫn nhúng như một QWidget thường bên trong container Fluent, không xung đột.

> ⚠️ **License: dual — GPLv3 cho non-commercial, cần mua license thương mại nếu dùng commercial**
> (zhiyiYo, `PySide6-Fluent-Widgets` trên PyPI). Nếu xcptool về sau gắn với sản phẩm/dự án công ty
> thay vì công cụ nội bộ/cá nhân, **phải xác nhận điều khoản license trước khi phase 05 bắt đầu.**

Theme tối: **không** dùng `pyqtdarktheme`/`pyqtdarktheme-fork` — cả hai đã ngừng phát triển
(không release ~12 tháng). Fluent-Widgets có sẵn `setTheme(Theme.DARK)` riêng, dùng cái đó;
nếu cần theme ngoài widget Fluent (vd. cửa sổ trace hex dùng QWidget thường) thì phủ thêm QSS thủ công.

---

## 4. DAQ engine — phần khó nhất

### 4.1 Ngân sách byte không đồng đều

Timestamp 4 byte **chỉ chèn vào ODT đầu tiên** của mỗi DAQ list:

```
ODT 0 (có timestamp):     [PID][TS][TS][TS][TS][data][data][data]   → 3 byte
ODT 1,2,3… (không TS):    [PID][data][data][data][data][data][data][data]  → 7 byte
```

### 4.2 🔴 CẢNH BÁO — slave KHÔNG tự bảo vệ

`Xcp_Handler.c:3064` khi xử lý `WRITE_DAQ` **chỉ kiểm tra kích thước từng entry ≤ 7**.
Không có chỗ nào cộng dồn các entry trong một ODT rồi đối chiếu với 8 byte DTO
(đã kiểm tra cả `XcpAllocOdtEntry` ở dòng 1095).

**Hệ quả:** nếu master nhồi 7 byte vào ODT 0 khi timestamp bật, slave trả `0xFF` (OK) bình thường
→ lúc DAQ chạy, vòng lặp sampling ghi `1 + 4 + 7 = 12 byte vào buffer 8 byte`, tràn sang
phần tử kế tiếp trong send queue. Triệu chứng: dữ liệu sai lệch ngẫu nhiên hoặc ECU treo,
và sẽ đi tìm bug ở nhầm chỗ.

Đây là hành vi tiêu chuẩn của XcpBasic (spec giả định master đáng tin cậy), không phải lỗi mới.
Nhưng nó biến packing đúng thành **trách nhiệm tuyệt đối của master**.

→ **Viết unit test cho hàm packing TRƯỚC khi viết bất cứ dòng GUI nào.**

### 4.3 Thuật toán packing

```python
# Một signal KHÔNG được cắt đôi qua hai ODT.
def pack_odts(signals, timestamp_on, max_dto=8):
    first_budget = max_dto - 1 - (4 if timestamp_on else 0)   # 3
    rest_budget  = max_dto - 1                                # 7

    odts, cur, used = [], [], 0
    budget = first_budget
    for s in sorted(signals, key=lambda x: -x.size):   # first-fit decreasing
        if s.size > rest_budget:
            raise ValueError(f"{s.name}: {s.size}B > {rest_budget}B, phải tách nhỏ")
        if used + s.size > budget:
            odts.append(cur)
            cur, used, budget = [], 0, rest_budget
        cur.append(s); used += s.size
    if cur: odts.append(cur)
    return odts
```

**Hệ quả thực tế với ví dụ trong repo:**
- `speedPidTelemetry` là struct 12 byte > 7 → bắt buộc tách thành 3 entry float32 riêng (A2L mẫu đã làm đúng)
- `torqueSamples[4]` khai `MATRIX_DIM 4` gọn trong A2L, nhưng trên đường truyền vẫn là 4 entry 4-byte tách biệt

### 4.4 Trình tự cấu hình — sai thứ tự là nhận `CRC_SEQUENCE`

Slave kiểm tra rất chặt (`XcpAllocDaq` từ chối nếu `OdtCount != 0`):

```
FREE_DAQ                              # xoá sạch, bắt buộc trước tiên
ALLOC_DAQ(n_lists)
for daq in lists:  ALLOC_ODT(daq, n_odts)          # hết mọi list rồi mới sang bước sau
for daq, odt:      ALLOC_ODT_ENTRY(daq, odt, n_entries)

for daq, odt:
    SET_DAQ_PTR(daq, odt, 0)
    for e in entries:  WRITE_DAQ(bit_offset=0xFF, size, ext=0, addr)

for daq:
    SET_DAQ_LIST_MODE(mode=0x10, daq, event, prescaler=1, prio=0)   # 0x10 = bật timestamp
    first_pid[daq] = START_STOP_DAQ_LIST(mode=2, daq)               # 2 = select, trả firstPid

START_STOP_SYNCH(mode=1)                                            # khởi động đồng loạt
```

`first_pid` trả về từ bước select chính là chìa khoá giải mã. Master dựng bảng phẳng
`pid → (danh sách signal, offset trong frame)`; vòng lặp RX chỉ còn tra bảng.

### 4.5 Đường tắt: đo bằng polling trước khi đo bằng DAQ

`SHORT_UPLOAD` đọc tối đa 7 byte tại địa chỉ bất kỳ chỉ bằng một lệnh.
Gọi lặp 10 lần/giây → đã có "scope" chạy được từ phase 2, trong khi DAQ engine chưa viết.
Chậm và không có timestamp chuẩn, nhưng **tách bạch được lỗi địa chỉ khỏi lỗi DAQ**.

---

## 5. Calibration — mô hình hai trang trên phía PC

Slave phân biệt *trang ECU đang đọc* và *trang XCP đang nhìn* — hai thứ độc lập.
Địa chỉ A2L luôn trỏ ROM; `Xcp_GetPointer()` tự chuyển hướng sang RAM khi XCP ở working page.

- **Ghi tham số** — về nguyên tắc `SHORT_DOWNLOAD(addr, size, data)` với địa chỉ ROM lấy thẳng từ A2L,
  không tự tính lại địa chỉ RAM (đó là việc của slave). **Trên CAN thì không dùng được**: dung lượng
  SHORT_DOWNLOAD = MAX_CTO − 8, mà CAN giới hạn khung 8 byte nên MAX_CTO clamp về 8 → dung lượng = 0.
  xcptool luôn đi bằng `SET_MTA` + `DOWNLOAD` trên CAN *(xác nhận 2026-08-16 khi backend triển khai
  `master/core.py`)*; SHORT_DOWNLOAD chỉ có ý nghĩa nếu sau này có transport khung lớn hơn (XCP-on-Ethernet, M5).
- **Nhận `0xFE` + `CRC_WRITE_PROTECTED`** — không phải bug, mà là XCP đang trỏ reference page.
  Thông báo đúng nguyên nhân đó, kèm nút chuyển về working page.
- **So sánh working vs reference** — checksum đã tắt → chuyển XCP page qua lại, UPLOAD cả hai
  vùng rồi diff trên PC. Đây là tính năng "so với giá trị gốc" mà kỹ sư hiệu chỉnh dùng liên tục.
- **Xuất/nhập bộ tham số** — JSON hoặc DCM, để chia sẻ kết quả hiệu chỉnh giữa các lần chạy.

> **Chi tiết dễ bỏ sót:** với struct/mảng như `speedPid` hay `torqueMap[8]`, đọc/ghi **trọn khối**
> bằng `SET_MTA` + `DOWNLOAD` liên tiếp, thay vì mỗi field một `SHORT_DOWNLOAD`. Ghi từng field
> rời rạc → ECU chạy qua trạng thái nửa cũ nửa mới; với hệ số PID có thể làm vòng điều khiển giật một nhịp.

---

## 6. Lộ trình 6 giai đoạn

Thứ tự sắp để **rủi ro lớn nhất bị đẩy lên sớm nhất**. GUI để cuối vì nó là phần duy nhất
có thể xây trên nền đã chắc chắn.

| # | Giai đoạn | Công | Mốc chứng minh |
|---|---|---|---|
| 01 | **Nối dây và nhìn thấy byte** — khung repo, lớp transport, CLI in mọi frame trên 0x7E0/0x7E1 | ~0.5 ngày | Gửi `FF 00`, thấy slave trả frame bắt đầu bằng `FF` |
| 02 | **Protocol core + slave giả lập** — CONNECT/DISCONNECT/GET_STATUS/SYNC, SET_MTA/UPLOAD/SHORT_UPLOAD, DOWNLOAD/SHORT_DOWNLOAD, timeout T1, retry. Song song: port `pc_sim` | ~2 ngày<br>⚠️ rủi ro cao nhất | Ghi một giá trị vào `systemGain` rồi đọc lại đúng — qua UDP, không cần board |
| 03 | **A2L parser** — MEASUREMENT, CHARACTERISTIC, COMPU_METHOD, RECORD_LAYOUT, MATRIX_DIM, IF_DATA XCP → symbol table | ~2 ngày | Nạp `xcp_daq_example.a2l`, in ra 8 measurement đúng địa chỉ và kiểu |
| 04 | **DAQ engine** — packing (có unit test cho ngân sách 3 byte), chuỗi ALLOC, bảng giải mã theo PID, phát hiện overrun bit 7, ring buffer | ~3 ngày<br>nặng nhất | Ghi 60s `engineRpm` ra CSV, timestamp đều 10 ms, không mất frame |
| 05 | **Giao diện** — dựng trên PySide6-Fluent-Widgets: cây signal, scope pyqtgraph, bảng calibration sửa trực tiếp, chỉ báo trang ROM/RAM, cửa sổ trace hex | ~4 ngày | Kéo signal vào scope và sửa tham số không cần dòng lệnh |
| 06 | **Mở rộng** — MDF4 qua asammdf, scripting Python, nhập/xuất bộ tham số, XCP-on-Ethernet | tuỳ nhu cầu | Script chạy kịch bản đo–hiệu chỉnh–ghi log không cần người trực |

---

## 7. Danh sách bẫy

| Bẫy | Cách tránh |
|---|---|
| **Demux nhầm DTO thành response** | CRM và DTO chung ID `0x7E1`. Byte 0 ∈ `{0xFF,0xFE,0xFD,0xFC}` → CTO, còn lại → DAQ. Với 2 list nhỏ, PID không bao giờ chạm vùng đó |
| **Quên mask bit 7 của PID** | Khi ECU quá tải, PID được OR thêm `0x80`. Không mask → KeyError đúng lúc hệ thống đang căng nhất |
| **Timestamp tràn số sau ~43 giây** | Bộ đếm 32-bit @ 10 ns quay vòng sau 42,9 s. Master phải tự cộng dồn số lần tràn |
| **Không gửi FREE_DAQ khi bắt đầu** | Phiên trước thoát bất thường → cấu hình DAQ cũ còn trong ECU. Luôn `FREE_DAQ` ngay sau CONNECT |
| **Bỏ qua DISCONNECT khi thoát** | Slave tiếp tục bắn DAQ lên bus. Bắt cả trường hợp thoát do lỗi, không chỉ nút đóng |
| **Frame ngắn hơn 8 byte** | A2L khai `MAX_DLC_REQUIRED`. Pad CRO đủ 8 byte kể cả `DISCONNECT` 1 byte |
| **Địa chỉ A2L lệch sau khi build lại** | Đưa `tools/sync_a2l_addresses.py` vào build script. Địa chỉ lệch biểu hiện thành "số đo vô nghĩa" → dễ đổ oan cho master |
| **Vẽ đồ thị theo từng frame** | Gom vào buffer, repaint theo timer 30–50 ms. Repaint 100 Hz làm GUI đứng, dễ tưởng do CAN chậm |

---

## 8. Bắt đầu từ đâu

**Lịch triển khai chi tiết đã chuyển sang [DEV_PLAN.md](DEV_PLAN.md)** — bản rút gọn 7 ngày,
thay cho lộ trình 11,5 ngày ở §6 trên.

### Quyết định đã chốt (2026-08-16)

| | |
|---|---|
| Tên package | **`xcptool`** |
| Phần cứng | **Đa nền tảng**, user chọn lúc setup — PEAK / Vector / ETAS / slcan |
| Firmware | **Không đụng vào code production.** Dùng stub header iLLD trong `driver/port/pc_sim/illd_stub/` để biên dịch core trên PC với 0 dòng thay đổi trong `driver/`. Patch dọn sạch (`docs/decouple-core.patch`) để dành áp dụng sau |
