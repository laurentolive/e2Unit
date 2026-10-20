/*******************************************************************************
 * emath - saturated integer power (exponentiation by squaring)
 ******************************************************************************/
#include "emath.h"

int32_t emath_pow(int32_t base, uint8_t exp)
{
    if (base == 0) {
        return (exp == 0u) ? 1 : 0;
    }
    if (base == 1) {
        return 1;
    }
    if (base == -1) {
        return ((exp & 1u) != 0u) ? -1 : 1;
    }

    const bool negative = (base < 0) && ((exp & 1u) != 0u);
    const uint64_t limit = negative ? 2147483648u : 2147483647u;
    const int32_t saturated = negative ? INT32_MIN : INT32_MAX;
    uint64_t m = (base < 0) ? (uint64_t)(-(int64_t)base) : (uint64_t)base; /* |base| >= 2 */
    uint64_t r = 1u;
    uint8_t e = exp;

    while (e != 0u) {
        if ((e & 1u) != 0u) {
            r *= m;                       /* r, m <= 2^31: no 64-bit overflow */
            if (r > limit) {
                return saturated;
            }
        }
        e = (uint8_t)(e >> 1);
        if (e != 0u) {
            m *= m;
            if (m > limit) {              /* m will still be multiplied into r */
                return saturated;
            }
        }
    }
    return negative ? (int32_t)(-(int64_t)r) : (int32_t)r;
}
