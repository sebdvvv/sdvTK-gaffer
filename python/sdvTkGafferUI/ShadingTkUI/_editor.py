"""Minimal Node Editor helpers (no GafferPipe dependency)."""

from __future__ import annotations

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


def _install_safe_widget_visible() -> None:
    """PlugValueWidget updates call ``visible()`` after Qt has already gone."""
    current = GafferUI.Widget.visible
    if getattr(current, "_shadingtk_safe", False):
        return

    def visible(self, relativeTo=None):
        try:
            qt_widget = self._qtWidget()
            if qt_widget is None or not GafferUI._qtObjectIsValid(qt_widget):
                return False
            if relativeTo is not None:
                other = relativeTo._qtWidget()
                if other is None or not GafferUI._qtObjectIsValid(other):
                    return False
            return current(self, relativeTo)
        except RuntimeError:
            return False

    visible._shadingtk_safe = True
    GafferUI.Widget.visible = visible


_install_safe_widget_visible()


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
    if isinstance(plug, Gaffer.Color3fPlug):
        return GafferUI.ColorPlugValueWidget(plug)
    if isinstance(plug, Gaffer.StringVectorDataPlug):
        return GafferUI.VectorDataPlugValueWidget(plug)
    if isinstance(plug, Gaffer.StringPlug):
        return GafferUI.StringPlugValueWidget(plug)
    raise TypeError("No PlugValueWidget for {}".format(type(plug).__name__))


def param_label(plug: Any) -> str:
    label = Gaffer.Metadata.value(plug, "label")
    if label:
        return str(label)
    return IECore.CamelCase.toSpaced(plug.getName())


def plug_widget(plug: Any) -> GafferUI.Widget | None:
    if isinstance(plug, Gaffer.Color3fPlug):
        try:
            return GafferUI.ColorPlugValueWidget(plug)
        except Exception:
            pass
    try:
        return native_widget(plug)
    except Exception:
        return None


def descendant_widgets(widget: GafferUI.Widget | None) -> list[GafferUI.Widget]:
    """Nested Gaffer widgets, including those not exposed by list(container)."""
    found: list[GafferUI.Widget] = []
    seen: set[int] = set()
    stack: list[GafferUI.Widget] = [widget] if widget is not None else []
    while stack:
        current = stack.pop()
        ident = id(current)
        if ident in seen:
            continue
        seen.add(ident)
        found.append(current)
        try:
            stack.extend(list(current))
        except Exception:
            pass
        try:
            qt_widget = current._qtWidget()
            if not GafferUI._qtObjectIsValid(qt_widget):
                continue
            from Qt import QtWidgets

            for child_qt in qt_widget.findChildren(QtWidgets.QWidget):
                owner = GafferUI.Widget._owner(child_qt)
                if owner is not None:
                    stack.append(owner)
        except Exception:
            pass
    return found


def detach_path_widget(widget: GafferUI.Widget) -> None:
    """PathWidget listens to Path.pathChanged even after its Qt line edit is gone."""
    if not isinstance(widget, GafferUI.PathWidget):
        return
    try:
        widget._PathWidget__pathChangedConnection = None
    except Exception:
        pass


def release_plug_widget(widget: GafferUI.Widget) -> None:
    detach_path_widget(widget)
    if not isinstance(widget, GafferUI.PlugValueWidget):
        return
    try:
        widget._PlugValueWidget__plugDirtiedConnections = []
        widget._PlugValueWidget__plugInputChangedConnections = []
        widget._PlugValueWidget__plugMetadataChangedConnections = []
        widget._PlugValueWidget__auxiliaryPlugDirtiedConnections = []
        widget._PlugValueWidget__auxiliaryPlugInputChangedConnections = []
        widget._PlugValueWidget__plugs = set()
    except Exception:
        pass
    if not widget_is_alive(widget):
        return
    try:
        widget.setPlugs(set())
    except Exception:
        try:
            widget.setPlug(None)
        except Exception:
            pass


def release_plug_widgets(widget: GafferUI.Widget | None) -> None:
    """Drop PlugValueWidget plugs so Gaffer does not update deleted Qt objects."""
    descendants = descendant_widgets(widget)
    descendants.reverse()
    for child in descendants:
        release_plug_widget(child)


def clear_container(container: GafferUI.ListContainer) -> None:
    children = list(container)
    for child in children:
        release_plug_widgets(child)
        try:
            container.removeChild(child)
        except Exception:
            pass


_VALUE_CLIPBOARD: dict[str, dict] = {}


class CardNodeWidget(GafferUI.Widget):
    """Top-anchored column of rows with a live ``plugDirtied`` connection."""

    _LABEL_W = 130

    def __init__(self, node: Any, **kw: Any) -> None:
        self._node = node
        self.__disposed = False
        self._buttonConnections: list[Any] = []
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
                "Copy filters, colour, and shading. Paste onto another "
                "node of the same type.",
                self.__onCopyValues,
            ),
            (
                "Paste",
                "Apply the last Copy onto this node.",
                self.__onPasteValues,
            ),
            (
                "Reset",
                "Reset filters and shading to defaults.",
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
            self._buttonConnections.append(conn)
            header.append(button)
        for widget in self._headerTrailingWidgets():
            header.append(widget)
        body.append(header)
        card.setChild(body)
        self._column.append(card)
        return body

    def _headerTrailingWidgets(self) -> list:
        """Widgets after the title, before Copy / Paste / Reset (top-right)."""
        return []

    def _formColumn(self, card: GafferUI.Widget, spacing: int = 6):
        col = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=spacing
        )
        card.append(col)
        return col

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
            "Reset values to defaults.",
        )

    def _addRow(
        self,
        form: GafferUI.Widget,
        label: str,
        widget: GafferUI.Widget,
        name: str | None = None,
        fill: bool = True,
        text_label: bool = False,
        label_width: int | None = None,
    ) -> GafferUI.ListContainer:
        row = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=8
        )
        lbl = GafferUI.Label(label) if text_label else self.__rowLabel(label, widget)
        width = self._LABEL_W if label_width is None else label_width
        try:
            if text_label:
                pass
            elif isinstance(lbl, GafferUI.LabelPlugValueWidget):
                lbl.label()._qtWidget().setFixedWidth(width)
            else:
                lbl._qtWidget().setFixedWidth(width)
        except Exception:
            pass
        row.append(lbl)
        if fill:
            expand_h(widget)
            row.append(widget, expand=True)
        else:
            row.append(widget)
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
        if plug is None or not isinstance(plug, Gaffer.ValuePlug):
            return GafferUI.Label(label)
        return GafferUI.LabelPlugValueWidget(plug)

    def _setRowVisible(self, name: str, visible: bool) -> None:
        row = self._rows.get(name)
        if row is None or not widget_is_alive(row[0]):
            return
        row[0].setVisible(visible)

    def _setRowEnabled(self, name: str, enabled: bool) -> None:
        row = self._rows.get(name)
        if row is None or not widget_is_alive(row[0]):
            return
        try:
            row[0].setEnabled(enabled)
        except Exception:
            pass
        if len(row) > 1 and widget_is_alive(row[1]):
            try:
                row[1].setEnabled(enabled)
            except Exception:
                pass

    def __dispatch(self, plug: Any) -> None:
        if self.__disposed or not widget_is_alive(self):
            return
        self._onPlugDirtied(plug)
