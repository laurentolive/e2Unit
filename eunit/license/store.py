"""License files: one per type, encrypted for the current user (Windows DPAPI), as eScope."""
import ctypes
import json
import os
from pathlib import Path

from .info import LicenseInfo, LicenseType
from .product import PRODUCT_NAME


def _dir():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / PRODUCT_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / PRODUCT_NAME.lower()


def path(type_):
    return _dir() / f"license{LicenseType(type_).value}.dat"


# ----------------------------------------------------------------------------
if os.name == "nt":
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]

    def _dpapi(data, protect):
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _Blob()
        fn = _crypt32.CryptProtectData if protect else _crypt32.CryptUnprotectData
        if not fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
            raise OSError(ctypes.get_last_error(), "DPAPI failed")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            _kernel32.LocalFree(blob_out.pbData)

    def _protect(data):
        return _dpapi(data, True)

    def _unprotect(data):
        return _dpapi(data, False)
else:
    def _protect(data):
        return data

    def _unprotect(data):
        return data


# ----------------------------------------------------------------------------
def save(lic):
    p = path(lic.type)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_protect(json.dumps(lic.to_dict()).encode()))
    if os.name != "nt":
        p.chmod(0o600)


def delete(type_):
    p = path(type_)
    if p.exists():
        p.unlink()


def load(type_=None):
    """The license of a type, or the best one installed (Professional, Personal, Demonstration)."""
    if type_ is None:
        for t in (LicenseType.PROFESSIONAL, LicenseType.PERSONAL, LicenseType.DEMONSTRATION):
            lic = load(t)
            if lic is not None:
                return lic
        return None
    p = path(type_)
    if not p.exists():
        return None
    try:
        return LicenseInfo.from_dict(json.loads(_unprotect(p.read_bytes())))
    except (OSError, ValueError, KeyError, TypeError):
        return None   # unreadable (other user, corrupted): as if absent
