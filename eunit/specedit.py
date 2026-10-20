"""Editing of suite files (tests, functions, build lists, new suites) for the MCP server.

PyYAML loses the comments: a file is edited as text, one top-level block or one list item at a
time, so the rest of it is kept as written. Every edit is validated by loading the whole suite
(and generating the stimuli of the tests touched); a refused edit restores the file, mtime
included, so make does not rebuild anything.
"""
import os
import re
import textwrap
from pathlib import Path

import yaml

from . import EUnitError
from .spec import load_suite

ROOT = Path(__file__).resolve().parent.parent
TEST_KEYS_ORDER = ("id", "title", "requirement", "requirements", "description", "tags", "setup",
                   "call", "stimuli", "combine", "reset", "checks")
FUNC_KEYS_ORDER = ("prototype", "returns", "custom", "outputs", "description")
BUILD_KEYS = ("sources", "includes", "headers", "defines")


# ----------------------------------------------------------------------------
# Rendering: block style for the structure, flow style for the leaves, like the examples

class _Block(dict):
    pass


class _BlockList(list):
    pass


class _Dumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)        # "  - item" under a key


_Dumper.add_representer(_Block, lambda d, v: d.represent_mapping("tag:yaml.org,2002:map", v.items(),
                                                                 flow_style=False))
_Dumper.add_representer(_BlockList, lambda d, v: d.represent_sequence("tag:yaml.org,2002:seq", v,
                                                                      flow_style=False))


def _dump(node):
    text = yaml.dump(node, Dumper=_Dumper, sort_keys=False, default_flow_style=True,
                     allow_unicode=True, width=100)
    return text.rstrip("\n").removesuffix("\n...").split("\n")


def _ordered(d, order):
    return {**{k: d[k] for k in order if k in d}, **{k: v for k, v in d.items() if k not in order}}


def _test_node(test):
    t = _Block(_ordered(test, TEST_KEYS_ORDER))
    if isinstance(t.get("stimuli"), dict):
        t["stimuli"] = _Block(t["stimuli"])
    if isinstance(t.get("checks"), list):
        t["checks"] = _BlockList(_Block(c) if isinstance(c, dict) else c for c in t["checks"])
    if isinstance(t.get("setup"), list):
        t["setup"] = _BlockList(_Block(s) if isinstance(s, dict) else s for s in t["setup"])
    return t


def _func_node(d):
    return _Block(_ordered({"prototype": d} if isinstance(d, str) else d, FUNC_KEYS_ORDER))


def render_test(test, indent=2):
    lines = _dump(_test_node(test))
    pad = " " * indent
    return [pad + "- " + lines[0]] + [pad + "  " + x for x in lines[1:]]


def render_function(name, d, indent=2):
    return [" " * indent + x for x in _dump(_Block({name: _func_node(d)}))]


def _render_build(build):
    return _dump(_Block({"build": _Block({k: build[k] for k in BUILD_KEYS if build.get(k)})}))


# ----------------------------------------------------------------------------
# Text structure of a suite file

def _top(line):
    """Start of a top-level key (column 0, not a comment nor a list item)."""
    return bool(line) and not line[0].isspace() and line[0] not in "#-"


def _filler(line):
    return not line.strip() or line.lstrip().startswith("#")


def _indent(line):
    return len(line) - len(line.lstrip())


