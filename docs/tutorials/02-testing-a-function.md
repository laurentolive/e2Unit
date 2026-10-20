# 2. Testing a function

**English** | [Français](../tutoriels/02-tester-une-fonction.md)

Write a suite for a new function, watch e2Unit find a bug, fix it. The function: a Q15 fixed-point
multiplication, where 32767 stands for 1.0.

## 1. The function

In [`emath.h`](../../examples/emath/src/emath.h):

```c
/* a * b in Q15, rounded to nearest, saturated: (-1) * (-1) = 32767 */
int16_t emath_mul_q15(int16_t a, int16_t b);
```

First version, in `emath_mul.c`:

```c
int16_t emath_mul_q15(int16_t a, int16_t b)
{
    return (int16_t)(((int32_t)a * b + (1 << 14)) >> 15);
}
```

32-bit product, rounding (+0.5 LSB), back to Q15. It looks right.

## 2. The suite

Create `tests/mulq15/mulq15.yaml`:

```yaml
suite: mulq15

build:
  sources: [../../src/emath_mul.c]     # relative to the YAML file
  includes: [../../src]
  headers: [emath.h]

functions:
  mul:
    prototype: "int16_t emath_mul_q15(int16_t a, int16_t b)"
    returns: p

tests:
  - id: MUL-001
    title: accuracy on a 257 x 257 grid
    requirement: EMATH-MUL-01
    call: mul
    combine: grid
    stimuli:
      a: {linspace: [-32768, 32767, 257]}
      b: {linspace: [-32768, 32767, 257]}
    checks:
      - desc: "|p - a b / 32768| <= 0.5 LSB, saturated to int16"
        expect: "sat(a * b / 32768, 'int16_t')"
        tolerance: {abs: 0.5}

  - id: MUL-002
    title: remarkable values
    requirement: EMATH-MUL-02
    call: mul
    stimuli:
      a: [16384, -16384, 32767, -32768, -32768, 0]
      b: [16384, 16384, 32767, 32767, -32768, -32768]
    checks:
      - desc: 0.5 x 0.5, -0.5 x 0.5, max x max, -1 x max, -1 x -1 (saturated), 0 x -1
        expect: [8192, -8192, 32766, -32767, 32767, 0]
```

Line by line:

- **`functions`** declares the function by its **C prototype**. e2Unit generates the call: nothing
  to write in C for functions with scalar parameters. `returns: p` names the return value.
- **`stimuli`** gives the values of each parameter. `linspace`: 257 values from -32768 to 32767.
  `combine: grid` crosses every value of `a` with every value of `b`: 66,049 calls.
- **`expect`** is a Python (numpy) expression computing the expected value from the inputs.
  `sat(..., 'int16_t')` saturates to the range of the C type. The 0.5 LSB **tolerance** states the
  requirement: the result is rounded to nearest.
- **MUL-002** gives the expected values explicitly: the most readable form for remarkable cases.

And the Makefile, as for every suite:

```make
EUNIT_ROOT := ../../../..
SUITE      := mulq15.yaml
include $(EUNIT_ROOT)/mk/eunit.mk
```

## 3. Run

```
cd tests/mulq15
make EUNIT_RUN_OPTS="--plot build/plots"
```

```
e2Unit 0.1.0: suite mulq15, 2 test(s) on host
eunit: Personal License - Non-commercial use only
  [FAIL ] MUL-001 accuracy on a 257 x 257 grid (66049 samples, 0.01 s)
         1. [FAIL] |p - a b / 32768| <= 0.5 LSB, saturated to int16: 1/66049 samples out of tolerance (abs=0.5), max |err| 65535 at #0; first failure #0: a=-32768, b=-32768 -> p=-32768, expected 32767
  [FAIL ] MUL-002 remarkable values (6 samples, 0.00 s)
         1. [FAIL] 0.5 x 0.5, -0.5 x 0.5, max x max, -1 x max, -1 x -1 (saturated), 0 x -1: 1/6 samples out of tolerance (exact), max |err| 65535 at #4; first failure #4: a=-32768, b=-32768 -> p=-32768, expected 32767
eunit: 2 plot(s) in build/plots
eunit: FAIL - 0 passed, 2 failed, 0 errors, 0 skipped in 0.01 s - reports in build\report\host
```

A single wrong case out of 66,049, and the message points straight at it: **-1 × -1 gives -1**.
The product is +1.0, which does not fit in Q15 (32768) and wraps to negative when converted to `int16_t`.

The plot isolates the faulty point:

![MUL-001: a single sample in error, the first one (a = b = -32768)](../img/plot-mul-fail.png)

## 4. Fix

```c
int16_t emath_mul_q15(int16_t a, int16_t b)
{
    int32_t p = ((int32_t)a * b + (1 << 14)) >> 15;  /* rounded to nearest */
    if (p > 32767) {
        p = 32767;                                    /* only (-1) * (-1) */
    }
    return (int16_t)p;
}
```

`make` rebuilds what changed and runs again:

```
  [PASS ] MUL-001 accuracy on a 257 x 257 grid (66049 samples, 0.01 s)
  [PASS ] MUL-002 remarkable values (6 samples, 0.00 s)
eunit: PASS - 2 passed, 0 failed, 0 errors, 0 skipped in 0.01 s - reports in build\report\host
```

## 5. Safeguards

e2Unit rejects specification mistakes instead of letting them through.

**Prototype different from the header.** The prototype of the specification is declared again in
the generated code. If the YAML says `int32_t a` while `emath.h` says `int16_t a`, the build fails:

```
build/gen/eunit_suite.c:8:9: error: conflicting types for 'emath_mul_q15'; have 'int16_t(int32_t,  int16_t)'
...emath.h:17:9: note: previous declaration of 'emath_mul_q15' with type 'int16_t(int16_t,  int16_t)'
```

**Stimulus out of the C type.** A value that does not fit in the parameter (40000 for an
`int16_t`) makes the test **ERROR**, never a silently truncated value.

**Typo.** An unknown key (`expected:` instead of `expect:`) is reported with the list of allowed keys.

## Summary

| Step | File |
|---|---|
| function and header | `src/emath_mul.c`, `src/emath.h` |
| specification | `tests/mulq15/mulq15.yaml` |
| build and run | `tests/mulq15/Makefile` (3 lines) |
| generated code | `tests/mulq15/build/gen/eunit_suite.c` (do not edit) |

[Tutorial 3](03-stimuli-checks.md) details every form of stimulus and check.
