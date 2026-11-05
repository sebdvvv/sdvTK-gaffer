"""Create / Edit insert: unique names, nested groups, overlay merge.

Edit loads transform and shader values from an existing light, then
authors this node's light at the same name and path. MergeScenes
replaces that location (no Prune). Mesh lights keep the mesh and
light it in place.
"""

from __future__ import annotations

import math
import re

import Gaffer
import GafferScene
import IECore
import imath

MODE_CREATE = "create"
MODE_EDIT = "edit"
DEFAULT_LABEL = "label"
DEFAULT_PRIM_PATH = "/LIGHTS"
MAX_GROUPS = 4
_GROUP_NAME = "__group{}"
_GROUP_SWITCH_NAME = "__groupSwitch{}"
SKY_SHADERS = frozenset({"skydome_light", "sky_light"})

# Prim names are ``{label}{index}_{typeToken}``. *typeToken* is camelCase
# with no underscores so the label may itself contain ``_``.
_INDEXED_TYPE = re.compile(
    r"^(?P<label>.+)(?P<index>\d+)_(?P<type>[A-Za-z]+)$"
)
_LEGACY_INDEXED_TYPE = re.compile(
    r"^(?P<label>.+)_(?P<type>[A-Za-z]+)(?P<index>\d+)$"
)


def path_parts(path: str) -> list[str]:
    return [p for p in (path or "").replace("\\", "/").split("/") if p]


def join_path(parts: list[str]) -> str:
    return "/" + "/".join(parts) if parts else ""


def split_location(path: str) -> tuple[str, str]:
    parts = path_parts(path)
    if not parts:
        return "", ""
    parent = join_path(parts[:-1])
    return parent, parts[-1]


def sanitise_label(label: str, *, fallback: str | None = DEFAULT_LABEL) -> str:
    text = (label or "").strip().replace(" ", "_")
    text = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")
    if fallback is None:
        return text
    return text or fallback


def name_type_token(type_id: str) -> str:
    """CamelCase type fragment for prim names — never contains ``_``."""
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", type_id or "") if p]
    if not parts:
        return "light"
    return parts[0].lower() + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def prim_type_token(type_id: str, aliases: dict[str, str] | None = None) -> str:
    if aliases:
        mapped = aliases.get(type_id)
        if mapped:
            return mapped
    return name_type_token(type_id)


def sanitise_type_token(type_token: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "", type_token or "")
    return text or "light"


def constructed_indexed_name(label: str, type_token: str, index: int) -> str:
    """``{label}{index}_{typeToken}``, or ``{typeToken}{index}`` if label is empty."""
    token = sanitise_type_token(type_token)
    clean = sanitise_label(label)
    if not clean:
        return "{}{}".format(token, index)
    return "{}{}_{}".format(clean, index, token)


def next_indexed_name(label: str, type_token: str, used: set[str]) -> str:
    """Next unused constructed_indexed_name, case-insensitive."""
    used_keys = {(u or "").strip().lstrip("/").lower() for u in used if u}
    index = 1
    while True:
        candidate = constructed_indexed_name(label, type_token, index)
        if candidate.lower() not in used_keys:
            return candidate
        index += 1


def parse_label_from_name(leaf: str, type_token: str) -> str:
    leaf = (leaf or "").strip().lstrip("/")
    if not leaf:
        return DEFAULT_LABEL
    if type_token:
        type_only = re.compile(
            r"^" + re.escape(type_token) + r"\d+$", re.IGNORECASE
        )
        if type_only.match(leaf):
            return ""
        current = re.compile(
            r"\d+_" + re.escape(type_token) + r"$", re.IGNORECASE
        )
        stripped = current.sub("", leaf)
        if stripped and stripped != leaf:
            return stripped
        legacy = re.compile(
            r"_" + re.escape(type_token) + r"\d+$", re.IGNORECASE
        )
        stripped = legacy.sub("", leaf)
        if stripped and stripped != leaf:
            return stripped
    match = _INDEXED_TYPE.match(leaf) or _LEGACY_INDEXED_TYPE.match(leaf)
    if match:
        return match.group("label") or DEFAULT_LABEL
    return leaf


