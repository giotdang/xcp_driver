# xcptool — Hướng dẫn sử dụng

Công cụ PC thay thế CANape/INCA cho việc kết nối tới ECU qua **XCP-on-CAN**: đo lường tín hiệu thời gian thực (DAQ), đồ thị scope, hiệu chỉnh tham số theo file A2L, quản lý trang nhớ calibration (Working/Reference), đọc/ghi bộ nhớ theo địa chỉ, xem trace CAN và gửi lệnh XCP thô.

> Tài liệu này viết cho **người dùng** xcptool (kỹ sư đo lường/hiệu chỉnh ECU). Muốn tìm hiểu sâu về kiến trúc mã nguồn, xem `ARCHITECTURE.md`.

---

## 1. Tính năng đang hỗ trợ

xcptool hiện đã hoàn thiện các mốc phát triển **M1 → M6** với đầy đủ các tính năng:

| Tính năng | Mô tả chi tiết |
|---|---|
| **Kết nối ECU qua CAN** | Hỗ trợ đa thiết bị: PEAK, Vector, ETAS, CANable/slcan, và bus ảo (`virtual`) để chạy thử nghiệm không cần phần cứng. |
| **Dò năng lực tự động** | Đọc `MAX_CTO`, `MAX_DTO`, byte order (Endianness), các tài nguyên `CAL/PAG`, `DAQ`, `STIM`, `PGM` từ ECU lúc CONNECT. |
| **Nạp file mô tả A2L** | Tự động phân tích file A2L (ASAM MCD-2 MC), nạp toàn bộ danh mục CHARACTERISTIC, MEASUREMENT, kiểu dữ liệu và RECORD_LAYOUT. |
| **Panel Hiệu chỉnh (Calibration)** | Xem và chỉnh sửa tham số theo tên, hỗ trợ phân cấp Struct và mảng Array `[0..N-1]`, sửa trực tiếp inline (double-click), đánh dấu màu cam (dirty), chống ghi đè trang ROM. |
| **Quản lý trang Calibration** | Điều khiển chuyển đổi trang Working (RAM) và Reference (ROM), hỗ trợ tính năng 1-click Copy Reference $\rightarrow$ Working. |
| **Panel Đo lường (Measurement & Scope)** | Chọn tín hiệu đo từ A2L, cấu hình DAQ list trên ECU, hiển thị giá trị số thực thời gian thực (Live Value), vẽ đồ thị Scope đa tín hiệu thời gian thực mượt mà (tăng tốc GPU PyOpenGL). |
| **Switch tối ưu Scope** | Nút gạt bật/tắt đồ thị: Tắt scope giúp giải phóng 100% tải GPU/CPU khi chỉ cần xem bảng giá trị. |
| **Cửa sổ CAN Trace** | Bảng ghi nhận toàn bộ frame CAN thời gian thực, bộ lọc thông minh (mặc định ẩn DTO để tránh nghẽn UI), tự động cuộn khi đang nhìn thấy, xuất file CSV. |
| **Console lệnh thô** | Gõ trực tiếp byte CTO dạng Hex, có các nút lệnh nhanh XCP chuẩn, lướt lịch sử lệnh (phím mũi tên). |
| **Panel Bộ nhớ Hex** | Đọc/ghi bộ nhớ theo địa chỉ tuyệt đối, hex dump trực quan, ghi trọn khối an toàn. |
| **Chế độ Demo (`--session fake`)** | Tích hợp ECU giả lập (`FakeSlave`) và mô hình xe + thuật toán PID (`PidPlant`) mô phỏng các giá trị đo thực tế tính từ các biến hiệu chỉnh. |

---

## 2. Cài đặt môi trường

Yêu cầu Python $\ge$ 3.11 (khuyến nghị Python 3.12).

```bash
cd xcptool
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
```

> **Mẹo tăng tốc đồ thị Scope:**
> Cài đặt thêm PyOpenGL để bật tính năng render đồ thị bằng phần cứng (GPU):
> ```bash
> .venv\Scripts\pip install PyOpenGL
> ```

### Cài đặt Driver thiết bị phần cứng CAN

