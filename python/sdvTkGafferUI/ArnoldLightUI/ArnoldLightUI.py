"""Node Editor card for ArnoldLight — Light / Shaping / Gobo / Transform / Arnold."""

from __future__ import annotations

import Gaffer
import GafferUI
import IECore

from sdvTkGaffer.ArnoldLight.ArnoldLight import ArnoldLight
from sdvTkGaffer.ArnoldLight._data import (
    ARNOLD_LIGHT_TYPES,
    GOBO_FOCUS_PARAMETERS,
    GOBO_MAP_CELL,
    GOBO_MAP_FILE,
    GOBO_MAP_HIDE,
    GOBO_MAP_NOISE,
    GOBO_MAP_OFF,
    GOBO_MAP_TYPES,
    GOBO_UV_PARAMETERS,
    INTERNAL_GOBO_CELL,
    INTERNAL_GOBO_IMAGE,
    INTERNAL_GOBO_NOISE,
    MESH_LIGHT,
    SHAPING_LABELS,
    SPOT_LIGHT,
    parameter_section,
)
from sdvTkGaffer.ArnoldLight._insert import MODE_CREATE, MODE_EDIT

from ._icons import register_node_icon

from ._editor import (
    CardNodeWidget,
    ExistingLightsPlugValueWidget,
    expand_h,
    native_widget,
)

LIGHT_AMBER = ArnoldLight.GRAPH_COLOR


def _param_label(plug: Gaffer.Plug) -> str:
    override = SHAPING_LABELS.get(plug.getName())
    if override:
        return override
    label = Gaffer.Metadata.value(plug, "label")
    if label:
        return str(label)
    return IECore.CamelCase.toSpaced(plug.getName())


def _show_param(plug: Gaffer.Plug) -> bool:
    if plug.getName() in ("out", "type", "name", "shader", "attributeSuffix"):
        return False
    if str(_param_label(plug)).strip().lower() == "shader":
        return False
    widget_type = Gaffer.Metadata.value(plug, "plugValueWidget:type")
    if widget_type == "":
        return False
    return True


def _plug_widget(plug: Gaffer.Plug) -> GafferUI.Widget | None:
    if not _show_param(plug):
        return None
    try:
        return native_widget(plug)
    except Exception:
        return None


