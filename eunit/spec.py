"""Test specification: loading, include merging and validation.

A suite file (YAML or JSON) describes the C sources to build, the functions
exposed to the tests (from their C prototype) and the tests themselves.
Every relative path is resolved against the file it appears in.
"""
import json
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from . import EUnitError
from .datatypes import DataType, lookup


# ----------------------------------------------------------------------------
@dataclass
class Port:
    name: str
    dtype: DataType


@dataclass
class Function:
    name: str               # adapter name, used by the tests
    index: int              # position in the adapter table
    prototype: str
    c_name: str             # C function called by a generated adapter
    inputs: list
    outputs: list
    custom: bool            # adapter written by the user with EUNIT_ADAPTER(name)
    has_return: bool

    def signature(self):
        ins = ",".join(p.dtype.name for p in self.inputs)
        outs = ",".join(p.dtype.name for p in self.outputs)
        return f"{self.name}({ins})->({outs})"

    def port(self, name):
        for p in self.inputs + self.outputs:
            if p.name == name:
                return p
        return None


@dataclass
class Check:
    index: int
    description: str
    kind: str                 # "value", "bounds" or "cycles"
    output: str = None
    expect: object = None
    tolerance: dict = field(default_factory=dict)
    window: tuple = None
    where: str = None
    min: object = None
    max: object = None
    cycles: dict = None


@dataclass
class Test:
    id: str
    title: str
    requirements: list
    description: str
    call: Function
    setup: list               # [(Function, [args])]
    stimuli: dict             # input name -> generator spec
    combine: str              # "zip" or "grid"
    checks: list
    reset: bool
    base_dir: Path
    source: Path


@dataclass
class Suite:
    name: str
    path: Path
    description: str = ""
    sources: list = field(default_factory=list)
    includes: list = field(default_factory=list)
    headers: list = field(default_factory=list)
    defines: list = field(default_factory=list)
    models: list = field(default_factory=list)
    functions: dict = field(default_factory=dict)
    tests: list = field(default_factory=list)
    files: list = field(default_factory=list)

    @property
    def hash(self):
        text = "\n".join(f.signature() for f in self.functions.values())
        return zlib.crc32(text.encode()) & 0xFFFFFFFF

    def function_list(self):
        return sorted(self.functions.values(), key=lambda f: f.index)

    def select(self, ids):
        """Keep the tests whose id is in ids (or starts with one of them)."""
        if not ids:
            return list(self.tests)
        chosen = [t for t in self.tests if any(t.id == i or t.id.startswith(i) for i in ids)]
        if not chosen:
            raise EUnitError(f"no test matches {ids}")
        return chosen


# ----------------------------------------------------------------------------
_SUITE_KEYS = {"suite", "description", "include", "build", "models", "functions", "tests"}
_BUILD_KEYS = {"sources", "includes", "headers", "defines"}
_FUNC_KEYS = {"prototype", "returns", "custom", "outputs", "description"}
_TEST_KEYS = {"id", "title", "requirement", "requirements", "description", "call", "setup",
              "stimuli", "combine", "checks", "reset", "tags"}
_CHECK_KEYS = {"desc", "description", "output", "expect", "tolerance", "window", "where",
               "min", "max", "cycles"}
_TOL_KEYS = {"abs", "rel", "modulo"}


