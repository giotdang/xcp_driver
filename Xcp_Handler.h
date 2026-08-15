/*----------------------------------------------------------------------------
| File:   Xcp_Handler.h
|
| Description:
|   XCP v1.0 Protocol Layer — header.
|   Renamed and refactored from Vector Informatik XcpBasic v1.30.04.
|
|   Changes from XcpBasic:
|     - AUTOSAR-style Xcp_Init(const Xcp_ConfigType*) — PostBuild config
|     - Xcp_TransportLayerType / Xcp_ConfigType — callback-based transport
|     - Xcp_Background() polls transport Receive() instead of ISR dispatch
|     - All ApplXcp* macros replaced by ConfigType callbacks
|     - Public API renamed with Xcp_ prefix
----------------------------------------------------------------------------*/

#ifndef XCP_HANDLER_H
#define XCP_HANDLER_H

#include "xcp_cfg.h"
#include "xcp_def.h"

/*--------------------------------------------------------------------------*/
/* Version                                                                  */
/*--------------------------------------------------------------------------*/

#define CP_XCP_VERSION          0x0130u
#define CP_XCP_RELEASE_VERSION  0x04u

#ifndef XCP_VERSION
  #define XCP_VERSION 0x0100
#endif

#define XCP_TRANSPORT_LAYER_VERSION_USED  XCP_TRANSPORT_LAYER_VERSION

/*--------------------------------------------------------------------------*/
/* Endianness                                                               */
/*--------------------------------------------------------------------------*/

#if defined(XCP_CPUTYPE_BIGENDIAN) || defined(XCP_CPUTYPE_LITTLEENDIAN)
#else
  #if defined(C_CPUTYPE_BIGENDIAN)
    #define XCP_CPUTYPE_BIGENDIAN
  #endif
  #if defined(C_CPUTYPE_LITTLEENDIAN)
    #define XCP_CPUTYPE_LITTLEENDIAN
  #endif
#endif

/*--------------------------------------------------------------------------*/
/* XCP Protocol Command Codes                                               */
/*--------------------------------------------------------------------------*/

/* Standard */
#define CC_CONNECT              0xFF
#define CC_DISCONNECT           0xFE
#define CC_GET_STATUS           0xFD
#define CC_SYNC                 0xFC
#define CC_GET_COMM_MODE_INFO   0xFB
#define CC_GET_ID               0xFA
#define CC_SET_REQUEST          0xF9
#define CC_GET_SEED             0xF8
#define CC_UNLOCK               0xF7
#define CC_SET_MTA              0xF6
#define CC_UPLOAD               0xF5
#define CC_SHORT_UPLOAD         0xF4
#define CC_BUILD_CHECKSUM       0xF3
#define CC_TRANSPORT_LAYER_CMD  0xF2
#define CC_USER_CMD             0xF1

/* Calibration */
#define CC_DOWNLOAD             0xF0
#define CC_DOWNLOAD_NEXT        0xEF
#define CC_DOWNLOAD_MAX         0xEE
#define CC_SHORT_DOWNLOAD       0xED
#define CC_MODIFY_BITS          0xEC

/* Page switching (PAG) */
#define CC_SET_CAL_PAGE             0xEB
#define CC_GET_CAL_PAGE             0xEA
#define CC_GET_PAG_PROCESSOR_INFO   0xE9
#define CC_GET_SEGMENT_INFO         0xE8
#define CC_GET_PAGE_INFO            0xE7
#define CC_SET_SEGMENT_MODE         0xE6
#define CC_GET_SEGMENT_MODE         0xE5
#define CC_COPY_CAL_PAGE            0xE4

/* DAQ/STIM */
#define CC_CLEAR_DAQ_LIST           0xE3
#define CC_SET_DAQ_PTR              0xE2
#define CC_WRITE_DAQ                0xE1
#define CC_SET_DAQ_LIST_MODE        0xE0
#define CC_GET_DAQ_LIST_MODE        0xDF
#define CC_START_STOP_DAQ_LIST      0xDE
#define CC_START_STOP_SYNCH         0xDD
#define CC_GET_DAQ_CLOCK            0xDC
#define CC_READ_DAQ                 0xDB
#define CC_GET_DAQ_PROCESSOR_INFO   0xDA
#define CC_GET_DAQ_RESOLUTION_INFO  0xD9
#define CC_GET_DAQ_LIST_INFO        0xD8
#define CC_GET_DAQ_EVENT_INFO       0xD7
#define CC_FREE_DAQ                 0xD6
#define CC_ALLOC_DAQ                0xD5
#define CC_ALLOC_ODT                0xD4
#define CC_ALLOC_ODT_ENTRY          0xD3

/* Programming (PGM) */
#define CC_PROGRAM_START        0xD2
#define CC_PROGRAM_CLEAR        0xD1
#define CC_PROGRAM              0xD0
#define CC_PROGRAM_RESET        0xCF
#define CC_GET_PGM_PROCESSOR_INFO 0xCE
#define CC_GET_SECTOR_INFO      0xCD
#define CC_PROGRAM_PREPARE      0xCC
#define CC_PROGRAM_FORMAT       0xCB
#define CC_PROGRAM_NEXT         0xCA
#define CC_PROGRAM_MAX          0xC9
#define CC_PROGRAM_VERIFY       0xC8

/* Custom extension */
#define CC_WRITE_DAQ_MULTIPLE   0x81

/*--------------------------------------------------------------------------*/
/* Packet Identifiers (Slave → Master)                                      */
/*--------------------------------------------------------------------------*/

#define PID_RES     0xFF
#define PID_ERR     0xFE
#define PID_EV      0xFD
#define PID_SERV    0xFC

/*--------------------------------------------------------------------------*/
/* Command Return Codes                                                     */
/*--------------------------------------------------------------------------*/

#define CRC_CMD_SYNCH           0x00
#define CRC_CMD_BUSY            0x10
#define CRC_DAQ_ACTIVE          0x11
#define CRC_PRM_ACTIVE          0x12
#define CRC_CMD_UNKNOWN         0x20
#define CRC_CMD_SYNTAX          0x21
#define CRC_OUT_OF_RANGE        0x22
#define CRC_WRITE_PROTECTED     0x23
#define CRC_ACCESS_DENIED       0x24
#define CRC_ACCESS_LOCKED       0x25
#define CRC_PAGE_NOT_VALID      0x26
#define CRC_PAGE_MODE_NOT_VALID 0x27
#define CRC_SEGMENT_NOT_VALID   0x28
#define CRC_SEQUENCE            0x29
#define CRC_DAQ_CONDIF          0x2A
#define CRC_MEMORY_OVERFLOW     0x30
#define CRC_GENERIC             0x31
#define CRC_VERIFY              0x32

/*--------------------------------------------------------------------------*/
/* Event Codes                                                              */
/*--------------------------------------------------------------------------*/

