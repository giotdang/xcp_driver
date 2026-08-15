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
|       ODT 0: g_xcpEngineRpm       (uint16, 2 bytes -> fits the 3-byte
|                                    budget left after PID+timestamp)
|       ODT 1: g_xcpVehicleSpeedKph (float32, 4 bytes -> PID-only ODT,
|                                    7 payload bytes free)
|
|     DAQ list 1 -- event 1 "100ms", timestamp ON
|       ODT 0: g_xcpDaqHeartbeat    (uint32, 4 bytes -- does NOT fit next to
|                                    a timestamp; either put it in ODT 1
|                                    instead, or turn timestamping off for
|                                    this list via SET_DAQ_LIST_MODE)
|       ODT 1: g_xcpCoolantTempC    (float32, 4 bytes, PID-only ODT)
----------------------------------------------------------------------------*/

#include "examples/xcp_daq_example.h"
#include "Xcp_Handler.h"
#include "port/tricore_illd/xcp_appl.h"

uint32  g_xcpDaqHeartbeat;
uint16  g_xcpEngineRpm;
float32 g_xcpVehicleSpeedKph;
float32 g_xcpCoolantTempC;

void XcpDaqExample_Init(void)
{
    Xcp_Init(&Xcp_Config);
}

void XcpDaqExample_Task_10ms(void)
{
    g_xcpDaqHeartbeat++;

    /* Sawtooth 0..120 kph over 12 s -- just something moving for CANape */
    g_xcpVehicleSpeedKph = (float32)(g_xcpDaqHeartbeat % 1200U) / 10.0f;
    g_xcpEngineRpm = (uint16)(800U + (uint16)(g_xcpVehicleSpeedKph * 40.0f));

    (void)Xcp_Event(XCP_EVENT_10MS);
}

void XcpDaqExample_Task_100ms(void)
{
    /* Sawtooth 20..90 degC over 7 s */
    g_xcpCoolantTempC = 20.0f + (float32)(g_xcpDaqHeartbeat % 700U) / 10.0f;

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
