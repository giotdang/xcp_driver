/*----------------------------------------------------------------------------
| File:   xcp_can_tricore.h
|
| Description:
|   XCP on CAN transport layer API for AURIX TriCore + iLLD MultiCAN.
|   Public interface of xcp_can_tricore.c.
|
| Include note:
|   Includes only Ifx_Types.h (not XcpBasic.h) to avoid a circular dependency:
|     xcp_can_tricore.h -> XcpBasic.h -> xcp_cfg.h -> xcp_can_tricore.h
|   The Vector aliases vuint8/BYTEPTR used by XcpBasic.c resolve to the same
|   underlying type as uint8/uint8* via the typedefs in xcp_types.h.
----------------------------------------------------------------------------*/

#ifndef XCP_CAN_TRICORE_H
#define XCP_CAN_TRICORE_H

#include "Ifx_Types.h"

/* Initialise the CAN node and message objects used by XCP.
 * Called via ApplXcpInit() -> XcpInit(). */
void XcpCan_Init(void);

/* Transmit one XCP packet (1-8 bytes) on the CAN bus.
 * Called via ApplXcpSend() by XcpBasic.c. */
void XcpCan_Send(uint8 len, const uint8 *msg);

/* Periodic background — no-op for ISR-driven design.
 * Called via ApplXcpBackground() by XcpBackground(). */
void XcpCan_Background(void);

/* ISR entry points — registered by IFX_INTERRUPT in xcp_can_tricore.c. */
void XcpCan_RxIsr(void);   /* CAN frame received  -> XcpCommand()      */
void XcpCan_TxIsr(void);   /* CAN frame confirmed -> XcpSendCallBack()  */

#endif /* XCP_CAN_TRICORE_H */
