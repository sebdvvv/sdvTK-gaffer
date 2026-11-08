"""OSL tab for the ShadingTk node editor."""

from __future__ import annotations

import contextlib
import weakref

import Gaffer
import GafferUI
import IECore

from sdvTkGaffer.ShadingTk._data import MAX_SLOTS
from sdvTkGaffer.ShadingTk._osl import (
    active_osl_node,
    connect_targets,
    osl_code_plug,
    osl_examples,
    osl_external_plug,
    osl_is_assignable,
    osl_name_plug,
    osl_output_plugs,
    osl_parameter_plugs,
    osl_prim_plug,
    osl_status,
)

from ._editor import (
    clear_container,
    expand_h,
    fit_width,
    native_widget,
    note_label,
    widget_is_alive,
)

_LIMITS = (
    "OSLCode (checkbox off) is the shader body only. No helper functions above the shader, "
    "and no #include. Add parameters and outputs as plugs. Gaffer compiles on edit and saves the code in the scene."
)
_EXTERNAL = (
    "Compile externally with oslc (checkbox on) takes the full .osl text, writes a temporary file, "
    "runs oslc, and puts the compiled shader in the OSL Path folder from Settings. "
    "Use this for noise_lib.h and any other include."
)
_HOOKUP = (
    "Connect an output into a Shader slot. Color goes to base color, emission, or specular color. "
    "Mask goes to roughness or metalness. Displacement goes to that slot's displacement map. "
    "The mesh needs subdivision, or the ridges stay flat."
)
_TIME = (
    "Drive Time sets Time = context.getFrame() / Framerate. Framerate is in Settings. "
    "Match Time, Scale, Speed, and WarpAmount on the surface and displacement shaders "
    "so the color bands stay on the ridges."
)
_ASSIGN = (
    "Once a slot has a shader, it gets its own tab. That tab assigns the OSL shader "
    "onto the prims you pick, the same way a ShaderAssignment does. Color and Mask "
    "stay outputs you connect into other shaders. A Displacement output also assigns "
    "an Arnold displacement of this shader on those same prims."
)


class _Call:
    def __init__(self, editor, fn, *head):
        self._editor = weakref.ref(editor)
        self._fn = fn
        self._head = head

    def __call__(self, *args):
        editor = self._editor()
        if editor is None or not widget_is_alive(editor):
            return None
        return self._fn(editor, *self._head, *args)


def _connect(bucket, editor, signal, fn, *head):
    bucket.append(signal.connect(_Call(editor, fn, *head), scoped=True))


def _undo(editor):
    script = editor._node.scriptNode()
    if script is None:
        return contextlib.nullcontext()
    return Gaffer.UndoScope(script)


def _fail(editor, index: int, exc: BaseException) -> None:
    node = editor._node
    status = getattr(node, "_oslStatus", None)
    if not isinstance(status, dict):
        status = {}
        node._oslStatus = status
    status[index] = str(exc)


class _Menu:
    def __init__(self, editor, fn, *head):
        self._editor = weakref.ref(editor)
        self._fn = fn
        self._head = head

    def __call__(self, *args):
        editor = self._editor()
        if editor is None or not widget_is_alive(editor):
            return IECore.MenuDefinition()
        return self._fn(editor, *self._head, *args)


def install_osl_tab(editor) -> None:
    if getattr(editor, "_osl_tab", None) is not None:
        return
    editor._node.ensureOslPlugs()
    form = GafferUI.ListContainer(
        GafferUI.ListContainer.Orientation.Vertical, spacing=8
    )
    editor._osl_form = form
    for text in (_LIMITS, _EXTERNAL, _HOOKUP, _TIME, _ASSIGN):
        form.append(note_label(text))
    buttons = GafferUI.ListContainer(
        GafferUI.ListContainer.Orientation.Horizontal, spacing=6
    )
    add = GafferUI.Button("Add OSL slot")
    add.setToolTip("Add an OSL shader slot (max {}).".format(MAX_SLOTS))
    editor._buttonConnections.append(
        add.clickedSignal().connect(_Call(editor, _on_add_slot), scoped=True)
    )
    buttons.append(add)
    form.append(buttons)
    editor._add_osl_button = add
    host = GafferUI.ListContainer(
        GafferUI.ListContainer.Orientation.Vertical, spacing=8
    )
    form.append(host)
    editor._osl_host = host
    editor._osl_connections = []
    editor._osl_status_labels = {}
    editor._osl_tab = editor._scroll(form)
    editor._osl_shader_tabs = {}
    editor._osl_shader_forms = {}
    editor._osl_shader_sig = {}
    editor._add_tab(editor._tabs, editor._osl_tab, "OSL slots")


