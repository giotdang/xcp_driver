/*----------------------------------------------------------------------------
| File:   xcp_cal_tricore.h
|
| Description:
|   Calibration page configuration and ECU-side access API for
|   XCP on AURIX TriCore.
|
|   Concept — ROM-shadow in RAM:
|     The A2L file (used by CANape/INCA) contains the FLASH addresses of
|     calibration parameters.  A RAM region of identical layout is reserved
|     as the "working page".  ApplXcpGetPointer transparently redirects
|     any XCP access to a ROM address into the mirrored RAM region, so the
|     calibration tool needs no knowledge of the RAM layout.
|
|   Page numbering (XCP spec convention):
|     XCP_PAGE_WORKING   (0) — RAM copy, CANape writes calibration here
|     XCP_PAGE_REFERENCE (1) — Flash, golden / default values
|
|   Linker script requirements:
|     Two symbols must be exported from the linker script so the C code
|     can compute the ROM→RAM address offset at runtime:
|
|     HighTec GCC (.ld):
|       _cal_rom_start = .;   /* first byte of .cal_rom section in flash *\/
|       _cal_rom_size  = SIZEOF(.cal_rom);
|       _cal_ram_start = .;   /* first byte of .cal_ram section in RAM   *\/
|
|     Tasking (.lsl) — use "symbol" keyword to export section start/size.
|
|   Calibration variable definition (application code):
|
|     // myapp_cal.h
|     #define CAL_ROM  __attribute__((section(".cal_rom")))
|     #define CAL_RAM  __attribute__((section(".cal_ram")))
|
|     typedef struct { float throttleGain; float brakeLimit; } CalData_t;
|
|     // myapp_cal.c (definition)
|     const CalData_t calROM CAL_ROM = { .throttleGain=1.0f, .brakeLimit=0.8f };
|     CalData_t       calRAM CAL_RAM;   // initialized by XcpCal_InitWorkingPage()
|
|     // ECU application always reads via this pointer
|     const CalData_t *pCal = &calROM;  // starts on reference page
|
|   Switching the ECU page:
|     Call XcpCal_SetEcuPage(XCP_PAGE_WORKING) to point pCal → calRAM.
|     The XCP page (what CANape reads/writes) is tracked separately.
----------------------------------------------------------------------------*/

#ifndef XCP_CAL_TRICORE_H
#define XCP_CAL_TRICORE_H

#include "Ifx_Types.h"

/* ============================================================
 * Page identifiers (must match ApplXcpGetCalPage / SetCalPage)
 * ============================================================ */
#define XCP_PAGE_WORKING    0U   /* RAM  — writable, transient        */
#define XCP_PAGE_REFERENCE  1U   /* Flash — read-only, persistent     */
#define XCP_NUM_PAGES       2U

/* Single segment (one contiguous calibration region) */
#define XCP_NUM_SEGMENTS    1U
#define XCP_SEGMENT_ID      0U

/* ============================================================
 * Calibration memory region
 *
 * These are resolved at link time from linker-script symbols.
 * If your toolchain uses different symbol naming, update here.
 *
 * The compiler will warn "declared but never defined" for the
 * extern arrays — that is expected; they are linker-defined.
 * ============================================================ */

/* Linker-exported symbols — defined in the .ld / .lsl script */
extern uint8 _cal_rom_start[];   /* start of .cal_rom section in flash */
extern uint8 _cal_rom_size[];    /* size  of .cal_rom section (bytes)  */
extern uint8 _cal_ram_start[];   /* start of .cal_ram section in RAM   */

/* Convenience accessors */
#define XCP_CAL_ROM_BASE    ((uint32)(Ifx_AddressValue)_cal_rom_start)
#define XCP_CAL_SIZE        ((uint32)(Ifx_AddressValue)_cal_rom_size)
#define XCP_CAL_RAM_BASE    ((uint32)(Ifx_AddressValue)_cal_ram_start)

/* ============================================================
 * Public API — called from xcp_appl_tricore.c and application
 * ============================================================ */

/* Copy reference page (ROM) → working page (RAM).
 * Must be called once before the working page is used.
 * Safe to call at any time; XCP master can trigger it via COPY_CAL_PAGE. */
void XcpCal_InitWorkingPage(void);

/* Switch the page that the ECU application reads from.
 * Updates the application-level calibration pointer.
 * page: XCP_PAGE_WORKING or XCP_PAGE_REFERENCE */
void XcpCal_SetEcuPage(uint8 page);

/* Return the page currently used by the ECU application. */
uint8 XcpCal_GetEcuPage(void);

/* Return the page currently used by the XCP master (CANape). */
uint8 XcpCal_GetXcpPage(void);

/* Set the page the XCP master reads/writes.
 * Affects address remapping in ApplXcpGetPointer. */
void XcpCal_SetXcpPage(uint8 page);

#endif /* XCP_CAL_TRICORE_H */
