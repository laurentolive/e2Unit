"""Simulated target: the host library runs the mailbox server in a thread and
the runner talks to it through process memory, exactly like over SWD."""
import ctypes
import threading

import numpy as np

from .. import EUnitError
from .host import SharedLib
from .mailbox import Link


class SimLink(Link):
    name = "sim"
    has_cycles = False

    def __init__(self, lib_path):
        self.dll = SharedLib(lib_path)
        self.thread = None
        self.stop = None
        self.base = None

    def _start(self):
        lib = self.dll.load()
        try:
            run = lib.eunit_sim_run
        except AttributeError as e:
            raise EUnitError(f"{self.dll.path.name}: eunit_sim_run not found (host port missing)") from e
        run.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
        run.restype = None
        self.base = ctypes.addressof(ctypes.c_uint32.in_dll(lib, "eunit_mailbox"))
        self.stop = ctypes.c_uint32(0)
        self.thread = threading.Thread(target=run, args=(ctypes.byref(self.stop),), daemon=True,
                                       name="eunit-sim")
        self.thread.start()

    def _halt(self):
        if self.thread is None:
            return
        self.stop.value = 1
        self.thread.join(5.0)
        if self.thread.is_alive():
            raise EUnitError("sim: target thread does not stop (function stuck?)")
        self.thread = None
        self.dll.unload()

    def open(self):
        self._start()
        return self.base

    def close(self):
        self._halt()
        self.dll.release()

    def reset(self):
        self._halt()
        self._start()

    def read(self, addr, nwords):
        buf = (ctypes.c_int32 * nwords)()
        ctypes.memmove(buf, addr, 4 * nwords)
        return np.frombuffer(buf, dtype=np.int32).copy()

    def write(self, addr, words):
        data = np.ascontiguousarray(words, dtype=np.int32)
        ctypes.memmove(addr, data.ctypes.data, 4 * data.size)

    def info(self):
        return {"link": self.name, "library": str(self.dll.path)}
