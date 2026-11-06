"""User preferences for sdvTk (``~/gaffer/sdvtk_prefs.json``)."""

from __future__ import annotations

import json
import os

DOUBLE_CLICK_ENTER = "double_click_enter_contents"
SHOW_CONTENTS_SINGLE_PANE = "show_contents_single_pane"
CTRL_DOUBLE_CLICK_NODE_EDITOR = "ctrl_double_click_node_editor"
GRAPH_VIEW_NAV_MENU = "graph_view_nav_menu"
HIERARCHY_BROWSE_ONLY = "hierarchy_browse_only"
USE_MULTI_SCRIPT_EDITOR = "use_multi_script_editor"
MULTI_SCRIPT_EDITOR_FOLDER = "multi_script_editor_folder"

_DEFAULTS = {
    DOUBLE_CLICK_ENTER: False,
    SHOW_CONTENTS_SINGLE_PANE: False,
    CTRL_DOUBLE_CLICK_NODE_EDITOR: False,
    GRAPH_VIEW_NAV_MENU: False,
    HIERARCHY_BROWSE_ONLY: False,
    USE_MULTI_SCRIPT_EDITOR: False,
    MULTI_SCRIPT_EDITOR_FOLDER: "",
}

_CACHE: dict | None = None

MSE_GITHUB = "https://github.com/sebdvvv/pw_MultiScriptEditor"


def _home() -> str:
    hp = os.environ.get("HOMEPATH") or os.environ.get("HOME") or os.path.expanduser("~")
    hp = os.path.expandvars(hp)
    if os.name == "nt":
        if hp.startswith("\\") or hp.startswith("/"):
            drive = os.environ.get("HOMEDRIVE") or os.environ.get("SystemDrive") or "C:"
            hp = drive + hp
        elif len(hp) >= 2 and hp[1] != ":":
            up = os.environ.get("USERPROFILE")
            if up:
                hp = up
    return os.path.normpath(hp)


def gaffer_user_dir() -> str:
    return os.path.join(_home(), "gaffer")


def prefs_path() -> str:
    return os.path.join(gaffer_user_dir(), "sdvtk_prefs.json")


def load(force: bool = False) -> dict:
    global _CACHE
    if _CACHE is not None and not force:
        return dict(_CACHE)
    data = dict(_DEFAULTS)
    path = prefs_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                for key in _DEFAULTS:
                    if key in loaded:
                        data[key] = _coerce(key, loaded[key])
        except Exception as exc:
            print("[sdvTk] Failed to read {}: {}".format(path, exc))
    _CACHE = dict(data)
    return dict(data)


def save(data: dict | None = None) -> bool:
    global _CACHE
    merged = dict(_DEFAULTS)
    merged.update(_CACHE or {})
    if data:
        for key, value in data.items():
            if key in _DEFAULTS:
                merged[key] = _coerce(key, value)
    path = prefs_path()
    try:
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(merged, handle, indent=2, sort_keys=True)
            handle.write("\n")
        _CACHE = dict(merged)
    except Exception as exc:
        print("[sdvTk] Failed to write {}: {}".format(path, exc))
        return False
    return True


def get(key: str, default=None):
    prefs = load()
    if key in prefs:
        return prefs[key]
    if default is not None:
        return default
    return _DEFAULTS.get(key)


def double_click_enter_contents() -> bool:
    return bool(get(DOUBLE_CLICK_ENTER, False))


def show_contents_single_pane() -> bool:
    return bool(get(SHOW_CONTENTS_SINGLE_PANE, False))


def ctrl_double_click_node_editor() -> bool:
    return bool(get(CTRL_DOUBLE_CLICK_NODE_EDITOR, False))


def graph_view_nav_menu() -> bool:
    return bool(get(GRAPH_VIEW_NAV_MENU, False))


def hierarchy_browse_only() -> bool:
    return bool(get(HIERARCHY_BROWSE_ONLY, False))


def use_multi_script_editor() -> bool:
    return bool(get(USE_MULTI_SCRIPT_EDITOR, False))


def multi_script_editor_folder() -> str:
    return str(get(MULTI_SCRIPT_EDITOR_FOLDER, "") or "")


def _coerce(key: str, value):
    default = _DEFAULTS[key]
    if isinstance(default, bool):
        return bool(value)
    if value is None:
        return ""
    return str(value)


def locate_multi_script_editor(folder: str | None = None) -> str | None:
    """Directory to put on ``PYTHONPATH`` so ``import multi_script_editor`` works.

    Accepts the folder that contains the package, the package folder itself,
    or a parent that contains ``pw_MultiScriptEditor/multi_script_editor``.
    """
    raw = multi_script_editor_folder() if folder is None else folder
    raw = (raw or "").strip()
    if not raw:
        return None
    chosen = os.path.normpath(os.path.expanduser(os.path.expandvars(raw)))
    if not os.path.isdir(chosen):
        return None
    package_init = os.path.join("multi_script_editor", "__init__.py")
    if os.path.isfile(os.path.join(chosen, package_init)):
        return chosen
    if os.path.basename(chosen) == "multi_script_editor" and os.path.isfile(
        os.path.join(chosen, "__init__.py")
    ):
        return os.path.dirname(chosen)
    nested = os.path.join(chosen, "pw_MultiScriptEditor")
    if os.path.isfile(os.path.join(nested, package_init)):
        return nested
    return None
