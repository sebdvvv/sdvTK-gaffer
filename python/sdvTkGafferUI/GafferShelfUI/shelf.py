"""
sdvTk shelf.

Installed via ``startup/gui/sdvTk.py``.

The shipped shelf is one tab, ``sdvTk``. Its buttons are Context, Forced
Geometry, and the node connection tools. About sits at the far right.

The shelf Gaffer uses lives in the user folder. On first launch the
shipped ``sdvTk`` shelf is copied there when that file is missing:

    %HOMEDRIVE%%HOMEPATH%/gaffer/shelves/<TabName>.json
    %HOMEDRIVE%%HOMEPATH%/gaffer/shelves/icons/
    %HOMEDRIVE%%HOMEPATH%/gaffer/shelves/actions/

The copy under ``GafferShelfUI/shelves`` and ``icons/shelf`` is only the
template for that first copy.

Local shelves can also be created from the tab selector menu
("Create My Shelf (Local)") via a small Maya-like tool editor that
reads/writes the user JSON files. Multiple local shelves are supported.

JSON is used (PyYAML is not shipped with Gaffer). Tabs switch via a
compact left selector, not space-hungry QTabBar tabs.

Action types
------------
Plain button::

    {"id": "hello", "label": "Hello", "command": "print('hi')"}

Menu button (looks like any other shelf button; click opens a context menu)::

    {
      "id": "create_light",
      "label": "Lights",
      "menu": [
        {"id": "section", "label": "Lights", "title": true},
        {"id": "distant", "label": "Distant", "command": "..."},
        {"separator": true},
        {"id": "dome", "label": "Dome", "script": "dome.py"}
      ]
    }

Hold-flyout button (click opens a column of icon actions)::

    {
      "id": "connect_node",
      "label": "Connect",
      "icon": "node_conn.png",
      "hold": [
        {"id": "connect", "icon": "node_conn.png", "command": "..."},
        {"id": "disconnect", "icon": "node_disconn.png", "command": "..."},
        {"id": "insert", "icon": "node_insert.png", "command": "..."},
        {"id": "merge", "icon": "merge.png", "command": "..."}
      ]
    }

Menu items accept the same ``command`` / ``script`` / ``data`` fields as
top-level actions, plus optional ``checkable``, ``checked``, ``group``.
"""

from __future__ import print_function

import colorsys
import copy
import gc
import glob
import importlib
import json
import os
import random
import re
import shutil
import sys
import traceback

import Gaffer
import GafferScene
import GafferUI

from Qt import QtCore
from Qt.QtCore import QPoint, QSize, QTimer
from Qt.QtGui import QIcon, QPixmap
from Qt.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTextEdit,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    from Qt.QtWidgets import QActionGroup  # Qt5 / PySide2
except ImportError:
    from Qt.QtGui import QActionGroup  # Qt6 / PySide6


# ------------------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------------------

_UI_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_DIR = os.path.normpath(os.path.join(_UI_DIR, "..", "..", ".."))


def shared_shelves_dir():
    """Shipped shelf JSON — ``GafferShelfUI/shelves``."""
    return os.path.join(_UI_DIR, "shelves")


def shared_icons_dir():
    """Shipped shelf icons — ``icons/shelf``."""
    return os.path.join(_REPO_DIR, "icons", "shelf")


# Used when no shelf JSON is found.
DEFAULT_TAB_ORDER = ["sdvTk"]


def _homepath_root():
    """Resolve HOMEPATH as requested; join HOMEDRIVE on Windows when needed."""
    hp = os.environ.get("HOMEPATH") or os.environ.get("HOME") or os.path.expanduser("~")
    hp = os.path.expandvars(hp)
    if os.name == "nt":
        # HOMEPATH is often "\Users\name" without a drive letter
        if hp.startswith("\\") or hp.startswith("/"):
            drive = os.environ.get("HOMEDRIVE") or os.environ.get("SystemDrive") or "C:"
            hp = drive + hp
        elif len(hp) >= 2 and hp[1] != ":":
            # relative path — still prefer USERPROFILE if present
            up = os.environ.get("USERPROFILE")
            if up:
                hp = up
    return os.path.normpath(hp)


def user_shelves_dir():
    return os.path.join(_homepath_root(), "gaffer", "shelves")


def ensure_user_shelves_dir():
    path = user_shelves_dir()
    try:
        os.makedirs(os.path.join(path, "icons"), exist_ok=True)
        os.makedirs(os.path.join(path, "actions"), exist_ok=True)
    except OSError as e:
        print("[Shelf] Could not create user shelves dir %s: %s" % (path, e))
    return path


def ensure_local_shelf():
    """Copy the shipped shelf into ``~/gaffer/shelves`` when it is not there yet."""
    ensure_user_shelves_dir()
    dest = user_shelf_json_path("sdvTk")
    src = os.path.join(shared_shelves_dir(), "sdvTk.json")
    if not os.path.isfile(dest) and os.path.isfile(src):
        shutil.copy2(src, dest)
        print("[Shelf] Copied default shelf to %s" % dest)

    src_icons = shared_icons_dir()
    dst_icons = user_icons_dir()
    if not os.path.isdir(src_icons):
        return dest
    for name in os.listdir(src_icons):
        src_path = os.path.join(src_icons, name)
        dst_path = os.path.join(dst_icons, name)
        if os.path.isfile(src_path) and not os.path.isfile(dst_path):
            shutil.copy2(src_path, dst_path)
    return dest


def user_shelf_json_path(shelf_name):
    return os.path.join(user_shelves_dir(), "%s.json" % shelf_name)


def user_icons_dir():
    return os.path.join(ensure_user_shelves_dir(), "icons")


DEFAULT_ACCENT = "#ffaa00"


def user_shelf_prefs_path():
    """Local prefs (accent color, …) under the user shelves folder."""
    return os.path.join(ensure_user_shelves_dir(), "_prefs.json")


def load_shelf_prefs():
    path = user_shelf_prefs_path()
    defaults = {"accent": DEFAULT_ACCENT}
    if not os.path.isfile(path):
        return dict(defaults)
    try:
        data = _load_json(path)
        if not isinstance(data, dict):
            return dict(defaults)
        out = dict(defaults)
        out.update(data)
        return out
    except Exception:
        return dict(defaults)


def save_shelf_prefs(prefs):
    ensure_user_shelves_dir()
    path = user_shelf_prefs_path()
    payload = dict(prefs or {})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def list_user_shelf_names():
    """Shelf names that have a local JSON file under the user shelves dir."""
    names = []
    for path in _discover_shelf_files(ensure_user_shelves_dir()):
        try:
            data = _load_json(path)
            name = data.get("name") or data.get("label") or os.path.splitext(os.path.basename(path))[0]
            names.append(name)
        except Exception:
            names.append(os.path.splitext(os.path.basename(path))[0])
    return sorted(set(names))


def _validate_shelf_name(name):
    """Return None if valid, else an error message. No spaces allowed."""
    if not name:
        return "Shelf name is required."
    if " " in name:
        return "Shelf name cannot contain spaces."
    if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", name):
        return "Use letters, numbers, and underscores only (must start with a letter)."
    return None


def _action_id_from_label(label, existing_ids=None):
    existing_ids = set(existing_ids or [])
    base = re.sub(r"[^A-Za-z0-9_]+", "_", (label or "tool").strip()).strip("_").lower()
    if not base:
        base = "tool"
    if not re.match(r"^[A-Za-z]", base):
        base = "tool_" + base
    candidate = base
    n = 2
    while candidate in existing_ids:
        candidate = "%s_%d" % (base, n)
        n += 1
    return candidate


def load_user_shelf_data(shelf_name):
    path = user_shelf_json_path(shelf_name)
    if not os.path.isfile(path):
        return {
            "name": shelf_name,
            "label": shelf_name,
            "order": 200,
            "actions": [],
        }
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ValueError("Shelf JSON root must be an object")
    data.setdefault("name", shelf_name)
    data.setdefault("label", data.get("name", shelf_name))
    data.setdefault("order", 200)
    data.setdefault("actions", [])
    return data


