"""ShadingTk — up to 8 Arnold shader assignment slots.

This is ``ShadingTk.ShadingTk``, not a stock Gaffer node.
"""

from __future__ import annotations

import os

import Gaffer
import GafferScene
import IECore

from ._box import (
    ENABLED_SWITCH,
    BoxNetworkSerialiser,
    SceneInsertMixin,
    add_enabled_switch,
    parse_prim_paths,
    persist_internal_shader_node,
    set_filter_paths,
    set_plug_value,
    set_switch_index,
    sync_enabled_switch,
)
from ._data import (
    ALL_SHADER_NAME,
    assign_path_plug,
    assign_source_plug,
    COLOR_PARAMETER_NAMES,
    DEFAULT_NAME_SUFFIX,
    DIAG_ASSIGN,
    DIAG_FILTER,
    DIAG_SHADER_NAME,
    DIAG_SWITCH,
    DIAGNOSTIC_SHADERS,
    EDIT_SCOPE,
    GLOBAL_ASSIGN,
    GLOBAL_FILTER,
    GLOBAL_SWITCH,
    LAYER_SHADER,
    MATTE_ASSIGN,
    MATTE_FILTER,
    MATTE_SHADER_NAME,
    MATTE_SWITCH,
    MAX_MIX_INPUTS,
    MAX_PATHS,
    MAX_SLOTS,
    MODE_CREATE,
    MODE_EDIT,
    MIX_ASSIGN,
    MIX_FILTER,
    MIX_SHADER,
    MIX_SHADER_NAME,
    MIX_SWITCH,
    PARAM_ALIASES,
    ROLE_META,
    STANDARD_SURFACE,
    TRANSFER_SKIP_SHADERS,
    UTILITY_COLOR_MODES,
    internal_assign,
    internal_filter,
    internal_shader,
    internal_switch,
    internal_texture,
    list_slot_shaders,
    list_texture_shaders,
    mix_input_plug,
    path_count_plug,
    path_plug,
    shader_handle_name,
    shader_name_plug,
    shader_type_plug,
    slot_label,
    SLOT_META,
    TEXTURES_BOX,
    LIBRARY_PREFIX,
    texture_type_plug,
    displacement_type_plug,
    internal_disp_map,
    internal_displacement,
    internal_disp_assign,
    internal_disp_switch,
    internal_reassign_copy,
    internal_reassign_filter,
    internal_reassign_switch,
)
from ._naming import auto_name_from_paths, unique_shader_name
from ._sampling import (
    ENGINE_OPTIONS_NODE,
    ENGINE_SURFACE_ATTR,
    SAMPLE_TWEAK_NAMES,
    SAMPLING_ARNOLD_OPTIONS,
    SAMPLING_CYCLES_OPTIONS,
    SAMPLING_EDIT_FILTER,
    SAMPLING_EDIT_TWEAKS,
    SAMPLING_LIGHT_TWEAKS,
    SAMPLING_RENDERMAN_OPTIONS,
    SAMPLING_TWEAKS,
    SAMPLING_TWEAKS_FILTER,
    available_engines,
    default_engine,
    engine_label,
    make_options_node,
    persist_sampling_node,
)
from ._textureIO import (
    context_rows,
    convert_file,
    default_texture_dir,
    find_matching_file,
    ingest_file,
    open_file,
    project_name,
    project_root,
    resolved_texture_dir,
    scene_path,
    scene_textures_dir,
    search_dirs,
    unique_path,
    use_existing_texture,
)
from ._scene import (
    SURFACE_ATTRS,
    acquire_parameter_edit,
    has_scene_input,
    list_existing_shaders,
    list_sampling_shaders,
    read_location_sampling_shader,
    read_location_shader_edit,
    resolve_edit_scope,
    shader_parameter_names,
    with_scene_context,
)


def _is_reserved_child_name(name: str) -> bool:
    if name in (
        "in",
        "out",
        "enabled",
        "slotCount",
        "mode",
        "assignCount",
        "presetFolder",
        "globalAssign",
        "globalPath",
        "matteEnabled",
        "mattePath",
        "diagEnabled",
        "diagShader",
        "diagMode",
        "diagPath",
        "mixEnabled",
        "mixType",
        "mixName",
        "mixCount",
        "mixPath",
        "autoName",
        "namePrefix",
        "nameSuffix",
        "textureRoot",
        "textureUseExisting",
        "textureNextToScene",
        "textureOpenCommand",
    ):
        return True
    for prefix in (
        "assign",
        "edit",
        "sampling",
        "shaderType",
        "shaderName",
        "textureType",
        "displacementType",
        "Textures",
        "pathCount",
        "path",
        "mixInput",
        "__",
    ):
        if name.startswith(prefix):
            return True
    return False


def script_is_loading(node: Gaffer.Node) -> bool:
    script = node.scriptNode()
    if script is None:
        return False
    is_executing = getattr(script, "isExecuting", None)
    if not callable(is_executing):
        return False
    try:
        return bool(is_executing())
    except Exception:
        return False


