/*----------------------------------------------------------------------------
| File:   cal_data.c
|
| Description:
|   Calibration data storage definitions.
|   calROM initialiser is generated automatically from cal_params.def.
----------------------------------------------------------------------------*/

#include "app/cal_data.h"

/* ============================================================
 * calROM — reference (golden) values placed in Flash
 *
 *   CAL_PARAM(type, name, ...)       →  .name = __VA_ARGS__,
 *   CAL_ARRAY(type, name, size, ...) →  .name = { __VA_ARGS__ },
 * ============================================================ */
const CalData_t calROM CAL_ROM =
{
#define CAL_PARAM(type, name, ...)       .name = __VA_ARGS__,
#define CAL_ARRAY(type, name, size, ...) .name = { __VA_ARGS__ },
#include "app/cal_params.def"
#undef CAL_PARAM
#undef CAL_ARRAY
};

/* ============================================================
 * calRAM — working copy (LMU RAM, no initialiser — NOLOAD section)
 * Filled by XcpCal_InitWorkingPage() at startup.
 * ============================================================ */
CalData_t calRAM CAL_RAM;

/* ============================================================
 * pCal — active page pointer, starts at reference (ROM)
 * ============================================================ */
const CalData_t *pCal = &calROM;