def append_osl_settings(editor, form) -> None:
    editor._node.ensureOslPlugs()
    form.append(GafferUI.Label("<b>OSL</b>"))
    path = native_widget(editor._node["oslPath"])
    try:
        path.setToolTip(
            "Compiled .oso shaders are written here, and this folder is prepended to "
            "OSL_SHADER_PATHS. Compile OSL also copies noise_lib.h here if it is missing."
        )
    except Exception:
        pass
    editor._addRow(form, "OSL Path folder", path, name="oslPath")
    rate = native_widget(editor._node["oslFrameRate"])
    try:
        rate.setToolTip(
            "Drive Time uses context.getFrame() / Framerate. "
            "24 matches the expression parent[...][\"parameters\"][\"Time\"] = context.getFrame() / 24.0."
        )
    except Exception:
        pass
    editor._addRow(form, "Framerate", rate, name="oslFrameRate")


def sync_osl_tab(editor) -> None:
    host = getattr(editor, "_osl_host", None)
    if host is None or not widget_is_alive(host):
        return
    node = editor._node
    node.ensureOslPlugs()
    try:
        count = int(node["oslCount"].getValue())
    except Exception:
        count = 0
    editor._osl_connections = []
    editor._osl_status_labels = {}
    editor._osl_param_names = {}
    _remember_new_slots(editor, count)
    clear_container(host)
    for index in range(1, count + 1):
        host.append(_build_slot(editor, index))
    button = getattr(editor, "_add_osl_button", None)
    if button is not None and widget_is_alive(button):
        button.setEnabled(count < MAX_SLOTS)
    sync_osl_shader_tabs(editor)


def refresh_osl_status(editor) -> None:
    labels = getattr(editor, "_osl_status_labels", {})
    node = editor._node
    for index, label in list(labels.items()):
        if not widget_is_alive(label):
            continue
        label.setText(osl_status(node, index) or " ")
    sync_osl_shader_tabs(editor)


def _collapsed_states(editor) -> dict:
    states = getattr(editor, "_osl_collapsed", None)
    if not isinstance(states, dict):
        states = {}
        editor._osl_collapsed = states
    return states


def _remember_new_slots(editor, count: int) -> None:
    """A slot you just added starts open. Slots already on the node stay as they were."""
    states = _collapsed_states(editor)
    previous = getattr(editor, "_osl_built_count", 0)
    if count > previous:
        for index in range(previous + 1, count + 1):
            states[index] = False
    editor._osl_built_count = count


def _slot_title(node, index: int) -> str:
    title = "OSL {}".format(index)
    try:
        named = (node[osl_name_plug(index)].getValue() or "").strip()
    except Exception:
        named = ""
    if named:
        title = "{} — {}".format(title, named)
    return title


def _relax_collapsible(section: GafferUI.Collapsible) -> None:
    """Let the section use the panel width. A long title does not stretch it."""
    try:
        from Qt import QtWidgets

        qt_widget = section._qtWidget()
        layout = qt_widget.layout()
        if layout is not None:
            layout.setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)
        qt_widget.setMinimumWidth(0)
        qt_widget.setMaximumWidth(16777215)
        toggle = qt_widget.findChild(QtWidgets.QCheckBox)
        if toggle is not None:
            toggle.setMinimumWidth(0)
            toggle.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
            )
    except Exception:
        pass


def _fit_code(code: GafferUI.Widget) -> None:
    """Keep the code field inside the panel. Long lines wrap."""
    fit_width(code)
    try:
        from Qt import QtWidgets

        text = code.textWidget()._qtWidget()
        text.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        text.setMinimumWidth(0)
        policy = text.sizePolicy()
        policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Expanding)
        text.setSizePolicy(policy)
    except Exception:
        pass


