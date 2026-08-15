/*----------------------------------------------------------------------------
| File:   xcp_can_tricore.c
|
| Description:
|   XCP on CAN transport layer for Infineon AURIX TC3xx + iLLD MCMCAN.
|
|   Responsibilities:
|     1. XcpCan_Init      — store XcpCan_ConfigType pointer (no hardware init)
|     2. XcpCan_Send      — transmit one XCP packet via dedicated TX buffer 0
|     3. XcpCan_RxIsr     — FIFO0 new-message ISR: read hardware FIFO and
|                           enqueue frame into SW ring buffer
|     4. XcpCan_TxIsr     — TX-complete ISR: clear flag, call Xcp_SendCallBack()
|     5. XcpCan_Receive   — poll function: dequeue one frame for Xcp_Background()
|
|   CAN module/node initialisation is the responsibility of the application.
|   XcpCan_Init() only stores a pointer to the pre-initialised node handle and
|   the TX CAN ID.  The application must configure TX dedicated buffer 0,
|   RX FIFO0, the standard ID filter, and the interrupt routing before calling
|   XcpCan_Init().
|
|   Async RX design:
|     RX ISR only enqueues frames into g_xcpRxQueue[].
|     Xcp_Background() calls XcpCan_Receive() to dequeue and then passes the
|     frame to Xcp_Command() — no protocol processing in ISR context.
|
|   Thread safety (single-producer / single-consumer ring buffer):
|     g_xcpRxQueueWp is volatile and only written by RX ISR.
|     g_xcpRxQueueRp is only read/written by Xcp_Background() (task context).
|     Data is written to the slot before advancing g_xcpRxQueueWp, so the
|     consumer sees a consistent frame whenever it observes the new pointer.
|     If the SW queue is full the ISR silently drops the frame; the XCP master
|     will retry on timeout.
|
| Dependencies:
|   iLLD:   IfxCan_Can.h, IfxCan.h
|   XCP:    Xcp_Handler.h, xcp_tricore.h (ISR priority macros), xcp_can_tricore.h
----------------------------------------------------------------------------*/

#include "driver/Xcp_Handler.h"
#include "driver/port/tricore_illd/xcp_tricore.h"
#include "driver/port/tricore_illd/xcp_can_tricore.h"

#include "IfxCan_Can.h"
#include "IfxCan.h"

#include <string.h>   /* memcpy */

/* ============================================================
 * Configuration pointer — stored by XcpCan_Init, used by all functions.
 * ============================================================ */
static const XcpCan_ConfigType *g_xcpCanCfg;

/* ============================================================
 * RX ring buffer — single-producer (ISR) / single-consumer (Background)
 * ============================================================ */
#define XCP_CAN_RX_QUEUE_SIZE  4U

typedef struct {
    uint32 data[2];   /* 8 bytes: data[0] = bytes 0-3, data[1] = bytes 4-7 */
} XcpCan_RxFrame_t;

static XcpCan_RxFrame_t  g_xcpRxQueue[XCP_CAN_RX_QUEUE_SIZE];
static volatile uint8    g_xcpRxQueueWp;   /* written by ISR, read by Background */
static uint8             g_xcpRxQueueRp;   /* read and written by Background only */

/* ============================================================
 * XcpCan_Init
 *
 * Stores the configuration pointer.  No hardware access is performed.
 * The application must fully initialise the CAN node (including TX
 * dedicated buffer 0, RX FIFO0, standard ID filter, and interrupt
 * routing) before calling this function.
 *
 * Call once, before Xcp_Init().
 * ============================================================ */
void XcpCan_Init(const XcpCan_ConfigType *ConfigPtr)
{
    g_xcpCanCfg = ConfigPtr;
}

/* ============================================================
 * XcpCan_Send  (bound to TransportLayer->Transmit callback)
 *
 * Transmits msg (len bytes, max 8) using TX dedicated buffer 0.
 * Spins until the buffer is free (non-blocking under normal conditions:
 * the TX ISR fires quickly after the frame is put on the bus).
 * ============================================================ */
