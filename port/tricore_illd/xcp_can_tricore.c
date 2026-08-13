/*----------------------------------------------------------------------------
| File:   xcp_can_tricore.c
|
| Description:
|   XCP on CAN transport layer for Infineon AURIX TC2xx + iLLD MultiCAN.
|
|   Responsibilities:
|     1. XcpCan_Init      — configure CAN node, TX and RX message objects
|     2. XcpCan_Send      — transmit one XCP packet (called by protocol layer)
|     3. XcpCan_RxIsr     — receive ISR: read frame, call XcpCommand()
|     4. XcpCan_TxIsr     — TX-done ISR: call XcpSendCallBack() to drain queue
|
|   ISR-driven design:
|     No polling is required.  The TX ISR calls XcpSendCallBack(), which
|     in turn calls XcpCan_Send() for the next queued DTO if one exists,
|     chaining transmissions without CPU spin.
|
| TC3xx (MCMCAN) migration guide — differences to address:
|   - Module init:  IfxMultican_Can_initModule  → IfxMcmcan_Can_initModule
|   - Node init:    IfxMultican_Can_Node_init   → IfxMcmcan_Can_Node_init
|   - No message objects on MCMCAN; use TX buffer + RX FIFO instead:
|       TX: IfxMcmcan_Can_Node_initTxBuffer / writeTxBuffer / setTxBufferAddRequest
|       RX: Configure RX filter → FIFO0; read via IfxMcmcan_Can_Node_readRxFifo0
|   - ISR: use IfxMcmcan_InterruptLine_* and route to SRC via iLLD init config
|
| Dependencies:
|   iLLD:   IfxMultican_Can.h, IfxMultican.h
|   XCP:    XcpBasic.h, xcp_tricore.h, xcp_can_tricore.h
|
|   Types: all functions use uint8/uint8* from Ifx_Types.h (via xcp_types.h).
|   XcpBasic.c call sites use the Vector aliases vuint8/BYTEPTR, which map to
|   the same underlying type (unsigned char), so no conversion is needed.
----------------------------------------------------------------------------*/

#include "XcpBasic.h"
#include "port/tricore_illd/xcp_tricore.h"
#include "port/tricore_illd/xcp_can_tricore.h"

/* iLLD MultiCAN */
#include "IfxMultican_Can.h"
#include "IfxMultican.h"

#include <string.h>   /* memcpy — safe byte-wise copy for unaligned msg ptr */

/* ============================================================
 * Module-level iLLD handles
 * Static — only accessible within this translation unit.
 * ============================================================ */
static IfxMultican_Can         g_xcpCanModule;
static IfxMultican_Can_Node    g_xcpCanNode;
static IfxMultican_Can_MsgObj  g_xcpTxObj;
static IfxMultican_Can_MsgObj  g_xcpRxObj;

/* ============================================================
 * XcpCan_Init
 *
 * Sequence:
 *   1. Enable and configure the MULTICAN module clock
 *   2. Initialise CAN node 0 at XCP_CAN_BAUDRATE
 *   3. Allocate TX message object (interrupt on TX confirmation)
 *   4. Allocate RX message object (interrupt on reception)
 *
 * Call this once before XcpInit(), or let it be called automatically
 * by XcpInit() via the ApplXcpInit() macro in xcp_cfg.h.
 * ============================================================ */
void XcpCan_Init(void)
{
    /* ---- CAN module ---- */
    IfxMultican_Can_Config modCfg;
    IfxMultican_Can_initModuleConfig(&modCfg, &XCP_CAN_MODULE);
    IfxMultican_Can_initModule(&g_xcpCanModule, &modCfg);

    /* ---- CAN node ---- */
    IfxMultican_Can_Node_Config nodeCfg;
    IfxMultican_Can_Node_initConfig(&nodeCfg, &g_xcpCanModule);

    nodeCfg.nodeId   = XCP_CAN_NODE_ID;
    nodeCfg.baudrate = XCP_CAN_BAUDRATE;

    /* Pin mapping — update XCP_CAN_TX_PIN / XCP_CAN_RX_PIN in xcp_tricore.h */
    const IfxMultican_Can_Pins pins = {
        .txPin     = &XCP_CAN_TX_PIN,
        .txPinMode = IfxPort_OutputMode_pushPull,
        .rxPin     = &XCP_CAN_RX_PIN,
        .rxPinMode = IfxPort_InputMode_pullUp,
    };
    nodeCfg.pins = &pins;

    IfxMultican_Can_Node_init(&g_xcpCanNode, &nodeCfg);

    /* ---- TX message object ---- */
    IfxMultican_Can_MsgObj_Config txObjCfg;
    IfxMultican_Can_MsgObj_initConfig(&txObjCfg, &g_xcpCanNode);

    txObjCfg.msgObjId            = XCP_CAN_TX_MSG_OBJ_ID;
    txObjCfg.messageId           = XCP_CAN_TX_ID;
    txObjCfg.frame               = IfxMultican_Frame_transmit;
    txObjCfg.txInterrupt.enabled = TRUE;
    txObjCfg.txInterrupt.srcId   = XCP_CAN_TX_ISR_SRC_ID;

    IfxMultican_Can_MsgObj_init(&g_xcpTxObj, &txObjCfg);

    /* ---- RX message object ---- */
    IfxMultican_Can_MsgObj_Config rxObjCfg;
    IfxMultican_Can_MsgObj_initConfig(&rxObjCfg, &g_xcpCanNode);

    rxObjCfg.msgObjId            = XCP_CAN_RX_MSG_OBJ_ID;
    rxObjCfg.messageId           = XCP_CAN_RX_ID;
    rxObjCfg.frame               = IfxMultican_Frame_receive;
    rxObjCfg.rxInterrupt.enabled = TRUE;
    rxObjCfg.rxInterrupt.srcId   = XCP_CAN_RX_ISR_SRC_ID;

    IfxMultican_Can_MsgObj_init(&g_xcpRxObj, &rxObjCfg);
}

