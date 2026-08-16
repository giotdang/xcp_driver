# xcptool — Kiến trúc

> **Đối tượng đọc:** developer hoặc agent sẽ SỬA/MỞ RỘNG code, không phải end-user.
> Muốn dùng công cụ, xem `USER_MANUAL.md`.
>
> **Nguồn sự thật:** tài liệu này mô tả ĐÚNG code hiện có tại thời điểm viết
> (sau khi B0→B4 + F0→F5 + J1 hoàn tất, 2026-08-16). `DESIGN.md`/`DEV_PLAN.md`
> là tài liệu lên kế hoạch từ TRƯỚC khi code — có chỗ đã lỗi thời (đã sửa một
> chỗ biết được: mục "Ghi tham số" trong DESIGN.md §5). Khi hai tài liệu mâu
> thuẫn nhau, tin file này hoặc tin code, không tin DESIGN.md/DEV_PLAN.md.

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

Phạm vi đã xong (M1 + M2 theo `DEV_PLAN.md`): chọn thiết bị CAN đa hãng →
CONNECT → capability discovery → cửa sổ debug CAN (trace) → console lệnh thô
→ đọc/ghi bộ nhớ theo địa chỉ → điều khiển trang calibration. **Chưa làm**:
DAQ engine/scope (M4), A2L parser, MDF4/export (M5) — xem §11.

---

## 2. Kiến trúc 5 lớp

```
┌─────────────────────────────────────────────────────────────────┐
│  ui/          cửa sổ chính, dialog thiết bị, trace/console/mem   │
│  cli/         lệnh `xcptool …` — người tiêu thụ thứ hai của      │
│               cùng contract                                      │
└──────────────────────────┬────────────────────────────────────────┘
                            │  chỉ qua session.api.Session (Protocol)
┌──────────────────────────▼────────────────────────────────────────┐
│  session/     api.py (CONTRACT) · real.py (backend) · fake.py     │
│               (frontend) — hai hiện thực CÙNG chữ ký              │
└───────┬────────────────────────────────────────────────┬──────────┘
        │ RealSession dùng cả hai                          │ FakeSession
┌───────▼──────────────────┐                    ┌──────────▼──────────┐
│  master/   protocol core  │                    │  (không có gì —     │
│  XCP thuần, không biết    │                    │   FakeSession tự    │
│  CAN/GUI là gì            │                    │   mô phỏng trong    │
└───────┬───────────────────┘                    │   bộ nhớ)           │
        │ Link Protocol (send/recv/close)         └──────────────────────┘
┌───────▼───────────────────┐
│  transport/  registry đa   │
│  backend, python-can       │
└────────────────────────────┘
```

**Vì sao tách lớp thế này:**

- `master/` không import `can` — sau này thêm transport XCP-on-Ethernet chỉ
  cần một `Link` mới, protocol core dùng lại nguyên vẹn.
- `ui/`/`cli/` không import `xcptool.master`/`xcptool.transport` — chỉ nói
  chuyện qua `session.api.Session`. Đây là điều kiện để `FakeSession` có ý
  nghĩa: frontend build & test được hoàn toàn không cần `python-can`, không
  cần ECU, không cần backend đã viết xong (đã chứng minh bằng thực tế: cả hai
  agent build song song, frontend không đợi backend tới tận J1).
- `session/api.py` chỉ chứa kiểu dữ liệu/ngoại lệ/chữ ký — không có logic.
  Là hợp đồng giữa hai bên, lead sở hữu.

### Ranh giới ép bằng AST (`tests/test_boundaries.py`)

Ba luật, quét import bằng `ast` (không cần cài PySide6/python-can để chạy được):

| Package | Cấm import |
|---|---|
| `master/` | `can`, `PySide6`, `xcptool.ui`, `xcptool.cli`, `xcptool.transport` |
| `transport/` | `PySide6`, `xcptool.ui`, `xcptool.cli`, `xcptool.master` |
| `ui/` | `can`, `xcptool.master`, `xcptool.transport`, `xcptool.a2l` |
| `cli/` | `can`, `xcptool.master`, `xcptool.transport`, `xcptool.a2l` |
| `session/api.py`, `session/fake.py` | `can`, `PySide6`, `xcptool.master`, `xcptool.transport` |

Cộng thêm `test_no_hardcoded_ecu_constants`: grep toàn bộ `src/` tìm chuỗi
`0x7E0`/`0x7E1`, chỉ cho phép xuất hiện ở `session/api.py` (giá trị mặc định
của dataclass), `transport/config.py` (giá trị mặc định lúc chưa có file
config), `cli/defaults.py` (mặc định tham số dòng lệnh).

**Sửa code khi test này đỏ, đừng sửa test** — file `test_boundaries.py` do
lead sở hữu, đỏ nghĩa là kiến trúc bị vi phạm thật.

---

## 3. Contract — `session/api.py`

File này KHÔNG có logic, chỉ có kiểu dữ liệu, cây ngoại lệ, chữ ký `Protocol`.
Hai hiện thực (`RealSession`, `FakeSession`) implement cùng interface
`Session`. Ai muốn đổi contract phải sửa đúng một chỗ này rồi cả hai bên tự
cập nhật theo.

### 3.1 Luật thread (chỗ app loại này chết nhiều nhất)

- **Session không biết Qt tồn tại.** Không bao giờ gọi ngược lên UI.
- **Nhóm chặn** — mọi phương thức trừ nhóm dưới, có thể mất tới `timeout_s`.
  PHẢI gọi từ worker thread rồi marshal kết quả về UI thread bằng Qt signal.
  Gọi thẳng từ UI thread = coi như lỗi (UI đơ).
