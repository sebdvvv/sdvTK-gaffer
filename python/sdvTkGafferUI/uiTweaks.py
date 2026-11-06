"""Graph and editor tweaks driven by sdvTk preferences.

- Middle-click closes a layout tab
- Double-click can enter Box / Reference / EditScope contents
- Graph Editor node menu can show root and history-back
"""

from __future__ import annotations

import traceback

import Gaffer
import GafferUI

_FILTER = None
_DOUBLE_CLICK_CONNECTED = False
_NAV_INSTALLED = False
_APP_ROOT = None

_NAV_ROOT_PATH = "/__sdvTkNavRoot"
_NAV_BACK_PATH = "/__sdvTkNavBack"
_NAV_DIVIDER_PATH = "/__sdvTkNavDivider"
_NAV_BACK_LABEL = "◀"
_NAV_ROOT_LABEL = "/"


def install(application=None) -> None:
    _install_middle_click_tabs()
    _install_graph_double_click()
    _install_node_menu_navigation(application)
    _install_unsaved_dialog_button_order()


def _event_pos(event):
    if hasattr(event, "position"):
        try:
            return event.position().toPoint()
        except Exception:
            pass
    return event.pos()


def _tabbed_container_for_bar(q_tab_bar):
    from Qt import QtWidgets

    widget = q_tab_bar.parent()
    while widget is not None and not isinstance(widget, QtWidgets.QTabWidget):
        widget = widget.parent()
    if widget is None:
        return None
    try:
        owner = GafferUI.Widget._owner(widget)
    except Exception:
        return None
    if owner is not None and callable(getattr(owner, "removeEditor", None)):
        return owner
    return None


class _MiddleClickTabCloseFilter:
    """Installed as a QObject below, once Qt is imported."""


def _install_middle_click_tabs() -> None:
    global _FILTER
    if _FILTER is not None:
        return
    from Qt import QtCore
    from Qt import QtWidgets

    class _Filter(QtCore.QObject):
        def eventFilter(self, obj, event):
            if event.type() != QtCore.QEvent.MouseButtonPress:
                return False
            if event.button() != QtCore.Qt.MiddleButton:
                return False
            if not isinstance(obj, QtWidgets.QTabBar):
                return False
            container = _tabbed_container_for_bar(obj)
            if container is None:
                return False
            index = obj.tabAt(_event_pos(event))
            if index < 0 or index >= len(container):
                return False
            try:
                container.removeEditor(container[index])
            except Exception as exc:
                print("[sdvTk] Middle-click tab close failed: {}".format(exc))
                return False
            return True

    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    _FILTER = _Filter(app)
    app.installEventFilter(_FILTER)


def _children_viewable(node) -> bool:
    for key in (
        "ui:childNodesAreViewable",
        "graphEditor:childrenViewable",
        "nodeGraph:childrenViewable",
    ):
        value = Gaffer.Metadata.value(node, key)
        if value is not None:
            return bool(value)
    return False


def _ctrl_held() -> bool:
    from Qt import QtCore
    from Qt import QtWidgets

    app = QtWidgets.QApplication.instance()
    if app is None:
        return False
    return bool(app.keyboardModifiers() & QtCore.Qt.ControlModifier)


def _on_node_double_click(graph_editor, node):
    from sdvTkGafferUI import prefs

    if not prefs.double_click_enter_contents():
        return False
    if prefs.ctrl_double_click_node_editor() and _ctrl_held():
        if node is not None:
            GafferUI.NodeEditor.acquire(node, floating=True)
        return True
    if node is None or not _children_viewable(node):
        return False
    gadget = graph_editor.graphGadget()
    if node.parent() is None or not node.parent().isSame(gadget.getRoot()):
        return False
    if prefs.show_contents_single_pane():
        gadget.setRoot(node)
    else:
        GafferUI.GraphEditor.acquire(node)
    return True


def _connect_graph_editor_double_click(graph_editor) -> None:
    try:
        graph_editor.nodeDoubleClickSignal().connect(_on_node_double_click, scoped=False)
    except Exception:
        traceback.print_exc()


def _install_graph_double_click() -> None:
    global _DOUBLE_CLICK_CONNECTED
    if _DOUBLE_CLICK_CONNECTED:
        return
    GafferUI.GraphEditor.instanceCreatedSignal().connect(
        _connect_graph_editor_double_click, scoped=False
    )
    try:
        GafferUI.GraphEditor.nodeDoubleClickSignal().connect(0, _on_node_double_click, scoped=False)
    except TypeError:
        pass
    _DOUBLE_CLICK_CONNECTED = True


