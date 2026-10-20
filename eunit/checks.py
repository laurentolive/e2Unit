"""Evaluation of the checks of a test, each check producing one report step."""
from dataclasses import dataclass, field

import numpy as np

from . import EUnitError

PASS, FAIL, SKIP, ERROR = "PASS", "FAIL", "SKIP", "ERROR"


@dataclass
class CycleStats:
    calls: int
    min: int
    max: int
    total: int

    @property
    def mean(self):
        return self.total / self.calls if self.calls else 0.0

    def merge(self, other):
        if other is None or other.calls == 0:
            return self
        if self.calls == 0:
            return other
        return CycleStats(self.calls + other.calls, min(self.min, other.min),
                          max(self.max, other.max), self.total + other.total)


@dataclass
class StepResult:
    index: int
    description: str
    status: str
    message: str
    stats: dict = field(default_factory=dict)
    plot: dict = field(default=None, repr=False)   # arrays for plotting, not serialised


def fmt(x):
    x = float(x)
    if np.isfinite(x) and x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return f"{x:.6g}"


def _mask(n, window, where_values):
    mask = np.ones(n, dtype=bool)
    if window is not None:
        sl = slice(*(None if w is None else int(w) for w in window))
        win = np.zeros(n, dtype=bool)
        win[sl] = True
        mask &= win
    if where_values is not None:
        mask &= np.broadcast_to(np.asarray(where_values, dtype=bool), (n,))
    return mask


def _sample_text(idx, inputs, variables):
    return ", ".join(f"{k}={fmt(variables[k][idx])}" for k in inputs)


def _tol_text(tol):
    parts = [f"{k}={fmt(v)}" for k, v in tol.items()]
    return ", ".join(parts) if parts else "exact"


def evaluate(check, variables, n, namespace, inputs, cycles, where):
    try:
        if check.kind == "cycles":
            return _cycles(check, cycles)
        where_values = None
        if check.where is not None:
            where_values = namespace.eval(check.where, variables, f"{where}.where")
        mask = _mask(n, check.window, where_values)
        if not mask.any():
            return StepResult(check.index, check.description, ERROR, "no sample selected by window/where")
        if check.kind == "value":
            return _value(check, variables, n, namespace, inputs, mask, where)
        return _bounds(check, variables, n, namespace, inputs, mask, where)
    except EUnitError as e:
        return StepResult(check.index, check.description, ERROR, str(e))


def _value(check, variables, n, namespace, inputs, mask, where):
    actual = np.asarray(variables[check.output], dtype=np.float64)
    expected = namespace.eval(check.expect, variables, f"{where}.expect")
    try:
        expected = np.broadcast_to(np.asarray(expected, dtype=np.float64), (n,))
    except ValueError as e:
        raise EUnitError(f"{where}.expect: shape {np.shape(expected)} does not match {n} samples") from e

    tol = check.tolerance
    err = actual - expected
    both_nan = np.isnan(actual) & np.isnan(expected)
    err = np.where(both_nan, 0.0, err)
    if "modulo" in tol:
        m = tol["modulo"]
        err = np.mod(err + m / 2, m) - m / 2
    allowed = tol.get("abs", 0.0) + tol.get("rel", 0.0) * np.abs(expected)
    bad = mask & ~(np.abs(err) <= allowed)          # NaN error counts as failure
    abs_err = np.where(mask, np.abs(err), 0.0)
    abs_err = np.where(np.isnan(abs_err), np.inf, abs_err)
    worst = int(np.argmax(abs_err))
    checked = int(mask.sum())
    stats = {"samples": checked, "failed": int(bad.sum()), "max_abs_err": float(abs_err[worst]),
             "worst_index": worst}
    plot = {"actual": actual, "expected": expected, "error": err, "mask": mask, "output": check.output}
    if not bad.any():
        msg = f"{checked} samples, max |err| {fmt(abs_err[worst])} (tol {_tol_text(tol)})"
        return StepResult(check.index, check.description, PASS, msg, stats, plot)
    first = int(np.argmax(bad))
    msg = (f"{int(bad.sum())}/{checked} samples out of tolerance ({_tol_text(tol)}), "
           f"max |err| {fmt(abs_err[worst])} at #{worst}; first failure #{first}: "
           f"{_sample_text(first, inputs, variables)} -> {check.output}={fmt(actual[first])}, "
           f"expected {fmt(expected[first])}")
    stats["first_failure"] = first
    return StepResult(check.index, check.description, FAIL, msg, stats, plot)


def _bounds(check, variables, n, namespace, inputs, mask, where):
    actual = np.asarray(variables[check.output], dtype=np.float64)
    lo = -np.inf if check.min is None else namespace.eval(check.min, variables, f"{where}.min")
    hi = np.inf if check.max is None else namespace.eval(check.max, variables, f"{where}.max")
    lo = np.broadcast_to(np.asarray(lo, dtype=np.float64), (n,))
    hi = np.broadcast_to(np.asarray(hi, dtype=np.float64), (n,))
    bad = mask & ~((actual >= lo) & (actual <= hi))
    checked = int(mask.sum())
    sel = actual[mask]
    stats = {"samples": checked, "failed": int(bad.sum()), "min": float(sel.min()), "max": float(sel.max())}
    plot = {"actual": actual, "lo": lo, "hi": hi, "mask": mask, "output": check.output}
    if not bad.any():
        msg = f"{checked} samples within bounds, observed [{fmt(sel.min())}, {fmt(sel.max())}]"
        return StepResult(check.index, check.description, PASS, msg, stats, plot)
    first = int(np.argmax(bad))
    msg = (f"{int(bad.sum())}/{checked} samples out of bounds; first failure #{first}: "
           f"{_sample_text(first, inputs, variables)} -> {check.output}={fmt(actual[first])} "
           f"not in [{fmt(lo[first])}, {fmt(hi[first])}]")
    return StepResult(check.index, check.description, FAIL, msg, stats, plot)


def _cycles(check, cycles):
    if cycles is None:
        return StepResult(check.index, check.description, SKIP, "no cycle counter on this runner")
    stats = {"calls": cycles.calls, "min": cycles.min, "max": cycles.max, "mean": cycles.mean}
    text = f"cycles min {cycles.min} / mean {cycles.mean:.1f} / max {cycles.max} over {cycles.calls} calls"
    fails = []
    if "max" in check.cycles and cycles.max > float(check.cycles["max"]):
        fails.append(f"max {cycles.max} > {fmt(check.cycles['max'])}")
    if "mean" in check.cycles and cycles.mean > float(check.cycles["mean"]):
        fails.append(f"mean {cycles.mean:.1f} > {fmt(check.cycles['mean'])}")
    if fails:
        return StepResult(check.index, check.description, FAIL, f"{text}: {'; '.join(fails)}", stats)
    return StepResult(check.index, check.description, PASS, text, stats)


def compare(index, output, actual, reference, ref_name, inputs, variables):
    """Bit-exact comparison of an output against another runner (e.g. target vs host)."""
    a = np.asarray(actual, dtype=np.float64)
    b = np.asarray(reference, dtype=np.float64)
    same = (a == b) | (np.isnan(a) & np.isnan(b))
    desc = f"{output} identical to {ref_name}"
    if same.all():
        return StepResult(index, desc, PASS, f"{len(a)} samples identical")
    first = int(np.argmax(~same))
    msg = (f"{int((~same).sum())}/{len(a)} samples differ; first #{first}: "
           f"{_sample_text(first, inputs, variables)} -> {fmt(a[first])} vs {ref_name} {fmt(b[first])}")
    return StepResult(index, desc, FAIL, msg, {"differ": int((~same).sum())})
