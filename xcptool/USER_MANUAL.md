# xcptool — Hướng dẫn sử dụng

Công cụ PC thay thế CANape/INCA cho việc kết nối tới ECU qua **XCP-on-CAN**: chọn thiết bị CAN, CONNECT tới ECU, xem mọi frame trên bus theo thời gian thực, gửi lệnh XCP thô, đọc/ghi bộ nhớ theo địa chỉ, và điều khiển trang calibration (working/reference). Không cần biên dịch, không cần phần cứng CAN thật để dùng thử (có bus ảo dựng sẵn).

> Tài liệu này viết cho **người dùng** xcptool (kỹ sư đo lường/hiệu chỉnh, đã quen CANape/XCP). Muốn hiểu code hoạt động thế nào, xem `ARCHITECTURE.md`.

---

## 1. Đang hỗ trợ gì / chưa hỗ trợ gì

xcptool hiện ở giai đoạn **M1 + M2** — nền tảng kết nối và thao tác bộ nhớ. Đọc kỹ mục này trước khi dùng để khỏi kỳ vọng nhầm.

**✅ Đã có, dùng được ngay:**

| Tính năng | Ghi chú |
|---|---|
| Kết nối ECU qua CAN | Đa hãng: PEAK, Vector, ETAS, CANable/slcan, bus ảo để test |
| Dò năng lực ECU lúc CONNECT | MAX_CTO/MAX_DTO, byte order, resource CAL/PAG/DAQ/STIM/PGM — không hardcode theo một ECU cụ thể |
| Cửa sổ debug CAN (trace) | Mọi frame đi qua bus, kể cả frame không thuộc phiên xcptool |
| Console lệnh XCP thô | Gõ tay CTO dạng hex, xem byte thô ECU trả về |
| Đọc/ghi bộ nhớ theo địa chỉ | Hex dump sửa trực tiếp, ghi trọn khối |
| Điều khiển trang calibration | Xem/đổi trang ECU (đang chạy) và trang XCP (đang nhìn), copy trang |

**❌ Chưa có — đừng tìm, chưa được viết:**

| Tính năng | Dự kiến |
|---|---|
| Đo tín hiệu theo thời gian (DAQ), đồ thị scope | M4 |
| Đọc A2L, làm việc theo **tên** tín hiệu thay vì địa chỉ thô | M3 |
| Ghi log ra MDF4 | M5 |
| Nạp chương trình vào flash (PGM/Block Upload/Download) | chưa có kế hoạch |
| STIM (bơm dữ liệu vào ECU) | chưa có kế hoạch |
| **Seed & Key** | Chưa hỗ trợ bypass. ECU đòi seed & key sẽ được CONNECT nhưng bị chặn ở đúng resource cần khoá — xcptool báo rõ, không có đường vòng |

---

## 2. Cài đặt

Yêu cầu Python ≥ 3.11.

```
cd xcptool
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
```

`pip install -e ".[dev]"` cài `python-can`, `PySide6`, `PySide6-Fluent-Widgets` (giao diện), và bộ công cụ test. Dùng **đúng interpreter trong venv** (`.venv\Scripts\python.exe`), không dùng `python` hệ thống.

### Driver hãng CAN — cài riêng theo thiết bị bạn có

xcptool không tự cài được driver hãng (đây là phần mềm của nhà sản xuất, không phải gói Python). Không có driver, backend đó vẫn hiện trong danh sách thiết bị nhưng đánh dấu "chưa dùng được" kèm gợi ý cần cài gì:

| Hãng | Cần cài | Nền tảng |
|---|---|---|
| PEAK PCAN-USB | Driver **PCAN-Basic** (PCANBasic.dll / libpcanbasic.so) | Windows / Linux |
| Vector VN16xx | **Vector XL Driver Library** (cài kèm Vector Driver Setup) | chỉ Windows |
| ETAS ES58x/ES5xx | **ETAS Distribution Package (BOA)** | chỉ Windows |
| CANable / slcan | Gói Python `pyserial` (`pip install xcptool[slcan]`) + driver COM ảo | Windows / Linux |
| Bus ảo (test) | Không cần gì | mọi nơi |

---

## 3. Khởi động nhanh

Hai cách chạy: dòng lệnh (`xcptool ...`) hoặc giao diện đồ hoạ.

```bash
# Thử ngay không cần phần cứng — dùng bus giả lập
.venv\Scripts\python.exe -m xcptool.cli.main --session fake devices
.venv\Scripts\python.exe -m xcptool.ui.app --session fake

# Có bus CAN thật rồi thì bỏ --session fake (mặc định là "real")
.venv\Scripts\python.exe -m xcptool.cli.main devices
.venv\Scripts\python.exe -m xcptool.ui.app
```