void XcpCan_Send(uint8 len, const uint8 *msg)
{
    IfxCan_Message txMsg;
    IfxCan_Message_init(&txMsg);

    txMsg.messageId          = g_xcpCanCfg->txId;
    txMsg.messageIdLength    = IfxCan_MessageIdLength_standard;
    txMsg.dataLengthCode     = IfxCan_DataLengthCode_8;
    txMsg.bufferNumber       = 0U;
    txMsg.storeInTxFifoQueue = FALSE;

    uint32 txData[2] = {0U, 0U};
    memcpy(txData, msg, (len <= 8U) ? (uint32)len : 8U);

    while (IfxCan_Can_sendMessage(g_xcpCanCfg->node, &txMsg, txData)
           == IfxCan_Status_notSentBusy) {}
}

/* ============================================================
 * XcpCan_Receive  (bound to TransportLayer->Receive callback)
 *
 * Called from Xcp_Background() to dequeue one RX frame.
 * Returns 1 if a frame was dequeued, 0 if the queue is empty.
 * *len is always set to 8 (fixed CAN DLC for XCP on CAN).
 * ============================================================ */
uint8 XcpCan_Receive(uint8 *len, uint8 *data)
{
    if (g_xcpRxQueueRp == g_xcpRxQueueWp)
    {
        return 0U;
    }

    memcpy(data, &g_xcpRxQueue[g_xcpRxQueueRp], 8U);
    *len = 8U;

    g_xcpRxQueueRp = (uint8)((g_xcpRxQueueRp + 1U) % XCP_CAN_RX_QUEUE_SIZE);
    return 1U;
}

/* ============================================================
 * XcpCan_RxIsr
 *
 * Triggered by MCMCAN FIFO0 new-message interrupt.
 * Reads the frame from the hardware FIFO (auto-acknowledged by iLLD)
 * and enqueues it into the SW ring buffer.  Xcp_Background() dequeues
 * and calls Xcp_Command().
 *
 * ISR priority: XCP_CAN_RX_ISR_PRIORITY (xcp_tricore.h)
 * CPU affinity: core 0
 * ============================================================ */
IFX_INTERRUPT(XcpCan_RxIsr, 0, XCP_CAN_RX_ISR_PRIORITY)
{
    IfxCan_Message rxMsg;
    IfxCan_Message_init(&rxMsg);
    rxMsg.readFromRxFifo0 = TRUE;

    uint32 rxData[2] = {0U, 0U};
    IfxCan_Can_readMessage(g_xcpCanCfg->node, &rxMsg, rxData);

    uint8 nextWp = (uint8)((g_xcpRxQueueWp + 1U) % XCP_CAN_RX_QUEUE_SIZE);
    if (nextWp != g_xcpRxQueueRp)   /* drop silently if SW queue is full */
    {
        g_xcpRxQueue[g_xcpRxQueueWp].data[0] = rxData[0];
        g_xcpRxQueue[g_xcpRxQueueWp].data[1] = rxData[1];
        g_xcpRxQueueWp = nextWp;    /* advance after data is written */
    }
}

/* ============================================================
 * XcpCan_TxIsr
 *
 * Triggered when dedicated TX buffer 0 has successfully sent a frame.
 * Clears the hardware TX-complete interrupt flag, then calls
 * Xcp_SendCallBack() to chain the next DTO from the XCP send queue.
 *
 * ISR priority: XCP_CAN_TX_ISR_PRIORITY (xcp_tricore.h)
 * CPU affinity: core 0
 * ============================================================ */
IFX_INTERRUPT(XcpCan_TxIsr, 0, XCP_CAN_TX_ISR_PRIORITY)
{
    IfxCan_Node_clearInterruptFlag(g_xcpCanCfg->node->node,
                                   IfxCan_Interrupt_transmissionCompleted);
    Xcp_SendCallBack();
}
