"""Minimal Node Editor helpers (no GafferPipe dependency)."""

from __future__ import annotations

import functools
from typing import Any

import Gaffer
import GafferUI
import IECore
import imath


def widget_is_alive(widget: Any) -> bool:
    if widget is None:
        return False
    try:
        return bool(GafferUI._qtObjectIsValid(widget._qtWidget()))
    except (RuntimeError, ReferenceError, AttributeError, TypeError):
        return False


def expand_h(widget: GafferUI.Widget) -> GafferUI.Widget:
    try:
        qt_widget = widget._qtWidget()
        policy = qt_widget.sizePolicy()
        expanding = getattr(policy, "Expanding", None)
        if expanding is None:
            from Qt import QtWidgets

            expanding = QtWidgets.QSizePolicy.Policy.Expanding
        policy.setHorizontalPolicy(expanding)
        qt_widget.setSizePolicy(policy)
    except Exception:
        pass
    return widget


def native_widget(plug: Any) -> GafferUI.PlugValueWidget:
    created = GafferUI.PlugValueWidget.create(plug)
    if created is not None:
        return created
    if isinstance(plug, Gaffer.BoolPlug):
        return GafferUI.BoolPlugValueWidget(plug)
    if isinstance(plug, (Gaffer.IntPlug, Gaffer.FloatPlug)):
        return GafferUI.NumericPlugValueWidget(plug)
    if isinstance(plug, Gaffer.StringVectorDataPlug):
        return GafferUI.VectorDataPlugValueWidget(plug)
    if isinstance(plug, Gaffer.TransformPlug):
        return GafferUI.TransformPlugValueWidget(plug)
    return GafferUI.StringPlugValueWidget(plug)


class ExistingLightsPlugValueWidget(GafferUI.PlugValueWidget):
    """Combo of lights found on the incoming scene (Edit mode)."""

    def __init__(self, plug: Any, **kw: Any) -> None:
        self._button = GafferUI.MenuButton(
            text="Select light…",
            menu=GafferUI.Menu(Gaffer.WeakMethod(self._menuDefinition)),
        )
        expand_h(self._button)
        GafferUI.PlugValueWidget.__init__(self, self._button, plug, **kw)

    def _updateFromValues(self, values: Any, exception: Any) -> None:
        value = values[0] if values else ""
        self._button.setText(str(value) if value else "Select light…")

    def _menuDefinition(self) -> IECore.MenuDefinition:
        md = IECore.MenuDefinition()
        plug = self.getPlug()
        node = plug.node() if plug is not None else None
        lights = []
        if node is not None and hasattr(node, "existingLights"):
            try:
                lights = list(node.existingLights())
            except Exception:
                lights = []
        if not lights:
            md.append("/No lights in incoming scene", {"active": False})
            return md
        current = plug.getValue() if plug is not None else ""
        plugs = tuple(self.getPlugs())
        for path in lights:
            md.append(
                path if path.startswith("/") else "/" + path,
                {
                    "command": functools.partial(_set_edit_path, plugs, path),
                    "checkBox": path == current,
                },
            )
        return md


def _set_edit_path(plugs, path: str, *unused: Any) -> None:
    script = plugs[0].ancestor(Gaffer.ScriptNode) if plugs else None
    with Gaffer.UndoScope(script):
        for plug in plugs:
            plug.setValue(path)


# Last Copy per node class name, so Paste works after selecting another light.
_VALUE_CLIPBOARD: dict[str, dict] = {}