- **Nhóm không chặn, an toàn thread** — gọi thẳng từ UI thread được:
  `state`, `caps`, `dropped_frames`, `drain_trace()`, `load_config()`. Gọi
  `drain_trace()` theo `QTimer` 30–50 ms, KHÔNG vẽ theo từng frame.
- **Session không reentrant** — có lệnh đang chờ response mà bị gọi lệnh khác
  chồng lên → `BusyError` ngay lập tức, không xếp hàng, không chờ.
- **`close()` idempotent, KHÔNG BAO GIỜ ném.** Gọi được cả lúc lỗi, cả lúc
  chưa từng connect. Frontend gọi trong `closeEvent()`.

### 3.2 Luật ngoại lệ

Mọi lỗi lường trước được là con của `XcpToolError`. Frontend bắt đúng lớp này
→ hiện thông báo. Ngoại lệ nào khác lọt ra khỏi `Session` là **bug của
backend**, không phải việc frontend xử lý (`RealSession` cưỡng chế luật này
bằng decorator `_guarded()` — xem §4.4).

Cây ngoại lệ:

```
XcpToolError
├── TransportError              (lỗi tầng bus, chưa đụng XCP)
│   ├── DeviceNotFoundError     kênh đã chọn không còn tồn tại
│   ├── DriverMissingError      thiếu driver hãng — có .package_hint
│   └── BusError                bus lỗi lúc đang chạy
├── ProtocolError                (lỗi tầng XCP)
│   ├── XcpTimeoutError          hết T1, ECU không trả lời
│   ├── MalformedResponseError   frame ngắn/sai định dạng — KHÔNG được để
│   │                            struct.error/IndexError lọt ra thay vào đây
│   └── SlaveError               ECU trả 0xFE — có .code/.name/.description
│       ├── WriteProtectedError  CRC_WRITE_PROTECTED — kèm nút "chuyển
│       │                        working page" ở UI (xem §7.4)
│       ├── OutOfRangeError      CRC_OUT_OF_RANGE
│       └── SequenceError        CRC_SEQUENCE
├── NotConnectedError            gọi lệnh khi chưa CONNECT
├── BusyError                    lệnh chồng lên lệnh đang chạy
└── UnsupportedByEcuError        gọi tính năng ECU không có theo SlaveCaps
```

`AccessDeniedError` có trong `__all__` (dùng cho CRC_ACCESS_DENIED/LOCKED) —
hiện tại chưa có đường gọi tới nó trong M1/M2 vì seed & key được xử lý ở
`connect()` (xem §4.3), không phải ở một lệnh riêng.

### 3.3 Luật độc lập ECU

Không trường nào trong `SlaveCaps` được hardcode — tất cả lấy từ response
CONNECT và các `GET_*_INFO`. `SlaveCaps.daq = None` nghĩa là ECU không trả lời
`GET_DAQ_PROCESSOR_INFO`/`GET_DAQ_RESOLUTION_INFO` — bỏ qua êm, không ném lỗi.

### 3.4 Dataclass quan trọng

- **`BusConfig`** — mọi thứ để mở bus + nói chuyện với MỘT ECU. `cro_id`/`dto_id`
  mặc định `0x7E0`/`0x7E1` chỉ là điểm khởi đầu tiện tay, user đổi được.
- **`SlaveCaps`** — ECU tự khai nó là gì (từ CONNECT + GET_STATUS +
  GET_DAQ_*_INFO + GET_ID). `protocol_version`/`transport_version` là
  `(major, 0)` — xem §4.3 vì sao minor luôn là 0.
- **`DaqCaps`** — khai báo sẵn cho M4 (DAQ engine), chưa dùng trong M1/M2.
- **`TraceEntry`** — một dòng trace CAN. `decoded` LUÔN có giá trị (hex nếu
  không giải mã được) — frontend không bao giờ tự giải mã byte.
- **`DeviceInfo`** — kết quả `list_devices()`. Backend chưa cài driver vẫn
  xuất hiện với `available=False` + `hint` — không bao giờ im lặng bỏ qua.

---

## 4. Protocol core — `master/`

`master/core.py` (`XcpMaster`) là nơi hiện thực giao thức XCP thuần, không
biết CAN/GUI. Nó nói chuyện với một `Link` (giao diện `send`/`recv`/`close`,
duck-typed qua `typing.Protocol`, không import gì cụ thể) mà `transport/`
hiện thực.

### 4.1 Luồng RX/TX

- **RX thread riêng** (`_rx_loop`, daemon) — gọi `link.recv(0.05s)` liên tục,
  phân loại frame bằng `codec.classify()`, ghi vào `TraceBuffer`, và nếu là
  response (`res`/`err`) thì đẩy vào `queue.Queue(maxsize=1)` cho lệnh đang
  chờ. RX thread chết vì exception → không làm sập app: bắt `BaseException`,
  chuyển `state = ERROR`, đánh thức lệnh đang chờ bằng `_Sentinel` thay vì để
  nó ngồi hết timeout T1.
- **Gọi lệnh (`transact`)** — khoá bằng `threading.Lock` không chặn
  (`acquire(blocking=False)`) → `BusyError` ngay nếu đã có lệnh khác đang chạy.
  Đây chính là cách contract "không reentrant" được hiện thực.
