# XCP Driver — Project Guide

## Project Overview

XCP (Universal Measurement and Calibration Protocol) v1.0 slave implementation cho Infineon AURIX TriCore TC2xx, dựa trên **Vector Informatik XcpBasic v1.30.04** (refactored). Mục đích: cho phép công cụ đo lường/hiệu chỉnh (CANape, INCA) truy cập ECU qua CAN để đọc tín hiệu (DAQ) và ghi tham số hiệu chỉnh (CAL).

## Repository Layout

```
xcp_driver/
├── Xcp_Handler.c / Xcp_Handler.h        # Protocol layer (core XCP state machine)
├── xcp_cfg.h                             # Cấu hình compile-time features
├── xcp_def.h                             # XCP default settings — KHÔNG sửa trực tiếp
│
├── port/tricore_illd/                    # HAL port cho Infineon AURIX + iLLD
│   ├── xcp_types.h                      # Type aliases (vuint8→uint8, v.v.)
│   ├── xcp_tricore.h                    # Cấu hình phần cứng (CAN IDs, ISR, pins)
│   ├── xcp_can_tricore.c/h              # Transport layer CAN: ring buffer, ISR, Receive()
│   ├── xcp_appl_tricore.c/h             # Callbacks + Xcp_Config (PostBuild config object)
│   └── xcp_cal_tricore.c/h              # Quản lý trang hiệu chỉnh ROM/RAM
│
└── app/                                  # Calibration framework tầng ứng dụng
    ├── cal_types.h                       # Struct definitions (PidConfig_t, v.v.)
    ├── cal_params.h                      # Bảng tham số hiệu chỉnh (macro-driven)
    ├── cal_data.c / cal_data.h          # Lưu trữ calROM, calRAM, pCal
    └── cal_access.h                      # Macro truy cập CAL(name)
```

## Architecture (Phân lớp)

```
Startup code
  XcpCan_Init()          ← gọi trực tiếp bởi user
  XcpCal_InitWorkingPage()
  Xcp_Init(&Xcp_Config)  ← store ConfigPtr, init protocol state

Main loop
  Xcp_Background()
    → ConfigPtr->TransportLayer->Receive()  [poll RX ring buffer]
    → Xcp_Command()                         [process nếu có frame]
    → checksum background

CAN RX ISR (prio 60)
  XcpCan_RxIsr()
    → enqueue frame vào g_xcpRxQueue[]   ← KHÔNG xử lý command trực tiếp

CAN TX ISR (prio 59)
  XcpCan_TxIsr()
    → Xcp_SendCallBack()                 ← drain send queue
```

## Key Files & Responsibilities

| File | Role |
|------|------|
| `Xcp_Handler.c` (~3400 lines) | Core protocol: connect/disconnect, DOWNLOAD, UPLOAD, DAQ, SET_CAL_PAGE, COPY_CAL_PAGE, checksum, send queue |
| `Xcp_Handler.h` | Protocol constants (CC_*), packet structs (tXcpCto, tXcpDto), `Xcp_ConfigType`, `Xcp_TransportLayerType`, public API |
| `xcp_cfg.h` | **Điểm cấu hình chính**: bật/tắt features, kích thước buffer, timestamp config |
| `xcp_tricore.h` | CAN hardware: node ID, TX/RX message IDs (0x7E1/0x7E0), baudrate, ISR priority, GPIO pins |
| `xcp_can_tricore.c` | Ring buffer RX, RxIsr enqueue, TxIsr → Xcp_SendCallBack(), XcpCan_Receive() poll |
| `xcp_appl_tricore.c` | Callback implementations + định nghĩa `Xcp_Config` (PostBuild config object) |
| `xcp_cal_tricore.c/h` | Page state: xcpCalPage_Ecu, xcpCalPage_Xcp, XcpCal_InitWorkingPage() |
| `cal_params.h` | **Danh sách tham số hiệu chỉnh** — append-only, KHÔNG reorder |
| `cal_data.h/c` | calROM (Flash, const), calRAM (RAM, NOLOAD), pCal (active pointer) |
| `cal_access.h` | Macro CAL(name) = pCal->name |

## Callback-based Transport Abstraction

Tất cả platform-specific calls đều đi qua `Xcp_ConfigType`:

