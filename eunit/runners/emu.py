"""Emulated target: the real ARM firmware (ELF built for the board) runs in the
Unicorn CPU emulator (pip install unicorn) and is driven through the mailbox,
exactly as with a J-Link probe.

This validates the code produced by the target compiler without hardware.
The emulator is instruction accurate, not cycle accurate: no cycle counts.
"""
from pathlib import Path

import numpy as np

from .. import EUnitError
from .. import elf
from .. import protocol as P
from .mailbox import Link

_BLOCK = 0x10000            # mapping granularity (64 KiB)
_PPB = (0xE0000000, 0x100000)  # system control space (DWT, SCB...), plain memory here
_SLICE = 200_000            # instructions executed per host access


def _unicorn():
    try:
        import unicorn
        from unicorn import arm_const
    except ImportError as e:
        raise EUnitError("the emu runner needs unicorn: pip install unicorn") from e
    return unicorn, arm_const


class EmuLink(Link):
    name = "emu"
    has_cycles = False

    def __init__(self, elf_path, cpu="cortex-m33"):
        self.elf_path = Path(elf_path)
        self.cpu = cpu
        self.uc = None
        self.base = None
        self.pc = None
        self.instructions = 0

    # ------------------------------------------------------------------
    def _load_image(self):
        from elftools.elf.elffile import ELFFile
        with open(self.elf_path, "rb") as f:
            e = ELFFile(f)
            if e["e_machine"] != "EM_ARM":
                raise EUnitError(f"{self.elf_path.name} is not an ARM firmware")
            loads, spans = [], []
            for seg in e.iter_segments():
                if seg["p_type"] != "PT_LOAD":
                    continue
                if seg["p_filesz"]:
                    loads.append((seg["p_paddr"], seg.data()))
                    spans.append((seg["p_paddr"], seg["p_filesz"]))
                spans.append((seg["p_vaddr"], seg["p_memsz"]))
        estack, _ = elf.symbol(self.elf_path, "_estack")
        ram_start = min((a for a, n in spans if a >= 0x20000000 and n), default=estack - _BLOCK)
        spans.append((ram_start, estack - ram_start))
        return loads, spans, estack

    def _boot(self):
        unicorn, A = _unicorn()
        loads, spans, _ = self._load_image()
        uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB | unicorn.UC_MODE_MCLASS)
        models = {"cortex-m0": A.UC_CPU_ARM_CORTEX_M0, "cortex-m3": A.UC_CPU_ARM_CORTEX_M3,
                  "cortex-m4": A.UC_CPU_ARM_CORTEX_M4, "cortex-m7": A.UC_CPU_ARM_CORTEX_M7,
                  "cortex-m33": A.UC_CPU_ARM_CORTEX_M33}
        if self.cpu not in models:
            raise EUnitError(f"emu: unknown cpu {self.cpu} ({sorted(models)})")
        uc.ctl_set_cpu_model(models[self.cpu])

        blocks = set()
        for addr, size in spans:
            for b in range(addr // _BLOCK, (addr + max(size, 1) - 1) // _BLOCK + 1):
                blocks.add(b)
        for b in sorted(blocks):
            uc.mem_map(b * _BLOCK, _BLOCK)
        uc.mem_map(*_PPB)
        for addr, data in loads:
            uc.mem_write(addr, data)

        vectors = np.frombuffer(bytes(uc.mem_read(0, 8)), dtype=np.uint32)
        uc.reg_write(A.UC_ARM_REG_SP, int(vectors[0]))
        self.pc = int(vectors[1])
        self.uc = uc
        self._arm = A
        self._unicorn = unicorn

    def _step(self, count=_SLICE):
        """Let the firmware run for a while (it polls the mailbox)."""
        try:
            self.uc.emu_start(self.pc | 1, 0xFFFFFFFE, count=count)
            self.pc = self.uc.reg_read(self._arm.UC_ARM_REG_PC)
            self.instructions += count
        except self._unicorn.UcError as e:
            pc = self.uc.reg_read(self._arm.UC_ARM_REG_PC)
            self._report_fault(pc, e)

    def _report_fault(self, pc, err):
        """Emulate eunit_fault(): the runner sees a CPU fault on the pending request."""
        if self.base is None:
            raise EUnitError(f"emu: fault at boot, PC 0x{pc:08X}: {err}")
        req = self.read_raw(self.base + 4 * P.W_REQ, 1)
        self.write_raw(self.base + 4 * P.W_FAULT_PC, np.array([pc], dtype=np.uint32).view(np.int32))
        self.write_raw(self.base + 4 * P.W_STATUS, np.array([P.STATUS_FAULT], dtype=np.int32))
        self.write_raw(self.base + 4 * P.W_ACK, req)
        self.pc = None

    # ------------------------------------------------------------------
    def open(self):
        self.base, _ = elf.symbol(self.elf_path, "eunit_mailbox")
        self._boot()
        return self.base

    def close(self):
        self.uc = None

    def reset(self):
        self._boot()

    def read_raw(self, addr, nwords):
        return np.frombuffer(bytes(self.uc.mem_read(addr, 4 * nwords)), dtype=np.int32).copy()

    def write_raw(self, addr, words):
        self.uc.mem_write(addr, np.ascontiguousarray(words, dtype=np.int32).tobytes())

    def read(self, addr, nwords):
        if self.pc is not None:
            self._step()
        return self.read_raw(addr, nwords)

    def write(self, addr, words):
        self.write_raw(addr, words)

    def info(self):
        return {"link": self.name, "elf": str(self.elf_path), "cpu": self.cpu}