#define EVC_RESUME_MODE         0x00
#define EVC_CLEAR_DAQ           0x01
#define EVC_STORE_DAQ           0x02
#define EVC_STORE_CAL           0x03
#define EVC_CMD_PENDING         0x05
#define EVC_DAQ_OVERLOAD        0x06
#define EVC_SESSION_TERMINATED  0x07
#define EVC_USER                0xFE
#define EVC_TRANSPORT           0xFF

#define SERV_RESET  0x00
#define SERV_TEXT   0x01

/*--------------------------------------------------------------------------*/
/* Resource Masks (CONNECT)                                                 */
/*--------------------------------------------------------------------------*/

#define RM_CAL_PAG  0x01
#define RM_DAQ      0x04
#define RM_STIM     0x08
#define RM_PGM      0x10

/*--------------------------------------------------------------------------*/
/* CommMode Basic (CONNECT)                                                 */
/*--------------------------------------------------------------------------*/

#define PI_MOTOROLA                     0x01
#define CMB_BYTE_ORDER                  (0x01u<<0)
#define CMB_ADDRESS_GRANULARITY         (0x03u<<1)
#define CMB_SLAVE_BLOCK_MODE            (0x01u<<6)
#define CMB_OPTIONAL                    (0x01u<<7)
#define CMB_ADDRESS_GRANULARITY_BYTE    (0<<1)
#define CMB_ADDRESS_GRANULARITY_WORD    (1<<1)
#define CMB_ADDRESS_GRANULARITY_DWORD   (2<<1)
#define CMB_ADDRESS_GRANULARITY_QWORD   (3<<1)

#define CMO_MASTER_BLOCK_MODE   0x01
#define CMO_INTERLEAVED_MODE    0x02

/*--------------------------------------------------------------------------*/
/* Session Status                                                           */
/*--------------------------------------------------------------------------*/

#define SS_STORE_CAL_REQ    0x0001u
#define SS_BLOCK_UPLOAD     0x0002u
#define SS_STORE_DAQ_REQ    0x0004u
#define SS_CLEAR_DAQ_REQ    0x0008u
#define SS_ERROR            0x0010u
#define SS_CONNECTED        0x0020u
#define SS_DAQ              0x0040u
#define SS_RESUME           0x0080u
#define SS_POLLING          0x0100u

/*--------------------------------------------------------------------------*/
/* Identifier Types (GET_ID)                                                */
/*--------------------------------------------------------------------------*/

#define IDT_ASCII           0
#define IDT_ASAM_NAME       1
#define IDT_ASAM_PATH       2
#define IDT_ASAM_URL        3
#define IDT_ASAM_UPLOAD     4
#define IDT_VECTOR_MAPNAMES 0xDB

/*--------------------------------------------------------------------------*/
/* Checksum Types                                                           */
/*--------------------------------------------------------------------------*/

#define XCP_CHECKSUM_TYPE_ADD11      0x01
#define XCP_CHECKSUM_TYPE_ADD12      0x02
#define XCP_CHECKSUM_TYPE_ADD14      0x03
#define XCP_CHECKSUM_TYPE_ADD22      0x04
#define XCP_CHECKSUM_TYPE_ADD24      0x05
#define XCP_CHECKSUM_TYPE_ADD44      0x06
#define XCP_CHECKSUM_TYPE_CRC16      0x07
#define XCP_CHECKSUM_TYPE_CRC16CCITT 0x08
#define XCP_CHECKSUM_TYPE_CRC32      0x09
#define XCP_CHECKSUM_TYPE_DLL        0xFF

/*--------------------------------------------------------------------------*/
/* CAL Page Mode                                                            */
/*--------------------------------------------------------------------------*/

#define CAL_ECU     0x01
#define CAL_XCP     0x02
#define CAL_ALL     0x80

#define PAG_PROPERTY_FREEZE             0x01
#define ECU_ACCESS_TYPE                 0x03
#define XCP_READ_ACCESS_TYPE            0x0C
#define XCP_WRITE_ACCESS_TYPE           0x30
#define ECU_ACCESS_NONE                 (0<<0)
#define ECU_ACCESS_WITHOUT              (1<<0)
#define ECU_ACCESS_WITH                 (2<<0)
#define ECU_ACCESS_DONT_CARE            (3<<0)
#define XCP_READ_ACCESS_NONE            (0<<2)
#define XCP_READ_ACCESS_WITHOUT         (1<<2)
#define XCP_READ_ACCESS_WITH            (2<<2)
#define XCP_READ_ACCESS_DONT_CARE       (3<<2)
#define XCP_WRITE_ACCESS_NONE           (0<<4)
#define XCP_WRITE_ACCESS_WITHOUT        (1<<4)
#define XCP_WRITE_ACCESS_WITH           (2<<4)
#define XCP_WRITE_ACCESS_DONT_CARE      (3<<4)
#define SEGMENT_FLAG_FREEZE             0x01

/*--------------------------------------------------------------------------*/
/* DAQ List Mode Flags                                                      */
/*--------------------------------------------------------------------------*/

#define DAQ_FLAG_SELECTED       0x01u
#define DAQ_FLAG_DIRECTION      0x02u
#define DAQ_FLAG_TIMESTAMP      0x10u
#define DAQ_FLAG_NO_PID         0x20u
#define DAQ_FLAG_RUNNING        0x40u
#define DAQ_FLAG_RESUME         0x80u
#define DAQ_FLAG_RESERVED       0x08u
#define DAQ_FLAG_OVERRUN        0x08u

/*--------------------------------------------------------------------------*/
/* DAQ Processor Info                                                       */
/*--------------------------------------------------------------------------*/

#define DAQ_PROPERTY_CONFIG_TYPE         0x01
#define DAQ_PROPERTY_PRESCALER           0x02
#define DAQ_PROPERTY_RESUME              0x04
#define DAQ_PROPERTY_BIT_STIM            0x08
#define DAQ_PROPERTY_TIMESTAMP           0x10
#define DAQ_PROPERTY_NO_PID              0x20
#define DAQ_PROPERTY_OVERLOAD_INDICATION 0xC0
#define DAQ_OVERLOAD_INDICATION_NONE     (0<<6)
#define DAQ_OVERLOAD_INDICATION_PID      (1<<6)
#define DAQ_OVERLOAD_INDICATION_EVENT    (2<<6)

#define DAQ_OPT_TYPE    0x0F
#define DAQ_EXT_TYPE    0x30
#define DAQ_HDR_TYPE    0xC0
#define DAQ_OPT_DEFAULT (0<<0)
#define DAQ_EXT_FREE    (0<<4)
#define DAQ_EXT_ODT     (1<<4)
#define DAQ_EXT_DAQ     (3<<4)
#define DAQ_HDR_PID         (0<<6)
#define DAQ_HDR_ODT_DAQB    (1<<6)
#define DAQ_HDR_ODT_DAQW    (2<<6)
#define DAQ_HDR_ODT_FIL_DAQW (3<<6)

