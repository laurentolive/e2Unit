"""Command line: python eunit_cli.py <command> ..."""
import argparse
import shutil
import sys
from pathlib import Path

from . import EUnitError, __version__
from . import codegen, engine, report
from .license.product import PRODUCT_NAME
from .spec import load_suite


def _cmd_gen(a):
    suite = load_suite(a.suite)
    for p in codegen.write(suite, a.out):
        print(f"eunit: generated {p}")
    return 0


def _cmd_list(a):
    suite = load_suite(a.suite)
    print(f"suite {suite.name} (hash 0x{suite.hash:08X})")
    for f in suite.function_list():
        kind = "custom" if f.custom else f.c_name
        print(f"  fn {f.index}: {f.signature()}  [{kind}]")
    for t in suite.tests:
        req = f" [{', '.join(t.requirements)}]" if t.requirements else ""
        print(f"  test {t.id}: {t.title}{req} - {len(t.checks)} check(s)")
    return 0


def _make_runner(a, suite, kind):
    if kind == "host":
        from .runners.host import HostRunner
        if not a.lib:
            raise EUnitError("--lib is required for the host runner")
        return HostRunner(suite, a.lib)
    from .runners.mailbox import MailboxRunner
    if kind == "sim":
        from .runners.sim import SimLink
        if not a.lib:
            raise EUnitError("--lib is required for the sim runner")
        return MailboxRunner(suite, SimLink(a.lib), timeout=a.timeout)
    if kind in ("jlink", "emu"):
        from . import elf
        if not a.elf:
            raise EUnitError(f"--elf is required for the {kind} runner")
        fw_hash = elf.read_u32(a.elf, "eunit_suite_hash")
        if fw_hash != suite.hash:
            raise EUnitError(f"{a.elf} was built from another suite version "
                             f"(hash 0x{fw_hash:08X}, expected 0x{suite.hash:08X}): rebuild it")
    if kind == "emu":
        from .runners.emu import EmuLink
        return MailboxRunner(suite, EmuLink(a.elf, a.cpu), timeout=a.timeout)
    if kind == "jlink":
        from .runners.jlink import JLinkLink
        image = None
        if a.flash:
            image = Path(a.image) if a.image else Path(a.elf).with_suffix(".hex")
        link = JLinkLink(a.elf, a.device, a.serial, a.speed, a.interface, a.jlink_dll, image)
        return MailboxRunner(suite, link, timeout=a.timeout)
    raise EUnitError(f"unknown runner {kind}")


def _cmd_run(a):
    suite = load_suite(a.suite)
    tests = suite.select(a.test)
    runner = _make_runner(a, suite, a.runner)
    from .license import check_at_startup
    license_text = check_at_startup()
    compare = None
    if a.compare_host:
        from .runners.host import HostRunner
        compare = HostRunner(suite, a.compare_host)

    print(f"{PRODUCT_NAME} {__version__}: suite {suite.name}, {len(tests)} test(s) on {a.runner}"
          + (" (compared with host)" if compare else ""))
    print(f"eunit: {license_text}")
    with runner:
        if compare:
            compare.open()
        try:
            result = engine.run_suite(suite, runner, tests, compare, verbose=a.verbose)
            result.license = license_text
        finally:
            if compare:
                compare.close()

    out = Path(a.report_dir) if a.report_dir else None
    junit = a.junit or (out / "junit.xml" if out else None)
    js = a.json or (out / "results.json" if out else None)
    xlsx = a.xlsx or (out / f"{suite.name}_{a.runner}.xlsx" if out else None)
    if junit:
        report.write_junit(result, junit)
    if js:
        report.write_json(result, js)
    if xlsx:
        report.write_xlsx(result, xlsx)
    if a.plot:
        from .plot import plot_suite
        n = len(plot_suite(result, a.plot, a.plot_all))
        print(f"eunit: {n} plot(s) in {a.plot}")

    m = result.meta()
    print(f"eunit: {m['status']} - {m['PASS']} passed, {m['FAIL']} failed, {m['ERROR']} errors, "
          f"{m['SKIP']} skipped in {result.duration:.2f} s"
          + (f" - reports in {out}" if out else ""))
    return 0 if result.status != "FAIL" else 1


def _cmd_flash(a):
    from .runners.jlink import flash, open_probe
    jl = open_probe(a.device, a.serial, a.speed, a.interface, a.jlink_dll)
    try:
        flash(jl, a.image)
    finally:
        jl.close()
    print(f"eunit: flashed {a.image} on {a.device}")
    return 0


def _cmd_probes(a):
    from .runners.jlink import list_probes
    probes = list_probes(a.jlink_dll)
    for serial, product in probes:
        print(f"{serial}  {product}")
    if not probes:
        print("no J-Link probe connected")
    return 0


