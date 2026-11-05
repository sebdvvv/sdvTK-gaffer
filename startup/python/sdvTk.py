"""``gaffer python`` startup: import nodes so scripts can deserialise."""

from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PYTHON = os.path.join(_ROOT, "python")
if _PYTHON not in sys.path:
    sys.path.insert(0, _PYTHON)

import sdvTkGaffer  # noqa: E402, F401