/*--------------------------------------------------------------------------*/
/* DAQ Timestamp                                                            */
/*--------------------------------------------------------------------------*/

#define DAQ_TIMESTAMP_SIZE  0x07
#define DAQ_TIMESTAMP_FIXED 0x08
#define DAQ_TIMESTAMP_UNIT  0xF0
#define DAQ_TIMESTAMP_OFF   (0<<0)
#define DAQ_TIMESTAMP_BYTE  (1<<0)
#define DAQ_TIMESTAMP_WORD  (2<<0)
#define DAQ_TIMESTAMP_DWORD (4<<0)
#define DAQ_TIMESTAMP_UNIT_1NS    (0<<4)
#define DAQ_TIMESTAMP_UNIT_10NS   (1<<4)
#define DAQ_TIMESTAMP_UNIT_100NS  (2<<4)
#define DAQ_TIMESTAMP_UNIT_1US    (3<<4)
#define DAQ_TIMESTAMP_UNIT_10US   (4<<4)
#define DAQ_TIMESTAMP_UNIT_100US  (5<<4)
#define DAQ_TIMESTAMP_UNIT_1MS    (6<<4)
#define DAQ_TIMESTAMP_UNIT_10MS   (7<<4)
#define DAQ_TIMESTAMP_UNIT_100MS  (8<<4)
#define DAQ_TIMESTAMP_UNIT_1S     (9<<4)

/*--------------------------------------------------------------------------*/
/* DAQ List Properties                                                      */
/*--------------------------------------------------------------------------*/

#define DAQ_LIST_PREDEFINED     0x01
#define DAQ_LIST_FIXED_EVENT    0x02
#define DAQ_LIST_DIR_DAQ        0x04
#define DAQ_LIST_DIR_STIM       0x08
#define DAQ_EVENT_DIRECTION_DAQ      0x04
#define DAQ_EVENT_DIRECTION_STIM     0x08
#define DAQ_EVENT_DIRECTION_DAQ_STIM 0x0C

/*--------------------------------------------------------------------------*/
/* CRO/CRM Byte Accessor Macros                                             */
/*--------------------------------------------------------------------------*/

#define CRO_BYTE(x)   (pCmd->b[x])
#define CRM_BYTE(x)   (xcp.Crm.b[x])

#if defined(XCP_CPUTYPE_BIGENDIAN)
  #define CRO_WORD(x)         (((vuint16)pCmd->b[((x)*2)+0] << 8) | ((vuint8)pCmd->b[((x)*2)+1]))
  #define CRO_DWORD(x)        (((vuint32)pCmd->b[((x)*4)+0] << 24) | ((vuint32)pCmd->b[((x)*4)+1] << 16) | ((vuint16)pCmd->b[((x)*4)+2] << 8) | ((vuint8)pCmd->b[((x)*4)+3]))
  #define CRM_WORD(x)         (((vuint16)xcp.Crm.b[((x)*2)+0] << 8) | ((vuint8)xcp.Crm.b[((x)*2)+1]))
  #define CRM_WORD_WRITE(x,d) {xcp.Crm.b[((x)*2)+1] = ((vuint8)(d) & 0xFF); xcp.Crm.b[((x)*2)+0] = ((vuint8)((vuint16)(d) >> 8) & 0xFF);}
  #define CRM_DWORD(x)        (((vuint32)xcp.Crm.b[((x)*4)+0] << 24) | ((vuint32)xcp.Crm.b[((x)*4)+1] << 16) | ((vuint16)xcp.Crm.b[((x)*4)+2] << 8) | ((vuint8)xcp.Crm.b[((x)*4)+3]))
  #define CRM_DWORD_WRITE(x,d) {xcp.Crm.b[((x)*4)+3] = ((vuint8)((vuint32)(d) >> 0) & 0xFF); \
                                 xcp.Crm.b[((x)*4)+2] = ((vuint8)((vuint32)(d) >> 8) & 0xFF); \
                                 xcp.Crm.b[((x)*4)+1] = ((vuint8)((vuint32)(d) >> 16) & 0xFF); \
                                 xcp.Crm.b[((x)*4)+0] = ((vuint8)((vuint32)(d) >> 24) & 0xFF);}
#else
  #define CRO_WORD(x)          (pCmd->w[x])
  #define CRO_DWORD(x)         (pCmd->dw[x])
  #define CRM_WORD(x)          (xcp.Crm.w[x])
  #define CRM_WORD_WRITE(x,d)  (xcp.Crm.w[x] = (d))
  #define CRM_DWORD(x)         (xcp.Crm.dw[x])
  #define CRM_DWORD_WRITE(x,d) (xcp.Crm.dw[x] = (d))
#endif

#define CRO_CMD     CRO_BYTE(0)
#define CRM_CMD     CRM_BYTE(0)
#define CRM_ERR     CRM_BYTE(1)

/*--------------------------------------------------------------------------*/
/* Command Field Accessors — Standard                                       */
/*--------------------------------------------------------------------------*/

#define CRO_CONNECT_LEN             2
#define CRO_CONNECT_MODE            CRO_BYTE(1)
#define CRM_CONNECT_LEN             8
#define CRM_CONNECT_RESOURCE        CRM_BYTE(1)
#define CRM_CONNECT_COMM_BASIC      CRM_BYTE(2)
#define CRM_CONNECT_MAX_CTO_SIZE    CRM_BYTE(3)
#define CRM_CONNECT_MAX_DTO_SIZE    CRM_WORD(2)
#define CRM_CONNECT_MAX_DTO_SIZE_WRITE(size) CRM_WORD_WRITE(2, size)
#define CRM_CONNECT_PROTOCOL_VERSION    CRM_BYTE(6)
#define CRM_CONNECT_TRANSPORT_VERSION   CRM_BYTE(7)

#define CRO_DISCONNECT_LEN          1
#define CRM_DISCONNECT_LEN          1

#define CRO_GET_STATUS_LEN          1
#define CRM_GET_STATUS_LEN          6
#define CRM_GET_STATUS_STATUS       CRM_BYTE(1)
#define CRM_GET_STATUS_PROTECTION   CRM_BYTE(2)
#define CRM_GET_STATUS_CONFIG_ID    CRM_WORD(2)
#define CRM_GET_STATUS_CONFIG_ID_WRITE(id) CRM_WORD_WRITE(2, id)

#define CRO_SYNCH_LEN               1
#define CRM_SYNCH_LEN               2
#define CRM_SYNCH_RESULT            CRM_BYTE(1)

