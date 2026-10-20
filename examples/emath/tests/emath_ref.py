"""Reference models of the emath library (exact Python arithmetic).

Every public function of this file can be used in the 'expect' expressions of
the suites that list it under 'models:'.
"""
import math

import numpy as np

INT32_MIN, INT32_MAX = -(1 << 31), (1 << 31) - 1


def sin_q15(angle):
    """Ideal sine of a binary angle, rounded to Q15."""
    return np.round(32767 * np.sin(np.pi * np.asarray(angle) / 32768.0))


def atan2_bin(y, x):
    """Ideal atan2 as a binary angle (pi = 32768, compare with modulo 65536)."""
    return np.round(np.arctan2(y, x) * 32768.0 / np.pi)


def pow_sat(base, exp):
    """Exact integer power saturated to int32 (0^0 = 1)."""
    def one(b, e):
        return max(INT32_MIN, min(INT32_MAX, int(b) ** int(e)))
    # int ** int is exact; large exponents of |b| >= 2 saturate anyway
    out = []
    for b, e in zip(np.ravel(base), np.ravel(exp)):
        b, e = int(b), int(e)
        if abs(b) >= 2 and e > 64:
            out.append(INT32_MIN if (b < 0 and e % 2) else INT32_MAX)
        else:
            out.append(one(b, e))
    return np.array(out, dtype=np.int64)


def rms_window(x, log2n):
    """floor(sqrt(mean of the squares of the last 2^log2n samples)), zeros before start."""
    n = 1 << int(log2n)
    sq = np.asarray(x, dtype=np.int64) ** 2
    csum = np.concatenate(([0], np.cumsum(sq)))
    i = np.arange(len(sq))
    window = csum[i + 1] - csum[np.maximum(i + 1 - n, 0)]
    return np.array([math.isqrt(int(v) >> int(log2n)) for v in window], dtype=np.int64)
