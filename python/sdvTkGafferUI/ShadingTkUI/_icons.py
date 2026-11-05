"""Graph Editor icons for ShadingTk.

Drop a PNG in this extension's ``graphics/`` or ``icons/`` folder.
Looked up in order, first hit wins: ``shadingTkNode.png``.
"""

from __future__ import annotations

import os

import Gaffer

_REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
_ICON_DIRS = (
    os.path.join(_REPO_ROOT, "graphics"),
    os.path.join(_REPO_ROOT, "icons"),
)


def _ensure_image_paths() -> None:
    current = os.environ.get("GAFFERUI_IMAGE_PATHS", "")
    parts = [p for p in current.split(os.pathsep) if p]
    changed = False
    for path in reversed(_ICON_DIRS):
        if os.path.isdir(path) and path not in parts:
            parts.insert(0, path)
            changed = True
    if changed:
        os.environ["GAFFERUI_IMAGE_PATHS"] = os.pathsep.join(parts)


def register_node_icon(node_type, *filenames: str) -> str | None:
    _ensure_image_paths()
    for directory in _ICON_DIRS:
        for name in filenames:
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                Gaffer.Metadata.registerValue(node_type, "icon", name)
                return name
    return None