- **Demux CRM vs DTO** — cùng một CAN ID (`cfg.dto_id`) mang cả response lẫn
  dữ liệu DAQ. Byte 0 ∈ `{0xFF,0xFE,0xFD,0xFC}` (`Pid` enum) → CTO, còn lại →
  `daq` (`codec.classify()`).

### 4.2 Timeout & retry

`_exchange()` gửi lệnh, chờ `timeout` giây; không có response → ghi trace
"(không có trả lời...)" rồi (nếu `retry=True`) gửi `SYNCH` để ECU vứt lệnh dở
dang, thử lại lệnh gốc một lần nữa. Hết hai lần → `XcpTimeoutError`.

**`raw_command()` gọi với `retry=False`** — quyết định thiết kế có chủ đích:
console debug phải cho thấy đúng thứ xảy ra trên dây theo đúng byte user gõ,
tự động thử lại sẽ che mất sự thật mà người debug đang muốn nhìn thấy. Mọi
lệnh khác (`read`/`write`/`connect`/`get_page`...) đều `retry=True`.

### 4.3 CONNECT & capability discovery

`connect()` gửi `CONNECT` rồi hỏi thêm (không giả định gì):

1. **`_parse_connect()`** — đọc `SlaveCaps` từ 8 byte response CONNECT (resource
   byte, comm_mode_basic, MAX_CTO, MAX_DTO, protocol/transport version).
   Validate `MAX_CTO >= 8` và `MAX_DTO >= 8` (bắt buộc trên CAN), ném
   `MalformedResponseError` nếu ECU khai nhỏ hơn.

   **`protocol_version`/`transport_version` luôn là `(byte, 0)`** — response
   CONNECT chỉ mang 1 byte version trên dây, không có chỗ nào cho minor
   version. `0` là placeholder do contract khai `tuple[int, int]`, KHÔNG phải
   giá trị đo được. `GET_COMM_MODE_INFO` (lệnh tuỳ chọn) có trả thêm
   `XCP_DRIVER_VERSION_NUMBER`, nhưng đó là version của driver/hãng làm slave,
   không phải minor version của protocol XCP theo đúng nghĩa — nếu sau này
   cần minor thật thì phải cân nhắc ý nghĩa ngữ nghĩa trước khi map vào.

2. **`_enrich_caps()`** — chạy các câu hỏi phụ, MỌI câu đều qua `_optional()`
   (bọc `_locked_transact` với `raise_on_error=True, retry=False`, nuốt
   `XcpToolError` thành `None`) — ECU không hỗ trợ thì bỏ qua êm, không ném:
   - `GET_STATUS` → `resource_protection` (byte Resource Protection Status).
   - `GET_DAQ_PROCESSOR_INFO` + `GET_DAQ_RESOLUTION_INFO` → `DaqCaps` (chỉ khi
     `caps.supports_daq`).
   - `GET_ID` type 1 (tên file A2L) → `id_string`, đọc bằng `UPLOAD` sau khi
     ECU tự đặt MTA.

3. **Seed & key — chỉ chặn nếu khoá chạm tài nguyên xcptool thực sự dùng.**
   `RealSession._reject_if_locked()` kiểm tra
   `protection & (CAL/PAG bit | DAQ bit)` (`_PROTECTION_BITS_WE_NEED = 0x01 |
   0x04`), KHÔNG chặn cứng theo `protection != 0`. ECU chỉ khoá riêng vùng PGM
   (flash) vẫn CONNECT được bình thường — quyết định có chủ đích để tránh từ
   chối oan những ECU không liên quan tới tính năng công cụ đang dùng. Nếu
   khoá đúng chỗ, ném `UnsupportedByEcuError` kèm thông báo rõ ràng, KHÔNG
   hỏng lặng lẽ giữa chừng.

### 4.4 `read()`/`write()` — chia khối theo MAX_CTO thật, KHÔNG theo giả định

`_cto_len(caps) = min(caps.max_cto, link.max_frame_len)` — **đây là điểm mấu
chốt của toàn bộ tầng bộ nhớ.** ECU có thể khai `MAX_CTO` lớn (có ý nghĩa với
XCP-on-Ethernet), nhưng CAN cổ điển giới hạn cứng 8 byte/frame
(`Transport.max_frame_len = 8`). Master luôn lấy `min` của hai số.

**Hệ quả trực tiếp: trên CAN, `SHORT_DOWNLOAD` không dùng được.**
`short_capacity = _cto_len(caps) - 8`. Với `MAX_CTO` clamp về 8 →
`short_capacity = 0` → nhánh `SHORT_DOWNLOAD` trong `write()` không bao giờ
được chọn trên CAN. Đường ghi THẬT luôn là `SET_MTA` + `DOWNLOAD` (chia theo
`chunk = _cto_len(caps) - 2`). Đây khác với mô tả ban đầu trong `DESIGN.md`
§5 ("Ghi tham số — SHORT_DOWNLOAD") — đã sửa lại tài liệu đó, nhưng nhắc lại
ở đây vì đây là chỗ dễ hiểu nhầm nhất khi đọc code lần đầu.

`read()` ngược lại: `SHORT_UPLOAD` một lệnh duy nhất khi `size <= max_chunk`
(rẻ hơn `SET_MTA`+`UPLOAD` là hai lệnh), chỉ chuyển sang `SET_MTA`+`UPLOAD`
lặp khi khối dài hơn.

### 4.5 Từ điển lỗi — `errors.py`