class SpecFile:
    def __init__(self, path):
        self.path = Path(path)
        try:
            raw = self.path.read_bytes().decode("utf-8")
        except OSError as e:
            raise EUnitError(f"cannot read {self.path}: {e}") from e
        self.nl = "\r\n" if "\r\n" in raw else "\n"
        self.lines = raw.replace("\r\n", "\n").split("\n")

    def text(self):
        return self.nl.join(self.lines)

    def block(self, key):
        """(header, content end) of a top-level key, None if absent. The trailing blank and
        comment lines are left to what follows. An empty inline value ([], {}, null) is
        rewritten as an empty block; any other inline value cannot be edited."""
        pat = re.compile(rf"{re.escape(key)}\s*:(?=\s|$)")
        for i, line in enumerate(self.lines):
            if not pat.match(line):
                continue
            value = line.split(":", 1)[1].split(" #", 1)[0].strip()
            if value:
                if yaml.safe_load(value) not in (None, [], {}):
                    raise EUnitError(f"{self.path.name}: '{key}' is written inline ({value}); "
                                     f"write it as a block to edit it here")
                self.lines[i] = f"{key}:"
            end = i + 1
            while end < len(self.lines) and not _top(self.lines[end]):
                end += 1
            while end > i + 1 and _filler(self.lines[end - 1]):
                end -= 1
            return i, end
        return None

    def ensure_block(self, key):
        b = self.block(key)
        if b is None:
            while self.lines and not self.lines[-1].strip():
                self.lines.pop()
            self.lines += ["", f"{key}:", ""]
            b = (len(self.lines) - 2, len(self.lines) - 1)
        return b

    def entries(self, key, list_items):
        """[(start, content end)] of the entries of a block: list items ('- ') or mapping keys."""
        b = self.block(key)
        if b is None:
            return [], None
        head, end = b
        body = [j for j in range(head + 1, end) if not _filler(self.lines[j])]
        if not body:
            return [], None
        ind = _indent(self.lines[body[0]])
        starts = [j for j in body if _indent(self.lines[j]) == ind
                  and (self.lines[j].lstrip().startswith("-") == list_items)]
        if not starts or starts[0] != body[0]:
            raise EUnitError(f"{self.path.name}: unexpected layout of '{key}'")
        out = []
        for s, nxt in zip(starts, starts[1:] + [end]):
            e = nxt
            while e > s + 1 and _filler(self.lines[e - 1]):
                e -= 1
            out.append((s, e))
        return out, ind

    def item_data(self, s, e):
        return yaml.safe_load(textwrap.dedent("\n".join(self.lines[s:e])))

    def find_test(self, tid):
        items, ind = self.entries("tests", True)
        for s, e in items:
            d = self.item_data(s, e)
            if isinstance(d, list) and d and isinstance(d[0], dict) and str(d[0].get("id")) == tid:
                return s, e, ind, d[0]
        return None

    def separated(self, key, list_items):
        """True if the entries of the block are separated by blank lines."""
        items, _ = self.entries(key, list_items)
        return any(not self.lines[e].strip() for _s, e in items[:-1])


# ----------------------------------------------------------------------------
# Validated edits

def _validate(suite_path, test_ids=()):
    """Load the suite and generate the stimuli of the given tests: {test id: samples}."""
    import numpy as np
    from . import stimuli
    from .engine import _words
    from .expr import Namespace
    suite = load_suite(suite_path)
    samples = {}
    tests = [t for t in suite.tests if t.id in test_ids]
    if tests:
        ns = Namespace(suite.models)
        for t in tests:
            try:
                inputs, n = stimuli.build(t, ns)
                _words(t.call, inputs, n)
                for f, args in t.setup:
                    _words(f, {p.name: np.asarray([a]) for p, a in zip(f.inputs, args)}, 1)
            except EUnitError:
                raise
            except Exception as e:
                raise EUnitError(f"{t.id}: stimuli: {type(e).__name__}: {e}") from e
            samples[t.id] = n
    return suite, samples


def _including_suites(path):
    """Suites next to the edited file (siblings of its directory) that include it, e.g. a global
    suite including every suite of the project."""
    found = []
    for y in sorted(path.parent.parent.glob("**/*.y*ml")):
        if y.resolve() == path.resolve() or "build" in y.parts or y.suffix not in (".yaml", ".yml"):
            continue
        try:
            data = yaml.safe_load(y.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and "suite" in data and data.get("include"):
            try:
                if path.resolve() in load_suite(y).files:
                    found.append(y)
            except EUnitError:
                pass                                   # already broken: not the edit's fault
    return found


def commit(spec, suite_path, test_ids=(), dry_run=False):
    """Write the edited file, validate the suite and the suites including the file, restore the
    file if refused (or dry run)."""
    path = spec.path
    dependents = _including_suites(path)
    old = path.read_bytes()
    st = path.stat()
    path.write_bytes(spec.text().encode("utf-8"))
    ok = False
    try:
        suite, samples = _validate(suite_path, test_ids)
        for y in dependents:
            if Path(y).resolve() != Path(suite_path).resolve():
                try:
                    load_suite(y)
                except EUnitError as e:
                    raise EUnitError(f"this edit breaks {y}, which includes {path.name}: {e}") from e
        ok = not dry_run
        return suite, samples
    finally:
        if not ok:
            path.write_bytes(old)
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))


