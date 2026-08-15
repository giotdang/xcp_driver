/*----------------------------------------------------------------------------
| File:   cal_params.h  —  calibration parameter table
|
| How to add a new parameter:
|   Scalar / struct : CAL_PARAM( type,         name,         default_value )
|   Array           : CAL_ARRAY( element_type, name,  size,  d0, d1, ... )
|
| Rules:
|   - Only APPEND at the end; never reorder or remove.
|     Field order determines struct layout -> affects A2L symbol addresses.
|   - Use iLLD fixed-width types: float32, sint8/16/32, uint8/16/32, boolean.
|   - Struct defaults use C99 designated initialisers: { .field = value, ... }
|   - Array defaults are comma-separated values (no braces needed in macro).
|
| Usage:
|   Define CAL_PARAM / CAL_ARRAY before expanding the table, then undef:
|
|     #define CAL_PARAM(type, name, ...)        ...
|     #define CAL_ARRAY(type, name, size, ...)  ...
|     CAL_PARAMS_TABLE
|     #undef CAL_PARAM
|     #undef CAL_ARRAY
----------------------------------------------------------------------------*/

#ifndef CAL_PARAMS_H
#define CAL_PARAMS_H

#include "Ifx_Types.h"
#include "driver/app/cal_types.h"

/* clang-format off */

#define CAL_PARAMS_TABLE \
\
    /* ------------------------------------------------------------------ */ \
    /* Scalars — primitive types                                           */ \
    /* ------------------------------------------------------------------ */ \
    CAL_PARAM( float32,        systemGain,       1.0f                       ) \
    CAL_PARAM( float32,        idleSpeedRpm,     750.0f                     ) \
    CAL_PARAM( float32,        voltageThreshold, 12.5f                      ) \
    CAL_PARAM( uint32,         timeoutMs,        5000U                      ) \
    CAL_PARAM( uint16,         adcScaleFactor,   1000U                      ) \
    CAL_PARAM( uint8,          ctrlMode,         0U                         ) \
    CAL_PARAM( sint16,         tempOffsetDegC,   0                          ) \
    CAL_PARAM( sint8,          trimValue,        0                          ) \
    CAL_PARAM( boolean,        featureEnabled,   TRUE                       ) \
\
    /* ------------------------------------------------------------------ */ \
    /* Arrays — 1-D lookup tables and value sets                          */ \
    /* ------------------------------------------------------------------ */ \
    CAL_ARRAY( float32, torqueMap,     8, 0.0f, 12.5f, 25.0f, 37.5f, 50.0f, 65.0f, 80.0f, 95.0f ) \
    CAL_ARRAY( uint16,  adcCalPoints,  4, 0U, 1365U, 2730U, 4095U          ) \
    CAL_ARRAY( uint8,   gainSchedule,  4, 100U, 80U, 60U, 40U              ) \
    CAL_ARRAY( sint16,  tempCompTable, 6, -20, -10, 0, 10, 20, 30          ) \
\
    /* ------------------------------------------------------------------ */ \
    /* Structs — grouped calibration blocks                               */ \
    /* ------------------------------------------------------------------ */ \
    CAL_PARAM( PidConfig_t,    speedPid,       { .kp=1.0f,  .ki=0.05f, .kd=0.0f,  .outMin=-100.0f, .outMax= 100.0f } ) \
    CAL_PARAM( PidConfig_t,    currentPid,     { .kp=2.0f,  .ki=0.10f, .kd=0.01f, .outMin= -50.0f, .outMax=  50.0f } ) \
    CAL_PARAM( FilterConfig_t, sensorFilter,   { .cutoffHz=50.0f, .enabled=TRUE, ._pad={0U,0U,0U} }                   ) \
    CAL_PARAM( RampConfig_t,   outputRamp,     { .rateUp=10.0f, .rateDown=20.0f }                                     ) \
    CAL_PARAM( AdcCal_t,       pressureSensor, { .rawLow=102U, .rawHigh=921U, .refLow=0.0f, .refHigh=10.0f }         )
    /* ---- Add new parameters above this line ---- */

/* clang-format on */

#endif /* CAL_PARAMS_H */
