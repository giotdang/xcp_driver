/*----------------------------------------------------------------------------
| Project: XCP_Delivery
|
|  Description:   XCP Configuration for Infineon AURIX TriCore + iLLD
|                 Target: TC2xx (MultiCAN) / adaptable to TC3xx (MCMCAN)
|
|-----------------------------------------------------------------------------
| Copyright (c) by Vector Informatik GmbH.  All rights reserved.
----------------------------------------------------------------------------*/

#if !defined(__XCP_CFG_H__)
#define __XCP_CFG_H__

/* vuint8 / vuint16 / vuint32 / vsint* — must be visible before XcpBasic.h
 * expands its own type usages. */
#include "port/tricore_illd/xcp_types.h"

/* ============================================================
 * CPU / Memory model
 * TriCore is little-endian with a flat 32-bit address space.
 * ============================================================ */
#define XCP_CPUTYPE_LITTLEENDIAN
#define XCP_ENABLE_UNALIGNED_MEM_ACCESS   /* TriCore supports unaligned word access */

/* ============================================================
 * Protocol features
 * ============================================================ */
#define XCP_ENABLE_DAQ
#define XCP_ENABLE_SEND_QUEUE
#define XCP_ENABLE_PARAMETER_CHECK
#define XCP_ENABLE_COMM_MODE_INFO
#define XCP_ENABLE_DAQ_PROCESSOR_INFO
#define XCP_ENABLE_DAQ_RESOLUTION_INFO
#define XCP_ENABLE_DAQ_OVERRUN_INDICATION

/* ============================================================
 * Buffer sizing
 * kXcpDaqMemSize: total bytes shared across all DAQ lists/ODTs.
 * Increase if CANape reports "insufficient memory" during DAQ setup.
 * ============================================================ */
#define kXcpMaxCTO      8U      /* Command Transfer Object (host → ECU) */
#define kXcpMaxDTO      8U      /* Data Transfer Object    (ECU → host, = CAN DLC) */
#define kXcpDaqMemSize  1024U   /* DAQ allocation pool in bytes */

/* ============================================================
 * DAQ Timestamp — STM0 lower 32-bit counter
 *
 * STM0 runs at fSPB (typically 100 MHz on TC2xx AURIX).
 *   1 tick = 10 ns  →  unit = DAQ_TIMESTAMP_UNIT_10NS, ticks-per-unit = 1
 *
 * If your fSPB differs, adjust kXcpDaqTimestampUnit accordingly:
 *   50 MHz  → DAQ_TIMESTAMP_UNIT_20NS  (not standard, use UNIT_10NS + ticks=2)
 *   200 MHz → DAQ_TIMESTAMP_UNIT_5NS   (not standard, use UNIT_10NS + ticks=1, note drift)
 * ============================================================ */
#define XCP_ENABLE_DAQ_TIMESTAMP
#define kXcpDaqTimestampSize   DAQ_TIMESTAMP_DWORD    /* 32-bit counter */
#define kXcpDaqTimestampUnit   DAQ_TIMESTAMP_UNIT_10NS
#define kXcpDaqTimestampTicks  1U

/* ============================================================
 * Calibration page switching
 * Page 0 = Working page (RAM)  — CANape downloads calibration here
 * Page 1 = Reference page (ROM) — golden/default values in flash
 *
 * Address remapping is handled in ApplXcpGetPointer (xcp_appl_tricore.c):
 * when XCP accesses the working page, ROM addresses are transparently
 * redirected to the mirrored RAM region — CANape needs no A2L changes.
 * ============================================================ */
#define XCP_ENABLE_CALIBRATION_PAGE
#define XCP_ENABLE_PAGE_COPY        /* enable COPY_CAL_PAGE command (ROM→RAM) */

/* ============================================================
 * Calibration memory write protection
 *
 * XCP_ENABLE_CALIBRATION_MEM_ACCESS_BY_APPL routes all calibration
 * DOWNLOAD / SHORT_DOWNLOAD through ApplXcpCalibrationWrite() instead
 * of letting XcpBasic write directly via the MTA pointer.
 *
 * This gives us a status return value: ApplXcpCalibrationWrite can
 * return XCP_CMD_ERROR to send a negative response to the host when
 * the physical destination address is in the ROM (reference page) range.
 *
 * Protection logic (implemented in xcp_appl_tricore.c):
 *   Working page  → ApplXcpGetPointer remaps ROM addr → RAM addr
 *                 → write to RAM succeeds (XCP_CMD_OK)
 *   Reference page → ApplXcpGetPointer returns ROM addr unchanged
 *                 → ApplXcpCalibrationWrite detects ROM range
 *                 → returns XCP_CMD_ERROR → CANape receives 0xFE (ERR_WRITE_PROTECTED)
 * ============================================================ */
#define XCP_ENABLE_CALIBRATION_MEM_ACCESS_BY_APPL

#endif /* __XCP_CFG_H__ */