#define CRO_GET_COMM_MODE_INFO_LEN              1
#define CRM_GET_COMM_MODE_INFO_LEN              8
#define CRM_GET_COMM_MODE_INFO_COMM_OPTIONAL    CRM_BYTE(2)
#define CRM_GET_COMM_MODE_INFO_MAX_BS           CRM_BYTE(4)
#define CRM_GET_COMM_MODE_INFO_MIN_ST           CRM_BYTE(5)
#define CRM_GET_COMM_MODE_INFO_QUEUE_SIZE       CRM_BYTE(6)
#define CRM_GET_COMM_MODE_INFO_DRIVER_VERSION   CRM_BYTE(7)

#define CRO_GET_ID_LEN              2
#define CRO_GET_ID_TYPE             CRO_BYTE(1)
#define CRM_GET_ID_LEN              8
#define CRM_GET_ID_MODE             CRM_BYTE(1)
#define CRM_GET_ID_LENGTH           CRM_DWORD(1)
#define CRM_GET_ID_LENGTH_WRITE(l)  CRM_DWORD_WRITE(1, l)
#define CRM_GET_ID_DATA             (&CRM_BYTE(8))

#define CRO_SET_REQUEST_LEN         4
#define CRO_SET_REQUEST_MODE        CRO_BYTE(1)
#define CRO_SET_REQUEST_CONFIG_ID   CRO_WORD(1)
#define CRM_SET_REQUEST_LEN         1

#define CRO_GET_SEED_LEN            3
#define CRO_GET_SEED_MODE           CRO_BYTE(1)
#define CRO_GET_SEED_RESOURCE       CRO_BYTE(2)
#define CRM_GET_SEED_LEN            (CRM_GET_SEED_LENGTH+2u)
#define CRM_GET_SEED_LENGTH         CRM_BYTE(1)
#define CRM_GET_SEED_DATA           (&CRM_BYTE(2))

#define CRO_UNLOCK_LEN              8
#define CRO_UNLOCK_LENGTH           CRO_BYTE(1)
#define CRO_UNLOCK_KEY              (&CRO_BYTE(2))
#define CRM_UNLOCK_LEN              2
#define CRM_UNLOCK_PROTECTION       CRM_BYTE(1)

#define CRO_SET_MTA_LEN             8
#define CRO_SET_MTA_EXT             CRO_BYTE(3)
#define CRO_SET_MTA_ADDR            CRO_DWORD(1)
#define CRM_SET_MTA_LEN             1

#define CRM_UPLOAD_MAX_SIZE         ((vuint8)(kXcpMaxCTO-1))
#define CRO_UPLOAD_LEN              2
#define CRO_UPLOAD_SIZE             CRO_BYTE(1)
#define CRM_UPLOAD_LEN              1
#define CRM_UPLOAD_DATA             (&CRM_BYTE(1))

#define CRO_SHORT_UPLOAD_LEN        8
#define CRO_SHORT_UPLOAD_SIZE       CRO_BYTE(1)
#define CRO_SHORT_UPLOAD_EXT        CRO_BYTE(3)
#define CRO_SHORT_UPLOAD_ADDR       CRO_DWORD(1)
#define CRM_SHORT_UPLOAD_MAX_SIZE   ((vuint8)(kXcpMaxCTO-1))
#define CRM_SHORT_UPLOAD_LEN        1
#define CRM_SHORT_UPLOAD_DATA       (&CRM_BYTE(1))

#define CRO_BUILD_CHECKSUM_LEN      8
#define CRO_BUILD_CHECKSUM_SIZE     CRO_DWORD(1)
#define CRM_BUILD_CHECKSUM_LEN      8
#define CRM_BUILD_CHECKSUM_TYPE     CRM_BYTE(1)
#define CRM_BUILD_CHECKSUM_RESULT   CRM_DWORD(1)
#define CRM_BUILD_CHECKSUM_RESULT_WRITE(r) CRM_DWORD_WRITE(1, r)

/*--------------------------------------------------------------------------*/
/* Command Field Accessors — Calibration                                    */
/*--------------------------------------------------------------------------*/

#define CRO_DOWNLOAD_MAX_SIZE       ((vuint8)(kXcpMaxCTO-2))
#define CRO_DOWNLOAD_LEN            2
#define CRO_DOWNLOAD_SIZE           CRO_BYTE(1)
#define CRO_DOWNLOAD_DATA           (&CRO_BYTE(2))
#define CRM_DOWNLOAD_LEN            1

#define CRO_DOWNLOAD_NEXT_MAX_SIZE  ((vuint8)(kXcpMaxCTO-2))
#define CRO_DOWNLOAD_NEXT_LEN       2
#define CRO_DOWNLOAD_NEXT_SIZE      CRO_BYTE(1)
#define CRO_DOWNLOAD_NEXT_DATA      (&CRO_BYTE(2))
#define CRM_DOWNLOAD_NEXT_LEN       1

#define CRO_DOWNLOAD_MAX_MAX_SIZE   ((vuint8)(kXcpMaxCTO-1))
#define CRO_DOWNLOAD_MAX_DATA       (&CRO_BYTE(1))
#define CRM_DOWNLOAD_MAX_LEN        1

#define CRO_SHORT_DOWNLOAD_LEN      8
#define CRO_SHORT_DOWNLOAD_SIZE     CRO_BYTE(1)
#define CRO_SHORT_DOWNLOAD_EXT      CRO_BYTE(3)
#define CRO_SHORT_DOWNLOAD_ADDR     CRO_DWORD(1)
#define CRO_SHORT_DOWNLOAD_DATA     (&CRO_BYTE(8))
#define CRM_SHORT_DOWNLOAD_MAX_SIZE ((vuint8)(kXcpMaxCTO-8))
#define CRM_SHORT_DOWNLOAD_LEN      1

#define CRO_MODIFY_BITS_LEN         6
#define CRO_MODIFY_BITS_SHIFT       CRO_BYTE(1)
#define CRO_MODIFY_BITS_AND         CRO_WORD(1)
#define CRO_MODIFY_BITS_XOR         CRO_WORD(2)
#define CRM_MODIFY_BITS_LEN         1

/*--------------------------------------------------------------------------*/
/* Command Field Accessors — Page Switching                                 */
/*--------------------------------------------------------------------------*/

#define CRO_SET_CAL_PAGE_LEN        4
#define CRO_SET_CAL_PAGE_MODE       CRO_BYTE(1)
#define CRO_SET_CAL_PAGE_SEGMENT    CRO_BYTE(2)
#define CRO_SET_CAL_PAGE_PAGE       CRO_BYTE(3)
#define CRM_SET_CAL_PAGE_LEN        1

#define CRO_GET_CAL_PAGE_LEN        3
#define CRO_GET_CAL_PAGE_MODE       CRO_BYTE(1)
#define CRO_GET_CAL_PAGE_SEGMENT    CRO_BYTE(2)
#define CRM_GET_CAL_PAGE_LEN        4
#define CRM_GET_CAL_PAGE_PAGE       CRM_BYTE(3)

