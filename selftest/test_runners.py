"""Integration tests: the fixture suite on every runner available here.

The fixture is built with make (EUNIT_MAKE, default 'make'); the tests are
skipped when the toolchains are missing. Each fixture test documents the
verdict e2Unit must produce (PASS-*, FAIL-*, ERROR-*, TGT-* on targets only).
"""
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eunit import checks as C  # noqa: E402
from eunit import engine  # noqa: E402
from eunit.runners.host import HostRunner  # noqa: E402
from eunit.runners.mailbox import MailboxRunner  # noqa: E402
from eunit.runners.sim import SimLink  # noqa: E402
from eunit.spec import load_suite  # noqa: E402

FIXTURE = ROOT / "selftest" / "fixture"
MAKE = os.environ.get("EUNIT_MAKE", "make")
LIB = FIXTURE / "build" / "host" / ("fixture.dll" if os.name == "nt" else "fixture.so")
ELF = FIXTURE / "build" / "ra4e1" / "fixture.elf"


def _build(goal):
    if shutil.which(MAKE) is None and not Path(MAKE).exists():
        return False
    r = subprocess.run([MAKE, "-C", str(FIXTURE), goal], capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
    return r.returncode == 0


HAVE_HOST = _build("host")
HAVE_TARGET = _build("target")
try:
    import unicorn  # noqa: F401
    HAVE_EMU = HAVE_TARGET
except ImportError:
    HAVE_EMU = False


def _expected(test_id):
    return test_id.split("-")[0] if not test_id.startswith("TGT") else None


class Base:
    suite = load_suite(FIXTURE / "fixture.yaml")

    def run_suite(self, runner, ids, compare=None):
        with runner:
            if compare:
                compare.open()
            try:
                res = engine.run_suite(self.suite, runner, self.suite.select(ids), compare, log=lambda *_: None)
            finally:
                if compare:
                    compare.close()
        return {r.test.id: r for r in res.tests}

    def assert_verdicts(self, results):
        for tid, r in results.items():
            exp = _expected(tid)
            if exp:
                self.assertEqual(r.status, exp, f"{tid}: {r.error or [s.message for s in r.steps]}")

    COMMON = ["PASS", "FAIL", "ERROR"]


@unittest.skipUnless(HAVE_HOST, "host compiler / make not available")
class HostRunnerTest(Base, unittest.TestCase):
    def test_verdicts(self):
        res = self.run_suite(HostRunner(self.suite, LIB), self.COMMON)
        self.assert_verdicts(res)
        clamp = res["FAIL-CLAMP"]
        self.assertEqual([s.status for s in clamp.steps], [C.FAIL, C.FAIL])
        self.assertEqual(clamp.steps[0].stats["first_failure"], 3001)   # x = 1001
        self.assertIn("x=1001", clamp.steps[0].message)

    def test_wrong_library_is_refused(self):
        other = load_suite(ROOT / "examples" / "emath" / "tests" / "sin" / "sin.yaml")
        with self.assertRaisesRegex(Exception, "does not match"):
            HostRunner(other, LIB).open()


@unittest.skipUnless(HAVE_HOST, "host compiler / make not available")
class SimRunnerTest(Base, unittest.TestCase):
    def test_verdicts_and_chunking(self):
        runner = MailboxRunner(self.suite, SimLink(LIB), timeout=5)
        res = self.run_suite(runner, self.COMMON, compare=HostRunner(self.suite, LIB))
        self.assert_verdicts(res)
        # PASS-ADD has 35 calls, the 2048-word buffer holds 682 calls of add: also force chunking
        runner = MailboxRunner(self.suite, SimLink(LIB), timeout=5)
        with runner:
            runner.buf_words = 7      # 2 calls per chunk
            r = engine.run_test(self.suite.select(["PASS-ADD"])[0], runner,
                                engine.Namespace(), None)
            runner.buf_words = 7
        self.assertEqual(r.status, C.PASS, r.steps)


@unittest.skipUnless(HAVE_EMU, "arm toolchain or unicorn not available")
class EmuRunnerTest(Base, unittest.TestCase):
    def test_verdicts_hang_fault_recovery(self):
        from eunit.runners.emu import EmuLink
        runner = MailboxRunner(self.suite, EmuLink(ELF), timeout=1.0)
        res = self.run_suite(runner, self.COMMON + ["TGT"], compare=None)
        self.assert_verdicts(res)
        self.assertEqual(res["TGT-HANG"].status, C.ERROR)
        self.assertIn("no answer", res["TGT-HANG"].error)
        self.assertEqual(res["TGT-FAULT"].status, C.ERROR)
        self.assertIn("fault", res["TGT-FAULT"].error.lower())
        self.assertEqual(res["TGT-RECOVER"].status, C.PASS)

    def test_identical_to_host(self):
        from eunit.runners.emu import EmuLink
        runner = MailboxRunner(self.suite, EmuLink(ELF), timeout=5)
        res = self.run_suite(runner, ["PASS"], compare=HostRunner(self.suite, LIB))
        for r in res.values():
            self.assertEqual(r.status, C.PASS, [s.message for s in r.steps])
            self.assertTrue(any("identical to host" in s.description for s in r.steps))


if __name__ == "__main__":
    unittest.main()
