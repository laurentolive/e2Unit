"""Tests of the license procedure (no network, no dialog: scripted UI, fake Lemon Squeezy)."""
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eunit.license import env, lemonsqueezy as ls, product, store  # noqa: E402
from eunit.license.info import LicenseInfo, LicenseType, utcnow  # noqa: E402
from eunit.license.manager import LicenseManager  # noqa: E402

PRO, PERSO, DEMO = LicenseType.PROFESSIONAL, LicenseType.PERSONAL, LicenseType.DEMONSTRATION
OUR_META = {"store_id": product.STORE_ID, "product_id": 1234, "customer_email": "a@b.c"}


class ScriptedUI:
    def __init__(self, choices=(), personal=True, managed_ok=(), keys=()):
        self.choices, self.personal = list(choices), personal
        self.managed_ok, self.keys = list(managed_ok), list(keys)
        self.messages, self.notices = [], 0

    def message(self, text, level="info"):
        self.messages.append(text)

    def choose_license(self):
        return self.choices.pop(0) if self.choices else DEMO

    def confirm_personal(self):
        return self.personal

    def managed_notice(self, text, ok_cancel):
        self.notices += 1
        return self.managed_ok.pop(0) if (ok_cancel and self.managed_ok) else True

    def activate_professional(self, activate_fn):
        for k in self.keys:
            lic, _ = activate_fn(k)
            if lic is not None:
                return lic
        return None

    def close(self):
        pass


def answer(activated=False, valid=False, status="active", meta=OUR_META, error=None, instance="i-1"):
    return {"activated": activated, "valid": valid, "error": error, "meta": meta,
            "license_key": {"key": "K", "status": status, "expires_at": None},
            "instance": {"id": instance} if instance else None}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = [mock.patch.object(store, "_dir", lambda: Path(self.tmp.name)),
             mock.patch.object(env, "is_managed_by_organization", lambda: False),
             mock.patch.object(product, "PRODUCT_ID", 1234),
             mock.patch.dict(os.environ, {"EUNIT_LICENSE_KEY": ""})]
        for x in p:
            x.start()
            self.addCleanup(x.stop)


class Procedure(Base):
    def test_first_run_demonstration_cannot_restart(self):
        mgr = LicenseManager(ScriptedUI([DEMO]))
        mgr.startup()
        self.assertEqual(mgr.license.type, DEMO)
        self.assertIn("Valid until", mgr.status_text())
        first = mgr.license.activated_utc
        # expired demonstration: choosing it again reloads the same one
        lic = store.load(DEMO)
        lic.expires_utc = utcnow() - timedelta(days=1)
        store.save(lic)
        ui = ScriptedUI([DEMO])
        mgr = LicenseManager(ui)
        mgr.startup()
        self.assertEqual(mgr.license.activated_utc, first)
        self.assertIn("Expired", mgr.status_text())
        self.assertTrue(any("expired" in m.lower() for m in ui.messages))

    def test_personal_needs_confirmation(self):
        mgr = LicenseManager(ScriptedUI([PERSO], personal=False))
        mgr.startup()
        self.assertEqual(mgr.license.type, DEMO)
        mgr = LicenseManager(ScriptedUI([PERSO], personal=True))
        mgr.license = None
        mgr.ensure()
        self.assertEqual(mgr.license.type, PERSO)
        self.assertEqual(LicenseManager(ScriptedUI()).license.type, PERSO)   # stored, best one loaded

    def test_managed_computer(self):
        with mock.patch.object(env, "is_managed_by_organization", lambda: True):
            # Cancel on the notice goes back to the choice
            ui = ScriptedUI([PERSO, DEMO], managed_ok=[False])
            mgr = LicenseManager(ui)
            mgr.startup()
            self.assertEqual(mgr.license.type, DEMO)
            # Personal kept on a managed computer: reminder at each run, not blocking
            store.save(LicenseInfo.new(PERSO))
            ui = ScriptedUI()
            LicenseManager(ui).startup()
            self.assertEqual(ui.notices, 1)

    def test_professional_activation(self):
        with mock.patch.object(ls, "activate", return_value=answer(activated=True)):
            mgr = LicenseManager(ScriptedUI([PRO], keys=["K"]))
            mgr.startup()
        self.assertEqual(mgr.license.type, PRO)
        self.assertEqual(mgr.license.instance_id, "i-1")
        self.assertIn("a@b.c", mgr.status_text())

    def test_key_of_another_product_is_released(self):
        other = dict(OUR_META, product_id=999)
        with mock.patch.object(ls, "activate", return_value=answer(activated=True, meta=other)), \
             mock.patch.object(ls, "deactivate") as deact:
            lic, error = LicenseManager.activate_key("K")
        self.assertIsNone(lic)
        self.assertIn("not an e2Unit license", error)
        deact.assert_called_once_with("K", "i-1")

    def test_not_on_sale(self):
        with mock.patch.object(product, "PRODUCT_ID", None), mock.patch.object(ls, "activate") as act:
            lic, error = LicenseManager.activate_key("K")
        self.assertIsNone(lic)
        self.assertIn("not on sale", error)
        act.assert_not_called()

    def _pro(self, **kw):
        lic = LicenseInfo.new(PRO)
        lic.license_key, lic.instance_id, lic.server_status = "K", "i-1", "active"
        lic.last_validated_utc = utcnow()
        for k, v in kw.items():
            setattr(lic, k, v)
        store.save(lic)
        return lic

    def test_revalidation_invalid(self):
        self._pro(last_validated_utc=utcnow() - timedelta(days=2))
        with mock.patch.object(ls, "validate", return_value=answer(valid=False, status="active")):
            mgr = LicenseManager(ScriptedUI([DEMO]))
            mgr.startup()
        self.assertEqual(store.load(PRO).server_status, "invalid")

    def test_revalidated_once_a_day_only(self):
        self._pro()
        with mock.patch.object(ls, "validate") as val:
            LicenseManager(ScriptedUI()).startup()
        val.assert_not_called()

    def test_offline_grace(self):
        self._pro(last_validated_utc=utcnow() - timedelta(days=31))
        with mock.patch.object(ls, "validate", side_effect=ls.LicenseServerUnreachable("offline")):
            ui = ScriptedUI()
            mgr = LicenseManager(ui)
            mgr.startup()
        self.assertIn("Online validation required", mgr.status_text())
        self.assertTrue(any("30 days" in m for m in ui.messages))

    def test_ci_key(self):
        with mock.patch.dict(os.environ, {"EUNIT_LICENSE_KEY": "K"}), \
             mock.patch.object(ls, "validate", return_value=answer(valid=True, instance=None)) as val:
            mgr = LicenseManager(ScriptedUI())
            mgr.startup()
        val.assert_called_once_with("K")
        self.assertEqual(mgr.license.type, PRO)
        self.assertIsNone(store.load(PRO))      # never stored

    def test_store_round_trip(self):
        lic = self._pro(customer_email="x@y.z")
        raw = store.path(PRO).read_bytes()
        if os.name == "nt":
            self.assertNotIn(b"x@y.z", raw)      # DPAPI encrypted
        back = store.load(PRO)
        self.assertEqual((back.license_key, back.customer_email), ("K", "x@y.z"))
        self.assertEqual(back.activated_utc, lic.activated_utc)


if __name__ == "__main__":
    unittest.main()
