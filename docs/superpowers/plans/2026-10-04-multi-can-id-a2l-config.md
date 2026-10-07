# Nhận DAQ nhiều CAN ID + cấu hình CAN từ A2L — Kế hoạch triển khai

> **Trạng thái: HOÀN THÀNH** — cả 10 task đã thực thi và merge, mỗi task một commit:
> `a9f0536` (1) · `33935d5` (2) · `5b22454` (3) · `b52d45f` (4) · `7f28943` (5) · `3a10486` (6) ·
> `70df54a` (7) · `0eb508a` (8) · `b91788d` (9) · `c08846f` (10). Theo sau còn `7f7e9dc` giải lại
> thanh ghi timing khi dùng bitrate từ A2L. Tra lại: `git log --oneline a9f0536~1..c08846f`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** xcptool nhận và giải mã DTO trên nhiều CAN ID (mỗi DAQ list một ID), và đọc cấu hình CAN từ A2L qua một checkbox trong dialog Connect.

**Architecture:** `BusConfig` biết tập CAN ID nhận (`rx_ids`); filter phần cứng, `XcpMaster._on_frame` và bảng tra DTO đều theo tập đó. Cấu hình A2L được đọc vào `XcpCanInfo` (parser tự viết, không dùng pyA2L) rồi áp lúc `connect()` bằng hàm thuần `apply_a2l_can`; dialog chỉ hiển thị và khoá ô.

**Tech Stack:** Python, python-can (bus `virtual` cho test), PySide6 + Fluent Widgets, pytest / pytest-qt.

**Spec:** `docs/superpowers/specs/2026-10-04-multi-can-id-a2l-config-design.md`

## Global Constraints

