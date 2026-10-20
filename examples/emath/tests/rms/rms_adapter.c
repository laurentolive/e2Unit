/*******************************************************************************
 * Custom adapters of the rms suite: the RMS context lives here, between calls.
 * Static data is reinitialised before each test (reset of the runner).
 ******************************************************************************/
#include "eunit.h"
#include "emath.h"

static emath_rms_t rms_ctx;

EUNIT_ADAPTER(rms_init)
{
    out[0] = emath_rms_init(&rms_ctx, (uint8_t)in[0]) ? 1 : 0;
}

EUNIT_ADAPTER(rms_update)
{
    out[0] = (int32_t)emath_rms_update(&rms_ctx, (int16_t)in[0]);
}
