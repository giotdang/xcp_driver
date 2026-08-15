---
name: xcp-add-calibration-parameter
description: Step-by-step for adding a new calibration parameter to the XCP driver's CAL_PARAMS_TABLE (driver/app/cal_params.h) — scalar, array, or struct. Use when the user wants to add, extend, or wire up a calibration parameter.
---

1. Thêm type mới vào `driver/app/cal_types.h` nếu cần struct phức tạp
2. Thêm entry vào bảng `CAL_PARAMS_TABLE` trong `driver/app/cal_params.h`:
   ```c
   CAL_PARAM(float32, newParam, 1.0f)          // scalar
   CAL_ARRAY(float32, newTable, 8, {0})         // array
   CAL_PARAM(PidConfig_t, newController, {})    // struct
   ```
3. **KHÔNG** reorder hoặc xóa entry hiện có — ảnh hưởng địa chỉ A2L
4. Truy cập trong code: `CAL(newParam)` hoặc `newParam` (bare-name macro từ cal_access.h)