class ShadingTk(SceneInsertMixin, Gaffer.Box):
    """Assign up to eight Arnold shaders, each with its own PathFilter."""

    def __init__(self, name: str = "ShadingTk"):
        Gaffer.Box.__init__(self, name)

        try:
            import GafferArnold
        except Exception as exc:
            raise IECore.Exception(
                "ShadingTk requires GafferArnold ({})".format(exc)
            )

        self.addChild(GafferScene.ScenePlug("in", Gaffer.Plug.Direction.In))
        self.addChild(
            Gaffer.IntPlug(
                "slotCount",
                defaultValue=0,
                minValue=0,
                maxValue=MAX_SLOTS,
            )
        )
        self.addChild(Gaffer.BoolPlug("editEnabled", defaultValue=False))
        self.addChild(Gaffer.StringPlug("editPath", defaultValue=""))
        self.addChild(Gaffer.BoolPlug("editLoaded", defaultValue=False))
        edit_scope = Gaffer.Plug("editScope")
        self.addChild(edit_scope)
        Gaffer.Metadata.registerValue(edit_scope, "nodule:type", "")
        Gaffer.Metadata.registerValue(edit_scope, "plugValueWidget:type", "")
        sampling_engine = Gaffer.StringPlug(
            "samplingEngine", defaultValue=default_engine()
        )
        self.addChild(Gaffer.BoolPlug("samplingEnabled", defaultValue=False))
        self.addChild(sampling_engine)
        self.ensureModePlug()
        self.ensureAssignPlugs()
        self.addChild(Gaffer.BoolPlug("samplingApplyAll", defaultValue=False))
        self.addChild(
            Gaffer.IntPlug(
                "samplingShaderSamples",
                defaultValue=2,
                minValue=0,
                maxValue=64,
            )
        )
        self.addChild(Gaffer.StringPlug("samplingEditPath", defaultValue=""))
        self.addChild(Gaffer.BoolPlug("samplingEditLoaded", defaultValue=False))
        Gaffer.Metadata.registerValue(sampling_engine, "nodule:type", "")
        Gaffer.Metadata.registerValue(sampling_engine, "label", "Render Engine")
        Gaffer.Metadata.registerValue(
            sampling_engine,
            "plugValueWidget:type",
            "GafferUI.PresetsPlugValueWidget",
        )
        for _engine in available_engines():
            Gaffer.Metadata.registerValue(
                sampling_engine, "preset:" + engine_label(_engine), _engine
            )
        preset_folder = Gaffer.StringPlug("presetFolder", defaultValue="")
        self.addChild(preset_folder)
        Gaffer.Metadata.registerValue(preset_folder, "nodule:type", "")
        Gaffer.Metadata.registerValue(
            preset_folder,
            "plugValueWidget:type",
            "GafferUI.FileSystemPathPlugValueWidget",
        )
        Gaffer.Metadata.registerValue(preset_folder, "path:leaf", False)
        from ._presets import bind_preset_folder

        bind_preset_folder(self)

        global_assign = Gaffer.BoolPlug("globalAssign", defaultValue=False)
        global_path = Gaffer.StringPlug("globalPath", defaultValue="...")
        self.addChild(global_assign)
        self.addChild(global_path)
        matte_enabled = Gaffer.BoolPlug("matteEnabled", defaultValue=False)
        matte_path = Gaffer.StringPlug("mattePath", defaultValue="")
        self.addChild(matte_enabled)
        self.addChild(matte_path)
        diag_enabled = Gaffer.BoolPlug("diagEnabled", defaultValue=False)
        diag_shader = Gaffer.StringPlug("diagShader", defaultValue="utility")
        diag_mode = Gaffer.StringPlug("diagMode", defaultValue="ng")
        diag_path = Gaffer.StringPlug("diagPath", defaultValue="...")
        self.addChild(diag_enabled)
        self.addChild(diag_shader)
        self.addChild(diag_mode)
        self.addChild(diag_path)
        mix_enabled = Gaffer.BoolPlug("mixEnabled", defaultValue=False)
        mix_type = Gaffer.StringPlug("mixType", defaultValue=MIX_SHADER)
        mix_name = Gaffer.StringPlug("mixName", defaultValue=MIX_SHADER_NAME)
        mix_count = Gaffer.IntPlug(
            "mixCount", defaultValue=2, minValue=2, maxValue=MAX_MIX_INPUTS
        )
        mix_path = Gaffer.StringPlug("mixPath", defaultValue="")
        self.addChild(mix_enabled)
        self.addChild(mix_type)
        self.addChild(mix_name)
        self.addChild(mix_count)
        self.addChild(mix_path)
        for mix_index in range(1, MAX_MIX_INPUTS + 1):
            mix_input = Gaffer.StringPlug(mix_input_plug(mix_index), defaultValue="")
            self.addChild(mix_input)
            Gaffer.Metadata.registerValue(mix_input, "nodule:type", "")
        auto_name = Gaffer.BoolPlug("autoName", defaultValue=True)
        name_prefix = Gaffer.StringPlug("namePrefix", defaultValue="")
        name_suffix = Gaffer.StringPlug("nameSuffix", defaultValue=DEFAULT_NAME_SUFFIX)
        self.addChild(auto_name)
        self.addChild(name_prefix)
        self.addChild(name_suffix)
        self.ensureTextureSettingsPlugs()
        for plug in (
            global_assign,
            global_path,
            matte_enabled,
            matte_path,
            diag_enabled,
            diag_shader,
            diag_mode,
            diag_path,
            mix_enabled,
            mix_type,
            mix_name,
            mix_count,
            mix_path,
            auto_name,
            name_prefix,
            name_suffix,
        ):
            Gaffer.Metadata.registerValue(plug, "nodule:type", "")
        Gaffer.Metadata.registerValue(
            global_path, "plugValueWidget:type", "GafferUI.StringPlugValueWidget"
        )
        Gaffer.Metadata.registerValue(
            matte_path, "plugValueWidget:type", "GafferUI.StringPlugValueWidget"
        )
        Gaffer.Metadata.registerValue(
            diag_path, "plugValueWidget:type", "GafferUI.StringPlugValueWidget"
        )
        Gaffer.Metadata.registerValue(
            mix_path, "plugValueWidget:type", "GafferUI.StringPlugValueWidget"
        )
        Gaffer.Metadata.registerValue(mix_path, "label", "PrimPath(s)")
        Gaffer.Metadata.registerValue(
            diag_shader, "plugValueWidget:type", "GafferUI.PresetsPlugValueWidget"
        )
        Gaffer.Metadata.registerValue(
            diag_mode, "plugValueWidget:type", "GafferUI.PresetsPlugValueWidget"
        )
        Gaffer.Metadata.registerValue(
            mix_type, "plugValueWidget:type", "GafferUI.PresetsPlugValueWidget"
        )
        self.__register_presets(diag_shader, DIAGNOSTIC_SHADERS)
        self.__register_presets(diag_mode, UTILITY_COLOR_MODES)
        self.__register_presets(
            mix_type,
            ((MIX_SHADER, "MixShader"), (LAYER_SHADER, "LayerShader")),
        )

        slot_shaders = list_slot_shaders()
        texture_shaders = list_texture_shaders()
        for index in range(1, MAX_SLOTS + 1):
            self.__add_slot_plugs(index, slot_shaders, texture_shaders)

        switch = add_enabled_switch(self, self["in"])
        Gaffer.PlugAlgo.promote(switch["out"])

        self.__shifting = False
        self.__loadingEdit = False
        self.__loadingSampling = False
        self._bind_signals()
        self.__slotsReady = True
        self._sync_driven_plugs()

    def __add_slot_plugs(self, index: int, slot_shaders, texture_shaders) -> None:
        type_plug = Gaffer.StringPlug(
            shader_type_plug(index), defaultValue=STANDARD_SURFACE
        )
        name_plug = Gaffer.StringPlug(
            shader_name_plug(index), defaultValue=slot_label(index)
        )
        tex_plug = Gaffer.StringPlug(texture_type_plug(index), defaultValue="")
        disp_plug = Gaffer.StringPlug(displacement_type_plug(index), defaultValue="")
        count_plug = Gaffer.IntPlug(
            path_count_plug(index), defaultValue=1, minValue=1, maxValue=MAX_PATHS
        )
        self.addChild(type_plug)
        self.addChild(name_plug)
        self.addChild(tex_plug)
        self.addChild(disp_plug)
        self.addChild(count_plug)
        self.__register_presets(type_plug, slot_shaders)
        maps = (("", "None"),) + tuple(texture_shaders)
        self.__register_presets(tex_plug, maps)
        self.__register_presets(disp_plug, maps)
        for path_index in range(1, MAX_PATHS + 1):
            path = Gaffer.StringPlug(path_plug(index, path_index), defaultValue="")
            self.addChild(path)
            Gaffer.Metadata.registerValue(
                path,
                "plugValueWidget:type",
                "GafferUI.StringPlugValueWidget",
            )
            Gaffer.Metadata.registerValue(path, "label", "PrimPath(s)")
            Gaffer.Metadata.registerValue(path, "nodule:type", "")

        for plug in (type_plug, name_plug, tex_plug, disp_plug, count_plug):
            Gaffer.Metadata.registerValue(plug, "nodule:type", "")
        Gaffer.Metadata.registerValue(type_plug, "label", "Shader")
        Gaffer.Metadata.registerValue(name_plug, "label", "Name")
        Gaffer.Metadata.registerValue(tex_plug, "label", "Diffuse map")
        Gaffer.Metadata.registerValue(disp_plug, "label", "Displacement")
        Gaffer.Metadata.registerValue(
            type_plug, "plugValueWidget:type", "GafferUI.PresetsPlugValueWidget"
        )
        Gaffer.Metadata.registerValue(
            tex_plug, "plugValueWidget:type", "GafferUI.PresetsPlugValueWidget"
        )
        Gaffer.Metadata.registerValue(
            disp_plug, "plugValueWidget:type", "GafferUI.PresetsPlugValueWidget"
        )

    @staticmethod
    def __register_presets(plug: Gaffer.Plug, items) -> None:
        for value, label in items:
            key = "preset:" + (label or "None")
            Gaffer.Metadata.registerValue(plug, key, value)

    def __add_slot_network(self, GafferArnold, index: int, source):
        shader = self.slotShader(index)
        if shader is None:
            shader = self._find_serialised_shader(index)
        if shader is None and not script_is_loading(self):
            shader = GafferArnold.ArnoldShader(self._shader_handle_name(index))
            try:
                shader.loadShader(STANDARD_SURFACE)
            except Exception as exc:
                IECore.msg(
                    IECore.Msg.Level.Warning,
                    "ShadingTk",
                    "Could not load {} ({})".format(STANDARD_SURFACE, exc),
                )
            self.addChild(shader)
        if shader is not None:
            try:
                Gaffer.Metadata.registerValue(shader, SLOT_META, index)
            except Exception:
                pass
            self._sync_shader_node_name(index)
            self._detach_shader_type_name(index)

        texture = self.getChild(internal_texture(index))
        if texture is None and not script_is_loading(self):
            texture = GafferArnold.ArnoldShader(internal_texture(index))
            self.addChild(texture)

        path_filter = self.getChild(internal_filter(index))
        if path_filter is None:
            path_filter = GafferScene.PathFilter(internal_filter(index))
            self.addChild(path_filter)
            path_filter["paths"].setValue(IECore.StringVectorData())

        assign = self.getChild(internal_assign(index))
        if assign is None:
            assign = GafferScene.ShaderAssignment(internal_assign(index))
            self.addChild(assign)
        assign["in"].setInput(source)
        assign["filter"].setInput(path_filter["out"])
        self._connect_shader(index)

        shaded = assign["out"]
        disp_out = self._ensure_displacement_network(
            GafferArnold, index, shaded, path_filter
        )
        slot_switch = self.getChild(internal_switch(index))
        if slot_switch is None:
            slot_switch = Gaffer.Switch(internal_switch(index))
            self.addChild(slot_switch)
            slot_switch.setup(GafferScene.ScenePlug("in"))
            slot_switch["in"].resize(2)
        slot_switch["in"][0].setInput(source)
        slot_switch["in"][1].setInput(disp_out)
        return slot_switch["out"]

    def _ensure_displacement_network(
        self, GafferArnold, index: int, source, path_filter
    ):
        disp_map = self.getChild(internal_disp_map(index))
        if disp_map is None and not script_is_loading(self):
            disp_map = GafferArnold.ArnoldShader(internal_disp_map(index))
            self.addChild(disp_map)
        displacement = self.getChild(internal_displacement(index))
        if displacement is None and not script_is_loading(self):
            try:
                displacement = GafferArnold.ArnoldDisplacement(
                    internal_displacement(index)
                )
                self.addChild(displacement)
            except Exception:
                displacement = None
        disp_assign = self.getChild(internal_disp_assign(index))
        if disp_assign is None:
            disp_assign = GafferScene.ShaderAssignment(internal_disp_assign(index))
            self.addChild(disp_assign)
        disp_assign["in"].setInput(source)
        disp_assign["filter"].setInput(path_filter["out"])
        if displacement is not None and "out" in displacement and "shader" in disp_assign:
            try:
                disp_assign["shader"].setInput(displacement["out"])
            except Exception:
                pass
        disp_switch = self.getChild(internal_disp_switch(index))
        if disp_switch is None:
            disp_switch = Gaffer.Switch(internal_disp_switch(index))
            self.addChild(disp_switch)
            disp_switch.setup(GafferScene.ScenePlug("in"))
            disp_switch["in"].resize(2)
        disp_switch["in"][0].setInput(source)
        disp_switch["in"][1].setInput(disp_assign["out"])
        self._connect_displacement(index)
        return disp_switch["out"]

    def __getitem__(self, key):
        if isinstance(key, str):
            self._maybe_ensure_from_child_name(key)
        return Gaffer.Box.__getitem__(self, key)

    def _maybe_ensure_from_child_name(self, name: str) -> None:
        if not getattr(self, "_ShadingTk__slotsReady", False):
            return
        if self.getChild(name) is not None:
            return
        if name.startswith("__sampling"):
            if self["samplingEnabled"].getValue():
                self._ensure_sampling_network()
            return
        for prefix in (
            "__shader",
            "__texture",
            "__dispMap",
            "__displacement",
            "__dispAssign",
            "__dispSwitch",
            "__pathFilter",
            "__assign",
            "__slotSwitch",
            "__all",
            "__matte",
            "__diag",
            "__mix",
        ):
            if not name.startswith(prefix):
                continue
            suffix = name[len(prefix) :]
            if suffix.isdigit():
                self._ensure_slot(int(suffix))
            break
        else:
            for index in range(1, MAX_SLOTS + 1):
                try:
                    if self._shader_handle_name(index) == name:
                        self._ensure_slot(index)
                        break
                except Exception:
                    continue
        if script_is_loading(self) and self.getChild(name) is None:
            self._accept_serialised_shader(name)

    def _accept_serialised_shader(self, name: str) -> None:
        """Create a named ArnoldShader so copy/paste can set its plugs."""
        if not name or self.getChild(name) is not None:
            return
        if _is_reserved_child_name(name) and not name.startswith("__texture"):
            return
        try:
            import GafferArnold
        except Exception:
            return
        shader = GafferArnold.ArnoldShader(name)
        self.addChild(shader)

    def _find_serialised_shader(self, index: int):
        handle = self._shader_handle_name(index)
        child = self.getChild(handle)
        if self._is_slot_shader_child(child):
            return child
        used = set()
        for other in range(1, MAX_SLOTS + 1):
            if other == index:
                continue
            found = self.slotShader(other)
            if found is not None:
                used.add(found)
        for child in self.children():
            if child in used or not self._is_slot_shader_child(child):
                continue
            try:
                slot = Gaffer.Metadata.value(child, SLOT_META)
            except Exception:
                slot = None
            if slot in (None, index):
                return child
        return None

    @staticmethod
    def _is_slot_shader_child(child) -> bool:
        if child is None or not persist_internal_shader_node(child):
            return False
        try:
            name = child.getName()
        except Exception:
            return False
        if name.startswith("__"):
            return False
        if name in (ALL_SHADER_NAME, MATTE_SHADER_NAME, DIAG_SHADER_NAME):
            return False
        try:
            role = Gaffer.Metadata.value(child, ROLE_META)
        except Exception:
            role = None
        if role and role != "slot":
            return False
        return True

    def _finish_load(self) -> None:
        """Wire serialised shader children after copy/paste or file load."""
        count = 0
        try:
            count = int(self["slotCount"].getValue())
        except Exception:
            count = 0
        self._ensure_slots(count)
        for index in range(1, count + 1):
            shader = self.slotShader(index)
            if shader is None:
                shader = self._find_serialised_shader(index)
            if shader is None:
                try:
                    import GafferArnold

                    shader = GafferArnold.ArnoldShader(self._shader_handle_name(index))
                    wanted = STANDARD_SURFACE
                    try:
                        wanted = self[shader_type_plug(index)].getValue() or STANDARD_SURFACE
                    except Exception:
                        pass
                    try:
                        shader.loadShader(wanted)
                    except Exception:
                        pass
                    self.addChild(shader)
                except Exception:
                    shader = None
            if shader is not None:
                try:
                    Gaffer.Metadata.registerValue(shader, SLOT_META, index)
                except Exception:
                    pass
            self._sync_shader_node_name(index)
            self._detach_shader_type_name(index)
            self._connect_shader(index)
            texture = self.getChild(internal_texture(index))
            if texture is None:
                self._load_slot_texture(index)
            else:
                self._connect_texture(index)
            self._load_slot_displacement(index)
        self._ensure_enabled_stages()
        try:
            self._ensure_reassign_slots(int(self["assignCount"].getValue()))
        except Exception:
            pass
        if self["samplingEnabled"].getValue():
            try:
                self._ensure_sampling_network()
            except Exception:
                pass
        try:
            if (self["mode"].getValue() or MODE_CREATE) == MODE_EDIT or self.getChild(
                EDIT_SCOPE
            ) is not None:
                self._ensure_edit_scope()
        except Exception:
            pass
        self._rewire_outputs()

    def _ensure_slots(self, count: int) -> None:
        count = min(max(int(count), 0), MAX_SLOTS)
        if count < 1:
            return
        for index in range(1, count + 1):
            self._ensure_slot(index)

    def _ensure_slot(self, index: int) -> None:
        if index < 1 or index > MAX_SLOTS:
            return
        for previous in range(1, index):
            self._ensure_slot(previous)
        if self.getChild(internal_assign(index)) is not None:
            self._connect_shader(index)
            self._sync_shader_node_name(index)
            if self.getChild(internal_disp_switch(index)) is None:
                try:
                    import GafferArnold

                    assign = self.getChild(internal_assign(index))
                    path_filter = self.getChild(internal_filter(index))
                    slot_switch = self.getChild(internal_switch(index))
                    if assign is not None and path_filter is not None:
                        disp_out = self._ensure_displacement_network(
                            GafferArnold, index, assign["out"], path_filter
                        )
                        if slot_switch is not None:
                            slot_switch["in"][1].setInput(disp_out)
                except Exception:
                    pass
            return
        try:
            import GafferArnold
        except Exception as exc:
            raise IECore.Exception(
                "ShadingTk requires GafferArnold ({})".format(exc)
            )
        source = self._stage_source()
        if index > 1:
            prev = self.getChild(internal_switch(index - 1))
            if prev is not None:
                source = prev["out"]
        self.__add_slot_network(GafferArnold, index, source)
        self._connect_shader(index)
        self._rewire_outputs()

    def _incoming_scene(self) -> Gaffer.Plug:
        """Scene after the internal EditScope (passthrough until edits exist)."""
        scope = self.getChild(EDIT_SCOPE)
        if scope is not None and "out" in scope:
            return scope["out"]
        return self["in"]

    def _stage_source(self) -> Gaffer.Plug:
        switch = self.getChild(GLOBAL_SWITCH)
        if switch is not None:
            return switch["out"]
        return self._incoming_scene()

    def _slot_chain_out(self) -> Gaffer.Plug:
        for slot in range(MAX_SLOTS, 0, -1):
            switch = self.getChild(internal_switch(slot))
            if switch is not None:
                return switch["out"]
        return self._stage_source()

    def _shading_chain_out(self) -> Gaffer.Plug:
        processed = self._slot_chain_out()
        for name in (MIX_SWITCH, MATTE_SWITCH, DIAG_SWITCH):
            switch = self.getChild(name)
            if switch is not None:
                processed = switch["out"]
        return processed

    def _rewire_outputs(self) -> None:
        scope = self.getChild(EDIT_SCOPE)
        if scope is not None and "in" in scope:
            try:
                scope["in"].setInput(self["in"])
            except Exception:
                pass
        incoming = self._incoming_scene()
        global_assign = self.getChild(GLOBAL_ASSIGN)
        global_switch = self.getChild(GLOBAL_SWITCH)
        if global_assign is not None and "in" in global_assign:
            try:
                global_assign["in"].setInput(incoming)
            except Exception:
                pass
        if global_switch is not None and "in" in global_switch:
            try:
                global_switch["in"][0].setInput(incoming)
                if global_assign is not None and "out" in global_assign:
                    global_switch["in"][1].setInput(global_assign["out"])
            except Exception:
                pass
        source = self._stage_source()
        first_assign = self.getChild(internal_assign(1))
        first_switch = self.getChild(internal_switch(1))
        if first_assign is not None and "in" in first_assign:
            try:
                first_assign["in"].setInput(source)
            except Exception:
                pass
        if first_switch is not None and "in" in first_switch:
            try:
                first_switch["in"][0].setInput(source)
            except Exception:
                pass
        processed = self._slot_chain_out()
        for assign_name, switch_name in (
            (MIX_ASSIGN, MIX_SWITCH),
            (MATTE_ASSIGN, MATTE_SWITCH),
            (DIAG_ASSIGN, DIAG_SWITCH),
        ):
            assign = self.getChild(assign_name)
            switch = self.getChild(switch_name)
            if assign is not None and "in" in assign:
                try:
                    assign["in"].setInput(processed)
                except Exception:
                    pass
            if switch is not None and "in" in switch:
                try:
                    switch["in"][0].setInput(processed)
                    if assign is not None and "out" in assign:
                        switch["in"][1].setInput(assign["out"])
                    processed = switch["out"]
                except Exception:
                    pass
        processed = self._rewire_reassign(processed)
        for child_name in (
            SAMPLING_ARNOLD_OPTIONS,
            SAMPLING_CYCLES_OPTIONS,
            SAMPLING_RENDERMAN_OPTIONS,
            SAMPLING_TWEAKS,
            SAMPLING_LIGHT_TWEAKS,
            SAMPLING_EDIT_TWEAKS,
        ):
            child = self.getChild(child_name)
            if child is None or "in" not in child or "out" not in child:
                continue
            try:
                child["in"].setInput(processed)
            except Exception:
                pass
            processed = child["out"]
        enabled = self.getChild(ENABLED_SWITCH)
        if enabled is not None:
            try:
                enabled["in"][0].setInput(self["in"])
                enabled["in"][1].setInput(processed)
            except Exception:
                pass
        self._sync_driven_plugs()

    def _plug_text(self, name: str) -> str:
        try:
            if name not in self:
                return ""
            return str(self[name].getValue() or "")
        except Exception:
            return ""

    def _plug_on(self, name: str) -> bool:
        try:
            return bool(self[name].getValue()) if name in self else False
        except Exception:
            return False

    def _sync_stage_drive(
        self, switch_name: str, filter_name: str, enabled_plug: str, path_plugs
    ) -> None:
        if self.getChild(switch_name) is None:
            return
        set_switch_index(
            self, switch_name, 1 if self._plug_on(enabled_plug) else 0
        )
        texts = [self._plug_text(plug_name) for plug_name in path_plugs]
        set_filter_paths(self, filter_name, parse_prim_paths(*texts))

    def _sync_driven_plugs(self) -> None:
        """Write Switch / PathFilter values from public plugs. No live Expression."""
        sync_enabled_switch(self)
        try:
            count = int(self["slotCount"].getValue())
        except Exception:
            count = 0
        for index in range(1, MAX_SLOTS + 1):
            if self.getChild(internal_switch(index)) is None:
                continue
            set_switch_index(
                self, internal_switch(index), 1 if count >= index else 0
            )
            if self.getChild(internal_disp_switch(index)) is not None:
                kind = self._plug_text(displacement_type_plug(index)).strip()
                set_switch_index(
                    self, internal_disp_switch(index), 1 if kind else 0
                )
            try:
                path_count = int(self[path_count_plug(index)].getValue())
            except Exception:
                path_count = 1
            path_count = max(1, min(path_count, MAX_PATHS))
            texts = [
                self._plug_text(path_plug(index, path_index))
                for path_index in range(1, path_count + 1)
            ]
            set_filter_paths(
                self, internal_filter(index), parse_prim_paths(*texts)
            )
        self._sync_stage_drive(
            GLOBAL_SWITCH, GLOBAL_FILTER, "globalAssign", ("globalPath",)
        )
        self._sync_stage_drive(
            MATTE_SWITCH, MATTE_FILTER, "matteEnabled", ("mattePath",)
        )
        self._sync_stage_drive(
            DIAG_SWITCH, DIAG_FILTER, "diagEnabled", ("diagPath",)
        )
        self._sync_stage_drive(
            MIX_SWITCH, MIX_FILTER, "mixEnabled", ("mixPath",)
        )
        try:
            assign_count = int(self["assignCount"].getValue()) if "assignCount" in self else 0
        except Exception:
            assign_count = 0
        for index in range(1, MAX_SLOTS + 1):
            if self.getChild(internal_reassign_switch(index)) is None:
                continue
            source = self._plug_text(assign_source_plug(index)).strip()
            dests = parse_prim_paths(self._plug_text(assign_path_plug(index)))
            active = index <= assign_count and bool(source) and bool(dests)
            set_switch_index(
                self, internal_reassign_switch(index), 1 if active else 0
            )
            set_filter_paths(self, internal_reassign_filter(index), dests)
            copy = self.getChild(internal_reassign_copy(index))
            if copy is not None and "sourceLocation" in copy:
                set_plug_value(copy["sourceLocation"], source)
        sampling_on = self._plug_on("samplingEnabled")
        engine = (self._plug_text("samplingEngine") or "arnold").strip()
        apply_all = self._plug_on("samplingApplyAll")
        for name, token in (
            (SAMPLING_ARNOLD_OPTIONS, "arnold"),
            (SAMPLING_CYCLES_OPTIONS, "cycles"),
            (SAMPLING_RENDERMAN_OPTIONS, "renderman"),
        ):
            child = self.getChild(name)
            if child is None or "enabled" not in child:
                continue
            set_plug_value(child["enabled"], sampling_on and engine == token)
        tweaks = self.getChild(SAMPLING_TWEAKS)
        if tweaks is not None:
            if "enabled" in tweaks:
                set_plug_value(tweaks["enabled"], sampling_on and apply_all)
            if "shader" in tweaks:
                set_plug_value(
                    tweaks["shader"],
                    ENGINE_SURFACE_ATTR.get(engine, "ai:surface"),
                )
        lights = self.getChild(SAMPLING_LIGHT_TWEAKS)
        if lights is not None and "enabled" in lights:
            set_plug_value(lights["enabled"], sampling_on and apply_all)
        edit = self.getChild(SAMPLING_EDIT_TWEAKS)
        if edit is not None and "enabled" in edit:
            set_plug_value(
                edit["enabled"],
                sampling_on and self._plug_on("samplingEditLoaded"),
            )
        set_filter_paths(
            self,
            SAMPLING_EDIT_FILTER,
            parse_prim_paths(self._plug_text("samplingEditPath")),
        )

    def copyValues(self) -> dict:
        from ._values import snapshot

        return snapshot(self)

    def pasteValues(self, data: dict | None) -> int:
        from ._values import apply_snapshot

        return apply_snapshot(self, data, reload=self._reload_all_slots)

    def resetValues(self) -> None:
        from ._values import reset_values

        reset_values(self)
        self._reload_all_slots()

    def addSlot(self) -> None:
        count = self["slotCount"].getValue()
        if count >= MAX_SLOTS:
            return
        self._ensure_slots(count + 1)
        self["slotCount"].setValue(count + 1)

    def addAssignSlot(self) -> None:
        self.ensureAssignPlugs()
        count = int(self["assignCount"].getValue())
        if count >= MAX_SLOTS:
            return
        self._ensure_reassign_slots(count + 1)
        self["assignCount"].setValue(count + 1)

    def removeAssignSlotAt(self, index: int) -> None:
        self.ensureAssignPlugs()
        count = int(self["assignCount"].getValue())
        if index < 1 or index > count:
            return
        self.__shifting = True
        try:
            for src in range(index + 1, count + 1):
                self[assign_source_plug(src - 1)].setValue(
                    self[assign_source_plug(src)].getValue()
                )
                self[assign_path_plug(src - 1)].setValue(
                    self[assign_path_plug(src)].getValue()
                )
            self.clearAssignSlot(count)
        finally:
            self.__shifting = False
        self["assignCount"].setValue(count - 1)
        self._rewire_outputs()

    def clearAssignSlot(self, index: int) -> None:
        self.ensureAssignPlugs()
        self[assign_source_plug(index)].setValue("")
        self[assign_path_plug(index)].setValue("")

    def removeSlot(self, index: int | None = None) -> None:
        count = int(self["slotCount"].getValue())
        if count < 1:
            return
        if index is None:
            index = count
        self.removeSlotAt(index)

    def removeSlotAt(self, index: int) -> None:
        count = int(self["slotCount"].getValue())
        if index < 1 or index > count:
            return
        self.__shifting = True
        try:
            snapshots = [
                self._slot_snapshot(src) for src in range(index + 1, count + 1)
            ]
            for offset, snap in enumerate(snapshots):
                self._apply_slot_snapshot(index + offset, snap)
            self.clearSlot(count)
        finally:
            self.__shifting = False
        self["slotCount"].setValue(count - 1)
        self._rewire_outputs()

    def _slot_snapshot(self, index: int) -> dict:
        paths = []
        for path_index in range(1, MAX_PATHS + 1):
            try:
                paths.append(self[path_plug(index, path_index)].getValue())
            except Exception:
                paths.append("")
        return {
            "type": self[shader_type_plug(index)].getValue(),
            "name": self[shader_name_plug(index)].getValue(),
            "texture": self[texture_type_plug(index)].getValue(),
            "displacement": self[displacement_type_plug(index)].getValue(),
            "pathCount": self[path_count_plug(index)].getValue(),
            "paths": paths,
            "params": self._parameter_values(index),
            "texParams": self._parameter_values(index, texture=True),
        }

    def _apply_slot_snapshot(self, index: int, snap: dict) -> None:
        self._ensure_slot(index)
        self[shader_type_plug(index)].setValue(snap.get("type") or STANDARD_SURFACE)
        self._load_slot_shader(index)
        self[shader_name_plug(index)].setValue(snap.get("name") or slot_label(index))
        self._sync_shader_node_name(index)
        self[texture_type_plug(index)].setValue(snap.get("texture") or "")
        self._load_slot_texture(index)
        self[displacement_type_plug(index)].setValue(snap.get("displacement") or "")
        self._load_slot_displacement(index)
        count = max(1, min(int(snap.get("pathCount") or 1), MAX_PATHS))
        self[path_count_plug(index)].setValue(count)
        paths = list(snap.get("paths") or [])
        for path_index in range(1, MAX_PATHS + 1):
            value = paths[path_index - 1] if path_index <= len(paths) else ""
            self[path_plug(index, path_index)].setValue(value or "")
        self._apply_parameter_values(index, snap.get("params") or {})
        self._apply_parameter_values(
            index, snap.get("texParams") or {}, texture=True
        )

    def _parameter_values(self, index: int, *, texture: bool = False) -> dict:
        values = {}
        for plug in self.parameterPlugs(index, texture=texture):
            getter = getattr(plug, "getValue", None)
            if not callable(getter) or plug.getInput() is not None:
                continue
            try:
                values[plug.getName()] = getter()
            except Exception:
                pass
        return values

    def _apply_parameter_values(
        self, index: int, values: dict, *, texture: bool = False
    ) -> None:
        node = self.slotTexture(index) if texture else self.slotShader(index)
        if node is None or "parameters" not in node or not values:
            return
        params = node["parameters"]
        for name, value in values.items():
            if name not in params:
                continue
            plug = params[name]
            if plug.getInput() is not None:
                continue
            setter = getattr(plug, "setValue", None)
            if not callable(setter):
                continue
            try:
                setter(value)
            except Exception:
                pass

    def addPath(self, index: int) -> None:
        plug = self[path_count_plug(index)]
        count = plug.getValue()
        if count >= MAX_PATHS:
            return
        plug.setValue(count + 1)

    def removePath(self, index: int) -> None:
        plug = self[path_count_plug(index)]
        count = plug.getValue()
        if count <= 1:
            return
        self[path_plug(index, count)].setValue("")
        plug.setValue(count - 1)

    def listPresets(self) -> list:
        from ._presets import list_presets

        return list_presets(self)

    def applyPreset(self, index: int, name: str, shader: str | None = None) -> int:
        from ._presets import apply_preset, list_presets

        for preset in list_presets(self):
            if preset.get("name") != name:
                continue
            if shader is not None and preset.get("shader") != shader:
                continue
            return apply_preset(self, index, preset)
        return 0

    def savePreset(self, index: int, name: str, folder: str | None = None) -> str:
        from ._presets import save_slot_preset

        return save_slot_preset(self, index, name, folder)

    def resetSlotShader(self, index: int) -> None:
        """Reload the current shader type so attributes return to defaults."""
        self._load_slot_shader(index)

    def clearSlot(self, index: int) -> None:
        self[shader_type_plug(index)].setValue(STANDARD_SURFACE)
        self[shader_name_plug(index)].setValue(slot_label(index))
        self[texture_type_plug(index)].setValue("")
        self[displacement_type_plug(index)].setValue("")
        self[path_count_plug(index)].setValue(1)
        for path_index in range(1, MAX_PATHS + 1):
            self[path_plug(index, path_index)].setValue("")
        self._load_slot_shader(index)
        self._sync_shader_node_name(index)
        self._load_slot_texture(index)
        self._load_slot_displacement(index)

    def slotShader(self, index: int) -> Gaffer.Node | None:
        assign = self.getChild(internal_assign(index))
        if assign is not None and "shader" in assign:
            source = assign["shader"].getInput()
            if source is not None:
                node = source.node()
                if node is not None and node.parent() is self:
                    return node
        named = self.getChild(internal_shader(index))
        if named is not None:
            return named
        handle = self.getChild(self._shader_handle_name(index))
        if self._is_slot_shader_child(handle):
            return handle
        for child in self.children():
            if not self._is_slot_shader_child(child):
                continue
            try:
                slot = Gaffer.Metadata.value(child, SLOT_META)
            except Exception:
                slot = None
            if slot == index:
                return child
        return None

    def slotTexture(self, index: int) -> Gaffer.Node | None:
        return self.getChild(internal_texture(index))

    def slotDisplacement(self, index: int):
        return self.getChild(internal_displacement(index))

    def slotDispMap(self, index: int):
        return self.getChild(internal_disp_map(index))

    def texturesBox(self):
        return self.getChild(TEXTURES_BOX)

    def _ensure_textures_box(self):
        box = self.getChild(TEXTURES_BOX)
        if box is not None:
            return box
        box = Gaffer.Box(TEXTURES_BOX)
        self.addChild(box)
        return box

    def libraryTextures(self) -> list[dict]:
        box = self.texturesBox()
        if box is None:
            return []
        found = []
        for child in box.children():
            if not persist_internal_shader_node(child):
                continue
            path = ""
            try:
                if "parameters" in child and "filename" in child["parameters"]:
                    path = child["parameters"]["filename"].getValue() or ""
            except Exception:
                path = ""
            found.append({"name": child.getName(), "path": path, "node": child})
        found.sort(key=lambda item: item["name"].lower())
        return found

    def addLibraryTexture(self, filepath: str) -> str:
        filepath = (filepath or "").replace("\\", "/").strip()
        if not filepath:
            raise IECore.Exception("No texture file.")
        try:
            import GafferArnold
        except Exception as exc:
            raise IECore.Exception("ShadingTk requires GafferArnold ({})".format(exc))
        box = self._ensure_textures_box()
        stem = os.path.splitext(os.path.basename(filepath))[0]
        handle = shader_handle_name(stem, 1)
        if handle == slot_label(1):
            handle = "tex"
        existing = {child.getName() for child in box.children()}
        name = handle
        suffix = 1
        while name in existing:
            suffix += 1
            name = "{}{}".format(handle, suffix)
        shader = GafferArnold.ArnoldShader(name)
        try:
            shader.loadShader("image")
        except Exception as exc:
            raise IECore.Exception("Could not load image shader ({})".format(exc))
        if "parameters" in shader and "filename" in shader["parameters"]:
            try:
                shader["parameters"]["filename"].setValue(filepath)
            except Exception:
                pass
        box.addChild(shader)
        self.refresh_map_presets()
        return name

    def ensureModePlug(self) -> None:
        ready = bool(getattr(self, "_ShadingTk__slotsReady", False))
        flags = Gaffer.Plug.Flags.Default
        if ready:
            flags |= Gaffer.Plug.Flags.Dynamic
        if "mode" in self:
            plug = self["mode"]
        else:
            plug = Gaffer.StringPlug(
                "mode", defaultValue=MODE_CREATE, flags=flags
            )
            self.addChild(plug)
        Gaffer.Metadata.registerValue(plug, "nodule:type", "")
        Gaffer.Metadata.registerValue(
            plug, "plugValueWidget:type", "GafferUI.PresetsPlugValueWidget"
        )
        Gaffer.Metadata.registerValue(plug, "preset:Create", MODE_CREATE)
        Gaffer.Metadata.registerValue(plug, "preset:Edit", MODE_EDIT)
        Gaffer.Metadata.registerValue(plug, "label", "Mode")

    def ensureAssignPlugs(self) -> None:
        ready = bool(getattr(self, "_ShadingTk__slotsReady", False))
        flags = Gaffer.Plug.Flags.Default
        if ready:
            flags |= Gaffer.Plug.Flags.Dynamic
        if "assignCount" in self:
            count_plug = self["assignCount"]
        else:
            count_plug = Gaffer.IntPlug(
                "assignCount",
                defaultValue=0,
                minValue=0,
                maxValue=MAX_SLOTS,
                flags=flags,
            )
            self.addChild(count_plug)
        Gaffer.Metadata.registerValue(count_plug, "nodule:type", "")
        for index in range(1, MAX_SLOTS + 1):
            for name, default in (
                (assign_source_plug(index), ""),
                (assign_path_plug(index), ""),
            ):
                if name in self:
                    plug = self[name]
                else:
                    plug = Gaffer.StringPlug(
                        name, defaultValue=default, flags=flags
                    )
                    self.addChild(plug)
                Gaffer.Metadata.registerValue(plug, "nodule:type", "")
                if name.startswith("assignPath"):
                    Gaffer.Metadata.registerValue(
                        plug,
                        "plugValueWidget:type",
                        "GafferUI.StringPlugValueWidget",
                    )

    def ensureTextureSettingsPlugs(self) -> None:
        ready = bool(getattr(self, "_ShadingTk__slotsReady", False))
        flags = Gaffer.Plug.Flags.Default
        if ready:
            flags |= Gaffer.Plug.Flags.Dynamic
        specs = (
            ("textureRoot", Gaffer.StringPlug, ""),
            ("textureUseExisting", Gaffer.BoolPlug, True),
            ("textureNextToScene", Gaffer.BoolPlug, False),
            ("textureOpenCommand", Gaffer.StringPlug, ""),
        )
        for name, cls, default in specs:
            if name in self:
                plug = self[name]
            else:
                plug = cls(name, defaultValue=default, flags=flags)
                self.addChild(plug)
            Gaffer.Metadata.registerValue(plug, "nodule:type", "")
        root = self["textureRoot"]
        Gaffer.Metadata.registerValue(
            root, "plugValueWidget:type", "GafferUI.FileSystemPathPlugValueWidget"
        )
        Gaffer.Metadata.registerValue(root, "path:leaf", False)
        Gaffer.Metadata.registerValue(self["textureUseExisting"], "label", "Use existing")
        Gaffer.Metadata.registerValue(self["textureNextToScene"], "label", "Next to scene")
        Gaffer.Metadata.registerValue(root, "label", "Texture folder")
        Gaffer.Metadata.registerValue(self["textureOpenCommand"], "label", "Open command")

    def ingestLibraryTexture(self, filepath: str) -> str:
        self.ensureTextureSettingsPlugs()
        stored = ingest_file(self, filepath)
        return self.addLibraryTexture(stored)

    def renameLibraryTexture(self, name: str, new_name: str) -> str:
        box = self.texturesBox()
        child = box.getChild(name) if box is not None else None
        if child is None:
            raise IECore.Exception("Unknown texture '{}'.".format(name))
        handle = shader_handle_name(new_name, 1)
        if handle == slot_label(1):
            handle = "tex"
        existing = {item.getName() for item in box.children()} - {name}
        unique = handle
        suffix = 1
        while unique in existing:
            suffix += 1
            unique = "{}{}".format(handle, suffix)
        old_key = LIBRARY_PREFIX + name
        new_key = LIBRARY_PREFIX + unique
        child.setName(unique)
        for index in range(1, MAX_SLOTS + 1):
            for plug_name in (
                texture_type_plug(index),
                displacement_type_plug(index),
            ):
                if plug_name not in self:
                    continue
                plug = self[plug_name]
                try:
                    if plug.getValue() == old_key:
                        plug.setValue(new_key)
                except Exception:
                    pass
        self.refresh_map_presets()
        return unique

    def setLibraryTexturePath(self, name: str, filepath: str) -> None:
        box = self.texturesBox()
        child = box.getChild(name) if box is not None else None
        if child is None:
            return
        if "parameters" in child and "filename" in child["parameters"]:
            child["parameters"]["filename"].setValue(
                (filepath or "").replace("\\", "/")
            )

    def convertLibraryTexture(self, name: str, extension: str) -> str:
        self.ensureTextureSettingsPlugs()
        local = self.ensureLocalLibraryTexture(name=name)
        path = ""
        for item in self.libraryTextures():
            if item["name"] == local:
                path = item.get("path") or ""
                break
        if not path or not os.path.isfile(path):
            raise IECore.Exception("Texture file is missing: {}".format(path or name))
        ext = (extension or "").lstrip(".").lower()
        dest_dir = resolved_texture_dir(self)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(
            dest_dir, os.path.splitext(os.path.basename(path))[0] + "." + ext
        ).replace("\\", "/")
        if os.path.isfile(dest) and use_existing_texture(self):
            stored = dest
        else:
            if os.path.isfile(dest):
                dest = unique_path(dest).replace("\\", "/")
            stored = convert_file(path, dest)
        self.setLibraryTexturePath(local, stored)
        return stored

    def scanLibraryTextures(self) -> dict:
        relinked = []
        missing = []
        directories = search_dirs(self)
        for item in self.libraryTextures():
            path = item.get("path") or ""
            name = item.get("name") or ""
            if path and os.path.isfile(path):
                continue
            found = find_matching_file(path or name, directories)
            if found:
                self.setLibraryTexturePath(name, found)
                relinked.append({"name": name, "path": found})
            else:
                missing.append({"name": name, "path": path})
        return {"relinked": relinked, "missing": missing}

    def textureLocationInfo(self) -> dict:
        self.ensureTextureSettingsPlugs()
        return {
            "scene": scene_path(self),
            "project": project_name(self),
            "projectRoot": project_root(self).replace("\\", "/"),
            "defaultDir": default_texture_dir(self),
            "sceneTextures": scene_textures_dir(self),
            "resolvedDir": resolved_texture_dir(self),
            "context": context_rows(self),
        }

    def openLibraryTexture(self, name: str = "", path: str = "", command: str = "") -> None:
        self.ensureTextureSettingsPlugs()
        filepath = (path or "").replace("\\", "/")
        if not filepath:
            for item in self.visibleLibraryTextures():
                if name and item.get("name") == name:
                    filepath = item.get("path") or ""
                    break
        if command == "__default__":
            open_file(filepath, "")
            return
        if not command and "textureOpenCommand" in self:
            try:
                command = self["textureOpenCommand"].getValue() or ""
            except Exception:
                command = ""
        open_file(filepath, command)

    def removeLibraryTexture(self, name: str) -> bool:
        box = self.texturesBox()
        child = box.getChild(name) if box is not None else None
        if child is None:
            return False
        self._disconnect_texture_outputs(child)
        key = LIBRARY_PREFIX + name
        for index in range(1, MAX_SLOTS + 1):
            for plug_name in (
                texture_type_plug(index),
                displacement_type_plug(index),
            ):
                if plug_name not in self:
                    continue
                plug = self[plug_name]
                try:
                    if plug.getValue() == key:
                        plug.setValue("")
                except Exception:
                    pass
        try:
            box.removeChild(child)
        except Exception:
            return False
        self.refresh_map_presets()
        return True

    def unusedLibraryTextureNames(self) -> list[str]:
        names = []
        for item in self.libraryTextures():
            name = item.get("name") or ""
            node = item.get("node")
            if not name:
                continue
            if self._texture_node_is_used(node):
                continue
            names.append(name)
        return names

    def removeUnusedLibraryTextures(self) -> list[str]:
        removed = []
        for name in list(self.unusedLibraryTextureNames()):
            if self.removeLibraryTexture(name):
                removed.append(name)
        return removed

    def _texture_node_is_used(self, node) -> bool:
        if node is None or "out" not in node:
            return False
        return self._plug_has_outputs(node["out"])

    def _disconnect_texture_outputs(self, node) -> None:
        if node is None or "out" not in node:
            return
        self._disconnect_plug_outputs(node["out"])

    def _disconnect_plug_outputs(self, plug) -> None:
        if plug is None:
            return
        try:
            outputs = list(plug.outputs())
        except Exception:
            outputs = []
        for dest in outputs:
            try:
                dest.setInput(None)
            except Exception:
                pass
        try:
            children = list(plug)
        except Exception:
            children = []
        for child in children:
            self._disconnect_plug_outputs(child)

    @staticmethod
    def _plug_has_outputs(plug) -> bool:
        if plug is None:
            return False
        try:
            if list(plug.outputs()):
                return True
        except Exception:
            pass
        try:
            children = list(plug)
        except Exception:
            children = []
        for child in children:
            if ShadingTk._plug_has_outputs(child):
                return True
        return False

    def upstreamShadingTkNodes(self) -> list:
        """ShadingTk nodes feeding this one through scene ``in`` (far to near)."""
        found: list = []
        seen: set[int] = set()

        def visit(node) -> None:
            if node is None:
                return
            ident = id(node)
            if ident in seen:
                return
            seen.add(ident)
            for plug in self._scene_input_plugs(node):
                try:
                    source = plug.getInput()
                except Exception:
                    source = None
                if source is None:
                    continue
                visit(source.node())
            if node is not self and self._is_shading_tk_node(node):
                found.append(node)

        visit(self)
        return found

    @staticmethod
    def _is_shading_tk_node(node) -> bool:
        if node is None:
            return False
        try:
            if isinstance(node, ShadingTk):
                return True
        except Exception:
            pass
        return type(node).__name__ == "ShadingTk"

    @staticmethod
    def _scene_input_plugs(node) -> list:
        plugs = []
        if node is None:
            return plugs
        try:
            children = list(node.children())
        except Exception:
            return plugs
        for child in children:
            if not isinstance(child, Gaffer.Plug):
                continue
            try:
                if child.direction() != Gaffer.Plug.Direction.In:
                    continue
            except Exception:
                continue
            type_name = type(child).__name__
            if "ScenePlug" not in type_name:
                continue
            nested = []
            try:
                nested = list(child.children())
            except Exception:
                nested = []
            scene_children = [
                item
                for item in nested
                if "ScenePlug" in type(item).__name__
            ]
            if scene_children:
                plugs.extend(scene_children)
            else:
                plugs.append(child)
        return plugs

    def visibleLibraryTextures(self) -> list[dict]:
        """This node's textures, plus textures stored on upstream ShadingTk nodes."""
        by_key: dict[str, dict] = {}
        for source in self.upstreamShadingTkNodes():
            try:
                items = list(source.libraryTextures())
            except Exception:
                items = []
            source_name = source.getName()
            for item in items:
                path = (item.get("path") or "").replace("\\", "/").strip()
                name = item.get("name") or ""
                key = path.lower() if path else name.lower()
                if not key:
                    continue
                by_key[key] = {
                    "name": name,
                    "path": path,
                    "source": "upstream",
                    "sourceNode": source_name,
                    "local": False,
                }
        for item in self.libraryTextures():
            path = (item.get("path") or "").replace("\\", "/").strip()
            name = item.get("name") or ""
            key = path.lower() if path else name.lower()
            if not key:
                continue
            by_key[key] = {
                "name": name,
                "path": path,
                "source": "local",
                "sourceNode": self.getName(),
                "local": True,
            }
        found = list(by_key.values())
        found.sort(
            key=lambda item: (
                0 if item.get("local") else 1,
                item.get("sourceNode") or "",
                item.get("name") or "",
            )
        )
        return found

    def ensureLocalLibraryTexture(self, *, name: str = "", path: str = "") -> str:
        """Store the file on this node if it only exists upstream; return local name."""
        path = (path or "").replace("\\", "/").strip()
        name = (name or "").strip()
        for item in self.libraryTextures():
            item_path = (item.get("path") or "").replace("\\", "/")
            if path and item_path == path:
                return item["name"]
            if name and item.get("name") == name:
                return item["name"]
        if not path:
            for item in self.visibleLibraryTextures():
                if name and item.get("name") == name:
                    path = (item.get("path") or "").replace("\\", "/")
                    break
        if not path:
            raise IECore.Exception(
                "No texture file to store on this ShadingTk."
            )
        return self.addLibraryTexture(path)

    def textureManagerSnapshot(self) -> dict:
        """Frozen library + shader:input connections for the Texture Manager."""
        library = self.visibleLibraryTextures()
        shaders = []
        for entry in self._texture_manager_shader_entries():
            shader = entry.get("node")
            connections = []
            for spec in self.connectableTextureInputs(shader):
                dest = self._texture_input_plug(
                    shader, spec["plug"], spec.get("component") or ""
                )
                linked = self._texture_link_from_plug(dest)
                component = spec.get("component") or ""
                if not linked and component:
                    continue
                connections.append(
                    {
                        "plug": spec["plug"],
                        "component": component,
                        "label": spec["label"],
                        "texture": (linked or {}).get("name") or "",
                        "path": (linked or {}).get("path") or "",
                    }
                )
            shaders.append(
                {
                    "key": entry["key"],
                    "index": entry.get("index"),
                    "name": entry["name"],
                    "type": entry.get("type") or "",
                    "connections": connections,
                }
            )
        return {"library": library, "shaders": shaders}

    def _texture_manager_shader_entries(self) -> list[dict]:
        entries: list[dict] = []
        try:
            count = int(self["slotCount"].getValue())
        except Exception:
            count = 0
        for index in range(1, count + 1):
            shader = self.slotShader(index)
            if shader is None:
                continue
            shader_type = ""
            try:
                shader_type = self[shader_type_plug(index)].getValue() or ""
            except Exception:
                shader_type = ""
            entries.append(
                {
                    "key": "slot:{}".format(index),
                    "index": index,
                    "name": self._shader_handle_name(index),
                    "type": shader_type,
                    "node": shader,
                }
            )
        extras = (
            ("global", ALL_SHADER_NAME, self.globalShader),
            ("matte", MATTE_SHADER_NAME, self.matteShader),
            ("mix", MIX_SHADER_NAME, self.mixShader),
        )
        for key, fallback, getter in extras:
            shader = None
            try:
                shader = getter()
            except Exception:
                shader = None
            if shader is None:
                continue
            shader_type = ""
            try:
                if "name" in shader:
                    shader_type = shader["name"].getValue() or ""
            except Exception:
                shader_type = ""
            entries.append(
                {
                    "key": key,
                    "index": None,
                    "name": shader.getName() or fallback,
                    "type": shader_type,
                    "node": shader,
                }
            )
        return entries

    def shaderFromTextureManagerKey(self, key: str):
        key = (key or "").strip()
        if key.startswith("slot:"):
            try:
                return self.slotShader(int(key.split(":", 1)[1]))
            except Exception:
                return None
        lookup = {
            "global": self.globalShader,
            "matte": self.matteShader,
            "mix": self.mixShader,
        }
        getter = lookup.get(key)
        if getter is None:
            return None
        try:
            return getter()
        except Exception:
            return None

    def connectableTextureInputs(self, shader) -> list[dict]:
        """Color / RGB / RGBA parameters that can take an image shader."""
        found: list[dict] = []
        if shader is None or "parameters" not in shader:
            return found
        try:
            plugs = list(shader["parameters"].children())
        except Exception:
            return found
        for plug in plugs:
            if not self.__is_editable_param(plug):
                continue
            type_name = type(plug).__name__
            is_c4 = "Color4f" in type_name
            is_c3 = "Color3f" in type_name
            if not (is_c3 or is_c4):
                continue
            name = plug.getName()
            kind = "rgba" if is_c4 else "rgb"
            found.append(
                {
                    "plug": name,
                    "component": "",
                    "label": name,
                    "kind": kind,
                }
            )
            components = ("r", "g", "b", "a") if is_c4 else ("r", "g", "b")
            for component in components:
                if component not in plug:
                    continue
                found.append(
                    {
                        "plug": name,
                        "component": component,
                        "label": "{}.{}".format(name, component),
                        "kind": "component",
                    }
                )
        return found

    def connectLibraryTexture(
        self, texture_name: str, shader_key: str, plug_name: str, component: str = ""
    ) -> bool:
        path = ""
        for item in self.visibleLibraryTextures():
            if item.get("name") == texture_name:
                path = item.get("path") or ""
                if item.get("local"):
                    break
        local_name = self.ensureLocalLibraryTexture(name=texture_name, path=path)
        box = self.texturesBox()
        source = box.getChild(local_name) if box is not None else None
        shader = self.shaderFromTextureManagerKey(shader_key)
        dest = self._texture_input_plug(shader, plug_name, component)
        if source is None or dest is None:
            return False
        connected = self._connect_texture_output(dest, source, component)
        if connected and not component and shader_key.startswith("slot:"):
            try:
                index = int(shader_key.split(":", 1)[1])
                color = self.colorParameter(index)
                if color is not None and dest.isSame(color):
                    self[texture_type_plug(index)].setValue(
                        LIBRARY_PREFIX + local_name
                    )
            except Exception:
                pass
        return connected

    def disconnectLibraryTexture(
        self, shader_key: str, plug_name: str, component: str = ""
    ) -> bool:
        shader = self.shaderFromTextureManagerKey(shader_key)
        dest = self._texture_input_plug(shader, plug_name, component)
        if dest is None:
            return False
        try:
            if dest.getInput() is None:
                return False
            dest.setInput(None)
        except Exception:
            return False
        if not component and shader_key.startswith("slot:"):
            try:
                index = int(shader_key.split(":", 1)[1])
                color = self.colorParameter(index)
                if color is not None and dest.isSame(color):
                    self[texture_type_plug(index)].setValue("")
            except Exception:
                pass
        return True

    def _texture_input_plug(self, shader, plug_name: str, component: str = ""):
        if shader is None or "parameters" not in shader or not plug_name:
            return None
        if plug_name not in shader["parameters"]:
            return None
        plug = shader["parameters"][plug_name]
        if component:
            if component not in plug:
                return None
            return plug[component]
        return plug

    def _texture_link_from_plug(self, plug) -> dict | None:
        if plug is None:
            return None
        try:
            source = plug.getInput()
        except Exception:
            return None
        if source is None:
            return None
        node = source.node()
        if node is None:
            return None
        path = ""
        try:
            if "parameters" in node and "filename" in node["parameters"]:
                path = node["parameters"]["filename"].getValue() or ""
        except Exception:
            path = ""
        return {"name": node.getName(), "path": path}

    def _connect_texture_output(self, dest, source, component: str = "") -> bool:
        if dest is None or source is None or "out" not in source:
            return False
        out = source["out"]
        names = []
        if component:
            names.append(component)
        else:
            names.extend(("", "rgb", "rgba"))
        for name in names:
            target = out[name] if name and name in out else (out if not name else None)
            if target is None:
                continue
            try:
                dest.setInput(target)
                return True
            except Exception:
                continue
        return False

    def refresh_map_presets(self) -> None:
        maps = [("", "None")] + list(list_texture_shaders())
        for item in self.libraryTextures():
            maps.append(
                (LIBRARY_PREFIX + item["name"], "Library / {}".format(item["name"]))
            )
        for index in range(1, MAX_SLOTS + 1):
            for plug_name in (
                texture_type_plug(index),
                displacement_type_plug(index),
            ):
                if plug_name not in self:
                    continue
                plug = self[plug_name]
                try:
                    for key in list(Gaffer.Metadata.registeredValues(plug) or []):
                        if str(key).startswith("preset:"):
                            Gaffer.Metadata.deregisterValue(plug, key)
                except Exception:
                    pass
                self.__register_presets(plug, maps)

    def _map_source_shader(self, value: str, fallback):
        key = (value or "").strip()
        if key.startswith(LIBRARY_PREFIX):
            box = self.texturesBox()
            name = key[len(LIBRARY_PREFIX) :]
            child = box.getChild(name) if box is not None else None
            if child is not None:
                if persist_internal_shader_node(child):
                    return child
            return None
        if key:
            return fallback
        return None

    def colorParameter(self, index: int) -> Gaffer.Plug | None:
        shader = self.slotShader(index)
        if shader is None or "parameters" not in shader:
            return None
        params = shader["parameters"]
        for name in COLOR_PARAMETER_NAMES:
            if name in params:
                return params[name]
        return None

    def parameterPlugs(self, index: int, *, texture: bool = False):
        node = self.slotTexture(index) if texture else self.slotShader(index)
        return self._editable_params(node)

    def mapParameterPlugs(self, index: int, *, displacement: bool = False):
        plug_name = (
            displacement_type_plug(index) if displacement else texture_type_plug(index)
        )
        kind = ""
        try:
            kind = (self[plug_name].getValue() or "").strip()
        except Exception:
            kind = ""
        fallback = self.slotDispMap(index) if displacement else self.slotTexture(index)
        return self._editable_params(self._map_source_shader(kind, fallback))

    def displacementParameterPlugs(self, index: int):
        plugs = []
        displacement = self.slotDisplacement(index)
        if displacement is not None:
            for name in ("height", "padding", "zeroValue", "autoBump"):
                if name in displacement:
                    plugs.append(displacement[name])
        return plugs

    def plugAcceptsRgbTexture(self, plug) -> bool:
        if plug is None:
            return False
        type_name = type(plug).__name__
        return "Color3f" in type_name or "Color4f" in type_name

    def textureSourceNode(self, plug):
        """Texture shader feeding this plug, or one of its components."""
        if plug is None:
            return None
        try:
            source = plug.getInput()
        except Exception:
            source = None
        if source is not None:
            try:
                node = source.node()
            except Exception:
                node = None
            if self._is_texture_node(node):
                return node
        try:
            children = list(plug.children())
        except Exception:
            children = []
        for child in children:
            node = self.textureSourceNode(child)
            if node is not None:
                return node
        return None

    def texturePlugState(self, plug) -> str:
        """``none``, ``connected``, or ``missing`` for an RGB attribute."""
        node = self.textureSourceNode(plug)
        if node is None:
            return "none"
        path = None
        try:
            if "parameters" in node and "filename" in node["parameters"]:
                path = node["parameters"]["filename"].getValue() or ""
        except Exception:
            path = None
        if path is None:
            return "connected"
        if self._texture_file_missing(path):
            return "missing"
        return "connected"

    def textureNodeHasFile(self, node) -> bool:
        try:
            return node is not None and "parameters" in node and "filename" in node["parameters"]
        except Exception:
            return False

    def texturePlugChoices(self) -> list[tuple[str, str]]:
        """Shader types, then library file textures, for the TXT picker."""
        choices = list(list_texture_shaders())
        for item in self.libraryTextures():
            name = item.get("name") or ""
            if name:
                choices.append((LIBRARY_PREFIX + name, name))
        return choices

    def assignPlugTexture(self, plug, choice: str):
        """Connect a texture type or library texture to an RGB plug.

        An empty choice disconnects it. Returns the texture node, or None.
        """
        if not self.plugAcceptsRgbTexture(plug):
            return None
        choice = (choice or "").strip()
        if not choice:
            self._release_plug_texture(plug)
            self._sync_color_texture_type(plug, "")
            return None
        if choice.startswith(LIBRARY_PREFIX):
            node = self.textureNodeByName(choice[len(LIBRARY_PREFIX) :])
            if node is None:
                return None
        else:
            node = self._ensure_typed_texture(plug, choice)
            if node is None:
                return None
        self._release_plug_texture(plug, keep=node)
        if not self._connect_texture_output(plug, node, ""):
            return None
        try:
            key = LIBRARY_PREFIX + (node.getName() or "")
        except Exception:
            key = ""
        if key:
            self._sync_color_texture_type(plug, key)
        self.refresh_map_presets()
        return node

    def _texture_file_missing(self, path: str) -> bool:
        path = (path or "").strip()
        if not path:
            return True
        if "<" in path or "#" in path or "$" in path:
            return False
        return not os.path.isfile(path)

    def _node_in_textures_box(self, node) -> bool:
        box = self.texturesBox()
        if node is None or box is None:
            return False
        try:
            parent = node.parent()
        except Exception:
            return False
        try:
            return parent is not None and parent.isSame(box)
        except Exception:
            return False

    def _texture_output_destinations(self, node) -> list:
        found = []
        if node is None or "out" not in node:
            return found

        def walk(plug) -> None:
            try:
                found.extend(list(plug.outputs()))
            except Exception:
                pass
            try:
                children = list(plug.children())
            except Exception:
                children = []
            for child in children:
                walk(child)

        walk(node["out"])
        return found

    def _destination_under(self, dest, ancestor) -> bool:
        current = dest
        while current is not None:
            try:
                if current.isSame(ancestor):
                    return True
            except Exception:
                return False
            try:
                current = current.parent()
            except Exception:
                return False
        return False

    def _clear_texture_inputs(self, plug) -> None:
        if plug is None:
            return
        try:
            source = plug.getInput()
        except Exception:
            source = None
        if source is not None and self._is_texture_node(getattr(source, "node", lambda: None)()):
            try:
                plug.setInput(None)
            except Exception:
                pass
        try:
            children = list(plug.children())
        except Exception:
            children = []
        for child in children:
            self._clear_texture_inputs(child)

    def _release_plug_texture(self, plug, keep=None) -> None:
        node = self.textureSourceNode(plug)
        if node is None:
            return
        if keep is not None:
            try:
                if node.isSame(keep):
                    return
            except Exception:
                pass
        self._clear_texture_inputs(plug)
        if not self._node_in_textures_box(node):
            return
        elsewhere = False
        for dest in self._texture_output_destinations(node):
            if not self._destination_under(dest, plug):
                elsewhere = True
                break
        if elsewhere:
            return
        try:
            self.removeLibraryTexture(node.getName())
        except Exception:
            pass

    def _ensure_typed_texture(self, plug, shader_type: str):
        current = self.textureSourceNode(plug)
        if (
            current is not None
            and self._node_in_textures_box(current)
            and not any(
                not self._destination_under(dest, plug)
                for dest in self._texture_output_destinations(current)
            )
        ):
            current_type = ""
            try:
                if "name" in current:
                    current_type = current["name"].getValue() or ""
            except Exception:
                current_type = ""
            if current_type != shader_type:
                try:
                    current.loadShader(shader_type)
                except Exception as exc:
                    IECore.msg(
                        IECore.Msg.Level.Warning,
                        "ShadingTk",
                        "Could not load texture {} ({})".format(shader_type, exc),
                    )
                    return None
            return current
        try:
            import GafferArnold
        except Exception as exc:
            IECore.msg(
                IECore.Msg.Level.Warning,
                "ShadingTk",
                "ShadingTk requires GafferArnold ({})".format(exc),
            )
            return None
        box = self._ensure_textures_box()
        stem = shader_handle_name(plug.getName() or "tex", 1)
        if stem == slot_label(1):
            stem = "tex"
        existing = {child.getName() for child in box.children()}
        name = stem
        suffix = 1
        while name in existing:
            suffix += 1
            name = "{}{}".format(stem, suffix)
        shader = GafferArnold.ArnoldShader(name)
        try:
            shader.loadShader(shader_type)
        except Exception as exc:
            IECore.msg(
                IECore.Msg.Level.Warning,
                "ShadingTk",
                "Could not load texture {} ({})".format(shader_type, exc),
            )
            return None
        box.addChild(shader)
        return shader

    def _sync_color_texture_type(self, plug, value: str) -> None:
        for index in range(1, MAX_SLOTS + 1):
            color = self.colorParameter(index)
            if color is None:
                continue
            try:
                same = color.isSame(plug)
            except Exception:
                same = False
            if not same:
                continue
            plug_name = texture_type_plug(index)
            if plug_name not in self:
                return
            try:
                if (self[plug_name].getValue() or "") != (value or ""):
                    self[plug_name].setValue(value or "")
            except Exception:
                pass
            return

    def plugHasTextureInput(self, plug) -> bool:
        if plug is None:
            return False
        try:
            source = plug.getInput()
        except Exception:
            source = None
        if source is not None:
            try:
                node = source.node()
            except Exception:
                node = None
            if self._is_texture_node(node):
                return True
        try:
            children = list(plug)
        except Exception:
            children = []
        for child in children:
            if self.plugHasTextureInput(child):
                return True
        return False

    def _is_texture_node(self, node) -> bool:
        if node is None:
            return False
        box = self.texturesBox()
        try:
            parent = node.parent()
        except Exception:
            parent = None
        if box is not None and parent is not None:
            try:
                if parent.isSame(box):
                    return True
            except Exception:
                pass
        try:
            name = node.getName() or ""
        except Exception:
            name = ""
        if name.startswith("__texture") or name.startswith("__dispMap"):
            return True
        try:
            return "parameters" in node and "filename" in node["parameters"]
        except Exception:
            return False

    def textureNodeByName(self, name: str):
        name = (name or "").strip()
        if not name:
            return None
        box = self.texturesBox()
        if box is not None:
            child = box.getChild(name)
            if child is not None:
                return child
        return self.getChild(name)

    def textureParameterPlugs(self, node):
        return self._editable_params(node)

    def editScope(self):
        return resolve_edit_scope(self)

    def _ensure_edit_scope(self):
        """EditScope after the incoming assignment: ``in`` → ShaderEdits → chain."""
        scope = self.getChild(EDIT_SCOPE)
        if scope is None:
            scope = Gaffer.EditScope(EDIT_SCOPE)
            self.addChild(scope)
        if "in" not in scope:
            scope.setup(self["in"])
        try:
            current = scope["in"].getInput()
            if current is None or not current.isSame(self["in"]):
                scope["in"].setInput(self["in"])
        except Exception:
            try:
                scope["in"].setInput(self["in"])
            except Exception:
                pass
        self._rewire_outputs()
        return scope

    def editParameterPlugs(self):
        scope = self.editScope()
        if scope is None or not self["editLoaded"].getValue():
            return []
        path = (self["editPath"].getValue() or "").strip()
        if path and not path.startswith("/"):
            path = "/" + path
        if not path:
            return []
        handle, shader, attr, _shader_type = read_location_shader_edit(self, path)
        if not attr or shader is None:
            return []
        tweaks = []
        for parameter in shader_parameter_names(shader):
            try:
                tweak = acquire_parameter_edit(
                    scope, path, attr, handle, parameter, create=False
                )
            except Exception:
                tweak = None
            if tweak is not None:
                tweaks.append(tweak)
        return tweaks

    def _editable_params(self, node):
        if node is None or "parameters" not in node:
            return []
        return [
            plug
            for plug in node["parameters"].children()
            if self.__is_editable_param(plug)
        ]

    def existingShaders(self) -> list[dict]:
        return list_existing_shaders(self)

    def existingSamplingShaders(self) -> list[dict]:
        if not self["samplingEnabled"].getValue():
            return []
        return list_sampling_shaders(self)

    def samplingOptionsNode(self):
        engine = ""
        try:
            engine = self["samplingEngine"].getValue() or ""
        except Exception:
            engine = ""
        return self.getChild(ENGINE_OPTIONS_NODE.get(engine, ""))

    def samplingEditTweaks(self):
        return self.getChild(SAMPLING_EDIT_TWEAKS)

    def _ensure_sampling_network(self) -> None:
        last = self._shading_chain_out()
        for engine, child_name in ENGINE_OPTIONS_NODE.items():
            node = self.getChild(child_name)
            if node is None:
                node = make_options_node(engine, child_name)
                if node is None:
                    continue
                self.addChild(node)
                if "enabled" in node:
                    node["enabled"].setValue(False)
            try:
                node["in"].setInput(last)
                last = node["out"]
            except Exception:
                pass
        tweaks = self.getChild(SAMPLING_TWEAKS)
        if tweaks is None:
            tweaks_filter = GafferScene.PathFilter(SAMPLING_TWEAKS_FILTER)
            self.addChild(tweaks_filter)
            tweaks_filter["paths"].setValue(IECore.StringVectorData(["..."]))
            tweaks = GafferScene.ShaderTweaks(SAMPLING_TWEAKS)
            self.addChild(tweaks)
            tweaks["filter"].setInput(tweaks_filter["out"])
            tweaks["ignoreMissing"].setValue(True)
            tweaks["shader"].setValue(
                ENGINE_SURFACE_ATTR.get(
                    self["samplingEngine"].getValue(), "ai:surface"
                )
            )
            if "enabled" in tweaks:
                tweaks["enabled"].setValue(False)
            self._sync_sample_tweaks(tweaks)
        try:
            tweaks["in"].setInput(last)
            last = tweaks["out"]
        except Exception:
            pass
        light_tweaks = self.getChild(SAMPLING_LIGHT_TWEAKS)
        if light_tweaks is None:
            light_tweaks = GafferScene.ShaderTweaks(SAMPLING_LIGHT_TWEAKS)
            self.addChild(light_tweaks)
            filt = self.getChild(SAMPLING_TWEAKS_FILTER)
            if filt is not None:
                light_tweaks["filter"].setInput(filt["out"])
            light_tweaks["ignoreMissing"].setValue(True)
            light_tweaks["shader"].setValue("light")
            if "enabled" in light_tweaks:
                light_tweaks["enabled"].setValue(False)
            self._sync_sample_tweaks(light_tweaks)
        try:
            light_tweaks["in"].setInput(last)
            last = light_tweaks["out"]
        except Exception:
            pass
        edit_tweaks = self.getChild(SAMPLING_EDIT_TWEAKS)
        if edit_tweaks is None:
            edit_filter = GafferScene.PathFilter(SAMPLING_EDIT_FILTER)
            self.addChild(edit_filter)
            edit_filter["paths"].setValue(IECore.StringVectorData())
            edit_tweaks = GafferScene.ShaderTweaks(SAMPLING_EDIT_TWEAKS)
            self.addChild(edit_tweaks)
            edit_tweaks["filter"].setInput(edit_filter["out"])
            edit_tweaks["ignoreMissing"].setValue(True)
            if "enabled" in edit_tweaks:
                edit_tweaks["enabled"].setValue(False)
        try:
            edit_tweaks["in"].setInput(last)
        except Exception:
            pass
        self._rewire_outputs()

    def _sync_sample_tweaks(self, tweaks) -> None:
        if tweaks is None or "tweaks" not in tweaks:
            return
        existing = {child["name"].getValue(): child for child in tweaks["tweaks"].children()}
        source = self["samplingShaderSamples"]
        for name in SAMPLE_TWEAK_NAMES:
            child = existing.get(name)
            if child is None:
                child = Gaffer.TweakPlug(name, 2)
                tweaks["tweaks"].addChild(child)
            try:
                child["value"].setInput(source)
            except Exception:
                try:
                    child["value"].setValue(source.getValue())
                except Exception:
                    pass
            try:
                child["enabled"].setValue(True)
            except Exception:
                pass

    def loadSamplingShader(self, path: str | None = None) -> int:
        path = (
            path
            if path is not None
            else (self["samplingEditPath"].getValue() or "")
        ).strip()
        if path and not path.startswith("/"):
            path = "/" + path
        if not self["samplingEnabled"].getValue():
            raise IECore.Exception("Enable Shader sampling overrides first.")
        if not path:
            self["samplingEditLoaded"].setValue(False)
            return 0
        if not has_scene_input(self):
            raise IECore.Exception("Connect a scene to edit a sampling shader.")
        name, shader, params = read_location_sampling_shader(self, path)
        if not name or not params:
            self["samplingEditLoaded"].setValue(False)
            raise IECore.Exception(
                "No sampling parameters on '{}'.".format(path)
            )
        self._ensure_sampling_network()
        tweaks = self.getChild(SAMPLING_EDIT_TWEAKS)
        values = {}
        param_data = getattr(shader, "parameters", None)
        if param_data is not None and hasattr(param_data, "items"):
            for pname, data in param_data.items():
                if str(pname) in params:
                    values[str(pname)] = data.value if hasattr(data, "value") else data
        try:
            for child in list(tweaks["tweaks"].children()):
                tweaks["tweaks"].removeChild(child)
        except Exception:
            pass
        applied = 0
        for pname in params:
            value = values.get(pname, 2)
            try:
                if isinstance(value, float) and not isinstance(value, bool):
                    plug = Gaffer.TweakPlug(pname, float(value))
                else:
                    plug = Gaffer.TweakPlug(pname, int(value))
            except Exception:
                plug = Gaffer.TweakPlug(pname, 2)
            tweaks["tweaks"].addChild(plug)
            applied += 1
        attr = ENGINE_SURFACE_ATTR.get(
            self["samplingEngine"].getValue(), "ai:surface"
        )
        try:
            tweaks["shader"].setValue(attr)
        except Exception:
            pass
        self.__loadingSampling = True
        try:
            if self["samplingEditPath"].getValue() != path:
                self["samplingEditPath"].setValue(path)
            self["samplingEditLoaded"].setValue(True)
        finally:
            self.__loadingSampling = False
        self._rewire_outputs()
        return applied

    def loadEditShader(self, path: str | None = None) -> int:
        path = (path if path is not None else self["editPath"].getValue() or "").strip()
        if path and not path.startswith("/"):
            path = "/" + path
        if not path:
            self["editLoaded"].setValue(False)
            return 0
        if not has_scene_input(self):
            raise IECore.Exception("Connect a scene to Edit an existing shader.")
        scope = self._ensure_edit_scope()
        if scope is None:
            self["editLoaded"].setValue(False)
            raise IECore.Exception("Could not create an EditScope on this node.")
        handle, shader, attr, shader_type = read_location_shader_edit(self, path)
        if shader is None or not attr:
            self["editLoaded"].setValue(False)
            raise IECore.Exception(
                "No surface shader on '{}'.".format(path)
            )
        parameters = shader_parameter_names(shader)
        if not parameters:
            self["editLoaded"].setValue(False)
            raise IECore.Exception(
                "No parameters on '{}'.".format(handle or path)
            )
        reason = GafferScene.EditScopeAlgo.parameterEditReadOnlyReason(
            scope, path, attr, ("", parameters[0])
        )
        if reason is not None:
            self["editLoaded"].setValue(False)
            raise IECore.Exception(
                "EditScope '{}' is read-only.".format(scope.getName())
            )
        self.__loadingEdit = True
        try:
            def _acquire() -> int:
                applied = 0
                last_error = ""
                for parameter in parameters:
                    try:
                        tweak = acquire_parameter_edit(
                            scope, path, attr, handle, parameter, create=True
                        )
                    except Exception as exc:
                        last_error = str(exc)
                        tweak = None
                    if tweak is None:
                        continue
                    applied += 1
                if applied < 1:
                    raise IECore.Exception(
                        last_error
                        or "Could not acquire parameter edits in '{}'.".format(
                            scope.getName()
                        )
                    )
                return applied

            applied = with_scene_context(self, _acquire)
            if self["editPath"].getValue() != path:
                self["editPath"].setValue(path)
            self["editLoaded"].setValue(True)
            return applied
        except Exception:
            self["editLoaded"].setValue(False)
            raise
        finally:
            self.__loadingEdit = False

    def _try_load_edit_shader(self) -> None:
        if self.__loadingEdit or script_is_loading(self):
            return
        try:
            if (self["mode"].getValue() or MODE_CREATE) != MODE_EDIT:
                return
        except Exception:
            return
        path = ""
        try:
            path = (self["editPath"].getValue() or "").strip()
        except Exception:
            path = ""
        if not path:
            return
        try:
            if self["editLoaded"].getValue():
                return
        except Exception:
            pass
        if not has_scene_input(self):
            return
        try:
            self._ensure_edit_scope()
        except Exception:
            return
        try:
            self.loadEditShader(path)
        except Exception as exc:
            IECore.msg(IECore.Msg.Level.Warning, "ShadingTk", str(exc))

    @staticmethod
    def __is_editable_param(plug: Gaffer.Plug) -> bool:
        if plug.getName().startswith("__"):
            return False
        if plug.direction() != Gaffer.Plug.Direction.In:
            return False
        if plug.getName() in ("out", "type", "name"):
            return False
        return True

    def _ensure_enabled_stages(self) -> None:
        try:
            if self["globalAssign"].getValue():
                self._ensure_global_network()
        except Exception:
            pass
        try:
            if self["mixEnabled"].getValue():
                self._ensure_mix_network()
        except Exception:
            pass
        try:
            if self["matteEnabled"].getValue():
                self._ensure_matte_network()
        except Exception:
            pass
        try:
            if self["diagEnabled"].getValue():
                self._ensure_diag_network()
        except Exception:
            pass
        try:
            self._ensure_reassign_slots(int(self["assignCount"].getValue()))
        except Exception:
            pass

    def _ensure_reassign_slots(self, count: int) -> None:
        count = min(max(int(count), 0), MAX_SLOTS)
        if count < 1:
            return
        for index in range(1, count + 1):
            self._ensure_reassign_slot(index)

    def _ensure_reassign_slot(self, index: int) -> None:
        if index < 1 or index > MAX_SLOTS:
            return
        path_filter = self.getChild(internal_reassign_filter(index))
        if path_filter is None:
            path_filter = GafferScene.PathFilter(internal_reassign_filter(index))
            self.addChild(path_filter)
            path_filter["paths"].setValue(IECore.StringVectorData())
        copy = self.getChild(internal_reassign_copy(index))
        if copy is None:
            copy = GafferScene.CopyAttributes(internal_reassign_copy(index))
            self.addChild(copy)
            if "attributes" in copy:
                copy["attributes"].setValue(" ".join(SURFACE_ATTRS))
        copy["filter"].setInput(path_filter["out"])
        try:
            copy["source"].setInput(self["in"])
        except Exception:
            pass
        switch = self.getChild(internal_reassign_switch(index))
        if switch is None:
            switch = Gaffer.Switch(internal_reassign_switch(index))
            self.addChild(switch)
            switch.setup(GafferScene.ScenePlug("in"))
            switch["in"].resize(2)
        if "out" in copy:
            try:
                switch["in"][1].setInput(copy["out"])
            except Exception:
                pass

    def _rewire_reassign(self, processed: Gaffer.Plug) -> Gaffer.Plug:
        for index in range(1, MAX_SLOTS + 1):
            switch = self.getChild(internal_reassign_switch(index))
            copy = self.getChild(internal_reassign_copy(index))
            if switch is None or "in" not in switch:
                continue
            try:
                switch["in"][0].setInput(processed)
            except Exception:
                pass
            if copy is not None:
                try:
                    copy["in"].setInput(processed)
                except Exception:
                    pass
                try:
                    copy["source"].setInput(self["in"])
                except Exception:
                    pass
                if "out" in copy:
                    try:
                        switch["in"][1].setInput(copy["out"])
                    except Exception:
                        pass
            processed = switch["out"]
        return processed

    def _ensure_assign_stage(
        self,
        *,
        handle: str,
        shader_type: str,
        role: str,
        filter_name: str,
        assign_name: str,
        switch_name: str,
        source: Gaffer.Plug,
    ):
        try:
            import GafferArnold
        except Exception as exc:
            raise IECore.Exception(
                "ShadingTk requires GafferArnold ({})".format(exc)
            )
        shader = self.getChild(handle)
        if shader is None and not script_is_loading(self):
            shader = GafferArnold.ArnoldShader(handle)
            try:
                shader.loadShader(shader_type)
            except Exception as exc:
                IECore.msg(
                    IECore.Msg.Level.Warning,
                    "ShadingTk",
                    "Could not load {} ({})".format(shader_type, exc),
                )
            self.addChild(shader)
        if shader is not None:
            try:
                Gaffer.Metadata.registerValue(shader, ROLE_META, role)
            except Exception:
                pass
            if "name" in shader:
                try:
                    if shader["name"].getInput() is not None:
                        shader["name"].setInput(None)
                    if (shader["name"].getValue() or "") != shader_type:
                        shader["name"].setValue(shader_type)
                except Exception:
                    pass
        path_filter = self.getChild(filter_name)
        if path_filter is None:
            path_filter = GafferScene.PathFilter(filter_name)
            self.addChild(path_filter)
            path_filter["paths"].setValue(IECore.StringVectorData())
        assign = self.getChild(assign_name)
        if assign is None:
            assign = GafferScene.ShaderAssignment(assign_name)
            self.addChild(assign)
        assign["in"].setInput(source)
        assign["filter"].setInput(path_filter["out"])
        if shader is not None and "out" in shader and "shader" in assign:
            try:
                assign["shader"].setInput(shader["out"])
            except Exception:
                for name in ("shader", "closure", "rgb"):
                    if name in shader["out"]:
                        try:
                            assign["shader"].setInput(shader["out"][name])
                            break
                        except Exception:
                            continue
        slot_switch = self.getChild(switch_name)
        if slot_switch is None:
            slot_switch = Gaffer.Switch(switch_name)
            self.addChild(slot_switch)
            slot_switch.setup(GafferScene.ScenePlug("in"))
            slot_switch["in"].resize(2)
        slot_switch["in"][0].setInput(source)
        slot_switch["in"][1].setInput(assign["out"])
        return shader

    def _ensure_global_network(self) -> None:
        self._ensure_assign_stage(
            handle=ALL_SHADER_NAME,
            shader_type=STANDARD_SURFACE,
            role="global",
            filter_name=GLOBAL_FILTER,
            assign_name=GLOBAL_ASSIGN,
            switch_name=GLOBAL_SWITCH,
            source=self._incoming_scene(),
        )
        self._rewire_outputs()

    def _ensure_matte_network(self) -> None:
        self._ensure_assign_stage(
            handle=MATTE_SHADER_NAME,
            shader_type="matte",
            role="matte",
            filter_name=MATTE_FILTER,
            assign_name=MATTE_ASSIGN,
            switch_name=MATTE_SWITCH,
            source=self._slot_chain_out(),
        )
        self._rewire_outputs()

    def _ensure_diag_network(self) -> None:
        shader_type = "utility"
        try:
            shader_type = self["diagShader"].getValue() or "utility"
        except Exception:
            pass
        shader = self._ensure_assign_stage(
            handle=DIAG_SHADER_NAME,
            shader_type=shader_type,
            role="diag",
            filter_name=DIAG_FILTER,
            assign_name=DIAG_ASSIGN,
            switch_name=DIAG_SWITCH,
            source=self._slot_chain_out(),
        )
        self._apply_diag_mode(shader)
        self._rewire_outputs()

    def _ensure_mix_network(self) -> None:
        shader_type = MIX_SHADER
        handle = MIX_SHADER_NAME
        try:
            shader_type = self["mixType"].getValue() or MIX_SHADER
        except Exception:
            pass
        try:
            handle = shader_handle_name(self["mixName"].getValue() or "", 1)
            if handle == slot_label(1):
                handle = MIX_SHADER_NAME
        except Exception:
            handle = MIX_SHADER_NAME
        existing = self.mixShader()
        if existing is not None:
            handle = existing.getName()
        shader = self._ensure_assign_stage(
            handle=handle,
            shader_type=shader_type,
            role="mix",
            filter_name=MIX_FILTER,
            assign_name=MIX_ASSIGN,
            switch_name=MIX_SWITCH,
            source=self._slot_chain_out(),
        )
        self._sync_mix_shader_name()
        self._connect_mix_inputs()
        self._rewire_outputs()
        return shader

    def globalShader(self):
        child = self.getChild(ALL_SHADER_NAME)
        if child is not None:
            return child
        for child in self.children():
            try:
                if Gaffer.Metadata.value(child, ROLE_META) == "global":
                    return child
            except Exception:
                continue
        return None

    def mixShader(self):
        for child in self.children():
            try:
                if Gaffer.Metadata.value(child, ROLE_META) == "mix":
                    return child
            except Exception:
                continue
        wanted = shader_handle_name(self["mixName"].getValue() or "", 1)
        return self.getChild(wanted) or self.getChild(MIX_SHADER_NAME)

    def matteShader(self):
        child = self.getChild(MATTE_SHADER_NAME)
        if child is not None:
            return child
        for child in self.children():
            try:
                if Gaffer.Metadata.value(child, ROLE_META) == "matte":
                    return child
            except Exception:
                continue
        return None

    def diagnosticShader(self):
        child = self.getChild(DIAG_SHADER_NAME)
        if child is not None:
            return child
        for child in self.children():
            try:
                if Gaffer.Metadata.value(child, ROLE_META) == "diag":
                    return child
            except Exception:
                continue
        return None

    def globalParameterPlugs(self):
        return self._editable_params(self.globalShader())

    def mixParameterPlugs(self):
        return self._editable_params(self.mixShader())

    def _apply_diag_mode(self, shader=None) -> None:
        shader = shader if shader is not None else self.diagnosticShader()
        if shader is None or "parameters" not in shader:
            return
        mode = ""
        try:
            mode = self["diagMode"].getValue() or ""
        except Exception:
            mode = ""
        if not mode or "color_mode" not in shader["parameters"]:
            return
        try:
            shader["parameters"]["color_mode"].setValue(mode)
        except Exception:
            pass

    def _load_diag_shader(self) -> None:
        shader = self.diagnosticShader()
        if shader is None:
            return
        shader_type = self["diagShader"].getValue() or "utility"
        try:
            shader.loadShader(shader_type)
        except Exception as exc:
            IECore.msg(
                IECore.Msg.Level.Warning,
                "ShadingTk",
                "Could not load {} ({})".format(shader_type, exc),
            )
            return
        assign = self.getChild(DIAG_ASSIGN)
        if assign is not None and "shader" in assign and "out" in shader:
            try:
                assign["shader"].setInput(shader["out"])
            except Exception:
                pass
        self._apply_diag_mode(shader)

    def _load_mix_shader(self) -> None:
        shader = self.mixShader()
        if shader is None:
            return
        shader_type = self["mixType"].getValue() or MIX_SHADER
        try:
            shader.loadShader(shader_type)
        except Exception as exc:
            IECore.msg(
                IECore.Msg.Level.Warning,
                "ShadingTk",
                "Could not load {} ({})".format(shader_type, exc),
            )
            return
        assign = self.getChild(MIX_ASSIGN)
        if assign is not None and "shader" in assign and "out" in shader:
            try:
                assign["shader"].setInput(shader["out"])
            except Exception:
                pass
        self._connect_mix_inputs()

    def _sync_mix_shader_name(self) -> None:
        shader = self.mixShader()
        if shader is None:
            return
        wanted = shader_handle_name(self["mixName"].getValue() or "", 1)
        if wanted == slot_label(1):
            wanted = MIX_SHADER_NAME
        if shader.getName() == wanted:
            return
        if self.getChild(wanted) is not None and self.getChild(wanted) is not shader:
            return
        try:
            shader.setName(wanted)
        except Exception:
            pass

    def _mix_source_shader(self, index: int):
        key = ""
        try:
            key = (self[mix_input_plug(index)].getValue() or "").strip()
        except Exception:
            key = ""
        if not key:
            return None
        if key in ("all", ALL_SHADER_NAME, "global"):
            return self.globalShader()
        if key.isdigit():
            return self.slotShader(int(key))
        child = self.getChild(key)
        if persist_internal_shader_node(child):
            return child
        for slot in range(1, MAX_SLOTS + 1):
            if self._shader_handle_name(slot) == key:
                return self.slotShader(slot)
        return None

    def _connect_mix_inputs(self) -> None:
        shader = self.mixShader()
        if shader is None or "parameters" not in shader:
            return
        mix_type = MIX_SHADER
        count = 2
        try:
            mix_type = self["mixType"].getValue() or MIX_SHADER
        except Exception:
            pass
        try:
            count = int(self["mixCount"].getValue())
        except Exception:
            count = 2
        if mix_type == MIX_SHADER:
            count = min(count, 2)
        for index in range(1, MAX_MIX_INPUTS + 1):
            plug_name = "shader{}".format(index) if mix_type == MIX_SHADER else "input{}".format(index)
            enable_name = "enable{}".format(index)
            if plug_name not in shader["parameters"]:
                continue
            dest = shader["parameters"][plug_name]
            source = self._mix_source_shader(index) if index <= count else None
            if source is None or "out" not in source:
                try:
                    dest.setInput(None)
                except Exception:
                    pass
                if enable_name in shader["parameters"]:
                    try:
                        shader["parameters"][enable_name].setValue(False)
                    except Exception:
                        pass
                continue
            connected = False
            try:
                dest.setInput(source["out"])
                connected = True
            except Exception:
                for name in ("shader", "closure", "rgb"):
                    if name not in source["out"]:
                        continue
                    try:
                        dest.setInput(source["out"][name])
                        connected = True
                        break
                    except Exception:
                        continue
            if enable_name in shader["parameters"]:
                try:
                    shader["parameters"][enable_name].setValue(connected)
                except Exception:
                    pass

    def autoNameFromPick(self, index: int, paths: list[str]) -> str:
        if index < 1 or index > MAX_SLOTS:
            return ""
        try:
            if not self["autoName"].getValue():
                return ""
        except Exception:
            return ""
        prefix = ""
        suffix = DEFAULT_NAME_SUFFIX
        try:
            prefix = self["namePrefix"].getValue() or ""
        except Exception:
            prefix = ""
        try:
            suffix = self["nameSuffix"].getValue() or DEFAULT_NAME_SUFFIX
        except Exception:
            suffix = DEFAULT_NAME_SUFFIX
        wanted = auto_name_from_paths(paths, prefix, suffix)
        if not wanted:
            return ""
        taken = set()
        for other in range(1, MAX_SLOTS + 1):
            if other == index:
                continue
            try:
                taken.add(self._shader_handle_name(other))
            except Exception:
                pass
        name = unique_shader_name(wanted, taken, index, suffix)
        self[shader_name_plug(index)].setValue(name)
        self._sync_shader_node_name(index)
        return name

    def _shader_transfer_snapshot(self, shader) -> dict:
        values = {}
        inputs = {}
        if shader is None or "parameters" not in shader:
            return {"values": values, "inputs": inputs}
        for plug in shader["parameters"].children():
            name = plug.getName()
            if name.startswith("__"):
                continue
            try:
                source = plug.getInput()
            except Exception:
                source = None
            if source is not None:
                inputs[name] = source
                continue
            getter = getattr(plug, "getValue", None)
            if not callable(getter):
                continue
            try:
                values[name] = getter()
            except Exception:
                pass
        return {"values": values, "inputs": inputs}

    def _apply_shader_transfer(self, shader, snapshot: dict) -> None:
        if shader is None or "parameters" not in shader or not snapshot:
            return
        params = shader["parameters"]
        values = snapshot.get("values") or {}
        inputs = snapshot.get("inputs") or {}
        used = set()
        for name, source in inputs.items():
            dest = self._transfer_dest_plug(params, name, used)
            if dest is None:
                continue
            try:
                dest.setInput(source)
                used.add(dest.getName())
            except Exception:
                continue
        for name, value in values.items():
            dest = self._transfer_dest_plug(params, name, used)
            if dest is None or dest.getInput() is not None:
                continue
            setter = getattr(dest, "setValue", None)
            if not callable(setter):
                continue
            try:
                setter(value)
                used.add(dest.getName())
            except Exception:
                continue

    @staticmethod
    def _transfer_dest_plug(params, name: str, used: set[str]):
        candidates = (name,) + PARAM_ALIASES.get(name, ())
        for candidate in candidates:
            if candidate in used or candidate not in params:
                continue
            return params[candidate]
        return None

    def _reload_all_slots(self) -> None:
        for index in range(1, MAX_SLOTS + 1):
            if self.slotShader(index) is None:
                continue
            self._load_slot_shader(index, transfer=False)
            self._load_slot_texture(index)

    def _load_slot_shader(self, index: int, *, transfer: bool = False) -> None:
        shader = self.slotShader(index)
        if shader is None:
            return
        shader_name = self[shader_type_plug(index)].getValue() or STANDARD_SURFACE
        old_type = ""
        try:
            if "name" in shader:
                old_type = shader["name"].getValue() or ""
        except Exception:
            old_type = ""
        skip_types = old_type in TRANSFER_SKIP_SHADERS or shader_name in TRANSFER_SKIP_SHADERS
        snapshot = self._shader_transfer_snapshot(shader) if transfer and not skip_types else None
        try:
            shader.loadShader(shader_name)
        except Exception as exc:
            IECore.msg(
                IECore.Msg.Level.Warning,
                "ShadingTk",
                "Could not load {} ({})".format(shader_name, exc),
            )
            return
        self._detach_shader_type_name(index)
        self._sync_shader_node_name(index)
        self._connect_shader(index)
        if snapshot:
            self._apply_shader_transfer(shader, snapshot)
        self._connect_texture(index)
        self._connect_displacement(index)

    def _load_slot_texture(self, index: int) -> None:
        texture = self.slotTexture(index)
        if texture is None:
            return
        tex_name = (self[texture_type_plug(index)].getValue() or "").strip()
        if not tex_name or tex_name.startswith(LIBRARY_PREFIX):
            self._connect_texture(index)
            return
        try:
            texture.loadShader(tex_name)
        except Exception as exc:
            IECore.msg(
                IECore.Msg.Level.Warning,
                "ShadingTk",
                "Could not load texture {} ({})".format(tex_name, exc),
            )
        self._connect_texture(index)

    def _load_slot_displacement(self, index: int) -> None:
        kind = ""
        try:
            kind = (self[displacement_type_plug(index)].getValue() or "").strip()
        except Exception:
            kind = ""
        disp_map = self.slotDispMap(index)
        if disp_map is not None and kind and not kind.startswith(LIBRARY_PREFIX):
            try:
                disp_map.loadShader(kind)
            except Exception as exc:
                IECore.msg(
                    IECore.Msg.Level.Warning,
                    "ShadingTk",
                    "Could not load displacement {} ({})".format(kind, exc),
                )
        self._connect_displacement(index)

    def _shader_handle_name(self, index: int) -> str:
        text = ""
        try:
            text = self[shader_name_plug(index)].getValue() or ""
        except Exception:
            text = ""
        return shader_handle_name(text, index)

    def _sync_shader_node_name(self, index: int) -> None:
        """ArnoldShader node name is the ShaderNetwork handle (Name column)."""
        shader = self.slotShader(index)
        if shader is None:
            return
        wanted = self._shader_handle_name(index)
        try:
            Gaffer.Metadata.registerValue(shader, SLOT_META, index)
        except Exception:
            pass
        if shader.getName() == wanted:
            return
        existing = self.getChild(wanted)
        if existing is not None and existing is not shader:
            if self._is_slot_shader_child(existing):
                try:
                    Gaffer.Metadata.registerValue(existing, SLOT_META, index)
                except Exception:
                    pass
                assign = self.getChild(internal_assign(index))
                if assign is not None and "shader" in assign:
                    try:
                        assign["shader"].setInput(None)
                    except Exception:
                        pass
                try:
                    self.removeChild(shader)
                except Exception:
                    pass
                self._connect_shader(index)
                return
        try:
            shader.setName(wanted)
        except Exception:
            return

    def _detach_shader_type_name(self, index: int) -> None:
        """ArnoldShader['name'] plug is the type (Value), never the instance Name."""
        shader = self.slotShader(index)
        if shader is None or "name" not in shader:
            return
        try:
            if shader["name"].getInput() is not None:
                shader["name"].setInput(None)
        except Exception:
            return
        wanted = STANDARD_SURFACE
        try:
            wanted = self[shader_type_plug(index)].getValue() or STANDARD_SURFACE
        except Exception:
            pass
        try:
            if (shader["name"].getValue() or "") != wanted:
                shader["name"].setValue(wanted)
        except Exception:
            pass

    def _connect_shader(self, index: int) -> None:
        """Keep ShaderAssignment wired after loadShader rebuilds ``out``."""
        self._detach_shader_type_name(index)
        shader = self.slotShader(index)
        assign = self.getChild(internal_assign(index))
        if shader is None or assign is None or "shader" not in assign:
            return
        if "out" not in shader:
            return
        out = shader["out"]
        try:
            assign["shader"].setInput(out)
            return
        except Exception:
            pass
        for name in ("shader", "closure", "rgb"):
            if name not in out:
                continue
            try:
                assign["shader"].setInput(out[name])
                return
            except Exception:
                continue

    def _connect_shader_output(self, dest, source) -> None:
        if dest is None or source is None or "out" not in source:
            return
        try:
            dest.setInput(source["out"])
            return
        except Exception:
            pass
        out = source["out"]
        for name in ("rgb", "r", "y", "x"):
            if name in out:
                try:
                    dest.setInput(out[name])
                    return
                except Exception:
                    continue

    def _connect_texture(self, index: int) -> None:
        color = self.colorParameter(index)
        if color is None:
            return
        tex_name = (self[texture_type_plug(index)].getValue() or "").strip()
        source = self._map_source_shader(tex_name, self.slotTexture(index))
        current_node = None
        try:
            current = color.getInput()
            current_node = current.node() if current is not None else None
        except Exception:
            current_node = None
        slot_tex = self.slotTexture(index)
        driven_here = False
        if current_node is not None:
            try:
                if slot_tex is not None and current_node.isSame(slot_tex):
                    driven_here = True
                elif source is not None and current_node.isSame(source):
                    driven_here = True
            except Exception:
                driven_here = False
        if not tex_name or source is None:
            if driven_here:
                try:
                    color.setInput(None)
                except Exception:
                    pass
            return
        self._connect_shader_output(color, source)

    def _connect_displacement(self, index: int) -> None:
        displacement = self.slotDisplacement(index)
        if displacement is None or "map" not in displacement:
            return
        kind = ""
        try:
            kind = (self[displacement_type_plug(index)].getValue() or "").strip()
        except Exception:
            kind = ""
        source = self._map_source_shader(kind, self.slotDispMap(index))
        try:
            current = displacement["map"].getInput()
            if not kind or source is None:
                if current is not None:
                    displacement["map"].setInput(None)
                return
        except Exception:
            if not kind or source is None:
                return
        self._connect_shader_output(displacement["map"], source)

    def _bind_signals(self) -> None:
        self.__plugSetConnection = self.plugSetSignal().connect(
            Gaffer.WeakMethod(self._on_plug_set), scoped=True
        )
        self.__plugInputChangedConnection = self.plugInputChangedSignal().connect(
            Gaffer.WeakMethod(self._on_plug_input_changed), scoped=True
        )

    def _on_plug_set(self, plug: Gaffer.Plug) -> None:
        try:
            self._apply_plug_set(plug)
        finally:
            if getattr(self, "_ShadingTk__slotsReady", False) and not self.__shifting:
                if not script_is_loading(self):
                    self._sync_driven_plugs()

    def _apply_plug_set(self, plug: Gaffer.Plug) -> None:
        name = plug.getName()
        if name == "slotCount":
            try:
                self._ensure_slots(int(plug.getValue()))
            except Exception:
                pass
            return
        if name == "assignCount":
            try:
                self._ensure_reassign_slots(int(plug.getValue()))
            except Exception:
                pass
            self._rewire_outputs()
            return
        if name == "mode":
            if (plug.getValue() or MODE_CREATE) == MODE_EDIT and has_scene_input(self):
                try:
                    self._ensure_edit_scope()
                except Exception:
                    pass
                self._try_load_edit_shader()
            return
        if name == "editEnabled" and plug.getValue() and not has_scene_input(self):
            if not script_is_loading(self):
                try:
                    plug.setValue(False)
                except Exception:
                    pass
            return
        if name == "editPath":
            if self.__loadingEdit:
                return
            try:
                if self["editLoaded"].getValue():
                    self["editLoaded"].setValue(False)
            except Exception:
                pass
            self._try_load_edit_shader()
            return
        if name == "samplingEnabled" and plug.getValue():
            try:
                self._ensure_sampling_network()
            except Exception:
                pass
            return
        if name in ("samplingEngine", "samplingApplyAll") and self[
            "samplingEnabled"
        ].getValue():
            try:
                self._ensure_sampling_network()
            except Exception:
                pass
            return
        if name == "samplingEditPath" and not self.__loadingSampling:
            try:
                if self["samplingEditLoaded"].getValue():
                    self["samplingEditLoaded"].setValue(False)
            except Exception:
                pass
            return
        if name == "globalAssign" and plug.getValue():
            self._ensure_global_network()
            return
        if name == "matteEnabled" and plug.getValue():
            self._ensure_matte_network()
            return
        if name == "diagEnabled" and plug.getValue():
            self._ensure_diag_network()
            return
        if name == "mixEnabled" and plug.getValue():
            self._ensure_mix_network()
            return
        if name == "diagShader":
            if self.getChild(DIAG_SWITCH) is not None:
                self._load_diag_shader()
            return
        if name == "diagMode":
            self._apply_diag_mode()
            return
        if name == "mixType":
            if self["mixType"].getValue() == MIX_SHADER:
                try:
                    if int(self["mixCount"].getValue()) > 2:
                        self["mixCount"].setValue(2)
                except Exception:
                    pass
            if self.getChild(MIX_SWITCH) is not None:
                self._load_mix_shader()
            return
        if name == "mixCount":
            if self["mixType"].getValue() == MIX_SHADER:
                try:
                    if int(plug.getValue()) > 2:
                        plug.setValue(2)
                        return
                except Exception:
                    pass
            if self.getChild(MIX_SWITCH) is not None:
                self._connect_mix_inputs()
            return
        if name == "mixName" and self.getChild(MIX_SWITCH) is not None:
            self._sync_mix_shader_name()
            return
        if name.startswith("mixInput") and self.getChild(MIX_SWITCH) is not None:
            self._connect_mix_inputs()
            return
        if script_is_loading(self) or self.__shifting:
            return
        if name.startswith("shaderType"):
            try:
                index = int(name.replace("shaderType", ""))
            except ValueError:
                return
            self._load_slot_shader(index, transfer=True)
        elif name.startswith("shaderName"):
            try:
                index = int(name.replace("shaderName", ""))
            except ValueError:
                return
            self._sync_shader_node_name(index)
        elif name.startswith("textureType"):
            try:
                index = int(name.replace("textureType", ""))
            except ValueError:
                return
            self._load_slot_texture(index)
        elif name.startswith("displacementType"):
            try:
                index = int(name.replace("displacementType", ""))
            except ValueError:
                return
            self._load_slot_displacement(index)

    def _on_plug_input_changed(self, plug: Gaffer.Plug) -> None:
        if plug.getName() == "in":
            try:
                if (self["mode"].getValue() or MODE_CREATE) == MODE_EDIT:
                    self._ensure_edit_scope()
            except Exception:
                pass
            self._try_load_edit_shader()
            return
        if plug.getName() == "editScope":
            self._try_load_edit_shader()
            return
        if plug.getName() != "name" or plug.getInput() is None:
            return
        node = plug.node()
        if node is None or node.parent() is not self:
            return
        if not persist_internal_shader_node(node):
            return
        source = plug.getInput()
        if source is None or source.node() is not self:
            return
        if not source.getName().startswith("shaderName"):
            return
        try:
            slot = Gaffer.Metadata.value(node, SLOT_META)
        except Exception:
            slot = None
        if slot is None:
            suffix = node.getName()[len("__shader") :]
            if not suffix.isdigit():
                return
            slot = int(suffix)
        self._detach_shader_type_name(int(slot))


