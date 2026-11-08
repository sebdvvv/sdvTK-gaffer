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
    return GafferUI.StringPlugValueWidget(plug)


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
                "Copy this node's values. Paste onto another node of the same type.",
                self.__onCopyValues,
            ),
            (
                "Paste",
                "Apply the last Copy onto this node.",
                self.__onPasteValues,
            ),
            (
                "Reset",
                "Reset values to defaults. Renderer is kept.",
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
        from sdvTkGafferUI.nodeHelp import append_help_button

        append_help_button(header, self._node, self._buttonConnections)
        body.append(header)
        card.setChild(body)
        self._column.append(card)
        return body

    def _headerTrailingWidgets(self) -> list:
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
        return GafferUI.Label(label)

    def _setRowVisible(self, name: str, visible: bool) -> None:
        row = self._rows.get(name)
        if row is None or not widget_is_alive(row[0]):
            return
        row[0].setVisible(visible)

    def __dispatch(self, plug: Any) -> None:
        if self.__disposed or not widget_is_alive(self):
            return
        self._onPlugDirtied(plug)