def locate_test(suite_path, tid):
    """File that defines a test of the suite (the suite file or an included one)."""
    suite = load_suite(suite_path)
    for t in suite.tests:
        if t.id == tid:
            return Path(t.source)
    raise EUnitError(f"no test '{tid}' in suite {suite.name} (tests: {[t.id for t in suite.tests]})")


def _clean_test(test):
    if not isinstance(test, dict):
        raise EUnitError("test must be an object (id, title, requirement, call, stimuli, checks...)")
    for k in ("id", "call"):
        if k not in test:
            raise EUnitError(f"test: '{k}' is required")
    return {**test, "id": str(test["id"])}


def add_test(suite_path, test, after=None, dry_run=False):
    test = _clean_test(test)
    spec = SpecFile(suite_path)
    head, _end = spec.ensure_block("tests")
    items, ind = spec.entries("tests", True)
    if after is not None:
        found = spec.find_test(str(after))
        if found is None:
            raise EUnitError(f"no test '{after}' in {spec.path.name}")
        pos = found[1]
    else:
        pos = items[-1][1] if items else head + 1
    ind = 2 if ind is None else ind
    new = render_test(test, ind)
    if items and spec.separated("tests", True):
        new = [""] + new
    spec.lines[pos:pos] = new
    suite, samples = commit(spec, suite_path, [test["id"]], dry_run)
    return {"file": str(spec.path), "yaml": "\n".join(x for x in new if x), "samples": samples.get(test["id"]),
            "tests": [t.id for t in suite.tests]}


def get_test(suite_path, tid):
    src = locate_test(suite_path, tid)
    spec = SpecFile(src)
    s, e, _ind, data = spec.find_test(tid)
    return {"file": str(src), "test": data, "yaml": "\n".join(spec.lines[s:e])}


def update_test(suite_path, tid, test, dry_run=False):
    test = _clean_test(test)
    src = locate_test(suite_path, tid)
    spec = SpecFile(src)
    s, e, ind, _old = spec.find_test(tid)
    new = render_test(test, ind)
    spec.lines[s:e] = new
    suite, samples = commit(spec, suite_path, [test["id"]], dry_run)
    return {"file": str(src), "yaml": "\n".join(new), "samples": samples.get(test["id"]),
            "tests": [t.id for t in suite.tests]}


def remove_test(suite_path, tid, dry_run=False):
    src = locate_test(suite_path, tid)
    spec = SpecFile(src)
    s, e, _ind, _old = spec.find_test(tid)
    items, _ = spec.entries("tests", True)
    starts = [a for a, _b in items]

    def lead(j):                                     # comment lines just above an item are its own
        while spec.lines[j - 1].lstrip().startswith("#"):
            j -= 1
        return j
    k = starts.index(s)
    s = lead(s)
    if k + 1 < len(starts):
        del spec.lines[s:lead(starts[k + 1])]        # the test and the blank lines after it
    else:
        while k and not spec.lines[s - 1].strip():   # last test: the blank lines before it
            s -= 1
        del spec.lines[s:e]
    suite, _ = commit(spec, suite_path, (), dry_run)
    return {"file": str(src), "removed": tid, "tests": [t.id for t in suite.tests]}


