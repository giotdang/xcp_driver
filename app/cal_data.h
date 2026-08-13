/*----------------------------------------------------------------------------
| File:   cal_data.h
|
| Description:
|   Calibration data type and storage declarations.
|   CalData_t is generated automatically from cal_params.def.
|
|   Include cal_access.h (not this file) in application code.
----------------------------------------------------------------------------*/

#ifndef CAL_DATA_H
#define CAL_DATA_H

#include "Ifx_Types.h"
#include "app/cal_types.h"   /* PidConfig_t, FilterConfig_t, etc. */

/* ============================================================
 * Section placement attributes
 * ============================================================ */
#define CAL_ROM  __attribute__((section(".cal_rom")))
#define CAL_RAM  __attribute__((section(".cal_ram")))

/* ============================================================
 * CalData_t — generated from cal_params.def
 *
 *   CAL_PARAM(type, name, ...)  →  type name;
 *   CAL_ARRAY(type, name, size, ...) →  type name[size];
 * ============================================================ */
typedef struct
{
#define CAL_PARAM(type, name, ...)       type name;
#define CAL_ARRAY(type, name, size, ...) type name[size];
#include "app/cal_params.def"
#undef CAL_PARAM
#undef CAL_ARRAY
} CalData_t;

/* ============================================================
 * Storage declarations — defined in cal_data.c
 * ============================================================ */
extern const CalData_t  calROM;   /* reference page — Flash  */
extern       CalData_t  calRAM;   /* working page   — RAM    */
extern const CalData_t *pCal;     /* active page pointer     */

#endif /* CAL_DATA_H */