#define CRO_GET_PAG_PROCESSOR_INFO_LEN          1
#define CRM_GET_PAG_PROCESSOR_INFO_LEN          3
#define CRM_GET_PAG_PROCESSOR_INFO_MAX_SEGMENT  CRM_BYTE(1)
#define CRM_GET_PAG_PROCESSOR_INFO_PROPERTIES   CRM_BYTE(2)

#define CRO_GET_SEGMENT_INFO_LEN            5
#define CRO_GET_SEGMENT_INFO_MODE           CRO_BYTE(1)
#define CRO_GET_SEGMENT_INFO_NUMBER         CRO_BYTE(2)
#define CRO_GET_SEGMENT_INFO_MAPPING_INDEX  CRO_BYTE(3)
#define CRO_GET_SEGMENT_INFO_MAPPING        CRO_BYTE(4)
#define CRM_GET_SEGMENT_INFO_LEN            8
#define CRM_GET_SEGMENT_INFO_MAX_PAGES      CRM_BYTE(1)
#define CRM_GET_SEGMENT_INFO_ADDRESS_EXTENSION CRM_BYTE(2)
#define CRM_GET_SEGMENT_INFO_MAX_MAPPING    CRM_BYTE(3)
#define CRM_GET_SEGMENT_INFO_COMPRESSION    CRM_BYTE(4)
#define CRM_GET_SEGMENT_INFO_ENCRYPTION     CRM_BYTE(5)
#define CRM_GET_SEGMENT_INFO_MAPPING_INFO   CRM_DWORD(1)

#define CRO_GET_PAGE_INFO_LEN               4
#define CRO_GET_PAGE_INFO_SEGMENT_NUMBER    CRO_BYTE(2)
#define CRO_GET_PAGE_INFO_PAGE_NUMBER       CRO_BYTE(3)
#define CRM_GET_PAGE_INFO_LEN               3
#define CRM_GET_PAGE_INFO_PROPERTIES        CRM_BYTE(1)
#define CRM_GET_PAGE_INFO_INIT_SEGMENT      CRM_BYTE(2)

#define CRO_SET_SEGMENT_MODE_LEN        3
#define CRO_SET_SEGMENT_MODE_MODE       CRO_BYTE(1)
#define CRO_SET_SEGMENT_MODE_SEGMENT    CRO_BYTE(2)
#define CRM_SET_SEGMENT_MODE_LEN        1

#define CRO_GET_SEGMENT_MODE_LEN        3
#define CRO_GET_SEGMENT_MODE_SEGMENT    CRO_BYTE(2)
#define CRM_GET_SEGMENT_MODE_LEN        3
#define CRM_GET_SEGMENT_MODE_MODE       CRM_BYTE(2)

#define CRO_COPY_CAL_PAGE_LEN           5
#define CRO_COPY_CAL_PAGE_SRC_SEGMENT   CRO_BYTE(1)
#define CRO_COPY_CAL_PAGE_SRC_PAGE      CRO_BYTE(2)
#define CRO_COPY_CAL_PAGE_DEST_SEGMENT  CRO_BYTE(3)
#define CRO_COPY_CAL_PAGE_DEST_PAGE     CRO_BYTE(4)
#define CRM_COPY_CAL_PAGE_LEN           1

/*--------------------------------------------------------------------------*/
/* Command Field Accessors — DAQ/STIM                                       */
/*--------------------------------------------------------------------------*/

#define CRO_CLEAR_DAQ_LIST_LEN      4
#define CRO_CLEAR_DAQ_LIST_DAQ      CRO_WORD(1)
#define CRM_CLEAR_DAQ_LIST_LEN      1

#define CRO_SET_DAQ_PTR_LEN         6
#define CRO_SET_DAQ_PTR_DAQ         CRO_WORD(1)
#define CRO_SET_DAQ_PTR_ODT         CRO_BYTE(4)
#define CRO_SET_DAQ_PTR_IDX         CRO_BYTE(5)
#define CRM_SET_DAQ_PTR_LEN         1

#define CRO_WRITE_DAQ_LEN           8
#define CRO_WRITE_DAQ_BITOFFSET     CRO_BYTE(1)
#define CRO_WRITE_DAQ_SIZE          CRO_BYTE(2)
#define CRO_WRITE_DAQ_EXT           CRO_BYTE(3)
#define CRO_WRITE_DAQ_ADDR          CRO_DWORD(1)
#define CRM_WRITE_DAQ_LEN           1

#define CRO_WRITE_DAQ_MULTIPLE_LEN          8
#define CRO_WRITE_DAQ_MULTIPLE_COMMAND      CRO_BYTE(1)
#define CRO_WRITE_DAQ_MULTIPLE_NODAQ        CRO_BYTE(2)
#define CRO_WRITE_DAQ_MULTIPLE_BITOFFSET(i) CRO_BYTE(8 + (8*(i)))
#define CRO_WRITE_DAQ_MULTIPLE_SIZE(i)      CRO_BYTE(9 + (8*(i)))
#define CRO_WRITE_DAQ_MULTIPLE_EXT(i)       CRO_BYTE(10 + (8*(i)))
#define CRO_WRITE_DAQ_MULTIPLE_ADDR(i)      CRO_DWORD(1 + (2*(i)))
#define CRM_WRITE_DAQ_MULTIPLE_LEN          1

#define CRO_SET_DAQ_LIST_MODE_LEN           8
#define CRO_SET_DAQ_LIST_MODE_MODE          CRO_BYTE(1)
#define CRO_SET_DAQ_LIST_MODE_DAQ           CRO_WORD(1)
#define CRO_SET_DAQ_LIST_MODE_EVENTCHANNEL  CRO_WORD(2)
#define CRO_SET_DAQ_LIST_MODE_PRESCALER     CRO_BYTE(6)
#define CRO_SET_DAQ_LIST_MODE_PRIORITY      CRO_BYTE(7)
#define CRM_SET_DAQ_LIST_MODE_LEN           6

#define CRO_GET_DAQ_LIST_MODE_LEN           4
#define CRO_GET_DAQ_LIST_MODE_DAQ           CRO_WORD(1)
#define CRM_GET_DAQ_LIST_MODE_LEN           8
#define CRM_GET_DAQ_LIST_MODE_MODE          CRM_BYTE(1)
#define CRM_GET_DAQ_LIST_MODE_EVENTCHANNEL  CRM_WORD(2)
#define CRM_GET_DAQ_LIST_MODE_EVENTCHANNEL_WRITE(ch) CRM_WORD_WRITE(2, ch)
#define CRM_GET_DAQ_LIST_MODE_PRESCALER     CRM_BYTE(6)
#define CRM_GET_DAQ_LIST_MODE_PRIORITY      CRM_BYTE(7)

