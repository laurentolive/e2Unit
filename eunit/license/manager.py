"""License procedure, same as eScope.

The license is not meant to resist tampering (whoever wants to cheat takes the free Personal
license), but the Professional one must be paid: its key is checked against the product and
validated online again; an expired / unvalidated license brings the reminder back at each run.
Demonstration / Personal licenses are local; a Professional license is a Lemon Squeezy key
activated on this machine, validated online (at most once a day here: a command line tool runs
often) and trusted offline for OFFLINE_GRACE_DAYS.

In continuous integration, the key can be given by the EUNIT_LICENSE_KEY environment variable:
it is validated without being activated (agents come and go), and never stored.
"""
import os
import platform
from datetime import timedelta

from . import env, lemonsqueezy as ls, product, store
from .info import OFFLINE_GRACE_DAYS, LicenseInfo, LicenseType, utcnow

REVALIDATE_EVERY = timedelta(hours=24)
KEY_ENV = "EUNIT_LICENSE_KEY"

MANAGED_NOTICE = ("This computer appears to be managed by an organization.\n\n"
                  "Personal licenses are intended for non-commercial use.\n"
                  "If you are using this software for work or professional purposes,\n"
                  "a Professional license is required.")


class LicenseManager:
    def __init__(self, ui):
        self.ui = ui
        self.license = store.load()
        self._managed_notice_shown = False

    # ------------------------------------------------------------------
    def startup(self):
        """At the start of a run: CI key, revalidation, license choice, reminders."""
        if os.environ.get(KEY_ENV):
            if self._use_ci_key(os.environ[KEY_ENV].strip()):
                return
        lic = self.license
        if (lic is not None and lic.type == LicenseType.PROFESSIONAL
                and (lic.last_validated_utc is None or utcnow() - lic.last_validated_utc > REVALIDATE_EVERY)):
            # validate first: a renewed subscription must not show the expired reminder
            self.revalidate(silent=True)
        self.ensure()
        self.remind_managed_personal()

    def status_text(self):
        return self.license.status_text() if self.license else "Unlicensed"

    # ------------------------------------------------------------------
    def ensure(self):
        lic = self.license
        # still active on the server, just not validated for too long: a new activation would not help
        if lic is not None and lic.is_offline_too_long and lic.server_status == "active":
            self.ui.message(
                f"The Professional license has not been validated online for more than {OFFLINE_GRACE_DAYS} days.\n"
                f"Please connect this computer to the Internet and run: eunit license check", "warning")
            return
        if lic is not None and not lic.is_expired:
            return

        if lic is not None:
            msg = (f"Your Professional license is no longer valid ({lic.server_status}).\n"
                   "Renew your subscription or enter another license key."
                   if lic.type == LicenseType.PROFESSIONAL else "License expired. Please acquire a license.")
            self.ui.message(msg, "warning")

        selected = self.ui.choose_license()
        # managed computer: OK goes on with the Personal license, Cancel goes back to the license choice
        managed = env.is_managed_by_organization()
        while managed and selected == LicenseType.PERSONAL:
            if self._managed_notice(ok_cancel=True):
                break
            selected = self.ui.choose_license()

        if selected == LicenseType.PERSONAL and self.ui.confirm_personal():
            self.license = LicenseInfo.new(LicenseType.PERSONAL)
        if selected == LicenseType.PROFESSIONAL:
            pro = self.ui.activate_professional(self.activate_key)
            if pro is not None:
                self.license = pro
            elif self.license is not None and self.license.type == LicenseType.PROFESSIONAL:
                self.license = None   # activation cancelled: fall back to the demonstration below

        if selected == LicenseType.DEMONSTRATION or self.license is None:
            # an existing demonstration is reloaded: it cannot be restarted
            self.license = store.load(LicenseType.DEMONSTRATION) or LicenseInfo.new(LicenseType.DEMONSTRATION)
        store.save(self.license)

    def _managed_notice(self, ok_cancel):
        self._managed_notice_shown = True
        return self.ui.managed_notice(MANAGED_NOTICE, ok_cancel)

    def remind_managed_personal(self):
        """A Personal license on a managed computer: reminder at each run, without blocking;
        not twice when the license was just chosen."""
        if self.license is None or self.license.type != LicenseType.PERSONAL or self._managed_notice_shown:
            return
        if env.is_managed_by_organization():
            self._managed_notice(ok_cancel=False)

    # ------------------------------------------------------------------
    @staticmethod
    def activate_key(key):
        """Activate a key on this machine: (LicenseInfo, None) or (None, error message)."""
        key = key.strip()
        if not key:
            return None, "Please enter a license key."
        if product.PRODUCT_ID is None:
            return None, f"{product.PRODUCT_NAME} Professional licenses are not on sale yet."
        try:
            r = ls.activate(key, platform.node())
            if not r.get("activated"):
                return None, r.get("error") or "This license key could not be activated."
            if not ls.is_our_product(r):
                # the key is now activated on Lemon Squeezy: release it
                inst = r.get("instance") or {}
                if inst.get("id"):
                    try:
                        ls.deactivate(key, inst["id"])
                    except ls.LicenseServerUnreachable:
                        pass
                return None, f"This license key is not an {product.PRODUCT_NAME} license."
            return LicenseInfo.from_server(r), None
        except ls.LicenseServerUnreachable as e:
            return None, f"{e}\nAn Internet connection is needed to activate the license."

    def activate(self, key=None):
        """Activate a new Professional key (license command); the previous activation is released."""
        if key is None:
            pro = self.ui.activate_professional(self.activate_key)
        else:
            pro, error = self.activate_key(key)
            if error:
                self.ui.message(error, "error")
        if pro is None:
            return False
        old = self.license
        if (old is not None and old.type == LicenseType.PROFESSIONAL and old.license_key
                and old.instance_id and old.instance_id != pro.instance_id):
            try:
                ls.deactivate(old.license_key, old.instance_id)
            except ls.LicenseServerUnreachable:
                pass
        self.license = pro
        store.save(pro)
        return True

    def revalidate(self, silent):
        """Validate the Professional key and refresh its status; None if the server is unreachable."""
        lic = self.license
        if lic is None or lic.type != LicenseType.PROFESSIONAL or not lic.license_key or not lic.instance_id:
            return False
        try:
            r = ls.validate(lic.license_key, lic.instance_id)
        except ls.LicenseServerUnreachable as e:
            if not silent:
                self.ui.message(str(e), "warning")
            return None
        lic.update(r)
        if not r.get("valid") or not ls.is_our_product(r):
            # instance deactivated from the customer portal, key deleted, refunded...
            if lic.server_status not in ("expired", "disabled"):
                lic.server_status = "invalid"
        store.save(lic)
        return not lic.is_expired

    def deactivate(self):
        """Free the activation so the key can be used on another computer."""
        lic = self.license
        if lic is None or lic.type != LicenseType.PROFESSIONAL or not lic.license_key or not lic.instance_id:
            self.ui.message("No Professional license is activated on this computer.", "info")
            return False
        try:
            r = ls.deactivate(lic.license_key, lic.instance_id)
            # an instance already removed on the server is gone as well
            if not r.get("deactivated") and r.get("license_key") is not None:
                self.ui.message(r.get("error") or "The license could not be deactivated.", "error")
                return False
        except ls.LicenseServerUnreachable as e:
            self.ui.message(f"{e}\n\nAn Internet connection is needed to deactivate the license.", "error")
            return False
        store.delete(LicenseType.PROFESSIONAL)
        self.license = store.load()
        self.ensure()
        return True

    # ------------------------------------------------------------------
    def _use_ci_key(self, key):
        lic = LicenseInfo.new(LicenseType.PROFESSIONAL)
        lic.license_key = key
        lic.expires_utc = None
        if product.PRODUCT_ID is None:
            self.ui.message(f"{KEY_ENV}: {product.PRODUCT_NAME} Professional licenses are not on sale yet.", "warning")
            return False
        try:
            r = ls.validate(key)
        except ls.LicenseServerUnreachable:
            lic.server_status = "active"     # offline agent: trusted for this run
            lic.last_validated_utc = utcnow()
            self.license = lic
            return True
        if not r.get("valid") or not ls.is_our_product(r):
            self.ui.message(f"{KEY_ENV}: {r.get('error') or 'invalid license key'}", "warning")
            return False
        lic.update(r)
        self.license = lic
        return True