| Hãng thiết bị | Gói driver cần cài đặt | Hệ điều hành |
|---|---|---|
| **PEAK PCAN-USB** | Driver **PCAN-Basic** (`PCANBasic.dll` / `libpcanbasic.so`) | Windows / Linux |
| **Vector VN16xx** | **Vector XL Driver Library** (kèm Vector Driver Setup) | Windows |
| **ETAS ES58x/ES5xx** | **ETAS Distribution Package (BOA)** | Windows |
| **CANable / slcan** | Gói Python `pyserial` (`pip install xcptool[slcan]`) + cổng COM ảo | Windows / Linux |
| **Bus ảo (Virtual)** | Có sẵn trong `python-can`, không cần cài thêm driver | Mọi nền tảng |

---

## 3. Khởi động nhanh

### 3.1 Dùng thử không cần phần cứng (Chế độ Demo)
Chạy ứng dụng với cờ `--session fake`. Hệ thống sẽ tự động khởi động một ECU giả lập kèm mô hình động lực học xe PID:

```bash
# Giao diện đồ họa (GUI)
.venv\Scripts\python.exe -m xcptool.ui.app --session fake

# Hoặc dùng script tiện ích
.\run.bat
```

### 3.2 Kết nối với phần cứng CAN thật
Khi đã cắm thiết bị CAN và nối dây tới ECU:

```bash
.venv\Scripts\python.exe -m xcptool.ui.app
```

---

## 4. Kết nối ECU & Nạp file A2L

### Bước 1: Kết nối thiết bị CAN
1. Bấm nút **Kết nối…** ở góc dưới thanh điều hướng (hoặc menu `Phiên → Kết nối…`, phím tắt `Ctrl+K`).
2. Chọn thiết bị phần cứng trong danh sách (PEAK, Vector, Virtual...).
3. Kiểm tra Bitrate (mặc định 500 kbps) và CAN ID của CRO/DTO (mặc định `0x7E0` / `0x7E1`).
4. Bấm **Kết nối**. Thanh trạng thái dưới cùng sẽ hiển thị thông tin ECU: `MAX_CTO`, `MAX_DTO`, Endianness và các tính năng hỗ trợ (`CAL`, `DAQ`...).

### Bước 2: Nạp file A2L
1. Bấm **Nạp A2L…** trên thanh công cụ của tab Hiệu chỉnh hoặc Đo lường (phím tắt `Ctrl+O`).
2. Chọn file `.a2l` (ví dụ: `examples/xcp_daq_example.a2l`).
3. Ứng dụng sẽ nạp toàn bộ danh mục tham số và tín hiệu vào cả hai tab.

---

## 5. Panel Hiệu chỉnh (Calibration)

Tab **Hiệu chỉnh** (biểu tượng cây bút trên thanh điều hướng bên trái):

```
┌─────────────────────────────────────────────────────────────────────────┐
│ [Nạp A2L…]  [Đọc tất cả]  [Ghi thay đổi]       15 CHARACTERISTIC        │
├─────────────────────────────────────────────────────────────────────────┤
│ Tên               Loại        Địa chỉ     Byte   Giá trị       Khoảng    │
│ ▼ speedPid        STRUCT (4)  0x80100000  16     —                       │
│     kp            FLOAT32     0x80100000  4      1.25          [0 … 100] │
│     ki            FLOAT32     0x80100004  4      0.08          [0 … 50]  │
│     outMin        FLOAT32     0x80100008  4      -50.0         [-100 … 0]│
│     outMax        FLOAT32     0x8010000C  4      50.0          [0 … 100] │
│ ▶ adcCalPoints    UINT16[4]   0x80100038  8      —                       │
└─────────────────────────────────────────────────────────────────────────┘
```

### Thao tác chính:
1. **Đọc giá trị từ ECU**: Bấm **Đọc tất cả** để lấy giá trị hiện tại của toàn bộ tham số trong bộ nhớ ECU.
2. **Chỉnh sửa giá trị (Inline Edit)**:
   - Nhấp đúp chuột (Double-click) vào ô ở cột **Giá trị**.
   - Nhập giá trị mới (số thực hoặc số nguyên) rồi nhấn `Enter`.
   - Dòng vừa sửa và dòng cha sẽ chuyển sang **màu cam nổi bật** (Dirty indicator) để dễ nhận biết các giá trị chưa ghi.
