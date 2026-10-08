"""Root conftest: make the ``src`` package importable regardless of the
directory pytest is invoked from or of pytest's per-test-file import mode.

The project has no editable install; ``pyproject.toml`` declares ``src`` as
the package root but nothing installs it into the environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
