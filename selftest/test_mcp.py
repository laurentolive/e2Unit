"""MCP server: protocol and the tools that need no build (python -m unittest selftest.test_mcp)."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eunit.mcp_server import serve  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixture" / "fixture.yaml"


def _session(*messages, workspace=None, demo=False):
    stdin = io.BytesIO(b"".join(json.dumps(m).encode() + b"\n" for m in messages))
    stdout = io.BytesIO()
    saved = sys.stdout
    try:
        serve(stdin, stdout, workspace, demo)
    finally:
        sys.stdout = saved
    return {r["id"]: r for r in map(json.loads, stdout.getvalue().splitlines())}


def _call(name, args, mid=1):
    return {"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": {"name": name, "arguments": args}}


class _Workspace(unittest.TestCase):
    """A temporary workspace holding a copy of the fixture suite."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        shutil.copytree(FIXTURE.parent, self.tmp / "fixture", ignore=shutil.ignore_patterns("build"))
        self.suite = self.tmp / "fixture" / "fixture.yaml"
        self.original = self.suite.read_bytes()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def session(self, *messages):
        return _session(*messages, workspace=str(self.tmp))


class McpTest(_Workspace):
    def test_handshake_and_lists(self):
        r = self.session({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2024-11-05", "capabilities": {}}},
                     {"jsonrpc": "2.0", "method": "notifications/initialized"},
                     {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                     {"jsonrpc": "2.0", "id": 3, "method": "resources/list"},
                     {"jsonrpc": "2.0", "id": 4, "method": "nope"})
        self.assertEqual(len(r), 4)                         # no answer to the notification
        self.assertEqual(r[1]["result"]["protocolVersion"], "2024-11-05")
        self.assertIn(str(self.tmp), r[1]["result"]["instructions"])
        names = {t["name"] for t in r[2]["result"]["tools"]}
        self.assertTrue({"find_suites", "describe_suite", "build", "run_suite"} <= names)
        uris = {x["uri"] for x in r[3]["result"]["resources"]}
        self.assertIn("eunit://docs/README.md", uris)
        self.assertEqual(r[4]["error"]["code"], -32601)

    def test_describe_and_errors(self):
        r = self.session(_call("describe_suite", {"suite": "fixture"}, 1),
                         _call("describe_suite", {"suite": "fixture/missing.yaml"}, 2),
                         _call("find_suites", {}, 3))
        self.assertFalse(r[1]["result"]["isError"])
        d = json.loads(r[1]["result"]["content"][0]["text"])
        self.assertEqual(d["path"], str(self.suite))
        self.assertTrue(d["functions"] and d["tests"])
        self.assertTrue(r[2]["result"]["isError"])
        found = json.loads(r[3]["result"]["content"][0]["text"])["suites"]
        self.assertEqual([s["suite"] for s in found], [str(self.suite)])

    def test_workspace_required_and_enforced(self):
        def error(r):
            self.assertTrue(r["result"]["isError"])
            return json.loads(r["result"]["content"][0]["text"])["error"]
        saved = os.environ.pop("EUNIT_WORKSPACE", None)
        try:
            r = _session(_call("find_suites", {}))
        finally:
            if saved is not None:
                os.environ["EUNIT_WORKSPACE"] = saved
        self.assertIn("no workspace", error(r[1]))
        r = _session(_call("find_suites", {}), workspace=str(FIXTURE.parent))
        self.assertIn("inside e2Unit", error(r[1]))
        r = self.session(_call("describe_suite", {"suite": str(FIXTURE)}, 1),
                         _call("describe_suite", {"suite": "../elsewhere.yaml"}, 2),
                         _call("create_suite", {"directory": str(FIXTURE.parent / "new"), "name": "new",
                                                "functions": {"inc": "uint8_t fx_inc_u8(uint8_t x)"}}, 3))
        self.assertIn("outside the workspace", error(r[1]))
        self.assertIn("outside the workspace", error(r[2]))
        self.assertIn("outside the workspace", error(r[3]))
        self.assertFalse((FIXTURE.parent / "new").exists())

    def test_demo(self):
        ws = self.tmp / "demo"                               # created by --demo
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        r = _session(init, _call("find_suites", {}, 2), workspace=str(ws), demo=True)
        self.assertIn("examples", r[1]["result"]["instructions"])
        found = json.loads(r[2]["result"]["content"][0]["text"])["suites"]
        self.assertIn(str(ws / "examples" / "emath" / "tests" / "sin" / "sin.yaml"), [s["suite"] for s in found])
        self.assertTrue(all(s["makefile"] for s in found))
        mk = ws / "examples" / "emath" / "tests" / "sin" / "Makefile"
        from eunit.mcp_server import ROOT
        self.assertIn(f"EUNIT_ROOT := {ROOT.as_posix()}\n", mk.read_text(encoding="utf-8"))
        self.assertFalse(list((ws / "examples").rglob("build")))

        mk.write_text("# changed by the user\n", encoding="utf-8")   # a second --demo keeps the copy
        _session(workspace=str(ws), demo=True)
        self.assertEqual(mk.read_text(encoding="utf-8"), "# changed by the user\n")


class SpecEditTest(_Workspace):
    """Edits on a copy of the fixture suite: comments kept, refused edits leave the file as is."""

    def call(self, tool, **args):
        r = self.session(_call(tool, {"suite": str(self.suite), **args}))[1]["result"]
        return r["isError"], json.loads(r["content"][0]["text"])

    def test_add_update_remove(self):
        test = {"id": "PASS-ADD-2", "title": "small sums", "call": "add",
                "stimuli": {"a": {"range": [-5, 5]}, "b": 1}, "checks": [{"expect": "a + 1"}]}
        err, d = self.call("add_test", test=test, after="PASS-ADD")
        self.assertFalse(err, d)
        self.assertEqual(d["samples"], 11)
        self.assertEqual(d["tests"][:3], ["PASS-ADD", "PASS-ADD-2", "FAIL-CLAMP"])
        text = self.suite.read_text(encoding="utf-8")
        self.assertIn("# Self test suite", text)
        self.assertIn("  - id: PASS-ADD-2\n    title: small sums\n", text)

        err, d = self.call("get_test", id="PASS-ADD-2")
        self.assertEqual(d["test"]["stimuli"]["a"], {"range": [-5, 5]})
        test["checks"].append({"min": -4})
        err, d = self.call("update_test", id="PASS-ADD-2", test=test)
        self.assertFalse(err, d)
        self.assertIn("- min: -4", self.suite.read_text(encoding="utf-8"))

        err, d = self.call("remove_test", id="PASS-ADD-2")
        self.assertFalse(err, d)
        self.assertEqual(self.suite.read_bytes(), self.original)

    def test_refused_edits(self):
        cases = [{"id": "PASS-ADD", "call": "add", "stimuli": {"a": 0, "b": 0}, "checks": [{"expect": 0}]},
                 {"id": "X", "call": "nope", "stimuli": {}, "checks": [{"expect": 0}]},
                 {"id": "X", "call": "inc", "stimuli": {"x": [256]}, "checks": [{"expect": 0}]},
                 {"id": "X", "call": "inc", "stimuli": {"x": [1]}, "checks": []}]
        for test in cases:
            err, d = self.call("add_test", test=test)
            self.assertTrue(err, test)
            self.assertEqual(self.suite.read_bytes(), self.original)
        err, d = self.call("add_test", test=cases[2] | {"stimuli": {"x": [1]}}, dry_run=True)
        self.assertFalse(err, d)
        self.assertFalse(d["written"])
        self.assertEqual(self.suite.read_bytes(), self.original)

    def test_add_function_and_create_suite(self):
        err, d = self.call("add_function", name="neg", prototype="int16_t fx_neg(int16_t x)", returns="y")
        self.assertFalse(err, d)
        self.assertTrue(d["hash_changed"])
        self.assertEqual(d["signature"], "neg(int16_t)->(int16_t)")
        err, d = self.call("add_function", name="neg", prototype="int16_t fx_neg(int16_t x)")
        self.assertTrue(err)

        r = self.session(_call("create_suite", {
            "directory": "new", "name": "new", "sources": ["../fixture/fixture.c"],
            "functions": {"inc": "uint8_t fx_inc_u8(uint8_t x)"},
            "tests": [{"id": "INC", "call": "inc", "stimuli": {"x": {"range": [0, 254]}},
                       "checks": [{"expect": "x + 1"}]}]}))[1]["result"]
        self.assertFalse(r["isError"], r)
        from eunit.spec import load_suite
        suite = load_suite(self.tmp / "new" / "new.yaml")
        self.assertEqual([t.id for t in suite.tests], ["INC"])
        self.assertIn("mk/eunit.mk", (self.tmp / "new" / "Makefile").read_text())


if __name__ == "__main__":
    unittest.main()