`--session fake` dùng một ECU giả lập hoàn toàn trong Python, không đụng `python-can`, không cần bus thật — tiện để làm quen giao diện trước khi có phần cứng.

---

## 4. Kết nối ECU

Trong GUI: menu **Phiên → Kết nối…** (`Ctrl+K`) hoặc nút **Kết nối…** ở cuối thanh điều hướng trái.

**Dialog chọn thiết bị:**
- Danh sách liệt kê MỌI backend đã biết, kể cả cái chưa dùng được (hiện màu xám, kèm dòng gợi ý cần cài gì — xem mục 2). Đừng bỏ qua dòng gợi ý này, đây là nguyên nhân phổ biến nhất khi "không thấy thiết bị nào".
- Nút **Dò lại thiết bị** — quét lại (có thể mất vài giây, có spinner).
- Lựa chọn lần kết nối thành công gần nhất được **tự nhớ** và chọn sẵn ở lần mở dialog kế tiếp.
- Tham số bus (bitrate, CAN ID của CRO/DTO, ID 29-bit hay không, đệm đủ 8 byte, timeout T1) điều chỉnh được ngay trong dialog — giá trị mặc định lấy từ CAN ID chuẩn 0x7E0/0x7E1, 500 kbps, nhưng **ECU khác có thể dùng ID khác**, sửa lại cho khớp thiết bị của bạn.
- CRO và DTO thường dùng chung một CAN ID cho cả response lẫn dữ liệu DAQ — xcptool tự phân loại theo byte đầu, không cần bạn khai riêng.

Bấm **Kết nối** → có thể mất vài giây (spinner hiện, có nút **Huỷ** nếu đợi quá lâu — huỷ nghĩa là đóng hẳn bus, không phải tạm dừng). Kết nối thành công, thanh trạng thái dưới cùng hiện tóm tắt năng lực ECU: MAX_CTO/MAX_DTO, byte order, version XCP, resource nào ECU hỗ trợ (CAL/DAQ/STIM/PGM), có đòi seed & key không.

Ngắt kết nối: menu **Phiên → Ngắt kết nối** (giữ bus mở) hoặc đóng cửa sổ (đóng hẳn bus).

---

## 5. Cửa sổ debug CAN (Trace)

Tab **Trace CAN** — bảng liệt kê mọi frame đi qua bus theo thời gian thực, kể cả frame không thuộc phiên xcptool.

| Cột | Ý nghĩa |
|---|---|
| # | Số thứ tự, tăng dần trong phiên |
| t (s) | Thời điểm tương đối so với frame đầu tiên |
| Hướng | → gửi đi, ← nhận về |
| CAN ID | Hệ hex |
| DLC | Số byte |
| Dữ liệu | Toàn bộ byte, hex |
| Giải mã | Diễn giải người đọc được (`CONNECT mode=0`, `ERR CRC_WRITE_PROTECTED`...), không giải mã được thì hiện hex thô |

Công cụ trên thanh phía trên bảng:
- **Tạm dừng / Tiếp tục** — dừng vẽ (frame vẫn được đếm ở "bỏ khi tạm dừng", không dùng để phân tích được vì không lưu lại).
- **Tự cuộn** — tự trôi xuống dòng mới nhất.
- **Xoá** — xoá sạch bảng.
- **Xuất CSV…** — xuất các dòng đang hiển thị (theo bộ lọc hiện tại) ra file.
- **Lọc theo loại frame** — tick/bỏ tick từng loại: CMD (lệnh gửi), RES (phản hồi OK), ERR (phản hồi lỗi), EV (event), SERV (service request), DAQ, khác (frame không thuộc phiên).
- **Trần dòng** — số dòng tối đa giữ trong bộ nhớ (mặc định 20.000), vượt trần thì tự bỏ dòng cũ nhất — RAM không phình dù bus chạy hàng giờ.

Bộ đếm góc phải: nhận / đang giữ / hiện / **session bỏ** (frame bị ring buffer phía backend bỏ vì UI rút không kịp — nếu số này tăng liên tục nghĩa là bus quá tải so với tốc độ vẽ, không phải lỗi kết nối) / bỏ khi tạm dừng.

> **Lưu ý về timestamp:** PEAK/Vector lấy timestamp từ phần cứng, còn slcan và bus giả lập sinh bằng phần mềm nên có jitter — đừng dùng slcan để đo độ trễ chính xác của ECU.

---

## 6. Console lệnh thô

Tab **Lệnh thô** — dành cho khi bạn muốn tự tay gửi một CTO không qua panel nào khác (debug protocol, thử lệnh ECU chưa được xcptool hỗ trợ sẵn).

