# xcptool — Design Document

> **Trạng thái:** M1 ✅ M2 ✅ M3 ✅ — 346 tests, offscreen selftest pass (2026-08-18)
> **Kế hoạch triển khai & milestone:** xem [DEV_PLAN.md](DEV_PLAN.md)
> **Contract chính thức:** `src/xcptool/session/api.py`

---

## 1. ECU tham chiếu — giá trị kỳ vọng, KHÔNG phải hằng số để code theo

> ⚠️ Bảng này có hai công dụng hợp lệ duy nhất:
> 1. **Giá trị kỳ vọng** để đối chiếu khi test với ECU tham chiếu (AURIX TC2xx trong repo)
> 2. **Cấu hình mặc định** cho fake slave
>
> Không giá trị nào được hardcode trong logic. Mọi thứ hỏi ECU lúc CONNECT hoặc do user cấu hình.
> `test_boundaries.py::test_no_hardcoded_ecu_constants` cưỡng chế điều này bằng AST.

Mọi dòng dưới đây trích từ code của slave tham chiếu, không phải giả định.

| Đặc tính | Giá trị | Hệ quả cho master |
|---|---|---|
| Transport | CAN 11-bit, 500 kbps, CRO → `0x7E0`, DTO/CRM ← `0x7E1` | Response và DAQ dùng chung một CAN ID → phải demux theo byte 0 |
| MAX_CTO / MAX_DTO | 8 / 8 | Không block mode. UPLOAD tối đa 7 byte/lần |
| DLC | luôn = 8 | `MAX_DLC_REQUIRED` — pad đủ 8 byte kể cả lệnh 1 byte |
| Byte order | little-endian | `struct.unpack('<...')` |
| DAQ config | DYNAMIC | Master tự cấp phát qua `FREE_DAQ → ALLOC_*` |
| DAQ identification | ABSOLUTE (PID 1 byte) | `PID = firstPid(list) + odt_index` |
| Timestamp | DWORD, 10 ns/tick | 4 byte, **chỉ có trong ODT đầu tiên** của mỗi list |
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
| `GET_DAQ_EVENT_INFO` | ❌ tắt | **A2L là nguồn sự thật bắt buộc** cho tên event — không thể hỏi ECU lúc runtime |

---

## 2. Kiến trúc — 5 lớp

Nguyên tắc: **protocol core không biết gì về GUI, và cũng không biết gì về CAN.**

```
ui/  cli/     Calibration panel, Measurement scope, dock widget debug
              CHỈ gọi session/ qua giao diện trong session/api.py.
              Không import master/, transport/ hay a2l/ — test ranh giới ép luật.
    ▲ session/api.py — Session Protocol, dataclass, cây ngoại lệ
session/      Kết dính A2L với slave. Nghiệp vụ, không có byte.
              load_a2l() + symbols: A2LDatabase cho Calibration và DAQ.
    ▲ A2LDatabase lookup
a2l/          Parser + symbol database. MEASUREMENT, CHARACTERISTIC,
              COMPU_METHOD, RECORD_LAYOUT → dict tra theo tên.
              Hoàn toàn độc lập — không import session/, master/, transport/.
    ▲ ─────────────── (ranh giới cứng) ───────────────
master/       Protocol core. CONNECT/UPLOAD/DOWNLOAD, DAQ allocation,
              DTO decoder, timeout T1, retry qua SYNC.
              KHÔNG import GUI, KHÔNG import python-can.
    ▲ send(bytes) / recv(timeout) / close()
transport/    Backend hoán đổi được: pcan, vector, etas, slcan, virtual, replay.
              Lớp duy nhất biết CAN là gì.
```

Ranh giới được cưỡng chế bằng AST (`tests/test_boundaries.py`), không bằng kỷ luật.

### Ba luồng chạy song song

Chỗ dễ sai nhất về kiến trúc — DAQ có thể bắn 100 frame/s trong khi user đang ghi calibration.

- **RX thread** — `bus.recv()`, phân loại frame, đẩy DTO vào ring buffer, đẩy CRM vào `queue.Queue(maxsize=1)`.
- **Command (luồng gọi)** — gửi CRO rồi `get(timeout=T1)`. Đồng bộ, dễ test.
- **UI thread** — gọi `drain_trace()` theo QTimer 40 ms, vẽ lại. Không vẽ theo từng frame.

