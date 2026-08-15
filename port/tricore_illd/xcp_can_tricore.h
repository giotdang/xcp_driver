/*----------------------------------------------------------------------------
| File:   xcp_can_tricore.h
|
| Description:
|   XCP on CAN transport layer API for AURIX TC3xx + iLLD MCMCAN.
|   Public interface of xcp_can_tricore.c.
|
| Assumption:
|   The application initialises the CAN module and node (IfxCan_Can_initModule,
|   IfxCan_Can_initNode, filter, ISR routing) before calling XcpCan_Init().
|   XcpCan_Init() only stores the configuration; it performs no hardware access.
|
| Include note:
|   Includes IfxCan_Can.h for IfxCan_Can_Node used in XcpCan_ConfigType.
|   Does NOT include Xcp_Handler.h to avoid a circular dependency:
|     xcp_can_tricore.h -> Xcp_Handler.h -> xcp_cfg.h -> xcp_can_tricore.h
----------------------------------------------------------------------------*/

#ifndef XCP_CAN_TRICORE_H
#define XCP_CAN_TRICORE_H

#include "Ifx_Types.h"
#include "IfxCan_Can.h"

/* ============================================================
 * XcpCan_ConfigType
 *
 * Runtime parameters needed by the XCP CAN transport functions.
 * Passed to XcpCan_Init(); the pointer is stored and used for the
 * lifetime of the driver.
 *
 * node — pointer to a pre-initialised IfxCan_Can_Node handle.
 *         The application is responsible for calling IfxCan_Can_initNode()
 *         (and configuring TX buffer 0, RX FIFO0, filter, interrupts) before
 *         XcpCan_Init() is called.
 * txId — 11-bit standard CAN ID used by XcpCan_Send() for outgoing frames.
 * ============================================================ */
typedef struct {
    IfxCan_Can_Node *node;   /* pre-initialised CAN node handle */
    uint32           txId;  /* 11-bit standard CAN TX ID       */
} XcpCan_ConfigType;

/* Store ConfigPtr for runtime use.  No hardware access is performed.
 * Call once, after the CAN node has been initialised, before Xcp_Init(). */
void XcpCan_Init(const XcpCan_ConfigType *ConfigPtr);

/* Transmit one XCP packet (1-8 bytes) on the CAN bus.
 * Called via TransportLayer->Transmit() callback. */
void XcpCan_Send(uint8 len, const uint8 *msg);

/* Poll for a received XCP frame.
 * Returns 1 if a frame was dequeued from the RX ring buffer, 0 if empty. */
uint8 XcpCan_Receive(uint8 *len, uint8 *data);

/* ISR entry points — registered by IFX_INTERRUPT in xcp_can_tricore.c. */
void XcpCan_RxIsr(void);   /* CAN frame received  -> enqueue to RX ring buffer */
void XcpCan_TxIsr(void);   /* CAN frame confirmed -> Xcp_SendCallBack()        */

#endif /* XCP_CAN_TRICORE_H */
