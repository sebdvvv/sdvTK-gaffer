"""Expose legacy import names so existing .gfr scripts still load.

Saved scripts import ``ArnoldLight``, ``ShadingTk``, … Gaffer type names
stay those strings; the code lives under ``sdvTkGaffer`` / ``sdvTkGafferUI``.
"""

from __future__ import annotations

import sys


def alias_package(old: str, new: str) -> None:
    prefix = new + "."
    for name, module in list(sys.modules.items()):
        if name != new and not name.startswith(prefix):
            continue
        sys.modules.setdefault(old + name[len(new) :], module)