def _check_keys(d, allowed, where):
    if not isinstance(d, dict):
        raise EUnitError(f"{where}: expected a mapping, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise EUnitError(f"{where}: unknown key(s) {sorted(unknown)} (allowed: {sorted(allowed)})")


def _as_list(v):
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def _read(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise EUnitError(f"cannot read {path}: {e}") from e
    if path.suffix.lower() == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise EUnitError(f"{path}: {e}") from e
    try:
        import yaml
    except ImportError as e:
        raise EUnitError("PyYAML is required for .yaml suites (pip install pyyaml)") from e
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise EUnitError(f"{path}: {e}") from e


# ----------------------------------------------------------------------------
_PROTO = re.compile(r"^\s*(?P<ret>[A-Za-z_][\w\s]*?)\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<args>[^()]*)\)\s*;?\s*$")


def parse_prototype(proto: str, where: str):
    """'int16_t f(int16_t a, uint8_t b)' -> (ret type or None, name, [(name, type)])."""
    if "*" in proto or "[" in proto:
        raise EUnitError(f"{where}: pointer/array parameters are not supported by generated "
                         f"adapters, write a custom adapter (custom: true)")
    m = _PROTO.match(proto)
    if not m:
        raise EUnitError(f"{where}: cannot parse prototype '{proto}'")
    ret_txt = " ".join(m["ret"].replace("const", " ").split())
    ret = None if ret_txt == "void" else lookup(ret_txt)
    args = []
    args_txt = m["args"].strip()
    if args_txt and args_txt != "void":
        for i, a in enumerate(args_txt.split(",")):
            tokens = a.replace("const", " ").split()
            if not tokens:
                raise EUnitError(f"{where}: empty parameter in '{proto}'")
            try:
                dtype = lookup(" ".join(tokens))
                name = f"arg{i}"
            except EUnitError:
                dtype = lookup(" ".join(tokens[:-1]))
                name = tokens[-1]
            args.append((name, dtype))
    return ret, m["name"], args


def _parse_ports(text, where):
    ports = []
    for item in [s for s in str(text).split(",") if s.strip()]:
        tokens = item.split()
        if len(tokens) < 2:
            raise EUnitError(f"{where}: output '{item.strip()}' must be '<type> <name>'")
        ports.append(Port(tokens[-1], lookup(" ".join(tokens[:-1]))))
    return ports


def _parse_function(name, d, index, where):
    if isinstance(d, str):
        d = {"prototype": d}
    _check_keys(d, _FUNC_KEYS, where)
    if "prototype" not in d:
        raise EUnitError(f"{where}: 'prototype' is required")
    if not re.fullmatch(r"[A-Za-z_]\w*", name):
        raise EUnitError(f"{where}: function name '{name}' is not a C identifier")
    ret, c_name, args = parse_prototype(d["prototype"], where)
    inputs = [Port(n, t) for n, t in args]
    outputs = []
    if ret is not None:
        outputs.append(Port(str(d.get("returns", "ret")), ret))
    custom = bool(d.get("custom", False))
    if "outputs" in d:
        if not custom:
            raise EUnitError(f"{where}: extra 'outputs' need a custom adapter (custom: true)")
        outputs += _parse_ports(d["outputs"], where)
    names = [p.name for p in inputs + outputs]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise EUnitError(f"{where}: duplicated port name(s) {sorted(dup)}")
    if len(inputs) > 255 or len(outputs) > 255:
        raise EUnitError(f"{where}: too many ports")
    return Function(name, index, d["prototype"], c_name, inputs, outputs, custom, ret is not None)


def _parse_tolerance(t, where):
    if t is None:
        return {}
    if isinstance(t, (int, float)):
        return {"abs": float(t)}
    _check_keys(t, _TOL_KEYS, where)
    return {k: float(v) for k, v in t.items()}


def _parse_check(i, d, func, where):
    _check_keys(d, _CHECK_KEYS, where)
    desc = str(d.get("desc", d.get("description", "")))
    window = d.get("window")
    if window is not None:
        if not (isinstance(window, (list, tuple)) and len(window) == 2):
            raise EUnitError(f"{where}: window must be [start, end]")
        window = (window[0], window[1])
    if "cycles" in d:
        cyc = d["cycles"]
        if isinstance(cyc, (int, float)):
            cyc = {"max": cyc}
        _check_keys(cyc, {"max", "mean"}, f"{where}.cycles")
        return Check(i, desc or f"cycles {cyc}", "cycles", cycles=cyc)

    output = d.get("output")
    if output is None:
        if len(func.outputs) != 1:
            raise EUnitError(f"{where}: 'output' is required ({func.name} has "
                             f"{len(func.outputs)} outputs)")
        output = func.outputs[0].name
    if output not in [p.name for p in func.outputs]:
        raise EUnitError(f"{where}: '{output}' is not an output of {func.name} "
                         f"({[p.name for p in func.outputs]})")
    common = dict(output=output, window=window, where=d.get("where"))
    if "expect" in d:
        if "min" in d or "max" in d:
            raise EUnitError(f"{where}: use either expect or min/max in one check")
        return Check(i, desc or f"{output} == {d['expect']}", "value", expect=d["expect"],
                     tolerance=_parse_tolerance(d.get("tolerance"), f"{where}.tolerance"), **common)
    if "min" in d or "max" in d:
        return Check(i, desc or f"{d.get('min', '-inf')} <= {output} <= {d.get('max', '+inf')}",
                     "bounds", min=d.get("min"), max=d.get("max"), **common)
    raise EUnitError(f"{where}: a check needs 'expect', 'min'/'max' or 'cycles'")


def _parse_setup(items, functions, where):
    setup = []
    for j, item in enumerate(_as_list(items)):
        w = f"{where}.setup[{j}]"
        if isinstance(item, dict) and "call" in item:
            _check_keys(item, {"call", "args"}, w)
            fname, args = item["call"], _as_list(item.get("args"))
        elif isinstance(item, dict) and len(item) == 1:
            fname, args = next(iter(item.items()))
            args = _as_list(args)
        elif isinstance(item, str):
            fname, args = item, []
        else:
            raise EUnitError(f"{w}: expected '<function>: [args]'")
        if fname not in functions:
            raise EUnitError(f"{w}: unknown function '{fname}'")
        f = functions[fname]
        if len(args) != len(f.inputs):
            raise EUnitError(f"{w}: {fname} takes {len(f.inputs)} argument(s), got {len(args)}")
        setup.append((f, args))
    return setup


def _parse_test(d, functions, base_dir, source, where):
    _check_keys(d, _TEST_KEYS, where)
    for k in ("id", "call"):
        if k not in d:
            raise EUnitError(f"{where}: '{k}' is required")
    tid = str(d["id"])
    where = f"{source.name}:{tid}"
    if d["call"] not in functions:
        raise EUnitError(f"{where}: unknown function '{d['call']}' (known: {sorted(functions)})")
    func = functions[d["call"]]
    stimuli = d.get("stimuli") or {}
    if not isinstance(stimuli, dict):
        raise EUnitError(f"{where}: stimuli must map each input to a generator")
    names = [p.name for p in func.inputs]
    missing = [n for n in names if n not in stimuli]
    extra = [n for n in stimuli if n not in names]
    if missing or extra:
        raise EUnitError(f"{where}: stimuli must define exactly the inputs {names} "
                         f"(missing {missing}, unknown {extra})")
    combine = d.get("combine", "zip")
    if combine not in ("zip", "grid"):
        raise EUnitError(f"{where}: combine must be 'zip' or 'grid'")
    checks = [_parse_check(i + 1, c, func, f"{where}.checks[{i}]")
              for i, c in enumerate(_as_list(d.get("checks")))]
    if not checks:
        raise EUnitError(f"{where}: at least one check is required")
    reqs = [str(r) for r in _as_list(d.get("requirements", d.get("requirement")))]
    return Test(tid, str(d.get("title", tid)), reqs, str(d.get("description", "")), func,
                _parse_setup(d.get("setup"), functions, where), stimuli, combine, checks,
                bool(d.get("reset", True)), base_dir, source)


# ----------------------------------------------------------------------------
def _merge_unique(dst, items):
    for x in items:
        if x not in dst:
            dst.append(x)


def _load_into(suite: Suite, path: Path, stack):
    path = path.resolve()
    if path in stack:
        raise EUnitError(f"include cycle: {' -> '.join(p.name for p in stack + [path])}")
    if path in suite.files:
        return
    data = _read(path)
    _check_keys(data, _SUITE_KEYS, path.name)
    base = path.parent

    for inc in _as_list(data.get("include")):
        _load_into(suite, base / inc, stack + [path])
    suite.files.append(path)

    build = data.get("build") or {}
    _check_keys(build, _BUILD_KEYS, f"{path.name}.build")
    _merge_unique(suite.sources, [(base / s).resolve() for s in _as_list(build.get("sources"))])
    _merge_unique(suite.includes, [(base / s).resolve() for s in _as_list(build.get("includes"))])
    _merge_unique(suite.headers, [str(h) for h in _as_list(build.get("headers"))])
    _merge_unique(suite.defines, [str(x) for x in _as_list(build.get("defines"))])
    _merge_unique(suite.models, [(base / m).resolve() for m in _as_list(data.get("models"))])

    funcs = data.get("functions") or {}
    if not isinstance(funcs, dict):
        raise EUnitError(f"{path.name}: functions must be a mapping name -> definition")
    for name, fd in funcs.items():
        f = _parse_function(str(name), fd, len(suite.functions), f"{path.name}:functions.{name}")
        if name in suite.functions:
            if suite.functions[name].signature() != f.signature() or \
               suite.functions[name].c_name != f.c_name:
                raise EUnitError(f"{path.name}: function '{name}' redefined differently")
            continue
        suite.functions[name] = f

    ids = {t.id for t in suite.tests}
    for i, td in enumerate(_as_list(data.get("tests"))):
        t = _parse_test(td, suite.functions, base, path, f"{path.name}:tests[{i}]")
        if t.id in ids:
            raise EUnitError(f"{path.name}: duplicated test id '{t.id}'")
        ids.add(t.id)
        suite.tests.append(t)
    return data


def load_suite(path) -> Suite:
    path = Path(path).resolve()
    data = _read(path)
    if not isinstance(data, dict):
        raise EUnitError(f"{path}: a suite must be a mapping")
    suite = Suite(name=str(data.get("suite", path.stem)), path=path,
                  description=str(data.get("description", "")))
    if not re.fullmatch(r"[A-Za-z_][\w-]*", suite.name):
        raise EUnitError(f"{path.name}: invalid suite name '{suite.name}'")
    _load_into(suite, path, [])
    if not suite.functions:
        raise EUnitError(f"{path.name}: no function declared")
    return suite
