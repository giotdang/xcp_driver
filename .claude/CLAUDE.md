# XCP Driver — Project Guide

## Project Overview

XCP (Universal Measurement and Calibration Protocol) v1.0 slave implementation cho Infineon AURIX TriCore TC2xx, dựa trên **Vector Informatik XcpBasic v1.30.04** (refactored). Mục đích: cho phép công cụ đo lường/hiệu chỉnh (CANape, INCA) truy cập ECU qua CAN để đọc tín hiệu (DAQ) và ghi tham số hiệu chỉnh (CAL).

## Callback-based Transport Abstraction

Tất cả platform-specific calls đều đi qua `Xcp_ConfigType`. Config object cho TC2xx được định nghĩa trong `xcp_appl_tricore.c` và export qua `xcp_appl_tricore.h`.

## Calibration Page Model

```
REFERENCE PAGE (0x01): calROM — Flash, read-only, golden defaults
WORKING PAGE  (0x00): calRAM — RAM, CANape writes here

Startup: XcpCal_InitWorkingPage() → memcpy(calRAM, calROM)
ECU reads:   pCal->field  (pCal points to calROM or calRAM)
CANape xem:  XCP page (independent of ECU page)
Page switch: Xcp_SetCalPage() → XcpCal_SetEcuPage() / XcpCal_SetXcpPage()
```

**Address remapping**: `Xcp_GetPointer()` — khi XCP đang trỏ WORKING page và CANape gửi địa chỉ trong vùng ROM, hàm này tính offset và trả về địa chỉ RAM tương ứng. Đây là điểm cốt lõi giúp CANape "nhìn thấy" calRAM thông qua địa chỉ Flash.

## Disabled Features (chưa implement)

- STIM (stimulation / data injection)
- Block Upload / Block Download
- Flash Programming (PGM commands)
- Seed & Key
- Service Requests
- DAQ Prescaler
- DAQ Resume Mode
- Event sending (XCP_ENABLE_SEND_EVENT)

## Linker Script Requirements

```
.cal_rom : { *(.cal_rom) }  → exports: _cal_rom_start, _cal_rom_size
.cal_ram (NOLOAD) : { *(.cal_ram) }  → exports: _cal_ram_start
```

`XcpCal_InitWorkingPage()` dùng 3 symbols này để tính base address và size.

## Concurrency Model

- **RX ISR** (priority 60): enqueue frame vào ring buffer (4 slots), KHÔNG xử lý command
- **Main loop** (`Xcp_Background`): dequeue và gọi `Xcp_Command()` — không có context switch issue
- **TX ISR** (priority 59): `Xcp_SendCallBack()` → drain send queue
- **Critical section**: `EnterCritical/ExitCritical` callbacks dùng `IfxCpu_disableInterrupts()` (disable toàn bộ CPU interrupt)
- **Ring buffer thread safety**: single-producer (ISR) / single-consumer (Background); `g_xcpRxQueueWp` là `volatile`; data write trước khi advance pointer

## CANape / INCA Setup

| Setting | Value |
|---------|-------|
| Protocol | XCP on CAN |
| Bitrate | 500 kbps |
| CMD (host→ECU) CAN ID | 0x7E0 |
| RES/DAQ (ECU→host) CAN ID | 0x7E1 |
| Frame format | Standard 11-bit |
| Max CTO | 8 bytes |
| Max DTO | 8 bytes |
| A2L file | Generate từ cal_params.h |

## Persistent Memory — dùng agentmemory thay vì file .md

Project này đã cài đặt [agentmemory](https://github.com/rohitg00/agentmemory) (MCP server `agentmemory`, đã kết nối trong Claude Code ở user scope) làm nơi lưu trữ memory xuyên suốt các phiên làm việc, **thay thế** cho hệ thống file `memory/*.md` mặc định.

- **Ưu tiên dùng agentmemory MCP tools** (`memory_save`, `memory_recall`, `memory_smart_search`, v.v.) để lưu và truy xuất context về project này — không tạo thêm file `.md` mới trong hệ thống auto-memory nội bộ.
- Nếu MCP tools của `agentmemory` chưa nạp trong phiên hiện tại (do server mới kết nối giữa phiên), có thể gọi trực tiếp REST API tại `http://localhost:3111`:
  - Lưu: `POST /agentmemory/remember` — body `{content, type, concepts: [...], files: [...], project: "xcp_driver"}` (**`concepts` và `files` phải là mảng**, không phải chuỗi phân tách dấu phẩy).
  - Truy xuất: `POST /agentmemory/search` — body `{query, limit}`.
- Server `agentmemory` chạy nền, cần được khởi động thủ công (lệnh `agentmemory` trong terminal) sau mỗi lần khởi động máy — không tự chạy cùng hệ thống.
- Các file `memory/*.md` cũ (ở `~/.claude/projects/.../memory/` và bản copy tại `.claude/memory/` trong repo) vẫn được **giữ nguyên làm backup**, không xoá — nhưng không phải nguồn memory chính thức nữa.
