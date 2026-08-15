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
|   - Struct-typed fields (e.g. PidTelemetry_t, meas_types.h) are still
|     measured member-by-member: give each member its own MEASUREMENT
|     record in the A2L (named "<field>_<member>"), since XCP has no
|     concept of a struct-shaped DTO. Arrays are the opposite — describe
|     them as ONE MEASUREMENT with MATRIX_DIM; CANape splits an array
|     across as many ODT entries as it needs on its own.
|   - tools/sync_a2l_addresses.py parses this table directly (regex over
|     MEAS_PARAM/MEAS_ARRAY lines) to compute each field's offset the same
|     way the compiler lays out MeasData_t — natural alignment, no packing
|     pragma. Only fixed-width scalar types plus the struct types listed
|     in that script's STRUCT_TYPES registry are recognised; add a struct
|     type to both meas_types.h and STRUCT_TYPES together, kept in sync.
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
#include "app/meas_types.h"

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
    MEAS_PARAM( float32, coolantTempC,    0.0f ) \
\
    /* ------------------------------------------------------------------ */ \
    /* 10 ms raster — complex-type scenarios (struct, array)              */ \
    /* ------------------------------------------------------------------ */ \
    MEAS_PARAM( PidTelemetry_t, speedPidTelemetry, {0}                        ) \
    MEAS_ARRAY( float32,        torqueSamples,    4, 0.0f,0.0f,0.0f,0.0f      )
    /* ---- Add new measurement signals above this line ---- */

/* clang-format on */

#endif /* MEAS_PARAMS_H */
