"""Test execution: stimuli -> runner -> outputs -> checks."""
import datetime
import time
from dataclasses import dataclass, field

import numpy as np

from . import EUnitError, __version__
from . import checks as C
from . import stimuli
from .expr import Namespace


@dataclass
class TestResult:
    test: object
    status: str
    steps: list = field(default_factory=list)
    duration: float = 0.0
    samples: int = 0
    error: str = None
    cycles: object = None
    data: dict = field(default=None, repr=False)   # inputs/outputs, for plots


@dataclass
class SuiteResult:
    suite: object
    runner: dict
    tests: list
    started: str
    duration: float
    compare: dict = None
    license: str = None

    @property
    def status(self):
        if any(t.status in (C.FAIL, C.ERROR) for t in self.tests):
            return C.FAIL
        return C.PASS if any(t.status == C.PASS for t in self.tests) else C.SKIP

    def count(self, status):
        return sum(1 for t in self.tests if t.status == status)

    def meta(self):
        return {"suite": self.suite.name, "spec": str(self.suite.path), "hash": f"0x{self.suite.hash:08X}",
                "eunit": __version__, "license": self.license, "started": self.started, "duration_s": round(self.duration, 3),
                "status": self.status, **{k: self.count(k) for k in (C.PASS, C.FAIL, C.ERROR, C.SKIP)}}


def _words(func, values, n):
    """Encode the inputs of func into an int32 matrix (n, nin)."""
    if not func.inputs:
        return np.zeros((n, 0), dtype=np.int32)
    cols = [p.dtype.to_words(values[p.name], f"{func.name}.{p.name}") for p in func.inputs]
    return np.stack(cols, axis=1)


def _setup(runner, test):
    for func, args in test.setup:
        values = {p.name: np.asarray([a]) for p, a in zip(func.inputs, args)}
        runner.batch(func, _words(func, values, 1))


def _status(steps):
    statuses = {s.status for s in steps}
    if C.ERROR in statuses:
        return C.ERROR
    if C.FAIL in statuses:
        return C.FAIL
    return C.PASS if C.PASS in statuses else C.SKIP


def run_test(test, runner, namespace, compare_runner=None):
    t0 = time.perf_counter()
    res = TestResult(test, C.ERROR)
    try:
        func = test.call
        inputs, n = stimuli.build(test, namespace)
        words = _words(func, inputs, n)
        res.samples = n

        if test.reset:
            runner.reset()
        _setup(runner, test)
        out, cycles = runner.batch(func, words)
        res.cycles = cycles

        outputs = {p.name: p.dtype.from_words(out[:, k]) for k, p in enumerate(func.outputs)}
        variables = {**inputs, **outputs, "i": np.arange(n, dtype=np.int64), "n": n}
        names = [p.name for p in func.inputs]
        res.steps = [C.evaluate(chk, variables, n, namespace, names, cycles, f"{test.id}.checks[{chk.index}]")
                     for chk in test.checks]

        if compare_runner is not None:
            if test.reset:
                compare_runner.reset()
            _setup(compare_runner, test)
            ref, _ = compare_runner.batch(func, words)
            k0 = len(res.steps)
            for k, p in enumerate(func.outputs):
                res.steps.append(C.compare(k0 + k + 1, p.name, out[:, k], ref[:, k],
                                           compare_runner.name, names, variables))
        res.status = _status(res.steps)
        res.data = {"inputs": inputs, "outputs": outputs}
    except EUnitError as e:
        res.error = str(e)
        res.status = C.ERROR
    res.duration = time.perf_counter() - t0
    return res


def run_suite(suite, runner, tests=None, compare_runner=None, log=print, verbose=False):
    namespace = Namespace(suite.models)
    started = datetime.datetime.now().isoformat(timespec="seconds")
    t0 = time.perf_counter()
    results = []
    for test in tests if tests is not None else suite.tests:
        r = run_test(test, runner, namespace, compare_runner)
        results.append(r)
        log(_line(r))
        for s in r.steps:
            if verbose or s.status in (C.FAIL, C.ERROR):
                log(f"        {s.index:>2}. [{s.status}] {s.description}: {s.message}")
        if r.error:
            log(f"        {r.error}")
    return SuiteResult(suite, runner.info(), results, started, time.perf_counter() - t0,
                       compare_runner.info() if compare_runner else None)


def _line(r):
    cyc = f", cycles max {r.cycles.max}" if r.cycles is not None and r.cycles.calls else ""
    return f"  [{r.status:5}] {r.test.id} {r.test.title} ({r.samples} samples, {r.duration:.2f} s{cyc})"
