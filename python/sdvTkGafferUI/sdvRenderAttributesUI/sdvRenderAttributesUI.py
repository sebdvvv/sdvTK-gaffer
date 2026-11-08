"""Node Editor card for sdvRenderAttributes — MeshType toggle, then attribute sets."""

from __future__ import annotations

import functools

import Gaffer
import GafferUI
import imath

from sdvTkGaffer.sdvRenderAttributes.sdvRenderAttributes import sdvRenderAttributes
from sdvTkGaffer.sdvRenderSettings._data import (
    MAX_PATHS,
    MAX_SLOTS,
    default_set_name,
    engine_label,
    import_engine_ui,
    path_count_plug,
    path_plug,
    set_name_plug,
)
from sdvTkGafferUI.sdvRenderSettingsUI._editor import (
    CardNodeWidget,
    expand_h,
    native_widget,
    widget_is_alive,
)
from sdvTkGafferUI.sdvRenderSettingsUI._icons import register_node_icon
from sdvTkGafferUI.sdvRenderSettingsUI.sdvRenderSettingsUI import (
    _clear_container,
    _plug_widget,
    _settings_widget,
)

BOX_SLATE = imath.Color3f(0.30, 0.32, 0.38)


class _sdvRenderAttributesWidget(CardNodeWidget):
    _LABEL_W = 130

    def _build(self) -> None:
        card = self._addCard("Render Attributes")
        self._addRow(
            card,
            "Renderer",
            GafferUI.PresetsPlugValueWidget(self._node["renderEngine"]),
            name="renderEngine",
        )
        toggles = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=16
        )
        spacer = GafferUI.Label("")
        try:
            spacer._qtWidget().setFixedWidth(self._LABEL_W)
        except Exception:
            pass
        toggles.append(spacer)
        widget = GafferUI.BoolPlugValueWidget(self._node["enableCatmullClark"])
        try:
            widget.boolWidget().setText("Enable Catmull-Clark Subdivision type")
        except Exception:
            toggles.append(GafferUI.Label("Enable Catmull-Clark Subdivision type"))
        try:
            widget.setToolTip(
                Gaffer.Metadata.value(self._node["enableCatmullClark"], "description")
                or ""
            )
        except Exception:
            pass
        toggles.append(widget)
        card.append(toggles)

        self._tabs = GafferUI.TabbedContainer()
        expand_h(self._tabs)
        card.append(self._tabs)

        self._main_form = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8
        )
        self._main_tab = self._scroll(self._main_form)
        self._add_tab(self._tabs, self._main_tab, "Main")

        buttons = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=6
        )
        self._add_slot_button = GafferUI.Button(self._add_button_label())
        self._add_slot_button.setToolTip(
            "Add an attribute set (max {}).".format(MAX_SLOTS)
        )
        self._buttonConnections.append(
            self._add_slot_button.clickedSignal().connect(
                Gaffer.WeakMethod(self.__onAddSlot), scoped=True
            )
        )
        buttons.append(self._add_slot_button)
        self._main_form.append(buttons)

        self._slot_frames: list[GafferUI.Widget] = []
        self._slot_headers: dict[int, GafferUI.Label] = {}
        self._path_rows: dict[tuple[int, int], GafferUI.Widget] = {}
        self._path_plus: dict[int, GafferUI.Widget] = {}
        self._attr_forms: list[GafferUI.ListContainer] = []
        self._attr_tabs: list[GafferUI.Widget] = []
        self.__pending_attr: set[int] = set()

        for index in range(1, MAX_SLOTS + 1):
            self._main_form.append(self._build_slot(index))
            form = GafferUI.ListContainer(
                GafferUI.ListContainer.Orientation.Vertical, spacing=6
            )
            scroll = self._scroll(form)
            self._attr_forms.append(form)
            self._attr_tabs.append(scroll)
            self._add_tab(self._tabs, scroll, self._slot_tab_name(index))

        self._syncSlots()
        self._rebuild_all_attr_tabs()

    def _scroll(self, child: GafferUI.Widget) -> GafferUI.ScrolledContainer:
        scroll = GafferUI.ScrolledContainer(
            horizontalMode=GafferUI.ScrollMode.Never,
            borderWidth=0,
        )
        scroll.setChild(child)
        expand_h(scroll)
        return scroll

    @staticmethod
    def _add_tab(tabs, child, label: str) -> None:
        try:
            tabs.append(child, label)
        except TypeError:
            tabs.addChild(child)
            tabs.setLabel(child, label)

    def _add_button_label(self) -> str:
        renderer = engine_label(self._node.currentEngine()).replace(" ", "")
        return "Add {}Attributes Set".format(renderer)

    def _sync_add_button(self) -> None:
        button = getattr(self, "_add_slot_button", None)
        if button is None or not widget_is_alive(button):
            return
        try:
            button.setText(self._add_button_label())
            button.setToolTip(
                "Add an attribute set (max {}).".format(MAX_SLOTS)
            )
        except Exception:
            pass

    def _build_slot(self, index: int) -> GafferUI.Widget:
        node = self._node
        frame = GafferUI.Frame()
        body = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=6
        )
        header = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=6
        )
        title = GafferUI.Label("<b>{}</b>".format(self._slot_tab_name(index)))
        header.append(title)
        self._slot_headers[index] = title
        header.append(GafferUI.Spacer(imath.V2i(8, 1)), expand=True)
        clear = GafferUI.Button("Clear")
        clear.setToolTip("Reset this attribute set's name, paths, and values.")
        self._buttonConnections.append(
            clear.clickedSignal().connect(
                functools.partial(self.__onClearSlot, index), scoped=True
            )
        )
        header.append(clear)
        remove = GafferUI.Button("Remove")
        remove.setToolTip("Remove this attribute set.")
        self._buttonConnections.append(
            remove.clickedSignal().connect(
                functools.partial(self.__onRemoveSlot, index), scoped=True
            )
        )
        header.append(remove)
        body.append(header)

        self._addRow(
            body,
            "Attribute Set",
            native_widget(node[set_name_plug(index)]),
            name="setName{}".format(index),
        )
        plus_row = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=6
        )
        plus_row.append(GafferUI.Spacer(imath.V2i(self._LABEL_W, 1)))
        plus = GafferUI.Button("+")
        plus.setToolTip("Add another prim path to this set's PathFilter.")
        minus = GafferUI.Button("−")
        minus.setToolTip("Remove the last prim path field.")
        self._buttonConnections.append(
            plus.clickedSignal().connect(
                functools.partial(self.__onAddPath, index), scoped=True
            )
        )
        self._buttonConnections.append(
            minus.clickedSignal().connect(
                functools.partial(self.__onRemovePath, index), scoped=True
            )
        )
        plus_row.append(plus)
        plus_row.append(minus)
        body.append(plus_row)
        self._path_plus[index] = plus_row

        frame.setChild(body)
        self._slot_frames.append(frame)
        self._sync_path_rows(index)
        return frame

    def _sync_path_rows(self, index: int) -> None:
        try:
            path_count = int(self._node[path_count_plug(index)].getValue())
        except Exception:
            path_count = 1
        path_count = max(1, min(path_count, MAX_PATHS))
        for path_index in range(1, path_count + 1):
            self._ensure_path_row(index, path_index)
        extras = [
            key
            for key in list(self._path_rows)
            if key[0] == index and key[1] > path_count
        ]
        body = None
        if index <= len(self._slot_frames):
            try:
                body = self._slot_frames[index - 1].getChild()
            except Exception:
                body = None
        for key in extras:
            row = self._path_rows.pop(key, None)
            if row is None:
                continue
            if body is not None:
                try:
                    body.removeChild(row)
                except Exception:
                    pass

    def _ensure_path_row(self, index: int, path_index: int) -> None:
        if (index, path_index) in self._path_rows:
            return
        if index < 1 or index > len(self._slot_frames):
            return
        path = self._node[path_plug(index, path_index)]
        widget = _plug_widget(path)
        if widget is None:
            return
        body = self._slot_frames[index - 1].getChild()
        plus = self._path_plus.get(index)
        if plus is not None:
            try:
                body.removeChild(plus)
            except Exception:
                pass
        row = self._addRow(
            body,
            "PrimPath(es) :",
            widget,
            name="path{}_{}".format(index, path_index),
        )
        self._path_rows[(index, path_index)] = row
        if plus is not None:
            body.append(plus)

    def _onPlugDirtied(self, plug: Gaffer.Plug) -> None:
        name = plug.getName()
        if name == "renderEngine":
            self._sync_add_button()
            self.__pending_attr.update(range(1, MAX_SLOTS + 1))
            self.__rebuildAttrLazily()
        elif name == "slotCount":
            self.__syncSlotsLazily()
            self.__pending_attr.update(range(1, MAX_SLOTS + 1))
            self.__rebuildAttrLazily()
        elif name.startswith("pathCount"):
            self.__syncSlotsLazily()
        elif name.startswith("setName"):
            digits = "".join(ch for ch in name if ch.isdigit())
            if digits:
                self._set_tab_label(int(digits))

    @GafferUI.LazyMethod()
    def __syncSlotsLazily(self) -> None:
        self._syncSlots()

    @GafferUI.LazyMethod()
    def __rebuildAttrLazily(self) -> None:
        pending = set(self.__pending_attr)
        self.__pending_attr.clear()
        if not pending:
            self._rebuild_all_attr_tabs()
            return
        for index in sorted(pending):
            self._fill_attr_tab(index)

    def _syncSlots(self) -> None:
        if not widget_is_alive(self):
            return
        count = int(self._node["slotCount"].getValue())
        for index in range(1, MAX_SLOTS + 1):
            visible = index <= count
            if index <= len(self._slot_frames):
                self._slot_frames[index - 1].setVisible(visible)
            self._set_tab_visible(index, visible)
            if visible:
                self._sync_path_rows(index)
        self._add_slot_button.setEnabled(count < MAX_SLOTS)
        self._sync_add_button()
        for index in range(1, MAX_SLOTS + 1):
            self._set_tab_label(index)

    def _set_tab_visible(self, index: int, visible: bool) -> None:
        if index < 1 or index > len(self._attr_tabs):
            return
        tab = self._attr_tabs[index - 1]
        try:
            self._tabs.setTabVisible(tab, visible)
            return
        except Exception:
            pass
        try:
            tab.setVisible(visible)
        except Exception:
            pass

    def _slot_tab_name(self, index: int) -> str:
        try:
            name = (self._node[set_name_plug(index)].getValue() or "").strip()
        except Exception:
            name = ""
        return name or default_set_name(self._node.currentEngine(), index)

    def _set_tab_label(self, index: int) -> None:
        if not widget_is_alive(self):
            return
        label = self._slot_tab_name(index)
        tab = self._attr_tabs[index - 1]
        try:
            self._tabs.setLabel(tab, label)
        except Exception:
            qt = self._tabs._qtWidget()
            setter = getattr(qt, "setTabText", None)
            if callable(setter):
                try:
                    setter(self._tabs.index(tab), label)
                except Exception:
                    pass
        header = self._slot_headers.get(index)
        if header is not None and widget_is_alive(header):
            try:
                header.setText("<b>{}</b>".format(label))
            except Exception:
                pass

    def _rebuild_all_attr_tabs(self) -> None:
        if not widget_is_alive(self):
            return
        for index in range(1, MAX_SLOTS + 1):
            self._fill_attr_tab(index)

    def _fill_attr_tab(self, index: int) -> None:
        self._set_tab_label(index)
        form = self._attr_forms[index - 1]
        _clear_container(form)
        form.append(GafferUI.Label("<b>{}</b>".format(self._slot_tab_name(index))))
        engine = self._node.currentEngine()
        import_engine_ui(engine)
        attr = self._node.attributesNode(index)
        if attr is None or "attributes" not in attr:
            form.append(
                GafferUI.Label(
                    "No {} attributes for this set.".format(engine_label(engine))
                )
            )
            return
        form.append(_settings_widget(attr["attributes"]))

    def __onAddSlot(self, *unused) -> None:
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node.addSlot()

    def __onRemoveSlot(self, index: int, *unused) -> None:
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node.removeSlot(index)
        self._syncSlots()
        self._rebuild_all_attr_tabs()

    def __onAddPath(self, index: int, *unused) -> None:
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node.addPath(index)

    def __onRemovePath(self, index: int, *unused) -> None:
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node.removePath(index)

    def __onClearSlot(self, index: int, *unused) -> None:
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node.clearSlot(index)
        self._fill_attr_tab(index)


