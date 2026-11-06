"""sdvRenderSettings — Standard Options and renderer options.

Arnold, RenderMan, or Cycles. Unused engine nodes are disabled so only
the active renderer does work. Attribute sets live on sdvRenderAttributes.
This is ``sdvRenderSettings.sdvRenderSettings``.
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
    set_plug_value,
    sync_enabled_switch,
)
from ._data import (
    ENGINE_LABELS,
    ENGINE_ORDER,
    INTERNAL_STANDARD_OPTIONS,
    default_engine,
    engine_label,
    internal_options,
    make_options_node,
)


class sdvRenderSettings(SceneInsertMixin, Gaffer.Box):
    """Standard options plus renderer options."""

    def __init__(self, name: str = "sdvRenderSettings"):
        Gaffer.Box.__init__(self, name)

        engine = default_engine()
        self.addChild(GafferScene.ScenePlug("in", Gaffer.Plug.Direction.In))
        engine_plug = Gaffer.StringPlug("renderEngine", defaultValue=engine)
        self.addChild(engine_plug)
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
        return self._options_tail()

    def _sync_driven_plugs(self) -> None:
        """Write the enabled switch and per-engine flags from public plugs."""
        self._wire_options_chain()
        sync_enabled_switch(self)
        self._sync_standard_renderer()
        engine = self.currentEngine()
        for item in ENGINE_ORDER:
            options = self.getChild(internal_options(item))
            if options is None or "enabled" not in options:
                continue
            set_plug_value(options["enabled"], item == engine)
        enabled = self.getChild(ENABLED_SWITCH)
        if enabled is not None:
            enabled["in"][1].setInput(self._chain_tail())

    def currentEngine(self) -> str:
        try:
            value = (self["renderEngine"].getValue() or "").strip()
        except Exception:
            value = ""
        return value or default_engine()

    def optionsNode(self) -> Gaffer.Node | None:
        return self.getChild(internal_options(self.currentEngine()))

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

        applied = apply_snapshot(self, data)
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
    "Standard options plus renderer options (Arnold / RenderMan / Cycles). "
    "Enable Subdivision and Enable Displacement drive the matching "
    "toggles in the Viewer Arnold settings menu, and revert when this "
    "node is deleted. Renderer drives Standard Options Default Renderer. "
    "Attribute sets live on sdvRenderAttributes. "
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
