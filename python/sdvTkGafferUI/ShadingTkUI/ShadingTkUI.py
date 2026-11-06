"""Node Editor card for ShadingTk — Create or Edit mode."""

from __future__ import annotations

import functools
import os

import Gaffer
import GafferUI
import IECore
import imath

from sdvTkGaffer.ShadingTk.ShadingTk import ShadingTk
from sdvTkGaffer.ShadingTk._data import (
    ALL_SHADER_NAME,
    assign_path_plug,
    assign_slot_label,
    assign_source_plug,
    LAYER_SHADER,
    MAX_MIX_INPUTS,
    MAX_PATHS,
    MAX_SLOTS,
    MODE_CREATE,
    MODE_EDIT,
    MIX_SHADER,
    mix_input_plug,
    path_count_plug,
    path_plug,
    shader_file_prefix,
    shader_name_plug,
    shader_type_plug,
    slot_label,
    texture_type_plug,
    displacement_type_plug,
)
from sdvTkGaffer.ShadingTk._sampling import (
    SAMPLE_OPTION_KEYS,
    engine_label,
    import_engine_ui,
)
from sdvTkGaffer.ShadingTk._box import parse_prim_paths
from sdvTkGaffer.ShadingTk._scene import has_scene_input

from ._editor import (
    CardNodeWidget,
    clear_container,
    expand_h,
    native_widget,
    plug_widget,
    release_plug_widgets,
    widget_is_alive,
)
from ._icons import register_node_icon

BOX_PURPLE = imath.Color3f(72 / 255, 36 / 255, 118 / 255)
HAS_TEXTURES_COLOR = "#43a047"


class _SavePresetDialogue(GafferUI.Dialogue):
    """Small name prompt — no spaces, no overwrite of existing YAML presets."""

    def __init__(self, node, index: int, **kw) -> None:
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
        self.__shader = ""
        try:
            self.__shader = node[shader_type_plug(index)].getValue() or ""
        except Exception:
            self.__shader = ""
        column = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=6
        )
        column.append(GafferUI.Label("Preset name (no spaces)"))
        self.__name = GafferUI.TextWidget()
        try:
            self.__name.setPlaceholderText("Gold_brushed")
        except Exception:
            pass
        column.append(self.__name)
        prefix = shader_file_prefix(self.__shader) if self.__shader else "Shader"
        self.__hint = GafferUI.Label("File: {}_Name.yaml".format(prefix))
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
        from sdvTkGaffer.ShadingTk._presets import filename_for, look_name, validate_preset_name

        name = self.__name.getText() or ""
        look = look_name(name, self.__shader)
        prefix = shader_file_prefix(self.__shader) if self.__shader else "Shader"
        if look:
            try:
                self.__hint.setText(
                    "File: {}".format(filename_for(look, self.__shader))
                )
            except Exception:
                pass
        else:
            try:
                self.__hint.setText("File: {}_Name.yaml".format(prefix))
            except Exception:
                pass
        if not look:
            self.__save.setEnabled(False)
            try:
                self.__status.setText("")
            except Exception:
                pass
            return
        error = validate_preset_name(look, self.__node, self.__shader)
        self.__save.setEnabled(error is None)
        try:
            self.__status.setText("" if error is None else error)
        except Exception:
            pass


def _param_label(plug: Gaffer.Plug) -> str:
    label = Gaffer.Metadata.value(plug, "label")
    if label:
        return str(label)
    return IECore.CamelCase.toSpaced(plug.getName())


def _format_param_name(name: str) -> str:
    text = str(name or "").replace("_", " ").strip()
    if not text:
        return ""
    return IECore.CamelCase.toSpaced(text)


def _tweak_label(tweak: Gaffer.Plug) -> str:
    label = Gaffer.Metadata.value(tweak, "label")
    if label:
        return str(label)
    name = tweak.getName()
    try:
        if "name" in tweak:
            name = tweak["name"].getValue() or name
    except Exception:
        pass
    return _format_param_name(name) or _param_label(tweak)


