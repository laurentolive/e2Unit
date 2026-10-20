"""Stimulus generators.

A stimulus is one of:
  5                              constant (broadcast)
  [1, 2, 3]                      explicit values
  {values: [...]}                explicit values
  {range: [a, b], step: s}       integers a..b inclusive
  {linspace: [a, b, n]}          n points from a to b inclusive
  {random: [a, b], n: N, seed: S}  uniform (integers for integer inputs)
  {segments: [...], seed: S}     piecewise signal, each segment sums components:
        {n: 100, dc: v, ramp: [a, b], sine: {amp, period, phase, offset},
         square: {amp, period, duty}, noise: amp}
  {expr: "...", n: N}            numpy expression of the sample index i
  {file: data.npy | data.csv}    samples from a file

Generators are deterministic: the default random seed derives from the test id
and the input name.
"""
import zlib

import numpy as np

from . import EUnitError

_GEN_KEYS = {"values", "range", "step", "linspace", "random", "n", "seed", "segments", "expr", "file"}
_SEG_KEYS = {"n", "dc", "ramp", "sine", "square", "noise"}


def _seed(test_id, name, given):
    if given is not None:
        return int(given)
    return zlib.crc32(f"{test_id}/{name}".encode())


def _segments(segs, rng, where):
    parts, start = [], 0
    for k, s in enumerate(segs):
        w = f"{where}.segments[{k}]"
        if not isinstance(s, dict) or "n" not in s:
            raise EUnitError(f"{w}: each segment needs 'n'")
        unknown = set(s) - _SEG_KEYS
        if unknown:
            raise EUnitError(f"{w}: unknown key(s) {sorted(unknown)}")
        n = int(s["n"])
        i = np.arange(start, start + n, dtype=np.float64)   # global index: continuous phase
        y = np.zeros(n)
        if "dc" in s:
            y += float(s["dc"])
        if "ramp" in s:
            a, b = s["ramp"]
            y += np.linspace(float(a), float(b), n)
        if "sine" in s:
            p = s["sine"]
            y += float(p.get("offset", 0)) + float(p["amp"]) * np.sin(
                2 * np.pi * i / float(p["period"]) + np.deg2rad(float(p.get("phase", 0))))
        if "square" in s:
            p = s["square"]
            phase = np.mod(i, float(p["period"])) / float(p["period"])
            y += np.where(phase < float(p.get("duty", 0.5)), float(p["amp"]), -float(p["amp"]))
        if "noise" in s:
            a = float(s["noise"])
            y += rng.uniform(-a, a, n)
        parts.append(y)
        start += n
    return np.concatenate(parts) if parts else np.zeros(0)


def generate(spec, port, test_id, base_dir, namespace):
    """Return a 1-D array (or a scalar) of values for one input."""
    where = f"{test_id}.stimuli.{port.name}"
    is_int = port.dtype.kind != "float"
    if isinstance(spec, (int, float)):
        return spec
    if isinstance(spec, (list, tuple)):
        spec = {"values": spec}
    if not isinstance(spec, dict):
        raise EUnitError(f"{where}: invalid generator {spec!r}")
    unknown = set(spec) - _GEN_KEYS
    if unknown:
        raise EUnitError(f"{where}: unknown key(s) {sorted(unknown)}")
    rng = np.random.default_rng(_seed(test_id, port.name, spec.get("seed")))

    try:
        if "values" in spec:
            vals = list(spec["values"])
            exact_int = is_int and all(isinstance(x, int) for x in vals)
            v = np.asarray(vals, dtype=np.int64 if exact_int else np.float64)
        elif "range" in spec:
            a, b = (int(x) for x in spec["range"])
            step = int(spec.get("step", 1 if b >= a else -1))
            v = np.arange(a, b + (1 if step > 0 else -1), step, dtype=np.int64)
        elif "linspace" in spec:
            a, b, n = spec["linspace"]
            v = np.linspace(float(a), float(b), int(n))
        elif "random" in spec:
            a, b = spec["random"]
            n = int(spec.get("n", 1000))
            if is_int:
                v = rng.integers(int(a), int(b), n, endpoint=True, dtype=np.int64)
            else:
                v = rng.uniform(float(a), float(b), n)
        elif "segments" in spec:
            v = _segments(spec["segments"], rng, where)
        elif "expr" in spec:
            n = int(spec.get("n", 1))
            v = namespace.eval(spec["expr"], {"i": np.arange(n, dtype=np.int64), "n": n, "rng": rng}, where)
            v = np.broadcast_to(np.asarray(v, dtype=np.float64), (n,)).copy()
        elif "file" in spec:
            path = base_dir / spec["file"]
            v = np.load(path) if path.suffix == ".npy" else np.loadtxt(path, delimiter=",", ndmin=1)
            v = np.asarray(v, dtype=np.float64).ravel()
        else:
            raise EUnitError(f"{where}: no generator given")
    except EUnitError:
        raise
    except Exception as e:  # malformed parameters
        raise EUnitError(f"{where}: {type(e).__name__}: {e}") from e

    if v.size == 0:
        raise EUnitError(f"{where}: generator produced no sample")
    return v


def build(test, namespace):
    """Generate all inputs of a test, combined, as {name: array} of equal length N."""
    raw = {}
    for port in test.call.inputs:
        raw[port.name] = generate(test.stimuli[port.name], port, test.id, test.base_dir, namespace)

    arrays = {k: v for k, v in raw.items() if not np.isscalar(v)}
    if test.combine == "grid" and arrays:
        grids = np.meshgrid(*arrays.values(), indexing="ij")
        arrays = {k: g.ravel() for k, g in zip(arrays, grids)}
    lengths = {len(v) for v in arrays.values()}
    if len(lengths) > 1:
        detail = ", ".join(f"{k}={len(v)}" for k, v in arrays.items())
        raise EUnitError(f"{test.id}: inputs have different lengths ({detail}); "
                         f"use the same length or 'combine: grid'")
    n = lengths.pop() if lengths else 1

    out = {}
    for port in test.call.inputs:
        v = raw[port.name] if port.name not in arrays else arrays[port.name]
        v = np.broadcast_to(np.asarray(v), (n,))
        if port.dtype.kind == "float":
            out[port.name] = v.astype(np.float64)
        else:
            if v.dtype.kind == "f":
                v = np.rint(v)
            out[port.name] = v.astype(np.int64)
    return out, n