def sanitise_graph_name(name: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", name or "").strip("_")
    if not text:
        return "Light"
    if text[0].isdigit():
        text = "n" + text
    return text


def connect_array(array_plug: Gaffer.Plug, sources: list) -> None:
    for src in sources:
        free = None
        for child in array_plug.children():
            if child.getInput() is None:
                free = child
                break
        if free is None:
            children = list(array_plug.children())
            if not children:
                continue
            free = children[-1]
        free.setInput(src)


def add_public_insert_plugs(
    node: Gaffer.Node, default_name: str, *, default_label: str | None = None
) -> None:
    if default_label is None:
        default_label = DEFAULT_LABEL
    node.addChild(Gaffer.StringPlug("mode", defaultValue=MODE_CREATE))
    node.addChild(Gaffer.StringPlug("label", defaultValue=default_label))
    node.addChild(Gaffer.StringPlug("name", defaultValue=default_name))
    node.addChild(Gaffer.StringPlug("primPath", defaultValue=DEFAULT_PRIM_PATH))
    node.addChild(Gaffer.StringPlug("editPath", defaultValue=""))


def wanted_group_names(path: str, *, max_groups: int = MAX_GROUPS) -> list[str]:
    """Innermost-first group names for *path* (empty path → no groups)."""
    parts = path_parts(path)[:max_groups]
    parts.reverse()
    return parts


def add_group_chain(
    node: Gaffer.Node,
    source: Gaffer.Plug,
    *,
    max_groups: int = MAX_GROUPS,
    extra_sources: list | None = None,
) -> Gaffer.Plug:
    """Create Group nodes only for the current ``primPath`` (max *max_groups*)."""
    return sync_group_chain(
        node, source, max_groups=max_groups, extra_sources=extra_sources
    )


def sync_group_chain(
    node: Gaffer.Node,
    source: Gaffer.Plug,
    sink: Gaffer.Plug | None = None,
    *,
    max_groups: int = MAX_GROUPS,
    path: str | None = None,
    extra_sources: list | None = None,
) -> Gaffer.Plug:
    """Rebuild the group chain to match *path*. Stick until the path changes.

    *extra_sources* (gobo, etc.) feed the innermost Group so they sit
    under the same prim-path folders, not after the chain.
    """
    extras = [src for src in (extra_sources or []) if src is not None]
    if path is None:
        try:
            path = (node["primPath"].getValue() or "").strip()
        except Exception:
            path = ""
    names = wanted_group_names(path, max_groups=max_groups)
    _remove_legacy_group_switches(node)
    existing = _group_nodes(node)
    current_names = [_group_node_name(group) for group in existing]
    output = existing[-1]["out"] if existing else source
    if current_names == names:
        if not names:
            output = source
        elif existing:
            _wire_group_inputs(existing[0], source, extras)
        _set_sink(sink, output)
        return output

    while len(existing) > len(names):
        _remove_internal_node(node, existing.pop())
    while len(existing) < len(names):
        index = len(existing)
        group = GafferScene.Group(_GROUP_NAME.format(index))
        node.addChild(group)
        existing.append(group)

    previous = source
    for index, group in enumerate(existing):
        try:
            group["name"].setValue(names[index])
        except Exception:
            pass
        extras_here = extras if index == 0 else []
        _wire_group_inputs(group, previous, extras_here)
        previous = group["out"]
    output = previous
    _set_sink(sink, output)
    return output


def _wire_group_inputs(group, primary, extras) -> None:
    sources = [primary]
    sources.extend(extras or [])
    _clear_array_inputs(group["in"])
    connect_array(group["in"], sources)


def _group_nodes(node: Gaffer.Node) -> list:
    found: list = []
    index = 0
    while True:
        child = node.getChild(_GROUP_NAME.format(index))
        if child is None:
            break
        found.append(child)
        index += 1
    return found


def _group_node_name(group) -> str:
    try:
        if "name" in group:
            return group["name"].getValue() or ""
    except Exception:
        pass
    return ""


def _remove_legacy_group_switches(node: Gaffer.Node) -> None:
    index = 0
    while True:
        child = node.getChild(_GROUP_SWITCH_NAME.format(index))
        if child is None:
            break
        _remove_internal_node(node, child)
        index += 1


def _clear_array_inputs(array_plug: Gaffer.Plug) -> None:
    try:
        children = list(array_plug.children())
    except Exception:
        return
    for child in children:
        try:
            if child.getInput() is not None:
                child.setInput(None)
        except Exception:
            pass


def _set_sink(sink: Gaffer.Plug | None, output: Gaffer.Plug) -> None:
    if sink is None:
        return
    try:
        current = sink.getInput()
        if current is not None and current.isSame(output):
            return
        sink.setInput(output)
    except Exception:
        pass


def _remove_internal_node(node: Gaffer.Node, child) -> None:
    try:
        for plug in child.children(Gaffer.Plug):
            try:
                if plug.getInput() is not None:
                    plug.setInput(None)
            except Exception:
                pass
            try:
                for dest in list(plug.outputs()):
                    dest.setInput(None)
            except Exception:
                pass
        node.removeChild(child)
    except Exception:
        pass


def add_gl_drawing(
    node: Gaffer.Node, source: Gaffer.Plug, filter_plug: Gaffer.Plug
) -> Gaffer.Plug:
    """Optional per-light Viewer drawing override (``gl:light:drawingMode``).

    Default is inherit: the OpenGLAttributes node is off so the Viewer
    Drawing menu (wireframe / color / texture) still applies. Set
    ``glDrawingMode`` to ``off`` / ``wireframe`` / ``color`` / ``texture``
    to author that mode on this light only.
    """
    if "glDrawingMode" not in node:
        node.addChild(Gaffer.StringPlug("glDrawingMode", defaultValue=""))
    gl_attrs = GafferScene.OpenGLAttributes("__glDraw")
    node.addChild(gl_attrs)
    gl_attrs["in"].setInput(source)
    gl_attrs["filter"].setInput(filter_plug)
    gl_attrs["enabled"].setValue(False)
    try:
        plug = gl_attrs["attributes"]["gl:light:drawingMode"]
        if "enabled" in plug:
            plug["enabled"].setValue(True)
    except Exception:
        pass
    return gl_attrs["out"]


def add_scene_switch(
    node: Gaffer.Node,
    name: str,
    sources: list,
    *,
    default_index: int = 0,
) -> Gaffer.Switch:
    """Pick one scene input. Unused sources are not pulled (stay inactive)."""
    switch = Gaffer.Switch(name)
    node.addChild(switch)
    switch.setup(GafferScene.ScenePlug("in"))
    if sources:
        switch["in"].resize(len(sources))
        for index, source in enumerate(sources):
            switch["in"][index].setInput(source)
        if 0 <= default_index < len(sources):
            try:
                switch["index"].setValue(default_index)
            except Exception:
                pass
    return switch


def node_enabled_plug(node: Gaffer.Node):
    child = node.getChild("enabled")
    if isinstance(child, Gaffer.BoolPlug):
        return child
    getter = getattr(node, "enabledPlug", None)
    if not callable(getter):
        return None
    try:
        plug = getter()
    except Exception:
        return None
    return plug if isinstance(plug, Gaffer.BoolPlug) else None


def set_node_enabled(node: Gaffer.Node, on: bool) -> None:
    """Force ``enabled`` on/off. Expression inputs cannot drive this plug."""
    plug = node_enabled_plug(node)
    if plug is None:
        return
    try:
        if plug.getInput() is not None:
            plug.setInput(None)
    except Exception:
        pass
    try:
        plug.setFlags(Gaffer.Plug.Flags.Serialisable, False)
    except Exception:
        pass
    value = bool(on)
    try:
        if bool(plug.getValue()) == value:
            return
    except Exception:
        pass
    try:
        plug.setValue(value)
    except Exception:
        pass


def set_switch_index(parent: Gaffer.Node, name: str, index: int) -> None:
    switch = parent.getChild(name)
    if switch is None:
        return
    plug = switch.getChild("index")
    if plug is None:
        return
    try:
        if plug.getInput() is not None:
            plug.setInput(None)
    except Exception:
        pass
    try:
        if int(plug.getValue()) == int(index):
            return
    except Exception:
        pass
    try:
        plug.setValue(int(index))
    except Exception:
        pass


def set_plug_value(plug, value) -> None:
    if plug is None:
        return
    try:
        if plug.getInput() is not None:
            plug.setInput(None)
    except Exception:
        pass
    try:
        current = plug.getValue()
        if isinstance(value, IECore.StringVectorData) or isinstance(
            current, IECore.StringVectorData
        ):
            if list(current) == list(value):
                return
        elif current == value:
            return
    except Exception:
        pass
    try:
        plug.setValue(value)
    except Exception:
        pass


def parse_prim_paths(*texts: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        raw = str(text or "").replace("\\", "/").replace(",", " ")
        for token in raw.split():
            item = token.strip()
            if not item:
                continue
            if not item.startswith("/"):
                item = "/" + item
            if item in seen:
                continue
            seen.add(item)
            found.append(item)
    return found


def set_filter_paths(parent: Gaffer.Node, name: str, paths) -> None:
    child = parent.getChild(name)
    if child is None or "paths" not in child:
        return
    set_plug_value(child["paths"], IECore.StringVectorData(list(paths)))


def sync_enabled_switch(node: Gaffer.Node) -> None:
    enabled = True
    try:
        enabled = bool(node["enabled"].getValue())
    except Exception:
        pass
    set_switch_index(node, "__enabledSwitch", 1 if enabled else 0)


def configure_internal_enabled(node: Gaffer.Node, on: bool) -> None:
    set_node_enabled(node, on)


def add_overlay_merge(
    node: Gaffer.Node, incoming: Gaffer.Plug, overlay: Gaffer.Plug
) -> GafferScene.MergeScenes:
    """Incoming scene plus this node's light; overlapping locations take the light."""
    merge = GafferScene.MergeScenes("__mergeScene")
    node.addChild(merge)
    merge["in"][0].setInput(incoming)
    merge["in"][1].setInput(overlay)
    replace = int(GafferScene.MergeScenes.Mode.Replace)
    for plug_name in ("transformMode", "attributesMode", "objectMode"):
        try:
            merge[plug_name].setValue(replace)
        except Exception:
            pass
    return merge


def insert_expression_lines(
    type_plug: str,
    created_types: list[str],
    internal_name,
    *,
    switch_types: list[str] | None = None,
    switch_name: str = "__lightSwitch",
) -> list[str]:
    lines = [
        "leaf = parent['name'] or 'light'",
        "path = leaf if str(leaf).startswith('/') else '/' + str(leaf)",
        "parent['__pathFilter']['paths'] = IECore.StringVectorData([path])",
    ]
    del type_plug, created_types, internal_name, switch_types, switch_name
    lines.extend(
        [
            "draw = (parent['glDrawingMode'] or '').strip().lower()",
            "parent['__glDraw']['enabled'] = draw not in ('', 'inherit', 'default')",
            "parent['__glDraw']['attributes']['gl:light:drawingMode']['value'] = "
            "draw if draw else 'wireframe'",
        ]
    )
    return lines


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


def _with_scene_context(node: Gaffer.Node, fn):
    script = node.scriptNode()
    context = script.context() if script is not None else None
    if context is not None:
        with context:
            return fn()
    return fn()


def _shader_network(attrs) -> tuple[object | None, object | None]:
    try:
        import IECoreScene
    except Exception:
        IECoreScene = None
    for key in attrs.keys():
        try:
            value = attrs[key]
        except Exception:
            continue
        type_name = value.__class__.__name__
        if type_name == "ShaderNetwork" or (
            IECoreScene is not None
            and isinstance(value, IECoreScene.ShaderNetwork)
        ):
            return key, value
    return None, None


def _network_shaders(network) -> dict[str, object]:
    found: dict[str, object] = {}
    shaders_fn = getattr(network, "shaders", None)
    if callable(shaders_fn):
        try:
            data = shaders_fn()
            if isinstance(data, dict):
                for handle, shader in data.items():
                    found[str(getattr(shader, "name", handle))] = shader
                return found
        except Exception:
            pass
    get_output = getattr(network, "getOutput", None)
    get_shader = getattr(network, "getShader", None)
    if callable(get_output) and callable(get_shader):
        try:
            output = get_output()
            handle = getattr(output, "shader", None)
            if handle:
                shader = get_shader(handle)
                found[str(getattr(shader, "name", handle))] = shader
        except Exception:
            pass
    return found


def _set_plug_from_data(plug: Gaffer.Plug, data) -> None:
    value = data.value if hasattr(data, "value") else data
    try:
        plug.setValue(value)
        return
    except Exception:
        pass
    if hasattr(value, "value"):
        try:
            plug.setValue(value.value)
        except Exception:
            pass


def apply_matrix_to_transform(plug: Gaffer.Plug, matrix) -> None:
    try:
        scale = imath.V3f()
        shear = imath.V3f()
        rotate = imath.V3f()
        translate = imath.V3f()
        if hasattr(matrix, "extractSHRT"):
            matrix.extractSHRT(scale, shear, rotate, translate)
            if "translate" in plug:
                plug["translate"].setValue(translate)
            if "scale" in plug:
                plug["scale"].setValue(scale)
            if "rotate" in plug:
                deg = 180.0 / math.pi
                plug["rotate"].setValue(
                    imath.V3f(rotate.x * deg, rotate.y * deg, rotate.z * deg)
                )
            return
    except Exception:
        pass
    try:
        translate = matrix.translation()
        if "translate" in plug:
            plug["translate"].setValue(imath.V3f(translate))
    except Exception:
        pass


def list_scene_lights(node: Gaffer.Node, accept) -> list[str]:
    if "in" not in node or node["in"].getInput() is None:
        return []

    def _collect() -> list[str]:
        try:
            data = node["in"].set("__lights")
        except Exception:
            return []
        if data is None:
            return []
        matcher = getattr(data, "value", data)
        paths_fn = getattr(matcher, "paths", None)
        raw = []
        if callable(paths_fn):
            try:
                raw = list(paths_fn())
            except Exception:
                raw = []
        result = []
        for path in raw:
            location = str(path)
            try:
                attrs = node["in"].attributes(location)
            except Exception:
                result.append(location)
                continue
            _key, network = _shader_network(attrs)
            shader_name = ""
            if network is not None:
                shaders = _network_shaders(network)
                if shaders:
                    shader_name = next(iter(shaders))
                    output = getattr(network, "getOutput", lambda: None)()
                    handle = getattr(output, "shader", None) if output else None
                    if handle:
                        try:
                            shader_name = network.getShader(handle).name
                        except Exception:
                            pass
            if accept(shader_name, _network_shaders(network) if network else {}):
                result.append(location)
        return result

    try:
        return _with_scene_context(node, _collect)
    except Exception:
        return []


class LightInsertMixin:
    """Unique naming, nested groups, create/edit overlay."""

    def _sync_active_nodes(self) -> None:
        """Enable only the internal nodes for the current type. Override me."""

    TYPE_PLUG = "lightType"
    NAME_TYPE_ALIASES: dict[str, str] = {}
    EXISTING_SHADER_DENY: frozenset[str] | None = None
    EXISTING_SHADER_ALLOW: frozenset[str] | None = None
    GRAPH_NAME_PREFIX = ""
    GRAPH_NAME_INCLUDE_PRIM = True

    def _internal_light_name(self, shader: str) -> str:
        return "__light_{}".format(shader)

    def _accept_existing_light(self, shader_name: str, shaders: dict) -> bool:
        del shaders
        if self.EXISTING_SHADER_ALLOW is not None:
            return shader_name in self.EXISTING_SHADER_ALLOW
        if self.EXISTING_SHADER_DENY is not None:
            return shader_name not in self.EXISTING_SHADER_DENY
        return True

    def existingLights(self) -> list[str]:
        return list_scene_lights(self, self._accept_existing_light)

    def _type_token(self) -> str:
        try:
            raw = (self[self.TYPE_PLUG].getValue() or "").strip()
        except Exception:
            raw = ""
        return prim_type_token(raw, getattr(self, "NAME_TYPE_ALIASES", None))

    def _migrate_legacy_name(self) -> None:
        try:
            name = (self["name"].getValue() or "").strip()
            prim_path = (self["primPath"].getValue() or "").strip()
        except Exception:
            return
        if prim_path or "/" not in name.strip("/"):
            return
        location = name if name.startswith("/") else "/" + name
        parent, leaf = split_location(location)
        if not leaf:
            return
        self["primPath"].setValue(parent)
        self["name"].setValue(leaf)

    def _used_leaf_names(self) -> set[str]:
        used: set[str] = set()
        try:
            prim_path = (self["primPath"].getValue() or "").strip()
            mode = self["mode"].getValue()
            edit_path = (self["editPath"].getValue() or "").strip()
        except Exception:
            prim_path = ""
            mode = MODE_CREATE
            edit_path = ""
        parent_key = join_path(path_parts(prim_path))
        script = self.scriptNode()
        root = script if script is not None else self.parent()
        if root is not None:
            stack: list[Gaffer.Node] = [root]
            seen: set[int] = set()
            while stack:
                node = stack.pop()
                ident = id(node)
                if ident in seen:
                    continue
                seen.add(ident)
                if isinstance(node, type(self)) and not node.isSame(self):
                    try:
                        other_parent = join_path(
                            path_parts(node["primPath"].getValue())
                        )
                        other_name = (node["name"].getValue() or "").strip()
                    except Exception:
                        other_parent = ""
                        other_name = ""
                    if other_name and other_parent == parent_key:
                        used.add(other_name)
                stack.extend(node.children(Gaffer.Node))
        if "in" in self and self["in"].getInput() is not None:
            parent_loc = parent_key if parent_key else "/"

            def _children():
                if parent_loc != "/" and not self["in"].exists(parent_loc):
                    return []
                return list(self["in"].childNames(parent_loc) or [])

            try:
                for child in _with_scene_context(self, _children):
                    used.add(str(child))
            except Exception:
                pass
        if mode == MODE_EDIT and edit_path:
            _parent, leaf = split_location(edit_path)
            if leaf:
                used.discard(leaf)
        return used

    def _editing(self) -> bool:
        try:
            return self["mode"].getValue() == MODE_EDIT
        except Exception:
            return False

    def _sync_edit_lock(self) -> None:
        """Name / label / path follow the selected light in Edit mode."""
        editing = self._editing()
        for plug_name in ("name", "label", "primPath"):
            if plug_name not in self:
                continue
            try:
                Gaffer.MetadataAlgo.setReadOnly(self[plug_name], editing)
            except Exception:
                pass

    def _restore_edit_identity(self) -> None:
        """Keep leaf name equal to the Edit menu selection."""
        if not self._editing():
            return
        if getattr(self, "_LightInsertMixin__loadingEdit", False):
            return
        try:
            edit_path = (self["editPath"].getValue() or "").strip()
        except Exception:
            return
        if not edit_path:
            return
        _parent, leaf = split_location(edit_path)
        if not leaf or "name" not in self:
            return
        try:
            if (self["name"].getValue() or "").strip() == leaf:
                return
        except Exception:
            return
        self.__loadingEdit = True
        try:
            self["name"].setValue(leaf)
        except Exception:
            pass
        finally:
            self.__loadingEdit = False

    def _assign_unique_prim_name(self) -> None:
        if getattr(self, "_LightInsertMixin__assigningName", False):
            return
        if getattr(self, "_LightInsertMixin__loadingEdit", False):
            return
        if self._editing():
            return
        if script_is_loading(self):
            return
        try:
            label = self["label"].getValue()
        except Exception:
            label = DEFAULT_LABEL
        type_token = self._type_token()
        try:
            current = (self["name"].getValue() or "").strip()
        except Exception:
            current = ""
        used = self._used_leaf_names()
        clean = sanitise_label(label)
        token = sanitise_type_token(type_token)
        if clean:
            indexed = re.compile(
                r"^"
                + re.escape(clean)
                + r"(\d+)_"
                + re.escape(token)
                + r"$",
                re.IGNORECASE,
            )
        else:
            indexed = re.compile(
                r"^" + re.escape(token) + r"(\d+)$", re.IGNORECASE
            )
        if current and indexed.match(current):
            taken = {u.lower() for u in used}
            if current.lower() not in taken:
                return
        unique = next_indexed_name(label, type_token, used)
        if unique == current:
            return
        self.__assigningName = True
        try:
            self["name"].setValue(unique)
        except Exception:
            pass
        finally:
            self.__assigningName = False
        self._sync_graph_node_name()

    def _desired_graph_name(self) -> str:
        prefix = getattr(self, "GRAPH_NAME_PREFIX", "") or ""
        if not prefix:
            return ""
        try:
            mode = self["mode"].getValue()
        except Exception:
            return ""
        if getattr(self, "GRAPH_NAME_INCLUDE_PRIM", True):
            try:
                prim = (self["name"].getValue() or "").strip().lstrip("/")
            except Exception:
                prim = ""
            if not prim:
                return ""
            name = "{}_{}".format(prefix, prim)
        else:
            name = prefix
        if mode == MODE_EDIT:
            name += "_edit"
        return sanitise_graph_name(name)

    def _sync_graph_node_name(self) -> None:
        if getattr(self, "_LightInsertMixin__assigningName", False):
            return
        if getattr(self, "_LightInsertMixin__syncingGraphName", False):
            return
        if getattr(self, "_LightInsertMixin__loadingEdit", False):
            return
        if script_is_loading(self):
            return
        if self.parent() is None:
            return
        desired = self._desired_graph_name()
        if not desired:
            return
        current = self.getName()
        if current == desired:
            return
        if re.match(r"^" + re.escape(desired) + r"\d+$", current):
            return
        self.__syncingGraphName = True
        try:
            self.setName(desired)
        except Exception:
            pass
        finally:
            self.__syncingGraphName = False

    def _load_edit_target(self, path: str) -> None:
        if getattr(self, "_LightInsertMixin__loadingEdit", False):
            return
        path = (path or "").strip()
        if not path or "in" not in self or self["in"].getInput() is None:
            return
        self.__loadingEdit = True
        try:
            parent, leaf = split_location(path)
            if leaf:
                self["name"].setValue(leaf)
            self["primPath"].setValue(parent)

            def _read():
                scene = self["in"]
                xform = scene.transform(path) if scene.exists(path) else None
                attrs = scene.attributes(path) if scene.exists(path) else None
                return xform, attrs

            matrix, attrs = _with_scene_context(self, _read)
            if matrix is not None and "transform" in self:
                apply_matrix_to_transform(self["transform"], matrix)
            shaders: dict[str, object] = {}
            output_name = ""
            if attrs is not None:
                _key, network = _shader_network(attrs)
                if network is not None:
                    shaders = _network_shaders(network)
                    output = getattr(network, "getOutput", lambda: None)()
                    handle = getattr(output, "shader", None) if output else None
                    if handle:
                        try:
                            output_name = network.getShader(handle).name
                        except Exception:
                            output_name = next(iter(shaders), "")
                    elif shaders:
                        output_name = next(iter(shaders))
            self._apply_loaded_shaders(output_name, shaders)
            token = self._type_token()
            if leaf:
                self["label"].setValue(parse_label_from_name(leaf, token))
        except Exception as exc:
            IECore.msg(
                IECore.Msg.Level.Warning,
                self.getName(),
                "Could not load light '{}' ({})".format(path, exc),
            )
        finally:
            self.__loadingEdit = False

    def _apply_loaded_shaders(self, output_name: str, shaders: dict) -> None:
        token = output_name
        child = self._internal_light_name(token) if token else ""
        if token and child in self and self.TYPE_PLUG in self:
            try:
                self[self.TYPE_PLUG].setValue(token)
            except Exception:
                pass
        for shader_name, shader in shaders.items():
            child = self._internal_light_name(shader_name)
            target = self[child] if child in self else None
            if target is None or "parameters" not in target:
                continue
            params = getattr(shader, "parameters", None)
            if not params:
                continue
            items = params.items() if hasattr(params, "items") else []
            for name, data in items:
                if name in target["parameters"]:
                    _set_plug_from_data(target["parameters"][name], data)

    def _bind_insert_signals(self) -> None:
        self.__assigningName = False
        self.__loadingEdit = False
        self.__syncingGraphName = False
        self.__syncingGroups = False
        self.__parentChangedConnection = self.parentChangedSignal().connect(
            Gaffer.WeakMethod(self._on_insert_parent_changed),
            scoped=True,
        )
        self.__plugInputChangedConnection = self.plugInputChangedSignal().connect(
            Gaffer.WeakMethod(self._on_insert_plug_input_changed),
            scoped=True,
        )
        self.__plugSetConnection = self.plugSetSignal().connect(
            Gaffer.WeakMethod(self._on_insert_plug_set),
            scoped=True,
        )
        self.__lastType = self._current_type()
        self._sync_edit_lock()
        self._sync_graph_icon()
        self._sync_driven_plugs()

    def _sync_driven_plugs(self) -> None:
        """Copy name / drawing / enabled into internal plugs. No live Expression."""
        sync_enabled_switch(self)
        leaf = "light"
        try:
            leaf = (self["name"].getValue() or "").strip() or "light"
        except Exception:
            pass
        path = leaf if str(leaf).startswith("/") else "/" + str(leaf)
        set_filter_paths(self, "__pathFilter", [path])
        gl_draw = self.getChild("__glDraw")
        if gl_draw is not None:
            mode = ""
            try:
                mode = (self["glDrawingMode"].getValue() or "").strip().lower()
            except Exception:
                mode = ""
            set_node_enabled(gl_draw, mode not in ("", "inherit", "default"))
            try:
                set_plug_value(
                    gl_draw["attributes"]["gl:light:drawingMode"]["value"],
                    mode if mode else "wireframe",
                )
            except Exception:
                pass
        if self.getChild("__meshFilter") is not None:
            prim = ""
            try:
                prim = (self["primPath"].getValue() or "").strip()
            except Exception:
                prim = ""
            set_filter_paths(self, "__meshFilter", parse_prim_paths(prim))

    def _sync_graph_icon(self) -> None:
        """Create vs Edit Graph Editor icon and colour. Instance metadata so the gadget refreshes."""
        editing = self._editing()
        create = getattr(self, "GRAPH_ICON", None)
        edit = getattr(self, "GRAPH_ICON_EDIT", None)
        icon = edit if edit and editing else create
        if icon:
            try:
                Gaffer.Metadata.registerValue(self, "icon", icon)
            except Exception:
                pass
        create_color = getattr(self, "GRAPH_COLOR", None)
        edit_color = getattr(self, "GRAPH_COLOR_EDIT", None)
        color = edit_color if edit_color is not None and editing else create_color
        if color is not None:
            try:
                Gaffer.Metadata.registerValue(self, "nodeGadget:color", color)
            except Exception:
                pass

    def _current_type(self) -> str:
        if self.TYPE_PLUG not in self:
            return ""
        try:
            return (self[self.TYPE_PLUG].getValue() or "").strip()
        except Exception:
            return ""

    def _on_type_changed(self, previous: str, current: str) -> None:
        """Retain overlapping shader parameters when the light type changes."""
        del previous, current

    def _group_prim_path(self) -> str:
        try:
            return (self["primPath"].getValue() or "").strip()
        except Exception:
            return ""

    def _group_chain_source(self):
        gl_draw = self.getChild("__glDraw")
        if gl_draw is not None and "out" in gl_draw:
            return gl_draw["out"]
        return None

    def _group_chain_sink(self):
        merge = self.getChild("__mergeScene")
        if merge is None or "in" not in merge:
            return None
        try:
            children = list(merge["in"].children())
        except Exception:
            return None
        if len(children) > 1:
            return children[1]
        return None

    def _group_chain_extra_sources(self) -> list:
        """Scene plugs parented into the innermost Prim Path group."""
        return []

    def _sync_ungrouped_overlays(self, has_groups: bool) -> None:
        """When Prim Path has no groups, extras overlay at the merge instead."""
        merge = self.getChild("__mergeScene")
        if merge is None or "in" not in merge:
            return
        extras = []
        if not has_groups:
            extras = [
                src for src in (self._group_chain_extra_sources() or []) if src is not None
            ]
        try:
            children = list(merge["in"].children())
        except Exception:
            return
        needed = 2 + len(extras)
        try:
            if len(children) < needed:
                merge["in"].resize(needed)
                children = list(merge["in"].children())
        except Exception:
            pass
        for index, child in enumerate(children):
            if index < 2:
                continue
            src = extras[index - 2] if index - 2 < len(extras) else None
            try:
                current = child.getInput()
                if src is None:
                    if current is not None:
                        child.setInput(None)
                elif current is None or not current.isSame(src):
                    child.setInput(src)
            except Exception:
                pass

    def _sync_groups(self) -> None:
        """Create only the Group nodes the current prim path needs (max 4)."""
        if getattr(self, "_LightInsertMixin__syncingGroups", False):
            return
        source = self._group_chain_source()
        if source is None:
            return
        self.__syncingGroups = True
        try:
            path = self._group_prim_path()
            parts = path_parts(path)
            if len(parts) > MAX_GROUPS and "primPath" in self:
                truncated = join_path(parts[:MAX_GROUPS])
                try:
                    current = join_path(path_parts(self["primPath"].getValue()))
                except Exception:
                    current = ""
                if current != truncated:
                    try:
                        self["primPath"].setValue(truncated)
                    except Exception:
                        pass
                path = truncated
            extras = self._group_chain_extra_sources()
            sync_group_chain(
                self,
                source,
                self._group_chain_sink(),
                path=path,
                extra_sources=extras,
            )
            self._sync_ungrouped_overlays(bool(wanted_group_names(path)))
        finally:
            self.__syncingGroups = False

    def _on_insert_parent_changed(self, *_args) -> None:
        if self.parent() is None:
            return
        if script_is_loading(self):
            script = self.scriptNode()
            if (
                script is not None
                and hasattr(script, "scriptLoadedSignal")
                and not getattr(self, "_LightInsertMixin__loadedConn", None)
            ):
                self.__loadedConn = script.scriptLoadedSignal().connect(
                    Gaffer.WeakMethod(self._on_script_loaded),
                    scoped=True,
                )
            return
        self._migrate_legacy_name()
        self._sync_edit_lock()
        self._sync_graph_icon()
        self._assign_unique_prim_name()
        self._sync_graph_node_name()
        self._sync_active_nodes()
        self._sync_groups()
        self._sync_driven_plugs()

    def _on_script_loaded(self, *_args) -> None:
        self._migrate_legacy_name()
        self._sync_edit_lock()
        self._sync_graph_icon()
        self.__lastType = self._current_type()
        self._sync_active_nodes()
        self._sync_groups()
        self._sync_driven_plugs()

    def _on_insert_plug_input_changed(self, plug: Gaffer.Plug) -> None:
        if plug.getName() != "in":
            return
        self._assign_unique_prim_name()

    def _on_insert_plug_set(self, plug: Gaffer.Plug) -> None:
        name = plug.getName()
        if name == self.TYPE_PLUG:
            current = self._current_type()
            previous = getattr(self, "_LightInsertMixin__lastType", "") or ""
            loading = script_is_loading(self) or getattr(
                self, "_LightInsertMixin__loadingEdit", False
            )
            if not loading and previous and current and current != previous:
                self._on_type_changed(previous, current)
            self.__lastType = current
            self._sync_active_nodes()
        if name == "mode":
            self._sync_graph_icon()
        if name in ("enabled", "name", "glDrawingMode", "primPath"):
            self._sync_driven_plugs()
        if script_is_loading(self):
            return
        if name == "mode":
            self._sync_edit_lock()
            if self._editing():
                try:
                    path = (self["editPath"].getValue() or "").strip()
                except Exception:
                    path = ""
                if path:
                    self._load_edit_target(path)
                    self._sync_graph_node_name()
                    return
            self._assign_unique_prim_name()
            return
        if name in ("label", self.TYPE_PLUG, "primPath"):
            self._assign_unique_prim_name()
        if name in ("primPath", self.TYPE_PLUG):
            self._sync_groups()
        if name == "name" and self._editing():
            self._restore_edit_identity()
        if name in ("label", self.TYPE_PLUG, "name"):
            self._sync_graph_node_name()
        if name == "editPath" and not getattr(
            self, "_LightInsertMixin__loadingEdit", False
        ):
            try:
                if self._editing():
                    self._load_edit_target(plug.getValue())
                    self._sync_graph_node_name()
            except Exception:
                pass