- Gõ hex vào ô nhập, ví dụ `FF 00` (CONNECT mode 0), Enter hoặc bấm **Gửi**. Chấp nhận cả dạng `ff00`, `FF,00`, `0xFF 0x00`.
- Có sẵn nút bấm nhanh: CONNECT, GET_STATUS, SYNCH, GET_ID, DISCONNECT.
- Phím ↑/↓ trong ô nhập để lướt lại lịch sử lệnh đã gửi (tối đa 50 lệnh gần nhất).
- Đọc response: byte đầu tiên `0xFF` = OK, `0xFE` = ECU báo lỗi (frame lỗi vẫn được **in ra**, không tự động thành hộp thoại — bạn tự đọc byte). Tick **"Coi response lỗi là ngoại lệ"** nếu muốn lỗi ECU hiện thành hộp thoại như các thao tác khác.
- Mọi lệnh gửi qua đây cũng xuất hiện đồng thời trong tab Trace CAN.

---

## 7. Panel bộ nhớ

Tab **Bộ nhớ** — đọc/ghi ECU theo địa chỉ tuyệt đối, và điều khiển trang calibration.

**Đọc/ghi:**
1. Nhập địa chỉ (hex, có hoặc không tiền tố `0x`), số byte cần đọc, `ext` (address extension — hầu hết ECU dùng `0`).
2. Bấm **Đọc** → hiện hex dump, mỗi ô là 1 byte, nhấp đúp để sửa trực tiếp (ô sửa đổi màu cam để phân biệt).
3. Bấm **Ghi vùng này** → ghi *toàn bộ khối* xuống ECU trong một lượt (không ghi rời từng byte — tránh ECU chạy qua trạng thái nửa cũ nửa mới, đặc biệt quan trọng với struct/mảng như bộ hệ số PID).
4. **Bỏ sửa** — hoàn tác về giá trị vừa đọc, chưa ghi gì.
5. Tick **"Đọc lại sau khi ghi để đối chiếu"** (mặc định bật) — tự đọc lại ngay sau khi ghi để xác nhận giá trị đã lên ECU đúng như ý.

**Trang calibration (working/reference):** ECU phân biệt *trang nó đang chạy* (trang ECU) và *trang XCP đang nhìn vào* (trang XCP) — hai khái niệm độc lập nhau. Địa chỉ bạn nhập luôn hiểu theo vùng ROM (reference); khi XCP trỏ working page, ECU tự đổi hướng sang RAM tương ứng.

- **Segment / Đọc lại trạng thái trang** — xem trang ECU và trang XCP hiện tại.
- **Đặt trang** — đổi trang cho một trong hai mode (XCP hoặc ECU).
- **Copy trang** — copy nội dung từ trang nguồn sang trang đích trong cùng segment.

**Khi ghi bị từ chối** (thường gặp nhất): hộp thoại "Không ghi được — vùng nhớ đang được bảo vệ" hiện ra kèm nút **"Chuyển sang trang 0 và ghi lại"**. Nguyên nhân gần như luôn là XCP đang trỏ reference page (ROM, chỉ đọc) thay vì working page (RAM) — bấm nút đó, xcptool tự đổi trang rồi ghi lại đúng dữ liệu bạn vừa sửa, không cần làm lại từ đầu.

> Quy ước "trang 0 = working" là của slave tham chiếu trong dự án này (XcpBasic), **không phải chuẩn chung của XCP** — ECU khác có thể đánh số trang khác.

---

## 8. Tham chiếu dòng lệnh (CLI)

```
xcptool [--session fake|real] [--backend TÊN] [--channel KÊNH]
        [--bitrate SỐ] [--cro 0xHEX] [--dto 0xHEX] [--timeout GIÂY]
        <lệnh con> [tham số]
```

Không truyền `--backend`/`--channel` thì xcptool tự lấy kênh khả dụng đầu tiên dò được.

| Lệnh con | Tham số | Ý nghĩa | Ví dụ |
|---|---|---|---|
| `devices` | — | Liệt kê kênh CAN dò được, kèm hint nếu thiếu driver | `xcptool devices` |
| `connect` | — | CONNECT rồi in năng lực ECU | `xcptool --session fake connect` |
| `read` | `<địa_chỉ_hex> <số_byte>` | Đọc bộ nhớ, in hex dump | `xcptool read 80000000 64` |
| `write` | `<địa_chỉ_hex> <chuỗi_hex>` | Ghi bộ nhớ rồi đọc lại để xác nhận | `xcptool write 80000000 "DE AD BE EF"` |
| `pages` | `[--segment N]` | In trang ECU và trang XCP hiện tại | `xcptool pages --segment 0` |
| `set-page` | `<trang> [--segment N] [--mode ecu\|xcp]` | Đổi trang calibration | `xcptool set-page 0 --mode xcp` |
| `raw` | `<chuỗi_hex>` | Gửi CTO thô, in response | `xcptool raw "FF 00"` |
| `trace` | `[--seconds N]` | Nghe bus N giây rồi in mọi frame và thoát | `xcptool trace --seconds 10` |

