"""Node Editor card for sdvRenderSettings — Standard Options, then engine options."""

from __future__ import annotations

import functools
import os

import Gaffer
import GafferUI
import IECore
import imath

from sdvTkGaffer.sdvRenderSettings.sdvRenderSettings import sdvRenderSettings
from sdvTkGaffer.sdvRenderSettings._data import (
    engine_available,
    engine_label,
    import_engine_ui,
)

from ._editor import CardNodeWidget, expand_h, native_widget, widget_is_alive
from ._icons import register_node_icon

BOX_SLATE = imath.Color3f(0.30, 0.32, 0.38)


class _SavePresetDialogue(GafferUI.Dialogue):
    def __init__(self, node, **kw) -> None:
        try:
            GafferUI.Dialogue.__init__(
                self,
                "Save Preset",
                sizeMode=GafferUI.Window.SizeMode.Automatic,
                **kw
            )
        except TypeError:
            GafferUI.Dialogue.__init__(self, "Save Preset", **kw)
        self.__node = node
        self.__engine = ""
        try:
            self.__engine = node["renderEngine"].getValue() or ""
        except Exception:
            self.__engine = ""
        column = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=6
        )
        column.append(GafferUI.Label("Preset name (no spaces)"))
        self.__name = GafferUI.TextWidget()
        try:
            self.__name.setPlaceholderText("Preview")
        except Exception:
            pass
        column.append(self.__name)
        self.__hint = GafferUI.Label(
            "File: {}_Name.yaml".format((self.__engine or "render").capitalize())
        )
        column.append(self.__hint)
        self.__status = GafferUI.Label("")
        column.append(self.__status)
        self._setWidget(column)
        self._addButton("Cancel")
        self.__save = self._addButton("Save")
        self.__save.setEnabled(False)
        self.__textChangedConnection = self.__name.textChangedSignal().connect(
            Gaffer.WeakMethod(self.__onTextChanged),
            scoped=True,
        )
        self.__activatedConnection = None
        activated = getattr(self.__name, "activatedSignal", None)
        if callable(activated):
            self.__activatedConnection = activated().connect(
                Gaffer.WeakMethod(self.__onActivated),
                scoped=True,
            )

    def waitForName(self, **kw) -> str:
        try:
            self.__name.setFocus()
        except Exception:
            pass
        button = self.waitForButton(**kw)
        if button is self.__save:
            return (self.__name.getText() or "").strip()
        return ""

    def __onActivated(self, *unused) -> None:
        if not self.__save.getEnabled():
            return
        try:
            self.__save._qtWidget().click()
        except Exception:
            pass

    def __onTextChanged(self, *unused) -> None:
        from sdvTkGaffer.sdvRenderSettings._presets import filename_for, validate_preset_name

        name = (self.__name.getText() or "").strip()
        if name:
            try:
                self.__hint.setText(
                    "File: {}".format(filename_for(name, self.__engine))
                )
            except Exception:
                pass
        else:
            try:
                self.__hint.setText(
                    "File: {}_Name.yaml".format(
                        (self.__engine or "render").capitalize()
                    )
                )
            except Exception:
                pass
        if not name:
            self.__save.setEnabled(False)
            try:
                self.__status.setText("")
            except Exception:
                pass
            return
        error = validate_preset_name(name, self.__node, self.__engine)
        self.__save.setEnabled(error is None)
        try:
            self.__status.setText("" if error is None else error)
        except Exception:
            pass


def _plug_widget(plug: Gaffer.Plug) -> GafferUI.Widget | None:
    try:
        return native_widget(plug)
    except Exception:
        return None


def _clear_container(container: GafferUI.ListContainer) -> None:
    children = list(container)
    for child in children:
        try:
            container.removeChild(child)
        except Exception:
            pass


def _settings_widget(parent_plug) -> GafferUI.Widget:
    if parent_plug is None:
        return GafferUI.Label("This render engine is not available in this Gaffer.")
    try:
        layout = GafferUI.PlugLayout(parent_plug)
        expand_h(layout)
        return layout
    except Exception:
        pass
    try:
        created = GafferUI.PlugValueWidget.create(parent_plug)
        if created is not None:
            expand_h(created)
            return created
    except Exception:
        pass
    column = GafferUI.ListContainer(
        GafferUI.ListContainer.Orientation.Vertical, spacing=4
    )
    for child in parent_plug.children():
        if child.getName().startswith("__"):
            continue
        widget = _plug_widget(child)
        if widget is None:
            continue
        row = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=8
        )
        label = Gaffer.Metadata.value(child, "label") or IECore.CamelCase.toSpaced(
            child.getName()
        )
        row.append(GafferUI.Label(str(label)))
        expand_h(widget)
        row.append(widget, expand=True)
        column.append(row)
    if not list(column):
        column.append(GafferUI.Label("No settings to display."))
    expand_h(column)
    return column


