"""ArnoldPhysicalSky — boxed Arnold environment / skydome light.

Internal network: one ``skydome_light``. Sky Type is exclusive — HDRI
connects an ``image`` shader to colour, Physical Sky connects
``physical_sky``, Color leaves colour unconnected. Split Camera /
Lighting puts an Arnold ``ray_switch`` on that colour: camera rays
use one source, lighting rays use the other. Incoming scene + the
light go through MergeScenes, then a Transform, then Group nodes
created only for the current ``primPath`` (default ``/LIGHTS``, max 4),
then out.
"""

from __future__ import annotations

import Gaffer
import GafferScene
import IECore
import imath

from ._box import (
    BoxNetworkSerialiser,
    SceneInsertMixin,
    add_enabled_switch,
)
from ._data import (
    ARNOLD_SKY_DRIVEN_PARAMETERS,
    ARNOLD_SKY_SHADERS,
    COLOR_CORRECT_SHADER,
    CONTRIBUTION_PARAMETERS,
    IMAGE_SHADER,
    INTERNAL_RAY_SWITCH,
    RAY_SWITCH_SHADER,
    SKYDOME_LIGHT,
    SPLIT_CAMERA,
    SPLIT_LIGHTING,
    UV_PARAMETERS,
    side_grade_child,
    side_shader_child,
)
from ._insert import (
    SKY_SHADERS,
    LightInsertMixin,
    add_gl_drawing,
    add_group_chain,
    add_overlay_merge,
    add_public_insert_plugs,
    constructed_indexed_name,
    prim_type_token,
    script_is_loading,
    set_node_enabled,
)

_SPLIT_SYNC_PLUGS = frozenset(
    {
        "splitRays",
        "cameraSkyType",
        "lightingSkyType",
        "cameraExposure",
        "lightingExposure",
        "cameraColor",
        "lightingColor",
    }
)
_GRADE_INPUT_NAMES = ("input", "color", "texture")

INTERNAL_LIGHT = "__light"

DEFAULT_SKY_TYPE = "physical_sky"
DEFAULT_PRIM_NAME = constructed_indexed_name(
    "", prim_type_token(DEFAULT_SKY_TYPE), 1
)

_HDRI_EXTENSIONS = "exr hdr tx jpg jpeg png tif tiff"


def internal_light_name(sky_type: str | None = None) -> str:
    del sky_type
    return INTERNAL_LIGHT


def parameter_section(
    sky_type: str, plug_name: str, *, source: str = "light"
) -> str | None:
    """Node Editor tab for a parameter: ``light``, ``uv``, ``arnold``, or None."""
    if plug_name in UV_PARAMETERS:
        return "uv"
    if source != "light":
        return "light"
    if plug_name in ARNOLD_SKY_DRIVEN_PARAMETERS.get(sky_type, ()):
        return None
    if plug_name in CONTRIBUTION_PARAMETERS:
        return "arnold"
    return "light"


def sky_parameter_allowed(
    sky_type: str, plug_name: str, *, contribution: bool, source: str = "light"
) -> bool:
    """Whether *plug_name* should appear on the Light or Arnold tab."""
    section = parameter_section(sky_type, plug_name, source=source)
    if contribution:
        return section == "arnold"
    return section == "light"