class _ArnoldLightWidget(CardNodeWidget):
    """Card + tabs for ArnoldLight."""

    def _build(self) -> None:
        node = self._node
        card = self._addCard("Arnold Light")

        self._addRow(
            card,
            "Mode",
            GafferUI.PresetsPlugValueWidget(node["mode"]),
            name="mode",
        )
        self._addRow(
            card,
            "Existing Light",
            ExistingLightsPlugValueWidget(node["editPath"]),
            name="editPath",
        )

        tabs = GafferUI.TabbedContainer()
        expand_h(tabs)
        card.append(tabs)

        light_form = self._tab_form()
        self._add_tab(tabs, self._scroll(light_form), "Light")

        self._addRow(
            light_form,
            "Light Type",
            GafferUI.PresetsPlugValueWidget(node["lightType"]),
            name="lightType",
        )
        self._addRow(
            light_form,
            "Prim Path",
            native_widget(node["primPath"]),
            name="meshPrimPath",
        )
        self._addRow(
            light_form,
            "Label",
            native_widget(node["label"]),
            name="label",
        )
        self._addRow(
            light_form,
            "Prim Name",
            native_widget(node["name"]),
            name="name",
        )
        self._addRow(
            light_form,
            "GL Drawing",
            GafferUI.PresetsPlugValueWidget(node["glDrawingMode"]),
            name="glDrawingMode",
        )
        self._lightForm = light_form

        shaping_form = self._tab_form()
        self._add_tab(tabs, self._scroll(shaping_form), "Shaping")
        self._shapingForm = shaping_form

        gobo_form = self._tab_form()
        self._add_tab(tabs, self._scroll(gobo_form), "Gobo/Masking")
        self._goboForm = gobo_form
        self._addRow(
            gobo_form,
            "Gobo Map",
            GafferUI.PresetsPlugValueWidget(node["goboMap"]),
            name="goboMap",
        )

        xform_form = self._tab_form()
        self._add_tab(tabs, self._scroll(xform_form), "Transform")
        xform_widget = _plug_widget(node["transform"])
        if xform_widget is not None:
            self._addRow(
                xform_form, "Transform", xform_widget, name="transform"
            )

        path_form = self._tab_form()
        self._add_tab(tabs, self._scroll(path_form), "Prim Path")
        self._addRow(
            path_form,
            "Prim Path",
            native_widget(node["primPath"]),
            name="primPath",
        )

        arnold_form = self._tab_form()
        self._add_tab(tabs, self._scroll(arnold_form), "Arnold")
        self._arnoldForm = arnold_form

        self._fillTypeParams()
        self._syncTypeRows()
        self._syncModeRows()
        self._syncGoboRows()

    def _onPlugDirtied(self, plug: Gaffer.Plug) -> None:
        if plug.getName() == "lightType":
            self.__rebuildParamsLazily()
        elif plug.getName() == "goboMap":
            self.__syncGoboLazily()
        elif plug.getName() == "mode":
            self.__syncModeLazily()

    @GafferUI.LazyMethod()
    def __rebuildParamsLazily(self) -> None:
        self._fillTypeParams()
        self._syncTypeRows()
        self._syncGoboRows()

    @GafferUI.LazyMethod()
    def __syncGoboLazily(self) -> None:
        self._syncGoboRows()

    @GafferUI.LazyMethod()
    def __syncModeLazily(self) -> None:
        self._syncModeRows()

    def _fillTypeParams(self) -> None:
        self._clearRows(self._lightForm, "param:")
        self._clearRows(
            self._shapingForm, "shaping:", "shapingHint:"
        )
        self._clearRows(
            self._goboForm,
            "goboUv:",
            "goboFocus:",
            "goboFilter:",
            "goboMapParam:",
            "goboHint:",
        )
        self._clearRows(self._arnoldForm, "contrib:")

        shader = self._node["lightType"].getValue()
        is_spot = shader == SPOT_LIGHT
        shaping_count = 0
        for plug in self._node.parameterPlugs():
            widget = _plug_widget(plug)
            if widget is None:
                continue
            section = parameter_section(plug.getName())
            label = _param_label(plug)
            if section == "shaping":
                self._addRow(
                    self._shapingForm,
                    label,
                    widget,
                    name="shaping:{}".format(plug.getName()),
                )
                shaping_count += 1
            elif section == "arnold":
                self._addRow(
                    self._arnoldForm,
                    label,
                    widget,
                    name="contrib:{}".format(plug.getName()),
                )
            else:
                self._addRow(
                    self._lightForm,
                    label,
                    widget,
                    name="param:{}".format(plug.getName()),
                )
        if shaping_count == 0:
            self._addRow(
                self._shapingForm,
                "",
                GafferUI.Label("No shaping parameters for this light type."),
                name="shapingHint:empty",
            )

        self._fillGoboParams(is_spot)

    def _fillGoboParams(self, is_spot: bool) -> None:
        if not is_spot:
            self._addRow(
                self._goboForm,
                "",
                GafferUI.Label("Gobo / masking is available on Spot Light."),
                name="goboHint:spot",
            )
            return
        gobo = self._node.goboFilter()
        if gobo is None or "parameters" not in gobo:
            self._addRow(
                self._goboForm,
                "",
                GafferUI.Label("Gobo filter is not available in this Arnold."),
                name="goboHint:missing",
            )
            return
        params = gobo["parameters"]
        for name in GOBO_UV_PARAMETERS:
            if name not in params:
                continue
            widget = _plug_widget(params[name])
            if widget is None:
                continue
            self._addRow(
                self._goboForm,
                _param_label(params[name]),
                widget,
                name="goboUv:{}".format(name),
            )
        for name in GOBO_FOCUS_PARAMETERS:
            light_plug = None
            for plug in self._node.parameterPlugs():
                if plug.getName() == name:
                    light_plug = plug
                    break
            if light_plug is None:
                continue
            widget = _plug_widget(light_plug)
            if widget is None:
                continue
            self._addRow(
                self._goboForm,
                _param_label(light_plug),
                widget,
                name="goboFocus:{}".format(name),
            )
        skip = set(GOBO_UV_PARAMETERS)
        for plug in params.children():
            if plug.getName() in skip or plug.getName() == "density":
                continue
            widget = _plug_widget(plug)
            if widget is None:
                continue
            self._addRow(
                self._goboForm,
                _param_label(plug),
                widget,
                name="goboFilter:{}".format(plug.getName()),
            )
        for map_shader in (
            self._node.getChild(INTERNAL_GOBO_IMAGE),
            self._node.getChild(INTERNAL_GOBO_NOISE),
            self._node.getChild(INTERNAL_GOBO_CELL),
        ):
            if map_shader is None or "parameters" not in map_shader:
                continue
            prefix = "goboMapParam:{}:".format(map_shader.getName())
            for plug in map_shader["parameters"].children():
                if plug.getName() in GOBO_MAP_HIDE:
                    continue
                widget = _plug_widget(plug)
                if widget is None:
                    continue
                self._addRow(
                    self._goboForm,
                    _param_label(plug),
                    widget,
                    name=prefix + plug.getName(),
                )

    def _syncTypeRows(self) -> None:
        shader = self._node["lightType"].getValue()
        is_mesh = shader == MESH_LIGHT
        is_spot = shader == SPOT_LIGHT
        self._setRowVisible("meshPrimPath", is_mesh)
        self._setRowVisible("label", not is_mesh)
        self._setRowVisible("name", not is_mesh)
        self._setRowVisible("glDrawingMode", not is_mesh)
        self._setRowVisible("transform", not is_mesh)
        self._setRowVisible("goboMap", is_spot)
        self._syncModeRows()

    def _syncGoboRows(self) -> None:
        shader = self._node["lightType"].getValue()
        is_spot = shader == SPOT_LIGHT
        kind = GOBO_MAP_OFF
        try:
            kind = (self._node["goboMap"].getValue() or "").strip() or GOBO_MAP_OFF
        except Exception:
            kind = GOBO_MAP_OFF
        wanted = {
            GOBO_MAP_OFF: "",
            GOBO_MAP_FILE: INTERNAL_GOBO_IMAGE,
            GOBO_MAP_NOISE: INTERNAL_GOBO_NOISE,
            GOBO_MAP_CELL: INTERNAL_GOBO_CELL,
        }.get(kind, "")
        for name in self._rows:
            if (
                name.startswith("goboUv:")
                or name.startswith("goboFocus:")
                or name.startswith("goboFilter:")
            ):
                self._setRowVisible(name, is_spot)
            elif name.startswith("goboMapParam:"):
                child = name.split(":")[1] if name.count(":") >= 1 else ""
                self._setRowVisible(
                    name, is_spot and kind != GOBO_MAP_OFF and child == wanted
                )
        self._setRowVisible("goboMap", is_spot)

    def _syncModeRows(self) -> None:
        editing = self._node["mode"].getValue() == MODE_EDIT
        self._setRowVisible("editPath", editing)
        # Identity is the selected light; name / path / label are not free.
        self._setRowEnabled("name", not editing)
        self._setRowEnabled("label", not editing)
        self._setRowEnabled("primPath", not editing)
        self._setRowEnabled("meshPrimPath", not editing)


