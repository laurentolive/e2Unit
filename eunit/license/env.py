"""Signals of a professional environment, as eScope: a computer joined to an Active
Directory domain or to Azure AD / Entra ID is likely a work computer."""
import ctypes
import os


def is_domain_joined():
    if os.name != "nt":
        return False
    try:
        from ctypes import wintypes
        netapi = ctypes.WinDLL("netapi32")
        name = wintypes.LPWSTR()
        status = ctypes.c_int()
        if netapi.NetGetJoinInformation(None, ctypes.byref(name), ctypes.byref(status)) != 0:
            return False
        netapi.NetApiBufferFree(name)
        return status.value == 3       # NetSetupDomainName
    except (OSError, AttributeError):
        return False


def is_azure_ad_joined():
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\CloudDomainJoin\JoinInfo") as k:
            return winreg.QueryInfoKey(k)[0] > 0
    except OSError:
        return False


def is_managed_by_organization():
    return is_domain_joined() or is_azure_ad_joined()


_CI_VARS = ("CI", "JENKINS_URL", "GITHUB_ACTIONS", "GITLAB_CI", "TF_BUILD", "TEAMCITY_VERSION",
            "BUILDKITE", "BAMBOO_BUILDKEY", "CIRCLECI", "DRONE")


def is_ci():
    """Run by a continuous integration server: no dialog may block it."""
    return any(os.environ.get(v) for v in _CI_VARS)
