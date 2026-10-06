# Kế hoạch: bỏ ODT 0 rỗng bằng cách hạ timestamp cho chính DAQ list đó

> **Trạng thái:** chưa thực thi — lên kế hoạch ngày 2026-10-06, làm ở phiên sau.
> **Ngữ cảnh:** phát hiện khi rà soát đường đi DAQ list / ODT / event mapping.
> Hướng 2 (chẻ signal qua biên ODT) **không** nằm trong kế hoạch này.

**Mục tiêu:** `configure_daq()` không bao giờ phát `ALLOC_ODT_ENTRY` với
`ODT_ENTRIES_COUNT = 0`. Khi ngân sách byte khiến ODT đầu tiên rỗng, pack lại
chính DAQ list đó với timestamp tắt thay vì cấp phát một ODT rỗng.

---

## 1. Vấn đề

Với `MAX_DTO = 8`, header PID 1 B, timestamp 4 B thì ngân sách ODT 0 chỉ còn
3 B. Mọi signal ≥ 4 B (FLOAT32, ULONG) bị `pack_odts()` đẩy xuống ODT 1+, nên
khi **không có** signal nào ≤ 3 B, ODT 0 rỗng. `configure_daq()` vẫn cấp phát
nó:

```
ALLOC_DAQ(1) → ALLOC_ODT(daq=0, count=2) → ALLOC_ODT_ENTRY(daq=0, odt=0, count=0)
                                                                        ^^^^^^^
```

Hệ quả:

1. **Slave có quyền từ chối.** `ODT_ENTRIES_COUNT = 0` không cấp phát gì; trả
   `ERR_OUT_OF_RANGE` là hợp lệ và nhiều implementation làm đúng như vậy
   (XcpBasic: `XcpAllocOdtEntry()` chặn thẳng `odtEntryCount == 0`). Khi đó
   toàn bộ `start_daq` hỏng — người dùng không đo được signal 4 B nào.
2. **Timestamp vô dụng.** Theo ASAM, timestamp chỉ nằm ở ODT đầu của list mỗi
   chu kỳ. ODT đầu rỗng ⇒ 4 B timestamp không gắn với signal nào; mọi sample ở
   ODT 1+ có `timestamp_ns = 0`.
3. **Lãng phí cố định:** thêm một frame CAN mỗi chu kỳ mỗi list (~2–3 % tải bus
   ở 500 kbps / raster 10 ms), một PID (PID là 1 byte cho toàn ECU), một ODT
   trong bộ nhớ DAQ, và một slot trong send queue → tăng xác suất overrun.

Không dồn ngược lên được: bỏ ODT rỗng đi thì ODT kế tiếp trở thành ODT đầu và
phải chở timestamp — `1 + 4 + 4 = 9 > 8`. Vì vậy chỉ còn hai lối: **tắt
timestamp cho list đó** (kế hoạch này) hoặc **chẻ signal qua biên ODT** (để
sau).

## 2. Phạm vi

**Trong phạm vi**

- `configure_daq()` tự hạ timestamp cho đúng những list bị ODT 0 rỗng.
- Chặn tuyệt đối việc cấp phát ODT 0 entry ở mọi nhánh (dynamic lẫn static).
- `fakeslave` phản chiếu đúng ràng buộc của spec (hiện đang dễ dãi nên test
  không bắt được lỗi).
- Người dùng thấy được là timestamp đã bị hạ.

**Ngoài phạm vi (không làm, ghi để khỏi trôi)**

- Chẻ signal qua biên ODT và ghép lại ở decoder (hướng 2).
- Lan timestamp của ODT 0 sang các ODT cùng chu kỳ.
- `configure_daq_predefined()`: layout do caller cung cấp, không tự pack, không
  cấp phát gì — không đụng tới.
- Thay đổi ngữ nghĩa `pack_odts()`: nó vẫn được phép trả ODT 0 rỗng. Chính
  sách "không cấp phát ODT rỗng" thuộc về `configure_daq()`.

## 3. Ràng buộc chung

- **Spec-first.** Mọi quyết định neo vào ASAM MCD-1 XCP, không vào firmware
  trong `driver/`. XcpBasic chỉ được trích dẫn như một ví dụ cụ thể.
- **Hạ cấp theo từng list, không toàn cục.** List có ODT 0 không rỗng giữ
  nguyên timestamp.