def _merge_build(spec, build):
    """Add sources, includes, headers, defines to the build block (comments inside it are lost)."""
    build = {k: [str(x) for x in (build.get(k) or [])] for k in BUILD_KEYS}
    if not any(build.values()):
        return False
    data = yaml.safe_load(spec.text()) or {}
    cur = data.get("build") or {}
    merged = {k: list(cur.get(k) or []) for k in BUILD_KEYS}
    changed = False
    for k, items in build.items():
        for x in items:
            if x not in merged[k]:
                merged[k].append(x)
                changed = True
    if not changed:
        return False
    b = spec.block("build")
    lines = _render_build(merged)
    if b is None:
        f = spec.block("models") or spec.block("functions") or spec.block("tests")
        at = f[0] if f else len(spec.lines)
        spec.lines[at:at] = lines + [""]
    else:
        spec.lines[b[0]:b[1]] = lines
    return True


def missing_files(suite):
    out = [str(p) for p in suite.sources + suite.models if not Path(p).is_file()]
    return out + [str(p) for p in suite.includes if not Path(p).is_dir()]


def add_function(suite_path, name, definition, build=None, dry_run=False):
    spec = SpecFile(suite_path)
    data = yaml.safe_load(spec.text()) or {}
    if name in (data.get("functions") or {}):
        raise EUnitError(f"function '{name}' already declared in {spec.path.name}")
    before = load_suite(suite_path).hash
    build_changed = _merge_build(spec, build or {})
    head, _end = spec.ensure_block("functions")
    entries, ind = spec.entries("functions", False)
    pos = entries[-1][1] if entries else head + 1
    new = render_function(name, definition, 2 if ind is None else ind)
    if entries and spec.separated("functions", False):
        new = [""] + new
    spec.lines[pos:pos] = new
    suite, _ = commit(spec, suite_path, (), dry_run)
    f = suite.functions[name]
    return {"file": str(spec.path), "yaml": "\n".join(x for x in new if x), "signature": f.signature(),
            "inputs": [p.name for p in f.inputs], "outputs": [p.name for p in f.outputs],
            "build_changed": build_changed, "hash": f"0x{suite.hash:08X}", "hash_changed": suite.hash != before,
            "missing_files": missing_files(suite)}


def create_suite(directory, name, functions, build=None, models=None, description="", tests=None,
                 dry_run=False):
    d = Path(directory).expanduser().resolve()
    yml, mk = d / f"{name}.yaml", d / "Makefile"
    for p in (yml, mk):
        if p.exists():
            raise EUnitError(f"{p} already exists")
    if not functions:
        raise EUnitError("a suite needs at least one function")

    lines = [f"# {description or name}", f"suite: {name}"]
    if description:
        lines += _dump(_Block({"description": description}))
    build = {k: [str(x) for x in (build or {}).get(k) or []] for k in BUILD_KEYS}
    if any(build.values()):
        lines += [""] + _render_build(build)
    if models:
        lines += [""] + _dump(_Block({"models": [str(m) for m in models]}))
    lines += ["", "functions:"]
    for fname, fd in functions.items():
        lines += render_function(fname, fd)
    tests = [_clean_test(t) for t in tests or []]
    if tests:
        lines += ["", "tests:"]
        for k, t in enumerate(tests):
            lines += ([""] if k else []) + render_test(t)
    text = "\n".join(lines) + "\n"

    # relative inside the e2Unit tree (like the examples), absolute elsewhere
    root = Path(os.path.relpath(ROOT, d)).as_posix() if d.is_relative_to(ROOT) else ROOT.as_posix()
    makefile = f"EUNIT_ROOT := {root}\nSUITE      := {name}.yaml\ninclude $(EUNIT_ROOT)/mk/eunit.mk\n"

    created_dir = not d.exists()
    d.mkdir(parents=True, exist_ok=True)
    yml.write_bytes(text.encode("utf-8"))
    ok = False
    try:
        suite, samples = _validate(yml, [t["id"] for t in tests])
        if not dry_run:
            mk.write_bytes(makefile.encode("utf-8"))
            ok = True
    finally:
        if not ok:
            yml.unlink()
            if created_dir:
                d.rmdir()
    return {"suite": str(yml), "makefile": str(mk), "yaml": text, "makefile_text": makefile,
            "hash": f"0x{suite.hash:08X}", "samples": samples, "missing_files": missing_files(suite),
            "written": not dry_run}