class ArnoldPhysicalSky(LightInsertMixin, SceneInsertMixin, Gaffer.Box):
    """Merge an Arnold skydome / physical-sky env light into a scene."""

    TYPE_PLUG = "skyType"
    EXISTING_SHADER_ALLOW = SKY_SHADERS
    GRAPH_NAME_PREFIX = "ArnoldPhysicalSky"
    GRAPH_NAME_INCLUDE_PRIM = False

    def __init__(self, name: str = "ArnoldPhysicalSky"):
        Gaffer.Box.__init__(self, name)

        try:
            import GafferArnold
        except Exception as exc:
            raise IECore.Exception(
                "ArnoldPhysicalSky requires GafferArnold ({})".format(exc)
            )

        self.addChild(GafferScene.ScenePlug("in", Gaffer.Plug.Direction.In))
        add_public_insert_plugs(self, DEFAULT_PRIM_NAME, default_label="")
        self.addChild(
            Gaffer.StringPlug("skyType", defaultValue=DEFAULT_SKY_TYPE)
        )
        self.addChild(Gaffer.BoolPlug("splitRays", defaultValue=False))
        self.addChild(
            Gaffer.StringPlug("cameraSkyType", defaultValue=DEFAULT_SKY_TYPE)
        )
        self.addChild(
            Gaffer.StringPlug("lightingSkyType", defaultValue=DEFAULT_SKY_TYPE)
        )
        self.addChild(
            Gaffer.FloatPlug(
                "cameraExposure", defaultValue=0.0, minValue=-8.0, maxValue=8.0
            )
        )
        self.addChild(
            Gaffer.FloatPlug(
                "lightingExposure",
                defaultValue=0.0,
                minValue=-8.0,
                maxValue=8.0,
            )
        )
        self.addChild(
            Gaffer.Color3fPlug(
                "cameraColor", defaultValue=imath.Color3f(1, 1, 1)
            )
        )
        self.addChild(
            Gaffer.Color3fPlug(
                "lightingColor", defaultValue=imath.Color3f(1, 1, 1)
            )
        )
        self.addChild(Gaffer.TransformPlug("transform"))
        self._splitWas = False
        self._seedingSplit = False

        light = self.__make_light(GafferArnold)
        if light is None:
            raise IECore.Exception(
                "ArnoldPhysicalSky could not create a skydome light"
            )
        self.__make_shaders(GafferArnold)

        path_filter = GafferScene.PathFilter("__pathFilter")
        self.addChild(path_filter)
        path_filter["paths"].setValue(
            IECore.StringVectorData(["/" + DEFAULT_PRIM_NAME])
        )

        xform = GafferScene.Transform("__transform")
        self.addChild(xform)
        xform["in"].setInput(light["out"])
        xform["filter"].setInput(path_filter["out"])
        xform["transform"].setInput(self["transform"])

        gl_drawn = add_gl_drawing(self, xform["out"], path_filter["out"])
        grouped = add_group_chain(self, gl_drawn)
        merge_scene = add_overlay_merge(self, self["in"], grouped)

        switch = add_enabled_switch(self, merge_scene["out"])
        Gaffer.PlugAlgo.promote(switch["out"])

        self._bind_insert_signals()
        self._sync_active_nodes()
        self._sync_driven_plugs()
        self._splitWas = self.splitActive()

    def _internal_light_name(self, shader: str) -> str:
        return internal_light_name(shader)

    def splitAvailable(self) -> bool:
        """True when this Arnold build has a usable ``ray_switch`` shader."""
        switch = self.getChild(INTERNAL_RAY_SWITCH)
        if switch is None or "out" not in switch or "parameters" not in switch:
            return False
        try:
            plug = switch["parameters"]["camera"]
        except Exception:
            return False
        return isinstance(plug, (Gaffer.Color3fPlug, Gaffer.Color4fPlug))

    def splitActive(self) -> bool:
        """True when Split is checked and ``ray_switch`` can drive the dome."""
        if not self.splitAvailable():
            return False
        try:
            return bool(self["splitRays"].getValue())
        except Exception:
            return False

    def _sync_active_nodes(self) -> None:
        try:
            kind = (self["skyType"].getValue() or "").strip() or DEFAULT_SKY_TYPE
        except Exception:
            kind = DEFAULT_SKY_TYPE
        split = self.splitActive()
        light = self.getChild(INTERNAL_LIGHT)
        if light is not None:
            set_node_enabled(light, True)
            if split:
                self.__connect_split(light)
            else:
                self.__connect_sky_color(light, kind)
        camera_type = self.__side_type(SPLIT_CAMERA)
        lighting_type = self.__side_type(SPLIT_LIGHTING)
        for sky_type, spec in ARNOLD_SKY_SHADERS.items():
            main = self.getChild(spec[1])
            if main is not None:
                active = camera_type == sky_type if split else kind == sky_type
                set_node_enabled(main, active)
            lighting = self.getChild(spec[1] + "_lighting")
            if lighting is not None:
                set_node_enabled(lighting, split and lighting_type == sky_type)
        for side in (SPLIT_CAMERA, SPLIT_LIGHTING):
            grade = self.getChild(side_grade_child(side))
            if grade is not None:
                set_node_enabled(grade, split)
        switch = self.getChild(INTERNAL_RAY_SWITCH)
        if switch is not None:
            set_node_enabled(switch, split)

    def _on_insert_plug_set(self, plug: Gaffer.Plug) -> None:
        name = plug.getName()
        if name == "splitRays":
            try:
                current = bool(plug.getValue())
            except Exception:
                current = False
            previous = bool(getattr(self, "_splitWas", current))
            self._splitWas = current
            if (
                current
                and not previous
                and not script_is_loading(self)
                and not getattr(self, "_seedingSplit", False)
                and self.splitAvailable()
            ):
                self.__seed_split_from_current()
        super()._on_insert_plug_set(plug)
        if name in _SPLIT_SYNC_PLUGS and not getattr(self, "_seedingSplit", False):
            self._sync_active_nodes()

    def _on_script_loaded(self, *args) -> None:
        super()._on_script_loaded(*args)
        self._splitWas = self.splitActive()

    def _apply_loaded_shaders(self, output_name: str, shaders: dict) -> None:
        from ._insert import _set_plug_from_data

        if "physical_sky" in shaders:
            sky_type = "physical_sky"
        elif "image" in shaders:
            sky_type = "skydome"
        else:
            sky_type = "color"
        try:
            self["skyType"].setValue(sky_type)
        except Exception:
            pass
        light = self.getChild(INTERNAL_LIGHT)
        skydome = shaders.get("skydome_light") or shaders.get(output_name)
        if light is not None and skydome is not None and "parameters" in light:
            params = getattr(skydome, "parameters", None)
            items = params.items() if params is not None and hasattr(params, "items") else []
            for name, data in items:
                if name in light["parameters"]:
                    _set_plug_from_data(light["parameters"][name], data)
        spec = ARNOLD_SKY_SHADERS.get(sky_type)
        if not spec:
            return
        shader_name, child_name = spec
        if child_name not in self or shader_name not in shaders:
            return
        shader_node = self[child_name]
        loaded = shaders[shader_name]
        params = getattr(loaded, "parameters", None)
        if "parameters" not in shader_node or params is None:
            return
        items = params.items() if hasattr(params, "items") else []
        for name, data in items:
            if name in shader_node["parameters"]:
                _set_plug_from_data(shader_node["parameters"][name], data)

    def activeLight(self) -> Gaffer.Node | None:
        return self.getChild(INTERNAL_LIGHT)

    def activeShader(self) -> Gaffer.Node | None:
        sky_type = self["skyType"].getValue()
        spec = ARNOLD_SKY_SHADERS.get(sky_type)
        if not spec:
            return None
        _shader, child_name = spec
        return self[child_name] if child_name in self else None

    def copyValues(self) -> dict:
        """Snapshot type, transform, GL drawing, and shader parameters."""
        from ._values import snapshot

        return snapshot(self)

    def pasteValues(self, data: dict | None) -> int:
        """Apply a snapshot from :meth:`copyValues`. Returns plugs written."""
        from ._values import apply_snapshot

        return apply_snapshot(self, data)

    def resetValues(self) -> None:
        """Restore look plugs to defaults. Keeps prim path, name, and mode."""
        from ._values import reset_values

        reset_values(self)

    def parameterPlugs(self, sky_type: str | None = None):
        del sky_type
        light = self.getChild(INTERNAL_LIGHT)
        if light is None:
            return []
        return self.__editable_params(light)

    def lightLinkingPlugs(self):
        light = self.getChild(INTERNAL_LIGHT)
        if light is None:
            return []
        plugs = []
        for name in ("defaultLight", "mute", "sets"):
            if name in light:
                plugs.append(light[name])
        return plugs

    def visualisationPlugs(self):
        light = self.getChild(INTERNAL_LIGHT)
        if light is None or "visualiserAttributes" not in light:
            return []
        return [
            plug
            for plug in light["visualiserAttributes"].children()
            if isinstance(plug, Gaffer.Plug) and not plug.getName().startswith("__")
        ]

    def shaderParameterPlugs(self, sky_type: str | None = None):
        sky = sky_type or self["skyType"].getValue()
        spec = ARNOLD_SKY_SHADERS.get(sky)
        if not spec:
            return []
        _shader, child_name = spec
        if child_name not in self:
            return []
        return self.__editable_params(self[child_name])

    def sideShaderParameterPlugs(self, side: str, sky_type: str):
        child_name = side_shader_child(side, sky_type)
        if not child_name or child_name not in self:
            return []
        return self.__editable_params(self[child_name])

    @staticmethod
    def __editable_params(node: Gaffer.Node):
        if "parameters" not in node:
            return []
        return [
            plug
            for plug in node["parameters"].children()
            if ArnoldPhysicalSky.__is_editable_param(plug)
        ]

    @staticmethod
    def __is_editable_param(plug: Gaffer.Plug) -> bool:
        if plug.getName().startswith("__"):
            return False
        if plug.direction() != Gaffer.Plug.Direction.In:
            return False
        if plug.getName() in ("out", "type", "name", "shader", "attributeSuffix"):
            return False
        return True

    def __make_light(self, GafferArnold):
        try:
            light = GafferArnold.ArnoldLight(INTERNAL_LIGHT)
            light.loadShader(SKYDOME_LIGHT)
        except Exception as exc:
            IECore.msg(
                IECore.Msg.Level.Warning,
                "ArnoldPhysicalSky",
                "Could not create skydome ({})".format(exc),
            )
            return None
        self.addChild(light)
        if "name" in light:
            light["name"].setInput(self["name"])
        self.__enable_camera_contribution(light)
        return light

    def __make_shaders(self, GafferArnold) -> None:
        for _sky_type, spec in ARNOLD_SKY_SHADERS.items():
            shader_name, child_name = spec
            self.__make_shader(GafferArnold, shader_name, child_name)
            self.__make_shader(
                GafferArnold, shader_name, child_name + "_lighting"
            )
        self.__make_shader(GafferArnold, RAY_SWITCH_SHADER, INTERNAL_RAY_SWITCH)
        self.__make_shader(
            GafferArnold, COLOR_CORRECT_SHADER, side_grade_child(SPLIT_CAMERA)
        )
        self.__make_shader(
            GafferArnold,
            COLOR_CORRECT_SHADER,
            side_grade_child(SPLIT_LIGHTING),
        )

    def __make_shader(self, GafferArnold, shader_name: str, child_name: str):
        existing = self.getChild(child_name)
        if existing is not None:
            return existing
        try:
            shader = GafferArnold.ArnoldShader(child_name)
            shader.loadShader(shader_name)
        except Exception as exc:
            IECore.msg(
                IECore.Msg.Level.Warning,
                "ArnoldPhysicalSky",
                "Could not create {} shader ({})".format(shader_name, exc),
            )
            return None
        self.addChild(shader)
        if shader_name == IMAGE_SHADER:
            self.__tag_hdri_filename(shader)
        return shader

    def __side_type(self, side: str) -> str:
        plug_name = "cameraSkyType" if side == SPLIT_CAMERA else "lightingSkyType"
        try:
            return (self[plug_name].getValue() or "").strip() or DEFAULT_SKY_TYPE
        except Exception:
            return DEFAULT_SKY_TYPE

    def __seed_split_from_current(self) -> None:
        """Match both sides to the current Env Light Type, once, as Split turns on."""
        try:
            kind = (self["skyType"].getValue() or "").strip() or DEFAULT_SKY_TYPE
        except Exception:
            kind = DEFAULT_SKY_TYPE
        dome_color = self.__read_dome_color()
        copied = self.__read_shader_values(kind)
        self._seedingSplit = True
        try:
            self.__set_if_diff(self["cameraSkyType"], kind)
            self.__set_if_diff(self["lightingSkyType"], kind)
            self.__set_if_diff(self["cameraExposure"], 0.0)
            self.__set_if_diff(self["lightingExposure"], 0.0)
            if dome_color is not None:
                self.__set_if_diff(self["cameraColor"], dome_color)
                self.__set_if_diff(self["lightingColor"], dome_color)
            self.__write_lighting_shader(kind, copied)
        finally:
            self._seedingSplit = False

    def __read_dome_color(self):
        light = self.getChild(INTERNAL_LIGHT)
        if light is None or "parameters" not in light or "color" not in light["parameters"]:
            return None
        plug = light["parameters"]["color"]
        try:
            if plug.getInput() is not None:
                return None
            value = plug.getValue()
            return imath.Color3f(value[0], value[1], value[2])
        except Exception:
            return None

    def __read_shader_values(self, sky_type: str) -> dict:
        spec = ARNOLD_SKY_SHADERS.get(sky_type)
        if not spec:
            return {}
        shader = self.getChild(spec[1])
        if shader is None or "parameters" not in shader:
            return {}
        values = {}
        for plug in shader["parameters"].children():
            if not self.__is_editable_param(plug):
                continue
            try:
                if plug.getInput() is not None:
                    continue
                values[plug.getName()] = plug.getValue()
            except Exception:
                continue
        return values

    def __write_lighting_shader(self, sky_type: str, values: dict) -> None:
        child_name = side_shader_child(SPLIT_LIGHTING, sky_type)
        if not child_name:
            return
        shader = self.getChild(child_name)
        if shader is None or "parameters" not in shader:
            return
        for name, value in values.items():
            if name not in shader["parameters"]:
                continue
            self.__set_if_diff(shader["parameters"][name], value)

    @staticmethod
    def __set_if_diff(plug: Gaffer.Plug, value) -> None:
        try:
            if plug.getInput() is not None:
                return
        except Exception:
            pass
        try:
            if plug.getValue() == value:
                return
        except Exception:
            pass
        try:
            plug.setValue(value)
        except Exception:
            pass

    def __connect_sky_color(self, light: Gaffer.Node, sky_type: str) -> None:
        if "parameters" not in light or "color" not in light["parameters"]:
            return
        spec = ARNOLD_SKY_SHADERS.get(sky_type)
        if not spec:
            self.__set_input(light["parameters"]["color"], None)
            return
        shader = self.getChild(spec[1])
        if shader is None:
            return
        self.__connect_color(light, shader)
        if spec[0] == IMAGE_SHADER:
            self.__set_hdri_format(light)

    def __connect_split(self, light: Gaffer.Node) -> None:
        switch = self.getChild(INTERNAL_RAY_SWITCH)
        if (
            switch is None
            or "out" not in switch
            or "parameters" not in light
            or "color" not in light["parameters"]
        ):
            return
        self.__connect_color(light, switch)
        camera_out = self.__drive_side(SPLIT_CAMERA)
        lighting_out = self.__drive_side(SPLIT_LIGHTING)
        if "parameters" not in switch:
            return
        for plug in switch["parameters"].children():
            if not isinstance(plug, (Gaffer.Color3fPlug, Gaffer.Color4fPlug)):
                continue
            source = camera_out if plug.getName() == "camera" else lighting_out
            if source is not None:
                self.__set_input(plug, source)
            else:
                side = SPLIT_CAMERA if plug.getName() == "camera" else SPLIT_LIGHTING
                self.__set_side_color(plug, side)
        if self.__side_type(SPLIT_CAMERA) == "skydome" or self.__side_type(
            SPLIT_LIGHTING
        ) == "skydome":
            self.__set_hdri_format(light)

    def __drive_side(self, side: str):
        """Return the plug that should feed this side, or None for a flat colour."""
        kind = self.__side_type(side)
        grade = self.getChild(side_grade_child(side))
        source = None
        child_name = side_shader_child(side, kind)
        shader = self.getChild(child_name) if child_name else None
        if shader is not None and "out" in shader and kind in ARNOLD_SKY_SHADERS:
            source = shader["out"]
        if grade is None or "out" not in grade:
            return source
        grade_input = self.__grade_input(grade)
        if grade_input is None:
            return source
        self.__set_grade_exposure(grade, side)
        if source is not None:
            self.__set_input(grade_input, source)
        else:
            self.__set_side_color(grade_input, side)
        return grade["out"]

    def __set_grade_exposure(self, grade: Gaffer.Node, side: str) -> None:
        if "parameters" not in grade or "multiply" not in grade["parameters"]:
            return
        plug_name = "cameraExposure" if side == SPLIT_CAMERA else "lightingExposure"
        try:
            stops = float(self[plug_name].getValue())
        except Exception:
            stops = 0.0
        factor = 2.0 ** stops
        self.__set_color_value(
            grade["parameters"]["multiply"], imath.Color3f(factor, factor, factor)
        )

    def __set_side_color(self, plug: Gaffer.Plug, side: str) -> None:
        plug_name = "cameraColor" if side == SPLIT_CAMERA else "lightingColor"
        try:
            color = self[plug_name].getValue()
        except Exception:
            color = imath.Color3f(1, 1, 1)
        self.__set_color_value(plug, color)

    @staticmethod
    def __grade_input(grade: Gaffer.Node):
        if "parameters" not in grade:
            return None
        for name in _GRADE_INPUT_NAMES:
            if name in grade["parameters"]:
                plug = grade["parameters"][name]
                if isinstance(plug, (Gaffer.Color3fPlug, Gaffer.Color4fPlug)):
                    return plug
        return None

    @staticmethod
    def __set_input(plug: Gaffer.Plug, source) -> None:
        if plug is None:
            return
        try:
            current = plug.getInput()
        except Exception:
            current = None
        if source is None:
            if current is not None:
                try:
                    plug.setInput(None)
                except Exception:
                    pass
            return
        try:
            if current is not None and current.isSame(source):
                return
            plug.setInput(source)
        except Exception as exc:
            IECore.msg(
                IECore.Msg.Level.Warning,
                "ArnoldPhysicalSky",
                "Could not connect {} ({})".format(plug.getName(), exc),
            )

    @staticmethod
    def __set_color_value(plug: Gaffer.Plug, color) -> None:
        if plug is None:
            return
        try:
            if plug.getInput() is not None:
                plug.setInput(None)
        except Exception:
            pass
        try:
            if isinstance(plug, Gaffer.Color4fPlug):
                value = imath.Color4f(color[0], color[1], color[2], 1.0)
            elif isinstance(plug, Gaffer.Color3fPlug):
                value = imath.Color3f(color[0], color[1], color[2])
            elif isinstance(plug, Gaffer.FloatPlug):
                value = float(color[0])
            else:
                value = color
        except Exception:
            value = color
        try:
            if plug.getValue() == value:
                return
        except Exception:
            pass
        try:
            plug.setValue(value)
        except Exception:
            pass

    def __connect_color(self, light: Gaffer.Node, shader: Gaffer.Node) -> None:
        if "parameters" not in light or "color" not in light["parameters"]:
            return
        out_plug = shader["out"] if "out" in shader else None
        if out_plug is None:
            return
        self.__set_input(light["parameters"]["color"], out_plug)

    @staticmethod
    def __set_hdri_format(light: Gaffer.Node) -> None:
        if "parameters" not in light or "format" not in light["parameters"]:
            return
        try:
            light["parameters"]["format"].setValue("latlong")
        except Exception:
            pass

    @staticmethod
    def __enable_camera_contribution(light: Gaffer.Node) -> None:
        """Skydome camera weight defaults to 1 so the env is visible in beauty."""
        if "parameters" not in light or "camera" not in light["parameters"]:
            return
        plug = light["parameters"]["camera"]
        setter = getattr(plug, "setValue", None)
        getter = getattr(plug, "getValue", None)
        if not callable(setter):
            return
        try:
            current = getter() if callable(getter) else None
        except Exception:
            current = None
        if current not in (None, 0, 0.0, False):
            return
        try:
            setter(1)
        except Exception:
            try:
                setter(1.0)
            except Exception:
                pass

    @staticmethod
    def __tag_hdri_filename(shader: Gaffer.Node) -> None:
        if "parameters" not in shader or "filename" not in shader["parameters"]:
            return
        plug = shader["parameters"]["filename"]
        Gaffer.Metadata.registerValue(
            plug, "plugValueWidget:type", "GafferUI.FileSystemPathPlugValueWidget"
        )
        Gaffer.Metadata.registerValue(plug, "path:leaf", True)
        Gaffer.Metadata.registerValue(plug, "path:valid", False)
        Gaffer.Metadata.registerValue(
            plug, "fileSystemPath:extensions", _HDRI_EXTENSIONS
        )
        Gaffer.Metadata.registerValue(
            plug, "fileSystemPath:extensionsLabel", "HDRI"
        )