#define CRO_START_STOP_LEN          4
#define CRO_START_STOP_MODE         CRO_BYTE(1)
#define CRO_START_STOP_DAQ          CRO_WORD(1)
#define CRM_START_STOP_LEN          2
#define CRM_START_STOP_FIRST_PID    CRM_BYTE(1)

#define CRO_START_STOP_SYNC_LEN     2
#define CRO_START_STOP_SYNC_MODE    CRO_BYTE(1)
#define CRM_START_STOP_SYNC_LEN     1

#define CRO_GET_DAQ_CLOCK_LEN       1
#define CRM_GET_DAQ_CLOCK_LEN       8
#define CRM_GET_DAQ_CLOCK_TIME      CRM_DWORD(1)
#define CRM_GET_DAQ_CLOCK_TIME_WRITE(t) CRM_DWORD_WRITE(1, t)

#define CRO_READ_DAQ_LEN            1
#define CRM_READ_DAQ_LEN            8
#define CRM_READ_DAQ_BITOFFSET      CRM_BYTE(1)
#define CRM_READ_DAQ_SIZE           CRM_BYTE(2)
#define CRM_READ_DAQ_EXT            CRM_BYTE(3)
#define CRM_READ_DAQ_ADDR           CRM_DWORD(1)

#define CRO_GET_DAQ_PROCESSOR_INFO_LEN              1
#define CRM_GET_DAQ_PROCESSOR_INFO_LEN              8
#define CRM_GET_DAQ_PROCESSOR_INFO_PROPERTIES       CRM_BYTE(1)
#define CRM_GET_DAQ_PROCESSOR_INFO_MAX_DAQ          CRM_WORD(1)
#define CRM_GET_DAQ_PROCESSOR_INFO_MAX_DAQ_WRITE(n) CRM_WORD_WRITE(1, n)
#define CRM_GET_DAQ_PROCESSOR_INFO_MAX_EVENT        CRM_WORD(2)
#define CRM_GET_DAQ_PROCESSOR_INFO_MAX_EVENT_WRITE(e) CRM_WORD_WRITE(2, e)
#define CRM_GET_DAQ_PROCESSOR_INFO_MIN_DAQ          CRM_BYTE(6)
#define CRM_GET_DAQ_PROCESSOR_INFO_DAQ_KEY_BYTE     CRM_BYTE(7)

#define CRO_GET_DAQ_RESOLUTION_INFO_LEN                     1
#define CRM_GET_DAQ_RESOLUTION_INFO_LEN                     8
#define CRM_GET_DAQ_RESOLUTION_INFO_GRANULARITY_DAQ         CRM_BYTE(1)
#define CRM_GET_DAQ_RESOLUTION_INFO_MAX_SIZE_DAQ            CRM_BYTE(2)
#define CRM_GET_DAQ_RESOLUTION_INFO_GRANULARITY_STIM        CRM_BYTE(3)
#define CRM_GET_DAQ_RESOLUTION_INFO_MAX_SIZE_STIM           CRM_BYTE(4)
#define CRM_GET_DAQ_RESOLUTION_INFO_TIMESTAMP_MODE          CRM_BYTE(5)
#define CRM_GET_DAQ_RESOLUTION_INFO_TIMESTAMP_TICKS         CRM_WORD(3)
#define CRM_GET_DAQ_RESOLUTION_INFO_TIMESTAMP_TICKS_WRITE(t) CRM_WORD_WRITE(3, t)

#define CRO_GET_DAQ_LIST_INFO_LEN           4
#define CRO_GET_DAQ_LIST_INFO_DAQ           CRO_WORD(1)
#define CRM_GET_DAQ_LIST_INFO_LEN           6
#define CRM_GET_DAQ_LIST_INFO_PROPERTIES    CRM_BYTE(1)
#define CRM_GET_DAQ_LIST_INFO_MAX_ODT       CRM_BYTE(2)
#define CRM_GET_DAQ_LIST_INFO_MAX_ODT_ENTRY CRM_BYTE(3)
#define CRM_GET_DAQ_LIST_INFO_FIXED_EVENT   CRM_WORD(2)

#define CRO_GET_DAQ_EVENT_INFO_LEN          4
#define CRO_GET_DAQ_EVENT_INFO_EVENT        CRO_WORD(1)
#define CRM_GET_DAQ_EVENT_INFO_LEN          7
#define CRM_GET_DAQ_EVENT_INFO_PROPERTIES   CRM_BYTE(1)
#define CRM_GET_DAQ_EVENT_INFO_TYPE         CRM_BYTE(2)
#define CRM_GET_DAQ_EVENT_INFO_MAX_DAQ_LIST CRM_BYTE(3)
#define CRM_GET_DAQ_EVENT_INFO_NAME_LENGTH  CRM_BYTE(4)
#define CRM_GET_DAQ_EVENT_INFO_TIME_CYCLE   CRM_BYTE(5)
#define CRM_GET_DAQ_EVENT_INFO_TIME_UNIT    CRM_BYTE(6)
#define CRM_GET_DAQ_EVENT_INFO_PRIORITY     CRM_BYTE(7)

#define CRO_FREE_DAQ_LEN                    1
#define CRM_FREE_DAQ_LEN                    1
#define CRO_ALLOC_DAQ_LEN                   4
#define CRO_ALLOC_DAQ_COUNT                 CRO_WORD(1)
#define CRM_ALLOC_DAQ_LEN                   1
#define CRO_ALLOC_ODT_LEN                   4
#define CRO_ALLOC_ODT_DAQ                   CRO_WORD(1)
#define CRO_ALLOC_ODT_COUNT                 CRO_BYTE(4)
#define CRM_ALLOC_ODT_LEN                   1
#define CRO_ALLOC_ODT_ENTRY_LEN             6
#define CRO_ALLOC_ODT_ENTRY_DAQ             CRO_WORD(1)
#define CRO_ALLOC_ODT_ENTRY_ODT             CRO_BYTE(4)
#define CRO_ALLOC_ODT_ENTRY_COUNT           CRO_BYTE(5)
#define CRM_ALLOC_ODT_ENTRY_LEN             1

/*--------------------------------------------------------------------------*/
/* Memory / Pointer Qualifiers                                              */
/*--------------------------------------------------------------------------*/

#ifndef MEMORY_ROM
  #define MEMORY_ROM const
#endif
#ifndef V_MEMROM0
  #define V_MEMROM0
#endif
#ifndef MEMORY_CONST
  #define MEMORY_CONST
#endif
#ifndef XCP_MEMORY_FAR
  #ifdef MEMORY_FAR
    #define XCP_MEMORY_FAR MEMORY_FAR
  #else
    #define XCP_MEMORY_FAR
  #endif
