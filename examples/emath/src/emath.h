/*******************************************************************************
 * emath - fixed-point math library used as e2Unit example
 *
 * Angles are binary angles: one turn = 65536, so int16_t covers [-pi, pi[.
 * Q15 values: 32767 = 1.0.
 ******************************************************************************/
#ifndef EMATH_H
#define EMATH_H

#include <stdbool.h>
#include <stdint.h>

/* sin of a binary angle, Q15 result, |error| <= 2 LSB */
int16_t emath_sin(int16_t angle);

/* a * b in Q15, rounded to nearest, saturated: (-1) * (-1) = 32767 */
int16_t emath_mul_q15(int16_t a, int16_t b);

/* atan2(y, x) as a binary angle, |error| <= 1 LSB, atan2(0, 0) = 0 */
int16_t emath_atan2(int16_t y, int16_t x);

/* base^exp, saturated to [INT32_MIN, INT32_MAX], 0^0 = 1 */
int32_t emath_pow(int32_t base, uint8_t exp);

/* floor(sqrt(x)) */
uint16_t emath_isqrt32(uint32_t x);

/* Sliding RMS over the last 2^log2n samples (zeros before the first ones) */
#define EMATH_RMS_LOG2N_MAX 8u

typedef struct {
    int16_t  buf[1u << EMATH_RMS_LOG2N_MAX];
    uint64_t sum_sq64; /* sum of the squares of the window, <= 2^38 */
    uint16_t idx;
    uint8_t  log2n;
} emath_rms_t;

/* false if log2n > EMATH_RMS_LOG2N_MAX */
bool emath_rms_init(emath_rms_t *ctx, uint8_t log2n);

/* push one sample, return the RMS of the window */
uint16_t emath_rms_update(emath_rms_t *ctx, int16_t x);

#endif /* EMATH_H */
