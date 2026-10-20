"""Runners execute batches of calls of the adapters of a suite.

  host  : shared library called directly through ctypes
  sim   : same shared library, driven through the mailbox protocol (no hardware)
  emu   : target firmware (ARM ELF) in the Unicorn emulator, through the mailbox
  jlink : test firmware on target, driven through the mailbox over SWD
"""
from abc import ABC, abstractmethod


class Runner(ABC):
    name = "runner"

    def __init__(self, suite):
        self.suite = suite

    def open(self):
        pass

    def close(self):
        pass

    def reset(self):
        """Restore the initial state of the code under test (static data)."""

    @abstractmethod
    def batch(self, func, words):
        """Call func once per row of words (int32, shape (N, nin)).

        Returns (outputs int32 (N, nout), CycleStats or None).
        """

    def info(self):
        return {"runner": self.name}

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()
