/*----------------------------------------------------------------------------
| File:   cal_types.h
|
| Description:
|   Complex types (structs) used as calibration parameter types.
|   Must be included before CalData_t is defined in cal_data.h.
|
|   Add new struct types here when a calibration parameter group
|   is better expressed as a named struct than as separate scalars.
----------------------------------------------------------------------------*/

#ifndef CAL_TYPES_H
#define CAL_TYPES_H

#include "Ifx_Types.h"

/* ============================================================
 * PidConfig_t — PID controller parameters
 * ============================================================ */
typedef struct
{
    float32 kp;        /* Proportional gain                    */
    float32 ki;        /* Integral gain                        */
    float32 kd;        /* Derivative gain                      */
    float32 outMin;    /* Output clamp — lower bound           */
    float32 outMax;    /* Output clamp — upper bound           */
} PidConfig_t;

/* ============================================================
 * FilterConfig_t — first-order low-pass filter
 * ============================================================ */
typedef struct
{
    float32 cutoffHz;  /* Cutoff frequency in Hz               */
    boolean enabled;   /* TRUE = filter active                 */
    uint8   _pad[3];   /* Explicit padding — keeps size a multiple of 4 */
} FilterConfig_t;

/* ============================================================
 * RampConfig_t — rate limiter / ramp generator
 * ============================================================ */
typedef struct
{
    float32 rateUp;    /* Maximum rising  rate  (units/s)      */
    float32 rateDown;  /* Maximum falling rate  (units/s)      */
} RampConfig_t;

/* ============================================================
 * AdcCal_t — two-point ADC linearisation
 * ============================================================ */
typedef struct
{
    uint16 rawLow;     /* Raw ADC count at the low  reference  */
    uint16 rawHigh;    /* Raw ADC count at the high reference  */
    float32 refLow;    /* Physical value at the low  reference */
    float32 refHigh;   /* Physical value at the high reference */
} AdcCal_t;

#endif /* CAL_TYPES_H */