def _build_slot(editor, index: int) -> GafferUI.Collapsible:
    node = editor._node
    body = GafferUI.ListContainer(
        GafferUI.ListContainer.Orientation.Vertical, spacing=6
    )
    section = GafferUI.Collapsible(
        _slot_title(node, index),
        collapsed=_collapsed_states(editor).get(index, False),
    )
    section.setChild(body)
    _relax_collapsible(section)
    expand_h(section)
    remove = GafferUI.Button("Remove")
    remove.setToolTip("Remove this OSL slot.")
    _connect(editor._osl_connections, editor, remove.clickedSignal(), _on_remove_slot, index)
    section.setCornerWidget(remove)
    _connect(
        editor._osl_connections,
        editor,
        section.stateChangedSignal(),
        _on_slot_state,
        index,
    )

    editor._addRow(
        body,
        "Name",
        native_widget(node[osl_name_plug(index)]),
        name="oslName{}".format(index),
    )
    external = bool(node[osl_external_plug(index)].getValue())
    editor._addRow(
        body,
        "Compile externally with `oslc`",
        native_widget(node[osl_external_plug(index)]),
        name="oslExternal{}".format(index),
    )

    actions = GafferUI.ListContainer(
        GafferUI.ListContainer.Orientation.Vertical, spacing=4
    )
    action_row = GafferUI.ListContainer(
        GafferUI.ListContainer.Orientation.Horizontal, spacing=6
    )
    compile_button = GafferUI.Button("Compile OSL")
    compile_button.setEnabled(external)
    compile_button.setToolTip(
        "Compile the .osl source with oslc into the OSL Path folder."
        if external
        else "Turn on Compile externally with oslc. While it is off, OSLCode compiles the shader body on edit."
    )
    _connect(
        editor._osl_connections,
        editor,
        compile_button.clickedSignal(),
        _on_compile,
        index,
    )
    action_row.append(compile_button)
    examples = GafferUI.MenuButton(
        "Examples",
        menu=GafferUI.Menu(_Menu(editor, _example_menu, index)),
    )
    examples.setToolTip(
        "Load a full .osl shader, or an OSLCode body with the noise inlined."
    )
    action_row.append(examples)
    actions.append(action_row)
    action_row = GafferUI.ListContainer(
        GafferUI.ListContainer.Orientation.Horizontal, spacing=6
    )
    drive = GafferUI.Button("Drive Time")
    drive.setToolTip(
        "Expression: Time = context.getFrame() / Framerate (Settings)."
    )
    _connect(editor._osl_connections, editor, drive.clickedSignal(), _on_drive_time, index)
    action_row.append(drive)
    connect = GafferUI.MenuButton(
        "Connect output",
        menu=GafferUI.Menu(_Menu(editor, _connect_menu, index)),
    )
    connect.setToolTip(
        "Plug this shader into a Shader slot. "
        "Uses OSLCode, or the oslc shader when Compile externally is on."
    )
    action_row.append(connect)
    actions.append(action_row)
    body.append(actions)

    body.append(GafferUI.Label("Code"))
    code = native_widget(node[osl_code_plug(index)])
    try:
        code.textWidget().setRole(GafferUI.MultiLineTextWidget.Role.Code)
        code.textWidget().setLineNumbersVisible(True)
        code.setToolTip(
            "Full .osl source, including the shader declaration, functions, and #include lines."
            if external
            else "Shader body only. No helper functions and no #include. Parameters and outputs are plugs."
        )
    except Exception:
        pass
    _fit_code(code)
    body.append(code)

    status = note_label(osl_status(node, index) or " ")
    editor._osl_status_labels[index] = status
    body.append(status)
    _build_parameters(editor, body, index, external)
    return section


def _build_parameters(editor, body, index: int, external: bool) -> None:
    node = editor._node
    if external:
        plugs = osl_parameter_plugs(node, index)
        if not plugs:
            body.append(
                note_label("Compile OSL to load parameters from the compiled shader.")
            )
            return
        body.append(GafferUI.Label("<b>Shader parameters</b>"))
    else:
        body.append(GafferUI.Label("<b>Parameters and outputs</b>"))
        name = GafferUI.TextWidget()
        try:
            name.setPlaceholderText("Plug name, for example Time")
        except Exception:
            pass
        fit_width(name)
        editor._osl_param_names[index] = name
        row = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=6
        )
        row.append(name, expand=True)
        row.append(
            GafferUI.MenuButton(
                "Add",
                menu=GafferUI.Menu(_Menu(editor, _add_menu, index)),
            )
        )
        body.append(row)
        plugs = osl_parameter_plugs(node, index)
    outputs = osl_output_plugs(node, index)
    if outputs:
        body.append(
            note_label(
                "Outputs: {}".format(", ".join(plug.getName() for plug in outputs))
            )
        )
    for plug in plugs:
        try:
            editor._addRow(body, plug.getName(), native_widget(plug))
        except Exception:
            continue
    if not external and active_osl_node(node, index) is None:
        body.append(GafferUI.Label("OSLCode is created when this slot is added."))


def _example_menu(editor, index: int, *unused) -> IECore.MenuDefinition:
    menu = IECore.MenuDefinition()
    for key, label in osl_examples():
        menu.append(
            "/" + label,
            {"command": _Call(editor, _on_example, index, key)},
        )
    return menu