def save_user_shelf_data(shelf_name, data):
    ensure_user_shelves_dir()
    path = user_shelf_json_path(shelf_name)
    payload = {
        "name": shelf_name,
        "label": data.get("label") or shelf_name,
        "order": int(data.get("order", 200)),
        "actions": data.get("actions") or [],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("[Shelf] Saved local shelf: %s" % path)
    return path


def delete_user_shelf(shelf_name):
    """Remove the local shelf JSON. Icons are left in place (may be shared)."""
    path = user_shelf_json_path(shelf_name)
    if not os.path.isfile(path):
        return False
    os.remove(path)
    print("[Shelf] Deleted local shelf: %s" % path)
    return True


def _import_icon_to_user(source_path, preferred_name=None):
    """Copy an icon into the user shelves/icons folder; return stored filename."""
    if not source_path or not os.path.isfile(source_path):
        return ""
    icons_dir = user_icons_dir()
    base = preferred_name or os.path.basename(source_path)
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    dest = os.path.join(icons_dir, base)
    src_abs = os.path.abspath(source_path)
    if os.path.abspath(dest) != src_abs:
        # Avoid clobbering unrelated files with same name from another path
        if os.path.isfile(dest):
            root, ext = os.path.splitext(base)
            n = 2
            while os.path.isfile(dest):
                dest = os.path.join(icons_dir, "%s_%d%s" % (root, n, ext))
                n += 1
        shutil.copy2(src_abs, dest)
    return os.path.basename(dest)


def _dialog_exec(dialog):
    """PySide2 uses exec_(); PySide6 uses exec()."""
    fn = getattr(dialog, "exec", None)
    if callable(fn):
        return fn()
    return dialog.exec_()


def _menu_exec_at(menu, global_pos):
    """Show a QMenu like a context menu (PySide2 exec_ / PySide6 exec)."""
    fn = getattr(menu, "exec", None)
    if callable(fn):
        return fn(global_pos)
    return menu.exec_(global_pos)

def _pick_existing_file(parent, title, start_dir, name_filter):
    """
    Open a file picker that works when nested under another modal dialog.

    Native Windows file dialogs often fail silently as children of an already
    modal QDialog, so we force Qt's non-native dialog.
    """
    start_dir = start_dir if start_dir and os.path.isdir(start_dir) else os.path.expanduser("~")
    dialog = QFileDialog(parent, title, start_dir, name_filter)
    dialog.setFileMode(QFileDialog.ExistingFile)
    dialog.setAcceptMode(QFileDialog.AcceptOpen)
    # Critical: nested native dialogs frequently do nothing on Windows
    try:
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
    except Exception:
        try:
            dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        except Exception:
            pass

    if _dialog_exec(dialog) != QDialog.Accepted:
        return ""
    files = dialog.selectedFiles()
    return files[0] if files else ""


# ------------------------------------------------------------------------------
# Style / accent (right-click tab button to randomize; stored in _prefs.json)
# ------------------------------------------------------------------------------

SHELF_BUTTON_SIZE = 42  # square action buttons (fills shelf bar a bit more)
SHELF_ICON_SIZE = SHELF_BUTTON_SIZE - 2

# Pinned to the far right of the shelf. The shipped shelf has this one icon there.
SHARED_RIGHT_SHELF_ACTIONS = (
    {
        "id": "about_sdvtk",
        "label": "About",
        "tooltip": "About sdvTk",
        "icon": "about_sdvTk.png",
        "builtin": "about_pipeline",
        "align": "right",
    },
)
SHARED_RIGHT_SHELF_IDS = frozenset(a["id"] for a in SHARED_RIGHT_SHELF_ACTIONS)

_accent_color = None  # cached; loaded lazily from local prefs


def _parse_hex_color(value):
    text = (value or "").strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _hex_color(rgb):
    r, g, b = [max(0, min(255, int(c))) for c in rgb]
    return "#%02x%02x%02x" % (r, g, b)


def _lighten_hex(color, amount=0.18):
    rgb = _parse_hex_color(color)
    if not rgb:
        return color
    return _hex_color(tuple(c + (255 - c) * amount for c in rgb))


def _mix_hex(color, other, t):
    """Mix color toward other by t (0=color, 1=other)."""
    a = _parse_hex_color(color)
    b = _parse_hex_color(other)
    if not a or not b:
        return color
    t = max(0.0, min(1.0, float(t)))
    return _hex_color(tuple(a[i] * (1.0 - t) + b[i] * t for i in range(3)))


def random_accent_color(exclude=None):
    """Bright accent suitable on the dark shelf chrome."""
    exclude = (exclude or "").lower()
    for _ in range(24):
        h = random.random()
        s = random.uniform(0.70, 0.95)
        l = random.uniform(0.48, 0.62)
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        color = _hex_color((r * 255, g * 255, b * 255))
        if color.lower() != exclude:
            return color
    return DEFAULT_ACCENT


def get_accent_color():
    global _accent_color
    if _accent_color is None:
        prefs = load_shelf_prefs()
        color = prefs.get("accent") or DEFAULT_ACCENT
        if _parse_hex_color(color) is None:
            color = DEFAULT_ACCENT
        _accent_color = color
    return _accent_color


def set_accent_color(color):
    """Persist and cache the shelf accent color."""
    global _accent_color
    if _parse_hex_color(color) is None:
        color = DEFAULT_ACCENT
    _accent_color = color
    prefs = load_shelf_prefs()
    prefs["accent"] = color
    try:
        save_shelf_prefs(prefs)
        print("[Shelf] Accent color saved: %s (%s)" % (color, user_shelf_prefs_path()))
    except Exception as e:
        print("[Shelf] Could not save accent prefs: %s" % e)
    return color


def shelf_style(accent=None):
    """Build the shelf stylesheet for the given (or current) accent."""
    accent = accent or get_accent_color()
    hover = _lighten_hex(accent, 0.22)
    checked_bg = _mix_hex(accent, "#252525", 0.62)
    pause_on_bg = _mix_hex(accent, "#252525", 0.40)
    return """
    QWidget#StimShelfBar {
        background-color: #252525;
    }
    QToolBar {
        background-color: #252525; border: none; padding: 2px 4px; spacing: 6px;
    }
    QToolBar QToolButton {
        background-color: #323232; border: 1px solid #454545;
        border-radius: 3px; padding: 0px; color: #dfdfdf;
        min-width: %dpx; max-width: %dpx;
        min-height: %dpx; max-height: %dpx;
        width: %dpx; height: %dpx;
    }
    QToolBar QToolButton:hover { background-color: #4a4a4a; border: 1px solid %s; }
    QToolBar QToolButton:checked { background-color: %s; border: 1px solid %s; }
    QToolBar QToolButton#ShelfPauseViewerButton:checked {
        background-color: %s;
        border: 2px solid %s;
        /* inner ring — reads as an “on” glow on dark chrome */
        margin: 1px;
        outline: 1px solid %s;
        outline-offset: -4px;
    }
    QToolBar QToolButton::menu-indicator { image: none; width: 0px; }
    QMenu { background-color: #252525; color: #dfdfdf; border: 1px solid #454545; icon-size: 20px; }
    QMenu::item { padding: 4px 24px 4px 8px; }
    QMenu::item:selected { background-color: %s; color: #252525; }
    QWidget#ShelfTabSelector {
        background-color: #1e1e1e; border-right: 1px solid #3a3a3a;
    }
    QToolButton#ShelfTabButton {
        background-color: #2a2a2a; border: none; border-radius: 0;
        border-left: 2px solid %s;
        color: %s; padding: 4px 2px; min-width: 20px; max-width: 24px;
        font-size: 9px; font-weight: bold;
    }
    QToolButton#ShelfTabButton:hover {
        color: %s; background-color: #333333;
    }
    QToolButton#ShelfTabButton::menu-indicator { image: none; width: 0px; }
""" % (
        *((SHELF_BUTTON_SIZE,) * 6),
        accent, checked_bg, accent,
        pause_on_bg, accent, hover,
        accent,
        accent, accent, hover,
    )


# ------------------------------------------------------------------------------
# Shelf definition loading / merging
# ------------------------------------------------------------------------------

def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_shelf(data, source_dir, source_label):
    if not isinstance(data, dict):
        raise ValueError("Shelf root must be an object")
    name = data.get("name") or data.get("label")
    if not name:
        raise ValueError("Shelf missing 'name'")
    shelf = {
        "name": name,
        "label": data.get("label") or name,
        "order": int(data.get("order", 100)),
        "actions": [],
        "_sources": [source_label],
        "_dirs": [source_dir],
    }
    for action in data.get("actions") or []:
        if not isinstance(action, dict):
            continue
        act = copy.deepcopy(action)
        act.setdefault("id", act.get("label") or "action")
        shelf["actions"].append(act)
    return shelf


def _merge_shelf(base, overlay):
    """Overlay user shelf onto shared: same action id replaces; new ids append."""
    merged = copy.deepcopy(base)
    merged["label"] = overlay.get("label") or merged["label"]
    if "order" in overlay:
        merged["order"] = overlay["order"]
    merged["_sources"] = list(base.get("_sources", [])) + list(overlay.get("_sources", []))
    merged["_dirs"] = list(base.get("_dirs", [])) + list(overlay.get("_dirs", []))

    by_id = {a.get("id"): i for i, a in enumerate(merged["actions"])}
    for action in overlay.get("actions") or []:
        aid = action.get("id")
        if aid in by_id:
            merged["actions"][by_id[aid]] = copy.deepcopy(action)
        else:
            merged["actions"].append(copy.deepcopy(action))
            by_id[aid] = len(merged["actions"]) - 1
    return merged


def _discover_shelf_files(directory):
    if not directory or not os.path.isdir(directory):
        return []
    files = sorted(glob.glob(os.path.join(directory, "*.json")))
    # skip hidden / underscore-prefixed helpers
    return [p for p in files if not os.path.basename(p).startswith("_")]


def load_all_shelves():
    """Load shelves from ``~/gaffer/shelves``. The shipped shelf is copied there first."""
    ensure_local_shelf()
    shelves = {}
    user_dir = user_shelves_dir()
    for path in _discover_shelf_files(user_dir):
        try:
            data = _load_json(path)
            shelf = _normalize_shelf(data, os.path.dirname(path), path)
            name = shelf["name"]
            if name in shelves:
                shelves[name] = _merge_shelf(shelves[name], shelf)
            else:
                shelves[name] = shelf
        except Exception as e:
            print("[Shelf] Failed to load user shelf %s: %s" % (path, e))

    # Prefer Lookdev / Lighting first when present, then any extras by order/name
    result = list(shelves.values())
    result.sort(key=lambda s: (s.get("order", 100), s.get("name", "")))

    if not result:
        print("[Shelf] No shelf JSON found in %s" % user_dir)
    return result


# ------------------------------------------------------------------------------
# Icon + command helpers
# ------------------------------------------------------------------------------

def _icon_search_dirs(shelf):
    """
    Icon lookup order:
      1. Per-shelf source dirs (user shelf JSON dir + its icons/ subfolder)
      2. User local icons  (~/gaffer/shelves/icons) — never touched by studio
      3. Shared studio icons (``pipegaffer/icons``)
    """
    dirs = []
    for d in shelf.get("_dirs") or []:
        dirs.append(os.path.join(d, "icons"))
        dirs.append(d)
    shared = shared_icons_dir()
    dirs.extend([
        user_icons_dir(),
        os.path.join(shared, "gaffer"),
        os.path.join(shared, "usd"),
        shared,
    ])
    # de-dupe preserving order
    seen = set()
    out = []
    for d in dirs:
        n = os.path.normpath(d)
        if n not in seen and os.path.isdir(n):
            seen.add(n)
            out.append(n)
    return out


def resolve_icon(icon_name, shelf, widget, size=None):
    """
    Load a shelf icon maximized to *size* (default ``SHELF_ICON_SIZE``).

    PNGs are scaled to fill the button icon area while keeping aspect ratio.
    Bare names are resolved under ``pipegaffer/icons`` (and shelf/user dirs).
    """
    if not icon_name:
        return QIcon()
    if size is None:
        size = SHELF_ICON_SIZE

    path = None
    if os.path.isabs(icon_name) and os.path.isfile(icon_name):
        path = icon_name
    else:
        for d in _icon_search_dirs(shelf):
            candidate = os.path.join(d, icon_name)
            if os.path.isfile(candidate):
                path = candidate
                break

    if path is None:
        return widget.style().standardIcon(QStyle.SP_FileIcon)

    pixmap = QPixmap(path)
    if pixmap.isNull():
        return QIcon(path)

    if pixmap.width() != size or pixmap.height() != size:
        pixmap = pixmap.scaled(
            size,
            size,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
    return QIcon(pixmap)


def _action_search_dirs(shelf):
    dirs = []
    for d in shelf.get("_dirs") or []:
        dirs.append(os.path.join(d, "actions"))
        dirs.append(d)
    dirs.append(os.path.join(shared_shelves_dir(), "actions"))
    dirs.append(os.path.join(user_shelves_dir(), "actions"))
    dirs.append(_UI_DIR)
    dirs.append(_REPO_DIR)
    seen = set()
    out = []
    for d in dirs:
        n = os.path.normpath(d)
        if n not in seen and os.path.isdir(n):
            seen.add(n)
            out.append(n)
    return out


def run_action_command(command, scriptNode, button=None, action=None, data=None, shelf_state=None):
    """Execute a shelf command string with a useful locals namespace."""
    if not command:
        return
    ns = {
        "__name__": "__shelf_action__",
        "scriptNode": scriptNode,
        "root": scriptNode,
        "Gaffer": Gaffer,
        "GafferScene": GafferScene,
        "GafferUI": GafferUI,
        "button": button,
        "action": action,
        "data": data,
        "shelf": shelf_state if shelf_state is not None else {},
        "os": os,
        "sys": sys,
        "importlib": importlib,
    }
    try:
        exec(command, ns, ns)  # noqa: S102 — intentional user/studio shelf scripts
    except Exception:
        print("[Shelf] Action failed:\n%s" % traceback.format_exc())


def run_script_file(script_rel, scriptNode, shelf, button=None, action=None, data=None, shelf_state=None):
    path = script_rel
    if not os.path.isabs(path):
        for d in _action_search_dirs(shelf):
            candidate = os.path.join(d, script_rel)
            if os.path.isfile(candidate):
                path = candidate
                break
    if not os.path.isfile(path):
        print("[Shelf] Script not found: %s" % script_rel)
        return
    with open(path, "r", encoding="utf-8") as f:
        code = f.read()
    run_action_command(code, scriptNode, button=button, action=action, data=data, shelf_state=shelf_state)


def invoke_action(defn, scriptNode, shelf, button=None, qt_action=None, data=None, shelf_state=None):
    if defn.get("script"):
        run_script_file(
            defn["script"], scriptNode, shelf,
            button=button, action=qt_action, data=data, shelf_state=shelf_state,
        )
    elif defn.get("command"):
        run_action_command(
            defn["command"], scriptNode,
            button=button, action=qt_action, data=data if data is not None else defn.get("data"),
            shelf_state=shelf_state,
        )


# ------------------------------------------------------------------------------
# Built-in complex widgets
# ------------------------------------------------------------------------------

def _bbox_mod():
    from sdvTkGafferUI.GafferShelfUI import geoExpansion
    return geoExpansion


def _square_shelf_button(btn):
    """Force action buttons to a fixed square size with maximized icons."""
    btn.setFixedSize(SHELF_BUTTON_SIZE, SHELF_BUTTON_SIZE)
    btn.setIconSize(QSize(SHELF_ICON_SIZE, SHELF_ICON_SIZE))
    btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


HOLD_FLYOUT_DELAY_MS = 280  # unused; kept for older docs / local shelf JSON


def _event_global_pos(event):
    """Qt5 ``globalPos`` / Qt6 ``globalPosition`` helper."""
    if hasattr(event, "globalPosition"):
        return event.globalPosition().toPoint()
    return event.globalPos()


class _HoldIconFlyout(QFrame):
    """
    Frameless icon column shown on a single click of the shelf button.

    Uses a Tool window (not Qt.Popup) so the flyout stays open until an
    icon is clicked or the user clicks away.
    """

    def __init__(self, items, shelf, scriptNode, shelf_state, anchor_btn, parent=None):
        flags = (
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
        )
        super(_HoldIconFlyout, self).__init__(parent, flags)
        self.setObjectName("ShelfHoldFlyout")
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self._apply_style()
        self._items = list(items or [])
        self._shelf = shelf
        self._scriptNode = scriptNode
        self._shelf_state = shelf_state
        self._anchor = anchor_btn
        self._buttons = []
        self._actions = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        for item in self._items:
            if item.get("separator"):
                continue
            btn = QToolButton(self)
            btn.setObjectName("ShelfFlyoutAction")
            _square_shelf_button(btn)
            icon = resolve_icon(item.get("icon"), shelf, btn)
            label = item.get("label") or item.get("id") or "?"
            if item.get("icon") and not icon.isNull():
                btn.setIcon(icon)
            else:
                btn.setText(label[:3])
            btn.setToolTip(item.get("tooltip") or item.get("label") or label)
            btn.clicked.connect(self._make_click(item))
            layout.addWidget(btn)
            self._buttons.append(btn)
            self._actions.append(item)

        self.adjustSize()

    def _apply_style(self):
        accent = get_accent_color()
        self.setStyleSheet(
            """
            QFrame#ShelfHoldFlyout {
                background-color: #252525;
                border: 1px solid #555555;
                border-radius: 4px;
            }
            QToolButton#ShelfFlyoutAction {
                background-color: #323232;
                border: 1px solid #454545;
                border-radius: 3px;
            }
            QToolButton#ShelfFlyoutAction:hover {
                background-color: #4a4a4a;
                border: 1px solid %s;
            }
            QToolButton#ShelfFlyoutAction:pressed {
                background-color: #2a2a2a;
                border: 1px solid %s;
            }
            """ % (accent, accent)
        )

    def _make_click(self, item_defn):
        def _click(checked=False):
            self.hide()
            invoke_action(
                item_defn, self._scriptNode, self._shelf,
                button=self._anchor, shelf_state=self._shelf_state,
            )
        return _click

    def button_at(self, global_pos):
        """Return the flyout tool-button under *global_pos*, if any."""
        for btn in self._buttons:
            if btn.isVisible() and btn.rect().contains(btn.mapFromGlobal(global_pos)):
                return btn
        return None

    def trigger_at(self, global_pos):
        """Run the flyout action under *global_pos*. Returns True if handled."""
        for btn, item in zip(self._buttons, self._actions):
            if btn.isVisible() and btn.rect().contains(btn.mapFromGlobal(global_pos)):
                self.hide()
                invoke_action(
                    item, self._scriptNode, self._shelf,
                    button=self._anchor, shelf_state=self._shelf_state,
                )
                return True
        return False

    def popup_below(self, anchor):
        """Open as a vertical column just under / aligned with the anchor."""
        self._apply_style()
        self.adjustSize()
        # Prefer dropping straight down under the shelf button (column of icons).
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 2))
        self.move(pos)
        self.show()
        self.raise_()

    def showEvent(self, event):
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        super(_HoldIconFlyout, self).showEvent(event)

    def hideEvent(self, event):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super(_HoldIconFlyout, self).hideEvent(event)

    def eventFilter(self, obj, event):
        if not self.isVisible():
            return False
        et = event.type()
        if et == QtCore.QEvent.MouseButtonPress:
            gp = _event_global_pos(event)
            if self.rect().contains(self.mapFromGlobal(gp)):
                return False
            if self._anchor is not None and self._anchor.rect().contains(
                self._anchor.mapFromGlobal(gp)
            ):
                return False
            self.hide()
            return False
        if et == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape:
            self.hide()
            return True
        return False


