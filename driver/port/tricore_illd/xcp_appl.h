/*----------------------------------------------------------------------------
| File:   xcp_appl.h
|
| Description:
|   Public declarations for the XCP platform callbacks (xcp_appl.c)
|   and the PostBuild configuration object (xcp_cfg.c).
|
|   Include this header in xcp_cfg.c to wire callbacks into Xcp_Config,
|   and in any startup file that calls Xcp_Init(&Xcp_Config).
----------------------------------------------------------------------------*/

#ifndef XCP_APPL_H
#define XCP_APPL_H

#include "driver/Xcp_Handler.h"

/* ---- Address / memory callbacks ---- */
uint8 *Xcp_GetPointer(uint8 addr_ext, uint32 addr);

#if defined(XCP_ENABLE_CALIBRATION_MEM_ACCESS_BY_APPL)
uint8 Xcp_CalibrationWrite(uint8 *addr, uint8 size, const uint8 *data);
uint8 Xcp_CalibrationRead(uint8 *addr, uint8 size, uint8 *data);
#endif

/* ---- Calibration page callbacks ---- */
#if defined(XCP_ENABLE_CALIBRATION_PAGE)
uint8 Xcp_GetCalPage(uint8 segment, uint8 mode);
uint8 Xcp_SetCalPage(uint8 segment, uint8 page, uint8 mode);
#if defined(XCP_ENABLE_PAGE_COPY)
uint8 Xcp_CopyCalPage(uint8 srcSeg, uint8 srcPage, uint8 destSeg, uint8 destPage);
#endif
#endif

/* ---- Timestamp ---- */
#if defined(XCP_ENABLE_DAQ_TIMESTAMP)
uint32 Xcp_GetTimestamp(void);
#endif

/* ---- Critical section ---- */
void Xcp_EnterCritical(void);
void Xcp_ExitCritical(void);

/* ---- PostBuild configuration object (defined in xcp_cfg.c) ---- */
extern const Xcp_ConfigType Xcp_Config;

#endif /* XCP_APPL_H */