3. **Ghi thay đổi xuống ECU**:
   - Chọn dòng tham số cần ghi.
   - Bấm nút **Ghi thay đổi** (nút chỉ kích hoạt khi dòng được chọn đang có thay đổi).
4. **Hiệu chỉnh mảng (Array)**:
   - Mở rộng mảng (ví dụ `adcCalPoints`), nhấp đúp vào từng phần tử `[0]`, `[1]`... để sửa giá trị riêng lẻ.
   - Khi bấm ghi, ứng dụng tự động đóng gói toàn bộ mảng và gửi xuống ECU.

### Quản lý trang (Working / Reference):
- Thanh điều khiển trang ở dưới cùng hiển thị trạng thái hiện tại:
  - **Working (RAM)**: Cho phép ghi và thay đổi tham số trực tiếp khi ECU đang chạy.
  - **Reference (ROM)**: Vùng nhớ chỉ đọc (Flash/ROM).
- **Tính năng bảo vệ thông minh**: Nếu bạn ghi giá trị khi đang ở trang Reference, ứng dụng sẽ hiện hộp thoại thông báo kèm nút **"Chuyển sang trang Working và ghi lại"** 1-click.
- **Copy Ref $\rightarrow$ Working**: Khôi phục toàn bộ giá trị hiệu chỉnh về mặc định ban đầu của ROM.

---

## 6. Panel Đo lường (Measurement & Scope)

Tab **Đo lường** (biểu tượng công cụ trên thanh điều hướng):

```
┌─────────────────────────────────────────────────────────────────────────┐
│ [Nạp A2L…]  [Bắt đầu đo]  [Dừng]  [🔘 Đồ thị: Bật]    12 MEASUREMENT    │
├───────────────────────────────────┬─────────────────────────────────────┤
│ Signal                Kiểu   Giá trị│ 📈 Scope (pyqtgraph)                │
│ ☑ vehicleSpeedKph     FLOAT32 45.2 │    ── vehicleSpeedKph               │
│ ☑ engineRpm           FLOAT32 2150 │    ── engineRpm                     │
│ ▼ ☑ speedPidTelemetry STRUCT  —    │                                     │
│       error           FLOAT32 1.45 │  80 ┤     /\     /\                 │
│       integral        FLOAT32 0.32 │  40 ┤____/  \___/  \____            │
│ ▶ ☑ torqueSamples     FLOAT32[4] — │   0 ┼───────────────────            │
│                                   │     0s      5s     10s    15s       │
└───────────────────────────────────┴─────────────────────────────────────┘
```

### Thao tác đo lường:
1. **Chọn tín hiệu đo**:
   - Tích chọn vào ô vuông (Checkbox) cạnh các tín hiệu muốn theo dõi.
   - Đối với nhóm Struct hoặc mảng Array: Chỉ cần tích chọn 1 ô ở dòng cha, toàn bộ các tín hiệu con sẽ tự động được đưa vào danh sách đo.
2. **Bắt đầu đo**:
   - Bấm **Bắt đầu đo**. Ứng dụng sẽ tự động cấu hình danh sách DAQ trên ECU và bắt đầu thu thập dữ liệu.
   - Cột **Giá trị** sẽ hiển thị số thực trực tiếp theo thời gian thực (chu kỳ cập nhật 40ms).
   - Đồ thị Scope bên phải sẽ vẽ các đường tín hiệu tương ứng với màu sắc phân biệt.
3. **Tối ưu hiệu năng với Switch "Đồ thị"**:
   - Gạt switch **Đồ thị: Tắt** khi bạn chỉ cần theo dõi các con số trong bảng hoặc đo số lượng lớn tín hiệu cùng lúc. Chế độ này ngắt hoàn toàn việc vẽ đồ thị để đạt tốc độ xử lý tối đa và không tốn CPU/GPU.
4. **Dừng đo**: Bấm nút **Dừng**.

---

## 7. Cửa sổ Trace CAN

Tab **Trace CAN** ở dock phía dưới (phím tắt `Ctrl+1`):

