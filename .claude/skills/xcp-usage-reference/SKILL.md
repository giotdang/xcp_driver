---
name: xcp-usage-reference
description: Public API function reference for the XCP driver (Xcp_Init, Xcp_Background, Xcp_Event, etc.) and how-tos for common tasks — adding a DAQ event, changing the CAN ID, increasing DAQ buffer size. Use when calling into or wiring up driver/Xcp_Handler.
---

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

## Common Tasks

### Thêm DAQ event mới
Gọi `Xcp_Event(eventId)` từ task/ISR. EventId do CANape assign khi config DAQ list.

### Đổi CAN ID
Sửa `XCP_CAN_TX_ID` và `XCP_CAN_RX_ID` trong `xcp_tricore.h`. Cập nhật A2L nếu thay đổi.

### Tăng số lượng DAQ signals
Tăng `kXcpDaqMemSize` trong `driver/xcp_cfg.h`. Rule of thumb: mỗi ODT entry cần ~5 bytes overhead.
