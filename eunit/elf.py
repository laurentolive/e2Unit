"""ELF helpers (pyelftools): symbol addresses and constant values of a firmware."""
import struct
from pathlib import Path

from . import EUnitError


def _open(path):
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError as e:
        raise EUnitError("pyelftools is required: pip install pyelftools") from e
    path = Path(path)
    if not path.exists():
        raise EUnitError(f"ELF not found: {path} (build it first: make target)")
    return ELFFile(open(path, "rb"))


def symbol(path, name):
    """Return (address, size) of a symbol."""
    f = _open(path)
    try:
        symtab = f.get_section_by_name(".symtab")
        syms = symtab.get_symbol_by_name(name) if symtab else None
        if not syms:
            raise EUnitError(f"{Path(path).name}: symbol '{name}' not found")
        s = syms[0]
        return int(s["st_value"]), int(s["st_size"])
    finally:
        f.stream.close()


def read_u32(path, name):
    """Value of an initialised 32-bit constant (e.g. eunit_suite_hash)."""
    addr, _ = symbol(path, name)
    f = _open(path)
    try:
        for sec in f.iter_sections():
            start, size = sec["sh_addr"], sec["sh_size"]
            if sec["sh_type"] != "SHT_NOBITS" and start <= addr < start + size:
                data = sec.data()[addr - start:addr - start + 4]
                return struct.unpack("<I", data)[0]
    finally:
        f.stream.close()
    raise EUnitError(f"{Path(path).name}: '{name}' has no initial value")
