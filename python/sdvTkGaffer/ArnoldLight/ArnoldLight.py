"""ArnoldLight — boxed scene-in / light-out merge.

One internal ``ArnoldLight`` is loaded as Area (quad) by default.
Changing Light Type calls ``loadShader`` on that node so only the
chosen type's parameters exist. Mesh Light is a separate
``ArnoldMeshLight``. Incoming scene + the active light go through
a Transform, then Group nodes for ``primPath`` (default ``/LIGHTS``,
max 4), then MergeScenes. A spot gobo (filter, map shader, and the
group that parents it) is created only while Gobo Map is in use.
``filteredLights`` points at this light, and the map connects to
``slidemap``.

This is ``ArnoldLight.ArnoldLight``, not ``GafferArnold.ArnoldLight``.
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
    ARNOLD_LIGHT_TYPES,
    GOBO_MAP_CELL,
    GOBO_MAP_FILE,
    GOBO_MAP_NOISE,
    GOBO_MAP_OFF,
    GOBO_GROUP_NAME,
    INTERNAL_GOBO,
    INTERNAL_GOBO_CELL,
    INTERNAL_GOBO_GROUP,
    INTERNAL_GOBO_IMAGE,
    INTERNAL_GOBO_NOISE,
    INTERNAL_LIGHT,
    MESH_LIGHT,
    SPOT_LIGHT,
    parameter_section,
    uses_mesh_light_node,
)
from ._insert import (
    SKY_SHADERS,
    LightInsertMixin,
    add_gl_drawing,
    add_group_chain,
    add_overlay_merge,
    add_public_insert_plugs,
    constructed_indexed_name,
    join_path,
    path_parts,
    prim_type_token,
    script_is_loading,
    set_node_enabled,
    set_plug_value,
    set_switch_index,
    _remove_internal_node,
)

DEFAULT_LIGHT_TYPE = ARNOLD_LIGHT_TYPES[0][0]  # quad_light / Area
NAME_TYPE_ALIASES = {
    "quad_light": "areaLight",
    "disk_light": "diskLight",
    "cylinder_light": "cylinderLight",
    "point_light": "pointLight",
    "spot_light": "spotLight",
    "distant_light": "distantLight",
    "photometric_light": "photometricLight",
    "mesh_light": "meshLight",
}
DEFAULT_PRIM_NAME = constructed_indexed_name(
    "label", prim_type_token(DEFAULT_LIGHT_TYPE, NAME_TYPE_ALIASES), 1
)


def _capture_parameters(parameters: Gaffer.Plug) -> dict:
    values = {}
    for plug in parameters.children():
        if not isinstance(plug, Gaffer.Plug):
            continue
        _capture_plug(plug, plug.getName(), values)
    return values


def _capture_plug(plug: Gaffer.Plug, path: str, values: dict) -> None:
    if plug.getInput() is not None or plug.getName().startswith("__"):
        return
    getter = getattr(plug, "getValue", None)
    if callable(getter) and not isinstance(plug, Gaffer.TransformPlug):
        try:
            encoded = _json_value(getter())
        except Exception:
            encoded = None
        if encoded is not None:
            values[path] = encoded
            return
    for child in plug.children():
        if isinstance(child, Gaffer.Plug):
            _capture_plug(child, path + "." + child.getName(), values)


def _json_value(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, str)):
        return value
    if hasattr(value, "r") and hasattr(value, "g") and hasattr(value, "b"):
        parts = [float(value.r), float(value.g), float(value.b)]
        if hasattr(value, "a"):
            parts.append(float(value.a))
        return parts
    if hasattr(value, "x") and hasattr(value, "y"):
        parts = [float(value.x), float(value.y)]
        if hasattr(value, "z"):
            parts.append(float(value.z))
        if hasattr(value, "w"):
            parts.append(float(value.w))
        return parts
    return None


def _apply_parameters(parameters: Gaffer.Plug, values: dict) -> None:
    for path, value in values.items():
        plug = parameters
        for part in str(path).split("."):
            if part not in plug:
                plug = None
                break
            plug = plug[part]
        if plug is None:
            continue
        _apply_json(plug, value)


def _apply_json(plug: Gaffer.Plug, value) -> None:
    if plug.getInput() is not None:
        return
    setter = getattr(plug, "setValue", None)
    if not callable(setter):
        return
    try:
        if isinstance(value, list):
            kind = plug.typeName()
            if "Color3f" in kind and len(value) >= 3:
                setter(imath.Color3f(*value[:3]))
                return
            if "Color4f" in kind and len(value) >= 4:
                setter(imath.Color4f(*value[:4]))
                return
            if "V3f" in kind and len(value) >= 3:
                setter(imath.V3f(*value[:3]))
                return
            if "V2f" in kind and len(value) >= 2:
                setter(imath.V2f(*value[:2]))
                return
        setter(value)
    except Exception:
        pass


def internal_light_name(shader_name: str) -> str:
    return "__light_{}".format(shader_name)


def parameter_allowed(
    shader_name: str, plug_name: str, *, contribution: bool, section: str | None = None
) -> bool:
    """Whether *plug_name* should appear on Light / Shaping / Arnold."""
    del shader_name
    wanted = parameter_section(plug_name)
    if section is not None:
        return wanted == section
    if contribution:
        return wanted == "arnold"
    return wanted != "arnold"


class ArnoldLight(LightInsertMixin, SceneInsertMixin, Gaffer.Box):
    """Merge an Arnold light into an incoming scene.

    Public plugs: ``in``, ``out``, ``mode``, ``label``, ``lightType``,
    ``name``, ``primPath``, ``editPath``, ``transform``, ``goboMap``.

    For Mesh Light, ``primPath`` is the location(s) that emit light
    (PathFilter on the internal ``ArnoldMeshLight``, which reads this
    node's ``in``). A Gaffer expression on ``primPath`` is supported.
    """

    TYPE_PLUG = "lightType"
    NAME_TYPE_ALIASES = NAME_TYPE_ALIASES
    EXISTING_SHADER_DENY = SKY_SHADERS
    GRAPH_NAME_PREFIX = "ArnoldLight"
    GRAPH_ICON = "ArnoldLight.png"
    GRAPH_ICON_EDIT = "ArnoldLightEdit.png"
    GRAPH_COLOR = imath.Color3f(230 / 255, 178 / 255, 72 / 255)
    GRAPH_COLOR_EDIT = imath.Color3f(224 / 255, 198 / 255, 148 / 255)

    def __init__(self, name: str = "ArnoldLight"):
        Gaffer.Box.__init__(self, name)

        try:
            import GafferArnold
        except Exception as exc:
            raise IECore.Exception(
                "ArnoldLight requires GafferArnold ({})".format(exc)
            )

        self.addChild(GafferScene.ScenePlug("in", Gaffer.Plug.Direction.In))
        add_public_insert_plugs(self, DEFAULT_PRIM_NAME)
        self.addChild(
            Gaffer.StringPlug("lightType", defaultValue=DEFAULT_LIGHT_TYPE)
        )
        self.addChild(Gaffer.StringPlug("goboMap", defaultValue=GOBO_MAP_OFF))
        gobo_state = Gaffer.StringPlug("goboState", defaultValue="")
        self.addChild(gobo_state)
        Gaffer.Metadata.registerValue(gobo_state, "nodule:type", "")
        self.addChild(Gaffer.TransformPlug("transform"))

        light = self.__make_light(GafferArnold, DEFAULT_LIGHT_TYPE)
        if light is None:
            raise IECore.Exception("ArnoldLight could not create an Area light")
        self.addChild(light)
        if "name" in light:
            light["name"].setInput(self["name"])

        mesh_light = self.__make_light(GafferArnold, MESH_LIGHT)
        mesh_filter = GafferScene.PathFilter("__meshFilter")
        self.addChild(mesh_filter)
        if mesh_light is not None:
            self.addChild(mesh_light)
            if "in" in mesh_light:
                mesh_light["in"].setInput(self["in"])
            if "filter" in mesh_light:
                mesh_light["filter"].setInput(mesh_filter["out"])

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
        grouped = add_group_chain(
            self, gl_drawn, extra_sources=self._group_chain_extra_sources()
        )
        merge_scene = add_overlay_merge(self, self["in"], grouped)

        processed = merge_scene["out"]
        if mesh_light is not None:
            mesh_switch = Gaffer.Switch("__meshSwitch")
            self.addChild(mesh_switch)
            mesh_switch.setup(GafferScene.ScenePlug("in"))
            mesh_switch["in"].resize(2)
            mesh_switch["in"][0].setInput(merge_scene["out"])
            mesh_switch["in"][1].setInput(mesh_light["out"])
            processed = mesh_switch["out"]

        switch = add_enabled_switch(self, processed)
        Gaffer.PlugAlgo.promote(switch["out"])

        self._bind_insert_signals()
        self._sync_active_nodes()
        self._sync_driven_plugs()

    def _internal_light_name(self, shader: str) -> str:
        if uses_mesh_light_node(shader) or shader == MESH_LIGHT:
            return internal_light_name(MESH_LIGHT)
        return INTERNAL_LIGHT

    def _group_prim_path(self) -> str:
        try:
            if self["lightType"].getValue() == MESH_LIGHT:
                return ""
        except Exception:
            pass
        return super()._group_prim_path()

    def _sync_active_nodes(self) -> None:
        kind = self._current_type()
        mesh = kind == MESH_LIGHT
        light = self.getChild(INTERNAL_LIGHT)
        if light is not None:
            set_node_enabled(light, not mesh)
        mesh_node = self.getChild(internal_light_name(MESH_LIGHT))
        if mesh_node is not None:
            set_node_enabled(mesh_node, mesh)
            for nested in mesh_node.children(Gaffer.Node):
                set_node_enabled(nested, mesh)
        set_switch_index(self, "__meshSwitch", 1 if mesh else 0)
        mesh_filter = self.getChild("__meshFilter")
        if mesh_filter is not None:
            set_node_enabled(mesh_filter, mesh)
        self._sync_gobo()

    def _on_type_changed(self, previous: str, current: str) -> None:
        from ._values import transfer_parameters

        prev_mesh = uses_mesh_light_node(previous) or previous == MESH_LIGHT
        curr_mesh = uses_mesh_light_node(current) or current == MESH_LIGHT

        def _apply() -> None:
            if not prev_mesh and not curr_mesh:
                self.__reload_regular_shader(current)
            else:
                if not curr_mesh:
                    self.__reload_regular_shader(current)
                transfer_parameters(self, previous, current)

        script = self.scriptNode()
        if script is not None:
            with Gaffer.UndoScope(script):
                _apply()
        else:
            _apply()
        self._sync_gobo()

    def _load_edit_target(self, path: str) -> None:
        super()._load_edit_target(path)
        try:
            if self["lightType"].getValue() != MESH_LIGHT:
                return
        except Exception:
            return
        location = (path or "").strip().replace("\\", "/")
        if not location:
            return
        if not location.startswith("/"):
            location = "/" + location
        try:
            self["primPath"].setValue(location)
        except Exception:
            pass

    def activeLight(self) -> Gaffer.Node | None:
        child_name = self._internal_light_name(self["lightType"].getValue())
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

    def parameterPlugs(self, shader_name: str | None = None):
        current = self["lightType"].getValue()
        shader = shader_name or current
        if shader_name is not None and shader != current:
            return []
        child_name = self._internal_light_name(shader)
        if child_name not in self:
            return []
        light = self[child_name]
        if "parameters" not in light:
            return []
        return [
            plug
            for plug in light["parameters"].children()
            if self.__is_editable_param(plug)
        ]

    def goboFilter(self) -> Gaffer.Node | None:
        return self.getChild(INTERNAL_GOBO)

    def goboMapShader(self) -> Gaffer.Node | None:
        kind = ""
        try:
            kind = (self["goboMap"].getValue() or "").strip()
        except Exception:
            kind = ""
        names = {
            GOBO_MAP_FILE: INTERNAL_GOBO_IMAGE,
            GOBO_MAP_NOISE: INTERNAL_GOBO_NOISE,
            GOBO_MAP_CELL: INTERNAL_GOBO_CELL,
        }
        child = names.get(kind)
        return self.getChild(child) if child else None

    @staticmethod
    def __is_editable_param(plug: Gaffer.Plug) -> bool:
        if plug.getName().startswith("__"):
            return False
        if plug.direction() != Gaffer.Plug.Direction.In:
            return False
        if plug.getName() in ("out", "type", "name", "shader", "attributeSuffix"):
            return False
        return True

    def __getitem__(self, key):
        if isinstance(key, str):
            self._ensure_named_gobo_child(key)
        return Gaffer.Box.__getitem__(self, key)

    def _gobo_shader_names(self) -> dict:
        return {
            GOBO_MAP_FILE: INTERNAL_GOBO_IMAGE,
            GOBO_MAP_NOISE: INTERNAL_GOBO_NOISE,
            GOBO_MAP_CELL: INTERNAL_GOBO_CELL,
        }

    def _gobo_rig_names(self) -> tuple:
        return (
            INTERNAL_GOBO,
            INTERNAL_GOBO_GROUP,
            INTERNAL_GOBO_IMAGE,
            INTERNAL_GOBO_NOISE,
            INTERNAL_GOBO_CELL,
        )

    def _gobo_rig_present(self) -> bool:
        return any(self.getChild(name) is not None for name in self._gobo_rig_names())

    def _ensure_named_gobo_child(self, name: str) -> None:
        """Recreate a gobo child a saved script still addresses by name."""
        if self.getChild(name) is not None:
            return
        if name == INTERNAL_GOBO:
            self._ensure_gobo_filter()
        elif name == INTERNAL_GOBO_GROUP:
            self._ensure_gobo_group()
        elif name in self._gobo_shader_names().values():
            self._ensure_gobo_shader(name, restore=False)

    def _sync_gobo(self) -> None:
        if getattr(self, "_syncingGobo", False):
            return
        self._syncingGobo = True
        try:
            if not self._gobo_active():
                if self._gobo_rig_present():
                    self._remember_gobo_rig()
                    self._remove_gobo_rig()
                    self._sync_groups()
                return
            self._ensure_gobo_filter()
            wanted = self._gobo_shader_names().get(self._gobo_map_kind())
            for child_name in self._gobo_shader_names().values():
                if child_name == wanted:
                    continue
                shader = self.getChild(child_name)
                if shader is None:
                    continue
                self._remember_gobo_node(shader)
                _remove_internal_node(self, shader)
            if wanted:
                self._ensure_gobo_shader(wanted, restore=True)
            self._wire_gobo_slide()
            self._sync_gobo_location()
            self._ensure_gobo_group()
            self._sync_groups()
        finally:
            self._syncingGobo = False

    def _gobo_map_kind(self) -> str:
        try:
            return (self["goboMap"].getValue() or "").strip() or GOBO_MAP_OFF
        except Exception:
            return GOBO_MAP_OFF

    def _remember_gobo_rig(self) -> None:
        for name in self._gobo_rig_names():
            if name == INTERNAL_GOBO_GROUP:
                continue
            self._remember_gobo_node(self.getChild(name))

    def _remember_gobo_node(self, node) -> None:
        if node is None or "parameters" not in node:
            return
        state = self._read_gobo_state()
        state[node.getName()] = _capture_parameters(node["parameters"])
        self._write_gobo_state(state)

    def _read_gobo_state(self) -> dict:
        try:
            raw = self["goboState"].getValue() or ""
        except Exception:
            return {}
        if not str(raw).strip():
            return {}
        try:
            import json

            data = json.loads(raw)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _write_gobo_state(self, state: dict) -> None:
        try:
            import json

            self["goboState"].setValue(json.dumps(state))
        except Exception:
            pass

    def _restore_gobo_node(self, node) -> None:
        saved = self._read_gobo_state().get(node.getName())
        if not isinstance(saved, dict) or "parameters" not in node:
            return
        _apply_parameters(node["parameters"], saved)

    def _remove_gobo_rig(self) -> None:
        for name in self._gobo_rig_names():
            child = self.getChild(name)
            if child is not None:
                _remove_internal_node(self, child)

    def _ensure_gobo_filter(self):
        existing = self.getChild(INTERNAL_GOBO)
        if existing is not None:
            set_node_enabled(existing, True)
            return existing
        try:
            import GafferArnold

            gobo = GafferArnold.ArnoldLightFilter(INTERNAL_GOBO)
            gobo.loadShader("gobo")
        except Exception as exc:
            IECore.msg(
                IECore.Msg.Level.Warning,
                "ArnoldLight",
                "Could not create gobo filter ({})".format(exc),
            )
            return None
        self.addChild(gobo)
        set_node_enabled(gobo, True)
        self._restore_gobo_node(gobo)
        return gobo

    def _ensure_gobo_shader(self, child_name: str, *, restore: bool):
        existing = self.getChild(child_name)
        if existing is not None:
            set_node_enabled(existing, True)
            return existing
        shader_name = {
            INTERNAL_GOBO_IMAGE: "image",
            INTERNAL_GOBO_NOISE: "noise",
            INTERNAL_GOBO_CELL: "cell_noise",
        }.get(child_name)
        if not shader_name:
            return None
        try:
            import GafferArnold

            shader = GafferArnold.ArnoldShader(child_name)
            shader.loadShader(shader_name)
        except Exception:
            return None
        self.addChild(shader)
        set_node_enabled(shader, True)
        if shader_name == "image":
            self.__tag_gobo_filename(shader)
        if restore:
            self._restore_gobo_node(shader)
        return shader

    def _wire_gobo_slide(self) -> None:
        gobo = self.getChild(INTERNAL_GOBO)
        wanted = self._gobo_shader_names().get(self._gobo_map_kind())
        target = self.getChild(wanted) if wanted else None
        if gobo is None or "parameters" not in gobo:
            return
        params = gobo["parameters"]
        for name in ("density", "slidemap", "slide_map", "slide", "map", "color"):
            if name not in params:
                continue
            try:
                params[name].setInput(None)
            except Exception:
                pass
        slide = None
        for name in ("slidemap", "slide_map", "slide"):
            if name in params:
                slide = params[name]
                break
        if slide is not None and target is not None:
            self.__connect_shader(slide, target)

    def _sync_gobo_location(self) -> None:
        gobo = self.getChild(INTERNAL_GOBO)
        if gobo is None:
            return
        leaf = "light"
        try:
            leaf = (self["name"].getValue() or "").strip().lstrip("/") or "light"
        except Exception:
            leaf = "light"
        parent = ""
        try:
            if self["lightType"].getValue() != MESH_LIGHT:
                parent = join_path(path_parts(self["primPath"].getValue() or ""))
        except Exception:
            parent = ""
        location = "{}/{}".format(parent, leaf) if parent else "/" + leaf
        if "name" in gobo:
            set_plug_value(gobo["name"], "{}_gobo".format(leaf))
        if "filteredLights" in gobo:
            set_plug_value(gobo["filteredLights"], location)

    def _sync_driven_plugs(self) -> None:
        super()._sync_driven_plugs()
        self._sync_gobo()

    def _gobo_active(self) -> bool:
        if self._current_type() != SPOT_LIGHT:
            return False
        try:
            kind = (self["goboMap"].getValue() or "").strip() or GOBO_MAP_OFF
        except Exception:
            return False
        return kind != GOBO_MAP_OFF

    def _ensure_gobo_group(self):
        """Parent the gobo filter at ``{primPath}/gobos``."""
        group = self.getChild(INTERNAL_GOBO_GROUP)
        if group is None:
            group = GafferScene.Group(INTERNAL_GOBO_GROUP)
            self.addChild(group)
            set_plug_value(group["name"], GOBO_GROUP_NAME)
        gobo = self.getChild(INTERNAL_GOBO)
        if gobo is not None and "out" in gobo:
            try:
                current = group["in"][0].getInput()
                if current is None or not current.isSame(gobo["out"]):
                    group["in"][0].setInput(gobo["out"])
            except Exception:
                pass
        set_node_enabled(group, True)
        return group

    def _group_chain_extra_sources(self) -> list:
        if not self._gobo_active():
            return []
        group = self._ensure_gobo_group()
        if group is not None and "out" in group:
            return [group["out"]]
        return []

    def _on_script_loaded(self, *_args) -> None:
        kind = self._current_type()
        if kind and kind != MESH_LIGHT:
            self.__reload_regular_shader(kind, keep=False)
        super()._on_script_loaded(*_args)

    def _on_insert_plug_set(self, plug: Gaffer.Plug) -> None:
        super()._on_insert_plug_set(plug)
        if plug.getName() == self.TYPE_PLUG and script_is_loading(self):
            current = self._current_type()
            if current and current != MESH_LIGHT:
                self.__reload_regular_shader(current, keep=False)
        if plug.getName() == "goboMap":
            self._sync_gobo()

    def __reload_regular_shader(self, shader: str, *, keep: bool = True) -> None:
        light = self.getChild(INTERNAL_LIGHT)
        if light is None:
            return
        loader = getattr(light, "loadShader", None)
        if not callable(loader):
            return
        try:
            loader(shader, keep)
        except TypeError:
            try:
                loader(shader)
            except Exception:
                return
        except Exception:
            return
        if "name" in light:
            try:
                if light["name"].getInput() is None:
                    light["name"].setInput(self["name"])
            except Exception:
                pass

    @staticmethod
    def __connect_shader(plug: Gaffer.Plug, shader: Gaffer.Node) -> None:
        out = shader.getChild("out")
        if out is None:
            return
        try:
            plug.setInput(out)
            return
        except Exception:
            pass
        for child in out.children():
            try:
                plug.setInput(child)
                return
            except Exception:
                continue

    @staticmethod
    def __tag_gobo_filename(shader: Gaffer.Node) -> None:
        if "parameters" not in shader or "filename" not in shader["parameters"]:
            return
        plug = shader["parameters"]["filename"]
        Gaffer.Metadata.registerValue(
            plug, "plugValueWidget:type", "GafferUI.FileSystemPathPlugValueWidget"
        )
        Gaffer.Metadata.registerValue(plug, "path:leaf", True)
        Gaffer.Metadata.registerValue(plug, "path:valid", False)
        Gaffer.Metadata.registerValue(
            plug,
            "fileSystemPath:extensions",
            "exr tx tif tiff png jpg jpeg hdr tga",
        )
        Gaffer.Metadata.registerValue(
            plug, "fileSystemPath:extensionsLabel", "Texture"
        )

    def __make_light(self, GafferArnold, shader: str):
        node_name = self._internal_light_name(shader)
        try:
            if uses_mesh_light_node(shader) or shader == MESH_LIGHT:
                return GafferArnold.ArnoldMeshLight(node_name)
            light = GafferArnold.ArnoldLight(node_name)
            light.loadShader(shader)
            return light
        except Exception as exc:
            IECore.msg(
                IECore.Msg.Level.Warning,
                "ArnoldLight",
                "Could not create {} ({})".format(shader, exc),
            )
            return None


ArnoldLight.__module__ = "ArnoldLight.ArnoldLight"
IECore.registerRunTimeTyped(ArnoldLight)

Gaffer.Metadata.registerNode(
    ArnoldLight,
    "description",
    "Adds one Arnold light (Area / disk / spot / …) into the incoming "
    "scene. Create authors {label}N_{typeToken} (areaLight, diskLight, "
    "… — type never contains '_'); Edit loads an existing light and "
    "authors at the same name and path.",
)


class _ArnoldLightSerialiser(BoxNetworkSerialiser):
    """Rebuild internals in ``__init__``; persist Arnold light parameters."""

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


Gaffer.Serialisation.registerSerialiser(ArnoldLight, _ArnoldLightSerialiser())