def _cmd_license(a):
    import webbrowser
    from .license import LicenseManager, product
    from .license.ui import make_ui
    ui = make_ui()
    try:
        mgr = LicenseManager(ui)
        if a.action == "choose":
            if mgr.license is not None and not mgr.license.is_expired:
                print("eunit: the current license is valid; 'eunit license activate' enters a Professional key")
            else:
                mgr.ensure()
        elif a.action == "activate":
            mgr.activate(a.key)
        elif a.action == "deactivate":
            mgr.deactivate()
        elif a.action == "check":
            ok = mgr.revalidate(silent=False)
            if ok is False and (mgr.license is None or mgr.license.type.value != "Professional"):
                print("eunit: no Professional license to validate")
        elif a.action == "buy":
            webbrowser.open(product.BUY_URL)
            print(f"eunit: {product.BUY_URL}")
        elif a.action == "portal":
            webbrowser.open(product.PORTAL_URL)
            print(f"eunit: {product.PORTAL_URL}")
        print(f"eunit: {mgr.status_text()}")
        lic = mgr.license
        if lic is not None and lic.type.value == "Professional" and lic.customer_email:
            print(f"eunit: licensed to {lic.customer_email}, last validated "
                  f"{lic.last_validated_utc:%Y-%m-%d %H:%M} UTC")
    finally:
        ui.close()
    return 0


def _cmd_fs(a):
    """Portable file operations for the makefiles (cmd.exe or sh)."""
    for p in map(Path, a.paths):
        if a.op == "mkdir":
            p.mkdir(parents=True, exist_ok=True)
        elif p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    return 0


def _probe_args(p):
    p.add_argument("--device", help="J-Link device name, e.g. R7FA4E10D")
    p.add_argument("--serial", type=int, help="J-Link serial number (default: the only probe)")
    p.add_argument("--speed", type=int, default=4000, help="SWD speed in kHz (default 4000)")
    p.add_argument("--interface", default="swd", choices=["swd", "jtag"])
    p.add_argument("--jlink-dll", help="path of JLink_x64.dll (default: installed one)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="eunit", description="e2Unit - unit tests of C functions on host and target")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("gen", help="generate the adapter table and the build fragment")
    p.add_argument("suite")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=_cmd_gen)

    p = sub.add_parser("list", help="list functions and tests of a suite")
    p.add_argument("suite")
    p.set_defaults(fn=_cmd_list)

    p = sub.add_parser("run", help="run a suite")
    p.add_argument("suite")
    p.add_argument("--runner", choices=["host", "sim", "emu", "jlink"], default="host")
    p.add_argument("--lib", help="suite shared library (host, sim)")
    p.add_argument("--elf", help="test firmware ELF (emu, jlink)")
    p.add_argument("--cpu", default="cortex-m33", help="emulated core (emu), e.g. cortex-m4")
    p.add_argument("--flash", action="store_true", help="flash the firmware before running (jlink)")
    p.add_argument("--image", help="image to flash (default: ELF with .hex suffix)")
    _probe_args(p)
    p.add_argument("--compare-host", metavar="LIB", help="also run on the host library and require identical outputs")
    p.add_argument("-t", "--test", nargs="+", help="test ids (or prefixes) to run")
    p.add_argument("--timeout", type=float, default=10.0, help="per request timeout in seconds")
    p.add_argument("--report-dir", help="write junit.xml, results.json and an Excel report here")
    p.add_argument("--junit")
    p.add_argument("--json")
    p.add_argument("--xlsx")
    p.add_argument("--plot", metavar="DIR", help="save PNG plots of failed checks")
    p.add_argument("--plot-all", action="store_true", help="plot every check, not only failures")
    p.add_argument("-v", "--verbose", action="store_true", help="print every check")
    p.set_defaults(fn=_cmd_run)

    p = sub.add_parser("flash", help="flash an image with J-Link")
    p.add_argument("image")
    _probe_args(p)
    p.set_defaults(fn=_cmd_flash)

    p = sub.add_parser("probes", help="list connected J-Link probes")
    p.add_argument("--jlink-dll")
    p.set_defaults(fn=_cmd_probes)

    p = sub.add_parser("license", help="show or manage the license (Demonstration, Personal, Professional)")
    p.add_argument("action", nargs="?", default="status",
                   choices=["status", "choose", "activate", "deactivate", "check", "buy", "portal"],
                   help="status (default), choose a license, activate a Professional key, deactivate it on "
                        "this computer, check it online now, open the buy page or the customer portal")
    p.add_argument("key", nargs="?", help="Professional license key (activate)")
    p.set_defaults(fn=_cmd_license)

    p = sub.add_parser("fs", help=argparse.SUPPRESS)
    p.add_argument("op", choices=["mkdir", "rm"])
    p.add_argument("paths", nargs="+")
    p.set_defaults(fn=_cmd_fs)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except EUnitError as e:
        print(f"eunit: error: {e}", file=sys.stderr)
        return 2
