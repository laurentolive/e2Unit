#!/usr/bin/env python3
"""e2Unit launcher usable without installation (used by the makefiles)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eunit.cli import main  # noqa: E402

sys.exit(main())