- **`DaqListConfig.timestamp` là một YÊU CẦU, không phải mệnh lệnh.** Đã có
  tiền lệ: `effective_timestamp()` (`master/daq.py:148`) vốn đã hạ im lặng khi
  ECU không hỗ trợ timestamp. Kế hoạch này thêm một lý do hạ nữa, nhưng lần
  này **phải nói ra** (mục 4, Task 4).
- **Offset và bit mode phải đi cùng nhau.** Nếu pack lại mà quên cập nhật
  `eff_ts[i]`, `_write_and_start()` vẫn gửi mode `0x10` và tính
  `frame_offset` lệch 4 byte → decode ra rác mà không có lỗi nào. Đây là rủi
  ro số 1 của thay đổi này, phải có test riêng.
- **ECU có `TIMESTAMP_FIXED` thì không hạ được** (master không được phép tắt
  timestamp; fakeslave cũng đã từ chối đúng như vậy ở
  `_cmd_set_daq_list_mode`). Ca này phải báo lỗi rõ ràng, không được lặng lẽ
  gửi `ALLOC_ODT_ENTRY(0)`.

## 4. Kiến trúc

Toàn bộ quyết định nằm trong `configure_daq()`, giữa bước pack và bước cấp
phát — chỗ duy nhất biết đồng thời `fmt`, `max_dto`, `eff_ts` và `packed`:

```python
# master/daq.py, sau dòng 240 (packed = [...])
packed, eff_ts = _avoid_empty_first_odt(configs, packed, eff_ts, fmt, max_dto)
```

```python
def _avoid_empty_first_odt(configs, packed, eff_ts, fmt, max_dto):
    """ODT đầu rỗng là thứ KHÔNG cấp phát được: ALLOC_ODT_ENTRY cần số entry
    ≥ 1. Nguyên nhân luôn là timestamp ăn hết ngân sách ODT 0 — pack lại
    không timestamp cho đúng list đó thì mọi signal lại vừa, và còn bớt được
    một frame mỗi chu kỳ."""
    for i, odts in enumerate(packed):
        if odts and odts[0]:
            continue
        if not configs[i].signals:
            raise ValueError(f"DAQ list {i} không có signal nào")
        if not eff_ts[i]:
            raise ValueError(...)        # không thể xảy ra, chặn để khỏi im lặng
        if fmt.ts_always:
            raise UnsupportedByEcuError(
                "ECU buộc gắn timestamp (TIMESTAMP_FIXED) nên không tắt được, "
                f"mà MAX_DTO={max_dto}B chỉ chừa "
                f"{max_dto - fmt.header_len - fmt.ts_size}B cho ODT đầu — "
                "không signal nào đã chọn vừa chỗ đó. Cần chẻ entry qua biên "
                "ODT (chưa hỗ trợ) hoặc chọn signal nhỏ hơn.")
        packed[i] = pack_odts(configs[i].signals, False, max_dto, fmt=fmt)
        eff_ts[i] = False
    return packed, eff_ts
```

Lý do đặt ở đây chứ không trong `pack_odts()`: `pack_odts()` trả về mỗi
`list[list[DaqSignal]]`, không có đường báo ngược "tôi đã bỏ timestamp", mà
`configure_daq` lại cần biết để đặt bit mode và tính offset. Giữ `pack_odts()`
thuần như cũ cũng giữ nguyên bộ test đang có của nó.

**Chỉ ODT 0 mới có thể rỗng.** Đã kiểm lại thuật toán `pack_odts()`
(`master/daq.py:652`): nhánh ODT 1+ chỉ cắt sang ODT mới khi `used + size >
rest_budget`, mà `size > rest_budget` đã bị `ValueError` chặn từ đầu, nên
`cur` không bao giờ rỗng lúc append. Guard ở Task 3 vì vậy là lưới an toàn cho
tương lai, không phải để sửa lỗi đang có.

## 5. Các task

### Task 1 — `fakeslave` từ chối `ALLOC_ODT_ENTRY(count=0)` (bước đỏ)

**Files:** sửa `xcptool/src/xcptool/devtools/fakeslave.py`; test
`xcptool/tests/unit/test_fakeslave_dto.py` (hoặc file unit fakeslave tương ứng).

