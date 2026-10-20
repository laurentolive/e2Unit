"""Lemon Squeezy License API (https://docs.lemonsqueezy.com/api/license-api), no API key needed:
purchase, VAT, renewal and key generation are done by Lemon Squeezy, e2Unit only activates the
key on this machine and validates it again."""
import json
import urllib.error
import urllib.parse
import urllib.request

from . import product

API_URL = "https://api.lemonsqueezy.com/v1/licenses/"
TIMEOUT_S = 10


class LicenseServerUnreachable(Exception):
    """No network, timeout, 5xx: keep the cached license."""


def _post(action, form):
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(API_URL + action, data=data, headers={
        "Accept": "application/json",
        "User-Agent": f"{product.PRODUCT_NAME}/{product.PRODUCT_VERSION}",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        if e.code >= 500:
            raise LicenseServerUnreachable(f"License server error {e.code}") from e
        body = e.read()     # 4xx (unknown key, activation limit reached...) carry the JSON with "error"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LicenseServerUnreachable(f"License server unreachable: {e}") from e
    try:
        r = json.loads(body)
    except ValueError as e:
        raise LicenseServerUnreachable("Unexpected answer from the license server") from e
    if not isinstance(r, dict):
        raise LicenseServerUnreachable("Unexpected answer from the license server")
    return r


def activate(key, instance_name):
    return _post("activate", {"license_key": key, "instance_name": instance_name})


def validate(key, instance_id=None):
    form = {"license_key": key}
    if instance_id:
        form["instance_id"] = instance_id
    return _post("validate", form)


def deactivate(key, instance_id):
    return _post("deactivate", {"license_key": key, "instance_id": instance_id})


def is_our_product(r):
    """The License API is shared by every Lemon Squeezy store: without this check a key of any
    other product would activate the Professional license."""
    meta = r.get("meta") or {}
    return (product.PRODUCT_ID is not None and meta.get("store_id") == product.STORE_ID
            and meta.get("product_id") == product.PRODUCT_ID)
