/*----------------------------------------------------------------------------
| File:   xcp_tricore.h
|
| Description:
|   Hardware configuration for XCP on CAN — Infineon AURIX TriCore (TC2xx).
|   HAL: iLLD MultiCAN (IfxMultican_Can_*).
|
|   This is a config-only header: pure #defines and one extern for the
|   interrupt state.  It has no corresponding .c file.
|   Included by xcp_cfg.h so the macros (XcpInterruptDisable/Enable,
|   ApplXcpInit/Send/Background) resolve correctly.
|
|   Adapt the defines below to match your board schematic and the
|   interrupt priority table of your project.
|
| TC3xx (MCMCAN) migration:
|   Replace  IfxMultican_NodeId_*  ->  IfxMcmcan_NodeId_*
|   Replace  IfxMultican_SrcId_*   ->  IfxMcmcan_InterruptLine_* + SRC routing
|   Pin names change from IfxMultican_TXD*/RXD* to IfxMcmcan_TXD*/RXD*
----------------------------------------------------------------------------*/

#ifndef XCP_TRICORE_H
#define XCP_TRICORE_H

#include "Ifx_Types.h"
#include "IfxCpu.h"
#include "IfxMultican_Can.h"

/* ============================================================
 * CAN hardware selection
 * ============================================================ */
#define XCP_CAN_MODULE          MODULE_CAN           /* single CAN module on TC2xx  */
#define XCP_CAN_NODE_ID         IfxMultican_NodeId_0
#define XCP_CAN_BAUDRATE        500000UL             /* 500 kbps                    */

/* ============================================================
 * XCP CAN message identifiers (11-bit standard frame)
 * Override via compiler flags if your network uses different IDs.
 * ============================================================ */
#ifndef XCP_CAN_TX_ID
#define XCP_CAN_TX_ID           0x7E1U   /* ECU -> Host (response / DAQ)  */
#endif
#ifndef XCP_CAN_RX_ID
#define XCP_CAN_RX_ID           0x7E0U   /* Host -> ECU (command)         */
#endif

/* ============================================================
 * MultiCAN message object allocation (0-127 on TC2xx)
 * ============================================================ */
#define XCP_CAN_TX_MSG_OBJ_ID   0U
#define XCP_CAN_RX_MSG_OBJ_ID   1U

/* ============================================================
 * ISR configuration
 * Priority: 1 (lowest) .. 255 (highest)
 * SrcId: maps message-object interrupt to a CPU interrupt line
 * ============================================================ */
#define XCP_CAN_RX_ISR_PRIORITY  60U
#define XCP_CAN_TX_ISR_PRIORITY  59U
#define XCP_CAN_TX_ISR_SRC_ID    IfxMultican_SrcId_0
#define XCP_CAN_RX_ISR_SRC_ID    IfxMultican_SrcId_1

/* ============================================================
 * CAN transceiver pin mapping
 * Example: TC275 Lite Kit — TXD -> P20.8, RXD -> P20.7
 * Update to match your schematic.
 * ============================================================ */
#define XCP_CAN_TX_PIN           IfxMultican_TXD0_P20_8_OUT
#define XCP_CAN_RX_PIN           IfxMultican_RXD0B_P20_7_IN

/* ============================================================
 * Interrupt state — saved/restored by XcpInterruptDisable/Enable
 * Defined in xcp_appl_tricore.c.
 * ============================================================ */
extern boolean g_xcpIsrState;

#endif /* XCP_TRICORE_H */