```c
typedef struct {
    void    (*Transmit)(vuint8 len, const BYTEPTR data);
    vuint8  (*Receive)(vuint8 *len, BYTEPTR data);   /* poll; 1 = frame available */
    vuint32 (*GetTimestamp)(void);
    void    (*EnterCritical)(void);
    void    (*ExitCritical)(void);
} Xcp_TransportLayerType;

typedef struct {
    const char                    *StationId;
    vuint8                         StationIdLength;
    const Xcp_TransportLayerType  *TransportLayer;
    BYTEPTR (*GetPointer)(vuint8 addrExt, vuint32 addr);
    vuint8  (*CalibrationWrite)(BYTEPTR addr, vuint8 size, const BYTEPTR data);
    vuint8  (*CalibrationRead)(BYTEPTR addr, vuint8 size, BYTEPTR data);
    vuint8  (*GetCalPage)(vuint8 segment, vuint8 mode);
    vuint8  (*SetCalPage)(vuint8 segment, vuint8 page, vuint8 mode);
    vuint8  (*CopyCalPage)(vuint8 srcSeg, vuint8 srcPage, vuint8 dstSeg, vuint8 dstPage);
} Xcp_ConfigType;
```

Config object cho TC2xx được định nghĩa trong `xcp_appl_tricore.c` và export qua `xcp_appl_tricore.h`.

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

## CAN Transport Configuration

| Parameter | Value | Nơi cấu hình |
|-----------|-------|-------------|
| CAN Module | MODULE_CAN | `xcp_tricore.h` |
| CAN Node | IfxMultican_NodeId_0 | `xcp_tricore.h` |
| Baudrate | 500 kbps | `xcp_tricore.h` |
| TX CAN ID | 0x7E1 (ECU→host) | `xcp_tricore.h` |
| RX CAN ID | 0x7E0 (host→ECU) | `xcp_tricore.h` |
| TX Msg Object | 0 | `xcp_tricore.h` |
| RX Msg Object | 1 | `xcp_tricore.h` |
| RX ISR Priority | 60 | `xcp_tricore.h` |
| TX ISR Priority | 59 | `xcp_tricore.h` |
| RX Ring Buffer | 4 frames | `xcp_can_tricore.c` |
| GPIO TX | P20.8 | `xcp_tricore.h` |
| GPIO RX | P20.7 (pull-up) | `xcp_tricore.h` |

## Enabled XCP Features (xcp_cfg.h)

- **DAQ** — Data Acquisition (đọc tín hiệu theo event)
- **DAQ Timestamps** — STM0 lower 32-bit @ 10 ns/tick (100 MHz)
- **Calibration Page Switching** — SET_CAL_PAGE, GET_CAL_PAGE, COPY_CAL_PAGE
- **Calibration Memory Access** — DOWNLOAD với write-protection (từ chối write vào Flash ROM)
- **Send Queue** — async DTO transmission (kXcpDaqMemSize = 1024 bytes)
- **Parameter Check** — validate input commands
- **Communication Mode Info** — GET_COMM_MODE_INFO
- **Unaligned Memory Access** — XCP_ENABLE_UNALIGNED_MEM_ACCESS
- **Little Endian** — XCP_CPUTYPE_LITTLEENDIAN

## Disabled Features (chưa implement)

- STIM (stimulation / data injection)
- Block Upload / Block Download
- Flash Programming (PGM commands)
- Seed & Key
- Service Requests
- DAQ Prescaler
- DAQ Resume Mode
- Event sending (XCP_ENABLE_SEND_EVENT)

## Public API

```c
/* Startup sequence */
XcpCan_Init();                   // transport layer init (độc lập)
XcpCal_InitWorkingPage();        // copy ROM→RAM (calibration init)
Xcp_Init(&Xcp_Config);           // protocol layer init với PostBuild config

/* Main loop */
void Xcp_Background(void);       // RX poll + command processing + checksum

/* Gọi từ TX ISR */
vuint8 Xcp_SendCallBack(void);   // drain send queue

/* Data acquisition (gọi từ task/ISR theo event) */
vuint8 Xcp_Event(vuint8 event);

/* Utilities */
vuint8 Xcp_GetState(void);
SessionStatusType Xcp_GetSessionStatus(void);
void Xcp_Disconnect(void);

/* Advanced — thường không cần gọi trực tiếp */
void  Xcp_Command(const vuint32 *pCommand);   /* public để test/sync mode */
void  Xcp_SendCrm(void);
void  Xcp_SetActiveTl(vuint8 MaxCto, vuint8 MaxDto, vuint8 ActiveTl);
vuint8 Xcp_GetActiveTl(void);
```

## Adding Calibration Parameters

1. Thêm type mới vào `app/cal_types.h` nếu cần struct phức tạp
2. Thêm entry vào bảng `CAL_PARAMS_TABLE` trong `app/cal_params.h`:
   ```c
   CAL_PARAM(float32, newParam, 1.0f)          // scalar
   CAL_ARRAY(float32, newTable, 8, {0})         // array
   CAL_PARAM(PidConfig_t, newController, {})    // struct
   ```