Ring buffer có trần — quá thì bỏ entry cũ nhất và tăng `dropped_frames`, không để RAM phình.

---

## 3. Quyết định đã chốt

| # | Quyết định | Lý do |
|---|---|---|
| QĐ1 | **Stack: Python + PySide6** | python-can bọc tất cả hãng CAN; pyqtgraph cho scope; PySide6-Fluent-Widgets cho UI Fluent Design |
| QĐ2 | **Protocol core tự viết** (tham khảo pyxcp) | Tập lệnh hẹp, kiểm soát cả hai đầu — debug được tận byte, ~700 dòng |
| QĐ3 | **Đa nền tảng: user chọn lúc setup** | PEAK/Vector/ETAS/slcan đều sau python-can API; thêm hãng = thêm entry, không đụng master/ |
| QĐ4 | **Không biên dịch slave C thành sim** | Công cụ phải độc lập với driver/; fake slave Python trên virtual bus linh hoạt hơn: có thể ép hành vi tồi (timeout, flood, frame méo) |
| QĐ5 | **PySide6-Fluent-Widgets** cho lớp UI | Fluent Design, có `setTheme(DARK)` riêng. ⚠️ License dual GPLv3/thương mại — xác nhận trước M5 nếu tool dùng thương mại |

---

## 4. DAQ engine — thiết kế cho M4

### 4.1 Ngân sách byte không đồng đều

Timestamp 4 byte **chỉ chèn vào ODT đầu tiên** của mỗi DAQ list:

```
ODT 0 (có timestamp):    [PID][TS][TS][TS][TS][data][data][data]  → 3 byte data
ODT 1, 2, … (không TS): [PID][data×7]                             → 7 byte data
```

### 4.2 🔴 Slave không tự bảo vệ

`Xcp_Handler.c:3064` khi xử lý `WRITE_DAQ` **chỉ kiểm tra kích thước từng entry ≤ 7**, không cộng dồn các entry trong ODT. Nếu master nhồi 7 byte vào ODT 0 khi timestamp bật, slave ghi `1+4+7=12 byte vào buffer 8 byte` — tràn bộ nhớ. Triệu chứng: dữ liệu sai ngẫu nhiên hoặc ECU treo, và sẽ đi tìm bug ở nhầm chỗ.

**Packing đúng là trách nhiệm tuyệt đối của master. Viết unit test trước khi viết bất cứ dòng GUI nào.**

### 4.3 Thuật toán packing — bản chuẩn

Bản cũ (design gốc) có bug: sorted largest-first → signal lớn nhất không lọt vào ODT 0 (budget 3 byte) → `cur=[]` bị push → **ODT 0 rỗng**, lãng phí có hệ thống. Bản dưới tách riêng hai nhóm:

```python
def pack_odts(signals, timestamp_on, max_dto=8):
    first_budget = max_dto - 1 - (4 if timestamp_on else 0)   # 3 với TS bật, 7 không TS
    rest_budget  = max_dto - 1                                  # 7

    for s in signals:
        if s.size > rest_budget:
            raise ValueError(f"{s.name}: {s.size}B > max {rest_budget}B, phải tách nhỏ")

    # Tách: signal vừa ODT 0 (≤ first_budget) vs signal chỉ vừa ODT 1+
    small = sorted([s for s in signals if s.size <= first_budget], key=lambda x: -x.size)
    large = sorted([s for s in signals if s.size > first_budget], key=lambda x: -x.size)

    odts: list[list] = []

    # ODT 0: nhét small signals, first-fit-decreasing trong first_budget
    odt0, used, in_odt0 = [], 0, set()
    for s in small:
        if used + s.size <= first_budget:
            odt0.append(s); used += s.size; in_odt0.add(id(s))
    odts.append(odt0)  # ODT 0 có thể rỗng nếu không có signal nào ≤ 3B — đây là OK

    # ODT 1+: large rồi small chưa vào ODT 0, first-fit-decreasing
    remaining = large + [s for s in small if id(s) not in in_odt0]
    cur, used = [], 0
    for s in remaining:
        if used + s.size > rest_budget:
            odts.append(cur)
            cur, used = [], 0
        cur.append(s); used += s.size
    if cur:
        odts.append(cur)

    return odts
```

