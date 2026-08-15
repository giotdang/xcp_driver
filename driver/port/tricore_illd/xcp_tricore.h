/*----------------------------------------------------------------------------
| File:   xcp_tricore.h
|
| Description:
|   Hardware configuration for XCP on CAN — Infineon AURIX TriCore (TC3xx).
|   HAL: iLLD MCMCAN (IfxCan_Can_*).
|
|   This is a config-only header: pure #defines for CAN hardware and ISR
|   configuration.  It has no corresponding .c file.
|   Included by xcp_can_tricore.c.
|
|   Adapt the defines below to match your board schematic and the
|   interrupt priority table of your project.
|
| TC2xx (MultiCAN) note:
|   Replace  IfxCan_NodeId_*        ->  IfxMultican_NodeId_*
|   Replace  IfxCan_InterruptLine_* ->  IfxMultican_SrcId_*
|   Pin names change from IfxCan_TXD*/RXD* to IfxMultican_TXD*/RXD*
|   Use MODULE_CAN instead of MODULE_CAN0
----------------------------------------------------------------------------*/

#ifndef XCP_TRICORE_H
#define XCP_TRICORE_H

#include "Ifx_Types.h"
#include "IfxCpu.h"
#include "IfxCan_Can.h"

/* ============================================================
 * CAN hardware selection
 * ============================================================ */
#define XCP_CAN_MODULE          MODULE_CAN0          /* MCMCAN module 0 on TC3xx  */
#define XCP_CAN_NODE_ID         IfxCan_NodeId_0
#define XCP_CAN_BAUDRATE        500000UL             /* 500 kbps                  */

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
 * ISR configuration
 * Priority: 1 (lowest) .. 255 (highest)
 * InterruptLine: routes the MCMCAN interrupt source to a CPU interrupt line.
 * Each line must be unique within the CAN module.
 * ============================================================ */
#define XCP_CAN_RX_ISR_PRIORITY     60U
#define XCP_CAN_TX_ISR_PRIORITY     59U
#define XCP_CAN_RX_INTERRUPT_LINE   IfxCan_InterruptLine_0   /* FIFO0 new message  */
#define XCP_CAN_TX_INTERRUPT_LINE   IfxCan_InterruptLine_1   /* TX buffer complete */

/* ============================================================
 * CAN transceiver pin mapping
 * Example: TC375 Lite Kit — TXD -> P20.8, RXD -> P20.7
 * Pin names are MCU-variant-specific — check the iLLD IfxCan_PinMap.h
 * for your device (e.g. TC397: IfxCan_TXD00_P20_8_OUT).
 * Update to match your schematic.
 * ============================================================ */
#define XCP_CAN_TX_PIN          IfxCan_TXD00_P20_8_OUT
#define XCP_CAN_RX_PIN          IfxCan_RXD00B_P20_7_IN

#endif /* XCP_TRICORE_H */
