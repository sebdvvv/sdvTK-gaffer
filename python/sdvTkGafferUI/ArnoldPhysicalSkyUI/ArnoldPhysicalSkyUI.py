"""Node Editor card for ArnoldPhysicalSky — Light / Transform / UV / Prim Path / Arnold / Light Linking / Viz."""

from __future__ import annotations

import Gaffer
import GafferUI
import IECore
import imath

from sdvTkGaffer.ArnoldPhysicalSky.ArnoldPhysicalSky import (
    ArnoldPhysicalSky,
    parameter_section,
)
from sdvTkGaffer.ArnoldPhysicalSky._data import (
    ARNOLD_SKY_DRIVEN_PARAMETERS,
    ARNOLD_SKY_TYPES,
    CONTRIBUTION_PARAMETERS,
    UV_PARAMETERS,
)
from sdvTkGaffer.ArnoldPhysicalSky._insert import MODE_EDIT

from ._icons import register_node_icon

from ._editor import (
    CardNodeWidget,
    ExistingLightsPlugValueWidget,
    expand_h,
    native_widget,
    widget_is_alive,
)

SKY_CYAN = imath.Color3f(72 / 255, 168 / 255, 230 / 255)

# Light-tab order overrides (plug names on the skydome / physical_sky shader).
_AFTER_NAME = ("intensity", "exposure")
_AFTER_SKY_TINT = ("shadow_density", "shadow_color")
_INLINE_SHADER_BOOLS = ("sun", "sky")
_HIDDEN_PARAM_NAMES = frozenset(
    {"out", "type", "name", "shader", "attributeSuffix"}
)


def _side_grade_ready(node: Gaffer.Node, side: str) -> bool:
    """True when this side has a colour grade with an input and a multiply."""
    grade = node.getChild("__shader_grade_{}".format(side))
    if grade is None or "parameters" not in grade or "multiply" not in grade["parameters"]:
        return False
    for name in ("input", "color", "texture"):
        if name not in grade["parameters"]:
            continue
        plug = grade["parameters"][name]
        if isinstance(plug, (Gaffer.Color3fPlug, Gaffer.Color4fPlug)):
            return True
    return False


def _param_label(plug: Gaffer.Plug) -> str:
    label = Gaffer.Metadata.value(plug, "label")
    if label:
        return str(label)
    return IECore.CamelCase.toSpaced(plug.getName())


def _uv_section(plug: Gaffer.Plug) -> bool:
    if plug.getName() in UV_PARAMETERS:
        return True
    section = Gaffer.Metadata.value(plug, "layout:section")
    return bool(section) and "uv" in str(section).lower()


def _show_param(plug: Gaffer.Plug) -> bool:
    if plug.getName() in _HIDDEN_PARAM_NAMES:
        return False
    if str(_param_label(plug)).strip().lower() == "shader":
        return False
    widget_type = Gaffer.Metadata.value(plug, "plugValueWidget:type")
    if widget_type == "":
        parent = plug.parent()
        parent_name = parent.getName() if parent is not None else ""
        return (
            plug.getName() in CONTRIBUTION_PARAMETERS
            or plug.getName() in ("defaultLight", "mute", "sets")
            or parent_name == "visualiserAttributes"
            or _uv_section(plug)
        )
    if widget_type and "ShaderName" in str(widget_type):
        return False
    return True


def _plug_widget(plug: Gaffer.Plug) -> GafferUI.Widget | None:
    if not _show_param(plug):
        return None
    if isinstance(plug, Gaffer.TransformPlug):
        try:
            return native_widget(plug)
        except Exception:
            return None
    if plug.getName() == "camera" and isinstance(
        plug, (Gaffer.FloatPlug, Gaffer.IntPlug, Gaffer.BoolPlug)
    ):
        try:
            if isinstance(plug, Gaffer.BoolPlug):
                return GafferUI.BoolPlugValueWidget(plug)
            return GafferUI.NumericPlugValueWidget(plug)
        except Exception:
            pass
    try:
        created = native_widget(plug)
    except Exception:
        created = None
    if created is not None:
        return created
    if _uv_section(plug) or plug.getName() in CONTRIBUTION_PARAMETERS:
        try:
            if isinstance(plug, Gaffer.BoolPlug):
                return GafferUI.BoolPlugValueWidget(plug)
            if isinstance(plug, (Gaffer.IntPlug, Gaffer.FloatPlug)):
                return GafferUI.NumericPlugValueWidget(plug)
            if isinstance(plug, Gaffer.StringPlug):
                return GafferUI.StringPlugValueWidget(plug)
        except Exception:
            return None
    return None


