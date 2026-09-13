"""
tests/__init__.py
-----------------
Ensures the project root (api-monitor/) is on sys.path so that all test
scripts in this folder can resolve ``from app.*`` imports regardless of
which directory they are launched from.

Any test file in this folder that does:

    import tests  # or is run via: python tests/some_test.py

will automatically benefit from this path fix via the __init__ import.

For scripts run directly (e.g. ``python tests/vectorstore_test.py``),
each script also inserts the root manually at the top as a belt-and-
suspenders guard -- see the individual files.
"""

from __future__ import annotations

import os
import sys

# Insert the project root (parent of this tests/ directory) at the front of
# sys.path so that ``from app.*`` imports resolve correctly from any CWD.
_PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
