/*----------------------------------------------------------------------------
| File:   cal_data.h
|
| Description:
|   Calibration data type and storage declarations.
|   CalData_t is generated automatically from CAL_PARAMS_TABLE (cal_params.h).
|
|   Include cal_access.h (not this file) in application code.
----------------------------------------------------------------------------*/

#ifndef CAL_DATA_H
#define CAL_DATA_H

#include "app/cal_params.h"   /* CAL_PARAMS_TABLE, cal_types.h, Ifx_Types.h */

/* ============================================================
 * Section placement attributes
 * ============================================================ */
#define CAL_ROM  __attribute__((section(".cal_rom")))
#define CAL_RAM  __attribute__((section(".cal_ram")))

/* ============================================================
 * CalData_t — generated from CAL_PARAMS_TABLE
 *
 *   CAL_PARAM(type, name, ...)       ->  type name;
 *   CAL_ARRAY(type, name, size, ...) ->  type name[size];
 * ============================================================ */
typedef struct
{
#define CAL_PARAM(type, name, ...)       type name;
#define CAL_ARRAY(type, name, size, ...) type name[size];
CAL_PARAMS_TABLE
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