def _resolve_application_root(application=None):
    if application is None:
        return _APP_ROOT
    try:
        if isinstance(application, Gaffer.ApplicationRoot):
            return application
        return application.root()
    except Exception:
        return _APP_ROOT


def _graph_editor_from_menu(menu):
    try:
        return menu.ancestor(GafferUI.GraphEditor)
    except Exception:
        return None


def _node_menu_go_root(menu) -> None:
    from sdvTkGafferUI import prefs

    if not prefs.graph_view_nav_menu():
        return
    graph_editor = _graph_editor_from_menu(menu)
    if graph_editor is None:
        return
    graph_editor.graphGadget().setRoot(graph_editor.scriptNode())


def _node_menu_go_back(menu) -> None:
    from sdvTkGafferUI import prefs

    if not prefs.graph_view_nav_menu():
        return
    graph_editor = _graph_editor_from_menu(menu)
    if graph_editor is None:
        return
    history = getattr(graph_editor, "_GraphEditor__historyWidget", None)
    if history is None:
        root = graph_editor.graphGadget().getRoot()
        if not isinstance(root, Gaffer.ScriptNode) and root.parent() is not None:
            graph_editor.graphGadget().setRoot(root.parent())
        return
    history.moveHistoryIndex(history.Direction.Back)


def _node_menu_root_active(menu) -> bool:
    from sdvTkGafferUI import prefs

    if not prefs.graph_view_nav_menu():
        return False
    graph_editor = _graph_editor_from_menu(menu)
    if graph_editor is None:
        return False
    return not graph_editor.graphGadget().getRoot().isSame(graph_editor.scriptNode())


def _node_menu_back_active(menu) -> bool:
    from sdvTkGafferUI import prefs

    if not prefs.graph_view_nav_menu():
        return False
    graph_editor = _graph_editor_from_menu(menu)
    if graph_editor is None:
        return False
    history = getattr(graph_editor, "_GraphEditor__historyWidget", None)
    if history is None:
        root = graph_editor.graphGadget().getRoot()
        return not isinstance(root, Gaffer.ScriptNode)
    try:
        button = getattr(history, "_HistoryWidget__backButton", None)
        if button is not None:
            return bool(button.getEnabled())
    except Exception:
        pass
    root = graph_editor.graphGadget().getRoot()
    return not isinstance(root, Gaffer.ScriptNode)


def _strip_nav(definition) -> None:
    for path in (_NAV_ROOT_PATH, _NAV_BACK_PATH, _NAV_DIVIDER_PATH):
        try:
            definition.remove(path, raiseIfMissing=False)
        except TypeError:
            try:
                definition.remove(path)
            except Exception:
                pass
        except Exception:
            pass


def _add_nav(definition) -> None:
    _strip_nav(definition)
    definition.prepend(_NAV_DIVIDER_PATH, {"divider": True})
    definition.prepend(
        _NAV_ROOT_PATH,
        {
            "label": _NAV_ROOT_LABEL,
            "command": _node_menu_go_root,
            "active": _node_menu_root_active,
            "description": "Go to script root",
        },
    )
    definition.prepend(
        _NAV_BACK_PATH,
        {
            "label": _NAV_BACK_LABEL,
            "command": _node_menu_go_back,
            "active": _node_menu_back_active,
            "description": "Go back in Graph Editor history",
        },
    )


def sync_graph_view_nav_menu(application=None) -> None:
    global _APP_ROOT
    from sdvTkGafferUI import prefs

    app_root = _resolve_application_root(application)
    if app_root is None:
        return
    _APP_ROOT = app_root
    definition = GafferUI.NodeMenu.acquire(app_root).definition()
    if prefs.graph_view_nav_menu():
        _add_nav(definition)
    else:
        _strip_nav(definition)


_UNSAVED_PATCHED = False
_NAV_HOOKED = False


def _install_unsaved_dialog_button_order() -> None:
    """Close dialog buttons: Cancel | Discard | Save (stock is Cancel | Save | Discard)."""
    global _UNSAVED_PATCHED
    if _UNSAVED_PATCHED:
        return

    def _accepts_close(self):
        import importlib
        import sys

        script = self.scriptNode()
        if not script["unsavedChanges"].getValue():
            return True
        filename = script["fileName"].getValue().replace("\\", "/")
        filename = filename.rpartition("/")[2] if filename else "untitled"
        sw_mod = sys.modules.get("GafferUI.ScriptWindow")
        if sw_mod is None:
            sw_mod = importlib.import_module("GafferUI.ScriptWindow")
        dialogue = sw_mod._ChoiceDialogue(
            "Discard Unsaved Changes?",
            'The file "{}" has unsaved changes. Do you want to discard them?'.format(filename),
            choices=["Cancel", "Discard", "Save"],
        )
        choice = dialogue.waitForChoice(parentWindow=self)
        if choice == "Discard":
            return True
        if choice == "Save":
            GafferUI.FileMenu.save(self.menuBar())
            return True
        return False

    GafferUI.ScriptWindow._acceptsClose = _accepts_close
    _UNSAVED_PATCHED = True


