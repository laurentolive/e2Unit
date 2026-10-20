"""Unit tests of the e2Unit Python core (no compiler needed).

Run: python -m unittest discover -s selftest -v
"""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eunit import EUnitError  # noqa: E402
from eunit import checks as C  # noqa: E402
from eunit import codegen, stimuli  # noqa: E402
from eunit.datatypes import lookup  # noqa: E402
from eunit.expr import Namespace  # noqa: E402
from eunit.spec import load_suite, parse_prototype  # noqa: E402


def write_suite(tmp, text, name="s.yaml"):
    p = Path(tmp) / name
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return p


class DataTypes(unittest.TestCase):
    def test_round_trip(self):
        for name, values in [("int8_t", [-128, -1, 0, 127]), ("uint8_t", [0, 255]),
                             ("int16_t", [-32768, 32767]), ("uint16_t", [0, 65535]),
                             ("int32_t", [-2**31, 2**31 - 1]), ("uint32_t", [0, 2**32 - 1]),
                             ("bool", [0, 1])]:
            t = lookup(name)
            w = t.to_words(np.array(values))
            self.assertEqual(w.dtype, np.int32)
            np.testing.assert_array_equal(t.from_words(w), values, err_msg=name)

    def test_float(self):
        t = lookup("f32")
        np.testing.assert_allclose(t.from_words(t.to_words([1.5, -2.25])), [1.5, -2.25])

    def test_out_of_range_is_refused(self):
        with self.assertRaisesRegex(EUnitError, "out of range"):
            lookup("uint8_t").to_words([256])
        with self.assertRaisesRegex(EUnitError, "out of range"):
            lookup("s16").to_words([-32769])

    def test_aliases(self):
        self.assertEqual(lookup("u16").name, "uint16_t")
        self.assertEqual(lookup("const unsigned int").name, "uint32_t")
        with self.assertRaises(EUnitError):
            lookup("double")


class Prototype(unittest.TestCase):
    def test_parse(self):
        ret, name, args = parse_prototype("int16_t emath_atan2(int16_t y, const int16_t x);", "t")
        self.assertEqual((ret.name, name), ("int16_t", "emath_atan2"))
        self.assertEqual([(n, t.name) for n, t in args], [("y", "int16_t"), ("x", "int16_t")])

    def test_void_and_unnamed(self):
        ret, _, args = parse_prototype("void f(void)", "t")
        self.assertIsNone(ret)
        self.assertEqual(args, [])
        _, _, args = parse_prototype("uint8_t g(uint8_t, unsigned int count)", "t")
        self.assertEqual([n for n, _ in args], ["arg0", "count"])

    def test_pointer_needs_custom_adapter(self):
        with self.assertRaisesRegex(EUnitError, "custom adapter"):
            parse_prototype("int32_t sum(const int16_t *buf, uint8_t n)", "t")


class Spec(unittest.TestCase):
    BASE = """
        suite: demo
        build: {sources: [a.c]}
        functions:
          f: {prototype: "int16_t f(int16_t x)", returns: y}
        tests:
          - id: T1
            call: f
            stimuli: {x: [1, 2]}
            checks: [{expect: x}]
        """

    def test_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = load_suite(write_suite(tmp, self.BASE))
            self.assertEqual(s.name, "demo")
            self.assertEqual(s.functions["f"].outputs[0].name, "y")
            self.assertEqual(s.sources, [(Path(tmp) / "a.c").resolve()])
            self.assertIn("eunit_adapter_f", codegen.generate_c(s))

    def test_typo_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = self.BASE.replace("checks: [{expect: x}]", "checks: [{expected: x}]")
            with self.assertRaisesRegex(EUnitError, "unknown key"):
                load_suite(write_suite(tmp, text))

    def test_stimuli_must_match_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = self.BASE.replace("stimuli: {x: [1, 2]}", "stimuli: {z: [1, 2]}")
            with self.assertRaisesRegex(EUnitError, "stimuli must define"):
                load_suite(write_suite(tmp, text))

    def test_include_merges_and_detects_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_suite(tmp, self.BASE, "a.yaml")
            write_suite(tmp, self.BASE.replace("T1", "T2"), "b.yaml")
            s = load_suite(write_suite(tmp, "suite: all\ninclude: [a.yaml, b.yaml]\n", "all.yaml"))
            self.assertEqual([t.id for t in s.tests], ["T1", "T2"])
            self.assertEqual(len(s.functions), 1)
            self.assertEqual(len(s.sources), 1)
            write_suite(tmp, self.BASE, "c.yaml")
            with self.assertRaisesRegex(EUnitError, "duplicated test id"):
                load_suite(write_suite(tmp, "suite: bad\ninclude: [a.yaml, c.yaml]\n", "bad.yaml"))

    def test_hash_depends_on_signatures(self):
        with tempfile.TemporaryDirectory() as tmp:
            h1 = load_suite(write_suite(tmp, self.BASE)).hash
            h2 = load_suite(write_suite(tmp, self.BASE.replace("int16_t x", "int32_t x"))).hash
            self.assertNotEqual(h1, h2)