3. **KHÔNG** reorder hoặc xóa entry hiện có — ảnh hưởng địa chỉ A2L
4. Truy cập trong code: `CAL(newParam)` hoặc `newParam` (bare-name macro từ cal_access.h)

## Linker Script Requirements

```
.cal_rom : { *(.cal_rom) }  → exports: _cal_rom_start, _cal_rom_size
.cal_ram (NOLOAD) : { *(.cal_ram) }  → exports: _cal_ram_start
```

`XcpCal_InitWorkingPage()` dùng 3 symbols này để tính base address và size.

## Porting to Another Platform

Kiến trúc callback-based giúp porting đơn giản:

1. **Tạo thư mục port mới** (e.g., `port/tc3xx/` hoặc `port/stm32/`)
2. **Implement `Xcp_ConfigType` callbacks:**
   - `Transmit(len, data)` — gửi CAN frame
   - `Receive(len, data)` — poll RX buffer, trả về 1 nếu có frame
   - `GetTimestamp()` — hardware timer tick
   - `EnterCritical()` / `ExitCritical()` — disable/restore interrupts
   - `GetPointer(addrExt, addr)` — address remapping
   - `CalibrationWrite/Read` — memory access với protection logic
   - `GetCalPage/SetCalPage/CopyCalPage` — page management
3. **Định nghĩa `Xcp_Config` object** và include `Xcp_Handler.h`
4. **Giữ nguyên** `Xcp_Handler.c/h`, `xcp_def.h`, `app/` — không cần sửa

## Key Global State

```c
tXcpData xcp;           // Protocol state (session, DAQ lists, send queue)
const CalData_t  calROM;        // Reference page — Flash
CalData_t        calRAM;        // Working page — RAM (NOLOAD)
const CalData_t *pCal;          // Active page pointer (starts at &calROM)
```

## DAQ Buffer Sizing (xcp_cfg.h)

```c
#define kXcpMaxCTO      8     // Max Command Transfer Object size (= CAN DLC)
#define kXcpMaxDTO      8     // Max Data Transfer Object size (= CAN DLC)
#define kXcpDaqMemSize  1024  // Shared pool for DAQ list / ODT / ODT entry
```

DAQ memory pool được chia sẻ giữa: tXcpDaqList[], tXcpOdt[], pOdtEntryAddr[], pOdtEntrySize[]. Tăng `kXcpDaqMemSize` nếu cần nhiều DAQ lists hoặc ODT entries.

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

## Common Tasks

### Thêm DAQ event mới
Gọi `Xcp_Event(eventId)` từ task/ISR. EventId do CANape assign khi config DAQ list.

### Đổi CAN ID
Sửa `XCP_CAN_TX_ID` và `XCP_CAN_RX_ID` trong `xcp_tricore.h`. Cập nhật A2L nếu thay đổi.

### Tăng số lượng DAQ signals
Tăng `kXcpDaqMemSize` trong `xcp_cfg.h`. Rule of thumb: mỗi ODT entry cần ~5 bytes overhead.

## Persistent Memory — dùng agentmemory thay vì file .md

Project này đã cài đặt [agentmemory](https://github.com/rohitg00/agentmemory) (MCP server `agentmemory`, đã kết nối trong Claude Code ở user scope) làm nơi lưu trữ memory xuyên suốt các phiên làm việc, **thay thế** cho hệ thống file `memory/*.md` mặc định.

- **Ưu tiên dùng agentmemory MCP tools** (`memory_save`, `memory_recall`, `memory_smart_search`, v.v.) để lưu và truy xuất context về project này — không tạo thêm file `.md` mới trong hệ thống auto-memory nội bộ.
- Nếu MCP tools của `agentmemory` chưa nạp trong phiên hiện tại (do server mới kết nối giữa phiên), có thể gọi trực tiếp REST API tại `http://localhost:3111`:
  - Lưu: `POST /agentmemory/remember` — body `{content, type, concepts: [...], files: [...], project: "xcp_driver"}` (**`concepts` và `files` phải là mảng**, không phải chuỗi phân tách dấu phẩy).
  - Truy xuất: `POST /agentmemory/search` — body `{query, limit}`.
- Server `agentmemory` chạy nền, cần được khởi động thủ công (lệnh `agentmemory` trong terminal) sau mỗi lần khởi động máy — không tự chạy cùng hệ thống.
- Các file `memory/*.md` cũ (ở `~/.claude/projects/.../memory/` và bản copy tại `.claude/memory/` trong repo) vẫn được **giữ nguyên làm backup**, không xoá — nhưng không phải nguồn memory chính thức nữa.