`_cmd_alloc_odt_entry()` hiện chỉ kiểm bounds của `daq` — thêm:

```python
count = data[5]
if count == 0:
    self._err(ErrCode.OUT_OF_RANGE)   # ALLOC_ODT_ENTRY cấp 0 entry là vô nghĩa
    return
```

- [ ] Test: fake trả `ERR_OUT_OF_RANGE` cho `ALLOC_ODT_ENTRY` count=0.
- [ ] Chạy `tests/integration/test_daq.py` → **mong đợi đỏ** ở
      `test_multiple_daq_lists_get_sequential_pids` (xem Task 2). Đỏ ở đây là
      bằng chứng lỗi có thật, không phải hồi quy.

### Task 2 — `configure_daq()` hạ timestamp thay vì cấp ODT rỗng (bước xanh)

**Files:** sửa `xcptool/src/xcptool/master/daq.py`; test mới
`xcptool/tests/unit/test_daq_configure.py`; sửa
`xcptool/tests/integration/test_daq.py`.

- [ ] **Viết test đỏ trước** (unit, dùng stub master ghi lại lệnh — không cần
      bus): một signal FLOAT32 4 B, `timestamp=True`, `max_dto=8`:
      - không có lệnh `alloc_odt_entry` nào mang count 0;
      - `alloc_odt(daq=0, count=1)` — một ODT, không phải hai;
      - `set_daq_list_mode` nhận mode `0x00` (bit4 tắt);
      - `pid_table` có đúng 1 entry, `odt_index == 0`,
        `has_timestamp is False`, `signals[0].frame_offset == 1`.
- [ ] Test hồi quy ca trộn (UWORD 2 B + FLOAT32 4 B): ODT 0 không rỗng ⇒
      **giữ nguyên** timestamp (mode `0x10`), ODT 0 chứa signal 2 B tại
      offset 5, ODT 1 chứa signal 4 B tại offset 1. Đây là lưới chặn cho rủi
      ro "quên cập nhật `eff_ts`" ở mục 3.
- [ ] Test `TIMESTAMP_FIXED`: caps có `timestamp_fixed=True` + chỉ signal 4 B
      → `UnsupportedByEcuError` với thông điệp nêu đúng ngân sách byte, và
      **không lệnh ALLOC nào được gửi** sau khi phát hiện.
- [ ] Test `DaqListConfig(signals=[])` → `ValueError`.
- [ ] Test CAN FD (`max_dto=64`): ODT 0 không bao giờ rỗng ⇒ fallback không
      kích hoạt, timestamp giữ nguyên.
- [ ] Hiện thực `_avoid_empty_first_odt()` theo mục 4 và gọi trong
      `configure_daq()` ngay sau khi tính `packed` (dòng ~240), **trước** cả
      nhánh static lẫn dynamic — nhánh static (`_reserve_static_lists`) chọn
      list theo `len(odts)` nên cũng được lợi.
- [ ] **Sửa test đang mã hoá hành vi cũ:**
      `tests/integration/test_daq.py::test_multiple_daq_lists_get_sequential_pids`
      (dòng ~295) có comment *"List 0: 1 signal 4B, TS=True → 2 ODT (ODT 0
      rỗng + ODT 1 với signal)"* và assert `pid_list0 == {0, 1}`. Sau fix,
      list 0 còn **1** ODT ⇒ `pid_list0 == {0}` và `pid_list1 == {1}`. Cập
      nhật cả comment lẫn assert, và nói rõ trong comment vì sao số ODT giảm.
- [ ] Cập nhật docstring `pack_odts()`: "ODT 0 CÓ THỂ RỖNG" vẫn đúng ở tầng
      này, thêm một câu trỏ sang `_avoid_empty_first_odt()` để người đọc sau
      không tưởng đó là thứ cấp phát được.

### Task 3 — Lưới an toàn: không cấp phát ODT rỗng ở bất cứ đâu

**Files:** sửa `xcptool/src/xcptool/master/daq.py`.

- [ ] Trong `_reserve_dynamic_lists()`, trước `alloc_odt_entry`, chặn
      `len(odt) == 0` bằng `ValueError` nêu rõ list/ODT — biến một vi phạm
      giao thức âm thầm thành lỗi nội bộ ồn ào nếu sau này `pack_odts()` đổi
      thuật toán.
