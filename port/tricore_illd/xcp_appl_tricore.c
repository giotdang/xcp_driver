/*----------------------------------------------------------------------------
| File:   xcp_appl_tricore.c
|
| Description:
|   XCP application callbacks for Infineon AURIX TriCore + iLLD.
|   Implements the ApplXcp* hooks called by XcpBasic.c.
|
|   ApplXcpGetPointer   — logical address -> C pointer, with cal page remapping
|   ApplXcpGetTimestamp — STM0 hardware timestamp for DAQ
|   ApplXcpGetCalPage   — report current page to XCP master
|   ApplXcpSetCalPage   — switch ECU and/or XCP page
|   ApplXcpCopyCalPage  — copy reference (ROM) -> working (RAM)
|   ApplXcpCalibrationWrite — write with ROM write-protection
|   ApplXcpCalibrationRead  — read from active page
|
|   Calibration page state and XcpCal_* functions live in xcp_cal_tricore.c.
|   This file only contains the XcpBasic.c-facing callbacks.
----------------------------------------------------------------------------*/

#include "XcpBasic.h"
#include "port/tricore_illd/xcp_tricore.h"
#include "port/tricore_illd/xcp_cal_tricore.h"
#include "app/cal_data.h"

#include "IfxStm.h"
#include <string.h>

/* ============================================================
 * g_xcpIsrState
 * Saved ICR.IE between XcpInterruptDisable / XcpInterruptEnable.
 * Declared extern in xcp_tricore.h, defined here.
 * ============================================================ */
boolean g_xcpIsrState = FALSE;

/* ============================================================
 * ApplXcpGetPointer
 *
 * Converts an XCP logical address to a C pointer.
 * When XCP master is on the WORKING page and the address falls
 * in the calibration ROM region, redirect to the mirrored RAM:
 *
 *   RAM addr = addr - XCP_CAL_ROM_BASE + XCP_CAL_RAM_BASE
 *
 * All other addresses pass through unchanged (flat 32-bit space).
 * ============================================================ */
uint8 *ApplXcpGetPointer(uint8 addr_ext, uint32 addr)
{
    (void)addr_ext;

    if (XcpCal_GetXcpPage() == XCP_PAGE_WORKING)
    {
        if ((addr >= XCP_CAL_ROM_BASE) &&
            (addr <  XCP_CAL_ROM_BASE + XCP_CAL_SIZE))
        {
            return (uint8 *)(Ifx_AddressValue)(XCP_CAL_RAM_BASE + (addr - XCP_CAL_ROM_BASE));
        }
    }

    return (uint8 *)(Ifx_AddressValue)addr;
}

/* ============================================================
 * ApplXcpGetTimestamp
 * STM0 lower 32-bit counter at fSPB (~100 MHz on TC2xx -> 10 ns/tick).
 * ============================================================ */
#if defined(XCP_ENABLE_DAQ_TIMESTAMP)
XcpDaqTimestampType ApplXcpGetTimestamp(void)
{
    return (XcpDaqTimestampType)IfxStm_getLower(&MODULE_STM0);
}
#endif

/* ============================================================
 * Calibration page callbacks
 * ============================================================ */
#if defined(XCP_ENABLE_CALIBRATION_PAGE)

uint8 ApplXcpGetCalPage(uint8 segment, uint8 mode)
{
    (void)segment;
    return (mode & 0x01U) ? (uint8)XcpCal_GetEcuPage()
                          : (uint8)XcpCal_GetXcpPage();
}

uint8 ApplXcpSetCalPage(uint8 segment, uint8 page, uint8 mode)
{
    if (segment != XCP_SEGMENT_ID) return (uint8)CRC_OUT_OF_RANGE;
    if (page >= XCP_NUM_PAGES)     return (uint8)CRC_PAGE_NOT_VALID;

    if (mode & 0x01U) XcpCal_SetEcuPage(page);
    if (mode & 0x02U) XcpCal_SetXcpPage(page);

    return 0U;
}

#if defined(XCP_ENABLE_PAGE_COPY)
uint8 ApplXcpCopyCalPage(uint8 srcSeg,  uint8 srcPage,
                         uint8 destSeg, uint8 destPage)
{
    if ((srcSeg != XCP_SEGMENT_ID) || (destSeg != XCP_SEGMENT_ID))
        return (uint8)CRC_OUT_OF_RANGE;

    if ((srcPage == XCP_PAGE_REFERENCE) && (destPage == XCP_PAGE_WORKING))
    {
        XcpCal_InitWorkingPage();
        return 0U;
    }

    return (uint8)CRC_OUT_OF_RANGE;   /* RAM->ROM requires flash programming */
}
#endif

#endif /* XCP_ENABLE_CALIBRATION_PAGE */

/* ============================================================
 * Calibration memory access with write protection
 * ============================================================ */
#if defined(XCP_ENABLE_CALIBRATION_MEM_ACCESS_BY_APPL)

uint8 ApplXcpCalibrationWrite(uint8 *addr, uint8 size, const uint8 *data)
{
    const uint32 physAddr = (uint32)(Ifx_AddressValue)addr;

    /* Reject writes to ROM — catches reference-page access where
     * ApplXcpGetPointer returned the ROM address unchanged. */
    if ((physAddr >= XCP_CAL_ROM_BASE) &&
        (physAddr <  XCP_CAL_ROM_BASE + XCP_CAL_SIZE))
    {
        return (uint8)XCP_CMD_ERROR;   /* ERR_WRITE_PROTECTED to CANape */
    }

    memcpy(addr, data, (uint32)size);
    return (uint8)XCP_CMD_OK;
}

uint8 ApplXcpCalibrationRead(uint8 *addr, uint8 size, uint8 *data)
{
    memcpy(data, addr, (uint32)size);
    return (uint8)XCP_CMD_OK;
}

#endif /* XCP_ENABLE_CALIBRATION_MEM_ACCESS_BY_APPL */
