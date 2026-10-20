/*******************************************************************************
 * emath - sliding window RMS
 *
 * Keeps the sum of the squares of the last 2^log2n samples (64-bit: up to
 * 256 * 2^30), RMS = floor(sqrt(sum >> log2n)).
 ******************************************************************************/
#include <string.h>
#include "emath.h"

bool emath_rms_init(emath_rms_t *ctx, uint8_t log2n)
{
    if (log2n > EMATH_RMS_LOG2N_MAX) {
        return false;
    }
    memset(ctx, 0, sizeof *ctx);
    ctx->log2n = log2n;
    return true;
}

uint16_t emath_rms_update(emath_rms_t *ctx, int16_t x)
{
    const uint16_t mask = (uint16_t)((1u << ctx->log2n) - 1u);
    const int32_t old = ctx->buf[ctx->idx];

    ctx->sum_sq64 -= (uint64_t)(old * old);
    ctx->sum_sq64 += (uint64_t)((int32_t)x * (int32_t)x);
    ctx->buf[ctx->idx] = x;
    ctx->idx = (uint16_t)((ctx->idx + 1u) & mask);

    const uint32_t mean = (uint32_t)(ctx->sum_sq64 >> ctx->log2n); /* <= 2^30 */
    return emath_isqrt32(mean);
}
