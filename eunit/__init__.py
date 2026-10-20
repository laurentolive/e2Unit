"""e2Unit - unit tests of C functions, on host (shared library) and on target (J-Link)."""

__version__ = "0.1.0"


class EUnitError(Exception):
    """Error in a specification, a build product or a runner (not a test failure)."""
