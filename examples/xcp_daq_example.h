/*----------------------------------------------------------------------------
| File:   xcp_daq_example.h
|
| Description:
|   Example: how to drive DAQ (Data Acquisition) with xcp_driver.
|
|   The driver's DTO pipeline (Xcp_Event -> send queue -> Transmit -> TX ISR
|   chaining, see Xcp_Handler.c) is complete and correct, but nothing in the
|   driver itself ever calls Xcp_Event() -- that call has to come from the
|   application's periodic tasks. This file is that missing piece, wired to
|   two example measurement rasters.
|
|   Assumptions:
|     - The CAN node (module/node/TX buffer 0/RX FIFO0/filter/ISR routing)
|       is already initialised by the application before XcpDaqExample_Init()
|       runs (see xcp_cfg.c: g_xcpCanNode).
|     - Some scheduler (AUTOSAR OS, FreeRTOS, bare cyclic loop, ...) can
|       invoke the XcpDaqExample_Task_*() functions below at the stated
|       period. The AUTOSAR OS TASK() wrappers at the bottom are one
|       concrete example of that wiring.
|
|   Event map -- must match what you author by hand in the A2L /begin EVENT
|   block. GET_DAQ_EVENT_INFO is unavailable (kXcpMaxEvent is not defined in
|   xcp_cfg.h), so CANape/INCA cannot auto-discover events over XCP:
|
|     Event 0  "10ms"   cycle 10 ms   -> XcpDaqExample_Task_10ms()
|     Event 1  "100ms"  cycle 100 ms  -> XcpDaqExample_Task_100ms()
|
|   ODT budget note (kXcpMaxDTO = 8, kXcpDaqTimestampSize = DWORD):
|     The first ODT of a DAQ list carries PID(1) + timestamp(4) = 5 bytes of
|     header when the list has per-event timestamping on, leaving only 3
|     payload bytes. A 4-byte float32/uint32 signal does NOT fit there --
|     put it in the list's *second* ODT (PID-only header, 7 payload bytes
|     free) or disable timestamping for that list. See the CANape DAQ list
|     layout suggested in the .c file's header comment.
----------------------------------------------------------------------------*/

#ifndef XCP_DAQ_EXAMPLE_H
#define XCP_DAQ_EXAMPLE_H

#include "Ifx_Types.h"

#define XCP_EVENT_10MS   0U
#define XCP_EVENT_100MS  1U

/* Measurement signals. Add each address to the A2L as a MEASUREMENT object,
 * then reference it from an ODT entry in a DAQ list bound to the matching
 * event above. */
extern uint32  g_xcpDaqHeartbeat;     /* free-running counter, sanity check */
extern uint16  g_xcpEngineRpm;        /* 800..5600 rpm, 10 ms raster        */
extern float32 g_xcpVehicleSpeedKph;  /* 0..120 kph sawtooth, 10 ms raster  */
extern float32 g_xcpCoolantTempC;     /* 20..90 degC sawtooth, 100 ms raster*/

/* Call once at startup, after the CAN node is initialised and before the
 * scheduler starts running the tasks below.
 * Internally calls Xcp_Init(&Xcp_Config), which itself calls
 * XcpCal_InitWorkingPage() and XcpCan_Init() -- no need to call those
 * separately. */
void XcpDaqExample_Init(void);

/* Call from a periodic 10 ms task/alarm. */
void XcpDaqExample_Task_10ms(void);

/* Call from a periodic 100 ms task/alarm. */
void XcpDaqExample_Task_100ms(void);

/* Call from the lowest-priority cyclic task (or idle loop), >= ~1-5 ms rate.
 * Polls CAN RX, processes XCP commands, drains checksum background work.
 * If this is starved for too long, CANape command responses stall. */
void XcpDaqExample_BackgroundTask(void);

#if defined(XCP_DAQ_EXAMPLE_USE_AUTOSAR_OS_TASKS)
/* AUTOSAR OS TASK() wrappers -- one concrete way to hook the functions
 * above into a scheduler. Configure matching cyclic alarms/counters in
 * your OIL/ARXML: TaskXcpDaq10ms @10ms, TaskXcpDaq100ms @100ms,
 * TaskXcpBackground @1-5ms (or call XcpDaqExample_BackgroundTask() from
 * the OS idle hook instead of a dedicated task).
 * For FreeRTOS or any other RTOS: create equivalent periodic tasks that
 * call the same three XcpDaqExample_* functions, nothing else changes. */
#include "Os.h"

TASK(TaskXcpDaq10ms);
TASK(TaskXcpDaq100ms);
TASK(TaskXcpBackground);
#endif /* XCP_DAQ_EXAMPLE_USE_AUTOSAR_OS_TASKS */

#endif /* XCP_DAQ_EXAMPLE_H */