`ERR_TABLE: dict[int, tuple[name, description, exception_class]]` ánh xạ mọi
mã `CRC_*` trong spec XCP 1.0 sang đúng lớp ngoại lệ trong `session.api`. Mã
lỗi lạ ngoài spec vẫn dựng được `SlaveError` (`make_slave_error()` có
fallback `ERR_UNKNOWN_0x{code:02X}`) — không bao giờ `KeyError`.

### 4.6 `codec.py` — giải mã cho cửa sổ debug

`describe_tx()`/`describe_rx()` sinh chuỗi người đọc được cho `TraceEntry.decoded`
(vd. `"CONNECT mode=0"`, `"SHORT_UPLOAD size=8 ext=0 addr=0x80000000"`). Luôn
có giá trị — không giải mã được thì rơi về hex thô, không bao giờ để trống.

---

## 5. Transport layer — `transport/`

### 5.1 Registry pattern

`registry.py` giữ `SPECS: dict[str, BackendSpec]` — mỗi hãng CAN là một
`BackendSpec` (tên, `interface=` của python-can, label hiển thị, hàm `open`,
`package_hint`, `log_needles` để nhặt đúng dòng cảnh báo). **Thêm hãng mới =
thêm một `BackendSpec`, không đụng `master/`.**

Backend hiện có: `virtual`, `pcan`, `vector`, `etas`, `slcan` build trên
`PyCanTransport` (`pycan.py`) — một lớp `Transport` dùng chung, gọi
`can.Bus(interface=..., channel=..., bitrate=...)`; mỗi file chỉ còn khai
`SPEC = BackendSpec(...)` với `open=` gọi `open_pycan_bus(<interface>, cfg,
SPEC.package_hint)` rồi bọc `PyCanTransport` — vài dòng, không có logic riêng.
`etas`/`vector` giới hạn `platforms=("win32",)` vì driver chỉ có bản Windows.

**`replay` (`replay.py`) là ngoại lệ** — tự hiện thực `Transport` riêng
(`ReplayTransport`), KHÔNG qua `python-can`/`PyCanTransport`, vì nó phát lại
file trace text (mỗi dòng `<t_mono> <tx|rx> <can_id_hex> <byte hex>`) chứ
không nói chuyện với bus thật. `can_interface=""` nên không bị
`can.detect_available_configs()` dò tới; `always_available=True` giống
`virtual`. Chỉ frame `rx` trong file được phát lại (frame `tx` là của phiên
cũ). Thêm backend không qua `python-can` (vd. transport TCP cho XCP-on-Ethernet
sau này) thì viết `Transport` riêng theo mẫu `ReplayTransport`, không theo
mẫu `pcan.py`.

### 5.2 `list_devices()` — không bao giờ ném, không bao giờ để lọt rác

`can.detect_available_configs()` phun hàng chục dòng cảnh báo ra stderr cho
backend chưa cài driver. `transport/quiet.py` (`capture_can_logs()`) gắn
`logging.Handler` riêng vào logger `"can"`, cắt `propagate`, đồng thời
`redirect_stderr` — không một dòng nào lọt ra ngoài khối `with`.

**Bug đã gặp và đã sửa:** lấy bừa dòng cảnh báo đầu tiên khớp tên backend làm
`hint` là sai — cây logger `can` còn phun cả lời khuyên vô hại (vd. PEAK báo
`"uptime library not available, timestamps are relative to boot time"`, không
liên quan gì tới việc thiếu driver). `BLOCKING_PHRASES` trong `quiet.py` là
danh sách từ vựng xác định đúng loại cảnh báo "backend thực sự không dùng
được" (`"won't be able to use"`, `"could not import"`, `"not installed"`...),
lọc theo đó trước khi lấy làm `hint`.

Backend chưa cài driver **vẫn xuất hiện** trong `list_devices()` với
`available=False` + `hint` — không bao giờ im lặng bỏ qua (đây là lỗi user
gặp nhiều nhất với công cụ loại này, nhắc lại từ `DEV_PLAN.md`).

### 5.3 `config.py` — persistence CAN ID/bitrate

`~/.xcptool/config.toml` (hoặc `$XCPTOOL_HOME/config.toml` — override cho
test). Đọc bằng `tomllib` (stdlib), ghi bằng hàm tự viết ~15 dòng (schema
phẳng và biết trước, rẻ hơn thêm dependency `tomli-w`). File hỏng/thiếu →
trả về `DEFAULT_BUS_CONFIG`, không ném.

Đây là module DUY NHẤT (cùng `session/api.py`) được test ranh giới cho phép
chứa `0x7E0`/`0x7E1` — vì đó là giá trị mặc định tiện tay, không phải giả
định của logic.

**Lưu qua side-effect của `connect()`, đọc qua `Session.load_config()` —
đã hợp nhất (2026-08-16):** `RealSession.connect()` tự gọi
`cfg_store.save_bus_config(cfg)` sau khi CONNECT thành công (`_remember()`,
nuốt `OSError`, chỉ log warning) — vẫn là side-effect ẩn trong một phương
thức mà chữ ký không gợi ý gì về việc ghi file, nhưng phần đọc lại giờ đã có
đường chính thức: `Session.load_config() -> BusConfig` (không chặn, thêm vào
`session/api.py`), `RealSession` hiện thực bằng `cfg_store.load_bus_config()`.