class _sdvRenderSettingsWidget(CardNodeWidget):
    _LABEL_W = 130

    def _build(self) -> None:
        card = self._addCard("Render Settings")

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
        for plug_name, label in (
            ("enableSubdivision", "Enable Subdivision"),
            ("enableDisplacement", "Enable Displacement"),
        ):
            widget = GafferUI.BoolPlugValueWidget(self._node[plug_name])
            try:
                widget.boolWidget().setText(label)
            except Exception:
                toggles.append(GafferUI.Label(label))
            try:
                widget.setToolTip(
                    Gaffer.Metadata.value(self._node[plug_name], "description") or ""
                )
            except Exception:
                pass
            toggles.append(widget)
        card.append(toggles)
        background = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=8
        )
        background_label = GafferUI.Label("Background")
        try:
            background_label._qtWidget().setFixedWidth(self._LABEL_W)
        except Exception:
            pass
        background.append(background_label)
        background.append(GafferUI.BoolPlugValueWidget(self._node["background"]))
        color = GafferUI.PlugValueWidget.create(self._node["backgroundColor"])
        if color is not None:
            expand_h(color)
            background.append(color, expand=True)
        card.append(background)
        try:
            from sdvTkGafferUI.viewerSync import sync_node

            sync_node(self._node)
        except Exception:
            pass

        self._tabs = GafferUI.TabbedContainer()
        expand_h(self._tabs)
        card.append(self._tabs)

        self._standard_form = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8
        )
        self._standard_tab = self._scroll(self._standard_form)
        self._add_tab(self._tabs, self._standard_tab, "Standard Options")

        self._options_form = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8
        )
        self._options_tab = self._scroll(self._options_form)
        self._add_tab(self._tabs, self._options_tab, self._options_tab_name())

        self._fill_standard_tab()
        self._fill_options_tab()

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

    def _options_tab_name(self) -> str:
        return "{} Options".format(engine_label(self._node.currentEngine()))

    def _fill_standard_tab(self) -> None:
        if not widget_is_alive(self):
            return
        _clear_container(self._standard_form)
        self._standard_form.append(
            GafferUI.Label(
                "Default Renderer follows Renderer above."
            )
        )
        standard = self._node.standardOptionsNode()
        if standard is None or "options" not in standard:
            self._standard_form.append(
                GafferUI.Label("Standard Options is not available in this Gaffer.")
            )
            return
        self._standard_form.append(_settings_widget(standard["options"]))

    def _fill_options_tab(self) -> None:
        if not widget_is_alive(self):
            return
        _clear_container(self._options_form)
        try:
            self._tabs.setLabel(self._options_tab, self._options_tab_name())
        except Exception:
            pass

        engine = self._node.currentEngine()
        import_engine_ui(engine)

        presets = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=6
        )
        selector = GafferUI.MenuButton(
            "Preset",
            menu=GafferUI.Menu(Gaffer.WeakMethod(self._presetMenuDefinition)),
        )
        try:
            selector.setToolTip(
                "Choose a YAML preset from the presets/ folder (and optional "
                "preset folder)."
            )
        except Exception:
            pass
        save = GafferUI.Button("Save")
        load = GafferUI.Button("Load")
        try:
            save.setToolTip("Save current render settings as a YAML preset.")
            load.setToolTip("Load a YAML preset from a file.")
        except Exception:
            pass
        self._buttonConnections.append(
            save.clickedSignal().connect(
                Gaffer.WeakMethod(self.__onSavePreset), scoped=True
            )
        )
        self._buttonConnections.append(
            load.clickedSignal().connect(
                Gaffer.WeakMethod(self.__onLoadPreset), scoped=True
            )
        )
        presets.append(selector)
        presets.append(save)
        presets.append(load)
        presets.append(GafferUI.Spacer(imath.V2i(8, 1)), expand=True)
        self._options_form.append(presets)
        self._addRow(
            self._options_form,
            "Preset Folder",
            native_widget(self._node["presetFolder"]),
            name="presetFolder",
        )

        options_node = self._node.optionsNode()
        if options_node is None:
            if engine_available(engine):
                message = "No options node for {}.".format(engine_label(engine))
            else:
                message = (
                    "{} is not available in this Gaffer. The scene passes "
                    "through this engine's settings."
                ).format(engine_label(engine))
            self._options_form.append(GafferUI.Label(message))
            return
        if "options" in options_node:
            self._options_form.append(_settings_widget(options_node["options"]))

    def _onPlugDirtied(self, plug: Gaffer.Plug) -> None:
        if plug.getName() == "renderEngine":
            self.__rebuildOptionsLazily()

    @GafferUI.LazyMethod()
    def __rebuildOptionsLazily(self) -> None:
        self._fill_options_tab()

    def _presetMenuDefinition(self, *unused) -> IECore.MenuDefinition:
        md = IECore.MenuDefinition()
        presets = []
        try:
            presets = list(self._node.listPresets())
        except Exception:
            presets = []
        current = ""
        try:
            current = self._node.currentEngine()
        except Exception:
            current = ""
        if not presets:
            md.append("/No presets found", {"active": False})
        else:
            matching = [p for p in presets if p.get("engine") == current]
            other = [p for p in presets if p.get("engine") != current]
            for preset in matching:
                md.append(
                    "/" + preset["name"],
                    {
                        "command": functools.partial(
                            self.__onApplyPreset,
                            preset["name"],
                            preset.get("engine"),
                        ),
                        "description": "{} ({})".format(
                            preset["name"], preset.get("source")
                        ),
                    },
                )
            if matching and other:
                md.append("/__divA", {"divider": True})
            for preset in other:
                md.append(
                    "/Other/{}/{}".format(
                        engine_label(str(preset.get("engine") or "")),
                        preset["name"],
                    ),
                    {
                        "command": functools.partial(
                            self.__onApplyPreset,
                            preset["name"],
                            preset.get("engine"),
                        )
                    },
                )
        md.append("/__divFolder", {"divider": True})
        md.append(
            "/Choose Preset Folder…",
            {"command": Gaffer.WeakMethod(self.__onChoosePresetFolder)},
        )
        md.append(
            "/Open Preset Folder",
            {"command": Gaffer.WeakMethod(self.__onOpenPresetFolder)},
        )
        md.append(
            "/Use Module Presets Folder",
            {"command": Gaffer.WeakMethod(self.__onClearPresetFolder)},
        )
        return md

    def __onApplyPreset(self, name: str, engine=None, *unused) -> None:
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            applied = self._node.applyPreset(name, engine)
        self._fill_options_tab()
        IECore.msg(
            IECore.Msg.Level.Info if applied else IECore.Msg.Level.Warning,
            "sdvRenderSettings",
            "Applied '{}' ({} values).".format(name, applied)
            if applied
            else "Could not apply preset '{}'.".format(name),
        )

    def __onSavePreset(self, *unused) -> None:
        parent = None
        try:
            parent = self.ancestor(GafferUI.Window)
        except Exception:
            parent = None
        try:
            dialogue = _SavePresetDialogue(self._node)
            name = dialogue.waitForName(parentWindow=parent)
        except Exception as exc:
            IECore.msg(
                IECore.Msg.Level.Error,
                "sdvRenderSettings",
                "Could not open Save Preset ({})".format(exc),
            )
            return
        name = (name or "").strip()
        if not name:
            return
        try:
            path = self._node.savePreset(name)
        except Exception as exc:
            self.__presetError("Could not save preset.\n{}".format(exc), parent)
            return
        IECore.msg(
            IECore.Msg.Level.Info,
            "sdvRenderSettings",
            "Saved preset '{}' to {}.".format(name, path),
        )

    def __onLoadPreset(self, *unused) -> None:
        from sdvTkGaffer.sdvRenderSettings._presets import dialog_start_dir

        path = _pick_file(self, dialog_start_dir(self._node))
        if not path:
            return
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            applied = self._node.loadPresetFile(path)
        self._fill_options_tab()
        IECore.msg(
            IECore.Msg.Level.Info if applied else IECore.Msg.Level.Warning,
            "sdvRenderSettings",
            "Loaded '{}' ({} values).".format(os.path.basename(path), applied)
            if applied
            else "Could not load '{}'.".format(path),
        )

    def __presetError(self, message: str, parent) -> None:
        try:
            GafferUI.ErrorDialogue.displayError(
                "Save Preset", message, parentWindow=parent
            )
            return
        except Exception:
            pass
        IECore.msg(IECore.Msg.Level.Error, "sdvRenderSettings", message)

    def __onChoosePresetFolder(self, *unused) -> None:
        from sdvTkGaffer.sdvRenderSettings._presets import dialog_start_dir, is_gaffer_bin_dir

        chosen = _pick_directory(self, dialog_start_dir(self._node))
        if not chosen or is_gaffer_bin_dir(chosen):
            return
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node["presetFolder"].setValue(chosen)

    def __onOpenPresetFolder(self, *unused) -> None:
        from sdvTkGaffer.sdvRenderSettings._presets import is_gaffer_bin_dir, save_dir

        path = save_dir(self._node)
        if not path or is_gaffer_bin_dir(path):
            return
        if not os.path.isdir(path):
            return
        _open_directory(path)

    def __onClearPresetFolder(self, *unused) -> None:
        from sdvTkGaffer.sdvRenderSettings._presets import discovered_presets_dir

        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node["presetFolder"].setValue(discovered_presets_dir())


