/*----------------------------------------------------------------------------
| Project: XCP_Delivery
|
|  Description:   Implementation of the XCP Protocol Layer
|                 XCP V1.0 slave device driver
|                 Basic Version
|
|-----------------------------------------------------------------------------
| Copyright (c) by Vector Informatik GmbH.  All rights reserved.
----------------------------------------------------------------------------*/
#if defined ( __XCP_PAR_H__ )
#else
#define __XCP_PAR_H__

/* Station ID returned by the GET_ID command (CANape uses this to identify the ECU).
 * Must match the A2L filename without extension. */
extern const char kXcpStationId[];

#define kXcpStationIdLength  ((vuint8)sizeof(kXcpStationId) - 1U)


#endif
