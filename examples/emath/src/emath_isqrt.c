/*******************************************************************************
 * emath - integer square root (digit by digit, no division)
 ******************************************************************************/
#include "emath.h"

uint16_t emath_isqrt32(uint32_t x)
{
    uint32_t rem = x;
    uint32_t root = 0u;
    uint32_t bit = 1u << 30;

    while (bit > rem) {
        bit >>= 2;
    }
    while (bit != 0u) {
        if (rem >= root + bit) {
            rem -= root + bit;
            root = (root >> 1) + bit;
        } else {
            root >>= 1;
        }
        bit >>= 2;
    }
    return (uint16_t)root;
}
