"""MCP server (Model Context Protocol, stdio transport): e2Unit for AI assistants.

    python eunit_cli.py mcp

Tools: find and describe suites, build them, run them on host / sim / emu / target and get the
verdicts, list J-Link probes, show the license. Resources: README and tutorials.

No dependency: JSON-RPC 2.0, one message per line on stdin/stdout. Builds and runs go through
make and the CLI in child processes, as from a terminal: the shared libraries are never loaded
in the server (they could not be rebuilt on Windows) and nothing but protocol reaches stdout.
Relative paths are relative to the server working directory (the project of the client).
"""
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

from . import EUnitError, __version__
from .license.product import PRODUCT_NAME

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "eunit_cli.py"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
OUTPUT_LIMIT = 12000          # characters of make / CLI output returned to the client
SKIP_DIRS = {"build", ".git", ".venv", "venv", "node_modules", "__pycache__"}

# runner -> (make goal, report directory under build/report)
RUNNERS = {
    "host": ("test-host", "host"),
    "sim": ("test-sim", "sim"),
    "emu": ("test-emu", "emu-{board}"),
    "target": ("test-target", "{board}"),
}

INSTRUCTIONS = f"""{PRODUCT_NAME} tests C functions on PC and on target from one YAML suite
(prototype, stimuli, expected values, tolerances). A suite is a YAML file next to a 3-line
Makefile. Workflow: find_suites -> describe_suite -> run_suite (runner host first, then sim,
emu or target). Verdicts: PASS, FAIL (a check failed), ERROR (specification, build, probe).
To write tests: create_suite, add_function, add_test / get_test / update_test / remove_test
(validated before writing, comments kept), then run_suite with tests=[id].
The YAML format is documented in the resource eunit://docs/README.md and the tutorials."""


# ----------------------------------------------------------------------------
# Helpers

def _path(p):
    return Path(p).expanduser().resolve()


def _suite_path(p):
    path = _path(p)
    if path.is_dir():
        yamls = [y for y in sorted(path.glob("*.yaml")) if _is_suite(y)]
        if len(yamls) != 1:
            raise EUnitError(f"{path}: expected one suite YAML in the directory, found {len(yamls)}")
        path = yamls[0]
    if not path.is_file():
        raise EUnitError(f"{path}: no such file")
    return path


def _is_suite(path):
    import yaml
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return isinstance(data, dict) and "suite" in data


def _make():
    make = os.environ.get("EUNIT_MAKE") or shutil.which("make") or shutil.which("mingw32-make")
    if not make:
        raise EUnitError("GNU make not found: put it in PATH or set EUNIT_MAKE")
    return make


def _tail(text):
    text = text.strip()
    return text if len(text) <= OUTPUT_LIMIT else "...\n" + text[-OUTPUT_LIMIT:]


def _exec(cmd, cwd, timeout):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        r = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "")
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        raise EUnitError(f"timeout after {timeout} s: {' '.join(map(str, cmd))}\n{_tail(out)}") from e
    except OSError as e:
        raise EUnitError(f"cannot run {cmd[0]}: {e}") from e
    return r.returncode, r.stdout + (("\n" + r.stderr) if r.stderr.strip() else "")


def _make_vars(board, extra):
    v = [f"BOARD={board}"] if board else []
    return v + [f"{k}={val}" for k, val in (extra or {}).items()]


def _suite_dir(suite):
    d = suite.parent
    if not (d / "Makefile").is_file():
        raise EUnitError(f"{d}: no Makefile next to {suite.name} (see README, 'Ecrire une suite')")
    return d


def _board(d, board):
    """Board of a suite directory: argument, else BOARD of the Makefile, else ra4e1."""
    if board:
        return board
    for line in (d / "Makefile").read_text(encoding="utf-8", errors="replace").splitlines():
        k, sep, v = line.partition("=")
        if sep and k.rstrip(":?+ \t") == "BOARD":
            return v.strip()
    return "ra4e1"


# ----------------------------------------------------------------------------
# Tools