class _EnvSkyWidget(CardNodeWidget):
    """Card + tabs for ArnoldPhysicalSky."""

    def _build(self) -> None:
        node = self._node
        card = self._addCard("Physical Sky")

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

        type_row = self._addRow(
            light_form,
            "Env Light Type",
            GafferUI.PresetsPlugValueWidget(node["skyType"]),
            name="skyType",
        )
        self._addInlineShaderBools(type_row, node)

        split_ready = node.splitAvailable()
        self._addRow(
            light_form,
            "Split Camera / Lighting",
            GafferUI.BoolPlugValueWidget(node["splitRays"]),
            name="splitRays",
        )
        if not split_ready:
            self._setRowEnabled("splitRays", False)
            self._addNote(
                light_form,
                "Arnold ray_switch is unavailable, so this stays off.",
                "splitMissing",
            )
        else:
            self._addNote(
                light_form,
                "Env Light Type is locked. Camera and Lighting replace its "
                "colour. Dome Intensity, Exposure, and Transform still apply "
                "to both. Turning this off returns to Env Light Type.",
                "splitLockHint",
            )
            light_form.append(self._buildSplitSection(node))

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
        self._addNamedLightParams(light_form, node, _AFTER_NAME)

        xform_form = self._tab_form()
        self._add_tab(tabs, self._scroll(xform_form), "Transform")
        xform_widget = _plug_widget(node["transform"])
        if xform_widget is not None:
            self._addRow(
                xform_form, "Transform", xform_widget, name="transform"
            )

        uv_form = self._tab_form()
        self._add_tab(tabs, self._scroll(uv_form), "UV Transform")
        self._addRow(
            uv_form,
            "",
            GafferUI.Label("UV Transform are available with HDRI."),
            name="uvHint",
        )
        self._addNote(
            uv_form,
            "Each HDRI side has its own UV inside Camera / Lighting on the Light tab.",
            "uvSplitHint",
        )

        path_form = self._tab_form()
        self._add_tab(tabs, self._scroll(path_form), "Prim Path")
        self._addRow(
            path_form,
            "Group Path",
            native_widget(node["primPath"]),
            name="primPath",
        )

        arnold_form = self._tab_form()
        self._add_tab(tabs, self._scroll(arnold_form), "Arnold")

        linking_form = self._tab_form()
        self._add_tab(tabs, self._scroll(linking_form), "Light Linking")
        for plug in node.lightLinkingPlugs():
            widget = _plug_widget(plug)
            if widget is None:
                continue
            self._addRow(
                linking_form,
                _param_label(plug),
                widget,
                name="link:{}".format(plug.getName()),
            )

        vis_form = self._tab_form()
        self._add_tab(tabs, self._scroll(vis_form), "Viz")
        for plug in node.visualisationPlugs():
            widget = _plug_widget(plug)
            if widget is None:
                continue
            self._addRow(
                vis_form,
                _param_label(plug),
                widget,
                name="vis:{}".format(plug.getName()),
            )

        light_plugs = {
            plug.getName(): plug for plug in node.parameterPlugs()
        }
        shadows = {
            name: light_plugs[name]
            for name in _AFTER_SKY_TINT
            if name in light_plugs
        }
        placed_light = set()
        shadows_added = False
        for sky_type, _label in ARNOLD_SKY_TYPES:
            for plug in node.shaderParameterPlugs(sky_type):
                if plug.getName() in _INLINE_SHADER_BOOLS:
                    continue
                widget = _plug_widget(plug)
                if widget is None:
                    continue
                section = parameter_section(
                    sky_type, plug.getName(), source="shader"
                )
                if section != "uv" and _uv_section(plug):
                    section = "uv"
                if section == "uv":
                    self._addRow(
                        uv_form,
                        _param_label(plug),
                        widget,
                        name="uv:{}:{}".format(sky_type, plug.getName()),
                    )
                    continue
                self._addRow(
                    light_form,
                    _param_label(plug),
                    widget,
                    name="shader:{}:{}".format(sky_type, plug.getName()),
                )
                if plug.getName() == "sky_tint":
                    for name in _AFTER_SKY_TINT:
                        shadow = shadows.get(name)
                        if shadow is None:
                            continue
                        self._addLightParamRow(light_form, shadow, "param")
                        placed_light.add(name)
                    shadows_added = True
        if not shadows_added:
            for name in _AFTER_SKY_TINT:
                shadow = shadows.get(name)
                if shadow is None:
                    continue
                self._addLightParamRow(light_form, shadow, "param")
                placed_light.add(name)
        for plug in node.parameterPlugs():
            name = plug.getName()
            if name in _AFTER_NAME or name in placed_light:
                continue
            if name in UV_PARAMETERS or _uv_section(plug):
                self._addLightParamRow(uv_form, plug, "uv")
            elif name in CONTRIBUTION_PARAMETERS:
                self._addLightParamRow(arnold_form, plug, "contrib")
            else:
                self._addLightParamRow(light_form, plug, "param")

        self._addRow(
            light_form,
            "GL Drawing",
            GafferUI.PresetsPlugValueWidget(node["glDrawingMode"]),
            name="glDrawingMode",
        )

        self._syncTypeRows()
        self._syncModeRows()

    def _addNote(self, form: GafferUI.Widget, text: str, name: str) -> None:
        label = GafferUI.Label(text)
        try:
            label._qtWidget().setWordWrap(True)
        except Exception:
            pass
        form.append(label)
        self._rows[name] = (label, label)

    def _buildSplitSection(self, node: Gaffer.Node) -> GafferUI.Widget:
        form = self._tab_form()
        form.append(GafferUI.Label("<h4>Camera</h4>"))
        form.append(GafferUI.Label("What camera rays see."))
        self._addSplitSide(form, node, "camera")
        form.append(GafferUI.Label("<h4>Lighting</h4>"))
        form.append(
            GafferUI.Label(
                "Diffuse, specular, transmission, volume, and shadow rays."
            )
        )
        self._addSplitSide(form, node, "lighting")
        try:
            section = GafferUI.Collapsible("Camera / Lighting", collapsed=False)
            section.setChild(form)
        except Exception:
            section = form
        expand_h(section)
        self._rows["splitSection"] = (section, section)
        return section

    def _addSplitSide(
        self, form: GafferUI.ListContainer, node: Gaffer.Node, side: str
    ) -> None:
        type_plug = node["cameraSkyType" if side == "camera" else "lightingSkyType"]
        exposure_plug = node[
            "cameraExposure" if side == "camera" else "lightingExposure"
        ]
        color_plug = node["cameraColor" if side == "camera" else "lightingColor"]
        type_row = self._addRow(
            form,
            "Type",
            GafferUI.PresetsPlugValueWidget(type_plug),
            name="split:{}:type".format(side),
        )
        self._addInlineShaderBools(type_row, node, side=side)
        if _side_grade_ready(node, side):
            self._addRow(
                form,
                "Exposure",
                GafferUI.NumericPlugValueWidget(exposure_plug),
                name="split:{}:exposure".format(side),
            )
        color_widget = _plug_widget(color_plug)
        if color_widget is not None:
            self._addRow(
                form,
                "Color",
                color_widget,
                name="split:{}:color".format(side),
            )
        for sky_type, _label in ARNOLD_SKY_TYPES:
            for plug in node.sideShaderParameterPlugs(side, sky_type):
                if plug.getName() in _INLINE_SHADER_BOOLS:
                    continue
                widget = _plug_widget(plug)
                if widget is None:
                    continue
                if plug.getName() in UV_PARAMETERS or _uv_section(plug):
                    self._addRow(
                        form,
                        _param_label(plug),
                        widget,
                        name="split:{}:uv:{}".format(side, plug.getName()),
                    )
                    continue
                self._addRow(
                    form,
                    _param_label(plug),
                    widget,
                    name="split:{}:shader:{}:{}".format(
                        side, sky_type, plug.getName()
                    ),
                )

    def _setRowEnabled(self, name: str, enabled: bool) -> None:
        row = self._rows.get(name)
        if row is None or not widget_is_alive(row[0]):
            return
        try:
            row[0].setEnabled(bool(enabled))
            return
        except Exception:
            pass
        try:
            row[0]._qtWidget().setEnabled(bool(enabled))
        except Exception:
            pass

    def _addInlineShaderBools(
        self,
        type_row: GafferUI.ListContainer,
        node: Gaffer.Node,
        side: str | None = None,
    ) -> None:
        """Sun / Sky checkboxes on an env-type row."""
        for sky_type, _label in ARNOLD_SKY_TYPES:
            if side is None:
                plugs = node.shaderParameterPlugs(sky_type)
            else:
                plugs = node.sideShaderParameterPlugs(side, sky_type)
            named = {plug.getName(): plug for plug in plugs}
            for name in _INLINE_SHADER_BOOLS:
                plug = named.get(name)
                if plug is None:
                    continue
                widget = _plug_widget(plug)
                if widget is None:
                    continue
                cell = GafferUI.ListContainer(
                    GafferUI.ListContainer.Orientation.Horizontal, spacing=4
                )
                cell.append(GafferUI.Label(_param_label(plug)))
                cell.append(widget)
                type_row.append(cell)
                if side is None:
                    row_name = "shader:{}:{}".format(sky_type, name)
                else:
                    row_name = "split:{}:shader:{}:{}".format(
                        side, sky_type, name
                    )
                self._rows[row_name] = (cell, widget)

    def _addNamedLightParams(
        self,
        form: GafferUI.ListContainer,
        node: Gaffer.Node,
        names: tuple[str, ...],
    ) -> None:
        plugs = {plug.getName(): plug for plug in node.parameterPlugs()}
        for name in names:
            plug = plugs.get(name)
            if plug is None:
                continue
            self._addLightParamRow(form, plug, "param")

    def _addLightParamRow(
        self,
        form: GafferUI.ListContainer,
        plug: Gaffer.Plug,
        prefix: str,
    ) -> None:
        widget = _plug_widget(plug)
        if widget is None:
            return
        self._addRow(
            form,
            _param_label(plug),
            widget,
            name="{}:{}".format(prefix, plug.getName()),
        )

    def _onPlugDirtied(self, plug: Gaffer.Plug) -> None:
        name = plug.getName()
        if name in ("skyType", "splitRays", "cameraSkyType", "lightingSkyType"):
            if name == "splitRays":
                try:
                    if bool(plug.getValue()):
                        self.__expandSplit()
                except Exception:
                    pass
            self.__syncTypeLazily()
        elif name == "mode":
            self.__syncModeLazily()

    def __expandSplit(self) -> None:
        row = self._rows.get("splitSection")
        if row is None or not widget_is_alive(row[0]):
            return
        setter = getattr(row[0], "setCollapsed", None)
        if callable(setter):
            setter(False)

    @GafferUI.LazyMethod()
    def __syncTypeLazily(self) -> None:
        self._syncTypeRows()

    @GafferUI.LazyMethod()
    def __syncModeLazily(self) -> None:
        self._syncModeRows()

    def _syncTypeRows(self) -> None:
        sky_type = self._node["skyType"].getValue()
        split = self._node.splitActive()
        shader_prefix = "shader:{}:".format(sky_type)
        driven = ARNOLD_SKY_DRIVEN_PARAMETERS.get(sky_type, frozenset())
        for name in self._rows:
            if name.startswith("shader:"):
                self._setRowVisible(
                    name, (not split) and name.startswith(shader_prefix)
                )
            elif name.startswith("param:"):
                plug_name = name.split(":", 1)[1]
                show = plug_name not in driven
                if split and plug_name == "color":
                    show = False
                self._setRowVisible(name, show)
            elif name.startswith("uv:"):
                self._setRowVisible(name, (not split) and sky_type == "skydome")
            elif name.startswith("split:"):
                self._setRowVisible(name, self._splitRowVisible(name))
        self._setRowVisible("splitSection", split)
        self._setRowVisible("splitLockHint", split)
        self._setRowEnabled("skyType", not split)
        self._setRowVisible("uvHint", (not split) and sky_type != "skydome")
        self._setRowVisible("uvSplitHint", split)

    def _splitRowVisible(self, name: str) -> bool:
        parts = name.split(":")
        if len(parts) < 3:
            return True
        side = parts[1]
        kind = parts[2]
        plug_name = "cameraSkyType" if side == "camera" else "lightingSkyType"
        try:
            side_type = self._node[plug_name].getValue()
        except Exception:
            side_type = ""
        if kind in ("type", "exposure"):
            return True
        if kind == "color":
            return side_type == "color"
        if kind == "uv":
            return side_type == "skydome"
        if kind == "shader" and len(parts) >= 4:
            return side_type == parts[3]
        return True

    def _syncModeRows(self) -> None:
        editing = self._node["mode"].getValue() == MODE_EDIT
        self._setRowVisible("editPath", editing)