def _add_menu(editor, index: int, *unused) -> IECore.MenuDefinition:
    menu = IECore.MenuDefinition()
    for label, kind, output in (
        ("Parameter/Float", "float", False),
        ("Parameter/Color", "color", False),
        ("Parameter/Int", "int", False),
        ("Output/Color", "color", True),
        ("Output/Float", "float", True),
    ):
        menu.append(
            "/" + label,
            {"command": _Call(editor, _on_add_plug, index, kind, output)},
        )
    return menu


def _connect_menu(editor, index: int, *unused) -> IECore.MenuDefinition:
    menu = IECore.MenuDefinition()
    try:
        items = connect_targets(editor._node, index)
    except Exception:
        items = []
    if not items:
        menu.append(
            "/Compile or edit the shader, and add a shader slot first",
            {"active": False},
        )
        return menu
    for item in items:
        menu.append(
            "/" + item["label"],
            {
                "command": _Call(
                    editor,
                    _on_connect,
                    index,
                    item["output"],
                    item["slot"],
                    item["parameter"],
                    item["displacement"],
                )
            },
        )
    return menu


def _on_add_slot(editor, *unused) -> None:
    with _undo(editor):
        editor._node.addOslSlot()


def _on_slot_state(editor, index: int, section, *unused) -> None:
    try:
        _collapsed_states(editor)[index] = bool(section.getCollapsed())
    except Exception:
        pass


def _on_remove_slot(editor, index: int, *unused) -> None:
    states = _collapsed_states(editor)
    try:
        count = int(editor._node["oslCount"].getValue())
    except Exception:
        count = 0
    shifted = {}
    for slot in range(1, count):
        source = slot if slot < index else slot + 1
        if source in states:
            shifted[slot] = states[source]
    editor._osl_collapsed = shifted
    editor._osl_built_count = max(0, count - 1)
    with _undo(editor):
        editor._node.removeOslSlotAt(index)


def _on_compile(editor, index: int, *unused) -> None:
    try:
        with _undo(editor):
            editor._node.compileOsl(index)
    except Exception as exc:
        _fail(editor, index, exc)
    sync_osl_tab(editor)


def _on_example(editor, index: int, key: str, *unused) -> None:
    try:
        with _undo(editor):
            editor._node.loadOslExample(index, key)
    except Exception as exc:
        _fail(editor, index, exc)
    sync_osl_tab(editor)


def _on_drive_time(editor, index: int, *unused) -> None:
    try:
        with _undo(editor):
            editor._node.driveOslTime(index)
    except Exception as exc:
        _fail(editor, index, exc)
    refresh_osl_status(editor)


def _on_add_plug(editor, index: int, kind: str, output: bool, *unused) -> None:
    widget = getattr(editor, "_osl_param_names", {}).get(index)
    raw = ""
    if widget is not None and widget_is_alive(widget):
        try:
            raw = widget.getText()
        except Exception:
            raw = ""
    try:
        with _undo(editor):
            editor._node.addOslPlug(index, raw, kind, output)
    except Exception as exc:
        _fail(editor, index, exc)
    sync_osl_tab(editor)


def _on_connect(
    editor, index: int, output: str, slot: int, parameter: str, displacement: bool, *unused
) -> None:
    try:
        with _undo(editor):
            editor._node.connectOslOutput(index, output, slot, parameter, displacement)
    except Exception as exc:
        _fail(editor, index, exc)
    refresh_osl_status(editor)


def sync_osl_shader_tabs(editor) -> None:
    tabs = getattr(editor, "_tabs", None)
    if tabs is None or not widget_is_alive(tabs):
        return
    node = editor._node
    widgets = getattr(editor, "_osl_shader_tabs", None)
    if not isinstance(widgets, dict):
        widgets = {}
        editor._osl_shader_tabs = widgets
    forms = getattr(editor, "_osl_shader_forms", None)
    if not isinstance(forms, dict):
        forms = {}
        editor._osl_shader_forms = forms
    signatures = getattr(editor, "_osl_shader_sig", None)
    if not isinstance(signatures, dict):
        signatures = {}
        editor._osl_shader_sig = signatures
    try:
        count = int(node["oslCount"].getValue())
    except Exception:
        count = 0
    alive = set()
    used = set()
    changed = False
    for index in range(1, count + 1):
        if not osl_is_assignable(node, index):
            if index in widgets:
                _drop_shader_tab(editor, index)
                changed = True
            continue
        alive.add(index)
        label = _shader_tab_label(node, index, used)
        widget = widgets.get(index)
        if widget is None or not widget_is_alive(widget):
            widget = _build_shader_tab(editor, index)
            widgets[index] = widget
            editor._add_tab(
                tabs, widget, label, index=editor._tab_index_after(None)
            )
            changed = True
        else:
            try:
                tabs.setLabel(widget, label)
            except Exception:
                pass
            try:
                tabs.setTabVisible(widget, True)
            except Exception:
                pass
        signature = _shader_signature(node, index)
        if signatures.get(index) != signature:
            _fill_shader_form(editor, index)
            signatures[index] = signature
            changed = True
    for index in list(widgets):
        if index not in alive:
            _drop_shader_tab(editor, index)
            changed = True
    if changed and hasattr(editor, "_refresh_shader_manager"):
        editor._refresh_shader_manager()