def _layout_nav_row(menu_widget) -> None:
    from Qt import QtGui
    from Qt import QtWidgets

    try:
        qt_menu = menu_widget._qtWidget()
    except Exception:
        return
    back_act = None
    root_act = None
    for action in qt_menu.actions():
        try:
            text = action.text()
        except Exception:
            continue
        if text == _NAV_BACK_LABEL:
            back_act = action
        elif text == _NAV_ROOT_LABEL:
            root_act = action
    if back_act is None or root_act is None:
        return
    actions = list(qt_menu.actions())
    last_idx = max(actions.index(back_act), actions.index(root_act))
    insert_before = actions[last_idx + 1] if last_idx + 1 < len(actions) else None
    row = QtWidgets.QWidget(qt_menu)
    lay = QtWidgets.QHBoxLayout(row)
    lay.setContentsMargins(8, 2, 8, 2)
    lay.setSpacing(2)
    style = (
        "QToolButton { color: #dfdfdf; background: transparent; border: none;"
        " padding: 2px 14px; min-width: 28px; }"
        "QToolButton:hover:!disabled { background-color: #5a4310; border-radius: 3px; }"
        "QToolButton:disabled { color: #666666; }"
    )
    font = QtGui.QFont(qt_menu.font())
    font.setBold(True)

    def _button(label, tip, enabled, command):
        button = QtWidgets.QToolButton(row)
        button.setText(label)
        button.setToolTip(tip)
        button.setFont(font)
        button.setAutoRaise(True)
        button.setEnabled(enabled)
        button.setStyleSheet(style)
        button.clicked.connect(lambda: (command(), qt_menu.hide()))
        return button

    lay.addWidget(
        _button(_NAV_BACK_LABEL, "Go back in Graph Editor history", back_act.isEnabled(), lambda: _node_menu_go_back(menu_widget)),
        1,
    )
    lay.addWidget(
        _button(_NAV_ROOT_LABEL, "Go to script root", root_act.isEnabled(), lambda: _node_menu_go_root(menu_widget)),
        1,
    )
    qt_menu.removeAction(back_act)
    qt_menu.removeAction(root_act)
    widget_action = QtWidgets.QWidgetAction(qt_menu)
    widget_action.setDefaultWidget(row)
    if insert_before is not None:
        qt_menu.insertAction(insert_before, widget_action)
    else:
        qt_menu.addAction(widget_action)


def _on_node_menu_visibility(menu_widget) -> None:
    if not menu_widget.visible():
        return
    from sdvTkGafferUI import prefs

    if not prefs.graph_view_nav_menu():
        return
    from Qt.QtCore import QTimer

    QTimer.singleShot(0, lambda m=menu_widget: _layout_nav_row(m))


def _hook_graph_editor_node_menu(graph_editor) -> None:
    try:
        menu = graph_editor._nodeMenu()
    except Exception:
        return
    try:
        menu.visibilityChangedSignal().connect(_on_node_menu_visibility, scoped=False)
    except Exception:
        traceback.print_exc()


def _install_node_menu_navigation(application=None) -> None:
    global _NAV_INSTALLED, _NAV_HOOKED, _APP_ROOT
    if not _NAV_HOOKED:
        GafferUI.GraphEditor.instanceCreatedSignal().connect(
            _hook_graph_editor_node_menu, scoped=False
        )
        _NAV_HOOKED = True
    app_root = _resolve_application_root(application)
    if app_root is not None:
        _APP_ROOT = app_root
        sync_graph_view_nav_menu(app_root)
        _NAV_INSTALLED = True
        return
    if _NAV_INSTALLED:
        return

    def _on_graph_editor(editor):
        try:
            root = editor.scriptNode().applicationRoot()
        except Exception:
            return
        sync_graph_view_nav_menu(root)

    GafferUI.GraphEditor.instanceCreatedSignal().connect(_on_graph_editor, scoped=False)
    _NAV_INSTALLED = True
