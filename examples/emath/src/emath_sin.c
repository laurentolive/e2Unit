/*******************************************************************************
 * emath - sine
 *
 * Quadrant reduction, then sin(pi/2 t) ~ t (c1 + t^2 (c3 + t^2 (c5 + t^2 c7)))
 * on t in [0, 1] (Q14), minimax coefficients in Q16.
 ******************************************************************************/
#include "emath.h"

#define SIN_C1  102943 /*  1.57079102 */
#define SIN_C3 (-42329) /* -0.64589291 */
#define SIN_C5   5206  /*  0.07943448 */
#define SIN_C7  (-284) /* -0.00433318 */

int16_t emath_sin(int16_t angle)
{
    const uint16_t ua = (uint16_t)angle;
    const uint16_t quadrant = (uint16_t)(ua >> 14);
    int32_t x = (int32_t)(ua & 0x3FFFu);          /* [0, 16384[ = [0, pi/2[ */

    if ((quadrant & 1u) != 0u) {
        x = 16384 - x;                              /* mirror: ]0, 16384] */
    }

    const int32_t t2 = (x * x) >> 14;               /* Q14 */
    int32_t acc = SIN_C7;
    acc = SIN_C5 + ((acc * t2) >> 14);
    acc = SIN_C3 + ((acc * t2) >> 14);
    acc = SIN_C1 + ((acc * t2) >> 14);              /* Q16 */

    int32_t y = (acc * x + (1 << 14)) >> 15;        /* Q16 * Q14 -> Q15 */
    if (y > 32767) {
        y = 32767;
    }
    return (int16_t)((quadrant >= 2u) ? -y : y);
}