**Lịch sử — trước đó có hai cơ chế "nhớ lựa chọn" độc lập, không đồng bộ:**
`transport/config.py` ghi `~/.xcptool/config.toml` sau CONNECT thành công
nhưng không ai đọc lại; song song đó `ui/device_dialog.py` tự làm riêng một
file `~/.xcptool/ui-last-device.json` (đọc/ghi ngay trong `ui/`, vi phạm tinh
thần ranh giới "chỉ nói chuyện qua `session.api`") để thật sự nuôi tính năng
"nhớ lựa chọn". Phát hiện khi viết tài liệu này (cả bản nháp `ARCHITECTURE.md`
lẫn `USER_MANUAL.md` độc lập tìm ra cùng một điều).

**Đã sửa:** bỏ hẳn `ui-last-device.json`/`load_last_choice`/`save_last_choice`
trong `device_dialog.py`. `DeviceDialog.__init__` nhận tham số `initial:
BusConfig | None` để tự điền sẵn, `MainWindow.open_device_dialog()` truyền
`initial=self.session.load_config()` — đi đúng qua `Session`, không with-tay
xuống file nào nữa. `FakeSession.load_config()` trả về `BusConfig` của lần
`connect()` gần nhất trong tiến trình (không cần bền qua lần chạy khác, chỉ
cần đúng hành vi để UI test được). Chữ ký `Session` đối chiếu lại vẫn khớp
100% giữa `RealSession`/`FakeSession` sau khi thêm method này; J1 chạy lại
vẫn xanh 10/10 bước.

---

## 6. Hai hiện thực `Session`

| | `RealSession` (`session/real.py`) | `FakeSession` (`session/fake.py`) |
|---|---|---|
| Chủ | backend | frontend |
| Bus thật? | Có — `python-can` qua `transport/` | Không — Python thuần, tự mô phỏng trong bộ nhớ (`dict` theo trang) |
| Dùng để | Chạy thật với ECU | GUI/CLI phát triển & test không cần phần cứng, không cần backend viết xong |
| Ngoại lệ ngoài dự kiến | Bọc mọi phương thức bằng decorator `_guarded()` — bắt `Exception` không phải `XcpToolError`, log traceback, ném lại thành `XcpToolError` | Ném trực tiếp qua `FakeBehavior` (test tự cấu hình `connect_error`, `read_error`...) |
| Mô phỏng hành vi tồi | Qua `FakeSlave` (devtools, node CAN thật trên `virtual` bus) — drop response, cắt cụt response, delay, force error, flood | Qua `FakeBehavior` — delay, lỗi, "rút dây" sau N lệnh, response méo, flood (`start_flood()`) |

### 6.1 Đối chiếu chữ ký — đã xác nhận khớp 100%

Kiểm tra tự động bằng `inspect.signature()` so từng property/method của
`Session` (Protocol) với `RealSession` và `FakeSession` — không lệch bất kỳ
chỗ nào. `isinstance(RealSession(), Session)` và tương tự với `FakeSession`
đều `True` (nhờ `@runtime_checkable`).

### 6.2 J1 — bằng chứng tích hợp mạnh nhất hiện có

`tests/ui/j1_smoke.py`: dựng `MainWindow` thật trên `RealSession` thật, nói
chuyện với `FakeSlave` (devtools) qua `virtual` bus, chạy đúng kịch bản
selftest (`ui/selftest.py`) — 10/10 bước xanh, kết quả **giống hệt** khi chạy
với `FakeSession`. Đây là bằng chứng end-to-end thật (không phải unit test
riêng lẻ) rằng toàn bộ chuỗi UI → worker thread → `RealSession` → `master` →
`transport` → `FakeSlave` hoạt động đúng.

Chạy tay: `QT_QPA_PLATFORM=offscreen python tests/ui/j1_smoke.py`

### 6.3 `devtools/fakeslave.py` — KHÁC `session/fake.py`, đừng nhầm

`FakeSlave` là một **node XCP thật** trên `virtual` bus (dùng `can.Bus` thật),
nói chuyện bằng frame CAN thật — nên đường code của `transport/` và `master/`
đi qua y hệt lúc cắm phần cứng. `FakeSession` thì không có bus nào, mô phỏng
hoàn toàn trong bộ nhớ Python. `FakeSlave` là ECU giả cho test backend + J1;
`FakeSession` là Session giả cho phát triển frontend.

Mọi đặc tính của `FakeSlave` là tham số của `SlaveConfig` (đổi `max_cto=12` ở
đó thì `SlaveCaps.max_cto` mà `RealSession.connect()` đọc được phải đổi
theo) — bài test chứng minh master không hardcode đặc tính ECU.

`FakeSlave.commands_seen` là `deque(maxlen=10_000)` chứ không phải list vô
hạn — soak chạy hàng trăm nghìn lệnh, list vô hạn ở một component TEST sẽ
hiện ra thành "rò bộ nhớ" giả trong báo cáo soak, dễ khiến người đọc report
tưởng nhầm là bug sản phẩm.

---

## 7. UI layer — `ui/`

### 7.1 Stack: PySide6-Fluent-Widgets

Dùng widget Fluent (`NavigationInterface`, `TableWidget`, `MessageBox`,
`InfoBar`...) từ package `qfluentwidgets` thay QWidget trần cho phần lớn
giao diện. `QMenuBar`/`QStatusBar` là widget Qt chuẩn (không nằm trong bộ
Fluent) nên được phủ QSS thủ công riêng (`theme.py`, `CHROME_QSS_DARK/LIGHT`).
Theme tối dùng `setTheme(Theme.DARK)` có sẵn của thư viện, KHÔNG dùng
`pyqtdarktheme` (đã ngừng maintain).

⚠️ **License: dual GPLv3 (non-commercial) / thương mại.** Xác nhận điều
khoản trước khi đóng gói bản phân phối ra ngoài — xem ghi chú trong
`pyproject.toml` và `DESIGN.md` QĐ5.

