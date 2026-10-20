"""License data, same model as eScope.

Demonstration (1 month, work use allowed), Personal (free, non-commercial) and
Professional (Lemon Squeezy key activated on this machine, validated online,
trusted offline for OFFLINE_GRACE_DAYS).
"""
import calendar
import getpass
import hashlib
import os
import platform
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

# without validation for this long, a Professional license counts as expired: the reminder is back at
# each run, so a cancelled subscription cannot be kept by staying offline
OFFLINE_GRACE_DAYS = 30


class LicenseType(str, Enum):
    DEMONSTRATION = "Demonstration"
    PERSONAL = "Personal"
    PROFESSIONAL = "Professional"


def utcnow():
    return datetime.now(timezone.utc)


def _add_months(d, months):
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))


def _windows_machine_guid():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
            return str(winreg.QueryValueEx(k, "MachineGuid")[0]) or "UNKNOWN"
    except OSError:
        return "UNKNOWN"


def machine_id():
    guid = _windows_machine_guid() if os.name == "nt" else "UNKNOWN"
    raw = f"{platform.node()}|{guid}"
    return hashlib.sha256(raw.encode()).hexdigest().upper()


@dataclass
class LicenseInfo:
    type: LicenseType
    activated_utc: datetime = field(default_factory=utcnow)
    expires_utc: datetime = None
    user_domain: str = ""
    user_name: str = ""
    machine_id: str = ""
    # Professional: Lemon Squeezy key activated on this machine
    license_key: str = None
    instance_id: str = None
    server_status: str = None       # Lemon Squeezy key status (active, expired, disabled) or invalid
    customer_email: str = None
    last_validated_utc: datetime = None

    @classmethod
    def new(cls, type_):
        lic = cls(LicenseType(type_))
        lic.user_domain = os.environ.get("USERDOMAIN", "")
        try:
            lic.user_name = getpass.getuser()
        except Exception:
            lic.user_name = ""
        lic.machine_id = machine_id()
        if lic.type == LicenseType.PROFESSIONAL:
            lic.expires_utc = lic.activated_utc + timedelta(days=365)
        elif lic.type == LicenseType.DEMONSTRATION:
            lic.expires_utc = _add_months(lic.activated_utc, 1)
        return lic

    @classmethod
    def from_server(cls, response):
        lic = cls.new(LicenseType.PROFESSIONAL)
        lic.update(response)
        return lic

    def update(self, r):
        """Refresh from an activate / validate answer."""
        key = r.get("license_key") or None
        if key:
            self.license_key = key.get("key") or self.license_key
            self.server_status = key.get("status")
            # null for a key tied to a subscription: the status follows the subscription instead
            exp = key.get("expires_at")
            self.expires_utc = _parse_date(exp) if exp else None
        inst = r.get("instance") or None
        if inst:
            self.instance_id = inst.get("id")
        meta = r.get("meta") or {}
        if meta.get("customer_email"):
            self.customer_email = meta["customer_email"]
        self.last_validated_utc = utcnow()

    # ------------------------------------------------------------------
    @property
    def is_offline_too_long(self):
        return self.type == LicenseType.PROFESSIONAL and (
            self.last_validated_utc is None
            or utcnow() > self.last_validated_utc + timedelta(days=OFFLINE_GRACE_DAYS))

    @property
    def is_expired(self):
        return ((self.expires_utc is not None and utcnow() > self.expires_utc)
                or (self.type == LicenseType.PROFESSIONAL
                    and self.server_status in ("expired", "disabled", "invalid"))
                or self.is_offline_too_long)

    def status_text(self):
        if self.type == LicenseType.DEMONSTRATION:
            return ("Demonstration License - Expired" if self.is_expired
                    else f"Demonstration License - Valid until {self.expires_utc:%Y-%m-%d}")
        if self.type == LicenseType.PERSONAL:
            return "Personal License - Non-commercial use only"
        if self.is_expired:
            if self.server_status == "disabled":
                return "Professional License - Disabled"
            if self.server_status == "invalid":
                return "Professional License - Invalid"
            if self.server_status == "active" and self.is_offline_too_long:
                return "Professional License - Online validation required"
            return "Professional License - Expired"
        suffix = f" ({self.customer_email})" if self.customer_email else ""
        if self.expires_utc is not None:
            return f"Professional License - Valid until {self.expires_utc:%Y-%m-%d}{suffix}"
        return f"Professional License{suffix}"

    # ------------------------------------------------------------------
    def to_dict(self):
        d = asdict(self)
        d["type"] = self.type.value
        for k, v in d.items():
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d["type"] = LicenseType(d["type"])
        for k in ("activated_utc", "expires_utc", "last_validated_utc"):
            if d.get(k):
                d[k] = _parse_date(d[k])
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


def _parse_date(text):
    d = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