Mọi lệnh con (trừ `devices`) tự CONNECT trước khi chạy và in trace của phiên khi kết thúc.

---

## 9. File cấu hình & log

| File | Nội dung |
|---|---|
| `~/.xcptool/config.toml` | Tự lưu lại `BusConfig` (backend, channel, bitrate, CAN ID, timeout...) sau lần CONNECT thành công qua `--session real`. Sửa tay được — file text thường, có comment. |
| `~/.xcptool/logs/xcptool-YYYYMMDD-HHMMSS.log` | Log đầy đủ của từng phiên GUI — xem đường dẫn qua menu **Trợ giúp → Đường dẫn file log**. Rất hữu ích khi báo lỗi cho người phát triển. |
| `~/.xcptool/logs/faulthandler.log` | Bắt cả những lỗi Python không kịp dựng traceback (ví dụ crash trong tầng Qt) — vết tích cuối cùng nếu app biến mất đột ngột. |

(Đường dẫn `~/.xcptool` đổi được qua biến môi trường `XCPTOOL_HOME`, chủ yếu dùng khi test.)

---

## 10. Xử lý sự cố thường gặp

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| Thiết bị hiện màu xám, "chưa dùng được" | Chưa cài driver hãng | Đọc dòng gợi ý ngay dưới tên thiết bị — nó nói chính xác cần cài gì (xem bảng mục 2), cài xong bấm Dò lại |
| "Không tìm thấy thiết bị" khi CONNECT | Thiết bị bị rút / đổi cổng USB giữa chừng | Kiểm tra dây, cổng USB, dò lại danh sách |
| Lỗi bus CAN | Bus-off, sai bitrate, thiếu điện trở đầu cuối | Kiểm tra bitrate khớp ECU, điện trở đầu cuối 120Ω, ECU có đang cấp nguồn không |
| "ECU không trả lời" (timeout) | Sai CAN ID của CRO/DTO, hoặc ECU không chạy | Đây là hai thứ hay đặt sai nhất — đối chiếu lại CRO/DTO với tài liệu ECU |
| "Response không hợp lệ" | ECU trả frame ngắn/sai định dạng | Xem tab Trace CAN, đối chiếu byte thô ECU thực sự gửi về |
| Ghi bộ nhớ bị từ chối, "vùng nhớ đang được bảo vệ" | XCP đang trỏ reference page (ROM, chỉ đọc) | Bấm nút "Chuyển sang trang 0 và ghi lại" trong hộp thoại hiện ra |
| "Bus đang bận" | Đã có một lệnh XCP khác đang chờ phản hồi | Mỗi lúc chỉ chạy được một lệnh — chờ lệnh hiện tại xong |
| "ECU không hỗ trợ" | Bạn yêu cầu tính năng ECU không khai hỗ trợ lúc CONNECT (vd. đổi trang trên ECU không có CAL/PAG) | Không có cách bypass — đúng theo năng lực ECU đã khai báo |
| ECU đòi seed & key | xcptool chưa hỗ trợ unlock | Không có đường vòng ở bản này — cần chờ tính năng Seed & Key được thêm |
| Số "session bỏ" trong tab Trace tăng liên tục | Bus bắn frame nhanh hơn tốc độ UI rút được | Không phải lỗi kết nối — tăng "Trần dòng" hoặc lọc bớt loại frame không cần xem |
| App đóng đột ngột / lỗi ngoài dự kiến | Bug của công cụ | Xem `~/.xcptool/logs/` — app đã ghi traceback đầy đủ trước khi hộp thoại xin lỗi hiện ra |

Mọi lỗi lường trước được đều hiện thành hộp thoại có nội dung đọc được kèm gợi ý xử lý — không bao giờ là traceback thô. Nếu bạn thấy traceback trong hộp thoại, đó là bug, báo lại kèm file log.

---

## 11. Giới hạn & lộ trình sắp tới

Nhắc lại mục 1: xcptool ở bản này **chưa** đo tín hiệu theo thời gian (DAQ/scope), **chưa** đọc A2L để làm việc theo tên tín hiệu, **chưa** ghi MDF4, **chưa** nạp flash, **chưa** hỗ trợ ECU đòi Seed & Key.

Các mốc tiếp theo (xem `DEV_PLAN.md` nếu muốn biết chi tiết kỹ thuật):
- **M3** — đọc file A2L, cho phép làm việc theo tên tín hiệu (`engineRpm` thay vì địa chỉ hex) và bảng calibration theo tên.
- **M4** — DAQ engine thật + scope thời gian thực (đồ thị `pyqtgraph`).
- **M5** — xuất log ra MDF4, xuất/nhập bộ tham số, hỗ trợ XCP-on-Ethernet, đóng gói thành file `.exe` độc lập.