### 7.2 `MainWindow` — điều phối duy nhất giữa UI và `Session`

Ba luật contract được cưỡng chế tại ĐÚNG MỘT chỗ, không rải rác khắp UI:

1. **Mọi lời gọi chặn đi qua `self.runner` (`TaskRunner`, `workers.py`)** rồi
   quay về UI thread bằng Qt signal. `_call()` là helper trung tâm: nhận
   `label` (hiện trên status bar), `fn`, args, `on_ok`/`on_err`; tự bật/tắt
   trạng thái bận (`_begin_busy`/`_end_busy`). Không widget nào tự gọi
   `session.*` trực tiếp — luôn qua `MainWindow` làm trung gian.
2. **`drain_trace()` chỉ gọi ở ĐÚNG MỘT NƠI** — `_poll_trace()`, theo
   `QTimer` 40 ms (`TRACE_POLL_MS`), rồi phân phát cho `TraceView.feed()`.
   Hai nơi cùng `drain()` sẽ ăn mất frame của nhau (ring buffer là
   pop-once).
3. **`closeEvent()` luôn gọi `session.close()`**, kể cả khi đang bận (huỷ
   task đang chạy trước) hay đang lỗi.

`TaskRunner` (`workers.py`) dùng `QThreadPool` + `QRunnable`; `Task.cancel()`
KHÔNG cắt ngang lời gọi đang chạy (contract không có cơ chế huỷ) — nó chỉ
đánh dấu để bỏ qua kết quả khi về, và UI "huỷ" thực chất là gọi
`session.close()` để đóng cả phiên.

### 7.3 Các panel chính

- **`TraceView`** (`trace_view.py`) — bảng trace CAN. `TraceModel` là
  `QAbstractTableModel` dùng `beginInsertRows`/`beginRemoveRows` theo LÔ
  (không phải theo từng dòng) — quan trọng cho hiệu năng khi flood hàng nghìn
  frame/giây. Ring buffer có trần (`cap_spin`), lọc theo `kind`, tạm dừng
  (đếm riêng số frame bị bỏ lỡ lúc tạm dừng), xuất CSV.
- **`ConsoleView`** (`console_view.py`) — gõ hex → `raw_command()`. Lịch sử
  lệnh bằng phím mũi tên (giống shell). `raise_on_error` checkbox điều khiển
  tham số cùng tên của `raw_command()`.
- **`MemoryView`** (`memory_view.py`) — hex dump sửa trực tiếp (double-click ô
  trong `QTableWidget`), ghi TRỌN KHỐI (không phải từng byte rời). Điều khiển
  trang calibration (đọc/đặt/copy). `WORKING_PAGE = 0` ở đây là QUY ƯỚC của
  slave XcpBasic trong dự án tham chiếu, không phải chuẩn XCP — ECU khác có
  thể đánh số khác, ghi rõ trong docstring để không ai tưởng nhầm là hằng số
  chuẩn.
- **`DeviceDialog`** (`device_dialog.py`) — xem §5.3 về persistence riêng của
  nó.

### 7.4 Điểm UX quan trọng nhất: `WriteProtectedError`

`MainWindow._on_write_protected()` — khi ghi bị từ chối vì XCP đang trỏ
reference page, KHÔNG chỉ in mã lỗi mà đưa thẳng hộp thoại
(`ask_switch_to_working_page`) với nút **"Chuyển sang trang 0 và ghi lại"**.
Chấp nhận → `set_page(XCP, WORKING_PAGE)` → sau khi ECU ack, ghi lại NGAY
bằng `QTimer.singleShot(0, retry_write)`, KHÔNG chen một lượt đọc trang vào
giữa (Session không reentrant — lệnh đọc đó sẽ chiếm chỗ, lần ghi lại bị
`BusyError` hoặc phải xếp hàng).

### 7.5 Excepthook & thoát an toàn

`ui/app.py` (entry point) sở hữu:
- `sys.excepthook`/`threading.excepthook` toàn cục (`logging_setup.py`,
  `install_excepthooks()`) — bắt mọi ngoại lệ chưa bắt trên bất kỳ thread nào,
  log kèm traceback, gọi `notify()` (marshal về UI qua `MainWindow.unexpected_error`
  signal) để hiện hộp thoại xin lỗi + đường dẫn log, KHÔNG hiện traceback thô.
- `faulthandler.enable()` ghi vào file riêng — bắt cả crash mà Python không
  kịp dựng traceback (segfault trong Qt).
- `main()` gọi `window.session.close()` trong `finally` — an toàn dù
  `closeEvent` đã chạy hay chưa (idempotent).

### 7.6 `selftest.py` — không thay pytest

`--selftest` chạy 15 bước tuần tự trên MỘT event loop Qt THẬT (không mock) —
list devices → connect → raw command → đọc/ghi bộ nhớ → trang calibration →
disconnect → close. Là kịch bản duy nhất chứng minh app đã DỰNG XONG chạy
đúng đường mà user sẽ đi, kể cả phần pytest bỏ qua (event loop thật, worker
thread thật, timer thật). Dùng chung được cho cả `--session fake` và
`--session real` — đây chính là cơ chế J1 (`j1_smoke.py` chỉ đổi
`create_session` thành `RealSession()` trực tiếp).

---

## 8. CLI — `cli/`