- [ ] Test: gọi `_reserve_dynamic_lists` (hoặc `configure_daq` với `packed`
      dựng tay) có ODT rỗng ở giữa → `ValueError`, và **không** lệnh
      `alloc_odt_entry` count 0 nào được gửi.

### Task 4 — Cho người dùng thấy timestamp đã bị hạ

**Files:** sửa `xcptool/src/xcptool/master/daq.py`,
`xcptool/src/xcptool/session/real.py`.

Hạ im lặng là đúng về hành vi nhưng sai về thông tin: người dùng sẽ thắc mắc
vì sao trục thời gian là đồng hồ host.

- [ ] Thêm tham số tuỳ chọn `on_note: Callable[[str], None] | None = None` cho
      `configure_daq()` (cộng thêm, không phá chữ ký cũ nên không đụng test
      hiện có). Gọi khi hạ timestamp, thông điệp nêu số list và lý do.
- [ ] `RealSession.start_daq()` truyền `on_note` ghi vào trace buffer, theo
      đúng tiền lệ `connect()` đang dùng cho "CAN config từ A2L"
      (`session/real.py`, `self._trace.add("rx", 0, b"", "other", …)`). Người
      dùng thấy dòng này trong cửa sổ Trace.
- [ ] Test: `start_daq` với list chỉ có signal 4 B → trace có entry chứa
      "timestamp".
- [ ] *(Tuỳ chọn, nếu còn thời gian)* hiện luôn trên status bar của
      MeasurementView sau khi start. Cần một đường từ session lên UI — chỉ làm
      nếu không phải phát minh cơ chế mới.

### Task 5 — Tài liệu

**Files:** sửa `xcptool/USER_MANUAL.md` (mục 6).

- [ ] Một đoạn ngắn: trên CAN classic (DTO 8 byte), DAQ list chỉ gồm signal
      ≥ 4 byte sẽ **không có timestamp ECU** — trục thời gian của scope lúc đó
      là đồng hồ máy host (độ phân giải ~40 ms). Muốn có timestamp thì trộn
      thêm một signal ≤ 3 byte vào cùng raster, hoặc chuyển sang CAN FD.
      Nêu luôn rằng đây là ràng buộc số học của khung 8 byte, không phải giới
      hạn của ECU.

## 6. Nghiệm thu

- [ ] Chọn **chỉ** các signal FLOAT32 trong MeasurementView → `start_daq`
      chạy được đầu-cuối trên fakeslave, có sample giải mã đúng giá trị.
- [ ] Không có `ALLOC_ODT_ENTRY` count 0 nào trong trace của bất kỳ kịch bản
      nào.
- [ ] List trộn (có signal ≤ 3 B) giữ nguyên timestamp và offset như trước —
      không hồi quy.
- [ ] ECU `TIMESTAMP_FIXED` + chỉ signal 4 B → lỗi có thông điệp đọc hiểu
      được, không phải mã lỗi thô từ ECU.
- [ ] Toàn bộ `tests/unit`, `tests/ui`, `tests/integration` xanh (mốc hiện
      tại: 757 unit+ui, 121 integration).

## 7. Rủi ro & quyết định mở

| Rủi ro | Giảm nhẹ |
|---|---|
| Quên cập nhật `eff_ts` khi pack lại → offset lệch 4 B, decode ra rác mà không lỗi | Test ca trộn + test offset tường minh ở Task 2 |
| `TIMESTAMP_FIXED` không hạ được | Báo lỗi rõ ràng, nêu luôn hướng 2 là lối thoát |
| Người dùng tưởng vẫn còn timestamp | Task 4 (trace note) + Task 5 (tài liệu) |
| Test `test_multiple_daq_lists_get_sequential_pids` đang assert hành vi cũ | Đã nêu đích danh trong Task 2, kèm giá trị mong đợi mới |

**Quyết định mở (hỏi người dùng nếu thấy cấn lúc làm):** có nên cho phép ép
giữ timestamp và chấp nhận lỗi, thay vì tự hạ? Hiện thiết kế chọn **tự hạ**,
vì `timestamp` vốn đã là yêu cầu chứ không phải mệnh lệnh (`effective_timestamp()`)
và vì ODT 0 rỗng hôm nay cũng chẳng cho timestamp nào dùng được.
