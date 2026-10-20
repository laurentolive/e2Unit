"""J-Link link: target memory access over SWD/JTAG with pylink (pip install pylink-square)."""
from pathlib import Path

import numpy as np

from .. import EUnitError
from .. import elf
from .mailbox import Link


def _pylink():
    try:
        import pylink
    except ImportError as e:
        raise EUnitError("the jlink runner needs pylink: pip install pylink-square") from e
    return pylink


def open_probe(device, serial=None, speed=4000, interface="swd", dll=None):
    pylink = _pylink()
    try:
        jl = pylink.JLink(lib=pylink.Library(dllpath=dll)) if dll else pylink.JLink()
        jl.disable_dialog_boxes()
        # check first: opening without a probe pops up a blocking J-Link dialog
        serials = [int(e.SerialNumber) for e in jl.connected_emulators()]
        if not serials:
            raise EUnitError("no J-Link probe connected (USB)")
        if serial is None and len(serials) > 1:
            raise EUnitError(f"several J-Link probes connected {serials}: choose one with --serial")
        if serial is not None and int(serial) not in serials:
            raise EUnitError(f"J-Link {serial} not connected (connected: {serials})")
        jl.open(serial_no=serial if serial is not None else serials[0])
        tif = pylink.enums.JLinkInterfaces.SWD if interface.lower() == "swd" \
            else pylink.enums.JLinkInterfaces.JTAG
        jl.set_tif(tif)
        jl.connect(device, speed=speed)
    except pylink.errors.JLinkException as e:
        raise EUnitError(f"J-Link: {e}") from e
    return jl


def list_probes(dll=None):
    pylink = _pylink()
    jl = pylink.JLink(lib=pylink.Library(dllpath=dll)) if dll else pylink.JLink()
    return [(e.SerialNumber, e.acProduct.decode(errors="replace") if isinstance(e.acProduct, bytes)
             else str(e.acProduct)) for e in jl.connected_emulators()]


def flash(jl, image):
    image = Path(image)
    if not image.exists():
        raise EUnitError(f"image not found: {image}")
    pylink = _pylink()
    try:
        jl.halt()
        jl.flash_file(str(image), 0)
        jl.reset(ms=0, halt=False)
    except pylink.errors.JLinkException as e:
        raise EUnitError(f"J-Link flash failed: {e}") from e


class JLinkLink(Link):
    name = "jlink"
    has_cycles = True

    def __init__(self, elf_path, device, serial=None, speed=4000, interface="swd", dll=None,
                 flash_image=None):
        self.elf_path = Path(elf_path)
        self.device = device
        self.serial = serial
        self.speed = speed
        self.interface = interface
        self.dll = dll
        self.flash_image = flash_image
        self.jl = None

    def open(self):
        if not self.device:
            raise EUnitError("jlink: the device name is required (e.g. --device R7FA4E10D)")
        base, _ = elf.symbol(self.elf_path, "eunit_mailbox")
        self.jl = open_probe(self.device, self.serial, self.speed, self.interface, self.dll)
        if self.flash_image:
            flash(self.jl, self.flash_image)
        else:
            self.reset()
        return base

    def close(self):
        if self.jl is not None:
            self.jl.close()
            self.jl = None

    def reset(self):
        self.jl.reset(ms=0, halt=False)

    def read(self, addr, nwords):
        return np.array(self.jl.memory_read32(addr, nwords), dtype=np.uint32).view(np.int32)

    def write(self, addr, words):
        data = np.ascontiguousarray(words, dtype=np.int32).view(np.uint32)
        self.jl.memory_write32(addr, data.tolist())

    def info(self):
        d = {"link": self.name, "elf": str(self.elf_path), "device": self.device,
             "speed_khz": self.speed}
        if self.jl is not None:
            try:
                d["probe"] = str(self.jl.serial_number)
                d["jlink_dll"] = str(self.jl.version)
            except Exception:
                pass
        return d
