/*----------------------------------------------------------------------------
| File:   meas_data.h
|
| Description:
|   DAQ measurement signal storage — mirrors app/cal_data.h, but for
|   read-only telemetry instead of writable/paged calibration data.
|
|   MeasData_t is generated automatically from MEAS_PARAMS_TABLE
|   (meas_params.h), exactly like CalData_t is generated from
|   CAL_PARAMS_TABLE. There is no ROM/RAM page pair and no GetPointer
|   remapping here — DAQ only ever reads, so one plain RAM instance is
|   enough (see xcp_daq_example.h / the DAQ conversation for why
|   measurement variables don't need the calibration machinery).
|
|   Why one struct instead of N separate globals: every field's ECU
|   address is measData's base address + offsetof(MeasData_t, field),
|   computed by the compiler at build time. After a rebuild, only the
|   ONE base symbol ("measData") needs to be re-read from the linker
|   .map/.elf — see tools/sync_a2l_addresses.py — instead of resyncing
|   one address per signal.
|
|   Include meas_access.h (not this file) in application code.
----------------------------------------------------------------------------*/

#ifndef MEAS_DATA_H
#define MEAS_DATA_H

#include "app/meas_params.h"

/* ============================================================
 * MeasData_t — generated from MEAS_PARAMS_TABLE
 *
 *   MEAS_PARAM(type, name, ...)       ->  type name;
 *   MEAS_ARRAY(type, name, size, ...) ->  type name[size];
 * ============================================================ */
typedef struct
{
#define MEAS_PARAM(type, name, ...)       type name;
#define MEAS_ARRAY(type, name, size, ...) type name[size];
MEAS_PARAMS_TABLE
#undef MEAS_PARAM
#undef MEAS_ARRAY
} MeasData_t;

/* ============================================================
 * Storage declaration — defined in meas_data.c
 *
 * volatile: nothing in this translation unit reads these fields back —
 * the only "reader" is Xcp_Event() copying raw memory via the address
 * CANape configured in WRITE_DAQ, invisible to the compiler. Without
 * volatile, an optimizing compiler/LTO could treat writes to unread
 * fields as dead stores and drop them.
 * ============================================================ */
extern volatile MeasData_t measData;

#endif /* MEAS_DATA_H */