ArnoldPhysicalSky.__module__ = "ArnoldPhysicalSky.ArnoldPhysicalSky"
IECore.registerRunTimeTyped(ArnoldPhysicalSky)

Gaffer.Metadata.registerNode(
    ArnoldPhysicalSky,
    "description",
    "Adds an Arnold environment skylight (HDRI / Physical Sky / Color) "
    "into the incoming scene. One skydome; Sky Type connects colour. "
    "Split Camera / Lighting feeds camera rays and lighting rays from "
    "different sources. Create authors physicalSkyN (or skydomeN / "
    "colorN). Optional Label prefixes the prim. Edit loads an existing "
    "env light and authors over it at the same path.",
)


class _EnvSkySerialiser(BoxNetworkSerialiser):
    """Rebuild internals in ``__init__``; persist shader/light parameters."""

    def childNeedsConstruction(
        self, child: Gaffer.GraphComponent, serialisation: Gaffer.Serialisation
    ) -> bool:
        if isinstance(child, Gaffer.Node):
            return False
        if isinstance(child, Gaffer.Plug) and child.getName() == "out":
            return False
        if child.getName() == "__uiPosition":
            return True
        return super().childNeedsConstruction(child, serialisation)


Gaffer.Serialisation.registerSerialiser(ArnoldPhysicalSky, _EnvSkySerialiser())