def _escape_label(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _shader_param_label(node, plug: Gaffer.Plug) -> tuple[str, bool]:
    name = _param_label(plug)
    has_tex = False
    try:
        has_tex = bool(node.plugHasTextureInput(plug))
    except Exception:
        has_tex = False
    if not has_tex:
        return name, False
    return (
        '<font color="{}">{} (has Textures)</font>'.format(
            HAS_TEXTURES_COLOR, _escape_label(name)
        ),
        True,
    )


_plug_widget = plug_widget
_release_plug_widgets = release_plug_widgets
_clear_container = clear_container


def _selected_prim_paths(script) -> list[str]:
    """Scene Hierarchy / Viewport selection as USD-style prim paths."""
    if script is None:
        return []
    matcher = None
    try:
        import GafferSceneUI

        algo = getattr(GafferSceneUI, "ScriptNodeAlgo", None)
        if algo is not None and hasattr(algo, "getSelectedPaths"):
            matcher = algo.getSelectedPaths(script)
        else:
            context_algo = getattr(GafferSceneUI, "ContextAlgo", None)
            context = getattr(script, "context", lambda: None)()
            if context_algo is not None and context is not None:
                matcher = context_algo.getSelectedPaths(context)
    except Exception:
        matcher = None
    paths = []
    if matcher is not None:
        getter = getattr(matcher, "paths", None)
        try:
            paths = list(getter() if callable(getter) else matcher)
        except Exception:
            paths = []
    return parse_prim_paths(*[str(raw or "") for raw in paths])


def _set_selected_prim_paths(script, paths: list[str]) -> bool:
    """Select the given prim paths in the Scene Hierarchy / Viewport."""
    if script is None or not paths:
        return False
    matcher = IECore.PathMatcher(list(paths))
    try:
        import GafferSceneUI

        algo = getattr(GafferSceneUI, "ScriptNodeAlgo", None)
        if algo is not None and hasattr(algo, "setSelectedPaths"):
            algo.setSelectedPaths(script, matcher)
            return True
        context_algo = getattr(GafferSceneUI, "ContextAlgo", None)
        context = getattr(script, "context", lambda: None)()
        if context_algo is not None and context is not None:
            context_algo.setSelectedPaths(context, matcher)
            return True
    except Exception:
        return False
    return False


class _ExistingShaderWidget(GafferUI.PlugValueWidget):
    """Menu of incoming surface shaders. Optionally waits for an enable plug."""

    def __init__(
        self,
        plug,
        *,
        require_enabled: str | None = None,
        empty_label: str = "Select shader…",
        **kw,
    ) -> None:
        self._require_enabled = require_enabled
        self._empty_label = empty_label
        self._button = GafferUI.MenuButton(
            text=empty_label,
            menu=GafferUI.Menu(Gaffer.WeakMethod(self._menuDefinition)),
        )
        expand_h(self._button)
        GafferUI.PlugValueWidget.__init__(self, self._button, plug, **kw)
        self._cache: list[dict] | None = None

    def _updateFromValues(self, values, exception) -> None:
        if not widget_is_alive(self) or not widget_is_alive(self._button):
            return
        value = values[0] if values else ""
        label = ""
        for item in self._cache or []:
            if item.get("path") == value:
                label = item.get("shader") or ""
                break
        try:
            self._button.setText(
                label or (str(value) if value else self._empty_label)
            )
        except RuntimeError:
            return

    def invalidateCache(self) -> None:
        self._cache = None

    def scanNow(self) -> list[dict]:
        plug = self.getPlug()
        node = plug.node() if plug is not None else None
        found: list[dict] = []
        if node is not None and hasattr(node, "existingShaders"):
            try:
                found = list(node.existingShaders())
            except Exception:
                found = []
        self._cache = found
        return found

    def _menuDefinition(self) -> IECore.MenuDefinition:
        md = IECore.MenuDefinition()
        plug = self.getPlug()
        node = plug.node() if plug is not None else None
        if self._require_enabled:
            enabled = False
            try:
                enabled = bool(node[self._require_enabled].getValue()) if node is not None else False
            except Exception:
                enabled = False
            if not enabled:
                md.append("/Enable shader edits first", {"active": False})
                return md
        if not has_scene_input(node):
            md.append("/Connect a scene to scan shaders", {"active": False})
            return md
        shaders = self._cache
        if shaders is None:
            shaders = self.scanNow()
        if not shaders:
            md.append("/No surface shaders on incoming stage", {"active": False})
            return md
        current = plug.getValue() if plug is not None else ""
        plugs = tuple(self.getPlugs())
        for item in shaders:
            path = item.get("path") or ""
            handle = item.get("shader") or item.get("handle") or "shader"
            shader_type = item.get("type") or ""
            extra = len(item.get("paths") or [])
            description = shader_type
            if extra > 1:
                description = "{} · {} locations".format(
                    shader_type, extra
                ).strip(" ·")
            menu_path = "/" + str(handle).replace("/", "|")
            md.append(
                menu_path,
                {
                    "command": functools.partial(_set_edit_path, plugs, path),
                    "checkBox": path == current,
                    "description": description,
                },
            )
        return md


def _set_edit_path(plugs, path: str, *unused) -> None:
    script = plugs[0].ancestor(Gaffer.ScriptNode) if plugs else None
    with Gaffer.UndoScope(script):
        for plug in plugs:
            plug.setValue(path)


class _ExistingSamplingShaderWidget(GafferUI.PlugValueWidget):
    """Menu of shaders that expose sample parameters. Scans only if overrides are on."""

    def __init__(self, plug, **kw) -> None:
        self._button = GafferUI.MenuButton(
            text="Select sampling shader…",
            menu=GafferUI.Menu(Gaffer.WeakMethod(self._menuDefinition)),
        )
        expand_h(self._button)
        GafferUI.PlugValueWidget.__init__(self, self._button, plug, **kw)
        self._cache: list[dict] | None = None

    def _updateFromValues(self, values, exception) -> None:
        if not widget_is_alive(self) or not widget_is_alive(self._button):
            return
        value = values[0] if values else ""
        label = ""
        for item in self._cache or []:
            if item.get("path") == value:
                label = item.get("shader") or ""
                break
        try:
            self._button.setText(
                label or (str(value) if value else "Select sampling shader…")
            )
        except RuntimeError:
            return

    def invalidateCache(self) -> None:
        self._cache = None

    def scanNow(self) -> list[dict]:
        plug = self.getPlug()
        node = plug.node() if plug is not None else None
        found: list[dict] = []
        if node is not None and hasattr(node, "existingSamplingShaders"):
            try:
                found = list(node.existingSamplingShaders())
            except Exception:
                found = []
        self._cache = found
        return found

    def _menuDefinition(self) -> IECore.MenuDefinition:
        md = IECore.MenuDefinition()
        plug = self.getPlug()
        node = plug.node() if plug is not None else None
        if node is None or not node["samplingEnabled"].getValue():
            md.append(
                "/Enable Shader sampling overrides first", {"active": False}
            )
            return md
        if not has_scene_input(node):
            md.append("/Connect a scene to scan shaders", {"active": False})
            return md
        shaders = self._cache
        if shaders is None:
            shaders = self.scanNow()
        if not shaders:
            md.append("/No sampling shaders on incoming stage", {"active": False})
            return md
        current = plug.getValue() if plug is not None else ""
        plugs = tuple(self.getPlugs())
        for item in shaders:
            path = item.get("path") or ""
            handle = item.get("shader") or "shader"
            shader_type = item.get("type") or ""
            menu_path = "/" + str(handle).replace("/", "|")
            md.append(
                menu_path,
                {
                    "command": functools.partial(_set_edit_path, plugs, path),
                    "checkBox": path == current,
                    "description": "{} ({})".format(
                        shader_type or handle,
                        ", ".join(item.get("params") or []),
                    ),
                },
            )
        return md


class _ShadingTkWidget(CardNodeWidget):
    """Create (Main / Sampling / Settings) or Edit (Edit Shader / Edit Binding / Settings) plus Sampling."""

    _LABEL_W = 130

    def _build(self) -> None:
        self._node.ensureModePlug()
        self._node.ensureAssignPlugs()
        engine = native_widget(self._node["samplingEngine"])
        try:
            engine.setToolTip(
                "Renderer for this node (Arnold, Cycles, or RenderMan). "
                "Sampling and shader-stage overrides use this engine."
            )
        except Exception:
            pass
        card = self._addCard("ShadingTk", header_widgets=[engine])
        manager = GafferUI.Button("ShadingTk Manager")
        manager.setToolTip(
            "Open ShadingTk Manager. Shaders and textures are separate tabs."
        )
        self._buttonConnections.append(
            manager.clickedSignal().connect(
                Gaffer.WeakMethod(self.__onOpenManager), scoped=True
            )
        )
        card.append(manager)
        mode = native_widget(self._node["mode"])
        try:
            mode.setToolTip(
                "Create assigns new shaders and a Mix. "
                "Edit loads Edit Shader, Edit Binding, and Settings "
                "(plus Sampling) to tweak or reuse existing shaders."
            )
        except Exception:
            pass
        self._addRow(card, "Mode", mode, name="mode")

        self._tabs = GafferUI.TabbedContainer()
        expand_h(self._tabs)
        card.append(self._tabs)

        self._tab_main = GafferUI.TabbedContainer()
        expand_h(self._tab_main)

        globals_form = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8
        )
        self._globals_tab = self._scroll(globals_form)
        self._add_tab(self._tab_main, self._globals_tab, "Globals")
        self._build_globals_tab(globals_form)

        main_form = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8
        )
        self._add_tab(self._tab_main, self._scroll(main_form), "Shader slots")
        self._add_tab(self._tabs, self._tab_main, "Main")

        buttons = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=6
        )
        self._add_slot_button = GafferUI.Button("Add Shader slot")
        self._add_slot_button.setToolTip(
            "Add a shader assignment slot (max {}).".format(MAX_SLOTS)
        )
        self._buttonConnections.append(
            self._add_slot_button.clickedSignal().connect(
                Gaffer.WeakMethod(self.__onAddSlot), scoped=True
            )
        )
        buttons.append(self._add_slot_button)
        main_form.append(buttons)

        self._slot_host = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8
        )
        main_form.append(self._slot_host)

        self._slot_frames: list[GafferUI.Widget] = []
        self._slot_headers: dict[int, GafferUI.Label] = {}
        self._path_rows: dict[tuple[int, int], GafferUI.Widget] = {}
        self._shader_forms: list[GafferUI.ListContainer] = []
        self._shader_tabs: list[GafferUI.Widget] = []
        self.__pending_shader: set[int] = set()
        self.__filled_shader: set[int] = set()
        self._texture_label_connections: list = []
        self._edit_params_key = None
        self._mix_params_key = None
        self._edit_tab = None
        self._assign_tab = None
        self._assign_frames: list[GafferUI.Widget] = []
        self._assign_headers: dict[int, GafferUI.Label] = {}
        self._assign_shader_widgets: dict[int, GafferUI.Widget] = {}
        self._edit_path_widget = None
        self._edit_load_button = None
        self._edit_hint = None
        self._edit_status = None
        self._edit_params = None
        self._global_filled = False

        mix_form = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8
        )
        self._mix_form = mix_form
        self._tab_mix = self._scroll(mix_form)
        self._add_tab(self._tab_main, self._tab_mix, "MixShader")
        self._build_mix_tab(mix_form)

        sampling_form = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8
        )
        self._sampling_tab = self._scroll(sampling_form)
        self._add_tab(self._tabs, self._sampling_tab, "Sampling")
        self._build_sampling_tab(sampling_form)

        settings_form = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8
        )
        self._tab_settings = self._scroll(settings_form)
        self._add_tab(self._tabs, self._tab_settings, "Settings")
        self._build_settings_tab(settings_form)

        self._inputChangedConnection = self._node.plugInputChangedSignal().connect(
            Gaffer.WeakMethod(self.__onInputChanged), scoped=True
        )
        self._parentChangedConnection = self.parentChangedSignal().connect(
            Gaffer.WeakMethod(self.__onParentChanged), scoped=True
        )
        self._syncMode()

    def _scroll(self, child: GafferUI.Widget) -> GafferUI.ScrolledContainer:
        scroll = GafferUI.ScrolledContainer(
            horizontalMode=GafferUI.ScrollMode.Never,
            borderWidth=0,
        )
        scroll.setChild(child)
        expand_h(scroll)
        return scroll

    @staticmethod
    def _add_tab(tabs, child, label: str, index: int | None = None) -> None:
        if index is not None:
            inserter = getattr(tabs, "insert", None)
            if callable(inserter):
                try:
                    inserter(index, child, label)
                    return
                except Exception:
                    pass
        try:
            tabs.append(child, label)
        except TypeError:
            tabs.addChild(child)
            tabs.setLabel(child, label)

    def _is_edit_mode(self) -> bool:
        try:
            return (self._node["mode"].getValue() or MODE_CREATE) == MODE_EDIT
        except Exception:
            return False

    def _ensure_assign_tab(self) -> None:
        if getattr(self, "_assign_tab", None) is not None:
            return
        form = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8
        )
        form.append(
            GafferUI.Label(
                "Assign an existing surface shader onto prims. "
                "The shader is not duplicated — its attribute is copied "
                "from the chosen location onto the PrimPath field."
            )
        )
        buttons = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=6
        )
        self._add_assign_button = GafferUI.Button("Add Shader slot")
        self._add_assign_button.setToolTip(
            "Add an existing-shader assignment slot (max {}).".format(MAX_SLOTS)
        )
        self._buttonConnections.append(
            self._add_assign_button.clickedSignal().connect(
                Gaffer.WeakMethod(self.__onAddAssignSlot), scoped=True
            )
        )
        buttons.append(self._add_assign_button)
        form.append(buttons)
        self._assign_host = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8
        )
        form.append(self._assign_host)
        self._assign_tab = self._scroll(form)
        self._add_tab(
            self._tabs,
            self._assign_tab,
            "Edit Binding",
            index=self._tab_index_after(getattr(self, "_edit_tab", None)),
        )

    def _ensure_edit_tab(self) -> None:
        if getattr(self, "_edit_tab", None) is not None:
            return
        form = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8
        )
        self._edit_tab = self._scroll(form)
        self._add_tab(
            self._tabs,
            self._edit_tab,
            "Edit Shader",
            index=self._tab_index_after(None),
        )
        self._build_edit_tab(form)

    def _tab_index_after(self, after) -> int | None:
        try:
            children = list(self._tabs)
        except Exception:
            children = []
        if after is not None and after in children:
            return children.index(after) + 1
        sampling = getattr(self, "_sampling_tab", None)
        if sampling is not None and sampling in children:
            return children.index(sampling)
        return None

    def _syncMode(self) -> None:
        if not widget_is_alive(self):
            return
        edit = self._is_edit_mode()
        if edit:
            self._ensure_edit_tab()
            self._ensure_assign_tab()
        self._apply_tab_visibility(edit)
        if edit:
            try:
                self._node._ensure_edit_scope()
            except Exception:
                pass
            self._refreshEditShaderList()
            self._syncAssignSlots()
            self._syncEditControls()
            try:
                self._node._try_load_edit_shader()
            except Exception:
                pass
            self._syncSamplingControls()
            return
        self._syncSlots()
        self._syncGlobalTab()
        self._syncMixControls()
        self._bind_texture_label_watchers()
        self._syncSamplingControls()

    def _apply_tab_visibility(self, edit: bool) -> None:
        create_tabs = (getattr(self, "_tab_main", None),)
        for tab in create_tabs:
            self._set_top_tab_visible(tab, not edit)
        self._set_top_tab_visible(getattr(self, "_assign_tab", None), edit)
        self._set_top_tab_visible(getattr(self, "_edit_tab", None), edit)
        self._set_top_tab_visible(getattr(self, "_sampling_tab", None), True)
        self._set_top_tab_visible(getattr(self, "_tab_settings", None), True)
        naming = getattr(self, "_settings_naming", None)
        if naming is not None:
            try:
                naming.setVisible(not edit)
            except Exception:
                pass
        if edit:
            current = getattr(self, "_edit_tab", None) or self._assign_tab
        else:
            current = getattr(self, "_tab_main", None)
        if current is None:
            return
        try:
            self._tabs.setCurrent(current)
        except Exception:
            pass

    def _set_top_tab_visible(self, child, visible: bool) -> None:
        if child is None:
            return
        try:
            self._tabs.setTabVisible(child, visible)
            return
        except Exception:
            pass
        try:
            child.setVisible(visible)
        except Exception:
            pass

    def _add_path_pick_row(self, form, label: str, plug, name: str, handler) -> None:
        widget = GafferUI.StringPlugValueWidget(plug)
        try:
            widget.setToolTip(
                "Scene prim path(s). Type them, or Pick from the Hierarchy / "
                "Viewport. Several prims in one field are separated by spaces. "
                "Select highlights those prims in the scene."
            )
        except Exception:
            pass
        row = self._addRow(form, label, widget, name=name)
        pick = GafferUI.Button("Pick")
        pick.setToolTip(
            "Fill from the current Scene Hierarchy or Viewport selection."
        )
        self._buttonConnections.append(
            pick.clickedSignal().connect(handler, scoped=True)
        )
        row.append(pick)
        select = GafferUI.Button("Select")
        select.setToolTip(
            "Select the prims in this field in the Scene Hierarchy / Viewport."
        )
        self._buttonConnections.append(
            select.clickedSignal().connect(
                functools.partial(self.__onSelectPlug, plug.getName()),
                scoped=True,
            )
        )
        row.append(select)

    def _build_globals_tab(self, form: GafferUI.ListContainer) -> None:
        form.append(
            GafferUI.Label(
                "Scene-wide assignments. These are not shader slots — "
                "slots still override them on their own prims.<br><br>"
                "Global Shader Override: This section allows to quickly "
                "override All Prims (or a quick PrimPath selection) with "
                "a single newly created default Shader."
            )
        )
        assign = native_widget(self._node["globalAssign"])
        try:
            assign.setToolTip(
                "Assign a default StandardSurface named all_shd. "
                "Turn on to create it and open its tab."
            )
        except Exception:
            pass
        self._addRow(form, "Assign all_shd", assign, name="globalAssign")
        self._add_path_pick_row(
            form,
            "PrimPath",
            self._node["globalPath"],
            "globalPath",
            Gaffer.WeakMethod(self.__onPickGlobal),
        )
        form.append(GafferUI.Label("<b>Matte</b>"))
        matte = native_widget(self._node["matteEnabled"])
        try:
            matte.setToolTip("Assign Arnold Matte to the prims below.")
        except Exception:
            pass
        self._addRow(form, "Enable Matte", matte, name="matteEnabled")
        self._add_path_pick_row(
            form,
            "PrimPath",
            self._node["mattePath"],
            "mattePath",
            Gaffer.WeakMethod(self.__onPickMatte),
        )
        form.append(GafferUI.Label("<b>Diagnostic</b>"))
        diag = native_widget(self._node["diagEnabled"])
        try:
            diag.setToolTip(
                "Quick-assign a diagnostic shader. Defaults to everything (...)."
            )
        except Exception:
            pass
        self._addRow(form, "Enable Diagnostic", diag, name="diagEnabled")
        self._addRow(
            form,
            "Shader",
            native_widget(self._node["diagShader"]),
            name="diagShader",
        )
        self._addRow(
            form,
            "Utility mode",
            native_widget(self._node["diagMode"]),
            name="diagMode",
        )
        self._add_path_pick_row(
            form,
            "PrimPath",
            self._node["diagPath"],
            "diagPath",
            Gaffer.WeakMethod(self.__onPickDiag),
        )
        self._syncGlobalControls()

    def _build_settings_tab(self, form: GafferUI.ListContainer) -> None:
        naming = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8
        )
        self._settings_naming = naming
        form.append(naming)
        naming.append(GafferUI.Label("<b>Naming</b>"))
        auto = native_widget(self._node["autoName"])
        try:
            auto.setToolTip(
                "When on, Pick on Shader slots names the shader from the selection. "
                "It does not keep renaming afterwards. You can still type a name."
            )
        except Exception:
            pass
        self._addRow(naming, "Auto-name shaders", auto, name="autoName")
        prefix = native_widget(self._node["namePrefix"])
        try:
            prefix.setToolTip("Optional prefix. Left blank by default.")
        except Exception:
            pass
        self._addRow(naming, "Prefix", prefix, name="namePrefix")
        suffix = native_widget(self._node["nameSuffix"])
        try:
            suffix.setToolTip(
                "Suffix after the object or parent name, e.g. cube_shd. "
                "Duplicate names increment before the suffix (cube2_shd)."
            )
        except Exception:
            pass
        self._addRow(naming, "Suffix", suffix, name="nameSuffix")
        naming.append(
            GafferUI.Label(
                "One prim: {object}_{suffix}. Same parent: {parent}1_{suffix}. "
                "Mixed parents: variousPick1_{suffix}."
            )
        )

    def _build_mix_tab(self, form: GafferUI.ListContainer) -> None:
        form.append(
            GafferUI.Label(
                "Mix slot shaders (and all_shd) into a MixShader or LayerShader, "
                "then assign that mix to a prim path."
            )
        )
        enabled = native_widget(self._node["mixEnabled"])
        self._addRow(form, "Enable Mix", enabled, name="mixEnabled")
        self._addRow(
            form, "Type", native_widget(self._node["mixType"]), name="mixType"
        )
        self._addRow(
            form, "Name", native_widget(self._node["mixName"]), name="mixName"
        )
        self._addRow(
            form,
            "Inputs",
            native_widget(self._node["mixCount"]),
            name="mixCount",
        )
        self._mix_input_rows = {}
        self._mix_input_buttons = {}
        for index in range(1, MAX_MIX_INPUTS + 1):
            button = GafferUI.MenuButton(
                "None",
                menu=GafferUI.Menu(
                    functools.partial(self._mixInputMenuDefinition, index)
                ),
            )
            row = self._addRow(
                form, "Input {}".format(index), button, name=mix_input_plug(index)
            )
            self._mix_input_rows[index] = row
            self._mix_input_buttons[index] = button
        form.append(GafferUI.Label("<b>Assign</b>"))
        form.append(
            GafferUI.Label(
                "Assign this MixShader to any prim path(s). "
                "Pick from the Hierarchy / Viewport, or type paths."
            )
        )
        try:
            Gaffer.Metadata.registerValue(self._node["mixPath"], "label", "PrimPath(s)")
        except Exception:
            pass
        self._add_path_pick_row(
            form,
            "PrimPath(s)",
            self._node["mixPath"],
            "mixPath",
            Gaffer.WeakMethod(self.__onPickMix),
        )

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
        edit = GafferUI.Button("Edit")
        edit.setToolTip("Open this shader in the Shader Manager.")
        self._buttonConnections.append(
            edit.clickedSignal().connect(
                functools.partial(self.__onEditSlot, index), scoped=True
            )
        )
        header.append(edit)
        clear = GafferUI.Button("Clear")
        clear.setToolTip(
            "Reset this slot's shader, name, texture map, and prim paths."
        )
        self._buttonConnections.append(
            clear.clickedSignal().connect(
                functools.partial(self.__onClearSlot, index), scoped=True
            )
        )
        header.append(clear)
        remove = GafferUI.Button("Remove")
        remove.setToolTip("Remove this shader slot.")
        self._buttonConnections.append(
            remove.clickedSignal().connect(
                functools.partial(self.__onRemoveSlot, index), scoped=True
            )
        )
        header.append(remove)
        body.append(header)

        self._addRow(
            body,
            "Shader",
            native_widget(node[shader_type_plug(index)]),
            name="shaderType{}".format(index),
        )
        name_widget = native_widget(node[shader_name_plug(index)])
        try:
            name_widget.setToolTip(
                "Shader node name written into ai:surface (Name). "
                "The Shader menu is the type (Value), e.g. standard_surface."
            )
        except Exception:
            pass
        self._addRow(
            body,
            "Name",
            name_widget,
            name="shaderName{}".format(index),
        )

        frame.setChild(body)
        self._slot_frames.append(frame)
        self._sync_path_rows(index)
        return frame

    def _sync_path_rows(self, index: int) -> None:
        self._ensure_path_row(index, 1)
        extras = [
            key for key in list(self._path_rows) if key[0] == index and key[1] > 1
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
            _release_plug_widgets(row)
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
        try:
            Gaffer.Metadata.registerValue(path, "label", "PrimPath(s)")
            Gaffer.Metadata.registerValue(
                path, "plugValueWidget:type", "GafferUI.StringPlugValueWidget"
            )
        except Exception:
            pass
        widget = GafferUI.StringPlugValueWidget(path)
        try:
            widget.setToolTip(
                "Scene prim path(s) for this slot's PathFilter. "
                "Type them, or Pick from the Hierarchy / Viewport. "
                "Several prims in one field are separated by spaces. "
                "Select highlights those prims in the scene."
            )
        except Exception:
            pass
        body = self._slot_frames[index - 1].getChild()
        row = self._addRow(
            body,
            "PrimPath(s)",
            widget,
            name="path{}_{}".format(index, path_index),
        )
        pick = GafferUI.Button("Pick")
        pick.setToolTip(
            "Fill from the current Scene Hierarchy or Viewport "
            "selection. Multiple selected prims are written next to "
            "each other, separated by spaces."
        )
        self._buttonConnections.append(
            pick.clickedSignal().connect(
                functools.partial(self.__onPickPrims, index, path_index),
                scoped=True,
            )
        )
        row.append(pick)
        select = GafferUI.Button("Select")
        select.setToolTip(
            "Select the prims in this field in the Scene Hierarchy / Viewport."
        )
        self._buttonConnections.append(
            select.clickedSignal().connect(
                functools.partial(self.__onSelectPrims, index, path_index),
                scoped=True,
            )
        )
        row.append(select)
        self._path_rows[(index, path_index)] = row

    def _syncAssignSlots(self) -> None:
        if not widget_is_alive(self):
            return
        if getattr(self, "_assign_host", None) is None:
            return
        try:
            count = int(self._node["assignCount"].getValue())
        except Exception:
            count = 0
        while len(self._assign_frames) < count:
            self._assign_host.append(
                self._build_assign_slot(len(self._assign_frames) + 1)
            )
        for index in range(1, len(self._assign_frames) + 1):
            visible = index <= count
            try:
                self._assign_frames[index - 1].setVisible(visible)
            except Exception:
                pass
            if visible:
                self._set_assign_header(index)
        try:
            self._add_assign_button.setEnabled(count < MAX_SLOTS)
        except Exception:
            pass

    def _build_assign_slot(self, index: int) -> GafferUI.Widget:
        frame = GafferUI.Frame()
        body = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=6
        )
        header = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=6
        )
        title = GafferUI.Label("<b>{}</b>".format(assign_slot_label(index)))
        header.append(title)
        self._assign_headers[index] = title
        header.append(GafferUI.Spacer(imath.V2i(8, 1)), expand=True)
        clear = GafferUI.Button("Clear")
        clear.setToolTip("Clear this assignment's shader and prim path.")
        self._buttonConnections.append(
            clear.clickedSignal().connect(
                functools.partial(self.__onClearAssignSlot, index), scoped=True
            )
        )
        header.append(clear)
        remove = GafferUI.Button("Remove")
        remove.setToolTip("Remove this assignment slot.")
        self._buttonConnections.append(
            remove.clickedSignal().connect(
                functools.partial(self.__onRemoveAssignSlot, index), scoped=True
            )
        )
        header.append(remove)
        body.append(header)
        shader = _ExistingShaderWidget(
            self._node[assign_source_plug(index)],
            require_enabled=None,
            empty_label="Select existing shader…",
        )
        try:
            shader.setToolTip(
                "Existing surface shader on the incoming scene. "
                "Its attribute is copied onto the PrimPath below."
            )
        except Exception:
            pass
        self._addRow(
            body, "Shader", shader, name=assign_source_plug(index)
        )
        self._assign_shader_widgets[index] = shader
        self._add_path_pick_row(
            body,
            "PrimPath",
            self._node[assign_path_plug(index)],
            assign_path_plug(index),
            functools.partial(self.__onPickAssign, index),
        )
        frame.setChild(body)
        self._assign_frames.append(frame)
        return frame

    def _set_assign_header(self, index: int) -> None:
        header = self._assign_headers.get(index)
        if header is None or not widget_is_alive(header):
            return
        label = assign_slot_label(index)
        widget = self._assign_shader_widgets.get(index)
        try:
            if widget is not None:
                for item in widget._cache or []:
                    if item.get("path") == self._node[assign_source_plug(index)].getValue():
                        label = item.get("shader") or label
                        break
        except Exception:
            pass
        try:
            header.setText("<b>{}</b>".format(label))
        except Exception:
            pass

    def _build_edit_tab(self, form: GafferUI.ListContainer) -> None:
        form.append(
            GafferUI.Label(
                "Tweak one existing surface shader. This node creates an "
                "EditScope after the incoming assignment and writes "
                "parameter edits there. Pick a shader — parameters load "
                "in this tab. The shader is not replaced or renamed."
            )
        )
        self._edit_hint = GafferUI.Label("")
        form.append(self._edit_hint)
        self._edit_path_widget = _ExistingShaderWidget(
            self._node["editPath"],
            empty_label="Select shader…",
        )
        self._addRow(
            form,
            "Existing shader",
            self._edit_path_widget,
            name="editPath",
            text_label=True,
        )
        self._edit_load_button = GafferUI.Button("Reload parameters")
        self._edit_load_button.setToolTip(
            "Load or refresh parameter tweaks for the selected shader. "
            "Choosing a shader also does this."
        )
        self._buttonConnections.append(
            self._edit_load_button.clickedSignal().connect(
                Gaffer.WeakMethod(self.__onEditSelected), scoped=True
            )
        )
        form.append(self._edit_load_button)
        self._edit_status = GafferUI.Label("")
        form.append(self._edit_status)
        self._edit_params = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=6
        )
        form.append(self._edit_params)

    def _build_textures_tab(self, form: GafferUI.ListContainer) -> None:
        form.append(
            GafferUI.Label(
                "Textures dropped here are stored on this ShadingTk. "
                "Open the Texture Manager to connect them and edit "
                "texture node attributes in the right pane. RGB shader "
                "attributes have a TXT button: grey with no texture, "
                "green when one is connected, red when that file is missing."
            )
        )
        open_btn = GafferUI.Button("Open Texture Manager")
        open_btn.setToolTip(
            "Open TxLibrary and shader inputs. Select a texture to "
            "edit its attributes in the right pane."
        )
        self._buttonConnections.append(
            open_btn.clickedSignal().connect(
                Gaffer.WeakMethod(self.__onOpenTextureManager), scoped=True
            )
        )
        form.append(open_btn)
        self._textures_status = GafferUI.Label("")
        form.append(self._textures_status)

    def __onOpenManager(self, *unused) -> None:
        from ._managerWindow import acquire_shadingtk_manager

        parent = None
        try:
            parent = self.ancestor(GafferUI.Window)
        except Exception:
            parent = None
        window = acquire_shadingtk_manager(self._node, parent)
        self._shader_window = window
        self._texture_window = window

    def __onOpenShaderManager(self, key=None, *unused) -> None:
        from ._shaderManager import acquire_shader_manager

        if not isinstance(key, str):
            key = None
        parent = None
        try:
            parent = self.ancestor(GafferUI.Window)
        except Exception:
            parent = None
        window = acquire_shader_manager(self._node, parent, key)
        self._shader_window = window

    def __onOpenTextureManager(self, *unused) -> None:
        from ._textureManager import acquire_texture_manager

        parent = None
        try:
            parent = self.ancestor(GafferUI.Window)
        except Exception:
            parent = None
        window = acquire_texture_manager(self._node, parent)
        self._texture_window = window
        try:
            count = len(self._node.visibleLibraryTextures())
            local = len(self._node.libraryTextures())
            self._textures_status.setText(
                "{} visible ({} stored on this node).".format(count, local)
            )
        except Exception:
            pass

    def _build_sampling_tab(self, form: GafferUI.ListContainer) -> None:
        form.append(
            GafferUI.Label(
                "Override renderer shading samples and shader sample "
                "parameters."
            )
        )
        enabled = native_widget(self._node["samplingEnabled"])
        try:
            enabled.setToolTip(
                "Master switch. Options and shader-sample tweaks stay "
                "inactive, and the stage is not scanned, until this is on."
            )
        except Exception:
            pass
        self._addRow(
            form, "Enable Shader sampling overrides", enabled, name="samplingEnabled"
        )

        self._sampling_body = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8
        )
        form.append(self._sampling_body)

        self._sampling_options = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=6
        )
        self._sampling_body.append(self._sampling_options)

        self._sampling_body.append(
            GafferUI.Label("<b>All matching shaders</b>")
        )
        self._sampling_body.append(
            GafferUI.Label(
                "Sets sample-like parameters (samples, sss_samples, …) on "
                "every matching surface and light shader. Uses a '...' "
                "filter and ignoreMissing, so shaders without those "
                "parameters are skipped."
            )
        )
        apply_all = native_widget(self._node["samplingApplyAll"])
        self._addRow(
            self._sampling_body,
            "Apply to all matching shaders",
            apply_all,
            name="samplingApplyAll",
        )
        self._addRow(
            self._sampling_body,
            "Shader samples",
            native_widget(self._node["samplingShaderSamples"]),
            name="samplingShaderSamples",
        )

        self._sampling_body.append(
            GafferUI.Label("<b>Edit one sampling shader</b>")
        )
        self._sampling_path_widget = _ExistingSamplingShaderWidget(
            self._node["samplingEditPath"]
        )
        self._addRow(
            self._sampling_body,
            "Existing sampling shader",
            self._sampling_path_widget,
            name="samplingEditPath",
        )
        self._sampling_load_button = GafferUI.Button(
            "Edit selected sampling shader"
        )
        self._sampling_load_button.setToolTip(
            "Load sample parameters from that shader and tweak only that prim."
        )
        self._buttonConnections.append(
            self._sampling_load_button.clickedSignal().connect(
                Gaffer.WeakMethod(self.__onEditSamplingShader), scoped=True
            )
        )
        self._sampling_body.append(self._sampling_load_button)
        self._sampling_status = GafferUI.Label("")
        self._sampling_body.append(self._sampling_status)
        self._sampling_edit_params = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=6
        )
        self._sampling_body.append(self._sampling_edit_params)

    def __onParentChanged(self, *unused) -> None:
        if self._is_edit_mode():
            self._syncEditControls()

    def _bind_texture_label_watchers(self) -> None:
        """Watch slot / global / mix shaders so (has Textures) updates on disconnect."""
        if not widget_is_alive(self):
            return
        connections = []
        seen: set[int] = set()
        for node in self._texture_label_nodes():
            ident = id(node)
            if ident in seen:
                continue
            seen.add(ident)
            try:
                connections.append(
                    node.plugInputChangedSignal().connect(
                        Gaffer.WeakMethod(self.__onInputChanged), scoped=True
                    )
                )
            except Exception:
                pass
        self._texture_label_connections = connections

    def _texture_label_nodes(self) -> list:
        nodes = []
        try:
            count = int(self._node["slotCount"].getValue())
        except Exception:
            count = 0
        for index in range(1, count + 1):
            try:
                nodes.append(self._node.slotShader(index))
            except Exception:
                pass
        for getter in (self._node.globalShader, self._node.mixShader):
            try:
                nodes.append(getter())
            except Exception:
                pass
        return [node for node in nodes if node is not None]

    def __onInputChanged(self, plug: Gaffer.Plug) -> None:
        name = plug.getName()
        if name == "editScope":
            if self._is_edit_mode():
                self._syncEditControls()
            return
        index = self.__shader_slot_for_plug(plug)
        if index is not None:
            self.__pending_shader.add(index)
            self.__filled_shader.discard(index)
            self.__rebuildShaderLazily()
            return
        try:
            owner = plug.node()
        except Exception:
            owner = None
        try:
            global_shader = self._node.globalShader()
        except Exception:
            global_shader = None
        if (
            owner is not None
            and global_shader is not None
            and global_shader.isSame(owner)
        ):
            if not self._is_edit_mode():
                self._global_filled = False
                self._fill_global_shader_tab()
            return
        try:
            mix = self._node.mixShader()
        except Exception:
            mix = None
        if owner is not None and mix is not None and mix.isSame(owner):
            if not self._is_edit_mode():
                self._mix_params_key = None
                self._refresh_shader_manager()
            return
        if name != "in":
            return
        self.__onSceneInputChangedLazily()

    def __shader_slot_for_plug(self, plug: Gaffer.Plug) -> int | None:
        try:
            owner = plug.node()
        except Exception:
            return None
        if owner is None:
            return None
        try:
            count = int(self._node["slotCount"].getValue())
        except Exception:
            count = 0
        for index in range(1, count + 1):
            shader = None
            try:
                shader = self._node.slotShader(index)
            except Exception:
                shader = None
            if shader is None:
                continue
            try:
                if shader.isSame(owner):
                    return index
            except Exception:
                continue
        return None

    @GafferUI.LazyMethod(deferUntilVisible=False)
    def __onSceneInputChangedLazily(self) -> None:
        if not widget_is_alive(self):
            return
        if self._is_edit_mode():
            self._refreshEditShaderList()
            self._syncAssignSlots()
            self._syncEditControls()
        self._syncSamplingControls()

    def _refreshEditShaderList(self) -> None:
        widgets = [getattr(self, "_edit_path_widget", None)]
        widgets.extend(self._assign_shader_widgets.values())
        connected = has_scene_input(self._node)
        for widget in widgets:
            if widget is None:
                continue
            try:
                widget.invalidateCache()
            except Exception:
                continue
            if not connected:
                continue
            try:
                widget.scanNow()
            except Exception:
                pass
        for index in self._assign_headers:
            self._set_assign_header(index)

    def _onPlugDirtied(self, plug: Gaffer.Plug) -> None:
        name = plug.getName()
        if name == "mode":
            self.__syncModeLazily()
            return
        if name == "assignCount" or name.startswith("assignSource") or name.startswith("assignPath"):
            if self._is_edit_mode():
                self._syncAssignSlots()
            return
        if name == "slotCount":
            if self._is_edit_mode():
                return
            self.__syncSlotsLazily()
            self.__pending_shader.update(range(1, MAX_SLOTS + 1))
            self.__rebuildShaderLazily()
        elif name.startswith("pathCount"):
            if not self._is_edit_mode():
                self.__syncSlotsLazily()
        elif name.startswith("shaderName"):
            digits = "".join(ch for ch in name if ch.isdigit())
            if digits:
                self._set_tab_label(int(digits))
        elif name.startswith("shaderType") or name.startswith("textureType") or name.startswith("displacementType"):
            if self._is_edit_mode():
                return
            digits = "".join(ch for ch in name if ch.isdigit())
            if digits:
                index = int(digits)
                self.__pending_shader.add(index)
                self.__filled_shader.discard(index)
            self.__rebuildShaderLazily()
        elif name in ("editEnabled", "editPath", "editLoaded"):
            if not self._is_edit_mode():
                return
            loaded = False
            try:
                loaded = bool(self._node["editLoaded"].getValue())
            except Exception:
                loaded = False
            if name in ("editPath", "editLoaded") and not loaded:
                self._clear_edit_params()
            self._syncEditControls()
        elif name in (
            "samplingEnabled",
            "samplingEngine",
            "samplingApplyAll",
            "samplingEditPath",
            "samplingEditLoaded",
        ):
            if name == "samplingEnabled":
                try:
                    self._sampling_path_widget.invalidateCache()
                except Exception:
                    pass
            self._syncSamplingControls()
            if name == "samplingEngine" and self._node["samplingEnabled"].getValue():
                self._fill_sampling_options()
            if name in ("samplingEditLoaded", "samplingEditPath") and self._node[
                "samplingEditLoaded"
            ].getValue():
                self._fill_sampling_edit()
        elif name in (
            "globalAssign",
            "globalPath",
            "matteEnabled",
            "mattePath",
            "diagEnabled",
            "diagShader",
            "diagMode",
            "diagPath",
        ):
            if name == "globalAssign":
                self._global_filled = False
            self._syncGlobalTab()
        elif name in ("mixEnabled", "mixType", "mixCount", "mixName", "mixPath") or name.startswith(
            "mixInput"
        ):
            self._syncMixControls()

    @GafferUI.LazyMethod(deferUntilVisible=False)
    def __syncModeLazily(self) -> None:
        if not widget_is_alive(self):
            return
        self._syncMode()

    @GafferUI.LazyMethod(deferUntilVisible=False)
    def __syncSlotsLazily(self) -> None:
        if not widget_is_alive(self):
            return
        if self._is_edit_mode():
            return
        self._syncSlots()

    @GafferUI.LazyMethod(deferUntilVisible=False)
    def __rebuildShaderLazily(self) -> None:
        if not widget_is_alive(self):
            return
        if self._is_edit_mode():
            return
        pending = set(self.__pending_shader)
        self.__pending_shader.clear()
        for index in sorted(pending):
            self._fill_shader_tab(index)

    def _syncSlots(self) -> None:
        if not widget_is_alive(self):
            return
        if self._is_edit_mode():
            return
        count = int(self._node["slotCount"].getValue())
        while len(self._slot_frames) < count:
            self._ensure_slot_ui(len(self._slot_frames) + 1)
        for index in range(1, len(self._slot_frames) + 1):
            visible = index <= count
            if index <= len(self._slot_frames):
                self._slot_frames[index - 1].setVisible(visible)
            self._set_tab_visible(index, visible)
            if not visible:
                continue
            self._sync_path_rows(index)
            if index not in self.__filled_shader:
                self._fill_shader_tab(index)
        self._add_slot_button.setEnabled(count < MAX_SLOTS)
        for index in range(1, len(self._slot_frames) + 1):
            self._set_tab_label(index)
        self._syncMixInputLabels()
        self._bind_texture_label_watchers()

    def _syncGlobalControls(self) -> None:
        if not widget_is_alive(self):
            return
        assign = False
        matte = False
        diag = False
        try:
            assign = bool(self._node["globalAssign"].getValue())
            matte = bool(self._node["matteEnabled"].getValue())
            diag = bool(self._node["diagEnabled"].getValue())
        except Exception:
            pass
        self._setRowEnabled("globalPath", assign)
        self._setRowEnabled("mattePath", matte)
        self._setRowEnabled("diagShader", diag)
        self._setRowEnabled("diagPath", diag)
        utility = False
        try:
            utility = (self._node["diagShader"].getValue() or "") == "utility"
        except Exception:
            utility = False
        self._setRowEnabled("diagMode", diag and utility)
        self._setRowVisible("diagMode", True)

    def _syncGlobalTab(self) -> None:
        if not widget_is_alive(self):
            return
        if self._is_edit_mode():
            return
        visible = False
        try:
            visible = bool(self._node["globalAssign"].getValue())
        except Exception:
            visible = False
        if visible:
            self._refresh_shader_manager()
        self._syncGlobalControls()
        self._bind_texture_label_watchers()

    def _fill_global_shader_tab(self) -> None:
        self._refresh_shader_manager()
        self._global_filled = True

    def _syncMixControls(self) -> None:
        if not widget_is_alive(self):
            return
        if self._is_edit_mode():
            return
        enabled = False
        mix_type = MIX_SHADER
        count = 2
        try:
            enabled = bool(self._node["mixEnabled"].getValue())
            mix_type = self._node["mixType"].getValue() or MIX_SHADER
            count = int(self._node["mixCount"].getValue())
        except Exception:
            pass
        if mix_type == MIX_SHADER:
            count = min(count, 2)
        self._setRowEnabled("mixType", enabled)
        self._setRowEnabled("mixName", enabled)
        self._setRowEnabled("mixCount", enabled and mix_type == LAYER_SHADER)
        self._setRowEnabled("mixPath", enabled)
        for index in range(1, MAX_MIX_INPUTS + 1):
            row = getattr(self, "_mix_input_rows", {}).get(index)
            if row is None or not widget_is_alive(row):
                continue
            row.setVisible(enabled and index <= count)
            try:
                row.setEnabled(enabled)
            except Exception:
                pass
        self._syncMixInputLabels()
        self.__fillMixParamsLazily()
        self._bind_texture_label_watchers()

    @GafferUI.LazyMethod(deferUntilVisible=False)
    def __fillMixParamsLazily(self) -> None:
        if not widget_is_alive(self):
            return
        if self._is_edit_mode():
            return
        self._fill_mix_params()

    def _mix_input_label(self, index: int) -> str:
        key = ""
        try:
            key = (self._node[mix_input_plug(index)].getValue() or "").strip()
        except Exception:
            key = ""
        if not key:
            return "None"
        if key in ("all", ALL_SHADER_NAME, "global"):
            return ALL_SHADER_NAME
        if key.isdigit():
            slot = int(key)
            try:
                return self._node[shader_name_plug(slot)].getValue() or slot_label(slot)
            except Exception:
                return slot_label(slot)
        return key

    def _syncMixInputLabels(self) -> None:
        for index, button in getattr(self, "_mix_input_buttons", {}).items():
            if not widget_is_alive(button):
                continue
            try:
                button.setText(self._mix_input_label(index))
            except Exception:
                pass

    def _mixInputMenuDefinition(self, index: int, *unused) -> IECore.MenuDefinition:
        md = IECore.MenuDefinition()
        md.append(
            "/None",
            {
                "command": functools.partial(self.__onSetMixInput, index, ""),
                "checkBox": self._mix_input_label(index) == "None",
            },
        )
        try:
            if self._node["globalAssign"].getValue():
                md.append(
                    "/" + ALL_SHADER_NAME,
                    {
                        "command": functools.partial(
                            self.__onSetMixInput, index, "all"
                        ),
                    },
                )
        except Exception:
            pass
        try:
            count = int(self._node["slotCount"].getValue())
        except Exception:
            count = 0
        for slot in range(1, count + 1):
            label = self._slot_tab_name(slot)
            md.append(
                "/" + label,
                {
                    "command": functools.partial(
                        self.__onSetMixInput, index, str(slot)
                    ),
                },
            )
        return md

    def _fill_mix_params(self) -> None:
        form = getattr(self, "_mix_params", None)
        if form is None or not widget_is_alive(form) or self._is_edit_mode():
            return
        enabled = False
        mix_type = MIX_SHADER
        shader = None
        try:
            enabled = bool(self._node["mixEnabled"].getValue())
            mix_type = self._node["mixType"].getValue() or MIX_SHADER
            shader = self._node.mixShader()
        except Exception:
            pass
        try:
            form.setVisible(enabled)
        except Exception:
            pass
        if not enabled:
            return
        key = (mix_type, shader)
        if key == getattr(self, "_mix_params_key", None) and list(form):
            return
        _clear_container(form)
        if shader is None:
            self._mix_params_key = key
            return
        form.append(GafferUI.Label("Mix"))
        for plug in self._node.mixParameterPlugs():
            name = plug.getName()
            if name.startswith("input") or name.startswith("shader") or name.startswith("enable"):
                continue
            self._add_shader_param_row(form, plug)
        self._mix_params_key = key

    def _ensure_slot_ui(self, index: int) -> None:
        self._slot_host.append(self._build_slot(index))

    def _set_tab_visible(self, index: int, visible: bool) -> None:
        if index < 1 or index > len(self._shader_tabs):
            return
        tab = self._shader_tabs[index - 1]
        host = getattr(self, "_shader_tabs_host", None)
        if host is None:
            return
        try:
            host.setTabVisible(tab, visible)
            return
        except Exception:
            pass
        try:
            tab.setVisible(visible)
        except Exception:
            pass

    def _syncEditControls(self) -> None:
        if not widget_is_alive(self):
            return
        if not self._is_edit_mode() or getattr(self, "_edit_path_widget", None) is None:
            return
        connected = has_scene_input(self._node)
        loaded = False
        path = ""
        try:
            loaded = bool(self._node["editLoaded"].getValue())
            path = (self._node["editPath"].getValue() or "").strip()
        except Exception:
            pass
        self._setRowEnabled("editPath", True)
        try:
            self._edit_load_button.setEnabled(bool(path and connected))
        except Exception:
            pass
        if not connected:
            hint = "Connect a scene to in, then pick a shader."
        elif not path:
            hint = "Pick an existing shader. Parameters load in this tab."
        elif loaded:
            hint = "Edits are written into this node's ShaderEdits scope. Enable a tweak to change that parameter."
        else:
            hint = "Reload parameters if the list is empty after picking a shader."
        try:
            self._edit_hint.setText(hint)
        except Exception:
            pass
        try:
            self._edit_params.setVisible(loaded)
        except Exception:
            pass
        if loaded:
            self.__fillEditParamsLazily()

    @GafferUI.LazyMethod(deferUntilVisible=False)
    def __fillEditParamsLazily(self) -> None:
        if not widget_is_alive(self):
            return
        self._fill_edit_params()

    def _clear_edit_params(self) -> None:
        form = getattr(self, "_edit_params", None)
        if form is None:
            self._edit_params_key = None
            return
        _clear_container(form)
        self._edit_params_key = None
        try:
            form.setVisible(False)
        except Exception:
            pass

    def _fill_edit_params(self) -> None:
        if not widget_is_alive(self):
            return
        if getattr(self, "_edit_params", None) is None or not self._is_edit_mode():
            return
        if not self._node["editLoaded"].getValue():
            self._clear_edit_params()
            return
        path = ""
        try:
            path = (self._node["editPath"].getValue() or "").strip()
        except Exception:
            path = ""
        key = (path, True)
        if key == getattr(self, "_edit_params_key", None) and list(self._edit_params):
            return
        form = self._edit_params
        _clear_container(form)
        title = "Material"
        try:
            for item in self._node.existingShaders():
                if item.get("path") == path:
                    title = item.get("shader") or title
                    break
        except Exception:
            pass
        try:
            form.setVisible(True)
        except Exception:
            pass
        form.append(GafferUI.Label("<b>{}</b>".format(title)))
        for tweak in self._node.editParameterPlugs():
            value = tweak["value"] if "value" in tweak else tweak
            widget = _plug_widget(value)
            if widget is None:
                continue
            if "enabled" in tweak:
                row = GafferUI.ListContainer(
                    GafferUI.ListContainer.Orientation.Horizontal, spacing=6
                )
                try:
                    row.append(
                        GafferUI.BoolPlugValueWidget(
                            tweak["enabled"],
                            displayMode=GafferUI.BoolWidget.DisplayMode.Switch,
                        )
                    )
                except Exception:
                    row.append(native_widget(tweak["enabled"]))
                row.append(widget, expand=True)
                widget = row
            row = self._addRow(form, _tweak_label(tweak), widget, text_label=True)
            self._attach_txt_button(row, value)
        self._edit_params_key = key

    def _syncSamplingControls(self) -> None:
        if not widget_is_alive(self):
            return
        enabled = False
        apply_all = False
        loaded = False
        try:
            enabled = bool(self._node["samplingEnabled"].getValue())
            apply_all = bool(self._node["samplingApplyAll"].getValue())
            loaded = bool(self._node["samplingEditLoaded"].getValue())
        except Exception:
            pass
        connected = has_scene_input(self._node)
        try:
            self._sampling_body.setVisible(enabled)
        except Exception:
            pass
        self._setRowEnabled("samplingApplyAll", enabled)
        self._setRowEnabled("samplingShaderSamples", enabled and apply_all)
        self._setRowEnabled("samplingEditPath", enabled and connected)
        try:
            self._sampling_load_button.setEnabled(enabled and connected)
        except Exception:
            pass
        if enabled:
            self._fill_sampling_options()
            if loaded:
                self._fill_sampling_edit()
            else:
                try:
                    self._sampling_edit_params.setVisible(False)
                except Exception:
                    pass
        else:
            try:
                self._sampling_options.setVisible(False)
                self._sampling_edit_params.setVisible(False)
            except Exception:
                pass

    def _fill_sampling_options(self) -> None:
        if not widget_is_alive(self):
            return
        form = self._sampling_options
        engine = ""
        try:
            engine = self._node["samplingEngine"].getValue() or ""
        except Exception:
            engine = ""
        try:
            form.setVisible(True)
        except Exception:
            pass
        if getattr(self, "_sampling_options_engine", None) == engine and len(list(form)):
            return
        self._sampling_options_engine = engine
        _clear_container(form)
        import_engine_ui(engine)
        options_node = self._node.samplingOptionsNode()
        if options_node is None or "options" not in options_node:
            form.append(
                GafferUI.Label(
                    "{} options are not available in this Gaffer.".format(
                        engine_label(engine)
                    )
                )
            )
            return
        form.append(
            GafferUI.Label(
                "<b>{} shading samples</b>".format(engine_label(engine))
            )
        )
        parent = options_node["options"]
        for key in SAMPLE_OPTION_KEYS.get(engine, ()):
            if key not in parent:
                continue
            widget = _plug_widget(parent[key])
            if widget is None:
                continue
            label = Gaffer.Metadata.value(parent[key], "label") or key.split(":")[-1]
            self._addRow(form, str(label), widget)

    def _fill_sampling_edit(self) -> None:
        if not widget_is_alive(self):
            return
        form = self._sampling_edit_params
        try:
            form.setVisible(True)
        except Exception:
            pass
        _clear_container(form)
        if not self._node["samplingEditLoaded"].getValue():
            return
        tweaks = self._node.samplingEditTweaks()
        if tweaks is None or "tweaks" not in tweaks:
            return
        form.append(GafferUI.Label("<b>Sample parameters</b>"))
        for tweak in tweaks["tweaks"].children():
            widget = None
            if "value" in tweak:
                widget = _plug_widget(tweak["value"])
            if widget is None:
                continue
            self._addRow(form, _tweak_label(tweak), widget, text_label=True)

    def __onEditSamplingShader(self, *unused) -> None:
        path = ""
        try:
            path = (self._node["samplingEditPath"].getValue() or "").strip()
        except Exception:
            path = ""
        if not path:
            try:
                self._sampling_status.setText("Select a sampling shader first.")
            except Exception:
                pass
            return
        script = self._node.scriptNode()
        try:
            with Gaffer.UndoScope(script):
                applied = self._node.loadSamplingShader(path)
        except Exception as exc:
            try:
                self._sampling_status.setText(str(exc))
            except Exception:
                pass
            return
        self._fill_sampling_edit()
        try:
            self._sampling_status.setText(
                "Loaded {} sample parameter{}.".format(
                    applied, "" if applied == 1 else "s"
                )
            )
        except Exception:
            pass

    def __onEditSlot(self, index: int, *unused) -> None:
        self.__onOpenShaderManager("slot:{}".format(index))

    def _focus_slot_shader(self, index: int) -> None:
        """Open Shader Manager on this Create slot."""
        self.__onOpenShaderManager("slot:{}".format(index))

    def __set_current_tab(self, tabs, child) -> None:
        if tabs is None or child is None or not widget_is_alive(child):
            return
        try:
            tabs.setCurrent(child)
            return
        except Exception:
            pass
        try:
            tabs._qtWidget().setCurrentWidget(child._qtWidget())
        except Exception:
            pass

    def _slot_tab_name(self, index: int) -> str:
        try:
            name = (self._node[shader_name_plug(index)].getValue() or "").strip()
        except Exception:
            name = ""
        return name or slot_label(index)

    def _set_tab_label(self, index: int) -> None:
        if not widget_is_alive(self):
            return
        label = self._slot_tab_name(index)
        header = self._slot_headers.get(index)
        if header is not None and widget_is_alive(header):
            try:
                header.setText("<b>{}</b>".format(label))
            except Exception:
                pass

    def _rebuild_all_shader_tabs(self) -> None:
        if not widget_is_alive(self):
            return
        for index in range(1, len(self._shader_forms) + 1):
            self._fill_shader_tab(index)

    def _refresh_shader_manager(self) -> None:
        window = getattr(self, "_shader_window", None)
        if window is None or not widget_is_alive(window):
            return
        try:
            window.refresh()
        except Exception:
            pass

    def _fill_shader_tab(self, index: int) -> None:
        self._set_tab_label(index)
        self._refresh_shader_manager()
        self.__filled_shader.add(index)

    def _add_shader_param_row(self, form: GafferUI.ListContainer, plug) -> None:
        widget = _plug_widget(plug)
        if widget is None:
            return
        label, marked = _shader_param_label(self._node, plug)
        row = self._addRow(
            form,
            label,
            widget,
            text_label=marked,
        )
        self._attach_txt_button(row, plug)

    def _attach_txt_button(self, row, plug) -> None:
        try:
            accepts = self._node.plugAcceptsRgbTexture(plug)
        except Exception:
            accepts = False
        if not accepts or row is None:
            return
        button = GafferUI.Button("TXT")
        try:
            button._qtWidget().setFixedWidth(46)
        except Exception:
            pass
        self._style_txt_button(button, plug)
        self._buttonConnections.append(
            button.clickedSignal().connect(
                functools.partial(Gaffer.WeakMethod(self.__onTxt), plug),
                scoped=True,
            )
        )
        row.append(button)
        buttons = getattr(self, "_txt_buttons", None)
        if buttons is None:
            buttons = []
            self._txt_buttons = buttons
        buttons.append((button, plug))
        source = None
        try:
            source = self._node.textureSourceNode(plug)
        except Exception:
            source = None
        if source is None:
            return
        watched = getattr(self, "_txt_watched", None)
        if watched is None:
            watched = set()
            self._txt_watched = watched
        if id(source) in watched:
            return
        watched.add(id(source))
        try:
            self._buttonConnections.append(
                source.plugSetSignal().connect(
                    Gaffer.WeakMethod(self.__onTexturePlugSet), scoped=True
                )
            )
        except Exception:
            pass

    def _style_txt_button(self, button, plug) -> None:
        state = "none"
        path = ""
        node_name = ""
        try:
            state = self._node.texturePlugState(plug)
        except Exception:
            state = "none"
        source = None
        try:
            source = self._node.textureSourceNode(plug)
        except Exception:
            source = None
        if source is not None:
            try:
                node_name = source.getName() or ""
            except Exception:
                node_name = ""
            try:
                if "parameters" in source and "filename" in source["parameters"]:
                    path = source["parameters"]["filename"].getValue() or ""
            except Exception:
                path = ""
        colors = {
            "none": ("#5e5e5e", "#e6e6e6"),
            "connected": ("#2e7d32", "#ffffff"),
            "missing": ("#c62828", "#ffffff"),
        }
        background, foreground = colors.get(state, colors["none"])
        try:
            button._qtWidget().setStyleSheet(
                "QPushButton {{ background-color: {}; color: {}; "
                "border: 1px solid #222222; border-radius: 2px; "
                "font-weight: bold; padding: 1px 4px; }}".format(
                    background, foreground
                )
            )
        except Exception:
            pass
        if state == "none":
            tip = "Choose a texture or a file texture for this colour."
        elif state == "missing":
            tip = "Texture file is missing ({}). Opens the texture node.".format(
                path or node_name or "empty path"
            )
        else:
            tip = "Opens {}.".format(node_name or "the texture node")
            if path:
                tip = "Opens {} ({})".format(node_name or "texture", path)
        try:
            button.setToolTip(tip)
        except Exception:
            pass

    def __onTexturePlugSet(self, plug, *unused) -> None:
        if plug is None or plug.getName() != "filename":
            return
        self.__refreshTxtButtons()

    def __refreshTxtButtons(self) -> None:
        live = []
        for button, plug in getattr(self, "_txt_buttons", []) or []:
            if not widget_is_alive(button):
                continue
            live.append((button, plug))
            self._style_txt_button(button, plug)
        self._txt_buttons = live

    def __onTxt(self, plug, *unused) -> None:
        state = "none"
        try:
            state = self._node.texturePlugState(plug)
        except Exception:
            state = "none"
        if state == "none":
            self._choose_plug_texture(plug)
        else:
            source = None
            try:
                source = self._node.textureSourceNode(plug)
            except Exception:
                source = None
            self._open_texture_panel(source)
        self.__refreshTxtButtons()

    def _choose_plug_texture(self, plug) -> None:
        from Qt.QtWidgets import QComboBox, QDialog, QVBoxLayout

        dialog = QDialog(self._qtWidget().window())
        dialog.setWindowTitle("Texture")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)
        combo = QComboBox()
        combo.addItem("None", "")
        combo.addItem("File texture…", "__file__")
        try:
            choices = list(self._node.texturePlugChoices())
        except Exception:
            choices = []
        for value, label in choices:
            combo.addItem(label, value)
        layout.addWidget(combo)
        picked = {"value": None}

        def _activate(index) -> None:
            picked["value"] = combo.itemData(index)
            dialog.accept()

        combo.activated.connect(_activate)
        dialog.setFixedWidth(280)
        dialog.adjustSize()
        runner = getattr(dialog, "exec", None) or dialog.exec_
        if runner() != QDialog.Accepted:
            return
        value = picked["value"]
        if value is None:
            value = ""
        value = str(value)
        script = self._node.scriptNode()
        node = None
        if value == "__file__":
            from Qt.QtWidgets import QFileDialog

            chosen, _filter = QFileDialog.getOpenFileName(
                dialog,
                "File texture",
                "",
                "Images (*.exr *.tx *.tif *.tiff *.png *.jpg *.jpeg *.hdr *.tga);;All (*)",
            )
            if not chosen:
                return
            with Gaffer.UndoScope(script):
                try:
                    name = self._node.ingestLibraryTexture(chosen)
                except Exception as exc:
                    IECore.msg(IECore.Msg.Level.Warning, "ShadingTk", str(exc))
                    return
                node = self._node.assignPlugTexture(
                    plug, "lib:" + name
                )
        else:
            with Gaffer.UndoScope(script):
                node = self._node.assignPlugTexture(plug, value)
        if node is None:
            return
        try:
            file_texture = self._node.textureNodeHasFile(node)
        except Exception:
            file_texture = False
        if file_texture:
            self._open_texture_panel(node)

    def _open_texture_panel(self, node) -> None:
        if node is None:
            return
        in_box = False
        try:
            in_box = self._node._node_in_textures_box(node)
        except Exception:
            in_box = False
        if in_box:
            self.__onOpenTextureManager()
            window = getattr(self, "_texture_window", None)
            if window is not None and widget_is_alive(window):
                try:
                    window.showTexture(node.getName())
                except Exception:
                    pass
            return
        try:
            GafferUI.NodeEditor.acquire(node, floating=True)
        except Exception:
            pass

    def __onAddSlot(self, *unused) -> None:
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node.addSlot()

    def __onAddAssignSlot(self, *unused) -> None:
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node.addAssignSlot()
        self._syncAssignSlots()

    def __onClearAssignSlot(self, index: int, *unused) -> None:
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node.clearAssignSlot(index)
        self._set_assign_header(index)

    def __onRemoveAssignSlot(self, index: int, *unused) -> None:
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node.removeAssignSlotAt(index)
        self._syncAssignSlots()

    def __onPickAssign(self, index: int, *unused) -> None:
        self.__pick_into(assign_path_plug(index))

    def __onRemoveSlot(self, index: int, *unused) -> None:
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node.removeSlotAt(index)

    def __onEditSelected(self, *unused) -> None:
        path = ""
        try:
            path = (self._node["editPath"].getValue() or "").strip()
        except Exception:
            path = ""
        if not path:
            try:
                self._edit_status.setText("Select a shader first.")
            except Exception:
                pass
            return
        script = self._node.scriptNode()
        try:
            with Gaffer.UndoScope(script):
                applied = self._node.loadEditShader(path)
        except Exception as exc:
            try:
                self._edit_status.setText(str(exc))
            except Exception:
                pass
            return
        self._fill_edit_params()
        try:
            self._edit_status.setText(
                "Loaded {} parameter{}.".format(
                    applied, "" if applied == 1 else "s"
                )
            )
        except Exception:
            pass

    def __onPickPrims(self, index: int, path_index: int, *unused) -> None:
        script = self._node.scriptNode()
        paths = _selected_prim_paths(script)
        if not paths:
            IECore.msg(
                IECore.Msg.Level.Warning,
                "ShadingTk",
                "Nothing selected in the Scene Hierarchy or Viewport.",
            )
            return
        with Gaffer.UndoScope(script):
            self._node[path_plug(index, path_index)].setValue(" ".join(paths))
            self._node.autoNameFromPick(index, paths)
        self._set_tab_label(index)

    def __onSelectPrims(self, index: int, path_index: int, *unused) -> None:
        self.__select_plug(path_plug(index, path_index))

    def __onSelectPlug(self, plug_name: str, *unused) -> None:
        self.__select_plug(plug_name)

    def __select_plug(self, plug_name: str) -> None:
        script = self._node.scriptNode()
        try:
            text = self._node[plug_name].getValue()
        except Exception:
            text = ""
        paths = parse_prim_paths(text)
        if not paths:
            IECore.msg(
                IECore.Msg.Level.Warning,
                "ShadingTk",
                "No prim paths in the field to select.",
            )
            return
        if not _set_selected_prim_paths(script, paths):
            IECore.msg(
                IECore.Msg.Level.Warning,
                "ShadingTk",
                "Could not select prims in the Scene Hierarchy or Viewport.",
            )

    def _presetMenuDefinition(self, index: int, *unused) -> IECore.MenuDefinition:
        md = IECore.MenuDefinition()
        slot = index
        label = slot_label(slot)
        presets = []
        try:
            presets = list(self._node.listPresets())
        except Exception:
            presets = []
        if not presets:
            md.append("/No presets found", {"active": False})
        else:
            current_type = ""
            try:
                current_type = self._node[shader_type_plug(slot)].getValue()
            except Exception:
                current_type = ""
            matching = [p for p in presets if p.get("shader") == current_type]
            other = [p for p in presets if p.get("shader") != current_type]
            for preset in matching:
                md.append(
                    "/" + preset["name"],
                    {
                        "command": functools.partial(
                            self.__onApplyPreset,
                            slot,
                            preset["name"],
                            preset.get("shader"),
                        ),
                        "description": "{} — {} ({})".format(
                            preset["name"], preset.get("shader"), preset.get("source")
                        ),
                    },
                )
            if matching and other:
                md.append("/__divA", {"divider": True})
            for preset in other:
                prefix = shader_file_prefix(str(preset.get("shader") or ""))
                md.append(
                    "/Other/{0}/{1}".format(prefix, preset["name"]),
                    {
                        "command": functools.partial(
                            self.__onApplyPreset,
                            slot,
                            preset["name"],
                            preset.get("shader"),
                        ),
                        "description": "Loads {0} on {1}".format(
                            preset.get("shader"), label
                        ),
                    },
                )
        md.append("/__divOps", {"divider": True})
        md.append(
            "/Save Preset…",
            {
                "command": functools.partial(self.__onSavePreset, slot),
                "description": "Write {0} attributes to a YAML file.".format(label),
            },
        )
        md.append(
            "/Reset Shader",
            {
                "command": functools.partial(self.__onResetShader, slot),
                "description": "Reload {0} with the shader's default attributes.".format(
                    label
                ),
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

    def __onApplyPreset(self, index: int, name: str, shader=None, *unused) -> None:
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            applied = self._node.applyPreset(index, name, shader)
        self._fill_shader_tab(index)
        IECore.msg(
            IECore.Msg.Level.Info if applied else IECore.Msg.Level.Warning,
            "ShadingTk",
            "Applied '{}' to {} ({} values).".format(
                name, slot_label(index), applied
            )
            if applied
            else "Could not apply preset '{}'.".format(name),
        )

    def __onSavePreset(self, index: int, *unused) -> None:
        parent = None
        try:
            parent = self.ancestor(GafferUI.Window)
        except Exception:
            parent = None
        try:
            dialogue = _SavePresetDialogue(self._node, index)
            name = dialogue.waitForName(parentWindow=parent)
        except Exception as exc:
            IECore.msg(
                IECore.Msg.Level.Error,
                "ShadingTk",
                "Could not open Save Preset ({})".format(exc),
            )
            return
        name = (name or "").strip()
        if not name:
            return
        try:
            path = self._node.savePreset(index, name)
        except Exception as exc:
            self.__presetError("Could not save preset.\n{}".format(exc), parent)
            return
        IECore.msg(
            IECore.Msg.Level.Info,
            "ShadingTk",
            "Saved preset '{}' to {}.".format(name, path),
        )

    def __presetError(self, message: str, parent) -> None:
        try:
            GafferUI.ErrorDialogue.displayError(
                "Save Preset", message, parentWindow=parent
            )
            return
        except Exception:
            pass
        IECore.msg(IECore.Msg.Level.Error, "ShadingTk", message)

    def __onResetShader(self, index: int, *unused) -> None:
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node.resetSlotShader(index)
        self._fill_shader_tab(index)

    def __onChoosePresetFolder(self, *unused) -> None:
        from sdvTkGaffer.ShadingTk._presets import dialog_start_dir, is_gaffer_bin_dir

        chosen = _pick_directory(self, dialog_start_dir(self._node))
        if not chosen or is_gaffer_bin_dir(chosen):
            return
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node["presetFolder"].setValue(chosen)

    def __onOpenPresetFolder(self, *unused) -> None:
        from sdvTkGaffer.ShadingTk._presets import is_gaffer_bin_dir, save_dir

        path = save_dir(self._node)
        if not path or is_gaffer_bin_dir(path):
            return
        if not os.path.isdir(path):
            return
        _open_directory(path)

    def __onClearPresetFolder(self, *unused) -> None:
        from sdvTkGaffer.ShadingTk._presets import discovered_presets_dir

        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node["presetFolder"].setValue(discovered_presets_dir())

    def __onPickGlobal(self, *unused) -> None:
        self.__pick_into("globalPath")

    def __onPickMatte(self, *unused) -> None:
        self.__pick_into("mattePath")

    def __onPickDiag(self, *unused) -> None:
        self.__pick_into("diagPath")

    def __onPickMix(self, *unused) -> None:
        self.__pick_into("mixPath")

    def __pick_into(self, plug_name: str) -> None:
        script = self._node.scriptNode()
        paths = _selected_prim_paths(script)
        if not paths:
            IECore.msg(
                IECore.Msg.Level.Warning,
                "ShadingTk",
                "Nothing selected in the Scene Hierarchy or Viewport.",
            )
            return
        with Gaffer.UndoScope(script):
            self._node[plug_name].setValue(" ".join(paths))

    def __onSetMixInput(self, index: int, value: str, *unused) -> None:
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node[mix_input_plug(index)].setValue(value)

    def __onClearSlot(self, index: int, *unused) -> None:
        script = self._node.scriptNode()
        with Gaffer.UndoScope(script):
            self._node.clearSlot(index)
        self._fill_shader_tab(index)


def _shadingTkWidgetCreator(node: Gaffer.Node) -> _ShadingTkWidget:
    return _ShadingTkWidget(node)


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
        "description": "Incoming scene with slot shaders assigned "
        "(passthrough of in when the node is disabled).",
        "nodule:type": "GafferUI::StandardNodule",
        "noduleLayout:section": "bottom",
        "noduleLayout:index": 0,
    },
    "enabled": {
        "description": "When off, the incoming scene passes through "
        "unchanged.",
        "nodule:type": "",
    },
    "slotCount": {
        "description": "How many shader slots are active (0–8). "
        "The node starts with none.",
        "nodule:type": "",
    },
    "editEnabled": {
        "description": "Legacy switch. Edit Shader now scans when you "
        "open the shader list and loads parameters when you pick one.",
        "nodule:type": "",
    },
    "editScope": {
        "description": "Unused by the artist UI. Edit Shader creates "
        "an internal ShaderEdits EditScope after the incoming scene.",
        "nodule:type": "",
        "plugValueWidget:type": "",
    },
    "editPath": {
        "description": "Authoring location of the existing shader to edit.",
        "nodule:type": "",
    },
    "editLoaded": {
        "description": "Whether the selected shader's parameter edits "
        "have been acquired in the EditScope.",
        "nodule:type": "",
    },
    "samplingEnabled": {
        "description": "Master switch for shading-sample overrides "
        "(renderer options and shader sample tweaks). The stage is "
        "not scanned until this is on.",
        "nodule:type": "",
    },
    "samplingEngine": {
        "description": "Renderer for this ShadingTk node (Arnold, "
        "Cycles, or RenderMan). The menu sits in the header, between "
        "the title and Copy. Sampling uses this choice.",
        "nodule:type": "",
        "label": "",
    },
    "mode": {
        "description": "Create assigns new shaders (Main and Settings). "
        "ShadingTk Manager sits under the header, then Mode. "
        "Edit shows Edit Shader, Edit Binding, and "
        "Settings (plus Sampling).",
        "nodule:type": "",
        "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
        "preset:Create": MODE_CREATE,
        "preset:Edit": MODE_EDIT,
        "label": "Mode",
    },
    "assignCount": {
        "description": "How many existing-shader assignment slots are "
        "active in Edit mode (0–8). The node starts with none.",
        "nodule:type": "",
    },
    "samplingApplyAll": {
        "description": "When on, set sample-like parameters on every "
        "matching surface and light shader in the incoming stage.",
        "nodule:type": "",
    },
    "samplingShaderSamples": {
        "description": "Value written onto shader sample parameters "
        "when Apply to all matching shaders is on.",
        "nodule:type": "",
    },
    "samplingEditPath": {
        "description": "Prim of a shader that already has sample parameters.",
        "nodule:type": "",
    },
    "samplingEditLoaded": {
        "description": "Whether a sampling shader has been loaded for edit.",
        "nodule:type": "",
    },
    "globalAssign": {
        "description": "Assign a default StandardSurface named all_shd. "
        "Not a slot — it has its own tab. Refine the scope with PrimPath.",
        "nodule:type": "",
    },
    "globalPath": {
        "description": "Prim path(s) for all_shd. Default ... is everything. "
        "Enabled when Assign all_shd is on. Pick from the Hierarchy / Viewport.",
        "nodule:type": "",
        "plugValueWidget:type": "GafferUI.StringPlugValueWidget",
    },
    "matteEnabled": {
        "description": "Assign Arnold Matte to the matte PrimPath.",
        "nodule:type": "",
    },
    "mattePath": {
        "description": "Prim path(s) that receive Matte. Pick from the "
        "Hierarchy / Viewport.",
        "nodule:type": "",
        "plugValueWidget:type": "GafferUI.StringPlugValueWidget",
    },
    "diagEnabled": {
        "description": "Quick-assign a diagnostic shader (utility, AO, "
        "wireframe, …). Defaults to everything.",
        "nodule:type": "",
    },
    "diagShader": {
        "description": "Diagnostic shader type.",
        "nodule:type": "",
        "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
    },
    "diagMode": {
        "description": "Utility color_mode when the diagnostic shader is Utility.",
        "nodule:type": "",
        "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
    },
    "diagPath": {
        "description": "Prim path(s) for the diagnostic assignment.",
        "nodule:type": "",
        "plugValueWidget:type": "GafferUI.StringPlugValueWidget",
    },
    "mixEnabled": {
        "description": "Mix slot shaders into a MixShader or LayerShader "
        "and assign the result.",
        "nodule:type": "",
    },
    "mixType": {
        "description": "MixShader (two inputs) or LayerShader (up to eight).",
        "nodule:type": "",
        "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
    },
    "mixName": {
        "description": "Shader network handle for the mix shader.",
        "nodule:type": "",
    },
    "mixCount": {
        "description": "How many mix inputs are used (2 for MixShader).",
        "nodule:type": "",
    },
    "mixPath": {
        "description": "Prim path(s) that receive this MixShader. "
        "The Assign section on the MixShader tab.",
        "nodule:type": "",
        "label": "PrimPath(s)",
        "plugValueWidget:type": "GafferUI.StringPlugValueWidget",
    },
    "autoName": {
        "description": "When on, Pick on Shader slots names the shader from the "
        "selection. It does not keep renaming afterwards.",
        "nodule:type": "",
    },
    "namePrefix": {
        "description": "Optional prefix for auto-named shaders. Blank by default.",
        "nodule:type": "",
    },
    "nameSuffix": {
        "description": "Suffix for auto-named shaders, e.g. shd → cube_shd. "
        "Uniqueness digits go after the name, never after the suffix "
        "(cube2_shd, not cube_shd2).",
        "nodule:type": "",
    },
    "presetFolder": {
        "description": "Folder of YAML shader presets. New nodes bind to "
        "../../presets relative to this module when that folder exists; "
        "otherwise this stays blank. Gaffer's bin folder is never used. "
        "Also searches SHADINGTK_PRESET_PATH.",
        "nodule:type": "",
        "plugValueWidget:type": "GafferUI.FileSystemPathPlugValueWidget",
        "path:leaf": False,
    },
}
for _mix in range(1, MAX_MIX_INPUTS + 1):
    _plugs[mix_input_plug(_mix)] = {
        "description": "Slot shader (or all_shd) plugged into this mix input.",
        "nodule:type": "",
    }
