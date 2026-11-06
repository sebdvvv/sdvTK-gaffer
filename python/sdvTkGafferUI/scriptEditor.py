"""Optional swap of Gaffer's Python Editor for pw_MultiScriptEditor.

The preference is off until the user checks it. The package folder is a
preference too (sdvTk → Options). On the next launch, startup puts that
folder on ``PYTHONPATH`` and registers the panel as ``GafferUI.PythonEditor``.
Layouts keep the name Python Editor.

The package is https://github.com/sebdvvv/pw_MultiScriptEditor.
"""

from __future__ import annotations

import os
import sys

import GafferUI
import IECore

_SWAPPED = False
_UNDER_GRAPH = False
_RATIO = 0.22


def install(application=None) -> bool:
    from sdvTkGafferUI import prefs

    if not prefs.use_multi_script_editor():
        return False
    apply_environment()
    if not _swap():
        return False
    _install_under_graph()
    return True


def apply_environment() -> str | None:
    """Put the preferred pw_MultiScriptEditor folder on ``sys.path`` and ``PYTHONPATH``."""
    from sdvTkGafferUI import prefs

    parent = prefs.locate_multi_script_editor()
    if not parent:
        return None
    if parent not in sys.path:
        sys.path.insert(0, parent)
    current = os.environ.get("PYTHONPATH", "")
    parts = [part for part in current.split(os.pathsep) if part]
    if parent not in parts:
        os.environ["PYTHONPATH"] = parent if not current else parent + os.pathsep + current
    return parent


def package_importable() -> bool:
    apply_environment()
    try:
        import multi_script_editor.managers._gaffer  # noqa: F401
    except Exception:
        return False
    return True


def _swap() -> bool:
    global _SWAPPED
    if _SWAPPED:
        return True
    try:
        from Qt import QtCore

        QtCore.QLoggingCategory.setFilterRules("qt.qpa.mime.warning=false")
    except Exception:
        pass
    try:
        import logging

        for name in ("parso", "parso.cache", "jedi"):
            logging.getLogger(name).setLevel(logging.WARNING)
        import multi_script_editor.managers._gaffer as mse
    except Exception as exc:
        from sdvTkGafferUI import prefs
        from sdvTkGafferUI.prefs import MSE_GITHUB

        folder = prefs.multi_script_editor_folder().strip()
        where = (
            "The folder set in sdvTk → Options is {}.".format(folder)
            if folder
            else "Set the pw_MultiScriptEditor folder in sdvTk → Options."
        )
        IECore.msg(
            IECore.Msg.Level.Error,
            "sdvTk",
            "Python Editor stays stock. import multi_script_editor failed: {}. "
            "{} {}".format(exc, where, MSE_GITHUB),
        )
        return False

    class _PythonEditor(mse.MultiScriptEditor):
        def getTitle(self):
            title = GafferUI.Editor.getTitle(self)
            return title if title else "Python Editor"

        def __repr__(self):
            return "GafferUI.PythonEditor( scriptNode )"

    GafferUI.Editor.registerType("PythonEditor", _PythonEditor)
    GafferUI.PythonEditor = _PythonEditor
    if hasattr(GafferUI, "CompoundEditor") and hasattr(GafferUI.CompoundEditor, "registerType"):
        try:
            GafferUI.CompoundEditor.registerType("PythonEditor", _PythonEditor)
        except Exception:
            pass
    _SWAPPED = True
    IECore.msg(
        IECore.Msg.Level.Info,
        "sdvTk",
        "Python Editor is pw_MultiScriptEditor.",
    )
    return True


def _find_editor(layout, editor_type):
    try:
        return layout.editor(editor_type, focussedOnly=False, visibleOnly=False)
    except Exception:
        return None


def _graph_leaf(graph):
    tabbed = graph.parent()
    if tabbed is None:
        return None, None
    leaf = tabbed.parent()
    if leaf is None or not hasattr(leaf, "split"):
        return None, None
    return leaf, tabbed


def _tabbed_of(split_container):
    if split_container is None:
        return None
    if hasattr(split_container, "isSplit") and split_container.isSplit():
        return None
    try:
        child = split_container[0]
    except Exception:
        return None
    if child is not None and hasattr(child, "addEditor"):
        return child
    return None


def _ensure_bottom(layout):
    graph = _find_editor(layout, GafferUI.GraphEditor)
    if graph is None:
        return None
    leaf, _tabbed = _graph_leaf(graph)
    if leaf is None:
        return None
    try:
        parent = leaf.parent()
    except Exception:
        parent = None
    if (
        parent is not None
        and hasattr(parent, "isSplit")
        and parent.isSplit()
        and parent.getOrientation() == GafferUI.SplitContainer.Orientation.Vertical
        and parent[0] is leaf
    ):
        return _tabbed_of(parent[1])
    if hasattr(leaf, "isSplit") and leaf.isSplit():
        return None
    try:
        leaf.split(GafferUI.SplitContainer.Orientation.Vertical, 1)
        leaf.setSizes([1.0 - _RATIO, _RATIO])
    except Exception as exc:
        print("[sdvTk] Split Bottom on Graph Editor failed: {}".format(exc))
        return None
    return _tabbed_of(leaf[1])


def _dock(script_window) -> bool:
    try:
        layout = script_window.getLayout()
    except Exception:
        return False
    if layout is None:
        return False
    bottom = _ensure_bottom(layout)
    if bottom is None:
        return False
    editor = _find_editor(layout, GafferUI.PythonEditor)
    if editor is None:
        try:
            editor = GafferUI.PythonEditor(script_window.scriptNode())
        except Exception as exc:
            print("[sdvTk] Could not create Python Editor: {}".format(exc))
            return False
    if editor.parent() is bottom:
        return True
    try:
        bottom.addEditor(editor)
    except Exception as exc:
        print("[sdvTk] Could not dock Python Editor: {}".format(exc))
        return False
    return True


def _install_under_graph() -> None:
    global _UNDER_GRAPH
    if _UNDER_GRAPH:
        return
    _UNDER_GRAPH = True
    from Qt import QtCore

    def _on_window(script_window):
        def attempt(tries=0):
            try:
                layout = script_window.getLayout()
            except Exception:
                layout = None
            graph = _find_editor(layout, GafferUI.GraphEditor) if layout is not None else None
            if graph is not None or tries >= 12:
                if _dock(script_window):
                    return
            if tries < 20:
                QtCore.QTimer.singleShot(100, lambda: attempt(tries + 1))

        QtCore.QTimer.singleShot(0, lambda: attempt(0))

    GafferUI.ScriptWindow.instanceCreatedSignal().connect(_on_window, scoped=False)
    try:
        for window in GafferUI.ScriptWindow.instances():
            _on_window(window)
    except Exception:
        pass
