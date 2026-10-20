"""PNG plots of checks (actual vs expected, error vs tolerance)."""
import re
from pathlib import Path

import numpy as np

from . import EUnitError
from .checks import FAIL, ERROR


def _safe(s):
    return re.sub(r"[^\w.-]+", "_", s).strip("_")


def plot_suite(result, out_dir, all_steps=False):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as e:
        raise EUnitError("matplotlib is required for plots: pip install matplotlib") from e

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for r in result.tests:
        if r.data is None:
            continue
        inputs = r.data["inputs"]
        # x axis: the input of a sweep (single monotonic input), else the sample index (signals)
        x_name = None
        if len(inputs) == 1:
            name, values = next(iter(inputs.items()))
            if len(values) > 1 and np.all(np.diff(values) > 0):
                x_name = name
        for s in r.steps:
            if s.plot is None or (not all_steps and s.status not in (FAIL, ERROR)):
                continue
            mask = s.plot["mask"]
            x = inputs[x_name] if x_name else np.arange(len(mask))
            order = np.arange(len(x))
            fig, axes = plt.subplots(2, 1, sharex=True, figsize=(10, 6))
            axes[0].plot(x[mask], s.plot["actual"][order][mask], ".", ms=2, label=s.plot["output"])
            if "expected" in s.plot:
                axes[0].plot(x[mask], s.plot["expected"][order][mask], "-", lw=0.8, label="expected")
                axes[1].plot(x[mask], s.plot["error"][order][mask], ".", ms=2, color="tab:red")
                axes[1].set_ylabel("error")
            else:
                axes[0].plot(x, s.plot["lo"][order], "--", lw=0.8, label="min")
                axes[0].plot(x, s.plot["hi"][order], "--", lw=0.8, label="max")
            axes[0].legend(loc="best", fontsize="small")
            axes[0].set_title(f"{r.test.id} step {s.index} [{s.status}] {s.description}", fontsize="small")
            axes[1].set_xlabel(x_name or "sample")
            for ax in axes:
                ax.grid(True, alpha=0.3)
            path = out / f"{_safe(r.test.id)}_{s.index}.png"
            fig.tight_layout()
            fig.savefig(path, dpi=110)
            plt.close(fig)
            written.append(path)
    return written