- Chạy mọi lệnh từ thư mục `xcptool/`: `python -m pytest <path> -v`. Chạy cả bộ: `python -m pytest`.
- `daq_can_ids` rỗng ⇒ hành vi **y hệt hiện tại**; mọi test cũ giữ nguyên và phải xanh sau mỗi task.
- Comment/docstring tiếng Việt, đúng giọng các file xung quanh.
- Khi commit chỉ `git add` đúng các file của task (cây làm việc đang có `config.toml` sửa dở và nhiều file chưa track của người dùng — **không** stage chúng). Kiểm tra `git diff --cached --stat` trước khi commit.
- Commit message kết thúc bằng dòng `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Test không được đụng thư mục cấu hình thật: `tests/conftest.py` đã đặt `XCPTOOL_HOME`; test dùng `channel` fixture riêng cho mỗi bus `virtual`.
- A2L: `CAN_ID_*` có bit 31 = 1 là 29-bit; `DAQ_LIST_CAN_ID` là **block con** của `XCP_ON_CAN`, `VARIABLE` không kèm ID, `FIXED <id>`.
- Ngoài phạm vi: `GET_DAQ_ID`/`SET_DAQ_ID`, ô nhập tay `daq_can_ids`, CLI `--can-from-a2l`, `CAN_ID_BROADCAST`, đổi `FakeSession._flood_loop`, STIM.

**Sai khác có chủ ý so với spec §3.3:** khoá bảng tra chỉ thành `(can_id, DtoKey)` khi caller truyền `route_of` (tức `daq_can_ids` không rỗng). Khi không truyền, bảng giữ khoá thuần như cũ. Lý do: ~70 chỗ trong 7 file test đang đọc/dựng bảng với khoá thuần. Một bảng chỉ thuộc một trong hai dạng nên không có nhập nhằng với khoá `(daq, odt)` của id_type 1–3. (Task 4 cập nhật lại spec §3.3 cho khớp.)

## Review Focus

1. Frame trên CAN ID riêng của một DAQ list có byte đầu `0xFF`/`0xFE` — không được hiểu là response (test ở Task 3).
2. Frame trên CAN ID ngoài `rx_ids` — bị bỏ, không làm hỏng lệnh đang chờ (Task 3).
3. `daq_can_ids` trùng ID giữa hai list, trùng `cro_id`, hoặc chuỗi TOML sai định dạng — lỗi rõ ràng / bỏ qua khoá, không chạy rồi mất dữ liệu (Task 1, 6).
4. ECU static: DAQ list vật lý không liền kề `i` — ID tra theo số **vật lý** (`daq_idx`), không theo vị trí trong `configs` (Task 4).
5. `use_a2l_can` bật nhưng chưa nạp A2L / A2L không có `XCP_ON_CAN` / thiếu một trường (vd `BAUDRATE`) / `custom_bit_timing` đang bật — thông báo rõ, không mở bus mơ hồ, không ghi đè giá trị tay (Task 8, 9, 10).

---

## Phần 1 — Nhận DAQ trên nhiều CAN ID

### Task 1: `BusConfig` biết tập CAN ID + lưu TOML

**Files:**
- Modify: `src/xcptool/session/api.py:125` (BusConfig)
- Modify: `src/xcptool/transport/config.py:78` (`_coerce_bus`), `:170` (`dumps_bus_config`)
- Test: `tests/unit/test_config.py` (thêm), `tests/unit/test_bus_ids.py` (mới)

**Interfaces:**
- Produces:
  - `BusConfig.daq_can_ids: tuple[tuple[int, int], ...] = ()` — các cặp `(số DAQ list vật lý, can_id)`.
  - `BusConfig.use_a2l_can: bool = False`.
  - `BusConfig.rx_ids -> frozenset[int]` (property) = `{dto_id} ∪ {id}`.
  - `BusConfig.daq_can_id_of(daq: int) -> int` = ID của list `daq`, mặc định `dto_id`.
  - `BusConfig.validate_ids() -> None` — ném `XcpToolError` (định nghĩa cùng file `api.py:318`) nếu hai list cùng ID, hoặc một ID trùng `cro_id`.
  - TOML: `daq_can_ids = "0:0x6A2,1:0x6A3"`, `use_a2l_can = true`.

- [x] **Step 1: Viết test (fail)** trong `tests/unit/test_bus_ids.py`:
  - `test_rx_ids_chi_co_dto_id_khi_khong_cau_hinh`: `BusConfig(backend="v", channel="c").rx_ids == frozenset({0x7E1})`.
  - `test_rx_ids_gom_id_rieng_cua_tung_list`: `daq_can_ids=((0,0x6A2),(1,0x6A3))`, `dto_id=0x6A1` → `{0x6A1,0x6A2,0x6A3}`; `daq_can_id_of(1)==0x6A3`, `daq_can_id_of(5)==0x6A1`.
  - `test_validate_ids_bao_loi_khi_hai_list_cung_id` và `..._khi_trung_cro_id`: `pytest.raises(XcpToolError)`; cấu hình hợp lệ thì không ném.
  - Trong `test_config.py`: `test_daq_can_ids_round_trip_toml` (ghi rồi đọc bằng `dumps_bus_config`/`load_bus_config` → bằng nhau, file chứa `0x6A2` dạng hex), `test_daq_can_ids_sai_dinh_dang_bi_bo_qua` (`daq_can_ids = "abc"` → `()`, các khoá khác vẫn đọc được), `test_use_a2l_can_round_trip`.
- [x] **Step 2:** Chạy `python -m pytest tests/unit/test_bus_ids.py tests/unit/test_config.py -v` → FAIL (thiếu thuộc tính).
- [x] **Step 3:** Thêm hai field + `rx_ids` + `daq_can_id_of` + `validate_ids` vào `BusConfig`. Trong `config.py`: `_coerce_bus` đọc `daq_can_ids` kiểu `str` rồi tách `"daq:id"` (id nhận cả `0x..` lẫn thập phân; mục nào sai → bỏ cả khoá), `use_a2l_can` kiểu `bool`; `dumps_bus_config` ghi `daq_can_ids` (hex) và `use_a2l_can`.
- [x] **Step 4:** Chạy lại hai file test → PASS; chạy `python -m pytest tests/unit -q` → không hồi quy.
- [x] **Step 5: Commit** — `git add src/xcptool/session/api.py src/xcptool/transport/config.py tests/unit/test_bus_ids.py tests/unit/test_config.py` · `feat(xcptool): BusConfig có daq_can_ids/use_a2l_can, rx_ids và lưu TOML`

### Task 2: Filter phần cứng cho mọi `rx_ids`

**Files:**
- Modify: `src/xcptool/transport/pycan.py:49-51`
- Test: `tests/unit/test_pycan_filters.py` (mới)

**Interfaces:**
- Consumes: `BusConfig.rx_ids` (Task 1).
- Produces: `rx_filters(cfg: BusConfig) -> list[dict[str, object]]` trong `pycan.py` — một filter cho mỗi ID, sắp xếp tăng dần, cùng mask (`0x1FFFFFFF` nếu `extended_id`, ngược lại `0x7FF`) và cờ `extended`.

- [x] **Step 1: Viết test (fail):** `test_mot_filter_khi_chi_co_dto_id` (== `[{"can_id":0x7E1,"can_mask":0x7FF,"extended":False}]`), `test_moi_id_mot_filter` (3 ID → 3 filter, thứ tự tăng dần), `test_mask_29_bit_khi_extended_id`.
- [x] **Step 2:** `python -m pytest tests/unit/test_pycan_filters.py -v` → FAIL.
- [x] **Step 3:** Tách phép dựng filter hiện có thành `rx_filters(cfg)` và gán `kwargs["can_filters"] = rx_filters(cfg)`.
- [x] **Step 4:** Chạy test mới + `tests/unit/test_protocol_core.py::test_frame_on_another_can_id_is_dropped` → PASS.
- [x] **Step 5: Commit** — `git add src/xcptool/transport/pycan.py tests/unit/test_pycan_filters.py` · `feat(xcptool): filter phần cứng cho mọi CAN ID nhận`

### Task 3: `XcpMaster` nhận nhiều ID, callback DAQ mang `can_id`

**Files:**
- Modify: `src/xcptool/master/core.py:111-147` (kiểu callback, `set_daq_callback`), `:175-200` (`_on_frame`)
- Modify: `src/xcptool/session/real.py:364` (`_on_daq_frame`)
- Test: `tests/integration/test_multi_can_id_rx.py` (mới)

**Interfaces:**
- Consumes: `BusConfig.rx_ids`, `BusConfig.daq_can_ids` (Task 1); `FakeSlave.send_raw(can_id, data)` (đã có).
- Produces: callback DAQ đổi thành `Callable[[bytes, int], None]` — tham số 2 là `can_id` của frame. `RealSession._on_daq_frame(self, frame: bytes, can_id: int) -> None` (chưa dùng `can_id` ở task này).

Quy tắc `_on_frame`: `can_id ∉ rx_ids` → bỏ; `can_id == dto_id` → `classify()` như cũ; `can_id` là ID riêng của một list → **luôn** `kind="daq"`, không `classify()`; trace ghi đúng `can_id` của frame.

- [x] **Step 1: Viết test (fail)** trong `tests/integration/test_multi_can_id_rx.py` (dùng fixtures `session`, `slave`, `slave_cfg`, `bus_cfg` của conftest; `dataclasses.replace(bus_cfg, daq_can_ids=((0, dto+0x10),))`; đăng ký callback qua `session._master.set_daq_callback`):
  - `test_frame_tren_id_rieng_toi_callback_kem_can_id`: `slave.send_raw(dto+0x10, b"\x01\x02\x03\x04")` → callback nhận `(data, dto+0x10)`.
  - `test_frame_id_rieng_byte_dau_0xFF_van_la_daq`: `send_raw(dto+0x10, b"\xFF\xFE\x01\x02")` → vào callback, trace có entry `kind=="daq"`, `can_id==dto+0x10`, và lệnh `session.read(...)` ngay sau đó vẫn trả đúng (hàng đợi response không bị nhiễm).
  - `test_frame_ngoai_rx_ids_van_bi_bo`: `send_raw(dto+0x50, ...)` → callback không được gọi, trace không có entry mới.
  - `test_khong_cau_hinh_id_rieng_thi_nhu_cu`: bus_cfg gốc, frame DAQ trên `dto_id` vẫn tới callback, `can_id == dto_id`.
- [x] **Step 2:** `python -m pytest tests/integration/test_multi_can_id_rx.py -v` → FAIL.
- [x] **Step 3:** Sửa `_on_frame` theo quy tắc trên (dùng `self._cfg.rx_ids` / `daq_can_ids`); đổi kiểu và lời gọi callback thành `cb(data, frame.can_id)`; cập nhật docstring; đổi chữ ký `RealSession._on_daq_frame`.
- [x] **Step 4:** Chạy test mới; rồi `python -m pytest tests/integration tests/unit -q` → không hồi quy.
- [x] **Step 5: Commit** — `git add src/xcptool/master/core.py src/xcptool/session/real.py tests/integration/test_multi_can_id_rx.py` · `feat(xcptool): master nhận DTO trên CAN ID riêng của DAQ list`

### Task 4: Định tuyến bảng tra DTO theo CAN ID

**Files:**
- Modify: `src/xcptool/master/daq.py` (`DtoKey` alias ~l.124, `configure_daq` l.193, `configure_daq_predefined` l.369, `_write_and_start` l.431, `decode_dto` l.564, `__all__` l.34)
- Modify: `docs/superpowers/specs/2026-10-04-multi-can-id-a2l-config-design.md` §3.3 (ghi sai khác chủ ý ở đầu plan)
- Test: `tests/unit/test_daq_routing.py` (mới)

**Interfaces:**
- Produces:
  - `RouteKey = tuple[int, DtoKey]` (export trong `__all__`).
  - `route_key(can_id: int, key: DtoKey) -> RouteKey`.
  - `configure_daq(master, configs, route_of: Callable[[int], int] | None = None) -> dict[DtoKey | RouteKey, PidEntry]`; `configure_daq_predefined(master, lists, route_of=None)` tương tự. `route_of(daq_vat_ly) -> can_id`; `None` ⇒ khoá thuần (hành vi cũ).
  - `decode_dto(frame, pid_table, ts_accum, fmt=None, can_id: int | None = None)`; `can_id` khác `None` ⇒ tra `route_key(can_id, key)`.

- [x] **Step 1: Viết test (fail)** trong `tests/unit/test_daq_routing.py` (dựng `PidEntry`/bảng tay như `tests/unit/test_daq_decoder.py`):
  - `test_cung_pid_tren_hai_can_id_ra_hai_list_khac_nhau`: bảng `{(0x6A2, 1): entry_list0, (0x6A3, 1): entry_list1}`; cùng frame `bytes([1, ...])` giải với `can_id=0x6A2` ra tên signal của list 0, với `0x6A3` ra list 1.
  - `test_can_id_la_khong_co_trong_bang_ra_rong`: `can_id=0x6AF` → `[]`.
  - `test_can_id_none_dung_khoa_thuan`: bảng khoá thuần + `can_id=None` giải như hiện nay.
  - `test_route_of_dang_ky_theo_so_vat_ly`: dùng FakeSlave static (`daq_dynamic=False`, `min_daq=2`/`max_daq=2`, theo mẫu fixture static của `tests/integration/test_daq.py`), cấp phát để list vật lý không liền kề thứ tự `configs`, truyền `route_of={0:0x6A2,1:0x6A3}.__getitem__`; mọi khoá trong bảng trả về có dạng `(route_of(entry.daq_list), …)`.
- [x] **Step 2:** `python -m pytest tests/unit/test_daq_routing.py -v` → FAIL.
- [x] **Step 3:** Thêm `route_key`; ở `_write_and_start` và `configure_daq_predefined`, khoá bảng = `make_key(...)` nếu `route_of is None`, ngược lại `route_key(route_of(daq_idx), make_key(...))`; `decode_dto` tra khoá theo `can_id`; không đổi `PidEntry` và `TimestampAccumulator`. Sửa spec §3.3 cho khớp sai khác ở đầu plan.
- [x] **Step 4:** Chạy test mới, rồi `python -m pytest tests/unit tests/integration/test_daq.py tests/integration/test_daq_dto_formats.py -q` → PASS (không sửa test cũ).
- [x] **Step 5: Commit** — `git add src/xcptool/master/daq.py tests/unit/test_daq_routing.py docs/superpowers/specs/2026-10-04-multi-can-id-a2l-config-design.md` · `feat(xcptool): bảng tra DTO có thể định tuyến theo CAN ID`

### Task 5: FakeSlave phát DTO trên ID riêng của từng list

**Files:**
- Modify: `src/xcptool/devtools/fakeslave.py:40` (`SlaveConfig`), `:290-333` (`_send_daq_frames`)
- Test: `tests/unit/test_fakeslave_dto.py` (thêm)

**Interfaces:**
- Produces: `SlaveConfig.daq_can_ids: dict[int, int]` (mặc định `{}`): DTO của list vật lý `n` phát với `arbitration_id = daq_can_ids.get(n, dto_id)`; response vẫn phát trên `dto_id`.

- [x] **Step 1: Viết test (fail):** `test_dto_cua_list_phat_tren_id_rieng` — `SlaveConfig(channel=…, daq_can_ids={0: 0x611, 1: 0x612})`, kết nối bằng helper `connected`, tự đọc bus `virtual` cùng channel bằng một `can.Bus` thứ hai (hoặc cơ chế sẵn có của file) và khẳng định frame của list 0 có `arbitration_id==0x611`, list 1 là `0x612`, response CONNECT vẫn `0x601`; `test_khong_cau_hinh_thi_dto_tren_dto_id` (hành vi cũ).
- [x] **Step 2:** `python -m pytest tests/unit/test_fakeslave_dto.py -v` → test mới FAIL.
- [x] **Step 3:** Thêm field vào `SlaveConfig` và dùng ở `_send_daq_frames` (biến `daq` đã là số list vật lý).
- [x] **Step 4:** Chạy cả `tests/unit/test_fakeslave_dto.py` → PASS.
- [x] **Step 5: Commit** — `git add src/xcptool/devtools/fakeslave.py tests/unit/test_fakeslave_dto.py` · `feat(fakeslave): DTO của mỗi DAQ list có thể phát trên CAN ID riêng`

### Task 6: `RealSession` nối dây + kiểm thử đầu-cuối (giao được riêng)

**Files:**
- Modify: `src/xcptool/session/real.py:168` (`connect`), `:332` (`start_daq`), `:364` (`_on_daq_frame`)
- Modify: `ARCHITECTURE.md` (thêm mục ngắn về định tuyến DTO theo CAN ID, đặt cạnh mục 4.4 `DtoFormat`)
- Test: `tests/integration/test_multi_can_id_daq.py` (mới)

**Interfaces:**
- Consumes: `BusConfig.validate_ids/rx_ids/daq_can_id_of` (Task 1), `configure_daq(..., route_of=)` & `decode_dto(..., can_id=)` (Task 4), callback `(data, can_id)` (Task 3), `SlaveConfig.daq_can_ids` (Task 5).
- Produces: `RealSession.connect(cfg)` gọi `cfg.validate_ids()` trước khi mở bus; `start_daq` truyền `route_of=cfg.daq_can_id_of` chỉ khi `cfg.daq_can_ids` không rỗng; `_on_daq_frame` truyền `can_id` cho `decode_dto` trong đúng trường hợp đó.

- [x] **Step 1: Viết test (fail)** trong `tests/integration/test_multi_can_id_daq.py` (theo mẫu `tests/integration/test_session_daq.py`: `SlaveConfig(channel=…, daq_can_ids={0:0x611,1:0x612}, max_daq=2)`, `BusConfig` tương ứng có `daq_can_ids=((0,0x611),(1,0x612))`, `slave.poke` để đặt giá trị):
  - `test_hai_list_hai_can_id_ra_du_mau`: `start_daq` hai list (mỗi list một signal khác tên, `event=0`), đợi, `drain_daq()` có mẫu của **cả hai** tên với đúng giá trị.
  - `test_pid_trung_giua_hai_list_van_tach_duoc`: đặt `id_field_type=0` và ép FakeSlave đánh PID lại từ 0 cho mỗi list nếu cấu hình hiện có cho phép; nếu không, test dùng `id_field_type=1` (khoá `(daq, odt)`) — ghi lý do trong docstring.
  - `test_ket_noi_tu_choi_khi_hai_list_cung_id`: `daq_can_ids=((0,0x611),(1,0x611))` → `connect` ném `XcpToolError`, không mở transport (`session.state == ConnState.DISCONNECTED`).
  - `test_khong_cau_hinh_thi_nhu_cu`: chạy lại kịch bản của `test_real_drain_daq_returns_sample_points` với cấu hình cũ → vẫn ra mẫu.
- [x] **Step 2:** `python -m pytest tests/integration/test_multi_can_id_daq.py -v` → FAIL.
- [x] **Step 3:** Thực hiện nối dây như mục Produces; `_remember` giữ nguyên.
- [x] **Step 4:** `python -m pytest -q` (toàn bộ) → PASS. Đây là mốc có thể phát hành riêng: lỗi mất DAQ im lặng đã sửa.
- [x] **Step 5: Commit** — `git add src/xcptool/session/real.py ARCHITECTURE.md tests/integration/test_multi_can_id_daq.py` · `feat(xcptool): RealSession nhận DAQ nhiều CAN ID đầu-cuối`

---

## Phần 2 — Cấu hình CAN từ A2L

### Task 7: `XcpCanInfo` + parser `XCP_ON_CAN`

**Files:**
- Modify: `src/xcptool/a2l/types.py` (thêm `DaqListCanId`, `XcpCanInfo`; `A2LDatabase.can_info` ~l.233), `src/xcptool/a2l/__init__.py` (export)
- Modify: `src/xcptool/a2l/parser.py` (hàm mới `_extract_xcp_can_info`, gọi ở nhánh IF_DATA XCP ~l.576-590 cạnh `_extract_xcp_protocol_info`)
- Test: `tests/unit/test_a2l_can_info.py` (mới)

**Interfaces:**
- Produces (dataclass `frozen`):
  - `DaqListCanId(daq_list: int, fixed: bool, can_id: int | None)`.
  - `XcpCanInfo(master_id: int | None, slave_id: int | None, extended: bool | None, baudrate: int | None, sample_point: float | None, is_fd: bool, fd_data_baudrate: int | None, fd_data_sample_point: float | None, max_dlc_required: bool, daq_list_ids: tuple[DaqListCanId, ...], notes: tuple[str, ...])`.
  - `A2LDatabase.can_info: XcpCanInfo | None = None`.
- Quy tắc: đọc theo **từ khoá** trong `tokens` của `XCP_ON_CAN`; `DAQ_LIST_CAN_ID` đọc qua `children` (tokens: `[list, "FIXED", id]` hoặc `[list, "VARIABLE"]`); ID có bit 31 ⇒ bỏ bit đó, `extended=True`; `extended` = `None` nếu không có `CAN_ID_MASTER` lẫn `CAN_ID_SLAVE`; block CAN FD nhận cả tên `CAN_FD` lẫn `XCP_ON_CAN_FD` (trường nào thiếu → `None`); `CAN_ID_MASTER_INCREMENTAL` đọc rồi bỏ qua, ghi một câu vào `notes`; lỗi cả block → `can_info=None` + `_log.warning`.

- [x] **Step 1: Viết test (fail)** — chuỗi A2L tối thiểu dựng trong test (nhãn "mẫu cú pháp theo AML XCP on CAN v1.0, ví dụ pyxcp"), parse bằng hàm parse hiện có của `a2l`:
  - `test_xcp_daq_example_a2l`: `examples/xcp_daq_example.a2l` → `master_id==0x7E0`, `slave_id==0x7E1`, `baudrate==500000`, `sample_point==75`, `extended is False`, `max_dlc_required`, `daq_list_ids==()`.
  - `test_ba_daq_list_can_id_fixed`: ví dụ pyxcp (master 0x0200, slave 0x0300, list 0/1/2 → `FIXED 0x310/0x320/0x330`) → `daq_list_ids == (DaqListCanId(0,True,0x310), …)`, và `notes` nhắc `CAN_ID_MASTER_INCREMENTAL`.
  - `test_variable_khong_co_can_id`: `/begin DAQ_LIST_CAN_ID 1 VARIABLE /end DAQ_LIST_CAN_ID` → `DaqListCanId(1, False, None)`.
  - `test_id_29_bit_bit31`: `CAN_ID_MASTER 0x80000123` → `master_id==0x123`, `extended is True`.
  - `test_thieu_truong_thi_none`: A2L chỉ có `CAN_ID_MASTER/SLAVE` → `baudrate is None`, `sample_point is None`, `is_fd is False`.
  - `test_khoi_can_fd_ca_hai_ten`: block `CAN_FD` và `XCP_ON_CAN_FD` đều cho `is_fd is True`; `fd_data_baudrate`/`fd_data_sample_point` đọc được khi có từ khoá `CAN_FD_DATA_TRANSFER_BAUDRATE`/`SAMPLE_POINT`, ngược lại `None` (đây là giả định A3 — ghi chú trong docstring test).
  - `test_khong_co_xcp_on_can_thi_can_info_none` và `test_block_hong_khong_nem` (token cụt → `None`, không raise).
- [x] **Step 2:** `python -m pytest tests/unit/test_a2l_can_info.py -v` → FAIL.
- [x] **Step 3:** Cài đặt như mục Interfaces; `XcpProtocolInfo.is_fd/max_dlc_required` giữ nguyên. Bắt `ValueError/IndexError` bằng `_to_int` như các hàm extract hiện có.
- [x] **Step 4:** `python -m pytest tests/unit/test_a2l_can_info.py tests/unit/test_a2l_parser.py tests/unit/test_a2l_database.py tests/unit/test_can_fd_payload.py -q` → PASS.
- [x] **Step 5: Commit** — `git add src/xcptool/a2l/types.py src/xcptool/a2l/__init__.py src/xcptool/a2l/parser.py tests/unit/test_a2l_can_info.py` · `feat(a2l): đọc XCP_ON_CAN (ID, baudrate, FD, DAQ_LIST_CAN_ID)`

### Task 8: `apply_a2l_can` (hàm thuần)

**Files:**
- Create: `src/xcptool/session/a2l_can.py`
- Test: `tests/unit/test_a2l_can_apply.py` (mới)

**Interfaces:**
- Consumes: `BusConfig` (Task 1), `XcpCanInfo` (Task 7).
- Produces: `apply_a2l_can(cfg: BusConfig, info: XcpCanInfo) -> tuple[BusConfig, list[str]]`.
  - Ghi đè: `cro_id`←`master_id`, `dto_id`←`slave_id`, `extended_id`, `bitrate`, `sample_point`, `is_fd`, `data_bitrate`←`fd_data_baudrate`, `data_sample_point`←`fd_data_sample_point`, `pad_dlc`←`max_dlc_required` (chỉ khi A2L có từ khoá), `daq_can_ids`←các list `fixed`.
  - Trường A2L là `None` → giữ giá trị của `cfg` và thêm một dòng ghi chú.
  - List `VARIABLE` → không vào `daq_can_ids`; ghi chú `"list N: VARIABLE — cần SET_DAQ_ID (chưa hỗ trợ)"`.
  - `cfg.custom_bit_timing` là `True` → không đổi timing thủ công, ghi chú cảnh báo "bitrate A2L chưa được dùng".
  - Không đụng: `backend`, `channel`, `f_clock`, `brp/tseg*`, `dbrp/dtseg*`, `t1_timeout_s`, `use_a2l_can`.
  - Nối thêm `info.notes` vào cuối danh sách ghi chú; không I/O.

- [x] **Step 1: Viết test (fail):** `test_ghi_de_id_bitrate_va_fd`, `test_truong_none_giu_gia_tri_cu_va_co_ghi_chu`, `test_chi_list_fixed_vao_daq_can_ids`, `test_variable_co_ghi_chu_khong_vao_cau_hinh`, `test_custom_bit_timing_thang_va_co_canh_bao` (bitrate giữ nguyên), `test_khong_dung_backend_channel_f_clock`, `test_id_29_bit_dat_extended_id`.
- [x] **Step 2:** `python -m pytest tests/unit/test_a2l_can_apply.py -v` → FAIL.
- [x] **Step 3:** Cài đặt bằng `dataclasses.replace`.
- [x] **Step 4:** Chạy lại → PASS.
- [x] **Step 5: Commit** — `git add src/xcptool/session/a2l_can.py tests/unit/test_a2l_can_apply.py` · `feat(xcptool): apply_a2l_can áp cấu hình CAN từ A2L`

### Task 9: `connect()` dùng cấu hình A2L (Real + Fake)

**Files:**
- Modify: `src/xcptool/session/real.py:168` (`connect`), `src/xcptool/session/fake.py:275` (`connect`)
- Test: `tests/integration/test_connect_a2l_can.py` (mới)

**Interfaces:**
- Consumes: `apply_a2l_can` (Task 8), `A2LDatabase.can_info` (Task 7), `XcpCanInfo`, `RealSession.symbols`.
- Produces: khi `cfg.use_a2l_can`:
  1. Chưa nạp A2L, hoặc `symbols.can_info is None` → `XcpToolError` nêu rõ nguyên nhân, **không** mở transport.
  2. `eff, notes = apply_a2l_can(cfg, can_info)`; `eff.validate_ids()`; mở transport/master bằng `eff`; ghi `notes` vào trace (một entry `kind="other"`, mô tả bắt đầu bằng `"CAN config từ A2L"`).
  3. `_remember(cfg)` lưu `cfg` **gốc** (giá trị tay + cờ).
  `FakeSession.connect` làm tương tự (không cần mở bus) để UI test chạy được.

- [x] **Step 1: Viết test (fail)** (nạp A2L bằng `session.load_a2l(tmp_path/"x.a2l")` với chuỗi A2L dựng sẵn có `XCP_ON_CAN`: master/slave khớp `SlaveConfig`, `BAUDRATE 500000`, hai `DAQ_LIST_CAN_ID FIXED`):
  - `test_use_a2l_can_ket_noi_duoc_du_cfg_tay_sai_id`: `BusConfig` có `cro_id/dto_id` **sai**, `use_a2l_can=True` → `connect` thành công vì dùng ID của A2L; `session.start_daq` hai list ra mẫu đúng (kết hợp FakeSlave `daq_can_ids`).
  - `test_khong_a2l_thi_loi_ro_rang`: `pytest.raises(XcpToolError, match="A2L")`, state `DISCONNECTED`.
  - `test_a2l_khong_co_xcp_on_can_thi_loi`: A2L không có block → lỗi nêu `XCP_ON_CAN`.
  - `test_remember_luu_cfg_goc`: sau connect, `load_config()` trả `cro_id/dto_id` **tay** và `use_a2l_can is True` (không phải giá trị A2L).
  - `test_trace_ghi_dong_cau_hinh_tu_a2l`: `drain_trace()` có entry `kind=="other"` bắt đầu `"CAN config từ A2L"`.
  - `test_fake_session_cung_quy_tac`: `FakeSession` + `use_a2l_can=True` không A2L → cùng loại lỗi.
- [x] **Step 2:** `python -m pytest tests/integration/test_connect_a2l_can.py -v` → FAIL.
- [x] **Step 3:** Cài đặt ở hai `connect`; dùng `eff` cho `registry.open_transport`/`XcpMaster`/`FakeSession._cfg`, `cfg` gốc cho `_remember`.
- [x] **Step 4:** `python -m pytest -q` → PASS.
- [x] **Step 5: Commit** — `git add src/xcptool/session/real.py src/xcptool/session/fake.py tests/integration/test_connect_a2l_can.py` · `feat(xcptool): connect dùng cấu hình CAN từ A2L khi use_a2l_can`

### Task 10: Checkbox trong dialog Connect

**Files:**
- Modify: `src/xcptool/ui/device_dialog.py` (`__init__` l.68, `_apply_initial_config` l.464, `build_config` l.523; thêm checkbox + dòng tóm tắt gần nhóm CAN ID l.205-215)
- Modify: `src/xcptool/ui/main_window.py:498` (truyền `self.session.symbols.can_info`)
- Modify: `USER_MANUAL.md` (mô tả checkbox "Config CAN from A2L")
- Test: `tests/ui/test_connect_flow.py` (thêm)

**Interfaces:**
- Consumes: `apply_a2l_can` (Task 8), `XcpCanInfo` (Task 7), `BusConfig.use_a2l_can`.
- Produces: `DeviceDialog(parent=None, initial=None, a2l_can: XcpCanInfo | None = None)`; widget `a2l_cb` (checkbox) và `a2l_summary` (label). `build_config()` luôn trả giá trị **nhập tay** + `use_a2l_can = a2l_cb.isChecked()`.

Hành vi: `a2l_can is None` → checkbox xám, bỏ tích, tooltip nêu lý do ("chưa nạp A2L hoặc A2L không có XCP_ON_CAN"), `build_config().use_a2l_can is False`. Tích → cất giá trị tay hiện tại, hiển thị giá trị hiệu lực (`apply_a2l_can` trên cfg đang nhập) vào ô CRO/DTO, 11/29-bit, bitrate, data bitrate, FD, sample point và **khoá chỉnh sửa**; bitrate không có trong combo thì thêm mục tạm; `a2l_summary` ghi ID, bitrate, số DAQ list có ID riêng và các ghi chú. Bỏ tích → mở khoá, trả giá trị đã cất. Nếu `initial.use_a2l_can` và `a2l_can` có sẵn thì mở dialog với checkbox đã tích.

- [x] **Step 1: Viết test (fail)** (dùng fixtures `qtbot`, `host`, `session` của `tests/ui`; dựng `XcpCanInfo` trực tiếp):
  - `test_checkbox_xam_khi_khong_co_a2l_can`: `isEnabled() is False`, `isChecked() is False`, tooltip không rỗng.
  - `test_tich_khoa_o_va_hien_gia_tri_a2l`: `a2l_can` có master 0x6A0, slave 0x6A1, 500000 → sau khi tích `cro_edit.text()=="0x6A0"`, `dto_edit.text()=="0x6A1"`, `cro_edit.isEnabled() is False`, summary chứa `"0x6A1"`.
  - `test_bo_tich_tra_lai_gia_tri_tay`: gõ `cro_edit` = `0x700`, tích rồi bỏ tích → `cro_edit.text()=="0x700"` và ô mở khoá.
  - `test_build_config_giu_gia_tri_tay_va_co_use_a2l_can`: đang tích → `cfg.cro_id==0x700` (tay), `cfg.use_a2l_can is True`.
  - `test_bitrate_a2l_ngoai_combo_van_hien_dung`: `baudrate=250000`/`83333` (không có trong combo) → ô bitrate hiển thị giá trị đó, `build_config().bitrate` vẫn là giá trị tay.
  - `test_custom_bit_timing_dang_bat_co_canh_bao`: `initial.custom_bit_timing=True` + tích → summary có cảnh báo timing thủ công.
  - `test_mo_lai_voi_initial_use_a2l_can`: `initial.use_a2l_can=True` + có `a2l_can` → checkbox đã tích; không có `a2l_can` → bỏ tích và `build_config().use_a2l_can is False`.
- [x] **Step 2:** `python -m pytest tests/ui/test_connect_flow.py -v` → test mới FAIL.
- [x] **Step 3:** Cài đặt checkbox, cất/khôi phục giá trị tay trong một chỗ (`_manual_snapshot`), tái dùng `_sync_bitrate_controls`/`_recompute_timing` sẵn có; `MainWindow` truyền `can_info`. Viết mục ngắn vào `USER_MANUAL.md`.
- [x] **Step 4:** `python -m pytest tests/ui -q`, rồi `python -m pytest -q` → PASS. Chạy thử app với `FakeSession` và nhờ người dùng chụp ảnh dialog nếu cần xác nhận hiển thị (giao diện native không tự chụp — xem ghi chú của người dùng).
- [x] **Step 5: Commit** — `git add src/xcptool/ui/device_dialog.py src/xcptool/ui/main_window.py USER_MANUAL.md tests/ui/test_connect_flow.py` · `feat(ui): checkbox Config CAN from A2L trong dialog Connect`

---

## Tự kiểm tra (đã chạy)

- **Phủ spec:** §3.1→T1; §3.2→T2, T3; §3.3→T4; §3.4→T5 (phần `fake.py:737` bỏ có chủ ý, ghi ở Global Constraints); §4.1→T7; §4.2→T8; §4.3→T9; §4.4→T10; §5 (xử lý lỗi)→T1, T6, T9, T10; §6 (kiểm thử)→mỗi task; §7 (thứ tự)→T1–T6 = phần 1, T7–T10 = phần 2.
- **Nhất quán tên/kiểu:** `daq_can_ids` (tuple cặp ở `BusConfig`, `dict[int,int]` ở `SlaveConfig`), `rx_ids`, `daq_can_id_of`, `route_key`/`RouteKey`, `route_of`, `XcpCanInfo.daq_list_ids`, `apply_a2l_can`, `use_a2l_can` dùng thống nhất ở mọi task.
- **Review Focus** đã gắn vào test: mục 1–2→T3; 3→T1, T6; 4→T4; 5→T8, T9, T10.
