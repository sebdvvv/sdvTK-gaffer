"""sdvRenderSettings — Standard Options, renderer options, and up to 8 attribute sets.

Arnold, RenderMan, or Cycles. Unused engine nodes are disabled so only
the active renderer does work. This is ``sdvRenderSettings.sdvRenderSettings``.
"""

from __future__ import annotations

import Gaffer
import GafferScene
import IECore

from ._box import (
    ENABLED_SWITCH,
    BoxNetworkSerialiser,
    SceneInsertMixin,
    add_enabled_switch,
    set_filter_paths,
    set_plug_value,
    set_switch_index,
    sync_enabled_switch,
)
from ._data import (
    ENGINE_LABELS,
    ENGINE_ORDER,
    MAX_PATHS,
    MAX_SLOTS,
    INTERNAL_STANDARD_OPTIONS,
    default_engine,
    default_set_name,
    engine_label,
    internal_attributes,
    internal_filter,
    internal_options,
    internal_switch,
    make_attributes_node,
    make_options_node,
    path_count_plug,
    path_plug,
    set_name_plug,
)


class sdvRenderSettings(SceneInsertMixin, Gaffer.Box):
    """Renderer options plus optional per-prim attribute sets."""

    def __init__(self, name: str = "sdvRenderSettings"):
        Gaffer.Box.__init__(self, name)

        engine = default_engine()
        self.addChild(GafferScene.ScenePlug("in", Gaffer.Plug.Direction.In))
        engine_plug = Gaffer.StringPlug("renderEngine", defaultValue=engine)
        self.addChild(engine_plug)
        self.addChild(
            Gaffer.IntPlug(
                "slotCount",
                defaultValue=0,
                minValue=0,
                maxValue=MAX_SLOTS,
            )
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
        Gaffer.Metadata.registerValue(engine_plug, "nodule:type", "")
        Gaffer.Metadata.registerValue(
            engine_plug, "plugValueWidget:type", "GafferUI.PresetsPlugValueWidget"
        )
        for value, label in ENGINE_LABELS.items():
            Gaffer.Metadata.registerValue(engine_plug, "preset:" + label, value)

        for plug_name, label, text in (
            (
                "enableSubdivision",
                "Enable Subdivision",
                "Drives Enable Subdivision in the Viewer Arnold settings "
                "menu (top-left of the viewport). While this node is in "
                "the script, that viewport toggle follows this checkbox. "
                "Deleting the node restores the viewport default.",
            ),
            (
                "enableDisplacement",
                "Enable Displacement",
                "Drives Enable Displacement in the Viewer Arnold settings "
                "menu. While this node is in the script, that viewport "
                "toggle follows this checkbox. Deleting the node restores "
                "the viewport default.",
            ),
        ):
            plug = Gaffer.BoolPlug(plug_name, defaultValue=False)
            self.addChild(plug)
            Gaffer.Metadata.registerValue(plug, "nodule:type", "")
            Gaffer.Metadata.registerValue(plug, "label", label)
            Gaffer.Metadata.registerValue(plug, "description", text)

        for index in range(1, MAX_SLOTS + 1):
            self.__add_slot_plugs(index, engine)

        self.__add_standard_options()

        last = self._wire_options_chain()
        for item in ENGINE_ORDER:
            options = make_options_node(item, internal_options(item))
            if options is None:
                continue
            self.addChild(options)
            options["in"].setInput(last)
            last = options["out"]
            if "enabled" in options:
                options["enabled"].setValue(item == engine)

        switch = add_enabled_switch(self, last)
        Gaffer.PlugAlgo.promote(switch["out"])

        self._bind_signals()
        self.__slotsReady = True
        self._sync_driven_plugs()
        try:
            from sdvTkGafferUI.viewerSync import watch

            watch(self)
        except Exception:
            pass

    def __add_slot_plugs(self, index: int, engine: str) -> None:
        name_plug = Gaffer.StringPlug(
            set_name_plug(index), defaultValue=default_set_name(engine, index)
        )
        count_plug = Gaffer.IntPlug(
            path_count_plug(index), defaultValue=1, minValue=1, maxValue=MAX_PATHS
        )
        self.addChild(name_plug)
        self.addChild(count_plug)
        Gaffer.Metadata.registerValue(name_plug, "nodule:type", "")
        Gaffer.Metadata.registerValue(count_plug, "nodule:type", "")
        Gaffer.Metadata.registerValue(name_plug, "label", "Attribute Set")
        for path_index in range(1, MAX_PATHS + 1):
            path = Gaffer.StringPlug(path_plug(index, path_index), defaultValue="")
            self.addChild(path)
            Gaffer.Metadata.registerValue(path, "label", "PrimPath(es) :")
            Gaffer.Metadata.registerValue(
                path,
                "plugValueWidget:type",
                "GafferUI.StringPlugValueWidget",
            )
            Gaffer.Metadata.registerValue(path, "nodule:type", "")

    def __getitem__(self, key):
        if isinstance(key, str):
            self._maybe_ensure_from_child_name(key)
        return Gaffer.Box.__getitem__(self, key)

    def _maybe_ensure_from_child_name(self, name: str) -> None:
        if not getattr(self, "_sdvRenderSettings__slotsReady", False):
            return
        if self.getChild(name) is not None:
            return
        for prefix in ("__pathFilter", "__slotSwitch"):
            if name.startswith(prefix):
                suffix = name[len(prefix) :]
                if suffix.isdigit():
                    self._ensure_slot(int(suffix))
                return
        for engine in ENGINE_ORDER:
            prefix = "__{}Attributes".format(engine)
            if name.startswith(prefix):
                suffix = name[len(prefix) :]
                if suffix.isdigit():
                    self._ensure_slot(int(suffix))
                return

    def _ensure_slots(self, count: int) -> None:
        for index in range(1, max(0, min(int(count), MAX_SLOTS)) + 1):
            self._ensure_slot(index)

    def _ensure_slot(self, index: int) -> None:
        if index < 1 or index > MAX_SLOTS:
            return
        for previous in range(1, index):
            self._ensure_slot(previous)
        if self.getChild(internal_switch(index)) is not None:
            return
        source = self._options_tail()
        if index > 1:
            prev = self.getChild(internal_switch(index - 1))
            if prev is not None:
                source = prev["out"]
        self.__add_slot_network(index, source)
        enabled = self.getChild(ENABLED_SWITCH)
        if enabled is not None:
            enabled["in"][1].setInput(self._chain_tail())
        self._sync_driven_plugs()

    def __add_standard_options(self) -> None:
        if self.getChild(INTERNAL_STANDARD_OPTIONS) is not None:
            return
        try:
            standard = GafferScene.StandardOptions(INTERNAL_STANDARD_OPTIONS)
        except Exception:
            return
        self.addChild(standard)
        standard["in"].setInput(self["in"])
        self.__lock_default_renderer(standard)

    @staticmethod
    def __lock_default_renderer(standard: Gaffer.Node) -> None:
        """Default Renderer is driven by this node's Renderer menu."""
        try:
            option = standard["options"]["render:defaultRenderer"]
        except Exception:
            return
        for plug, text in (
            (
                option["value"] if "value" in option else None,
                "Follows Renderer on this node.",
            ),
            (
                option["enabled"] if "enabled" in option else None,
                "Kept on so Renderer authors the default renderer.",
            ),
        ):
            if plug is None:
                continue
            Gaffer.Metadata.registerValue(plug, "readOnly", True)
            Gaffer.Metadata.registerValue(plug, "description", text)

    def standardOptionsNode(self) -> Gaffer.Node | None:
        return self.getChild(INTERNAL_STANDARD_OPTIONS)

    def _wire_options_chain(self):
        """Keep ``in`` → Standard Options → engine options, even after load."""
        standard = self.getChild(INTERNAL_STANDARD_OPTIONS)
        last = self["in"]
        if standard is not None and "in" in standard and "out" in standard:
            _set_input(standard["in"], self["in"])
            last = standard["out"]
        for item in ENGINE_ORDER:
            options = self.getChild(internal_options(item))
            if options is None or "in" not in options or "out" not in options:
                continue
            _set_input(options["in"], last)
            last = options["out"]
        return last

    def _sync_standard_renderer(self) -> None:
        standard = self.standardOptionsNode()
        if standard is None or "options" not in standard:
            return
        try:
            option = standard["options"]["render:defaultRenderer"]
        except Exception:
            return
        if "enabled" in option:
            set_plug_value(option["enabled"], True)
        if "value" in option:
            set_plug_value(option["value"], engine_label(self.currentEngine()))

    def _options_tail(self):
        standard = self.getChild(INTERNAL_STANDARD_OPTIONS)
        last = standard["out"] if standard is not None else self["in"]
        for engine in ENGINE_ORDER:
            options = self.getChild(internal_options(engine))
            if options is not None:
                last = options["out"]
        return last

    def _chain_tail(self):
        for index in range(MAX_SLOTS, 0, -1):
            switch = self.getChild(internal_switch(index))
            if switch is not None:
                return switch["out"]
        return self._options_tail()

    def __add_slot_network(self, index: int, source) -> None:
        path_filter = self.getChild(internal_filter(index))
        if path_filter is None:
            path_filter = GafferScene.PathFilter(internal_filter(index))
            self.addChild(path_filter)
            path_filter["paths"].setValue(IECore.StringVectorData())

        previous = source
        current = self.currentEngine()
        for engine in ENGINE_ORDER:
            child_name = internal_attributes(engine, index)
            attr = self.getChild(child_name)
            if attr is None:
                attr = make_attributes_node(engine, child_name)
                if attr is None:
                    continue
                self.addChild(attr)
            attr["in"].setInput(previous)
            if "filter" in attr:
                attr["filter"].setInput(path_filter["out"])
            if "enabled" in attr:
                attr["enabled"].setValue(engine == current)
            previous = attr["out"]

        slot_switch = self.getChild(internal_switch(index))
        if slot_switch is None:
            slot_switch = Gaffer.Switch(internal_switch(index))
            self.addChild(slot_switch)
            slot_switch.setup(GafferScene.ScenePlug("in"))
            slot_switch["in"].resize(2)
        slot_switch["in"][0].setInput(source)
        slot_switch["in"][1].setInput(previous)

    def _sync_driven_plugs(self) -> None:
        """Write Switch / PathFilter / enabled flags from public plugs."""
        self._wire_options_chain()
        sync_enabled_switch(self)
        self._sync_standard_renderer()
        engine = self.currentEngine()
        try:
            count = int(self["slotCount"].getValue())
        except Exception:
            count = 0
        for item in ENGINE_ORDER:
            options = self.getChild(internal_options(item))
            if options is None or "enabled" not in options:
                continue
            set_plug_value(options["enabled"], item == engine)
        for index in range(1, MAX_SLOTS + 1):
            if self.getChild(internal_switch(index)) is None:
                continue
            active = count >= index
            set_switch_index(self, internal_switch(index), 1 if active else 0)
            for item in ENGINE_ORDER:
                attr = self.getChild(internal_attributes(item, index))
                if attr is None or "enabled" not in attr:
                    continue
                set_plug_value(attr["enabled"], item == engine and active)
            try:
                path_count = int(self[path_count_plug(index)].getValue())
            except Exception:
                path_count = 1
            path_count = max(1, min(path_count, MAX_PATHS))
            paths = []
            for path_index in range(1, path_count + 1):
                try:
                    raw = (self[path_plug(index, path_index)].getValue() or "").replace(
                        "\\", "/"
                    ).strip()
                except Exception:
                    raw = ""
                if not raw:
                    continue
                paths.append(raw if raw.startswith("/") else "/" + raw)
            set_filter_paths(self, internal_filter(index), paths)

    def currentEngine(self) -> str:
        try:
            value = (self["renderEngine"].getValue() or "").strip()
        except Exception:
            value = ""
        return value or default_engine()

    def optionsNode(self) -> Gaffer.Node | None:
        return self.getChild(internal_options(self.currentEngine()))

    def attributesNode(self, index: int) -> Gaffer.Node | None:
        return self.getChild(internal_attributes(self.currentEngine(), index))

    def addSlot(self) -> None:
        count = self["slotCount"].getValue()
        if count >= MAX_SLOTS:
            return
        next_index = count + 1
        engine = self.currentEngine()
        name_plug = self[set_name_plug(next_index)]
        current = (name_plug.getValue() or "").strip()
        baked = default_set_name(default_engine(), next_index)
        if not current or current == baked:
            name_plug.setValue(default_set_name(engine, next_index))
        self._ensure_slots(next_index)
        self["slotCount"].setValue(next_index)

    def removeSlot(self) -> None:
        count = self["slotCount"].getValue()
        if count <= 0:
            return
        self.clearSlot(count)
        self["slotCount"].setValue(count - 1)

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

    def clearSlot(self, index: int) -> None:
        self[set_name_plug(index)].setValue(
            default_set_name(self.currentEngine(), index)
        )
        self[path_count_plug(index)].setValue(1)
        for path_index in range(1, MAX_PATHS + 1):
            self[path_plug(index, path_index)].setValue("")
        attr = self.attributesNode(index)
        if attr is not None and "attributes" in attr:
            reset = getattr(attr["attributes"], "setToDefault", None)
            if callable(reset):
                try:
                    reset()
                except Exception:
                    pass
            else:
                for plug in attr["attributes"].children():
                    child_reset = getattr(plug, "setToDefault", None)
                    if callable(child_reset):
                        try:
                            child_reset()
                        except Exception:
                            pass

    def listPresets(self) -> list:
        from ._presets import list_presets

        return list_presets(self)

    def applyPreset(self, name: str, engine: str | None = None) -> int:
        from ._presets import apply_preset, list_presets

        for preset in list_presets(self):
            if preset.get("name") != name:
                continue
            if engine is not None and preset.get("engine") != engine:
                continue
            return apply_preset(self, preset)
        return 0

    def savePreset(self, name: str, folder: str | None = None) -> str:
        from ._presets import save_settings_preset

        return save_settings_preset(self, name, folder)

    def loadPresetFile(self, path: str) -> int:
        from ._presets import apply_preset, load_preset_file

        data = load_preset_file(path)
        if not data:
            return 0
        return apply_preset(self, data)

    def copyValues(self) -> dict:
        from ._values import snapshot

        return snapshot(self)

    def pasteValues(self, data: dict | None) -> int:
        from ._values import apply_snapshot

        applied = apply_snapshot(
            self, data, ensure=lambda: self._ensure_slots(self["slotCount"].getValue())
        )
        self._sync_driven_plugs()
        return applied

    def resetValues(self) -> None:
        from ._values import reset_values

        reset_values(self)
        self._sync_driven_plugs()

    def _bind_signals(self) -> None:
        self.__plugSetConnection = self.plugSetSignal().connect(
            Gaffer.WeakMethod(self._on_plug_set), scoped=True
        )
        self.__parentChangedConnection = self.parentChangedSignal().connect(
            Gaffer.WeakMethod(self._on_parent_changed), scoped=True
        )

    def _on_parent_changed(self, *_args) -> None:
        if self.parent() is None:
            return
        script = self.scriptNode()
        if script is None:
            self._wire_options_chain()
            return
        loading = False
        is_executing = getattr(script, "isExecuting", None)
        if callable(is_executing):
            try:
                loading = bool(is_executing())
            except Exception:
                loading = False
        if loading and not getattr(self, "_sdvRenderSettings__loadedConn", None):
            loaded = getattr(script, "scriptLoadedSignal", None)
            if callable(loaded):
                self.__loadedConn = loaded().connect(
                    Gaffer.WeakMethod(self._on_script_loaded), scoped=True
                )
            return
        self._wire_options_chain()

    def _on_script_loaded(self, *_args) -> None:
        self._wire_options_chain()
        self._sync_standard_renderer()

    def _on_plug_set(self, plug: Gaffer.Plug) -> None:
        name = plug.getName()
        if name == "slotCount":
            try:
                self._ensure_slots(int(plug.getValue()))
            except Exception:
                pass
        if getattr(self, "_sdvRenderSettings__slotsReady", False):
            self._sync_driven_plugs()


def _set_input(plug: Gaffer.Plug, source: Gaffer.Plug) -> None:
    try:
        current = plug.getInput()
    except Exception:
        current = None
    if current is not None:
        try:
            if current.isSame(source):
                return
        except Exception:
            pass
    try:
        plug.setInput(source)
    except Exception:
        pass


sdvRenderSettings.__module__ = "sdvRenderSettings.sdvRenderSettings"
IECore.registerRunTimeTyped(sdvRenderSettings)

Gaffer.Metadata.registerNode(
    sdvRenderSettings,
    "description",
    "Standard options plus renderer options (Arnold / RenderMan / Cycles) "
    "and up to eight attribute sets, each with its own PathFilter. "
    "Enable Subdivision and Enable Displacement drive the matching "
    "toggles in the Viewer Arnold settings menu, and revert when this "
    "node is deleted. Renderer drives Standard Options Default Renderer. "
    "Unused engine nodes are disabled. Existing scenes keep the saved engine.",
)


class _sdvRenderSettingsSerialiser(BoxNetworkSerialiser):
    def childNeedsConstruction(
        self, child: Gaffer.GraphComponent, serialisation: Gaffer.Serialisation
    ) -> bool:
        if isinstance(child, Gaffer.Plug) and child.getName() == "out":
            return False
        return super().childNeedsConstruction(child, serialisation)


Gaffer.Serialisation.registerSerialiser(
    sdvRenderSettings, _sdvRenderSettingsSerialiser()
)