class _HoldFlyoutButton(QToolButton):
    """
    Shelf button: single click opens a column of icon actions.

    Hover highlights each icon; click an icon to run it. Click away or Esc
    dismisses. Toggle-click the shelf button to close if already open.
    """

    def __init__(self, items, shelf, scriptNode, shelf_state, parent=None):
        super(_HoldFlyoutButton, self).__init__(parent)
        self._items = list(items or [])
        self._shelf = shelf
        self._scriptNode = scriptNode
        self._shelf_state = shelf_state
        self._flyout = None
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self, checked=False):
        if self._flyout is not None and self._flyout.isVisible():
            self._flyout.hide()
            return
        self._show_flyout()

    def _show_flyout(self):
        if self._flyout is None:
            self._flyout = _HoldIconFlyout(
                self._items, self._shelf, self._scriptNode,
                self._shelf_state, self, parent=None,
            )
        self._flyout.popup_below(self)


def _build_hold_flyout_button(parent, scriptNode, shelf, shelf_state, defn):
    """Build a click-to-reveal icon flyout from a shelf action definition."""
    btn = _HoldFlyoutButton(
        defn.get("hold") or [], shelf, scriptNode, shelf_state, parent,
    )
    _square_shelf_button(btn)
    icon = resolve_icon(defn.get("icon"), shelf, btn)
    label = defn.get("label") or defn.get("id") or "?"
    if defn.get("icon") and not icon.isNull():
        btn.setIcon(icon)
    else:
        btn.setText(label)
    tip = defn.get("tooltip") or defn.get("label") or ""
    if tip and "hold" in tip.lower():
        # Older JSON text said "Hold click…" — keep meaning, drop hold wording.
        tip = tip.replace("Hold click, then choose", "Click to choose").replace(
            "Hold click", "Click"
        ).replace("hold to choose", "click to choose").replace(
            "Hold to choose", "Click to choose"
        )
    if not tip:
        tip = "Click to choose an action"
    btn.setToolTip(tip)
    return btn


def _build_forced_geometry_button(parent, scriptNode, shelf, shelf_state, defn=None):
    """Forced Geometry button wired to geoExpansion.on() / off()."""
    btn = QToolButton(parent)
    btn.setCheckable(True)
    _square_shelf_button(btn)
    icon_name = (defn or {}).get("icon") or "visu.png"
    icon = resolve_icon(icon_name, shelf, btn)
    if not icon.isNull():
        btn.setIcon(icon)
    else:
        btn.setIcon(btn.style().standardIcon(QStyle.SP_FileDialogDetailedView))
    tip = (defn or {}).get("tooltip") or (
        "Force Viewers to show real geometry instead of bounding boxes.\n"
        "Click to turn on/off; use the menu for depth.\n"
        "No selection needed."
    )
    btn.setToolTip(tip)

    # Match geoExpansion.FORCED_DEPTH default
    shelf_state.setdefault("bbox_depth", 1000)

    mod = _bbox_mod()
    btn.setChecked(bool(mod.is_active()))

    depth_labels = {
        10: "10 — light expand",
        100: "100 — deep expand",
        1000: "1000 — full (default)",
    }
    menu = QMenu(btn)

    act_on = menu.addAction("On")
    act_on.setCheckable(True)
    act_off = menu.addAction("Off")
    act_off.setCheckable(True)
    mode_group = QActionGroup(menu)
    mode_group.setExclusive(True)
    mode_group.addAction(act_on)
    mode_group.addAction(act_off)
    act_on.setChecked(btn.isChecked())
    act_off.setChecked(not btn.isChecked())

    menu.addSeparator()

    depth_group = QActionGroup(menu)
    depth_group.setExclusive(True)
    for d in (10, 100, 1000):
        label = depth_labels.get(d, str(d))
        act = menu.addAction(label)
        act.setCheckable(True)
        act.setData(d)
        act.setChecked(d == int(shelf_state["bbox_depth"]))
        depth_group.addAction(act)

    menu.addSeparator()
    act_report = menu.addAction("Report viewers…")

    def _set_ui_active(active):
        btn.setChecked(bool(active))
        act_on.setChecked(bool(active))
        act_off.setChecked(not bool(active))

    def _activate(active):
        try:
            m = _bbox_mod()
            if active:
                m.on(int(shelf_state["bbox_depth"]))
            else:
                m.off()
            _set_ui_active(active)
        except Exception as e:
            print("[Shelf] geoExpansion failed: %s" % e)
            traceback.print_exc()

    def _on_button_clicked(checked):
        _activate(bool(checked))

    def _on_mode_triggered(action):
        _activate(action is act_on)

    def _on_depth_triggered(action):
        depth = int(action.data())
        shelf_state["bbox_depth"] = depth
        try:
            m = _bbox_mod()
            m.set_depth(depth)
            if m.is_active():
                _set_ui_active(True)
        except Exception as e:
            print("[Shelf] set_depth failed: %s" % e)
            traceback.print_exc()

    def _on_report():
        try:
            _bbox_mod().report()
        except Exception as e:
            print("[Shelf] report failed: %s" % e)

    btn.clicked.connect(_on_button_clicked)
    mode_group.triggered.connect(_on_mode_triggered)
    depth_group.triggered.connect(_on_depth_triggered)
    act_report.triggered.connect(_on_report)

    btn.setMenu(menu)
    # Click icon = toggle on/off; menu arrow = On/Off + depth
    btn.setPopupMode(QToolButton.MenuButtonPopup)
    return btn


def _find_node_by_name(scriptNode, name):
    """Find a node by name or relative path under the script."""
    if not name:
        return None
    for candidate in (name, name.replace("/", ".")):
        try:
            node = scriptNode.descendant(candidate)
            if isinstance(node, Gaffer.Node):
                return node
        except Exception:
            pass
        try:
            child = scriptNode.getChild(candidate)
            if isinstance(child, Gaffer.Node):
                return child
        except Exception:
            pass
    leaf = name.replace("\\", "/").split("/")[-1].split(".")[-1]
    try:
        for node in Gaffer.Node.RecursiveRange(scriptNode):
            if node.getName() == leaf or node.getName() == name:
                return node
    except Exception:
        pass
    return None


def _script_viewers(scriptNode):
    try:
        window = GafferUI.ScriptWindow.acquire(scriptNode)
    except Exception:
        return []
    if window is None:
        return []
    try:
        return list(window.getLayout().editors(GafferUI.Viewer))
    except Exception:
        return []