Unit test **bắt buộc** trước khi viết code DAQ:
- Signal 4B + timestamp bật → ODT 0 rỗng (không có gì ≤ 3B), 4B ở ODT 1 — KHÔNG báo lỗi
- Hai signal 1B + 2B + timestamp bật → ODT 0 = [2B, 1B], tổng = 3B ≤ budget
- Signal 8B → `ValueError` ("phải tách nhỏ")
- timestamp tắt → first_budget = rest_budget = 7, thuật toán cho kết quả giống nhau

### 4.4 Trình tự cấu hình DAQ — sai thứ tự là nhận `CRC_SEQUENCE`

Slave kiểm tra rất chặt (`XcpAllocDaq` từ chối nếu `OdtCount != 0`):

```
FREE_DAQ                              # xoá sạch, bắt buộc đầu tiên
ALLOC_DAQ(n_lists)
for daq in lists:  ALLOC_ODT(daq, n_odts)
for daq, odt:      ALLOC_ODT_ENTRY(daq, odt, n_entries)

for daq, odt:
    SET_DAQ_PTR(daq, odt, 0)
    for e in entries:  WRITE_DAQ(bit_offset=0xFF, size, ext=0, addr)

for daq:
    SET_DAQ_LIST_MODE(mode=0x10, daq, event, prescaler=1, prio=0)  # 0x10 = bật timestamp
    first_pid[daq] = START_STOP_DAQ_LIST(mode=2, daq)              # 2 = select, trả firstPid

START_STOP_SYNCH(mode=1)   # khởi động đồng loạt
```

`first_pid` từ bước select là chìa khoá giải mã. Master dựng bảng phẳng `pid → (daq_list, odt_index, signals, frame_offset)`; vòng lặp RX chỉ còn tra bảng.

### 4.5 Các điểm kỹ thuật cần nhớ

| Điểm | Chi tiết |
|---|---|
| Demux CRM vs DTO | Byte 0 ∈ `{0xFF, 0xFE, 0xFD, 0xFC}` → CTO. Còn lại → DAQ. |
| Overrun bit | Bit 7 của PID. Mask `PID & 0x7F` trước khi tra bảng — KeyError nếu quên. |
| Timestamp rollover | 32-bit @ 10 ns → quay vòng sau 42,9 giây. Master phải cộng dồn số lần tràn. |
| `FREE_DAQ` bắt buộc | Phiên trước thoát bất thường → cấu hình DAQ cũ còn trong ECU. Luôn FREE_DAQ sau CONNECT. |
| `GET_DAQ_EVENT_INFO` tắt | Tên event phải lấy từ A2L `IF_DATA XCP EVENT`, không thể hỏi ECU runtime. |

---

## 5. Calibration — mô hình hai trang

### Mô hình XCP spec vs. UI xcptool

XCP spec cho phép ECU page và XCP page độc lập nhau. Trong workflow hiệu chỉnh thực tế, chúng luôn đi cùng nhau. xcptool không lộ sự phân biệt này ra UI:

```
Spec (bên dưới)         UI (người dùng thấy)
───────────────          ───────────────────────────────────
ECU_ACCESS bit  ┐        Trang hiện tại: [Working (RAM)]
XCP_ACCESS bit  ┘   →               hoặc [Reference (ROM)]
                         [→ Working]  [→ Reference]  [Copy Ref→Working]
```

`master/core.py` vẫn có `set_page(segment, page, mode: PageMode)` để set độc lập khi cần (sequence trung gian). Không lộ ra UI — `cal_set_page()` trong MainWindow luôn set cả ECU lẫn XCP cùng lúc.

### Ghi tham số

- Luôn `SET_MTA` + `DOWNLOAD`. `SHORT_DOWNLOAD` không dùng được vì MAX_CTO=8 trên CAN → capacity = MAX_CTO − 8 = 0.
- Địa chỉ từ A2L (vùng ROM); slave tự remap sang RAM qua `Xcp_GetPointer()`.
- Struct/array phải ghi trọn một lần, không ghi từng field rời — ECU đi qua trạng thái nửa cũ nửa mới, vòng điều khiển giật.

### Trường hợp trang không đồng bộ

Nếu `GET_CAL_PAGE` trả về ECU ≠ XCP (tool ngoài set, sequence bị gián đoạn giữa chừng): hiện cảnh báo `"⚠ Trang không đồng bộ (ECU: x, XCP: y)"` + nút **[Đồng bộ lại]** — set cả hai về trang XCP (master là người kiểm soát).