for _index in range(1, MAX_SLOTS + 1):
    _plugs[shader_type_plug(_index)] = {
        "description": "Arnold shader type written into ai:surface (Value), "
        "e.g. standard_surface.",
        "nodule:type": "",
    }
    _plugs[shader_name_plug(_index)] = {
        "description": "Shader node name written into ai:surface (Name). "
        "This is the handle on the primitive, not the shader type.",
        "nodule:type": "",
    }
    _plugs[texture_type_plug(_index)] = {
        "description": "Legacy diffuse-map type kept for older scripts. "
        "RGB attributes on the shader tab use the TXT button.",
        "nodule:type": "",
    }
    _plugs[displacement_type_plug(_index)] = {
        "description": "Optional displacement map (image, procedural, "
        "or a library texture). Assigned with ArnoldDisplacement on "
        "the same prims as this slot.",
        "nodule:type": "",
        "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
    }
    _plugs[path_count_plug(_index)] = {
        "description": "How many prim-path fields are shown for this slot.",
        "nodule:type": "",
    }
    for _path in range(1, MAX_PATHS + 1):
        _plugs[path_plug(_index, _path)] = {
            "description": "Scene prim path(s) assigned by {}. Type paths "
            "or Pick from the Hierarchy / Viewport. Multiple prims in one "
            "field are separated by spaces. Select highlights those prims "
            "in the scene.".format(slot_label(_index)),
            "label": "PrimPath(s)",
            "nodule:type": "",
            "plugValueWidget:type": "GafferUI.StringPlugValueWidget",
        }
    _plugs[assign_source_plug(_index)] = {
        "description": "Authoring location of an existing surface shader "
        "to copy onto {}'s PrimPath.".format(assign_slot_label(_index)),
        "label": "Shader",
        "nodule:type": "",
    }
    _plugs[assign_path_plug(_index)] = {
        "description": "Prim path(s) that receive the existing shader from "
        "{}. Pick / Select work like Create.".format(assign_slot_label(_index)),
        "label": "PrimPath",
        "nodule:type": "",
        "plugValueWidget:type": "GafferUI.StringPlugValueWidget",
    }

Gaffer.Metadata.registerNode(
    ShadingTk,
    "description",
    "Assigns up to eight Arnold shaders, plus optional all_shd / matte / "
    "diagnostic globals, MixShader, and EditScope tweaks. Mode Create "
    "builds new-shader UI; Mode Edit loads Edit Shader, Edit Binding, "
    "and Settings when chosen. Starts with no slots — add one when you need it.",
    "nodeGadget:color",
    BOX_PURPLE,
    "noduleLayout:customGadget:addButtonTop:gadgetType",
    None,
    "noduleLayout:customGadget:addButtonBottom:gadgetType",
    None,
    "noduleLayout:customGadget:addButtonLeft:gadgetType",
    None,
    "noduleLayout:customGadget:addButtonRight:gadgetType",
    None,
    "layout:customWidget:addButton:widgetType",
    "",
    "layout:customWidget:shadingTk:widgetType",
    "ShadingTkUI.ShadingTkUI._shadingTkWidgetCreator",
    "layout:customWidget:shadingTk:section",
    "",
    "layout:customWidget:shadingTk:index",
    0,
    "layout:activator:never",
    False,
    plugs=_plugs,
)

register_node_icon(ShadingTk, "shadingTkNode.png", "ShadingTk.png")


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
