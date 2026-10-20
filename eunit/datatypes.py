"""C scalar types supported by the adapter ABI (one 32-bit word per value)."""
from dataclasses import dataclass

import numpy as np

from . import EUnitError


@dataclass(frozen=True)
class DataType:
    name: str        # canonical C name
    kind: str        # "int", "bool" or "float"
    bits: int
    signed: bool

    @property
    def min(self):
        if self.kind == "float":
            return float(np.finfo(np.float32).min)
        if self.kind == "bool":
            return 0
        return -(1 << (self.bits - 1)) if self.signed else 0

    @property
    def max(self):
        if self.kind == "float":
            return float(np.finfo(np.float32).max)
        if self.kind == "bool":
            return 1
        return (1 << (self.bits - 1)) - 1 if self.signed else (1 << self.bits) - 1

    # ------------------------------------------------------------------
    def to_words(self, values, what="value"):
        """Encode values (array-like) into int32 words, refusing out-of-range values."""
        v = np.asarray(values)
        if self.kind == "float":
            return v.astype(np.float32).view(np.int32)
        if v.dtype.kind == "f":
            if not np.all(np.isfinite(v)):
                raise EUnitError(f"{what}: non finite value for {self.name}")
            v = np.rint(v)
        v = v.astype(np.int64)
        if self.kind == "bool":
            v = (v != 0).astype(np.int64)
        bad = (v < self.min) | (v > self.max)
        if np.any(bad):
            first = int(v[np.argmax(bad)])
            raise EUnitError(f"{what}: {first} is out of range for {self.name} [{self.min}, {self.max}]")
        return (v & 0xFFFFFFFF).astype(np.uint32).view(np.int32)

    def from_words(self, words):
        """Decode int32 words into int64 (integers) or float64 (floats) values."""
        w = np.asarray(words, dtype=np.int32)
        if self.kind == "float":
            return w.view(np.float32).astype(np.float64)
        if self.kind == "bool":
            return (w != 0).astype(np.int64)
        u = w.astype(np.int64) & ((1 << self.bits) - 1)
        if self.signed:
            half = 1 << (self.bits - 1)
            u = ((u ^ half) - half)
        return u

    def c_from_word(self, expr):
        """C expression converting an int32 word into this type."""
        if self.kind == "float":
            return f"eunit_w2f({expr})"
        if self.kind == "bool":
            return f"({expr} != 0)"
        return f"({self.name}){expr}"

    def c_to_word(self, expr):
        """C expression converting a value of this type into an int32 word."""
        if self.kind == "float":
            return f"eunit_f2w({expr})"
        if self.kind == "bool":
            return f"(({expr}) ? 1 : 0)"
        if self.name == "uint32_t":
            return f"(int32_t)(uint32_t)({expr})"
        return f"(int32_t)({expr})"


_TYPES = {
    "int8_t": DataType("int8_t", "int", 8, True),
    "uint8_t": DataType("uint8_t", "int", 8, False),
    "int16_t": DataType("int16_t", "int", 16, True),
    "uint16_t": DataType("uint16_t", "int", 16, False),
    "int32_t": DataType("int32_t", "int", 32, True),
    "uint32_t": DataType("uint32_t", "int", 32, False),
    "bool": DataType("bool", "bool", 8, False),
    "float": DataType("float", "float", 32, True),
}

_ALIASES = {
    "s8": "int8_t", "i8": "int8_t", "signed char": "int8_t",
    "u8": "uint8_t", "unsigned char": "uint8_t",
    "s16": "int16_t", "i16": "int16_t", "short": "int16_t",
    "u16": "uint16_t", "unsigned short": "uint16_t",
    "s32": "int32_t", "i32": "int32_t", "int": "int32_t",
    "u32": "uint32_t", "unsigned": "uint32_t", "unsigned int": "uint32_t",
    "_Bool": "bool", "Bool": "bool",
    "f32": "float", "float32_t": "float",
}


def lookup(name: str) -> DataType:
    key = " ".join(name.replace("const", " ").split())
    key = _ALIASES.get(key, key)
    if key not in _TYPES:
        supported = ", ".join(list(_TYPES) + sorted(_ALIASES))
        raise EUnitError(f"unsupported type '{name}' (supported: {supported})")
    return _TYPES[key]