class CardNodeWidget(GafferUI.Widget):
    """Top-anchored column of rows with a live ``plugDirtied`` connection."""

    _LABEL_W = 150

    def __init__(self, node: Any, **kw: Any) -> None:
        self._node = node
        self.__disposed = False
        self.__buttonConnections: list[Any] = []
        self._column = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8
        )
        expand_h(self._column)
        GafferUI.Widget.__init__(self, self._column, **kw)
        self._rows: dict[str, tuple[GafferUI.Widget, GafferUI.Widget]] = {}
        self._build()
        self._column.append(GafferUI.Spacer(imath.V2i(1, 1)), expand=True)
        self._plugDirtiedConnection = node.plugDirtiedSignal().connect(
            Gaffer.WeakMethod(self.__dispatch), scoped=True
        )

    def _build(self) -> None:
        raise NotImplementedError

    def _onPlugDirtied(self, plug: Any) -> None:
        pass

    def _addCard(self, title: str) -> GafferUI.ListContainer:
        card = GafferUI.Frame()
        body = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8
        )
        header = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=4
        )
        header.append(GafferUI.Label("<h3>{}</h3>".format(title)))
        header.append(GafferUI.Spacer(imath.V2i(8, 1)), expand=True)
        for label, tip, method in (
            (
                "Copy",
                "Copy type, transform, and parameters. Paste onto another "
                "node of the same type.",
                self.__onCopyValues,
            ),
            (
                "Paste",
                "Apply the last Copy onto this node. Prim path and name "
                "are kept.",
                self.__onPasteValues,
            ),
            (
                "Reset",
                "Reset all look values to defaults without creating a "
                "new node. Prim path and name are kept.",
                self.__onResetValues,
            ),
        ):
            button = GafferUI.Button(label)
            try:
                button.setToolTip(tip)
            except Exception:
                pass
            conn = button.clickedSignal().connect(
                Gaffer.WeakMethod(method), scoped=True
            )
            self.__buttonConnections.append(conn)
            header.append(button)
        body.append(header)
        card.setChild(body)
        self._column.append(card)
        return body

    def __onCopyValues(self, *unused: Any) -> None:
        copy = getattr(self._node, "copyValues", None)
        if not callable(copy):
            return
        data = copy()
        kind = data.get("kind") if isinstance(data, dict) else None
        if not kind:
            return
        _VALUE_CLIPBOARD[kind] = data
        IECore.msg(
            IECore.Msg.Level.Info,
            type(self._node).__name__,
            "Copied values — select another {} and Paste.".format(kind),
        )

    def __onPasteValues(self, *unused: Any) -> None:
        paste = getattr(self._node, "pasteValues", None)
        if not callable(paste):
            return
        kind = type(self._node).__name__
        data = _VALUE_CLIPBOARD.get(kind)
        if not data:
            IECore.msg(
                IECore.Msg.Level.Warning,
                kind,
                "Nothing to paste. Copy from another {} first.".format(kind),
            )
            return
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            applied = paste(data)
        IECore.msg(
            IECore.Msg.Level.Info if applied else IECore.Msg.Level.Warning,
            kind,
            "Pasted {} value{}.".format(applied, "" if applied == 1 else "s")
            if applied
            else "Paste did not apply any values.",
        )

    def __onResetValues(self, *unused: Any) -> None:
        reset = getattr(self._node, "resetValues", None)
        if not callable(reset):
            return
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            reset()
        IECore.msg(
            IECore.Msg.Level.Info,
            type(self._node).__name__,
            "Reset look values to defaults.",
        )

    def _addRow(
        self,
        form: GafferUI.Widget,
        label: str,
        widget: GafferUI.Widget,
        name: str | None = None,
    ) -> GafferUI.ListContainer:
        row = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=8
        )
        lbl = self.__rowLabel(label, widget)
        try:
            if isinstance(lbl, GafferUI.LabelPlugValueWidget):
                lbl.label()._qtWidget().setFixedWidth(self._LABEL_W)
            else:
                lbl._qtWidget().setFixedWidth(self._LABEL_W)
        except Exception:
            pass
        row.append(lbl)
        expand_h(widget)
        row.append(widget, expand=True)
        form.append(row)
        if name is not None:
            self._rows[name] = (row, widget)
        return row

    def __rowLabel(self, label: str, widget: GafferUI.Widget) -> GafferUI.Widget:
        plug = None
        if isinstance(widget, GafferUI.PlugValueWidget):
            try:
                plug = widget.getPlug()
            except Exception:
                plug = None
        if plug is None:
            return GafferUI.Label(label)
        return GafferUI.LabelPlugValueWidget(plug)

    def _clearRows(self, form: GafferUI.Widget, *prefixes: str) -> None:
        names = [
            name
            for name in list(self._rows)
            if any(name.startswith(prefix) for prefix in prefixes)
        ]
        for name in names:
            row, _widget = self._rows.pop(name)
            try:
                form.removeChild(row)
            except Exception:
                pass

    def _setRowVisible(self, name: str, visible: bool) -> None:
        row = self._rows.get(name)
        if row is None or not widget_is_alive(row[0]):
            return
        row[0].setVisible(visible)

    def _setRowEnabled(self, name: str, enabled: bool) -> None:
        row = self._rows.get(name)
        if row is None:
            return
        for widget in row:
            if not widget_is_alive(widget):
                continue
            try:
                widget.setEnabled(enabled)
            except Exception:
                pass

    def _tab_form(self) -> GafferUI.ListContainer:
        return GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=6
        )

    def _scroll(self, child: GafferUI.Widget) -> GafferUI.ScrolledContainer:
        scroll = GafferUI.ScrolledContainer(
            horizontalMode=GafferUI.ScrollMode.Never,
            borderWidth=0,
        )
        scroll.setChild(child)
        expand_h(scroll)
        return scroll

    @staticmethod
    def _add_tab(
        tabs: GafferUI.TabbedContainer, child: GafferUI.Widget, label: str
    ) -> None:
        try:
            tabs.append(child, label)
        except TypeError:
            tabs.addChild(child)
            tabs.setLabel(child, label)

    def __dispatch(self, plug: Any) -> None:
        if self.__disposed or not widget_is_alive(self):
            return
        self._onPlugDirtied(plug)
