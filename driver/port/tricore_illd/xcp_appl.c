/*----------------------------------------------------------------------------
| File:   xcp_appl.c
|
| Description:
|   XCP platform callbacks for Infineon AURIX TriCore + iLLD.
|   Implements the function-pointer callbacks required by Xcp_ConfigType.
|
|   These functions are platform-specific (TC2xx + iLLD) and should not
|   need to change unless the hardware or calibration page model changes.
|   The configuration object (Xcp_Config) that wires them together lives
|   in xcp_cfg.c — that is the file the application developer edits.
|
|   Xcp_GetPointer        — logical address -> C pointer, with cal page remapping
|   Xcp_GetTimestamp      — STM0 hardware timestamp for DAQ
|   Xcp_GetCalPage        — report current page to XCP master
|   Xcp_SetCalPage        — switch ECU and/or XCP page
|   Xcp_CopyCalPage       — copy reference (ROM) -> working (RAM)
|   Xcp_CalibrationWrite  — write with ROM write-protection
|   Xcp_CalibrationRead   — read from active page
|   Xcp_EnterCritical     — disable interrupts, save ICR state
|   Xcp_ExitCritical      — restore ICR state
|
|   Calibration page state and XcpCal_* functions live in xcp_cal.c.
----------------------------------------------------------------------------*/

#include "driver/Xcp_Handler.h"
#include "driver/port/tricore_illd/xcp_tricore.h"
#include "driver/port/tricore_illd/xcp_cal.h"
#include "driver/app/cal_data.h"

#include "IfxStm.h"
#include "IfxCpu.h"
#include <string.h>

/* ICR.IE value saved by Xcp_EnterCritical, restored by Xcp_ExitCritical. */
static boolean g_xcpIsrState = FALSE;

/* ============================================================
 * Xcp_GetPointer
 *
 * Converts an XCP logical address to a C pointer.
 * When the XCP master is on the WORKING page and the address falls
 * in the calibration ROM region, redirect to the mirrored RAM:
 *
 *   RAM addr = addr - XCP_CAL_ROM_BASE + XCP_CAL_RAM_BASE
 *
 * All other addresses pass through unchanged (flat 32-bit space).
 * ============================================================ */
uint8 *Xcp_GetPointer(uint8 addr_ext, uint32 addr)
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
 * Xcp_GetTimestamp
 * STM0 lower 32-bit counter at fSPB (~100 MHz on TC2xx -> 10 ns/tick).
 * ============================================================ */
#if defined(XCP_ENABLE_DAQ_TIMESTAMP)
uint32 Xcp_GetTimestamp(void)
{
    return (uint32)IfxStm_getLower(&MODULE_STM0);
}
#endif

/* ============================================================
 * Calibration page callbacks
 * ============================================================ */
#if defined(XCP_ENABLE_CALIBRATION_PAGE)

uint8 Xcp_GetCalPage(uint8 segment, uint8 mode)
{
    (void)segment;
    return (mode & 0x01U) ? (uint8)XcpCal_GetEcuPage()
                          : (uint8)XcpCal_GetXcpPage();
}

uint8 Xcp_SetCalPage(uint8 segment, uint8 page, uint8 mode)
{
    if (segment != XCP_SEGMENT_ID) return (uint8)CRC_OUT_OF_RANGE;
    if (page >= XCP_NUM_PAGES)     return (uint8)CRC_PAGE_NOT_VALID;

    if (mode & 0x01U) XcpCal_SetEcuPage(page);
    if (mode & 0x02U) XcpCal_SetXcpPage(page);

    return 0U;
}

#if defined(XCP_ENABLE_PAGE_COPY)
uint8 Xcp_CopyCalPage(uint8 srcSeg,  uint8 srcPage,
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

uint8 Xcp_CalibrationWrite(uint8 *addr, uint8 size, const uint8 *data)
{
    const uint32 physAddr = (uint32)(Ifx_AddressValue)addr;

    /* Reject writes to ROM — catches reference-page access where
     * Xcp_GetPointer returned the ROM address unchanged. */
    if ((physAddr >= XCP_CAL_ROM_BASE) &&
        (physAddr <  XCP_CAL_ROM_BASE + XCP_CAL_SIZE))
    {
        return (uint8)XCP_CMD_ERROR;   /* ERR_WRITE_PROTECTED to CANape */
    }

    memcpy(addr, data, (uint32)size);
    return (uint8)XCP_CMD_OK;
}

uint8 Xcp_CalibrationRead(uint8 *addr, uint8 size, uint8 *data)
{
    memcpy(data, addr, (uint32)size);
    return (uint8)XCP_CMD_OK;
}

#endif /* XCP_ENABLE_CALIBRATION_MEM_ACCESS_BY_APPL */

/* ============================================================
 * Critical section — disable/restore global interrupt enable
 * ============================================================ */
void Xcp_EnterCritical(void)
{
    g_xcpIsrState = IfxCpu_disableInterrupts();
}

void Xcp_ExitCritical(void)
{
    IfxCpu_restoreInterrupts(g_xcpIsrState);
}