#endif
#ifndef XCP_FAR
  #define XCP_FAR
#endif
#ifndef RAM
  #define RAM
#endif
#ifndef DAQBYTEPTR
  #define DAQBYTEPTR vuint8 XCP_MEMORY_FAR *
#endif
#ifndef MTABYTEPTR
  #define MTABYTEPTR vuint8 XCP_MEMORY_FAR *
#endif
#ifndef BYTEPTR
  #define BYTEPTR vuint8 *
#endif
#ifndef ROMBYTEPTR
  #define ROMBYTEPTR vuint8 const *
#endif

/*--------------------------------------------------------------------------*/
/* Assert / Profile stubs                                                   */
/*--------------------------------------------------------------------------*/

#ifndef XCP_ASSERT
  #define XCP_ASSERT(x)
#endif
#ifndef XCP_PRINT
  #define XCP_PRINT(x)
#endif
#ifndef BEGIN_PROFILE
  #define BEGIN_PROFILE(i)
#endif
#ifndef END_PROFILE
  #define END_PROFILE(i)
#endif

/*--------------------------------------------------------------------------*/
/* Buffer size checks                                                       */
/*--------------------------------------------------------------------------*/

#if (kXcpMaxCTO > 255)
  #error "kXcpMaxCTO must be < 256"
#endif
#if (kXcpMaxCTO < 0x08)
  #error "kXcpMaxCTO must be >= 8"
#endif
#if (kXcpMaxDTO > 255)
  #error "kXcpMaxDTO must be < 256"
#endif
#if (kXcpMaxDTO < 0x08)
  #error "kXcpMaxDTO must be >= 8"
#endif

#if defined(XCP_ENABLE_DAQ)
  #ifndef kXcpDaqMemSize
    #error "Please define kXcpDaqMemSize"
  #endif
  #if !defined(XCP_ENABLE_SEND_QUEUE) && !defined(XCP_DISABLE_SEND_QUEUE)
    #define XCP_ENABLE_SEND_QUEUE
  #endif
  #ifdef XCP_ENABLE_SEND_QUEUE
    #define XCP_DISABLE_SEND_DIRECT
  #endif
  #ifndef XCP_MAX_ODT_ENTRY_SIZE
    #ifdef XCP_ENABLE_DAQ_HDR_ODT_DAQ
      #define XCP_MAX_ODT_ENTRY_SIZE (kXcpMaxDTO-2)
    #else
      #define XCP_MAX_ODT_ENTRY_SIZE (kXcpMaxDTO-1)
    #endif
  #endif
#endif

/*--------------------------------------------------------------------------*/
/* Packet Type Definitions                                                  */
/*--------------------------------------------------------------------------*/

typedef struct {
    vuint8 b[kXcpMaxDTO];
    vuint8 l;
} tXcpDto;

typedef union {
    vuint8  b[ ((kXcpMaxCTO + 3) & 0xFFC)     ];
    vuint16 w[ ((kXcpMaxCTO + 3) & 0xFFC) / 2 ];
    vuint32 dw[((kXcpMaxCTO + 3) & 0xFFC) / 4 ];
} tXcpCto;

/*--------------------------------------------------------------------------*/
/* DAQ Type Definitions                                                     */
/*--------------------------------------------------------------------------*/

#if defined(XCP_ENABLE_DAQ)

typedef struct {
    vuint16 firstOdtEntry;
    vuint16 lastOdtEntry;
} tXcpOdt;

#if defined(XCP_ENABLE_ODT_SIZE_WORD)
  typedef vuint16 tXcpOdtIdx;
  typedef vuint16 tXcpOdtCnt;
#else
  typedef vuint8  tXcpOdtIdx;
  typedef vuint8  tXcpOdtCnt;
#endif

typedef struct {
    tXcpOdtIdx lastOdt;
    tXcpOdtIdx firstOdt;
    vuint8     flags;
#if !defined(kXcpMaxEvent) || defined(XCP_ENABLE_DAQ_PRESCALER)
    vuint8     eventChannel;
#endif
#if defined(XCP_ENABLE_DAQ_PRESCALER)
    vuint8     prescaler;
    vuint8     cycle;
#endif
} tXcpDaqList;

#endif /* XCP_ENABLE_DAQ */

typedef struct {
    vuint8 ActiveTl;
#if defined(XCP_ENABLE_DAQ)
    vuint8       DaqCount;
    tXcpOdtCnt   OdtCount;
    vuint16      OdtEntryCount;
#if defined(kXcpMaxEvent) && !defined(XCP_ENABLE_DAQ_PRESCALER)
    vuint8       EventDaq[kXcpMaxEvent];
#endif
    union {
        vuint8      b[kXcpDaqMemSize];
        tXcpDaqList DaqList[kXcpDaqMemSize/sizeof(tXcpDaqList)];
    } u;
#endif
} tXcpDaq;

/*--------------------------------------------------------------------------*/
/* DAQ Accessor Shorthand Macros                                            */
/*--------------------------------------------------------------------------*/

#if defined(XCP_ENABLE_DAQ)

#if defined(XCP_ENABLE_DAQ_TIMESTAMP)
  #if (kXcpDaqTimestampSize == DAQ_TIMESTAMP_BYTE)
    typedef vuint8  XcpDaqTimestampType;
    #define XcpDaqTimestampSize 1
  #elif (kXcpDaqTimestampSize == DAQ_TIMESTAMP_WORD)
    typedef vuint16 XcpDaqTimestampType;
    #define XcpDaqTimestampSize 2
  #elif (kXcpDaqTimestampSize == DAQ_TIMESTAMP_DWORD)
    typedef vuint32 XcpDaqTimestampType;
    #define XcpDaqTimestampSize 4
  #else
    #error "kXcpDaqTimestampSize invalid"
  #endif
#endif

#define DaqListOdtEntryCount(j) ((xcp.pOdt[j].lastOdtEntry - xcp.pOdt[j].firstOdtEntry) + 1)
#define DaqListOdtLastEntry(j)  (xcp.pOdt[j].lastOdtEntry)
#define DaqListOdtFirstEntry(j) (xcp.pOdt[j].firstOdtEntry)
#define OdtEntrySize(n)         (xcp.pOdtEntrySize[n])
#define OdtEntryAddr(n)         (xcp.pOdtEntryAddr[n])
#define DaqListOdtCount(i)      ((xcp.Daq.u.DaqList[i].lastOdt - xcp.Daq.u.DaqList[i].firstOdt) + 1)
#define DaqListLastOdt(i)       xcp.Daq.u.DaqList[i].lastOdt
#define DaqListFirstOdt(i)      xcp.Daq.u.DaqList[i].firstOdt
#define DaqListFirstPid(i)      xcp.Daq.u.DaqList[i].firstOdt
#define DaqListFlags(i)         xcp.Daq.u.DaqList[i].flags
#define DaqListEventChannel(i)  xcp.Daq.u.DaqList[i].eventChannel
#define DaqListPrescaler(i)     xcp.Daq.u.DaqList[i].prescaler
#define DaqListCycle(i)         xcp.Daq.u.DaqList[i].cycle