def _shader_tab_label(node, index: int, used: set) -> str:
    name = ""
    try:
        name = (node[osl_name_plug(index)].getValue() or "").strip()
    except Exception:
        name = ""
    if not name:
        name = "OSL {}".format(index)
    if name in used:
        name = "{} {}".format(name, index)
    used.add(name)
    return name


def _shader_signature(node, index: int):
    osl = active_osl_node(node, index)
    params = tuple(plug.getName() for plug in osl_parameter_plugs(node, index))
    outputs = tuple(plug.getName() for plug in osl_output_plugs(node, index))
    disp = node.getChild("__oslDisp{}".format(index)) is not None
    return (id(osl), params, outputs, disp)


def _build_shader_tab(editor, index: int):
    form = GafferUI.ListContainer(
        GafferUI.ListContainer.Orientation.Vertical, spacing=8
    )
    form.append(note_label(_ASSIGN))
    node = editor._node
    plug = node[osl_prim_plug(index)]
    widget = GafferUI.StringPlugValueWidget(plug)
    try:
        widget.setToolTip(
            "Prims this OSL shader is assigned to. Several paths are separated by spaces."
        )
    except Exception:
        pass
    row = editor._addRow(form, "PrimPath(s)", widget, name=osl_prim_plug(index))
    pick = GafferUI.Button("Pick")
    pick.setToolTip("Use the prims selected in the Hierarchy or Viewport.")
    editor._buttonConnections.append(
        pick.clickedSignal().connect(_Call(editor, _on_pick_osl, index), scoped=True)
    )
    row.append(pick)
    edit = GafferUI.Button("Edit")
    edit.setToolTip("Open this shader in Shader Manager.")
    editor._buttonConnections.append(
        edit.clickedSignal().connect(_Call(editor, _on_edit_osl, index), scoped=True)
    )
    row.append(edit)
    host = GafferUI.ListContainer(
        GafferUI.ListContainer.Orientation.Vertical, spacing=6
    )
    form.append(host)
    editor._osl_shader_forms[index] = host
    return editor._scroll(form)


def _fill_shader_form(editor, index: int) -> None:
    host = getattr(editor, "_osl_shader_forms", {}).get(index)
    if host is None or not widget_is_alive(host):
        return
    clear_container(host)
    node = editor._node
    outputs = osl_output_plugs(node, index)
    if outputs:
        host.append(
            note_label(
                "Outputs: {}".format(", ".join(plug.getName() for plug in outputs))
            )
        )
    host.append(GafferUI.Label("<b>Parameters</b>"))
    for plug in osl_parameter_plugs(node, index):
        try:
            editor._addRow(host, plug.getName(), native_widget(plug))
        except Exception:
            continue
    disp = node.getChild("__oslDisp{}".format(index))
    height = None
    if disp is not None:
        if "height" in disp:
            height = disp["height"]
        elif "parameters" in disp and "height" in disp["parameters"]:
            height = disp["parameters"]["height"]
    if height is not None:
        host.append(GafferUI.Label("<b>Displacement</b>"))
        try:
            editor._addRow(host, "Height", native_widget(height))
        except Exception:
            pass


def _drop_shader_tab(editor, index: int) -> None:
    widgets = getattr(editor, "_osl_shader_tabs", {})
    widget = widgets.pop(index, None)
    getattr(editor, "_osl_shader_forms", {}).pop(index, None)
    getattr(editor, "_osl_shader_sig", {}).pop(index, None)
    tabs = getattr(editor, "_tabs", None)
    if widget is None or tabs is None:
        return
    try:
        tabs.removeChild(widget)
    except Exception:
        pass


def _on_pick_osl(editor, index: int, *unused) -> None:
    editor.pickInto(osl_prim_plug(index))


def _on_edit_osl(editor, index: int, *unused) -> None:
    editor.openShaderManager("osl:{}".format(index))