/* ============================================================
 * XcpCan_Send  (= ApplXcpSend via macro in xcp_cfg.h)
 *
 * Called by XcpBasic.c whenever it needs to transmit:
 *   - A command response (CRM) after processing a host command
 *   - A DAQ/DTO packet when XcpSendCallBack drains the send queue
 *
 * The XCP protocol layer guarantees this is not called re-entrantly:
 *   - It disables interrupts (XcpInterruptDisable) around queue access
 *   - The TX mailbox is always free when called from the TX ISR context
 *     (because TX just completed, freeing the mailbox)
 *
 * memcpy is used instead of a direct word cast because the msg pointer
 * handed by the protocol layer may not be 32-bit aligned.
 * ============================================================ */
void XcpCan_Send(uint8 len, const uint8 *msg)
{
    uint32 dataLow  = 0U;
    uint32 dataHigh = 0U;

    /* Copy bytes into two 32-bit words, zero-padding short frames */
    const uint8 lowBytes  = (len >= 4U) ? 4U : len;
    const uint8 highBytes = (len > 4U)  ? (uint8)(len - 4U) : 0U;

    memcpy(&dataLow,  msg,     lowBytes);
    memcpy(&dataHigh, msg + 4U, highBytes);

    IfxMultican_Message txMsg;
    IfxMultican_Message_init(&txMsg,
                             XCP_CAN_TX_ID,
                             dataLow,
                             dataHigh,
                             IfxMultican_DataLengthCode_8);  /* always 8-byte DLC on CAN */

    /* Wait until the TX mailbox is ready.
     * Under normal operation this loop runs 0 iterations (mailbox is free).
     * It may spin briefly if XcpCan_Send is called from a task context
     * simultaneously with a background CAN transmission.            */
    while (IfxMultican_Can_MsgObj_sendMessage(&g_xcpTxObj, &txMsg)
           == IfxMultican_Status_notSentBusy) {}
}

/* ============================================================
 * XcpCan_RxIsr
 *
 * Triggered by the MULTICAN hardware when a CAN frame arrives with
 * an ID matching XCP_CAN_RX_ID (set in the RX message object filter).
 *
 * Reads the 8-byte frame and passes it to XcpCommand().
 * XcpCommand() processes the XCP protocol command and, if a response
 * is needed, calls back into XcpCan_Send() before returning.
 *
 * ISR priority: XCP_CAN_RX_ISR_PRIORITY (defined in xcp_tricore.h)
 * CPU affinity: core 0 (second arg of IFX_INTERRUPT)
 * ============================================================ */
IFX_INTERRUPT(XcpCan_RxIsr, 0, XCP_CAN_RX_ISR_PRIORITY)
{
    IfxMultican_Message rxMsg;

    if (IfxMultican_Can_MsgObj_readMessage(&g_xcpRxObj, &rxMsg)
        == IfxMultican_Status_ok)
    {
        /* rxMsg.data[0] = bytes 0–3 (little-endian word)
         * rxMsg.data[1] = bytes 4–7
         * Both are naturally 32-bit aligned — cast is safe.           */
        XcpCommand((const uint32*)rxMsg.data);
    }
}

/* ============================================================
 * XcpCan_TxIsr
 *
 * Triggered by the MULTICAN hardware when the TX mailbox has
 * successfully put the frame on the bus (arbitration won, frame sent).
 *
 * XcpSendCallBack() checks the DTO send-queue:
 *   - If empty  : returns 0, ISR exits.
 *   - If pending: calls XcpCan_Send() for the next DTO and returns 1.
 *
 * This creates a self-sustaining chain: each TX-done interrupt
 * dispatches the next queued frame, achieving maximum CAN bus
 * utilisation without any polling loop.
 *
 * ISR priority: XCP_CAN_TX_ISR_PRIORITY (defined in xcp_tricore.h)
 * CPU affinity: core 0
 * ============================================================ */
IFX_INTERRUPT(XcpCan_TxIsr, 0, XCP_CAN_TX_ISR_PRIORITY)
{
    XcpSendCallBack();
}

/* ============================================================
 * XcpCan_Background  (= ApplXcpBackground via macro in xcp_cfg.h)
 *
 * Called from XcpBackground() in the periodic task.
 * The ISR-driven design requires no polling here.
 * Placeholder for future extensions: bus-off recovery, error frames.
 * ============================================================ */
void XcpCan_Background(void) {}