def _sdvRenderAttributesWidgetCreator(node: Gaffer.Node) -> _sdvRenderAttributesWidget:
    return _sdvRenderAttributesWidget(node)


_plugs = {
    "*": {
        "layout:visibilityActivator": "never",
    },
    "in": {
        "description": "Incoming scene. Drop the node on a scene "
        "connection to insert.",
        "nodule:type": "GafferUI::StandardNodule",
        "noduleLayout:section": "top",
        "noduleLayout:index": 0,
    },
    "out": {
        "description": "Incoming scene with the MeshType and attribute "
        "sets applied (passthrough of in when disabled).",
        "nodule:type": "GafferUI::StandardNodule",
        "noduleLayout:section": "bottom",
        "noduleLayout:index": 0,
    },
    "enabled": {
        "description": "When off, the incoming scene passes through "
        "unchanged.",
        "nodule:type": "",
    },
    "renderEngine": {
        "label": "Renderer",
        "description": "Renderer whose attribute nodes are active "
        "(Arnold, RenderMan, or Cycles). Unused engine nodes are disabled.",
        "nodule:type": "",
        "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
        "preset:Arnold": "arnold",
        "preset:RenderMan": "renderman",
        "preset:Cycles": "cycles",
    },
    "enableCatmullClark": {
        "label": "Enable Catmull-Clark Subdivision type",
        "description": "Turns the MeshType at the start of this node to "
        "Catmull-Clark. Off leaves mesh interpolation unchanged.",
        "nodule:type": "",
    },
    "slotCount": {
        "description": "How many attribute sets are active (0–8).",
        "nodule:type": "",
    },
}
for _index in range(1, MAX_SLOTS + 1):
    _plugs[set_name_plug(_index)] = {
        "description": "Name of this attribute set. Also names its tab.",
        "nodule:type": "",
    }
    _plugs[path_count_plug(_index)] = {
        "description": "How many prim-path fields are shown for this set.",
        "nodule:type": "",
    }
    for _path in range(1, MAX_PATHS + 1):
        _plugs[path_plug(_index, _path)] = {
            "description": "Scene prim path for this attribute set. "
            "Feeds the set's PathFilter. Supports a Gaffer expression. "
            "All paths share one PathFilter.",
            "nodule:type": "",
            "label": "PrimPath(es) :",
            "plugValueWidget:type": "GafferUI.StringPlugValueWidget",
        }

Gaffer.Metadata.registerNode(
    sdvRenderAttributes,
    "description",
    "MeshType, then up to eight attribute sets. Enable Catmull-Clark "
    "Subdivision type sits under Renderer and drives that MeshType. "
    "Each attribute set has its own tab.",
    "nodeGadget:color",
    BOX_SLATE,
    "noduleLayout:customGadget:addButtonTop:gadgetType",
    None,
    "noduleLayout:customGadget:addButtonBottom:gadgetType",
    None,
    "noduleLayout:customGadget:addButtonLeft:gadgetType",
    None,
    "noduleLayout:customGadget:addButtonRight:gadgetType",
    None,
    "layout:customWidget:addButton:widgetType",
    None,
    "layout:customWidget:sdvRenderAttributes:widgetType",
    "sdvRenderAttributesUI.sdvRenderAttributesUI._sdvRenderAttributesWidgetCreator",
    "layout:customWidget:sdvRenderAttributes:section",
    "Settings",
    "layout:customWidget:sdvRenderAttributes:index",
    0,
    "layout:activator:never",
    False,
    plugs=_plugs,
)

register_node_icon(sdvRenderAttributes, "sdvRenderAttributes.png")
