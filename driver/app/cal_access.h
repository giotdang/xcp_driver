/*----------------------------------------------------------------------------
| File:   cal_access.h
|
| Description:
|   Convenient access macros for calibration parameters.
|   This is the only header application code needs to include.
|
|   Usage examples:
|
|     // Scalar
|     float gain = systemGain;
|     if (featureEnabled) { ... }
|
|     // Array element
|     float torque = torqueMap[idx];
|
|     // Struct member
|     float kp = speedPid.kp;
|     float hi = pressureSensor.refHigh;
|
|   All macros expand to (pCal->name) so they:
|     - Always read from the currently active page (ROM or RAM)
|     - Switch automatically when XcpCal_SetEcuPage() is called
|     - Compile to a single struct-field load — zero overhead
|
|   To add a new parameter:
|     1. Add one line to CAL_PARAMS_TABLE in cal_params.h
|     2. Add one #define line here (mirror below)
----------------------------------------------------------------------------*/

#ifndef CAL_ACCESS_H
#define CAL_ACCESS_H

#include "driver/app/cal_data.h"

/* ============================================================
 * CAL(name) — generic zero-maintenance accessor
 *
 * Works for ANY field without adding a macro here.
 * Prefer when writing reusable or library code, or when a local
 * variable would clash with a bare-name macro.
 *
 *   float kp = CAL(speedPid).kp;
 *   float  v = CAL(torqueMap)[2];
 * ============================================================ */
#define CAL(name)  (pCal->name)

/* ============================================================
 * Bare-name macros — one per parameter in CAL_PARAMS_TABLE
 *
 * Scalars:   read like a plain variable      →  systemGain
 * Arrays:    index like a plain array        →  torqueMap[i]
 * Structs:   access members with dot         →  speedPid.kp
 *
 * All three work because the macro expands to (pCal->name),
 * and C allows (ptr->array)[i] and (ptr->st).field naturally.
 * ============================================================ */

/* --- Scalars --- */
#define systemGain        CAL(systemGain)
#define idleSpeedRpm      CAL(idleSpeedRpm)
#define voltageThreshold  CAL(voltageThreshold)
#define timeoutMs         CAL(timeoutMs)
#define adcScaleFactor    CAL(adcScaleFactor)
#define ctrlMode          CAL(ctrlMode)
#define tempOffsetDegC    CAL(tempOffsetDegC)
#define trimValue         CAL(trimValue)
#define featureEnabled    CAL(featureEnabled)

/* --- Arrays --- */
#define torqueMap         CAL(torqueMap)
#define adcCalPoints      CAL(adcCalPoints)
#define gainSchedule      CAL(gainSchedule)
#define tempCompTable     CAL(tempCompTable)

/* --- Structs --- */
#define speedPid          CAL(speedPid)
#define currentPid        CAL(currentPid)
#define sensorFilter      CAL(sensorFilter)
#define outputRamp        CAL(outputRamp)
#define pressureSensor    CAL(pressureSensor)

/* ---- Add new parameter macros above this line ---- */

#endif /* CAL_ACCESS_H */