def _envSkyWidgetCreator(node: Gaffer.Node) -> _EnvSkyWidget:
    return _EnvSkyWidget(node)


_sky_type_presets = {}
for _sky, _label in ARNOLD_SKY_TYPES:
    _sky_type_presets["preset:" + _label] = _sky

Gaffer.Metadata.registerNode(
    ArnoldPhysicalSky,
    "description",
    "Adds an Arnold environment skylight into the incoming scene. "
    "Split Camera / Lighting, on the Light tab, gives camera rays and "
    "lighting rays different colours on the same dome. Create authors "
    "physicalSkyN under Prim Path groups (default /LIGHTS, max 4, "
    "created only as needed); Edit loads an existing env light and "
    "authors over it at the same path.",
    "nodeGadget:color",
    SKY_CYAN,
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
    "layout:customWidget:envSky:widgetType",
    "ArnoldPhysicalSkyUI.ArnoldPhysicalSkyUI._envSkyWidgetCreator",
    "layout:customWidget:envSky:section",
    "Settings",
    "layout:customWidget:envSky:index",
    0,
    "layout:activator:never",
    False,
    plugs={
        "*": {
            "layout:visibilityActivator": "never",
        },
        "in": {
            "description": "Incoming scene the environment light is merged into. "
            "Drop the node on a scene connection to insert.",
            "nodule:type": "GafferUI::StandardNodule",
            "noduleLayout:section": "top",
            "noduleLayout:index": 0,
        },
        "out": {
            "description": "Incoming scene plus the skydome "
            "(passthrough of in when the node is disabled).",
            "nodule:type": "GafferUI::StandardNodule",
            "noduleLayout:section": "bottom",
            "noduleLayout:index": 0,
        },
        "enabled": {
            "description": "When off, the incoming scene passes through "
            "unchanged (no environment light merged).",
            "nodule:type": "",
        },
        "mode": {
            "description": "Create authors a new env light. Edit lists "
            "existing skydomes, loads their values, then authors this "
            "node's light at the same name and path.",
            "nodule:type": "",
            "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
            "preset:Create": "create",
            "preset:Edit": "edit",
        },
        "label": {
            "description": "Optional. Empty defaults to physicalSky1 / "
            "skydome1 / color1. Set a label for {label}1_physicalSky, …",
            "nodule:type": "",
        },
        "skyType": {
            "label": "Env Light Type",
            "description": "What drives the single skydome colour. "
            "Physical Sky is the default. Exclusive: HDRI, Physical "
            "Sky, or a plain colour. Locked while Split Camera / "
            "Lighting is on. The prim suffix is camelCase with no "
            "underscores (physicalSky, skydome, color).",
            "nodule:type": "",
            "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
            **_sky_type_presets,
        },
        "splitRays": {
            "label": "Split Camera / Lighting",
            "description": "Camera rays and lighting rays can use different "
            "colours on this one dome. Turning it on copies the current "
            "Env Light Type to both sides, then locks that menu. The "
            "single-type colour controls are replaced by the Camera / "
            "Lighting section. Dome Intensity, Exposure, and Transform "
            "still apply to both.",
            "nodule:type": "",
        },
        "cameraSkyType": {
            "label": "Camera Type",
            "description": "What camera rays see while Split is on. "
            "Replaces Env Light Type for the camera.",
            "nodule:type": "",
            "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
            **_sky_type_presets,
        },
        "lightingSkyType": {
            "label": "Lighting Type",
            "description": "What diffuse, specular, transmission, volume, "
            "and shadow rays see while Split is on.",
            "nodule:type": "",
            "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
            **_sky_type_presets,
        },
        "cameraExposure": {
            "label": "Camera Exposure",
            "description": "Extra stops for camera rays only. Dome "
            "Exposure on the Light tab is still applied to both sides.",
            "nodule:type": "",
        },
        "lightingExposure": {
            "label": "Lighting Exposure",
            "description": "Extra stops for lighting rays only. Dome "
            "Exposure on the Light tab is still applied to both sides.",
            "nodule:type": "",
        },
        "cameraColor": {
            "label": "Camera Color",
            "description": "Flat colour for camera rays when Camera Type "
            "is Color.",
            "nodule:type": "",
        },
        "lightingColor": {
            "label": "Lighting Color",
            "description": "Flat colour for lighting rays when Lighting "
            "Type is Color.",
            "nodule:type": "",
        },
        "name": {
            "description": "Leaf prim name (physicalSky1 by default, "
            "uniqued in Create mode).",
            "nodule:type": "",
        },
        "primPath": {
            "description": "Group path the skydome is placed under. "
            "Groups are created only for that path (default /LIGHTS, "
            "max 4). /apath and /apath/ are one group.",
            "nodule:type": "",
        },
        "editPath": {
            "description": "Existing env light to load in Edit mode. "
            "This node authors at that name and path.",
            "nodule:type": "",
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
            "description": "Transform applied to the enabled skydome "
            "(rotate Y to spin an HDRI). UV placement of an HDRI on "
            "the dome is on the UV Transform tab.",
            "nodule:type": "",
        },
    },
)

register_node_icon(ArnoldPhysicalSky, "ArnoldPhysicalSky.png")