def tool_find_suites(root=".", **_):
    root = _path(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for f in sorted(filenames):
            p = Path(dirpath) / f
            if p.suffix in (".yaml", ".yml") and _is_suite(p):
                found.append({"suite": str(p), "makefile": (p.parent / "Makefile").is_file()})
    return {"root": str(root), "suites": found}


def tool_describe_suite(suite, **_):
    from .spec import load_suite
    path = _suite_path(suite)
    s = load_suite(path)

    def ports(ps):
        return [{"name": p.name, "type": p.dtype.name} for p in ps]

    return {
        "suite": s.name, "path": str(s.path), "hash": f"0x{s.hash:08X}", "description": s.description,
        "sources": [str(x) for x in s.sources], "includes": [str(x) for x in s.includes],
        "headers": s.headers, "defines": s.defines, "models": [str(x) for x in s.models],
        "makefile": (path.parent / "Makefile").is_file(),
        "functions": [{"name": f.name, "index": f.index, "prototype": f.prototype,
                       "signature": f.signature(), "custom_adapter": f.custom,
                       "inputs": ports(f.inputs), "outputs": ports(f.outputs)}
                      for f in s.function_list()],
        "tests": [{"id": t.id, "title": t.title, "requirements": t.requirements,
                   "function": t.call.name, "reset": t.reset,
                   "setup": [{fn.name: args} for fn, args in t.setup],
                   "checks": [c.description for c in t.checks]} for t in s.tests],
    }


def tool_build(suite, what="host", board=None, make_vars=None, timeout=600, **_):
    goals = {"host": ["host"], "target": ["target"], "all": ["host", "target"], "clean": ["clean"]}
    if what not in goals:
        raise EUnitError(f"what must be one of {sorted(goals)}")
    d = _suite_dir(_suite_path(suite))
    code, out = _exec([_make(), "-C", d, *goals[what], *_make_vars(board, make_vars)], d, timeout)
    return {"ok": code == 0, "exit_code": code, "output": _tail(out)}, code != 0


def tool_run_suite(suite, runner="host", tests=None, board=None, verbose=False, plot=None,
                   plot_all=False, details=False, make_vars=None, timeout=900, **_):
    if runner not in RUNNERS:
        raise EUnitError(f"runner must be one of {sorted(RUNNERS)}")
    path = _suite_path(suite)
    d = _suite_dir(path)
    goal, report = RUNNERS[runner]
    report_dir = d / "build" / "report" / report.format(board=_board(d, board))
    results = report_dir / "results.json"
    if results.exists():
        results.unlink()                          # never return the verdict of a previous run

    opts = []
    if tests:
        opts += ["-t", *([tests] if isinstance(tests, str) else tests)]
    if verbose:
        opts.append("-v")
    if plot:
        opts += ["--plot", str(_path(plot))]
        if plot_all:
            opts.append("--plot-all")
    mv = dict(make_vars or {})
    if opts:
        mv["EUNIT_RUN_OPTS"] = " ".join(f'"{o}"' if " " in o else o for o in opts)
    code, out = _exec([_make(), "-C", d, goal, *_make_vars(board, mv)], d, timeout)

    # make exits with 2 whatever the CLI verdict: the verdict comes from the report
    res = {"exit_code": code, "verdict": "ERROR"}
    if results.exists():
        data = json.loads(results.read_text(encoding="utf-8"))
        res["verdict"] = data["status"]
        if not details:
            for t in data.get("tests", []):
                for s in t.get("steps", []):
                    s.pop("stats", None)
        res["results"] = data
        res["reports"] = str(report_dir)
    else:
        res["error"] = "no results: the build or the run failed before the report (see output)"
    if plot:
        res["plots"] = str(_path(plot))
    res["output"] = _tail(out)
    return res, "results" not in res


def _written(res, dry_run):
    return {**res, "written": not dry_run}


def tool_get_test(suite, id, **_):
    from .specedit import get_test
    return get_test(_suite_path(suite), str(id))


def tool_add_test(suite, test, after=None, dry_run=False, **_):
    from .specedit import add_test
    return _written(add_test(_suite_path(suite), test, after, dry_run), dry_run)


def tool_update_test(suite, id, test, dry_run=False, **_):
    from .specedit import update_test
    return _written(update_test(_suite_path(suite), str(id), test, dry_run), dry_run)


def tool_remove_test(suite, id, dry_run=False, **_):
    from .specedit import remove_test
    return _written(remove_test(_suite_path(suite), str(id), dry_run), dry_run)


def _build_lists(sources=None, includes=None, headers=None, defines=None):
    return {"sources": sources, "includes": includes, "headers": headers, "defines": defines}


def _func_def(prototype, returns=None, custom=False, outputs=None, description=None):
    d = {"prototype": prototype}
    if returns:
        d["returns"] = returns
    if custom:
        d["custom"] = True
    if outputs:
        d["outputs"] = outputs
    if description:
        d["description"] = description
    return d


def tool_add_function(suite, name, prototype, returns=None, custom=False, outputs=None,
                      description=None, sources=None, includes=None, headers=None, defines=None,
                      dry_run=False, **_):
    from .specedit import add_function
    res = add_function(_suite_path(suite), name, _func_def(prototype, returns, custom, outputs, description),
                       _build_lists(sources, includes, headers, defines), dry_run)
    return _written(res, dry_run)


def tool_create_suite(directory, name, functions, description="", sources=None, includes=None,
                      headers=None, defines=None, models=None, tests=None, dry_run=False, **_):
    from .specedit import create_suite
    return create_suite(_path(directory), name, functions, _build_lists(sources, includes, headers, defines),
                        models, description, tests, dry_run)


def tool_list_probes(jlink_dll=None, **_):
    cmd = [sys.executable, CLI, "probes"] + (["--jlink-dll", jlink_dll] if jlink_dll else [])
    code, out = _exec(cmd, ROOT, 60)
    return {"exit_code": code, "output": _tail(out)}, code != 0


def tool_license_status(**_):
    code, out = _exec([sys.executable, CLI, "license", "status"], ROOT, 60)
    return {"exit_code": code, "output": _tail(out)}, code != 0


_SUITE = {"type": "string", "description": "suite YAML file, or the directory holding it "
                                           "(relative to the server working directory)"}
_BOARD = {"type": "string", "description": "board under boards/ (default: the Makefile one, ra4e1)"}
_VARS = {"type": "object", "additionalProperties": {"type": "string"},
         "description": "extra make variables, e.g. {\"JLINK_OPTS\": \"--serial 123456\"}"}
_DRY = {"type": "boolean", "default": False,
        "description": "validate and return the YAML without writing the file"}
_ID = {"type": "string", "description": "test id"}
_TEST = {
    "type": "object", "required": ["id", "call", "stimuli", "checks"],
    "description": "test, as written in the YAML 'tests' list (see eunit://docs/README.md)",
    "properties": {
        "id": {"type": "string", "description": "unique in the suite, e.g. SIN-004"},
        "title": {"type": "string"},
        "requirement": {"type": ["string", "array"], "items": {"type": "string"},
                        "description": "requirement id(s) covered (traceability)"},
        "description": {"type": "string"},
        "call": {"type": "string", "description": "function of the suite (describe_suite)"},
        "setup": {"type": "array", "description": "calls before the stimuli, e.g. [{\"rms_init\": [6]}]"},
        "stimuli": {"type": "object", "description":
                    "one generator per input: constant 0.5 | values [0, 16384] | {range: [lo, hi], step} "
                    "| {linspace: [lo, hi, n]} | {random: [lo, hi], n, seed} | {segments: [{n, dc|sine: "
                    "{amp, period}|square|ramp: [a, b]|noise}]} | {expr: \"<numpy expr of i>\", n} | "
                    "{file: data.npy|.csv}. Values outside the C type range are an error."},
        "combine": {"type": "string", "enum": ["zip", "grid"]},
        "reset": {"type": "boolean", "description": "false: keep the state of the previous test"},
        "checks": {"type": "array", "items": {"type": "object"}, "description":
                   "each: {desc, output (if several), expect: <numpy expr of inputs/outputs/i/n/models "
                   "or list>, tolerance: {abs, rel, modulo}} | {min, max} | {cycles: {max, mean}} "
                   "(target only); optional window: [start, end], where: \"<bool expr>\". Helpers: np, "
                   "sat(x, 'int16_t'), wrap(x, 'uint8_t'), isqrt, shift(x, k), model functions."},
    }}
_FUNC_PROPS = {
    "prototype": {"type": "string", "description": "C prototype, e.g. \"int16_t emath_sin(int16_t angle)\" "
                                                   "(int8_t..uint32_t, bool, float)"},
    "returns": {"type": "string", "description": "name of the returned output (default ret)"},
    "custom": {"type": "boolean", "description": "adapter written in C with EUNIT_ADAPTER(name) "
                                                 "(pointers, context, several outputs)"},
    "outputs": {"type": "string", "description": "extra outputs of a custom adapter, e.g. "
                                                 "\"uint32_t acc, int16_t last\""},
    "description": {"type": "string"},
}
_BUILD_PROPS = {k: {"type": "array", "items": {"type": "string"}, "description": d} for k, d in {
    "sources": "C files to compile, relative to the suite YAML",
    "includes": "include directories, relative to the suite YAML",
    "headers": "headers included by the generated code (declare the tested functions)",
    "defines": "preprocessor definitions"}.items()}

TOOLS = {
    "find_suites": (tool_find_suites, True, {
        "description": "Find the e2Unit suites (YAML files with a 'suite' key) under a directory.",
        "inputSchema": {"type": "object", "properties": {
            "root": {"type": "string", "description": "directory to search (default: working directory)"}}}}),
    "describe_suite": (tool_describe_suite, True, {
        "description": "Load and validate a suite: functions (prototype, inputs, outputs), tests "
                       "(id, requirements, checks), sources, hash. Specification errors are reported.",
        "inputSchema": {"type": "object", "properties": {"suite": _SUITE}, "required": ["suite"]}}),
    "build": (tool_build, False, {
        "description": "Build a suite with make: host shared library, target firmware (ELF/HEX), "
                       "both, or clean its build directory. Returns the compiler output.",
        "inputSchema": {"type": "object", "properties": {
            "suite": _SUITE,
            "what": {"type": "string", "enum": ["host", "target", "all", "clean"], "default": "host"},
            "board": _BOARD, "make_vars": _VARS,
            "timeout": {"type": "number", "default": 600}}, "required": ["suite"]}}),
    "run_suite": (tool_run_suite, False, {
        "description": "Build and run a suite, return the verdict and the results of every test and "
                       "check. Runners: host (PC library), sim (mailbox protocol on PC), emu (ARM "
                       "firmware in an emulator, compared with host), target (flash with J-Link, run "
                       "on the board, compared with host, CPU cycles). Reports (JUnit, JSON, Excel) "
                       "are written under build/report.",
        "inputSchema": {"type": "object", "properties": {
            "suite": _SUITE,
            "runner": {"type": "string", "enum": list(RUNNERS), "default": "host"},
            "tests": {"type": "array", "items": {"type": "string"},
                      "description": "test ids or id prefixes to run (default: all)"},
            "board": _BOARD,
            "verbose": {"type": "boolean", "default": False, "description": "log every check"},
            "plot": {"type": "string", "description": "directory for PNG plots of the failed checks"},
            "plot_all": {"type": "boolean", "default": False, "description": "plot every check"},
            "details": {"type": "boolean", "default": False,
                        "description": "include the error statistics of every check"},
            "make_vars": _VARS,
            "timeout": {"type": "number", "default": 900}}, "required": ["suite"]}}),
    "get_test": (tool_get_test, True, {
        "description": "Return a test as written in its YAML file (the suite file or an included one), "
                       "to modify it with update_test.",
        "inputSchema": {"type": "object", "properties": {"suite": _SUITE, "id": _ID},
                        "required": ["suite", "id"]}}),
    "add_test": (tool_add_test, False, {
        "description": "Add a test to a suite file, at the end of 'tests' or after a given test. The "
                       "rest of the file (comments, layout) is kept. The suite is validated and the "
                       "stimuli generated before writing: a refused test leaves the file unchanged. "
                       "Then run it with run_suite(tests=[id]).",
        "inputSchema": {"type": "object", "properties": {
            "suite": _SUITE, "test": _TEST,
            "after": {"type": "string", "description": "id of the test to insert after (default: last)"},
            "dry_run": _DRY}, "required": ["suite", "test"]}}),
    "update_test": (tool_update_test, False, {
        "description": "Replace a test (found in the suite file or an included one) by a new "
                       "definition, validated like add_test. The id may change.",
        "inputSchema": {"type": "object", "properties": {
            "suite": _SUITE, "id": _ID, "test": _TEST, "dry_run": _DRY},
            "required": ["suite", "id", "test"]}}),
    "remove_test": (tool_remove_test, False, {
        "description": "Remove a test (and the comment lines just above it) from its YAML file.",
        "inputSchema": {"type": "object", "properties": {"suite": _SUITE, "id": _ID, "dry_run": _DRY},
                        "required": ["suite", "id"]}}),
    "add_function": (tool_add_function, False, {
        "description": "Declare a function to test in a suite, and optionally add the C sources, "
                       "include directories and headers it needs to the build. The suite hash "
                       "changes: target firmware must be rebuilt (run_suite does it). A custom "
                       "adapter must then be written in a C source of the suite.",
        "inputSchema": {"type": "object", "properties": {
            "suite": _SUITE,
            "name": {"type": "string", "description": "name used by the tests (C identifier)"},
            **_FUNC_PROPS, **_BUILD_PROPS, "dry_run": _DRY}, "required": ["suite", "name", "prototype"]}}),
    "create_suite": (tool_create_suite, False, {
        "description": "Create a new suite: <directory>/<name>.yaml and its Makefile, with functions, "
                       "build lists and optionally first tests. Paths in the YAML are relative to it.",
        "inputSchema": {"type": "object", "properties": {
            "directory": {"type": "string", "description": "directory of the suite (created if needed)"},
            "name": {"type": "string", "description": "suite name, also the YAML file name"},
            "description": {"type": "string"},
            "functions": {"type": "object", "description": "name -> prototype string or "
                          "{prototype, returns, custom, outputs, description}",
                          "additionalProperties": {"type": ["string", "object"]}},
            **_BUILD_PROPS,
            "models": {"type": "array", "items": {"type": "string"},
                       "description": "Python files whose functions are usable in the expressions"},
            "tests": {"type": "array", "items": _TEST},
            "dry_run": _DRY}, "required": ["directory", "name", "functions"]}}),
    "list_probes": (tool_list_probes, True, {
        "description": "List the connected J-Link probes (serial number, product).",
        "inputSchema": {"type": "object", "properties": {
            "jlink_dll": {"type": "string", "description": "path of JLink_x64.dll (default: installed)"}}}}),
    "license_status": (tool_license_status, True, {
        "description": f"Show the {PRODUCT_NAME} license of this computer.",
        "inputSchema": {"type": "object", "properties": {}}}),
}


def _tool_list():
    return [{"name": name, **spec,
             "annotations": {"readOnlyHint": ro, "openWorldHint": False}}
            for name, (_fn, ro, spec) in TOOLS.items()]


def _call_tool(name, args):
    if name not in TOOLS:
        raise _RpcError(-32602, f"unknown tool {name}")
    try:
        r = TOOLS[name][0](**(args or {}))
        data, is_error = r if isinstance(r, tuple) else (r, False)
    except EUnitError as e:
        data, is_error = {"error": str(e)}, True
    except TypeError as e:
        data, is_error = {"error": f"bad arguments: {e}"}, True
    text = json.dumps(data, indent=1, ensure_ascii=False, default=str)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


# ----------------------------------------------------------------------------
# Resources: documentation

def _docs():
    """uri -> file: README.md, tutorials/*.md (English), tutoriels/*.md (French)."""
    docs = {"eunit://docs/README.md": ROOT / "README.md"}
    for p in sorted((ROOT / "docs").glob("*/*.md")):
        docs[f"eunit://docs/{p.relative_to(ROOT / 'docs').as_posix()}"] = p
    return {uri: p for uri, p in docs.items() if p.is_file()}


def _resource_list():
    out = []
    for uri, p in _docs().items():
        first = p.read_text(encoding="utf-8").lstrip().splitlines()[:1]
        title = first[0].lstrip("# ").strip() if first else p.stem
        out.append({"uri": uri, "name": uri.removeprefix("eunit://docs/"), "title": title,
                    "mimeType": "text/markdown"})
    return out


def _resource_read(uri):
    p = _docs().get(uri)
    if p is None:
        raise _RpcError(-32002, f"resource not found: {uri}")
    return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": p.read_text(encoding="utf-8")}]}


# ----------------------------------------------------------------------------
# JSON-RPC over stdio

class _RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _handle(method, params):
    if method == "initialize":
        asked = params.get("protocolVersion")
        return {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "e2unit", "title": PRODUCT_NAME, "version": __version__},
                "instructions": INSTRUCTIONS}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": _tool_list()}
    if method == "tools/call":
        return _call_tool(params.get("name"), params.get("arguments"))
    if method == "resources/list":
        return {"resources": _resource_list()}
    if method == "resources/templates/list":
        return {"resourceTemplates": []}
    if method == "resources/read":
        return _resource_read(params.get("uri"))
    raise _RpcError(-32601, f"method not found: {method}")


def serve(stdin=None, stdout=None):
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    sys.stdout = sys.stderr            # a stray print must not corrupt the protocol

    def send(msg):
        stdout.write(json.dumps(msg, ensure_ascii=False).encode("utf-8") + b"\n")
        stdout.flush()

    for line in stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        if not isinstance(msg, dict) or "method" not in msg:
            continue                   # a response or a batch: nothing is ever requested from the client
        mid = msg.get("id")
        try:
            result = _handle(msg["method"], msg.get("params") or {})
            if mid is not None:
                send({"jsonrpc": "2.0", "id": mid, "result": result})
        except _RpcError as e:
            if mid is not None:
                send({"jsonrpc": "2.0", "id": mid, "error": {"code": e.code, "message": str(e)}})
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            if mid is not None and not msg["method"].startswith("notifications/"):
                send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}})
    return 0
