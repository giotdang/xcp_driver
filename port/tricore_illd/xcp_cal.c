/*----------------------------------------------------------------------------
| File:   xcp_cal.c
|
| Description:
|   Calibration page state management for XCP.
|   Implements the XcpCal_* API declared in xcp_cal.h.
|
|   Responsibilities:
|     - Track which page ECU and XCP master are currently using
|     - Initialise the working (RAM) page from the reference (Flash) page
|     - Switch pCal so application code reads from the correct page
|
|   Callbacks that use this state (Xcp_GetCalPage, Xcp_SetCalPage,
|   Xcp_GetPointer) live in xcp_appl.c and access page state through
|   XcpCal_Get/Set functions.
----------------------------------------------------------------------------*/

#include "port/tricore_illd/xcp_cal.h"
#include "app/cal_data.h"

#include <string.h>   /* memcpy */

/* ============================================================
 * Page state
 * Both start at REFERENCE so the ECU boots from ROM and CANape
 * must explicitly switch to WORKING before writing.
 * ============================================================ */
static uint8 xcpCalPage_Ecu = XCP_PAGE_REFERENCE;
static uint8 xcpCalPage_Xcp = XCP_PAGE_REFERENCE;

/* ============================================================
 * XcpCal_InitWorkingPage
 * Copy reference (ROM) -> working (RAM).
 * Call once at startup before enabling XCP or switching page.
 * ============================================================ */
void XcpCal_InitWorkingPage(void)
{
    memcpy((void *)XCP_CAL_RAM_BASE,
           (const void *)XCP_CAL_ROM_BASE,
           XCP_CAL_SIZE);
}

/* ============================================================
 * Page accessors
 * ============================================================ */
uint8 XcpCal_GetEcuPage(void) { return xcpCalPage_Ecu; }
uint8 XcpCal_GetXcpPage(void) { return xcpCalPage_Xcp; }

void XcpCal_SetXcpPage(uint8 page) { xcpCalPage_Xcp = page; }

void XcpCal_SetEcuPage(uint8 page)
{
    xcpCalPage_Ecu = page;
    /* Switch application pointer so ECU reads from the new page immediately */
    pCal = (page == XCP_PAGE_WORKING) ? &calRAM : &calROM;
}
