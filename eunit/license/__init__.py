"""Licensing of the e2Unit tool (same procedure as eScope): Demonstration, Personal or
Professional (Lemon Squeezy). See manager.py."""
from .info import LicenseInfo, LicenseType  # noqa: F401
from .manager import LicenseManager  # noqa: F401
from .product import PRODUCT_NAME  # noqa: F401


def check_at_startup():
    """Run the license procedure (dialogs if needed) and return the status text."""
    from .ui import make_ui
    ui = make_ui()
    try:
        mgr = LicenseManager(ui)
        mgr.startup()
        return mgr.status_text()
    finally:
        ui.close()
