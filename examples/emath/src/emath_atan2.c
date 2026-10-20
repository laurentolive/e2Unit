/*******************************************************************************
 * emath - atan2
 *
 * Octant reduction: z = min/max in [0, 1] (Q15), then
 * atan(z) ~ z (d1 + z^2 (d3 + z^2 (d5 + z^2 (d7 + z^2 d9)))) in binary angle
 * units, coefficients scaled by 2^16.
 ******************************************************************************/
#include "emath.h"

static const int64_t ATAN_D[5] = {
    683473932,  /* d1 */
    -225785359, /* d3 */
    123152684,  /* d5 */
    -58213074,  /* d7 */
    14250578,   /* d9 */
};

/* atan(z) for z in [0, 32768] (Q15), result in [0, 8192] */
static int32_t atan_unit(int32_t z)
{
    const int64_t z2 = ((int64_t)z * z) >> 15;
    int64_t acc = ATAN_D[4];
    for (int k = 3; k >= 0; k--) {
        acc = ATAN_D[k] + ((acc * z2) >> 15);
    }
    return (int32_t)((((acc * z) >> 15) + (1 << 15)) >> 16);
}

int16_t emath_atan2(int16_t y, int16_t x)
{
    const int32_t ax = (x < 0) ? -(int32_t)x : (int32_t)x;
    const int32_t ay = (y < 0) ? -(int32_t)y : (int32_t)y;
    int32_t a;

    if ((ax == 0) && (ay == 0)) {
        return 0;
    }
    if (ay <= ax) {
        a = atan_unit((ay << 15) / ax);
    } else {
        a = 16384 - atan_unit((ax << 15) / ay);
    }
    if (x < 0) {
        a = 32768 - a;
    }
    if (y < 0) {
        a = -a;
    }
    return (int16_t)(uint16_t)(uint32_t)a; /* 32768 (pi) wraps to -32768 */
}
