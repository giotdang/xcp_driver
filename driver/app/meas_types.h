/*----------------------------------------------------------------------------
| File:   meas_types.h
|
| Description:
|   Struct types for DAQ measurement signals that group more than one
|   related value. Mirrors app/cal_types.h (struct types for calibration
|   parameters), on the measurement side.
|
|   A struct-typed field here is still measured member-by-member over
|   XCP DAQ -- there is no "whole struct in one ODT entry" unless every
|   member combined fits within XCP_MAX_ODT_ENTRY_SIZE (7 bytes, or 6 if
|   XCP_ENABLE_DAQ_HDR_ODT_DAQ is enabled). PidTelemetry_t is 12 bytes,
|   so its A2L representation is 3 separate MEASUREMENT records
|   (<field>_error / <field>_integral / <field>_output in
|   examples/xcp_daq_example.a2l), each at
|     ECU_ADDRESS = measData base + offsetof(MeasData_t, <field>)
|                                  + offsetof(PidTelemetry_t, <member>)
|
|   tools/sync_a2l_addresses.py computes that automatically via its
|   STRUCT_TYPES registry -- keep that registry in sync with this file
|   whenever a struct type or its members change.
----------------------------------------------------------------------------*/

#ifndef MEAS_TYPES_H
#define MEAS_TYPES_H

#include "Ifx_Types.h"

/* ============================================================
 * PidTelemetry_t — internal state of a running PID loop, sampled
 * as one DAQ snapshot per cycle (see XcpDaqExample_Task_10ms()).
 * ============================================================ */
typedef struct
{
    float32 error;      /* setpoint - measured value, this cycle          */
    float32 integral;   /* accumulated error, clamped to the PID's output
                          * range (app/cal_access.h: speedPid.outMin/Max) */
    float32 output;     /* kp*error + integral, clamped to the same range */
} PidTelemetry_t;

#endif /* MEAS_TYPES_H */