---

## 6. Bố cục giao diện

```
┌──────────────────────────────────────────────────────┐
│  Navigation  │  Panel chính                           │
│  sidebar     │                                        │
│              │  [Hiệu chỉnh] ← Calibration panel     │
│  Hiệu chỉnh │        hoặc                            │
│  Đo lường   │  [Đo lường]  ← M4, scope pyqtgraph    │
│  (M4)        │                                        │
│              ├────────────────────────────────────────│
│              │  [Trace CAN][Lệnh thô][Memory/Debug]   │
│              │  ↑ QDockWidget tabified bottom          │
└──────────────────────────────────────────────────────┘
```

| Widget | Loại | Mặc định | Milestone |
|---|---|---|---|
| Calibration panel | `QStackedWidget` (main area) | Hiển thị sau khi nạp A2L | M3 ✅ |
| Measurement scope | `QStackedWidget` (main area) | — | M4 |
| Trace CAN | `QDockWidget` (bottom) | Hiển thị, không đóng được | M3 ✅ |
| Lệnh thô | `QDockWidget` (bottom) | Tab cùng Trace CAN | M3 ✅ |
| Memory/Debug | `QDockWidget` (bottom) | Ẩn, mở từ `Ctrl+3` | M3 ✅ |

Layout serialize qua `QSettings("xcptool", "xcptool")` → nhớ giữa phiên.

### Calibration panel — thiết kế chi tiết

```
┌─ Hiệu chỉnh ─────────────────────────────────────────────┐
│  [Nạp A2L…]  [Đọc tất cả]  [Ghi thay đổi]   31 CHAR    │
├──────────────────────────────────────────────────────────│
│  Tên              Loại   Địa chỉ      Byte  Giá trị   … │
│  systemGain       VALUE  0x80100000      4  1.000        │
│  throttleOffset   VALUE  0x80100004      4  0.050        │
│  Kp               VALUE  0x80100008      4  0.500  (cam) │
│  …                                                       │
├──────────────────────────────────────────────────────────│
│  Segment: [0▲▼]  [Working (RAM)][Reference (ROM)]        │
│  [Đọc trạng thái trang]    [Copy Ref→Working]            │
└──────────────────────────────────────────────────────────┘
```

- Double-click cột Giá trị → edit inline, Enter xác nhận, Esc huỷ.
- Hàng đã sửa chưa ghi xuống ECU: tô màu cam (dirty indicator).
- `WriteProtectedError` → hỏi "Chuyển sang Working và ghi lại?" — không in mã lỗi thô.

---

## 7. Danh sách bẫy

| Bẫy | Cách tránh | Trạng thái |
|---|---|---|
| Demux nhầm DTO thành CRM | Byte 0 ∈ `{0xFF–0xFC}` → CTO, còn lại → DAQ | ✅ `master/core.py` |
| Quên mask bit 7 của PID | `PID & 0x7F` trước khi tra bảng | ⚠️ Nhớ khi viết DTO decoder (M4) |
| Timestamp rollover 42,9 giây | Cộng dồn số lần tràn 32-bit ở tầng decoder | ⚠️ Xử lý trong M4 |
| Không `FREE_DAQ` khi CONNECT | Luôn FREE_DAQ ngay sau CONNECT nếu DAQ bật | ⚠️ Thêm vào M4 |
| ODT 0 rỗng (bug thuật toán cũ) | Xem bản đã sửa §4.3 — tách small/large trước khi pack | ✅ Fix trong §4.3; code + test ở M4 |
| Bỏ qua DISCONNECT khi thoát | `closeEvent()` luôn gọi `session.close()` | ✅ `main_window.py` |
| Frame ngắn hơn 8 byte | Pad CRO đủ 8 byte (`BusConfig.pad_dlc = True`) | ✅ `transport/pycan.py` |
| Vẽ theo từng frame | Gom vào buffer, repaint theo QTimer 40 ms | ✅ `main_window._poll_trace()` |
| Địa chỉ A2L lệch sau rebuild | `tools/sync_a2l_addresses.py` chạy trong build script | ⚠️ Manual — chạy khi firmware rebuild |
| Ghi từng field của struct rời | Ghi trọn khối một lần — ECU không được đi qua state nửa cũ | ✅ `session/api.py` docstring ép luật |
