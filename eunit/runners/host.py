"""Host runner: the suite is built as a shared library and called through ctypes."""
import ctypes
import os
import shutil
import tempfile
from pathlib import Path

import numpy as np

from .. import EUnitError
from ..protocol import STATUS_TEXT
from . import Runner


class SharedLib:
    """Load / really unload a shared library, so its static data is reinitialised.

    A private copy is loaded: two users of the same library in one process
    (e.g. sim runner + host comparison) never share static data, and the build
    output is not locked while tests run.
    """

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.lib = None
        self._tmp = None

    def load(self):
        if not self.path.exists():
            raise EUnitError(f"library not found: {self.path} (build it first: make host)")
        if self._tmp is None:
            self._tmp = Path(tempfile.mkdtemp(prefix="eunit-"))
            shutil.copy2(self.path, self._tmp / self.path.name)
        try:
            self.lib = ctypes.CDLL(str(self._tmp / self.path.name))
        except OSError as e:
            raise EUnitError(f"cannot load {self.path}: {e}") from e
        return self.lib

    def release(self):
        """Unload and delete the private copy."""
        self.unload()
        if self._tmp is not None:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None

    def unload(self):
        if self.lib is None:
            return
        handle = self.lib._handle
        self.lib = None
        if os.name == "nt":
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.FreeLibrary.argtypes = [wintypes.HMODULE]
            k32.FreeLibrary.restype = wintypes.BOOL
            k32.FreeLibrary(handle)
        else:
            import _ctypes
            _ctypes.dlclose(handle)

    def u32(self, symbol):
        try:
            return ctypes.c_uint32.in_dll(self.lib, symbol).value
        except ValueError as e:
            raise EUnitError(f"{self.path.name}: symbol '{symbol}' not found, "
                             f"is it an e2Unit suite library?") from e


def check_identity(where, suite, lib_hash, lib_count):
    if lib_hash != suite.hash or lib_count != len(suite.functions):
        raise EUnitError(f"{where} does not match suite '{suite.name}' "
                         f"(hash 0x{lib_hash:08X} / {lib_count} functions, expected "
                         f"0x{suite.hash:08X} / {len(suite.functions)}): rebuild it")


class HostRunner(Runner):
    name = "host"

    def __init__(self, suite, lib_path):
        super().__init__(suite)
        self.dll = SharedLib(lib_path)
        self._exec = None

    def _load(self):
        lib = self.dll.load()
        check_identity(self.dll.path.name, self.suite, self.dll.u32("eunit_suite_hash"),
                       self.dll.u32("eunit_suite_count"))
        f = lib.eunit_exec
        f.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        f.restype = ctypes.c_uint32
        self._exec = f

    def open(self):
        self._load()

    def close(self):
        self._exec = None
        self.dll.release()

    def reset(self):
        self._exec = None
        self.dll.unload()
        self._load()

    def batch(self, func, words):
        n = words.shape[0]
        nin, nout = len(func.inputs), len(func.outputs)
        buf = np.zeros(max(n * (nin + nout), 1), dtype=np.int32)
        buf[:n * nin] = words.reshape(-1)
        status = self._exec(func.index, n, buf.ctypes.data, buf.size, None)
        if status:
            raise EUnitError(f"eunit_exec({func.name}) failed: {STATUS_TEXT.get(status, status)}")
        return buf[n * nin:n * (nin + nout)].reshape(n, nout).copy(), None

    def info(self):
        return {"runner": self.name, "library": str(self.dll.path)}
