---
name: xcp-porting-guide
description: How to port this XCP driver to a new hardware platform (new port/ directory, Xcp_ConfigType callbacks, Xcp_Config object) without touching the protocol core. Use when targeting a chip/platform other than TC2xx.
---

Kiến trúc callback-based giúp porting đơn giản:

1. **Tạo thư mục port mới** (e.g., `driver/port/tc3xx/` hoặc `driver/port/stm32/`)
2. **Implement `Xcp_ConfigType` callbacks:**
   - `Transmit(len, data)` — gửi CAN frame
   - `Receive(len, data)` — poll RX buffer, trả về 1 nếu có frame
   - `GetTimestamp()` — hardware timer tick
   - `EnterCritical()` / `ExitCritical()` — disable/restore interrupts
   - `GetPointer(addrExt, addr)` — address remapping
   - `CalibrationWrite/Read` — memory access với protection logic
   - `GetCalPage/SetCalPage/CopyCalPage` — page management
3. **Định nghĩa `Xcp_Config` object** và include `driver/Xcp_Handler.h`
4. **Giữ nguyên** `driver/Xcp_Handler.c/h`, `driver/xcp_def.h`, `driver/app/` — không cần sửa
