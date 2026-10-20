"""Evaluation of the Python expressions of a suite (expected values, masks).

Expressions see: numpy as `np`, common math names, the helpers below, every
input and output of the test by name, `i` (sample index), `n` (sample count)
and every public function of the suite model files (`models:`).
"""
import importlib.util
import math
from pathlib import Path

import numpy as np

from . import EUnitError
from .datatypes import lookup


def sat(x, ctype):
    """Saturate to the range of a C type."""
    t = lookup(ctype)
    return np.clip(x, t.min, t.max)


def wrap(x, ctype):
    """Wrap (two's complement) to a C integer type."""
    words = (np.asarray(x, dtype=np.int64) & 0xFFFFFFFF).astype(np.uint32).view(np.int32)
    return lookup(ctype).from_words(words)


def isqrt(x):
    """Exact floor(sqrt(x)) for non negative integers (element-wise)."""
    return np.array([math.isqrt(int(v)) for v in np.ravel(x)], dtype=np.int64).reshape(np.shape(x))


def shift(x, k, fill=0):
    """x delayed by k samples (x[i-k]), padded with fill."""
    x = np.asarray(x)
    out = np.full_like(x, fill)
    if k >= 0:
        out[k:] = x[:len(x) - k] if k else x
    else:
        out[:k] = x[-k:]
    return out


HELPERS = {
    "np": np, "numpy": np, "math": math,
    "pi": np.pi, "e": np.e, "inf": np.inf,
    "sin": np.sin, "cos": np.cos, "tan": np.tan, "arctan": np.arctan, "arctan2": np.arctan2,
    "sqrt": np.sqrt, "exp": np.exp, "log": np.log, "log10": np.log10,
    "abs": np.abs, "round": np.round, "floor": np.floor, "ceil": np.ceil,
    "minimum": np.minimum, "maximum": np.maximum, "clip": np.clip, "where": np.where,
    "sat": sat, "wrap": wrap, "isqrt": isqrt, "shift": shift,
}


class Namespace:
    def __init__(self, model_files=()):
        self.globals = dict(HELPERS)
        for path in model_files:
            self.globals.update(self._load(Path(path)))

    @staticmethod
    def _load(path):
        if not path.exists():
            raise EUnitError(f"model file not found: {path}")
        spec = importlib.util.spec_from_file_location(f"eunit_model_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            raise EUnitError(f"cannot load model {path}: {type(e).__name__}: {e}") from e
        return {k: v for k, v in vars(mod).items() if not k.startswith("_")}

    def eval(self, expr, variables, where):
        if isinstance(expr, (int, float, list)):
            return np.asarray(expr)
        try:
            return eval(compile(str(expr), where, "eval"), dict(self.globals), dict(variables))
        except Exception as e:
            raise EUnitError(f"{where}: cannot evaluate '{expr}': {type(e).__name__}: {e}") from e
