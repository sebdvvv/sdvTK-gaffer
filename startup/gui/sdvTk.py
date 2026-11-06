"""GUI startup: import all sdvTk nodes + UI, then register Node menu items.

Gaffer execs this file with ``application`` in the namespace.
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PYTHON = os.path.join(_ROOT, "python")
if _PYTHON not in sys.path:
    sys.path.insert(0, _PYTHON)

import GafferUI  # noqa: E402

import sdvTkGafferUI  # noqa: E402, F401
from sdvTkGaffer import (  # noqa: E402
    ArnoldLight,
    ArnoldPhysicalSky,
    ShadingTk,
    sdvRenderSettings,
)


def _creator(cls):
    return lambda: cls()


node_menu = GafferUI.NodeMenu.acquire(application)
for _path, _cls, _search in (
    ("/Arnold/ArnoldLight", ArnoldLight, "ArnoldLight"),
    ("/Arnold/ArnoldPhysicalSky", ArnoldPhysicalSky, "ArnoldPhysicalSky"),
    ("/Arnold/ShadingTk", ShadingTk, "ShadingTk"),
    ("/Render/sdvRenderSettings", sdvRenderSettings, "sdvRenderSettings"),
):
    node_menu.append(path=_path, nodeCreator=_creator(_cls), searchText=_search)

from sdvTkGafferUI import arnoldViewer  # noqa: E402
from sdvTkGafferUI import hierarchyBrowse  # noqa: E402
from sdvTkGafferUI import menu as sdv_menu  # noqa: E402
from sdvTkGafferUI import scriptEditor  # noqa: E402
from sdvTkGafferUI import shaderBinding  # noqa: E402
from sdvTkGafferUI import uiTweaks  # noqa: E402
from sdvTkGafferUI import viewerSync  # noqa: E402

arnoldViewer.install(application)
viewerSync.install(application)
hierarchyBrowse.install(application)
shaderBinding.install(application)
uiTweaks.install(application)
scriptEditor.install(application)
sdv_menu.install(application)
