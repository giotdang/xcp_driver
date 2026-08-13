/*----------------------------------------------------------------------------
| File:   xcp_types.h
|
| Description:
|   Maps Vector XCP platform types (vuint8, vuint16, vuint32, vsint*) to the
|   standard iLLD types from Ifx_Types.h.
|
|   Include this header from xcp_cfg.h so it is resolved before XcpBasic.h
|   expands any of its vuintXX / vsintXX usages.
|
|   Mapping:
|     vuint8  -> uint8   (unsigned char,  8-bit)
|     vuint16 -> uint16  (unsigned short, 16-bit)
|     vuint32 -> uint32  (unsigned long,  32-bit)
|     vsint8  -> sint8   (signed char,    8-bit)
|     vsint16 -> sint16  (signed short,   16-bit)
|     vsint32 -> sint32  (signed long,    32-bit)
|
|   boolean, TRUE, FALSE are already supplied by Ifx_Types.h and therefore
|   do not need an alias here.
----------------------------------------------------------------------------*/

#ifndef XCP_TYPES_H
#define XCP_TYPES_H

#include "Ifx_Types.h"   /* uint8, uint16, uint32, sint8, sint16, sint32 */

typedef uint8  vuint8;
typedef uint16 vuint16;
typedef uint32 vuint32;
typedef sint8  vsint8;
typedef sint16 vsint16;
typedef sint32 vsint32;

#endif /* XCP_TYPES_H */
