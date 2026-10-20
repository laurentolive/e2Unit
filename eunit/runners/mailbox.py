"""Mailbox runner: drives the e2Unit runtime through its RAM mailbox.

The transport is a Link giving word access to the target memory: a J-Link
probe (real target) or the memory of the process (simulated target).
Protocol (see target/include/eunit.h):
  host  : write inputs to buf, write cmd/fn/count, then req = seq + 1
  target: execute, write outputs, status and cycles, then ack = req
"""
import time
from abc import ABC, abstractmethod

import numpy as np

from .. import EUnitError
from .. import protocol as P
from ..checks import CycleStats
from . import Runner
from .host import check_identity


class Link(ABC):
    name = "link"
    has_cycles = False

    @abstractmethod
    def open(self):
        """Connect; return the address of eunit_mailbox."""

    @abstractmethod
    def close(self):
        pass

    @abstractmethod
    def read(self, addr, nwords):
        """Read nwords 32-bit words, return an int32 array."""

    @abstractmethod
    def write(self, addr, words):
        """Write an int32 array."""

    @abstractmethod
    def reset(self):
        """Reset the target and let it run."""

    def info(self):
        return {"link": self.name}


class TargetFault(EUnitError):
    pass


class MailboxRunner(Runner):
    def __init__(self, suite, link, timeout=5.0, boot_timeout=5.0):
        super().__init__(suite)
        self.link = link
        self.name = link.name
        self.timeout = timeout
        self.boot_timeout = boot_timeout
        self.base = None
        self.seq = 0
        self.buf_words = 0
        self.cpu_hz = 0
        self._dirty = False

    # ------------------------------------------------------------------
    def _addr(self, word):
        return self.base + 4 * word

    def _wait_ready(self):
        deadline = time.monotonic() + self.boot_timeout
        while True:
            hdr = self.link.read(self.base, P.HEADER_WORDS).view(np.uint32)
            if hdr[P.W_MAGIC] == P.MAGIC:
                break
            if time.monotonic() > deadline:
                raise EUnitError(f"{self.name}: e2Unit runtime not ready (no magic at 0x{self.base:08X}); "
                                 f"is the test firmware flashed and running?")
            time.sleep(0.002)
        if hdr[P.W_VERSION] != P.VERSION:
            raise EUnitError(f"{self.name}: protocol version {hdr[P.W_VERSION]}, expected {P.VERSION}")
        check_identity(f"{self.name} firmware", self.suite, int(hdr[P.W_HASH]), int(hdr[P.W_FN_COUNT]))
        self.buf_words = int(hdr[P.W_BUF_WORDS])
        self.cpu_hz = int(hdr[P.W_CPU_HZ])
        self.seq = int(hdr[P.W_ACK])
        self._dirty = False

    def _request(self, cmd, fn=0, count=0):
        self.link.write(self._addr(P.W_CMD), np.array([cmd, fn, count], dtype=np.int64).astype(np.int32))
        self.seq = (self.seq + 1) & 0xFFFFFFFF
        self.link.write(self._addr(P.W_REQ), np.array([self.seq], dtype=np.uint32).view(np.int32))
        deadline = time.monotonic() + self.timeout
        while int(self.link.read(self._addr(P.W_ACK), 1).view(np.uint32)[0]) != self.seq:
            if time.monotonic() > deadline:
                self._dirty = True
                raise EUnitError(f"{self.name}: no answer within {self.timeout} s "
                                 f"(function stuck in an infinite loop?)")
            time.sleep(0)
        r = self.link.read(self._addr(P.W_STATUS), 7).view(np.uint32)
        status, fault_pc = int(r[0]), int(r[6])
        if status == P.STATUS_FAULT:
            self._dirty = True
            raise TargetFault(f"{self.name}: CPU fault at PC 0x{fault_pc:08X}")
        if status != P.STATUS_OK:
            raise EUnitError(f"{self.name}: request failed: {P.STATUS_TEXT.get(status, status)}")
        calls, cmin, cmax, lo, hi = (int(x) for x in r[1:6])
        return CycleStats(calls, cmin, cmax, lo | (hi << 32))

    # ------------------------------------------------------------------
    def open(self):
        self.base = self.link.open()
        self._wait_ready()
        self._request(P.CMD_PING)

    def close(self):
        self.link.close()

    def reset(self):
        self.link.reset()
        self._wait_ready()

    def batch(self, func, words):
        if self._dirty:              # previous fault/timeout: restart the target
            self.reset()
        n = words.shape[0]
        nin, nout = len(func.inputs), len(func.outputs)
        per = nin + nout
        chunk = self.buf_words // per if per else n
        if chunk == 0:
            raise EUnitError(f"{func.name}: {per} words per call exceed the target buffer")
        out = np.zeros((n, nout), dtype=np.int32)
        stats = CycleStats(0, 0, 0, 0)
        buf = self._addr(P.W_BUF)
        for start in range(0, n, chunk):
            m = min(chunk, n - start)
            if nin:
                self.link.write(buf, words[start:start + m].reshape(-1))
            stats = stats.merge(self._request(P.CMD_BATCH, func.index, m))
            if nout:
                out[start:start + m] = self.link.read(buf + 4 * m * nin, m * nout).reshape(m, nout)
        return out, (stats if self.link.has_cycles else None)

    def info(self):
        d = {"runner": self.name, "mailbox": f"0x{self.base:08X}" if self.base is not None else None,
             "buffer_words": self.buf_words, "cpu_hz": self.cpu_hz}
        d.update(self.link.info())
        return d
