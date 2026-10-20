# 3. Stimuli and checks

**English** | [Français](../tutoriels/03-stimuli-verifications.md)

Every way to generate the inputs of a test and to check its outputs, illustrated by the example
suites ([`examples/emath/tests`](../../examples/emath/tests)).

## Stimuli

Each parameter of the function gets a generator, under `stimuli:`.

| Form | Example | Values |
|---|---|---|
| constant | `k: 5` | 5, repeated |
| list | `x: [0, 16384, -32768]` | these values |
| integer range | `x: {range: [-32768, 32767]}` | all of them, bounds included (optional `step:`) |
| spread | `x: {linspace: [-32768, 32767, 257]}` | 257 evenly spaced values, rounded for an integer |
| random | `x: {random: [0, 4294967295], n: 200000}` | uniform, **reproducible** |
| expression | `x: {expr: "(i // 3 + 1) ** 2 + i % 3 - 1", n: 196605}` | function of the index `i` |
| signal | `x: {segments: [...]}` | signal pieces (see below) |
| file | `x: {file: measure.npy}` | `.npy` or `.csv` |

**Reproducible random.** The default seed depends on the test id and on the parameter name: two
runs draw the same values, so a failure can be reproduced. `seed:` sets another seed.

**Expression.** The example above ([`isqrt.yaml`](../../examples/emath/tests/isqrt/isqrt.yaml))
produces k² - 1, k² and k² + 1 for k = 1 to 65535: every perfect square and its neighbours, where
an integer square root goes wrong.

**Signal made of segments.** Each segment has a length `n` and adds up components:

```yaml
x:
  segments:
    - {n: 300, dc: 0}
    - {n: 600, dc: -32768}
    - {n: 600, sine: {amp: 20000, period: 64, phase: 90}}
    - {n: 600, square: {amp: 10000, period: 50, duty: 0.5}}
    - {n: 500, ramp: [0, 1000], noise: 50}
```

The sine phase is continuous from one segment to the next; `period` is in samples.

### Combining several parameters

| `combine:` | Rule | Example |
|---|---|---|
| `zip` (default) | call *i* with value *i* of each parameter; same length, constants are repeated | `a: [1, 2, 3]`, `b: 7` → 3 calls |
| `grid` | every combination | 257 × 257 → 66,049 calls |

A value that does not fit in the C type of the parameter is an **error**, never truncated.

## Checks

Each item of `checks:` is a check, reported as a step of the test.

### Expected value: `expect`

```yaml
- desc: "|angle - atan2(y, x)| <= 1 LSB, modulo one turn"
  expect: atan2_bin(y, x)
  tolerance: {abs: 1, modulo: 65536}
```

`expect` is a list of values, a number, or a **Python expression** that sees:

| Name | Content |
|---|---|
| parameters and outputs | numpy arrays, by name (`a`, `b`, `p`...) |
| `i`, `n` | sample index, number of samples |
| `np`, `sin`, `sqrt`, `pi`, `clip`, `where`... | numpy |
| `sat(x, 'int16_t')` | saturation to the range of a C type |
| `wrap(x, 'uint8_t')` | two's complement wrap-around, as in C |
| `isqrt(x)` | exact integer square root |
| `shift(x, k)` | signal delayed by `k` samples |
| functions of the `models` | reference models (below) |

An output can be checked against another one. Symmetry of `emath_sin`, on angles from -32767 to 32767:

```yaml
- desc: sin(-a) = -sin(a)
  expect: -y[::-1]
```

### Tolerance

| Key | Allowed difference |
|---|---|
| (none) | exact equality |
| `abs: 2` | \|output - expected\| ≤ 2 |
| `rel: 1.0e-6` | ≤ 10⁻⁶ × \|expected\| (added to `abs`) |
| `modulo: 65536` | difference computed modulo 65536: for angles, π and -π are equal |

### Bounds: `min` / `max`

```yaml
- desc: output within [-32767, 32767]
  min: -32767
  max: 32767
```

### Narrowing: `window` and `where`

```yaml
- desc: once the window is full, rms = 20000 / sqrt(2) within 2 LSB
  window: [64, null]          # samples 64 to the end
  expect: 20000 / sqrt(2)
  tolerance: {abs: 2}

- desc: exact away from the origin
  where: "(x != 0) | (y != 0)"
  expect: atan2_bin(y, x)
```

`window: [start, end]` follows the Python convention (end excluded, `null` = to the end).

### Execution time: `cycles`

```yaml
- desc: execution time
  cycles: {max: 200, mean: 120}
```

Checked on the board only ([tutorial 6](06-ra4e1-jlink.md)), SKIP elsewhere.

## Reference models

When the expected value does not fit in one line, it is written in Python, in a file declared
under `models:`. All its public functions can then be used in `expect`:

```yaml
models: [../emath_ref.py]
...
    checks:
      - desc: exact or saturated result
        expect: pow_sat(base, exp)
```

```python
def pow_sat(base, exp):
    """Exact integer power saturated to int32 (0^0 = 1)."""
    ...
```

The model works with Python's exact integers: no overflow, it acts as an oracle. A model must be
**simpler** than the function under test, otherwise it may share its bugs. For the sine, the
reference is `round(32767 · sin(π · angle / 32768))`: one line, unrelated to the polynomial of the C code.

## A good suite

| Test | Role | Example |
|---|---|---|
| exhaustive sweep | no case forgotten when the domain is small | `sin`: all 65,536 angles |
| grid or random | large domain, several parameters | `atan2`: 257 × 257 grid + 100,000 points |
| remarkable cases | exact expected values, bounds, saturation | `pow`: 46340², 46341², (-2)³¹ |
| property | symmetry, monotonicity, invariant | `sin(-a) = -sin(a)` |

[Tutorial 4](04-stateful-functions.md) moves on to functions that keep a state between two calls.