class Stimuli(unittest.TestCase):
    def _test(self, stim, combine="zip", proto="int16_t f(int16_t a, int16_t b)"):
        with tempfile.TemporaryDirectory() as tmp:
            text = f"""
                suite: s
                functions: {{f: "{proto}"}}
                tests:
                  - id: T
                    call: f
                    combine: {combine}
                    stimuli: {stim}
                    checks: [{{expect: 0}}]
                """
            t = load_suite(write_suite(tmp, text)).tests[0]
            return stimuli.build(t, Namespace())

    def test_zip_broadcast(self):
        v, n = self._test("{a: {range: [0, 3]}, b: 7}")
        self.assertEqual(n, 4)
        np.testing.assert_array_equal(v["b"], [7, 7, 7, 7])

    def test_grid(self):
        v, n = self._test("{a: [1, 2], b: [10, 20, 30]}", combine="grid")
        self.assertEqual(n, 6)
        np.testing.assert_array_equal(v["a"], [1, 1, 1, 2, 2, 2])
        np.testing.assert_array_equal(v["b"], [10, 20, 30, 10, 20, 30])

    def test_length_mismatch(self):
        with self.assertRaisesRegex(EUnitError, "different lengths"):
            self._test("{a: [1, 2], b: [1, 2, 3]}")

    def test_random_is_deterministic(self):
        a, _ = self._test("{a: {random: [-100, 100], n: 50}, b: 0}")
        b, _ = self._test("{a: {random: [-100, 100], n: 50}, b: 0}")
        np.testing.assert_array_equal(a["a"], b["a"])
        self.assertTrue(np.all((a["a"] >= -100) & (a["a"] <= 100)))

    def test_segments_continuous(self):
        v, n = self._test("{a: {segments: [{n: 4, dc: 5}, {n: 4, ramp: [0, 300]}]}, b: 0}")
        np.testing.assert_array_equal(v["a"], [5, 5, 5, 5, 0, 100, 200, 300])

    def test_expr_large_values(self):
        v, n = self._test("{a: {expr: '(i + 1) ** 2', n: 70000}}", proto="uint16_t f(uint32_t a)")
        self.assertEqual(int(v["a"][-1]), 70000 ** 2)


class Checks(unittest.TestCase):
    def _check(self, actual, expect, tol=None, window=None, where=None):
        from eunit.spec import Check
        chk = Check(1, "d", "value", output="y", expect=expect, tolerance=tol or {}, window=window, where=where)
        n = len(actual)
        variables = {"x": np.arange(n), "y": np.asarray(actual, dtype=np.int64)}
        return C.evaluate(chk, variables, n, Namespace(), ["x"], None, "t")

    def test_exact_and_tolerance(self):
        self.assertEqual(self._check([0, 1, 2], "x").status, C.PASS)
        r = self._check([0, 1, 4], "x")
        self.assertEqual(r.status, C.FAIL)
        self.assertEqual(r.stats["first_failure"], 2)
        self.assertEqual(self._check([0, 1, 4], "x", {"abs": 2}).status, C.PASS)

    def test_modulo(self):
        r = self._check([-32768, 32767], [32768, -32767], {"abs": 2, "modulo": 65536})
        self.assertEqual(r.status, C.PASS)

    def test_window_and_where(self):
        self.assertEqual(self._check([9, 1, 2], "x", window=(1, None)).status, C.PASS)
        self.assertEqual(self._check([9, 1, 2], "x", where="x > 0").status, C.PASS)
        self.assertEqual(self._check([9, 1, 2], "x", where="x > 5").status, C.ERROR)

    def test_nan_fails(self):
        from eunit.spec import Check
        chk = Check(1, "d", "value", output="y", expect="0.0", tolerance={"abs": 1})
        r = C.evaluate(chk, {"y": np.array([np.nan]), "x": np.zeros(1)}, 1, Namespace(), ["x"], None, "t")
        self.assertEqual(r.status, C.FAIL)

    def test_cycles_skip_without_counter(self):
        from eunit.spec import Check
        chk = Check(1, "c", "cycles", cycles={"max": 10})
        self.assertEqual(C.evaluate(chk, {}, 1, Namespace(), [], None, "t").status, C.SKIP)
        r = C.evaluate(chk, {}, 1, Namespace(), [], C.CycleStats(2, 5, 12, 17), "t")
        self.assertEqual(r.status, C.FAIL)


if __name__ == "__main__":
    unittest.main()
