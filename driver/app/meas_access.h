/*----------------------------------------------------------------------------
| File:   meas_access.h
|
| Description:
|   Convenient access macros for DAQ measurement signals.
|   Mirrors cal_access.h — this is the only header application code
|   needs to include to read/write measurement signals.
|
|   Usage examples:
|
|     daqHeartbeat++;
|     engineRpm = 800U;
|     vehicleSpeedKph = 42.5f;
|
|   All macros expand to (measData.name), so they compile to a single
|   (volatile-qualified) struct-field access — same zero-overhead
|   property as CAL(name) in cal_access.h.
|
|   To add a new signal:
|     1. Add one line to MEAS_PARAMS_TABLE in meas_params.h
|     2. Add one #define line here (mirror below)
----------------------------------------------------------------------------*/

#ifndef MEAS_ACCESS_H
#define MEAS_ACCESS_H

#include "driver/app/meas_data.h"

/* ============================================================
 * MEAS(name) — generic zero-maintenance accessor
 *
 * Works for ANY field without adding a macro here. Prefer when writing
 * reusable/library code, or when a local variable would clash with a
 * bare-name macro.
 * ============================================================ */
#define MEAS(name)  (measData.name)

/* ============================================================
 * Bare-name macros — one per signal in MEAS_PARAMS_TABLE
 * ============================================================ */

/* --- 10 ms raster --- */
#define daqHeartbeat     MEAS(daqHeartbeat)
#define engineRpm        MEAS(engineRpm)
#define vehicleSpeedKph  MEAS(vehicleSpeedKph)

/* --- 100 ms raster --- */
#define coolantTempC     MEAS(coolantTempC)

/* --- 10 ms raster — complex-type scenarios ---
 * speedPidTelemetry.error / .integral / .output  (struct, meas_types.h)
 * torqueSamples[i]                               (array, 4 elements)   */
#define speedPidTelemetry MEAS(speedPidTelemetry)
#define torqueSamples     MEAS(torqueSamples)

/* ---- Add new parameter macros above this line ---- */

#endif /* MEAS_ACCESS_H */
