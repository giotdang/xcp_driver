/*----------------------------------------------------------------------------
| File:   xcp_daq_example.c
|
| Description:
|   Example DAQ producer for xcp_driver. See xcp_daq_example.h for the
|   assumptions and the event map.
|
|   Suggested CANape DAQ list layout for the four signals below (fits the
|   kXcpMaxDTO=8 / DWORD-timestamp budget explained in the header):
|
|     DAQ list 0 -- event 0 "10ms", timestamp ON
|       ODT 0: engineRpm       (uint16, 2 bytes -> fits the 3-byte budget
|                                left after PID+timestamp)
|       ODT 1: vehicleSpeedKph (float32, 4 bytes -> PID-only ODT,
|                                7 payload bytes free)
|
|     DAQ list 1 -- event 1 "100ms", timestamp ON
|       ODT 0: daqHeartbeat    (uint32, 4 bytes -- does NOT fit next to a
|                                timestamp; either put it in ODT 1 instead,
|                                or turn timestamping off for this list via
|                                SET_DAQ_LIST_MODE)
|       ODT 1: coolantTempC    (float32, 4 bytes, PID-only ODT)
|
|     DAQ list 0, continued -- complex-type scenarios, still event 0:
|       ODT 2: speedPidTelemetry.error     (float32, PID-only ODT, 4/7
|                                           payload bytes used)
|       ODT 3: speedPidTelemetry.integral  (float32 -- does NOT share ODT 2:
|                                           4+4=8 bytes > 7-byte PID-only
|                                           budget, so each float32 member
|                                           needs its own ODT here)
|       ODT 4: speedPidTelemetry.output    (float32)
|       ODT 5..8: torqueSamples[0..3]      (float32[4] -- same 8>7 rule
|                                           applies per array element, so
|                                           CANape needs 4 separate ODTs
|                                           for this one MATRIX_DIM signal,
|                                           1 element each. MATRIX_DIM only
|                                           saves you from hand-authoring 4
|                                           MEASUREMENT records in the A2L
|                                           -- it does NOT reduce the
|                                           number of CAN frames actually
|                                           sent every 10 ms; classic CAN's
|                                           8-byte frame is the real limit)
|
|   Storage: see app/meas_data.h -- these fields live in the single struct
|   instance measData, accessed here via app/meas_access.h bare names
|   (daqHeartbeat, engineRpm, speedPidTelemetry.error, torqueSamples[i], ...).
|
|   Calibration tie-in: this task also reads app/cal_access.h parameters
|   (idleSpeedRpm, systemGain, speedPid, torqueMap, tempOffsetDegC,
|   featureEnabled) -- showing the two halves of xcp_driver working
|   together: CANape DOWNLOADs a calibration value, the application logic
|   here reacts to it, and the result is what DAQ measures back out.
|   These CAL parameters still need their own CHARACTERISTIC/RECORD_LAYOUT
|   A2L records (generated separately from app/cal_params.h, per
|   CLAUDE.md) to be visible/editable in CANape -- deliberately not
|   duplicated in xcp_daq_example.a2l, which only covers DAQ/MEASUREMENT.
----------------------------------------------------------------------------*/

#include "examples/xcp_daq_example.h"
#include "Xcp_Handler.h"
#include "port/tricore_illd/xcp_appl.h"
#include "app/meas_access.h"
#include "app/cal_access.h"

void XcpDaqExample_Init(void)
{
    Xcp_Init(&Xcp_Config);
}

void XcpDaqExample_Task_10ms(void)
{
    daqHeartbeat++;

    /* Sawtooth 0..120 kph over 12 s, scaled by CAL systemGain; engineRpm
     * based off CAL idleSpeedRpm instead of a hardcoded constant. */
    vehicleSpeedKph = systemGain * (float32)(daqHeartbeat % 1200U) / 10.0f;
    engineRpm = (uint16)(idleSpeedRpm + (vehicleSpeedKph * 40.0f));

    /* PID demo: hold vehicleSpeedKph at a fixed setpoint using the CAL
     * speedPid block (kp/ki/outMin/outMax). The whole snapshot (error,
     * integral, output) is computed here, all in one place, BEFORE
     * Xcp_Event() runs below -- so even though the 3 fields end up split
     * across 2 ODTs in the DAQ list layout above, and Xcp_Event() only
     * holds its critical section per-ODT (not across the whole list, see
     * Xcp_Handler.c), there is no torn read: nothing else in this example
     * writes speedPidTelemetry between here and Xcp_Event(). A real
     * multi-task system where something else could still be writing this
     * struct concurrently would need the same "compute a stable snapshot,
     * then trigger DAQ" pattern, or an explicit staging buffer. */
    {
        const float32 setpointKph = 60.0f;
        float32 error = setpointKph - vehicleSpeedKph;
        float32 integral = speedPidTelemetry.integral + (speedPid.ki * error);

        if (integral > speedPid.outMax) { integral = speedPid.outMax; }
        if (integral < speedPid.outMin) { integral = speedPid.outMin; }

        speedPidTelemetry.error = error;
        speedPidTelemetry.integral = integral;
        speedPidTelemetry.output = (speedPid.kp * error) + integral;
        if (speedPidTelemetry.output > speedPid.outMax) { speedPidTelemetry.output = speedPid.outMax; }
        if (speedPidTelemetry.output < speedPid.outMin) { speedPidTelemetry.output = speedPid.outMin; }
    }

    /* Array demo: shift a torqueMap (CAL, 8-point lookup table) sample
     * into a 4-deep measurement history. idx is clamped even though
     * engineRpm is normally in range, because systemGain is a CAL
     * parameter CANape can DOWNLOAD to any value at runtime -- an
     * unclamped index here would be an out-of-bounds read of torqueMap. */
    {
        uint8 idx = (uint8)(engineRpm / 1000U);
        if (idx >= 8U) { idx = 7U; }   /* torqueMap has 8 entries, cal_params.h */

        torqueSamples[3] = torqueSamples[2];
        torqueSamples[2] = torqueSamples[1];
        torqueSamples[1] = torqueSamples[0];
        torqueSamples[0] = torqueMap[idx];
    }

    (void)Xcp_Event(XCP_EVENT_10MS);
}

void XcpDaqExample_Task_100ms(void)
{
    /* Sawtooth 20..90 degC over 7 s, offset by CAL tempOffsetDegC; frozen
     * at its last value while CAL featureEnabled is FALSE -- a scalar and
     * a boolean CAL parameter both feeding one measurement signal. */
    if (featureEnabled)
    {
        coolantTempC = 20.0f + (float32)tempOffsetDegC + (float32)(daqHeartbeat % 700U) / 10.0f;
    }

    (void)Xcp_Event(XCP_EVENT_100MS);
}

void XcpDaqExample_BackgroundTask(void)
{
    Xcp_Background();
}

#if defined(XCP_DAQ_EXAMPLE_USE_AUTOSAR_OS_TASKS)
TASK(TaskXcpDaq10ms)
{
    XcpDaqExample_Task_10ms();
    TerminateTask();
}

TASK(TaskXcpDaq100ms)
{
    XcpDaqExample_Task_100ms();
    TerminateTask();
}

TASK(TaskXcpBackground)
{
    XcpDaqExample_BackgroundTask();
    TerminateTask();
}
#endif /* XCP_DAQ_EXAMPLE_USE_AUTOSAR_OS_TASKS */