def _build_entity_focus_button(parent, scriptNode, shelf, shelf_state, defn=None):
    """
    Lighting focus control — square button; click focuses Shot Assembly.

    No Update lives on the Timeline (right side), not on this button.
    """
    btn = QToolButton(parent)
    btn.setCheckable(True)
    _square_shelf_button(btn)
    icon_name = (defn or {}).get("icon") or "entity_load.png"
    icon = resolve_icon(icon_name, shelf, btn)
    if not icon.isNull():
        btn.setIcon(icon)
    else:
        btn.setIcon(btn.style().standardIcon(QStyle.SP_ComputerIcon))
    tip_off = (defn or {}).get("tooltip") or (
        "Focus the graph on the Shot Assembly.\n"
        "Click for focus options.\n"
        "No selection needed."
    )
    tip_on = "Focused on Shot Assembly — click again for options.\nNo selection needed."
    btn.setToolTip(tip_off)

    shelf_state.setdefault("shot_assembly_node", "ShotAssembly")
    shelf_state.setdefault("focus_mode", "normal")  # normal | assembly

    menu = QMenu(btn)
    act_assembly = menu.addAction("Focus Shot Assembly")
    act_assembly.setCheckable(True)
    act_assembly.setToolTip("Focus the Shot Assembly node in the graph.\n"
        "No selection needed.")

    def _sync_ui():
        assembly = (shelf_state.get("focus_mode") or "normal") == "assembly"
        btn.setChecked(assembly)
        act_assembly.blockSignals(True)
        act_assembly.setChecked(assembly)
        act_assembly.blockSignals(False)
        if assembly:
            btn.setToolTip(tip_on)
        else:
            btn.setToolTip(tip_off)

    def _activate_assembly():
        name = shelf_state.get("shot_assembly_node") or "ShotAssembly"
        node = _find_node_by_name(scriptNode, name)
        if node is None:
            print(
                "[Shelf] Shot Assembly node '%s' not found yet — "
                "set shelf_state['shot_assembly_node'] or create the node."
                % name
            )
            _sync_ui()
            return
        try:
            # Leave global No Update so Viewers can show the assembly
            from pipegaffer.ui import ui_tweaks
            if ui_tweaks.get_update_mode() == "unload":
                ui_tweaks.apply_update_mode(scriptNode, "normal")
                ui_tweaks.sync_update_mode_ui()
            scriptNode.setFocus(node)
            try:
                scriptNode.selection().clear()
                scriptNode.selection().add(node)
            except Exception:
                pass
            for editor in _script_viewers(scriptNode):
                try:
                    editor.setNodeSet(scriptNode.focusSet())
                except Exception:
                    pass
            shelf_state["focus_mode"] = "assembly"
            _sync_ui()
            print("[Shelf] Focused Shot Assembly: %s" % node.relativeName(scriptNode))
        except Exception as e:
            print("[Shelf] Focus Shot Assembly failed: %s" % e)
            traceback.print_exc()

    def _clear_assembly():
        try:
            shelf_state["focus_mode"] = "normal"
            _sync_ui()
            print("[Shelf] Shot Assembly focus cleared")
        except Exception as e:
            print("[Shelf] Clear assembly focus failed: %s" % e)

    def _on_assembly(checked=False):
        if shelf_state.get("focus_mode") == "assembly":
            _clear_assembly()
        else:
            _activate_assembly()

    def _on_button_clicked(checked=False):
        _sync_ui()
        pos = btn.mapToGlobal(btn.rect().bottomLeft())
        _menu_exec_at(menu, pos)
        _sync_ui()

    act_assembly.triggered.connect(_on_assembly)
    btn.clicked.connect(_on_button_clicked)

    def _on_focus_changed(script, node):
        if shelf_state.get("focus_mode") != "assembly":
            return
        name = shelf_state.get("shot_assembly_node") or "ShotAssembly"
        still = False
        if node is not None:
            try:
                still = (
                    node.getName() == name
                    or node.relativeName(scriptNode) == name
                )
            except Exception:
                still = node.getName() == name
        if not still:
            shelf_state["focus_mode"] = "normal"
            _sync_ui()

    try:
        shelf_state["_entity_focus_conn"] = scriptNode.focusChangedSignal().connect(
            _on_focus_changed, scoped=True
        )
    except Exception:
        pass

    focused = scriptNode.getFocus()
    aname = shelf_state.get("shot_assembly_node") or "ShotAssembly"
    is_assembly = False
    if focused is not None:
        try:
            is_assembly = (
                focused.getName() == aname
                or focused.relativeName(scriptNode) == aname
            )
        except Exception:
            is_assembly = focused.getName() == aname
    shelf_state["focus_mode"] = "assembly" if is_assembly else "normal"
    _sync_ui()
    return btn


def _build_arnold_lights_button(parent, scriptNode, shelf, shelf_state, defn=None):
    """
    Lights menu — every Arnold light type available in Gaffer
    (queried from the Arnold universe, same source as Arnold node menu).
    """
    btn = QToolButton(parent)
    _square_shelf_button(btn)
    icon_name = (defn or {}).get("icon") or "lights.png"
    icon = resolve_icon(icon_name, shelf, btn)
    if not icon.isNull():
        btn.setIcon(icon)
    else:
        btn.setText("LGT")
    tip = (defn or {}).get("tooltip") or (
        "Create an Arnold light in the current Graph Editor.\n"
        "Select a scene node first to MergeScenes it into that flow;\n"
        "otherwise the light is placed alone."
    )
    btn.setToolTip(tip)

    menu = QMenu(btn)

    def _rebuild_menu():
        menu.clear()
        try:
            from pipegaffer.lighting.utils import lights as lgt_lights
            items = lgt_lights.list_arnold_lights()
        except Exception as e:
            print("[Shelf] Could not list Arnold lights: %s" % e)
            traceback.print_exc()
            items = []

        if not items:
            act = menu.addAction("(No Arnold lights found)")
            act.setEnabled(False)
            return

        for shader_name, display_name in items:
            act = menu.addAction(display_name)
            act.setToolTip("Create Arnold %s in the current Graph Editor.\n"
                "With a scene node selected: MergeScenes into that flow."
                % display_name)

            def _make(shader=shader_name):
                def _triggered(checked=False):
                    try:
                        from pipegaffer.lighting.utils import lights as lgt_lights
                        lgt_lights.create_arnold_light(scriptNode, shader)
                    except Exception as err:
                        print("[Shelf] Create Arnold light failed: %s" % err)
                        traceback.print_exc()
                return _triggered

            act.triggered.connect(_make())

    def _on_click(checked=False):
        _rebuild_menu()
        pos = btn.mapToGlobal(btn.rect().bottomLeft())
        _menu_exec_at(menu, pos)

    btn.clicked.connect(_on_click)
    return btn


def _build_pause_viewers_button(parent, scriptNode, shelf, shelf_state, defn=None):
    """Toggle Viewer setPaused — one icon; checked = pause enabled (inner glow)."""
    from pipegaffer.ui import ui_tweaks

    btn = QToolButton(parent)
    btn.setObjectName("ShelfPauseViewerButton")
    btn.setCheckable(True)
    _square_shelf_button(btn)

    icon_name = (defn or {}).get("icon") or "view_pause.png"
    icon = resolve_icon(icon_name, shelf, btn)
    if not icon.isNull():
        btn.setIcon(icon)
    else:
        btn.setText("||")

    tip_off = (defn or {}).get("tooltip") or (
        "Pause Viewer updates (same as Esc).\nNo selection needed."
    )
    tip_on = "Pause enabled — click to resume Viewer updates.\nNo selection needed."

    def _sync(paused):
        btn.setChecked(bool(paused))
        btn.setToolTip(tip_on if paused else tip_off)

    # Startup: Viewers are running (pause not enabled)
    _sync(ui_tweaks.viewers_are_paused())

    def _on_click(checked=False):
        try:
            paused = ui_tweaks.toggle_viewers_paused(scriptNode)
            _sync(paused)
        except Exception as e:
            print("[Shelf] Pause Viewer failed: %s" % e)
            traceback.print_exc()
            _sync(ui_tweaks.viewers_are_paused())

    btn.clicked.connect(_on_click)
    return btn


def _build_arnold_verbosity_button(parent, scriptNode, shelf, shelf_state, defn=None):
    """Menu — Arnold log / console verbosity presets (next to Pause)."""
    from pipegaffer.ui import arnold_setup

    btn = QToolButton(parent)
    btn.setObjectName("ShelfArnoldVerbosityButton")
    _square_shelf_button(btn)

    icon_name = (defn or {}).get("icon") or "arnold.png"
    icon = resolve_icon(icon_name, shelf, btn)
    if not icon.isNull():
        btn.setIcon(icon)
    else:
        btn.setText("Ai")

    tip = (defn or {}).get("tooltip") or (
        "Arnold render log / console verbosity.\nNo selection needed."
    )
    btn.setToolTip(tip)

    menu = QMenu(btn)

    def _rebuild_menu():
        menu.clear()
        current = arnold_setup.current_verbosity()
        group = QActionGroup(menu)
        group.setExclusive(True)

        header = menu.addAction("Arnold Verbosity")
        header.setEnabled(False)
        font = header.font()
        font.setBold(True)
        header.setFont(font)
        menu.addSeparator()

        for preset_id, label, preset_tip in arnold_setup.verbosity_presets():
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(preset_id == current)
            act.setToolTip(preset_tip)
            act.setData(preset_id)
            group.addAction(act)

            def _make(pid=preset_id):
                def _triggered(checked=False):
                    try:
                        n = arnold_setup.set_verbosity(scriptNode, pid)
                        print(
                            "[Shelf] Arnold verbosity → %s (%d ArnoldOptions)"
                            % (pid, n)
                        )
                    except Exception as err:
                        print("[Shelf] Arnold verbosity failed: %s" % err)
                        traceback.print_exc()
                return _triggered

            act.triggered.connect(_make())

    def _on_click(checked=False):
        _rebuild_menu()
        pos = btn.mapToGlobal(btn.rect().bottomLeft())
        _menu_exec_at(menu, pos)

    btn.clicked.connect(_on_click)
    return btn


def _build_about_pipeline_button(parent, scriptNode, shelf, shelf_state, defn=None):
    """Far-right About button. Opens the same dialog as sdvTk > About."""
    btn = QToolButton(parent)
    _square_shelf_button(btn)
    icon_name = (defn or {}).get("icon") or "about_sdvTk.png"
    icon = resolve_icon(icon_name, shelf, btn)
    if not icon.isNull():
        btn.setIcon(icon)
    else:
        btn.setText((defn or {}).get("label") or "?")
    tip = (defn or {}).get("tooltip") or "About sdvTk"
    btn.setToolTip(tip)

    def _on_click(checked=False):
        from sdvTkGafferUI import menu as sdv_menu
        sdv_menu._open_about()

    btn.clicked.connect(_on_click)
    return btn


BUILTINS = {
    "forced_geometry": _build_forced_geometry_button,
    "entity_focus": _build_entity_focus_button,
    "arnold_lights": _build_arnold_lights_button,
    "pause_viewers": _build_pause_viewers_button,
    "arnold_verbosity": _build_arnold_verbosity_button,
    "about_pipeline": _build_about_pipeline_button,
}


# ------------------------------------------------------------------------------
# UI
# ------------------------------------------------------------------------------

# Short codes shown on the single active tab button (Maya-style).
TAB_SHORT = {
    "sdvTk": "GAF",
    "General": "GEN",
    "Lookdev": "LDV",
    "Lighting": "LGT",
}


def _tab_short(name):
    if name in TAB_SHORT:
        return TAB_SHORT[name]
    letters = "".join(ch for ch in name if ch.isupper())
    if len(letters) >= 2:
        return letters[:3].upper()
    return (name[:3] if name else "?").upper()


def _tab_button_text(name):
    """Stack short code vertically: LDV -> L\\nD\\nV."""
    return "\n".join(_tab_short(name))


# ------------------------------------------------------------------------------
# Local shelf creator / editor (Maya-like)
# ------------------------------------------------------------------------------

EDITOR_STYLE = """
    QDialog {
        background-color: #2b2b2b;
        color: #dfdfdf;
    }
    QLabel { color: #dfdfdf; }
    QLineEdit, QTextEdit, QListWidget {
        background-color: #1e1e1e;
        color: #dfdfdf;
        border: 1px solid #454545;
        border-radius: 3px;
        padding: 4px;
    }
    QLineEdit:focus, QTextEdit:focus, QListWidget:focus {
        border: 1px solid #ffaa00;
    }
    QPushButton {
        background-color: #3a3a3a;
        color: #dfdfdf;
        border: 1px solid #555555;
        border-radius: 3px;
        padding: 5px 12px;
    }
    QPushButton:hover { background-color: #4a4a4a; border: 1px solid #ffaa00; }
    QPushButton:pressed { background-color: #2a2a2a; }
    QPushButton#PrimaryButton {
        background-color: #5a4310;
        border: 1px solid #ffaa00;
        font-weight: bold;
    }
    QPushButton#DangerButton {
        background-color: #5a2020;
        border: 1px solid #aa4444;
        color: #ffcccc;
    }
    QPushButton#DangerButton:hover {
        background-color: #7a3030;
        border: 1px solid #ff6666;
    }
    QListWidget::item:selected { background-color: #5a4310; color: #ffffff; }
"""


