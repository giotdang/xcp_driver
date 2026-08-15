/*----------------------------------------------------------------------------
| File:   xcp_cfg.c
|
| Description:
|   XCP PostBuild configuration — application-level wiring.
|
|   This file assembles the Xcp_Config object that is passed to Xcp_Init().
|   It is the single place to change when:
|     - Switching transport layer (CAN -> LIN, ETH, ...)
|     - Changing station ID / protocol parameters
|     - Swapping out platform callbacks for a new port
|
|   Platform callbacks (Xcp_GetPointer, Xcp_EnterCritical, ...) are
|   implemented in port/tricore_illd/xcp_appl.c.
|   Transport functions (XcpCan_Send, XcpCan_Receive) are in
|   port/tricore_illd/xcp_can_tricore.c.
----------------------------------------------------------------------------*/

#include "driver/Xcp_Handler.h"
#include "driver/port/tricore_illd/xcp_appl.h"
#include "driver/port/tricore_illd/xcp_can_tricore.h"
#include "driver/port/tricore_illd/xcp_tricore.h"    /* XCP_CAN_TX_ID              */

/* ============================================================
 * CAN transport configuration.
 * The application must initialise the CAN node (IfxCan_Can_initNode,
 * TX buffer, RX FIFO0, filter, ISR routing) before Xcp_Init() is called.
 * Declare the pre-initialised node handle extern here.
 * ============================================================ */
extern IfxCan_Can_Node g_xcpCanNode;   /* defined in the application CAN init module */

static const XcpCan_ConfigType XcpCan_Config = {
    .node = &g_xcpCanNode,
    .txId = XCP_CAN_TX_ID,
};

/* ============================================================
 * Xcp_Config — PostBuild configuration object.
 * Pass &Xcp_Config to Xcp_Init() during startup.
 * Xcp_Init() calls XcpCal_InitWorkingPage() and XcpCan_Init() internally.
 * ============================================================ */
static const Xcp_TransportLayerType Xcp_CanTransportLayer = {
    .CanConfig      = &XcpCan_Config,
    .Transmit       = XcpCan_Send,
    .Receive        = XcpCan_Receive,
#if defined(XCP_ENABLE_DAQ_TIMESTAMP)
    .GetTimestamp   = Xcp_GetTimestamp,
#endif
    .EnterCritical  = Xcp_EnterCritical,
    .ExitCritical   = Xcp_ExitCritical,
};

const Xcp_ConfigType Xcp_Config = {
    .StationId        = "AURIX_XCP",
    .StationIdLength  = 9U,
    .TransportLayer   = &Xcp_CanTransportLayer,
    .GetPointer       = Xcp_GetPointer,
#if defined(XCP_ENABLE_CALIBRATION_MEM_ACCESS_BY_APPL)
    .CalibrationWrite = Xcp_CalibrationWrite,
    .CalibrationRead  = Xcp_CalibrationRead,
#endif
#if defined(XCP_ENABLE_CALIBRATION_PAGE)
    .GetCalPage       = Xcp_GetCalPage,
    .SetCalPage       = Xcp_SetCalPage,
#if defined(XCP_ENABLE_PAGE_COPY)
    .CopyCalPage      = Xcp_CopyCalPage,
#endif
#endif
};