ShadingTk.__module__ = "ShadingTk.ShadingTk"
IECore.registerRunTimeTyped(ShadingTk)

Gaffer.Metadata.registerNode(
    ShadingTk,
    "description",
    "Assigns up to eight Arnold shaders, or edits one existing surface "
    "shader through an EditScope. Slots start empty — add one when "
    "you need it. Prim paths are applied when you edit them.",
)


class _ShadingTkSerialiser(BoxNetworkSerialiser):
    """Rebuild the active slot chain; persist Arnold shaders that exist."""

    def childNeedsConstruction(
        self, child: Gaffer.GraphComponent, serialisation: Gaffer.Serialisation
    ) -> bool:
        if persist_sampling_node(child) or persist_internal_shader_node(child):
            return True
        if child.getName() in (TEXTURES_BOX, EDIT_SCOPE):
            return True
        if isinstance(child, Gaffer.Plug) and child.getName() == "out":
            return False
        return super().childNeedsConstruction(child, serialisation)

    def childNeedsSerialisation(
        self, child: Gaffer.GraphComponent, serialisation: Gaffer.Serialisation
    ) -> bool:
        if isinstance(child, Gaffer.Node):
            if child.getName() in (TEXTURES_BOX, EDIT_SCOPE):
                return True
            return persist_internal_shader_node(child) or persist_sampling_node(
                child
            )
        return super().childNeedsSerialisation(child, serialisation)

    def postScript(self, node, identifier, serialisation) -> str:
        result = ""
        parent = super()
        fn = getattr(parent, "postScript", None)
        if callable(fn):
            result = fn(node, identifier, serialisation) or ""
        return result + identifier + "._finish_load()\n"


Gaffer.Serialisation.registerSerialiser(
    ShadingTk, _ShadingTkSerialiser()
)