`xcptool <command>` chạy đồng bộ trên main thread — KHÔNG có luật worker
thread (đó là luật của Qt, CLI không có event loop). `close()` vẫn phải gọi
trên MỌI đường thoát (`finally: session.close()`), kể cả khi ném
`XcpToolError` hay `KeyboardInterrupt`.

**Lý do CLI thuộc frontend, không thuộc backend** (từ `DEV_PLAN.md`): nó là
NGƯỜI TIÊU THỤ THỨ HAI của cùng contract. Có hai người tiêu thụ độc lập lộ
ngay chỗ contract thiết kế tệ — cái gì CLI làm được mà GUI không (hoặc ngược
lại) nghĩa là contract đang thiếu gì đó.

Lệnh con: `devices`, `connect`, `read`, `write`, `pages`, `set-page`, `raw`,
`trace`. Mặc định `--session real` (khác với GUI mặc định cũng là `real` —
cả hai đều yêu cầu người dùng tự chọn `fake` khi muốn chạy không cần bus).

---

## 9. Chiến lược test

| Loại | Ở đâu | Ý nghĩa |
|---|---|---|
| Ranh giới kiến trúc | `tests/test_boundaries.py` | Quét AST, không import module thật — chạy được cả khi thiếu dependency. Cưỡng chế 3 luật ở §2. |
| Unit | `tests/unit/` (backend sở hữu) | `master/`, `transport/config.py` — logic thuần, không cần bus. |
| Integration | `tests/integration/` (backend sở hữu) | Chạy qua `virtual` bus + `FakeSlave` thật — CONNECT/read/write/robustness thật sự đi qua transport. |
| UI | `tests/ui/` (frontend sở hữu) | `pytest-qt`, `QT_QPA_PLATFORM=offscreen` — chạy được trong CI không cần màn hình. |
| J1 smoke | `tests/ui/j1_smoke.py` | KHÔNG chạy bằng pytest — script tay, lead điều phối. Xem §6.2. |

Mỗi thư mục test đều có `__init__.py` — **bắt buộc**, nếu không pytest sẽ coi
hai file trùng tên ở hai thư mục khác nhau (vd. `tests/unit/test_trace.py` và
`tests/ui/test_trace.py`) là cùng một module và báo lỗi collect
("import file mismatch"). Đã gặp lỗi này thật khi cả hai agent cùng đặt tên
file trùng nhau — thêm `__init__.py` vào từng thư mục test là cách sửa dứt
điểm (biến mỗi thư mục thành package riêng, module name có tiền tố).

---

## 10. Bản đồ file

```
xcptool/
├── ARCHITECTURE.md              tài liệu này
├── USER_MANUAL.md                hướng dẫn dùng cho end-user
├── DESIGN.md, DEV_PLAN.md        tài liệu lên kế hoạch (có chỗ lỗi thời)
├── pyproject.toml                dependency + entry point `xcptool`
├── tests/
│   ├── test_boundaries.py        [lead] ranh giới kiến trúc
│   ├── conftest.py                fixture dùng chung
│   ├── unit/                     [backend] master/, transport/config.py
│   ├── integration/               [backend] qua virtual bus + FakeSlave
│   └── ui/                       [frontend] pytest-qt, offscreen; j1_smoke.py
└── src/xcptool/
    ├── session/
    │   ├── api.py                 [lead] CONTRACT — Protocol, dataclass, exception
    │   ├── real.py                [backend] RealSession — bus CAN thật
    │   └── fake.py                [frontend] FakeSession — mô phỏng thuần Python
    ├── master/                    [backend] protocol core, KHÔNG import can/PySide6
    │   ├── core.py                 XcpMaster — connect/read/write/page/raw_command
    │   ├── codec.py                 classify(), describe_tx/rx(), pack_u32()
    │   ├── constants.py            Cmd/Pid/ErrCode enum, TIMESTAMP_UNIT_NS
    │   ├── errors.py               ERR_TABLE — mã CRC_* → exception class
    │   └── trace.py                TraceBuffer — ring buffer có trần
    ├── transport/                 [backend] mọi thứ biết CAN là gì
    │   ├── base.py                  Transport ABC, CanFrame, BackendSpec
    │   ├── registry.py             SPECS, list_devices(), open_transport()
    │   ├── config.py               ~/.xcptool/config.toml
    │   ├── quiet.py                bắt cảnh báo stderr của python-can
    │   ├── pycan.py                 PyCanTransport — dùng chung cho mọi backend
    │   ├── virtual.py, pcan.py, vector.py, etas.py, slcan.py, replay.py
    │   │                            mỗi file = một BackendSpec
    ├── devtools/                  [backend] công cụ test, KHÔNG phải sản phẩm
    │   ├── fakeslave.py            FakeSlave — node XCP thật trên virtual bus
    │   └── soak.py                 chạy dài, bắt rò bộ nhớ/thread chết âm thầm
    ├── ui/                        [frontend] PySide6 + Fluent-Widgets
    │   ├── app.py                   entry point, excepthook, --selftest
    │   ├── main_window.py          điều phối UI ↔ Session (xem §7.2)
    │   ├── device_dialog.py        dialog chọn thiết bị, tự điền từ `initial`
    │   │                            (session.load_config()), không tự đọc file
    │   ├── trace_view.py, console_view.py, memory_view.py
    │   │                            ba panel chính
    │   ├── workers.py              TaskRunner — worker thread → Qt signal
    │   ├── theme.py                 Fluent dark/light + QSS cho menu/status bar
    │   ├── errors.py                exception → (tiêu đề, nội dung) tiếng Việt
    │   ├── logging_setup.py        log file + faulthandler + excepthook
    │   ├── selftest.py             --selftest, dùng chung cho j1_smoke.py
    │   └── session_factory.py      create_session("fake"|"real")
    └── cli/                       [frontend] người tiêu thụ thứ hai của contract
        ├── main.py                  toàn bộ lệnh con
        └── defaults.py             DEFAULT_BUS — lấy từ BusConfig, không lặp lại
```