#endif /* XCP_ENABLE_DAQ */

/*--------------------------------------------------------------------------*/
/* Return Values                                                            */
/*--------------------------------------------------------------------------*/

#define XCP_CMD_DENIED          0
#define XCP_CMD_OK              1
#define XCP_CMD_PENDING         2
#define XCP_CMD_SYNTAX          3
#define XCP_CMD_BUSY            4
#define XCP_CMD_UNKNOWN         5
#define XCP_CMD_OUT_OF_RANGE    6
#define XCP_MODE_NOT_VALID      7
#define XCP_CMD_ERROR           0xFF

#define XCP_OK                  0
#define XCP_NOT_OK              1

#define XCP_EVENT_NOP           0x00u
#define XCP_EVENT_DAQ           0x01u
#define XCP_EVENT_DAQ_OVERRUN   0x02u
#define XCP_EVENT_DAQ_TIMEOUT   0x04u
#define XCP_EVENT_STIM          0x08u
#define XCP_EVENT_STIM_OVERRUN  0x10u

#define XCP_CRM_REQUEST         0x01u
#define XCP_DTO_REQUEST         0x02u
#define XCP_EVT_REQUEST         0x04u
#define XCP_CRM_PENDING         0x10u
#define XCP_DTO_PENDING         0x20u
#define XCP_EVT_PENDING         0x40u
#define XCP_SEND_PENDING        (XCP_DTO_PENDING|XCP_CRM_PENDING|XCP_EVT_PENDING)

/*--------------------------------------------------------------------------*/
/* Protocol Driver State Type                                               */
/*--------------------------------------------------------------------------*/

typedef vuint16 SessionStatusType;

typedef struct {
    tXcpCto Crm;
    vuint8  CrmLen;

#if defined(XCP_ENABLE_SEND_EVENT) || defined(XCP_ENABLE_SERV_TEXT)
    tXcpCto Ev;
    vuint8  EvLen;
#endif

    SessionStatusType SessionStatus;
    MTABYTEPTR        Mta;

#if defined(XCP_ENABLE_SEED_KEY)
    vuint8 ProtectionStatus;
#endif

#if defined(XCP_ENABLE_CHECKSUM) && !defined(XCP_ENABLE_CUSTOM_CRC)
    vuint16             CheckSumSize;
    tXcpChecksumSumType CheckSum;
#endif

    tXcpDaq Daq;

#if defined(XCP_ENABLE_DAQ)
    tXcpOdt    *pOdt;
    DAQBYTEPTR *pOdtEntryAddr;
    vuint8     *pOdtEntrySize;

#if defined(XCP_ENABLE_SEND_QUEUE)
    tXcpDto *pQueue;
    vuint16  QueueSize;
    vuint16  QueueLen;
    vuint16  QueueRp;
    volatile vuint8 SendStatus;
#endif

    vuint16 DaqListPtr;
#endif

} tXcpData;

/*--------------------------------------------------------------------------*/
/* AUTOSAR-style Config Types                                               */
/*--------------------------------------------------------------------------*/

#include "port/tricore_illd/xcp_can_tricore.h"

typedef struct {
    const XcpCan_ConfigType *CanConfig;
    void    (*Transmit)(vuint8 len, const BYTEPTR data);
    vuint8  (*Receive)(vuint8 *len, BYTEPTR data);
    vuint32 (*GetTimestamp)(void);
    void    (*EnterCritical)(void);
    void    (*ExitCritical)(void);
} Xcp_TransportLayerType;

typedef struct {
    const char                    *StationId;
    vuint8                         StationIdLength;
    const Xcp_TransportLayerType  *TransportLayer;

    BYTEPTR (*GetPointer)(vuint8 addrExt, vuint32 addr);

#if defined(XCP_ENABLE_CALIBRATION_MEM_ACCESS_BY_APPL)
    vuint8 (*CalibrationWrite)(BYTEPTR addr, vuint8 size, const BYTEPTR data);
    vuint8 (*CalibrationRead)(BYTEPTR addr, vuint8 size, BYTEPTR data);
#endif

#if defined(XCP_ENABLE_CALIBRATION_PAGE)
    vuint8 (*GetCalPage)(vuint8 segment, vuint8 mode);
    vuint8 (*SetCalPage)(vuint8 segment, vuint8 page, vuint8 mode);
#if defined(XCP_ENABLE_PAGE_COPY)
    vuint8 (*CopyCalPage)(vuint8 srcSeg, vuint8 srcPage, vuint8 dstSeg, vuint8 dstPage);
#endif
#endif
} Xcp_ConfigType;

/*--------------------------------------------------------------------------*/
/* Version constants (exported from Xcp_Handler.c)                         */
/*--------------------------------------------------------------------------*/

V_MEMROM0 extern const vuint8 kXcpMainVersion;
V_MEMROM0 extern const vuint8 kXcpSubVersion;
V_MEMROM0 extern const vuint8 kXcpReleaseVersion;

/*--------------------------------------------------------------------------*/
/* Public API                                                               */
/*--------------------------------------------------------------------------*/

extern void Xcp_Init(const Xcp_ConfigType *ConfigPtr);
extern void Xcp_Exit(void);

extern void  Xcp_Command(const vuint32 *pCommand);
extern vuint8 Xcp_SendCallBack(void);
extern vuint8 Xcp_Background(void);
extern vuint8 Xcp_Event(vuint8 event);
extern void  Xcp_Disconnect(void);
extern void  Xcp_SendCrm(void);

extern vuint8         Xcp_GetState(void);
extern SessionStatusType Xcp_GetSessionStatus(void);

extern void  Xcp_SetActiveTl(vuint8 MaxCto, vuint8 MaxDto, vuint8 ActiveTl);
extern vuint8 Xcp_GetActiveTl(void);

#if defined(XCP_ENABLE_SEND_EVENT)
extern void Xcp_SendEvent(vuint8 evc, const BYTEPTR c, vuint8 len);
#endif

#if defined(XcpMemCpy)
#else
extern void XcpMemCpy(DAQBYTEPTR dest, const DAQBYTEPTR src, vuint8 n);
#endif
#if defined(XcpMemSet)
#else
extern void XcpMemSet(BYTEPTR p, vuint16 n, vuint8 b);
#endif

#if defined(XCP_ENABLE_DAQ)
  #if defined(XcpSendDto)
  #else
extern void XcpSendDto(const tXcpDto *dto);
  #endif
#endif

#endif /* XCP_HANDLER_H */