- **Hiển thị toàn bộ frame**: Liệt kê chi tiết mọi frame CAN gửi và nhận (`seq`, thời gian `t`, hướng `→`/`←`, `CAN ID`, `DLC`, `Dữ liệu Hex`, và diễn giải lệnh `Giải mã`).
- **Bộ lọc loại frame**: Lọc theo CMD, RES, ERR, EV, SERV, DAQ.
  > **Lưu ý:** Bộ lọc `DAQ` được **tắt mặc định** để tránh hàng trăm frame DTO mỗi giây làm chậm giao diện. Bạn có thể bật lại bất cứ lúc nào khi cần debug chi tiết cấu trúc frame DTO.
- **Tối ưu tự động cuộn**: Tự động tạm ngưng cuộn bảng khi tab Trace bị ẩn, giúp tiết kiệm tối đa tài nguyên hệ thống.
- **Xuất file**: Bấm **Xuất CSV…** để lưu lại log frame cho việc phân tích.

---

## 8. Panel Bộ nhớ & Console lệnh thô

### 8.1 Hex Memory Panel (phím tắt `Ctrl+3`)
- Nhập địa chỉ bắt đầu và số byte cần đọc $\rightarrow$ bấm **Đọc**.
- Nhấp đúp vào các ô byte hex để chỉnh sửa giá trị trực tiếp.
- Bấm **Ghi vùng này** để ghi toàn bộ khối nhớ xuống ECU.

### 8.2 Console lệnh thô (phím tắt `Ctrl+2`)
- Gõ trực tiếp các byte Hex của lệnh XCP (ví dụ: `FF 00` cho lệnh `CONNECT`).
- Cung cấp các nút lệnh nhanh: `CONNECT`, `GET_STATUS`, `SYNCH`, `GET_ID`, `DISCONNECT`.
- Lưu trữ lịch sử 50 lệnh gần nhất (dùng phím mũi tên $\uparrow/\downarrow$ để chọn lại).

---

## 9. Tham chiếu dòng lệnh (CLI)

```bash
xcptool [--session fake|real] [--backend TÊN] [--channel KÊNH]
        [--bitrate SỐ] [--cro 0xHEX] [--dto 0xHEX] [--timeout GIÂY]
        <lệnh con> [tham số]
```

| Lệnh con | Ví dụ | Ý nghĩa |
|---|---|---|
| `devices` | `xcptool devices` | Liệt kê các kênh CAN khả dụng trên máy tính |
| `connect` | `xcptool connect` | Kết nối thử tới ECU và in bảng năng lực |
| `read` | `xcptool read 80100000 16` | Đọc 16 byte từ địa chỉ `0x80100000` |
| `write` | `xcptool write 80100000 "00 00 80 3F"` | Ghi 4 byte xuống địa chỉ `0x80100000` |
| `pages` | `xcptool pages --segment 0` | Đọc trạng thái trang Working/Reference |
| `set-page`| `xcptool set-page 0 --mode xcp` | Chuyển trang XCP sang trang 0 |
| `raw` | `xcptool raw "FF 00"` | Gửi frame CTO thô |
| `trace` | `xcptool trace --seconds 5` | Bắt và in frame CAN trong 5 giây |

---

## 10. Xử lý sự cố thường gặp

| Hiện tượng | Nguyên nhân | Hướng xử lý |
|---|---|---|
| Thiết bị CAN hiện màu xám | Chưa cài driver nhà sản xuất | Đọc dòng hướng dẫn hiển thị dưới tên thiết bị để tải driver tương ứng. |
| "ECU không trả lời" (Timeout) | Sai Bitrate hoặc sai CAN ID | Kiểm tra lại Bitrate (500k, 250k...) và cặp CAN ID CRO/DTO trong hộp thoại Kết nối. |
| Ghi tham số bị từ chối | Đang ở Reference page (ROM) | Bấm nút chuyển sang Working page trong hộp thoại thông báo để ghi lại. |
| Đồ thị scope giật lag | Đang dùng software rendering | Cài đặt gói `PyOpenGL` (`pip install PyOpenGL`) để kích hoạt tăng tốc GPU. |
| Bị nghẽn frame khi đo DAQ | Bật hiển thị DAQ trong Trace | Tắt checkbox lọc `DAQ` trong tab Trace CAN để giảm tải vẽ bảng. |