def _sdvRenderSettingsWidgetCreator(node: Gaffer.Node) -> _sdvRenderSettingsWidget:
    return _sdvRenderSettingsWidget(node)


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
        "description": "Incoming scene with renderer options applied "
        "(passthrough of in when disabled).",
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
        "description": "Renderer for this node. Drives Standard Options "
        "Default Renderer (Arnold, RenderMan, or Cycles). Saved scenes "
        "keep the stored engine. Unused engine nodes are disabled.",
        "nodule:type": "",
        "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
        "preset:Arnold": "arnold",
        "preset:RenderMan": "renderman",
        "preset:Cycles": "cycles",
    },
    "presetFolder": {
        "description": "Folder of YAML render-settings presets. New nodes "
        "bind to ../../presets relative to this module when that folder "
        "exists; otherwise this stays blank. Gaffer's bin folder is "
        "never used. Also searches SDVRENDERSETTINGS_PRESET_PATH.",
        "nodule:type": "",
        "plugValueWidget:type": "GafferUI.FileSystemPathPlugValueWidget",
        "path:leaf": False,
    },
}
Gaffer.Metadata.registerNode(
    sdvRenderSettings,
    "description",
    "Standard Options, then renderer options (Arnold / RenderMan / Cycles). "
    "Renderer drives Standard Options Default Renderer. Renderer options "
    "keep YAML presets. Attribute sets live on sdvRenderAttributes.",
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
    "layout:customWidget:sdvRenderSettings:widgetType",
    "sdvRenderSettingsUI.sdvRenderSettingsUI._sdvRenderSettingsWidgetCreator",
    "layout:customWidget:sdvRenderSettings:section",
    "Settings",
    "layout:customWidget:sdvRenderSettings:index",
    0,
    "layout:activator:never",
    False,
    plugs=_plugs,
)

register_node_icon(sdvRenderSettings, "sdvRenderSettings.png")


def _pick_directory(widget: GafferUI.Widget, start: str) -> str:
    try:
        from Qt import QtWidgets

        parent = None
        try:
            parent = widget._qtWidget()
        except Exception:
            parent = None
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            parent, "Preset folder", start or ""
        )
        return chosen or ""
    except Exception:
        return ""


def _pick_file(widget: GafferUI.Widget, start: str) -> str:
    try:
        from Qt import QtWidgets

        parent = None
        try:
            parent = widget._qtWidget()
        except Exception:
            parent = None
        chosen, _unused = QtWidgets.QFileDialog.getOpenFileName(
            parent, "Load preset", start or "", "YAML (*.yaml *.yml)"
        )
        return chosen or ""
    except Exception:
        return ""


def _open_directory(path: str) -> None:
    if not path:
        return
    try:
        if os.name == "nt":
            os.startfile(path)  # noqa: S606
            return
        import subprocess

        subprocess.Popen(["xdg-open", path])
    except Exception:
        pass