def _arnoldLightWidgetCreator(node: Gaffer.Node) -> _ArnoldLightWidget:
    return _ArnoldLightWidget(node)


_light_type_presets = {}
for _shader, _label in ARNOLD_LIGHT_TYPES:
    _light_type_presets["preset:" + _label] = _shader

Gaffer.Metadata.registerNode(
    ArnoldLight,
    "description",
    "Adds one Arnold light into the incoming scene. Create authors "
    "{label}N_{typeToken} under Prim Path groups (areaLight, diskLight, "
    "…); Edit loads an existing light and authors at the same name "
    "and path.",
    "nodeGadget:color",
    LIGHT_AMBER,
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
    "layout:customWidget:arnoldLight:widgetType",
    "ArnoldLightUI.ArnoldLightUI._arnoldLightWidgetCreator",
    "layout:customWidget:arnoldLight:section",
    "Settings",
    "layout:customWidget:arnoldLight:index",
    0,
    "layout:activator:never",
    False,
    plugs={
        "*": {
            "layout:visibilityActivator": "never",
        },
        "in": {
            "description": "Incoming scene the light is merged into. "
            "Drop the node on a scene connection to insert.",
            "nodule:type": "GafferUI::StandardNodule",
            "noduleLayout:section": "top",
            "noduleLayout:index": 0,
        },
        "out": {
            "description": "Incoming scene plus the Arnold light "
            "(passthrough of in when the node is disabled).",
            "nodule:type": "GafferUI::StandardNodule",
            "noduleLayout:section": "bottom",
            "noduleLayout:index": 0,
        },
        "enabled": {
            "description": "When off, the incoming scene passes through "
            "unchanged (no light merged).",
            "nodule:type": "",
        },
        "mode": {
            "description": "Create authors a new light with a unique "
            "name. Edit picks an existing light, loads its values, and "
            "authors at the same name and path (those fields are locked "
            "to the selection).",
            "nodule:type": "",
            "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
            "preset:Create": MODE_CREATE,
            "preset:Edit": MODE_EDIT,
        },
        "label": {
            "description": "User name used to build the prim: "
            "{label}1_areaLight, {label}1_diskLight, …",
            "nodule:type": "",
        },
        "lightType": {
            "description": "Arnold light shader loaded on the internal "
            "light (Area / quad is the default). Only this type is "
            "created — switching type reloads the shader and keeps "
            "matching parameters (color, exposure, …). Skydome is a "
            "separate node. The prim suffix is camelCase with no "
            "underscores (areaLight, diskLight, …).",
            "nodule:type": "",
            "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
            **_light_type_presets,
        },
        "name": {
            "description": "Leaf prim name (constructed from Label + "
            "Light Type, uniqued in Create mode). Locked in Edit mode "
            "to the selected light.",
            "nodule:type": "",
        },
        "primPath": {
            "description": "For Mesh Light: scene location(s) that emit "
            "light (PathFilter on the internal ArnoldMeshLight). "
            "Supports a Gaffer expression. Separate several paths with "
            "spaces. For other types: group path the light is placed "
            "under. Groups are created only for that path (default "
            "/LIGHTS, max 4). /apath and /apath/ are one group. A "
            "spot gobo is parented at {Prim Path}/gobos inside that "
            "same group chain.",
            "nodule:type": "",
            "label": "Prim Path",
            "plugValueWidget:type": "GafferSceneUI.ScenePathPlugValueWidget",
            "scenePathPlugValueWidget:scene": "in",
        },
        "editPath": {
            "description": "Existing light to edit. Prim Name and Prim "
            "Path are forced to this location.",
            "nodule:type": "",
        },
        "goboMap": {
            "description": "Spot Light only. Off, or a File / Noise / "
            "Cell Noise map projected by an Arnold gobo filter. The "
            "gobo prim is grouped under gobos inside the Prim Path "
            "folders, not after them. UV and focus sit on the "
            "Gobo/Masking tab.",
            "nodule:type": "",
            "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
            **{
                "preset:" + label: value for value, label in GOBO_MAP_TYPES
            },
        },
        "glDrawingMode": {
            "description": "Viewer light drawing for this prim. Viewer "
            "follows the Drawing menu (wireframe / color / texture). "
            "Off / Wireframe / Color / Texture override that menu on "
            "this light only.",
            "nodule:type": "",
            "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
            "preset:Viewer": "",
            "preset:Off": "off",
            "preset:Wireframe": "wireframe",
            "preset:Color": "color",
            "preset:Texture": "texture",
        },
        "transform": {
            "description": "Transform applied to the enabled light.",
            "nodule:type": "",
        },
    },
)

register_node_icon(ArnoldLight, "ArnoldLight.png", "ArnoldLightEdit.png")