---

## 11. Giới hạn hiện tại & việc dang dở

**Đã biết, chưa sửa (không phải bug — quyết định có chủ đích, ghi lại để
không ai "phát hiện lại"):**

- `protocol_version`/`transport_version` là `(major, 0)` — xem §4.3.
- Side-effect `connect()` tự lưu `config.toml` không nằm trong contract —
  xem §5.3 (đã bớt hại hơn từ khi có `Session.load_config()` đọc lại đúng
  qua contract, nhưng bản thân việc ghi vẫn ẩn trong `connect()`).
- ~~Hai cơ chế "nhớ lựa chọn thiết bị" độc lập, không đồng bộ~~ — **đã sửa**,
  xem §5.3: hợp nhất về `Session.load_config()`, bỏ `ui-last-device.json`.
- `WORKING_PAGE = 0` trong `memory_view.py` là quy ước của slave tham chiếu
  (XcpBasic), không phải chuẩn XCP — ECU khác có thể khác.

**Hoãn có chủ đích tới mốc sau** (theo `DEV_PLAN.md` §8, vẫn đúng):

| Hoãn tới | Nội dung |
|---|---|
| M3 | A2L parser — làm việc theo tên thay vì địa chỉ, cây signal, bảng calibration |
| M4 | DAQ engine, scope `pyqtgraph`. `DaqCaps` trong contract đã khai sẵn để không phải đổi contract lúc đó. Nhớ: ngân sách 3 byte của ODT đầu tiên khi bật timestamp — xem `DESIGN.md` §4.3 (bug packing tham chiếu đã biết, phải sửa cùng lúc viết test, đừng copy nguyên bản) |
| M5 | MDF4 (`asammdf`), xuất/nhập bộ tham số, XCP-on-Ethernet, đóng gói `.exe` |
| Giai đoạn sau | Kiểm tra trên board thật; `driver/port/pc_sim/` nếu vẫn muốn |

---

## 12. Hướng dẫn mở rộng

### Thêm backend CAN mới (vd. một hãng khác)

1. Tạo `transport/<hãng>.py`, viết hàm `open_<hãng>(cfg: BusConfig) -> Transport`
   (thường chỉ cần gọi `open_pycan_bus(interface, cfg, package_hint, **extra)`
   nếu hãng đó có driver `python-can`).
2. Khai `SPEC = BackendSpec(name=..., can_interface=..., label=..., package_hint=...,
   open=open_<hãng>, log_needles=(...))`.
3. Thêm vào tuple import trong `registry.py` (`from . import ..., <hãng>`) và
   vào `SPECS`.
4. KHÔNG đụng `master/` — protocol core không biết backend nào đang chạy.

### Thêm lệnh XCP mới vào `master/`

1. Thêm mã lệnh vào `constants.Cmd` nếu chưa có.
2. Viết phương thức trên `XcpMaster` dùng `self._locked_transact(...)` —
   không tự ý bỏ qua khoá `_cmd_lock` (đó là cơ chế `BusyError`/không
   reentrant).
3. Nếu lệnh trả dữ liệu có ý nghĩa cho UI, thêm vào `session/api.py`
   (`Session` Protocol) TRƯỚC — không thêm phương thức "ngầm" chỉ có ở
   `RealSession` mà `FakeSession` không có (phá vỡ tính năng phát triển độc
   lập của frontend). Nhắn lead nếu là agent, đợi duyệt.
4. Cập nhật cả `RealSession` VÀ `FakeSession` cùng lúc — chữ ký phải khớp
   (dùng script đối chiếu ở §6.1 để tự kiểm tra trước khi báo xong).

### Thêm panel UI mới

1. Widget mới nhận callback do `MainWindow` cấp (theo mẫu `MemoryView`:
   nhận `read_cb`, `write_cb`... là hàm của `MainWindow`, không tự gọi
   `session.*`).
2. `MainWindow` là nơi DUY NHẤT gọi `self._call(...)` để chạy lệnh Session
   qua worker thread — panel mới không tự tạo `TaskRunner` riêng.
3. Nếu panel cần dữ liệu trace, KHÔNG tự gọi `drain_trace()` — nhận dữ liệu
   qua `MainWindow._poll_trace()` phân phát (xem §7.2 luật #2).
4. Thêm vào `nav.addItem(...)` trong `_build_navigation()` và vào
   `view_menu` trong `_build_menus()`.

### Quy tắc không được phá vỡ (test sẽ đỏ nếu phá)

- Không import `can`/`PySide6` chéo tầng — xem bảng ranh giới ở §2.
- Không hardcode `0x7E0`/`0x7E1` (hay bất kỳ đặc tính ECU cụ thể nào) ngoài
  ba file được phép (`session/api.py`, `transport/config.py`, `cli/defaults.py`).
- `session/api.py` chỉ lead sửa. Cần đổi contract → nhắn lead, không tự sửa
  rồi báo sau.
- `close()` ở mọi tầng (`Session`, `XcpMaster`, `Transport`) phải idempotent
  và không bao giờ ném — vi phạm luật này làm app treo lúc thoát, khó tái
  hiện, khó debug.