class _ShelfNameDialog(QDialog):
    """Ask for a local shelf name (no spaces)."""

    def __init__(self, parent=None, existing_names=None):
        super(_ShelfNameDialog, self).__init__(parent)
        self.setWindowTitle("Create My Shelf (Local)")
        self.setMinimumWidth(360)
        self.setStyleSheet(EDITOR_STYLE)
        self._existing = set(existing_names or [])

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Shelf name (no spaces):"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("MyShelf")
        layout.addWidget(self.name_edit)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #ff8888;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("PrimaryButton")
        buttons.button(QDialogButtonBox.Ok).setText("Create")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.name_edit.returnPressed.connect(self._accept)
        self.name_edit.setFocus()

    def shelf_name(self):
        return self.name_edit.text().strip()

    def _accept(self):
        name = self.shelf_name()
        err = _validate_shelf_name(name)
        if err:
            self.error_label.setText(err)
            return
        if name in self._existing or os.path.isfile(user_shelf_json_path(name)):
            self.error_label.setText("A shelf named '%s' already exists." % name)
            return
        self.accept()


class _LocalShelfEditorDialog(QDialog):
    """
    Maya-like local shelf editor.

    Reads/writes %HOMEPATH%/gaffer/shelves/<Shelf_Name>.json
    Each tool: icon, name, and either a python command or a menu of actions.
    """

    def __init__(self, shelf_name, parent=None):
        super(_LocalShelfEditorDialog, self).__init__(parent)
        self.shelf_name = shelf_name
        self.setWindowTitle("Edit Local Shelf — %s" % shelf_name)
        self.resize(720, 520)
        self.setMinimumSize(580, 420)
        self.setStyleSheet(EDITOR_STYLE)

        self._data = load_user_shelf_data(shelf_name)
        self._actions = [copy.deepcopy(a) for a in (self._data.get("actions") or [])]
        self._suppress = False
        self.deleted = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QLabel("Local shelf: <b>%s</b>  →  %s" % (
            shelf_name, user_shelf_json_path(shelf_name)
        ))
        header.setWordWrap(True)
        root.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        # --- Left: tool list ---
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(QLabel("Tools"))
        self.tool_list = QListWidget()
        self.tool_list.currentRowChanged.connect(self._on_selection_changed)
        left.addWidget(self.tool_list, 1)

        list_btns = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self._add_tool)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_tool)
        list_btns.addWidget(self.add_btn)
        list_btns.addWidget(self.remove_btn)
        left.addLayout(list_btns)
        body.addLayout(left, 1)

        # --- Right: tool fields ---
        right = QVBoxLayout()
        right.setSpacing(8)
        right.addWidget(QLabel("Tool details"))

        form = QFormLayout()
        form.setSpacing(8)

        icon_row = QHBoxLayout()
        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(36, 36)
        self.icon_preview.setStyleSheet(
            "background-color: #1e1e1e; border: 1px solid #454545; border-radius: 3px;"
        )
        self.icon_preview.setAlignment(QtCore.Qt.AlignCenter)
        self.icon_path = QLineEdit()
        self.icon_path.setPlaceholderText("icon filename or path")
        self.icon_path.textChanged.connect(self._on_fields_changed)
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.setEnabled(True)
        self.browse_btn.clicked.connect(self._browse_icon)
        icon_row.addWidget(self.icon_preview)
        icon_row.addWidget(self.icon_path, 1)
        icon_row.addWidget(self.browse_btn)
        form.addRow("Icon", icon_row)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Tool name")
        self.name_edit.textChanged.connect(self._on_fields_changed)
        form.addRow("Tool Name", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItem("Button", "button")
        self.type_combo.addItem("Menu (context on click)", "menu")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("Type", self.type_combo)

        right.addLayout(form)

        # --- Button command (single action) ---
        self.command_label = QLabel("Command")
        right.addWidget(self.command_label)
        self.command_edit = QTextEdit()
        self.command_edit.setPlaceholderText(
            "# Python command\n"
            "# Available: scriptNode, root, Gaffer, GafferUI, GafferScene, …\n"
            "print('hello from shelf')"
        )
        self.command_edit.setAcceptRichText(False)
        self.command_edit.textChanged.connect(self._on_fields_changed)
        right.addWidget(self.command_edit, 1)

        # --- Menu items editor ---
        self.menu_panel = QWidget()
        menu_layout = QVBoxLayout(self.menu_panel)
        menu_layout.setContentsMargins(0, 0, 0, 0)
        menu_layout.setSpacing(6)
        menu_layout.addWidget(QLabel("Menu items"))

        menu_body = QHBoxLayout()
        menu_body.setSpacing(8)
        menu_layout.addLayout(menu_body, 1)

        menu_left = QVBoxLayout()
        menu_left.setSpacing(4)
        self.menu_list = QListWidget()
        self.menu_list.currentRowChanged.connect(self._on_menu_selection_changed)
        menu_left.addWidget(self.menu_list, 1)
        menu_item_btns = QHBoxLayout()
        self.menu_add_btn = QPushButton("Add")
        self.menu_add_btn.clicked.connect(self._add_menu_item)
        self.menu_sep_btn = QPushButton("Separator")
        self.menu_sep_btn.clicked.connect(self._add_menu_separator)
        self.menu_remove_btn = QPushButton("Remove")
        self.menu_remove_btn.clicked.connect(self._remove_menu_item)
        menu_item_btns.addWidget(self.menu_add_btn)
        menu_item_btns.addWidget(self.menu_sep_btn)
        menu_item_btns.addWidget(self.menu_remove_btn)
        menu_left.addLayout(menu_item_btns)
        menu_body.addLayout(menu_left, 1)

        menu_right = QVBoxLayout()
        menu_right.setSpacing(4)
        self.menu_item_name = QLineEdit()
        self.menu_item_name.setPlaceholderText("Menu item label")
        self.menu_item_name.textChanged.connect(self._on_menu_item_fields_changed)
        menu_right.addWidget(self.menu_item_name)
        self.menu_item_command = QTextEdit()
        self.menu_item_command.setPlaceholderText(
            "# Python for this menu action\n"
            "print('menu item')"
        )
        self.menu_item_command.setAcceptRichText(False)
        self.menu_item_command.textChanged.connect(self._on_menu_item_fields_changed)
        menu_right.addWidget(self.menu_item_command, 1)
        menu_body.addLayout(menu_right, 2)

        right.addWidget(self.menu_panel, 1)
        body.addLayout(right, 2)

        buttons = QDialogButtonBox()
        self.delete_shelf_btn = QPushButton("Delete Shelf")
        self.delete_shelf_btn.setObjectName("DangerButton")
        self.delete_shelf_btn.clicked.connect(self._delete_shelf)
        buttons.addButton(self.delete_shelf_btn, QDialogButtonBox.ResetRole)

        save_btn = buttons.addButton("Save Shelf", QDialogButtonBox.AcceptRole)
        save_btn.setObjectName("PrimaryButton")
        cancel_btn = buttons.addButton(QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._rebuild_list()
        if self.tool_list.count():
            self.tool_list.setCurrentRow(0)
        else:
            self._set_fields_enabled(False)
            self._update_type_visibility()

    def _tool_list_label(self, act):
        return act.get("label") or act.get("id") or "Tool"

    def _rebuild_list(self, select_row=None):
        self._suppress = True
        self.tool_list.clear()
        for act in self._actions:
            self.tool_list.addItem(QListWidgetItem(self._tool_list_label(act)))
        self._suppress = False
        if select_row is not None and 0 <= select_row < self.tool_list.count():
            self.tool_list.setCurrentRow(select_row)

    def _is_menu_tool(self):
        return self.type_combo.currentData() == "menu"

    def _update_type_visibility(self):
        is_menu = self._is_menu_tool()
        self.command_label.setVisible(not is_menu)
        self.command_edit.setVisible(not is_menu)
        self.menu_panel.setVisible(is_menu)

    def _set_fields_enabled(self, enabled):
        self.icon_path.setEnabled(enabled)
        # Browse stays clickable; it will auto-create a tool if needed
        self.browse_btn.setEnabled(True)
        self.name_edit.setEnabled(enabled)
        self.type_combo.setEnabled(enabled)
        self.command_edit.setEnabled(enabled)
        self.menu_list.setEnabled(enabled)
        self.menu_add_btn.setEnabled(enabled)
        self.menu_sep_btn.setEnabled(enabled)
        self.menu_remove_btn.setEnabled(enabled)
        self.menu_item_name.setEnabled(enabled)
        self.menu_item_command.setEnabled(enabled)
        self.remove_btn.setEnabled(enabled and self.tool_list.count() > 0)

    def _current_index(self):
        return self.tool_list.currentRow()

    def _current_action(self):
        row = self._current_index()
        if row < 0 or row >= len(self._actions):
            return None
        return self._actions[row]

    def _ensure_tool_selected(self):
        """Guarantee a tool row exists/is selected before editing icon etc."""
        row = self._current_index()
        if row < 0 or row >= len(self._actions):
            self._add_tool()
            row = self._current_index()
        return row

    def _set_combo_by_data(self, combo, data, default_index=0):
        for i in range(combo.count()):
            if combo.itemData(i) == data:
                combo.setCurrentIndex(i)
                return
        combo.setCurrentIndex(default_index)

    def _rebuild_menu_list(self, select_row=None):
        act = self._current_action()
        self._suppress = True
        self.menu_list.clear()
        items = (act.get("menu") if act else None) or []
        for item in items:
            if item.get("separator"):
                text = "——— separator ———"
            else:
                text = item.get("label") or item.get("id") or "Item"
            self.menu_list.addItem(QListWidgetItem(text))
        self._suppress = False
        if items:
            row = select_row if select_row is not None else 0
            row = max(0, min(row, len(items) - 1))
            self.menu_list.setCurrentRow(row)
        else:
            self._clear_menu_item_fields()

    def _clear_menu_item_fields(self):
        self._suppress = True
        self.menu_item_name.clear()
        self.menu_item_command.clear()
        self.menu_item_name.setEnabled(False)
        self.menu_item_command.setEnabled(False)
        self._suppress = False

    def _on_selection_changed(self, row):
        if self._suppress:
            return
        if row < 0 or row >= len(self._actions):
            self._suppress = True
            self.icon_path.clear()
            self.name_edit.clear()
            self.command_edit.clear()
            self._set_combo_by_data(self.type_combo, "button")
            self._update_icon_preview("")
            self.menu_list.clear()
            self._clear_menu_item_fields()
            self._suppress = False
            self._set_fields_enabled(False)
            self._update_type_visibility()
            return

        act = self._actions[row]
        is_menu = bool(act.get("menu"))
        self._suppress = True
        self.icon_path.setText(act.get("icon") or "")
        self.name_edit.setText(act.get("label") or act.get("id") or "")
        self._set_combo_by_data(self.type_combo, "menu" if is_menu else "button")
        self.command_edit.setPlainText(act.get("command") or "")
        self._update_icon_preview(act.get("icon") or "")
        self._suppress = False
        self._set_fields_enabled(True)
        self._update_type_visibility()
        if is_menu:
            self._rebuild_menu_list()

    def _on_type_changed(self, *_args):
        if self._suppress:
            return
        act = self._current_action()
        if act is None:
            return
        want_menu = self._is_menu_tool()
        has_menu = bool(act.get("menu"))
        if want_menu and not has_menu:
            # Promote existing command into a first menu item when switching
            first = {
                "id": _action_id_from_label("item", []),
                "label": "Item",
                "command": act.get("command") or "",
            }
            act["menu"] = [first]
            act.pop("command", None)
            self._rebuild_menu_list(select_row=0)
        elif not want_menu and has_menu:
            # Keep first non-separator command when collapsing to a button
            command = ""
            for item in act.get("menu") or []:
                if item.get("separator"):
                    continue
                command = item.get("command") or ""
                break
            act.pop("menu", None)
            act.pop("popup", None)
            act["command"] = command
            self._suppress = True
            self.command_edit.setPlainText(command)
            self._suppress = False
        self._update_type_visibility()
        self._refresh_tool_list_label()
        self._on_fields_changed()

    def _refresh_tool_list_label(self):
        row = self._current_index()
        act = self._current_action()
        if act is None or row < 0:
            return
        item = self.tool_list.item(row)
        if item is not None:
            item.setText(self._tool_list_label(act))

    def _on_fields_changed(self, *_args):
        if self._suppress:
            return
        row = self._current_index()
        if row < 0 or row >= len(self._actions):
            return
        act = self._actions[row]
        label = self.name_edit.text().strip() or "Tool"
        act["label"] = label
        act["tooltip"] = label
        act["icon"] = self.icon_path.text().strip()
        if not act.get("id"):
            existing = [a.get("id") for a in self._actions if a is not act]
            act["id"] = _action_id_from_label(label, existing)

        if self._is_menu_tool():
            act.setdefault("menu", [])
            act.pop("command", None)
            act.pop("popup", None)
        else:
            act["command"] = self.command_edit.toPlainText()
            act.pop("menu", None)
            act.pop("popup", None)

        self._suppress = True
        self._refresh_tool_list_label()
        self._update_icon_preview(act.get("icon") or "")
        self._suppress = False

    def _on_menu_selection_changed(self, row):
        if self._suppress:
            return
        act = self._current_action()
        items = (act.get("menu") if act else None) or []
        if row < 0 or row >= len(items):
            self._clear_menu_item_fields()
            return
        item = items[row]
        is_sep = bool(item.get("separator"))
        self._suppress = True
        self.menu_item_name.setEnabled(not is_sep)
        self.menu_item_command.setEnabled(not is_sep)
        if is_sep:
            self.menu_item_name.setText("")
            self.menu_item_command.setPlainText("")
        else:
            self.menu_item_name.setText(item.get("label") or item.get("id") or "")
            self.menu_item_command.setPlainText(item.get("command") or "")
        self._suppress = False

    def _on_menu_item_fields_changed(self, *_args):
        if self._suppress:
            return
        act = self._current_action()
        if act is None:
            return
        items = act.get("menu") or []
        row = self.menu_list.currentRow()
        if row < 0 or row >= len(items):
            return
        item = items[row]
        if item.get("separator"):
            return
        label = self.menu_item_name.text().strip() or "Item"
        item["label"] = label
        item["command"] = self.menu_item_command.toPlainText()
        if not item.get("id"):
            existing = [i.get("id") for i in items if i is not item]
            item["id"] = _action_id_from_label(label, existing)
        list_item = self.menu_list.item(row)
        if list_item is not None:
            list_item.setText(label)

    def _add_menu_item(self):
        act = self._current_action()
        if act is None:
            return
        items = act.setdefault("menu", [])
        existing = [i.get("id") for i in items]
        aid = _action_id_from_label("Item", existing)
        items.append({"id": aid, "label": "Item", "command": ""})
        self._rebuild_menu_list(select_row=len(items) - 1)
        self.menu_item_name.setFocus()
        self.menu_item_name.selectAll()
        self._refresh_tool_list_label()

    def _add_menu_separator(self):
        act = self._current_action()
        if act is None:
            return
        items = act.setdefault("menu", [])
        items.append({"separator": True})
        self._rebuild_menu_list(select_row=len(items) - 1)
        self._refresh_tool_list_label()

    def _remove_menu_item(self):
        act = self._current_action()
        if act is None:
            return
        items = act.get("menu") or []
        row = self.menu_list.currentRow()
        if row < 0 or row >= len(items):
            return
        del items[row]
        next_row = min(row, len(items) - 1)
        self._rebuild_menu_list(select_row=next_row if next_row >= 0 else None)
        self._refresh_tool_list_label()

    def _update_icon_preview(self, icon_name):
        icon = QIcon()
        if icon_name:
            if os.path.isabs(icon_name) and os.path.isfile(icon_name):
                icon = QIcon(icon_name)
            else:
                for directory in (user_icons_dir(), shared_icons_dir(), os.path.join(shared_icons_dir(), "usd")):
                    candidate = os.path.join(directory, icon_name)
                    if os.path.isfile(candidate):
                        icon = QIcon(candidate)
                        break
        if icon.isNull():
            self.icon_preview.clear()
            self.icon_preview.setText("—")
        else:
            self.icon_preview.setText("")
            self.icon_preview.setPixmap(icon.pixmap(32, 32))

    def _browse_icon(self):
        self._ensure_tool_selected()
        try:
            path = _pick_existing_file(
                self,
                "Select Shelf Icon",
                user_icons_dir(),
                "Images (*.png *.jpg *.jpeg *.bmp *.gif *.svg);;All Files (*)",
            )
        except Exception as e:
            print("[Shelf] Icon browse failed: %s" % e)
            traceback.print_exc()
            QMessageBox.warning(self, "Browse Failed", str(e))
            return
        if not path:
            return
        stored = _import_icon_to_user(path)
        if stored:
            self.icon_path.setText(stored)

    def _add_tool(self):
        existing = [a.get("id") for a in self._actions]
        aid = _action_id_from_label("NewTool", existing)
        self._actions.append({
            "id": aid,
            "label": "NewTool",
            "tooltip": "NewTool",
            "icon": "",
            "command": "",
        })
        self._rebuild_list(select_row=len(self._actions) - 1)
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _remove_tool(self):
        row = self._current_index()
        if row < 0 or row >= len(self._actions):
            return
        del self._actions[row]
        next_row = min(row, len(self._actions) - 1)
        self._rebuild_list(select_row=next_row if next_row >= 0 else None)
        if next_row < 0:
            self._on_selection_changed(-1)

    def _delete_shelf(self):
        path = user_shelf_json_path(self.shelf_name)
        reply = QMessageBox.question(
            self,
            "Delete Shelf",
            "Delete local shelf '%s'?\n\nThis will remove:\n%s" % (self.shelf_name, path),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            delete_user_shelf(self.shelf_name)
        except Exception as e:
            QMessageBox.critical(self, "Delete Failed", str(e))
            return
        self.deleted = True
        self.reject()

    def _clean_menu_items(self, items):
        cleaned = []
        seen = set()
        for item in items or []:
            if not isinstance(item, dict):
                continue
            if item.get("separator"):
                cleaned.append({"separator": True})
                continue
            label = (item.get("label") or "").strip() or "Item"
            if item.get("title") or item.get("header"):
                cleaned.append({"id": item.get("id") or "title", "label": label, "title": True})
                continue
            aid = item.get("id") or _action_id_from_label(label, seen)
            if aid in seen:
                aid = _action_id_from_label(label, seen)
            seen.add(aid)
            entry = {"id": aid, "label": label}
            command = item.get("command") or ""
            if command.strip():
                entry["command"] = command
            script = (item.get("script") or "").strip()
            if script:
                entry["script"] = script
            if item.get("checkable"):
                entry["checkable"] = True
                entry["checked"] = bool(item.get("checked", False))
            if item.get("group"):
                entry["group"] = item["group"]
            if "data" in item:
                entry["data"] = item["data"]
            cleaned.append(entry)
        return cleaned

    def _save(self):
        # Flush current fields (tool + selected menu item)
        self._on_fields_changed()
        self._on_menu_item_fields_changed()
        # Ensure every action has a stable id
        seen = set()
        cleaned = []
        for act in self._actions:
            label = (act.get("label") or "").strip() or "Tool"
            aid = act.get("id") or _action_id_from_label(label, seen)
            if aid in seen:
                aid = _action_id_from_label(label, seen)
            seen.add(aid)
            entry = {
                "id": aid,
                "label": label,
                "tooltip": act.get("tooltip") or label,
            }
            icon = (act.get("icon") or "").strip()
            if icon:
                entry["icon"] = icon

            menu_items = act.get("menu")
            if menu_items:
                entry["menu"] = self._clean_menu_items(menu_items)
            else:
                command = act.get("command") or ""
                if command.strip():
                    entry["command"] = command
                script = (act.get("script") or "").strip()
                if script:
                    entry["script"] = script
            cleaned.append(entry)

        self._data["name"] = self.shelf_name
        self._data["label"] = self.shelf_name
        self._data["actions"] = cleaned
        try:
            save_user_shelf_data(self.shelf_name, self._data)
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", str(e))
            return
        self.accept()


class _TabSelector(QWidget):
    """
    Single Maya-style shelf tab switcher.

    Only the *active* tab label is shown (e.g. GEN). A click opens a small
    menu to pick another shelf; tabs are mutually exclusive — one at a time.
    Also exposes Create / Edit local shelf actions.

    Right-click the orange tab button to randomize the shelf accent color
    (saved under the user shelves ``_prefs.json``).
    """

    tabChanged = QtCore.Signal(str)
    accentChanged = QtCore.Signal(str)
    createLocalRequested = QtCore.Signal()
    editLocalRequested = QtCore.Signal(str)
    deleteLocalRequested = QtCore.Signal(str)

    def __init__(self, tab_names, parent=None, current=None):
        super(_TabSelector, self).__init__(parent)
        self.setObjectName("ShelfTabSelector")
        self.setFixedWidth(24)
        self._tab_names = list(tab_names) or list(DEFAULT_TAB_ORDER)
        self._current = current if current in self._tab_names else self._tab_names[0]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(0)

        self._button = QToolButton(self)
        self._button.setObjectName("ShelfTabButton")
        self._button.setAutoRaise(True)
        self._button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._button.setPopupMode(QToolButton.InstantPopup)  # left-click → menu
        self._button.setContextMenuPolicy(QtCore.Qt.PreventContextMenu)
        self._button.installEventFilter(self)

        self._menu = QMenu(self._button)
        self._button.setMenu(self._menu)
        self._rebuild_menu()
        self._refresh_button()

        layout.addWidget(self._button)
        layout.addStretch(1)

    def eventFilter(self, obj, event):
        if obj is self._button:
            et = event.type()
            if et == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.RightButton:
                self._randomize_accent()
                return True
            if et == QtCore.QEvent.ContextMenu:
                self._randomize_accent()
                return True
        return super(_TabSelector, self).eventFilter(obj, event)

    def _randomize_accent(self):
        color = random_accent_color(exclude=get_accent_color())
        set_accent_color(color)
        self._refresh_button()
        self.accentChanged.emit(color)

    def _rebuild_menu(self):
        self._menu.clear()
        group = QActionGroup(self._menu)
        group.setExclusive(True)
        for name in self._tab_names:
            short = _tab_short(name)
            label = "%s  (%s)" % (name, short)
            act = self._menu.addAction(label)
            act.setCheckable(True)
            act.setData(name)
            act.setChecked(name == self._current)
            group.addAction(act)

        def _picked(action):
            name = action.data()
            if not name or name == self._current:
                return
            self._current = name
            self._refresh_button()
            self.tabChanged.emit(name)

        group.triggered.connect(_picked)

        self._menu.addSeparator()
        create_act = self._menu.addAction("Create My Shelf (Local)…")
        create_act.triggered.connect(lambda checked=False: self.createLocalRequested.emit())

        local_names = list_user_shelf_names()
        if local_names:
            edit_menu = self._menu.addMenu("Edit Local Shelf")
            for name in local_names:
                edit_act = edit_menu.addAction(name)
                edit_act.triggered.connect(
                    lambda checked=False, n=name: self.editLocalRequested.emit(n)
                )
            delete_menu = self._menu.addMenu("Delete Local Shelf")
            for name in local_names:
                delete_act = delete_menu.addAction(name)
                delete_act.triggered.connect(
                    lambda checked=False, n=name: self.deleteLocalRequested.emit(n)
                )

    def _refresh_button(self):
        short = _tab_short(self._current)
        self._button.setText(_tab_button_text(self._current))
        accent = get_accent_color()
        self._button.setToolTip("%s (%s) — click to switch shelf\n"
            "Right-click to change accent color (%s)"
            % (self._current, short, accent))
        # Keep menu checkmarks in sync without rebuilding every time if possible
        for act in self._menu.actions():
            if act.isCheckable():
                act.setChecked(act.data() == self._current)

    def setTabs(self, tab_names, current=None):
        self._tab_names = list(tab_names) or list(DEFAULT_TAB_ORDER)
        if current and current in self._tab_names:
            self._current = current
        elif self._current not in self._tab_names:
            self._current = self._tab_names[0]
        self._rebuild_menu()
        self._refresh_button()

    def setCurrent(self, name):
        if name not in self._tab_names:
            return
        self._current = name
        self._refresh_button()


def _code_from_mime(mime):
    """Python text from a drop, or None when the drop is not code."""
    if mime is None:
        return None
    if mime.hasText():
        return mime.text()
    if mime.hasUrls():
        chunks = []
        for url in mime.urls():
            path = url.toLocalFile()
            if not path or not os.path.isfile(path):
                continue
            if os.path.splitext(path)[1].lower() not in (".py", ".txt"):
                continue
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    chunks.append(handle.read())
            except Exception:
                continue
        if chunks:
            return "\n\n".join(chunks)
    return None


class _AddActionDialog(QDialog):
    """Create one shelf button, or one menu button, from Python code."""

    def __init__(self, parent=None, command=""):
        super(_AddActionDialog, self).__init__(parent)
        self.setWindowTitle("Add Action/Menu to shelf")
        self.resize(640, 460)
        self.setMinimumSize(520, 360)
        self.setStyleSheet(EDITOR_STYLE)
        self._menu_items = []
        self._suppress = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(8)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Tool name")
        form.addRow("Name", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItem("Button", "button")
        self.type_combo.addItem("Menu", "menu")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("Type", self.type_combo)

        icon_row = QHBoxLayout()
        self.icon_path = QLineEdit()
        self.icon_path.setPlaceholderText("optional icon")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_icon)
        icon_row.addWidget(self.icon_path, 1)
        icon_row.addWidget(browse)
        form.addRow("Icon", icon_row)
        root.addLayout(form)

        self.command_edit = QTextEdit()
        self.command_edit.setAcceptRichText(False)
        self.command_edit.setPlaceholderText(
            "# Python. Available names include scriptNode, Gaffer, GafferUI."
        )
        self.command_edit.setPlainText(command or "")
        root.addWidget(self.command_edit, 1)

        self.menu_panel = QWidget()
        menu_layout = QVBoxLayout(self.menu_panel)
        menu_layout.setContentsMargins(0, 0, 0, 0)
        menu_layout.setSpacing(6)
        menu_body = QHBoxLayout()
        menu_layout.addLayout(menu_body, 1)
        menu_left = QVBoxLayout()
        self.menu_list = QListWidget()
        self.menu_list.currentRowChanged.connect(self._on_menu_row)
        menu_left.addWidget(self.menu_list, 1)
        menu_btns = QHBoxLayout()
        add_item = QPushButton("Add")
        add_item.clicked.connect(self._add_menu_item)
        remove_item = QPushButton("Remove")
        remove_item.clicked.connect(self._remove_menu_item)
        menu_btns.addWidget(add_item)
        menu_btns.addWidget(remove_item)
        menu_left.addLayout(menu_btns)
        menu_body.addLayout(menu_left, 1)
        menu_right = QVBoxLayout()
        self.menu_label = QLineEdit()
        self.menu_label.setPlaceholderText("Menu item label")
        self.menu_label.textChanged.connect(self._on_menu_fields)
        self.menu_command = QTextEdit()
        self.menu_command.setAcceptRichText(False)
        self.menu_command.setPlaceholderText("# Python for this menu item")
        self.menu_command.textChanged.connect(self._on_menu_fields)
        menu_right.addWidget(self.menu_label)
        menu_right.addWidget(self.menu_command, 1)
        menu_body.addLayout(menu_right, 2)
        root.addWidget(self.menu_panel, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("PrimaryButton")
        buttons.button(QDialogButtonBox.Ok).setText("Add")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        if command and command.strip():
            self._menu_items.append({
                "label": "Run",
                "command": command,
            })
        self._on_type_changed()
        self.name_edit.setFocus()

    def _browse_icon(self):
        path = _pick_existing_file(
            self,
            "Select Shelf Icon",
            user_icons_dir(),
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.svg);;All Files (*)",
        )
        if not path:
            return
        stored = _import_icon_to_user(path)
        if stored:
            self.icon_path.setText(stored)

    def _on_type_changed(self, *_args):
        is_menu = self.type_combo.currentData() == "menu"
        self.command_edit.setVisible(not is_menu)
        self.menu_panel.setVisible(is_menu)
        if is_menu and not self._menu_items:
            self._menu_items.append({
                "label": "Run",
                "command": self.command_edit.toPlainText(),
            })
        if is_menu:
            self._rebuild_menu_list(0)

    def _rebuild_menu_list(self, select_row=None):
        self._suppress = True
        self.menu_list.clear()
        for item in self._menu_items:
            self.menu_list.addItem(QListWidgetItem(item.get("label") or "Item"))
        self._suppress = False
        if self._menu_items:
            row = 0 if select_row is None else select_row
            row = max(0, min(row, len(self._menu_items) - 1))
            self.menu_list.setCurrentRow(row)
        else:
            self.menu_label.clear()
            self.menu_command.clear()

    def _on_menu_row(self, row):
        if self._suppress:
            return
        if row < 0 or row >= len(self._menu_items):
            return
        item = self._menu_items[row]
        self._suppress = True
        self.menu_label.setText(item.get("label") or "")
        self.menu_command.setPlainText(item.get("command") or "")
        self._suppress = False

    def _on_menu_fields(self, *_args):
        if self._suppress:
            return
        row = self.menu_list.currentRow()
        if row < 0 or row >= len(self._menu_items):
            return
        label = self.menu_label.text().strip() or "Item"
        self._menu_items[row]["label"] = label
        self._menu_items[row]["command"] = self.menu_command.toPlainText()
        current = self.menu_list.item(row)
        if current is not None:
            current.setText(label)

    def _add_menu_item(self):
        self._menu_items.append({"label": "Item", "command": ""})
        self._rebuild_menu_list(len(self._menu_items) - 1)
        self.menu_label.setFocus()
        self.menu_label.selectAll()

    def _remove_menu_item(self):
        row = self.menu_list.currentRow()
        if row < 0 or row >= len(self._menu_items):
            return
        del self._menu_items[row]
        self._rebuild_menu_list(min(row, len(self._menu_items) - 1))

    def action_definition(self, existing_ids):
        label = self.name_edit.text().strip() or "Tool"
        action = {
            "id": _action_id_from_label(label, existing_ids),
            "label": label,
            "tooltip": label,
        }
        icon = self.icon_path.text().strip()
        if icon:
            action["icon"] = icon
        if self.type_combo.currentData() == "menu":
            items = []
            for item in self._menu_items:
                item_label = (item.get("label") or "Item").strip() or "Item"
                items.append({
                    "id": _action_id_from_label(item_label, [i.get("id") for i in items]),
                    "label": item_label,
                    "command": item.get("command") or "",
                })
            if not items:
                items.append({
                    "id": "run",
                    "label": "Run",
                    "command": self.command_edit.toPlainText(),
                })
            action["menu"] = items
        else:
            action["command"] = self.command_edit.toPlainText()
        return action


class _ShelfBar(QWidget):
    """Grip + left tab selector + toolbar for the active shelf."""

    def __init__(self, scriptNode, dockCallback, shelves=None):
        super(_ShelfBar, self).__init__()
        self.__scriptNode = scriptNode
        self.__dockCallback = dockCallback
        self.__shelves = {s["name"]: s for s in (shelves or load_all_shelves())}
        self.__shelf_order = [s["name"] for s in (shelves or list(self.__shelves.values()))]
        if not self.__shelf_order:
            self.__shelf_order = list(DEFAULT_TAB_ORDER)
        self.__shelf_state = {"bbox_depth": 1000}
        self.__current = self.__shelf_order[0]

        self.setObjectName("StimShelfBar")
        self.setWindowTitle("sdvTk Shelf")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.grip = QToolButton()
        self.grip.setText("\u22ee\u22ee")
        self.grip.setAutoRaise(True)
        self.grip.setToolTip("Click to undock / re-dock the shelf")
        root.addWidget(self.grip)

        self.tab_selector = _TabSelector(self.__shelf_order, self, current=self.__current)
        self.tab_selector.tabChanged.connect(self.set_tab)
        self.tab_selector.accentChanged.connect(self._apply_accent)
        self.tab_selector.createLocalRequested.connect(self.create_local_shelf)
        self.tab_selector.editLocalRequested.connect(self.edit_local_shelf)
        self.tab_selector.deleteLocalRequested.connect(self.delete_local_shelf)
        root.addWidget(self.tab_selector)

        self._apply_accent(get_accent_color())

        self.shelf = QToolBar("Shelf", self)
        self.shelf.setIconSize(QSize(SHELF_ICON_SIZE, SHELF_ICON_SIZE))
        self.shelf.setMovable(False)
        self.shelf.setToolTip("Drop Python here, or right-click, to add a shelf button")
        root.addWidget(self.shelf, 1)

        self._arm_drop_target(self)
        self._arm_drop_target(self.grip)
        self._arm_drop_target(self.shelf)
        self._rebuild_actions()

    def _apply_accent(self, color=None):
        accent = color or get_accent_color()
        self.setStyleSheet(shelf_style(accent))
        self.grip.setStyleSheet(
            "QToolButton { border: none; background: #252525; color: #888; padding: 8px 4px; }"
            "QToolButton:hover { color: %s; }" % accent
        )

    @property
    def shelf_state(self):
        return self.__shelf_state

    def closeEvent(self, event):
        if self.isWindow() and self.__dockCallback:
            event.ignore()
            self.__dockCallback()
        else:
            event.accept()

    def set_tab(self, name):
        if name not in self.__shelves and name not in self.__shelf_order:
            return
        self.__current = name
        self.tab_selector.setCurrent(name)
        self._rebuild_actions()

    def reload_definitions(self, select_name=None):
        shelves = load_all_shelves()
        self.__shelves = {s["name"]: s for s in shelves}
        self.__shelf_order = [s["name"] for s in shelves] or list(DEFAULT_TAB_ORDER)
        if select_name and select_name in self.__shelves:
            self.__current = select_name
        elif self.__current not in self.__shelves:
            self.__current = self.__shelf_order[0]
        self.tab_selector.setTabs(self.__shelf_order, current=self.__current)
        self._rebuild_actions()

    def create_local_shelf(self):
        parent = self.window() or self
        existing = list(self.__shelves.keys()) + list_user_shelf_names()
        name_dlg = _ShelfNameDialog(parent, existing_names=existing)
        if _dialog_exec(name_dlg) != QDialog.Accepted:
            return
        shelf_name = name_dlg.shelf_name()
        try:
            save_user_shelf_data(shelf_name, {
                "name": shelf_name,
                "label": shelf_name,
                "order": 200,
                "actions": [],
            })
        except Exception as e:
            QMessageBox.critical(parent, "Create Failed", str(e))
            return

        editor = _LocalShelfEditorDialog(shelf_name, parent)
        _dialog_exec(editor)
        if getattr(editor, "deleted", False):
            self.reload_definitions()
        else:
            self.reload_definitions(select_name=shelf_name)

    def edit_local_shelf(self, shelf_name):
        if not shelf_name:
            return
        parent = self.window() or self
        if not os.path.isfile(user_shelf_json_path(shelf_name)):
            QMessageBox.warning(
                parent,
                "Missing Shelf",
                "No local JSON found for '%s'." % shelf_name,
            )
            return
        editor = _LocalShelfEditorDialog(shelf_name, parent)
        result = _dialog_exec(editor)
        if getattr(editor, "deleted", False):
            self.reload_definitions()
        elif result == QDialog.Accepted:
            self.reload_definitions(select_name=shelf_name)

    def delete_local_shelf(self, shelf_name):
        if not shelf_name:
            return
        parent = self.window() or self
        path = user_shelf_json_path(shelf_name)
        if not os.path.isfile(path):
            QMessageBox.warning(
                parent,
                "Missing Shelf",
                "No local JSON found for '%s'." % shelf_name,
            )
            return
        reply = QMessageBox.question(
            parent,
            "Delete Shelf",
            "Delete local shelf '%s'?\n\nThis will remove:\n%s" % (shelf_name, path),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            delete_user_shelf(shelf_name)
        except Exception as e:
            QMessageBox.critical(parent, "Delete Failed", str(e))
            return
        self.reload_definitions()

    def _arm_drop_target(self, widget):
        if widget is None or widget.property("_sdvtkDrop"):
            return
        widget.setProperty("_sdvtkDrop", True)
        widget.setAcceptDrops(True)
        widget.installEventFilter(self)

    def _arm_shelf_drops(self):
        self._arm_drop_target(self.shelf)
        for widget in self.shelf.findChildren(QWidget):
            self._arm_drop_target(widget)

    def eventFilter(self, obj, event):
        et = event.type()
        if et in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove):
            if _code_from_mime(event.mimeData()) is not None:
                event.acceptProposedAction()
                return True
            return False
        if et == QtCore.QEvent.Drop:
            code = _code_from_mime(event.mimeData())
            if code is None:
                return False
            self.add_action_from_code(code)
            event.acceptProposedAction()
            return True
        if et == QtCore.QEvent.ContextMenu:
            self._show_add_menu(event.globalPos())
            return True
        return super(_ShelfBar, self).eventFilter(obj, event)

    def _show_add_menu(self, global_pos):
        menu = QMenu(self)
        add_act = menu.addAction("Add Action/Menu to shelf")
        chosen = _menu_exec_at(menu, global_pos)
        if chosen is add_act:
            self.add_action_from_code("")

    def add_action_from_code(self, code):
        parent = self.window() or self
        dialog = _AddActionDialog(parent, command=code or "")
        if _dialog_exec(dialog) != QDialog.Accepted:
            return
        shelf_name = self.__current or "sdvTk"
        try:
            data = load_user_shelf_data(shelf_name)
        except Exception as error:
            QMessageBox.critical(parent, "Add Failed", str(error))
            return
        existing = [a.get("id") for a in (data.get("actions") or [])]
        action = dialog.action_definition(existing)
        data.setdefault("actions", []).append(action)
        try:
            save_user_shelf_data(shelf_name, data)
        except Exception as error:
            QMessageBox.critical(parent, "Add Failed", str(error))
            return
        self.reload_definitions(select_name=shelf_name)

    def _rebuild_actions(self):
        self.shelf.clear()

        shelf = self.__shelves.get(self.__current)
        if not shelf:
            return

        # Shelf-specific tools, then shared right-side tools on every tab
        actions = [
            a for a in (shelf.get("actions") or [])
            if a.get("id") not in SHARED_RIGHT_SHELF_IDS
        ]
        actions.extend(SHARED_RIGHT_SHELF_ACTIONS)

        right_spacer_added = False

        for defn in actions:
            # Same gate as GafferPipe.env.dev_mode() — STIM_DEV=1
            if defn.get("dev_only") and os.getenv("STIM_DEV") != "1":
                continue

            if defn.get("align") == "right" and not right_spacer_added:
                spacer = QWidget()
                spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                self.shelf.addWidget(spacer)
                right_spacer_added = True

            builtin = defn.get("builtin")
            if builtin and builtin in BUILTINS:
                widget = BUILTINS[builtin](
                    self.shelf, self.__scriptNode, shelf, self.__shelf_state, defn,
                )
                self.shelf.addWidget(widget)
                continue

            hold_items = defn.get("hold") or []
            if hold_items:
                widget = _build_hold_flyout_button(
                    self.shelf, self.__scriptNode, shelf, self.__shelf_state, defn,
                )
                self.shelf.addWidget(widget)
                continue

            btn = QToolButton(self.shelf)
            _square_shelf_button(btn)
            icon = resolve_icon(defn.get("icon"), shelf, btn)
            label = defn.get("label") or defn.get("id") or "?"
            menu_items = defn.get("menu") or []
            if defn.get("icon") and not icon.isNull():
                btn.setIcon(icon)
            else:
                btn.setText(label)
            tip = defn.get("tooltip") or defn.get("label") or ""
            btn.setToolTip(tip)
            if defn.get("checkable"):
                btn.setCheckable(True)
                btn.setChecked(bool(defn.get("checked", False)))

            if menu_items:
                # Same look as a normal shelf button; click → context menu
                menu = QMenu(btn)
                groups = {}
                for item in menu_items:
                    if item.get("separator"):
                        menu.addSeparator()
                        continue
                    item_label = item.get("label") or item.get("id") or "Item"
                    act = menu.addAction(item_label)
                    # Non-clickable section header (e.g. menu title)
                    if item.get("title") or item.get("header"):
                        act.setEnabled(False)
                        font = act.font()
                        font.setBold(True)
                        act.setFont(font)
                        continue
                    if item.get("enabled") is False:
                        act.setEnabled(False)
                    tip = item.get("tooltip") or ""
                    if tip:
                        act.setToolTip(tip)
                    if item.get("checkable"):
                        act.setCheckable(True)
                        act.setChecked(bool(item.get("checked", False)))
                    if "data" in item:
                        act.setData(item["data"])
                    group_name = item.get("group")
                    if group_name:
                        if group_name not in groups:
                            groups[group_name] = QActionGroup(menu)
                            groups[group_name].setExclusive(True)
                        groups[group_name].addAction(act)

                    def _make_handler(item_defn, act_ref):
                        def _handler(checked=False):
                            data = item_defn["data"] if "data" in item_defn else act_ref.data()
                            invoke_action(
                                item_defn, self.__scriptNode, shelf,
                                button=btn, qt_action=act_ref,
                                data=data,
                                shelf_state=self.__shelf_state,
                            )
                        return _handler

                    act.triggered.connect(_make_handler(item, act))

                def _make_menu_click(menu_ref, button_ref):
                    def _click(checked=False):
                        # Context-menu style under the button (not a combo dropdown)
                        pos = button_ref.mapToGlobal(button_ref.rect().bottomLeft())
                        _menu_exec_at(menu_ref, pos)
                    return _click

                btn.clicked.connect(_make_menu_click(menu, btn))
            else:
                def _make_click(action_defn):
                    def _click(checked=False):
                        invoke_action(
                            action_defn, self.__scriptNode, shelf,
                            button=btn, shelf_state=self.__shelf_state,
                        )
                    return _click

                btn.clicked.connect(_make_click(defn))

            self.shelf.addWidget(btn)

        self._arm_shelf_drops()


class _ShelfHost(QWidget):
    """Keeps a slot under the menu bar; collapses while the shelf floats."""

    def __init__(self, scriptWindow, shelves=None):
        super(_ShelfHost, self).__init__()
        self.__scriptWindow = scriptWindow
        self.__layout = QHBoxLayout(self)
        self.__layout.setContentsMargins(0, 0, 0, 0)
        self.__layout.setSpacing(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.bar = _ShelfBar(scriptWindow.scriptNode(), self.dock, shelves=shelves)
        self.bar.grip.clicked.connect(self.toggleFloating)
        self.__layout.addWidget(self.bar)
        self.__floating = False

    def toggleFloating(self):
        if self.__floating:
            self.dock()
        else:
            self.undock()

    def undock(self):
        if self.__floating:
            return
        self.__floating = True
        self.__layout.removeWidget(self.bar)
        parent = self.__scriptWindow._qtWidget()
        self.bar.setParent(parent, QtCore.Qt.Tool)
        self.bar.resize(max(self.bar.sizeHint().width() + 20, 320), self.bar.sizeHint().height() + 8)
        pos = self.mapToGlobal(QtCore.QPoint(40, 40))
        self.bar.move(pos)
        self.bar.show()
        self.setVisible(False)

    def dock(self):
        if not self.__floating:
            return
        self.__floating = False
        self.bar.hide()
        self.bar.setParent(self, QtCore.Qt.Widget)
        self.__layout.addWidget(self.bar)
        self.bar.show()
        self.setVisible(True)

    def is_shown(self):
        if self.__floating:
            return self.bar.isVisible()
        return self.isVisible()

    def show_shelf(self):
        if self.__floating:
            self.bar.show()
            self.bar.raise_()
            return
        self.bar.show()
        self.setVisible(True)

    def hide_shelf(self):
        if self.__floating:
            self.bar.hide()
        self.setVisible(False)

    def shutdown(self):
        if self.__floating:
            self.bar.setParent(None)
            self.bar.deleteLater()


# ------------------------------------------------------------------------------
# Install
# ------------------------------------------------------------------------------

def _print_shelf_install_done(shelves):
    names = ", ".join(s.get("name") or "?" for s in (shelves or []))
    if names:
        print("[Shelf] Shelf install done : %s" % names)
    else:
        print("[Shelf] Shelf install done : (no tabs)")


def install_in_window(scriptWindow, shelves=None):
    if getattr(scriptWindow, "_sdvtk_shelf_host", None) is not None:
        return True

    loaded = shelves if shelves is not None else load_all_shelves()

    child = scriptWindow.getChild()
    if not isinstance(child, GafferUI.ListContainer):
        central = scriptWindow._qtWidget().centralWidget()
        layout = central.layout() if central is not None else None
        if layout is None:
            return False
        host = _ShelfHost(scriptWindow, shelves=loaded)
        layout.insertWidget(1, host)
        scriptWindow._sdvtk_shelf_host = host
        _print_shelf_install_done(loaded)
        return True

    # Do not insert through Gaffer ListContainer API — ScriptWindow indexes
    # the editor layout as Python child [1]. Insert only at the Qt level.
    qtLayout = child._qtWidget().layout()
    if qtLayout is None:
        return False

    index = 1
    for c in child:
        if isinstance(c, GafferUI.MenuBar):
            found = qtLayout.indexOf(c._qtWidget())
            if found >= 0:
                index = found + 1
            break

    host = _ShelfHost(scriptWindow, shelves=loaded)
    qtLayout.insertWidget(index, host)
    scriptWindow._sdvtk_shelf_host = host
    try:
        scriptWindow.closedSignal().connect(lambda w: host.shutdown(), scoped=False)
    except Exception:
        pass
    _print_shelf_install_done(loaded)
    return True


def _on_window_created(scriptWindow, _tries=None):
    def attempt(tries=0):
        try:
            if install_in_window(scriptWindow):
                return
        except Exception as e:
            print("[Shelf] Install failed: %s" % e)
            traceback.print_exc()
            return
        if tries < 10:
            QtCore.QTimer.singleShot(100, lambda: attempt(tries + 1))

    attempt()


# ------------------------------------------------------------------------------
# Public install (called from startup/gui/init_ui.py)
# ------------------------------------------------------------------------------

def _script_windows():
    """Live script windows. ``ScriptWindow`` has no public ``instances()``."""
    return [o for o in gc.get_objects() if isinstance(o, GafferUI.ScriptWindow)]


def shelf_host(scriptWindow):
    return getattr(scriptWindow, "_sdvtk_shelf_host", None)


def shelf_is_shown(scriptWindow):
    host = shelf_host(scriptWindow)
    return host is not None and host.is_shown()


def show_shelf(scriptWindow):
    host = shelf_host(scriptWindow)
    if host is not None:
        host.show_shelf()


def hide_shelf(scriptWindow):
    host = shelf_host(scriptWindow)
    if host is not None:
        host.hide_shelf()


def install(application=None):
    """Register the sdvTk shelf on every script window."""
    GafferUI.ScriptWindow.instanceCreatedSignal().connect(_on_window_created, scoped=False)
    for window in _script_windows():
        _on_window_created(window)
