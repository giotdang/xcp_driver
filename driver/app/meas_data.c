/*----------------------------------------------------------------------------
| File:   meas_data.c
|
| Description:
|   DAQ measurement signal storage definition. Mirrors cal_data.c's
|   generated-initialiser pattern, applied to MEAS_PARAMS_TABLE.
----------------------------------------------------------------------------*/

#include "driver/app/meas_data.h"

/* ============================================================
 * measData — single RAM instance, all-zero / neutral defaults.
 *
 *   MEAS_PARAM(type, name, ...)       ->  .name = __VA_ARGS__,
 *   MEAS_ARRAY(type, name, size, ...) ->  .name = { __VA_ARGS__ },
 * ============================================================ */
volatile MeasData_t measData =
{
#define MEAS_PARAM(type, name, ...)       .name = __VA_ARGS__,
#define MEAS_ARRAY(type, name, size, ...) .name = { __VA_ARGS__ },
MEAS_PARAMS_TABLE
#undef MEAS_PARAM
#undef MEAS_ARRAY
};
