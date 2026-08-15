/*----------------------------------------------------------------------------
| File:   meas_params.h  —  DAQ measurement signal table
|
| How to add a new signal:
|   Scalar : MEAS_PARAM( type,         name,        default_value )
|   Array  : MEAS_ARRAY( element_type, name, size,  d0, d1, ...    )
|
| Rules:
|   - Only APPEND at the end; never reorder or remove.
|     Field order determines struct layout -> affects A2L symbol addresses,
|     same as CAL_PARAMS_TABLE (cal_params.h).
|   - Use iLLD fixed-width types: float32, sint8/16/32, uint8/16/32, boolean.
|   - Keep each field's byte size <= XCP_MAX_ODT_ENTRY_SIZE (7, or 6 if
|     XCP_ENABLE_DAQ_HDR_ODT_DAQ is enabled) if it must fit in one ODT
|     entry — split larger structs/arrays into multiple fields otherwise.
|   - tools/sync_a2l_addresses.py parses this table directly (regex over
|     MEAS_PARAM/MEAS_ARRAY lines) to compute each field's offset the same
|     way the compiler lays out MeasData_t — natural alignment, no packing
|     pragma. Only fixed-width scalar types are recognised; extend the
|     SIZE_ALIGN table in that script if you add a struct-typed field.
|
| Usage:
|   Define MEAS_PARAM / MEAS_ARRAY before expanding the table, then undef:
|
|     #define MEAS_PARAM(type, name, ...)        ...
|     #define MEAS_ARRAY(type, name, size, ...)  ...
|     MEAS_PARAMS_TABLE
|     #undef MEAS_PARAM
|     #undef MEAS_ARRAY
----------------------------------------------------------------------------*/

#ifndef MEAS_PARAMS_H
#define MEAS_PARAMS_H

#include "Ifx_Types.h"

/* clang-format off */

#define MEAS_PARAMS_TABLE \
\
    /* ------------------------------------------------------------------ */ \
    /* 10 ms raster (XCP_EVENT_10MS)                                      */ \
    /* ------------------------------------------------------------------ */ \
    MEAS_PARAM( uint32,  daqHeartbeat,    0U   ) \
    MEAS_PARAM( uint16,  engineRpm,       0U   ) \
    MEAS_PARAM( float32, vehicleSpeedKph, 0.0f ) \
\
    /* ------------------------------------------------------------------ */ \
    /* 100 ms raster (XCP_EVENT_100MS)                                    */ \
    /* ------------------------------------------------------------------ */ \
    MEAS_PARAM( float32, coolantTempC,    0.0f )
    /* ---- Add new measurement signals above this line ---- */

/* clang-format on */

#endif /* MEAS_PARAMS_H */
