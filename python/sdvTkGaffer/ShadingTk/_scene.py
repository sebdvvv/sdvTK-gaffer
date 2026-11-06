"""Read surface shaders from the incoming scene (Edit mode)."""

from __future__ import annotations

from typing import Any, Callable

from ._data import EDIT_SCOPE

SURFACE_ATTRS = (
    "ai:surface",
    "arnold:surface",
    "surface",
    "osl:shader",
    "os:surface",
    "render:surface",
    "ri:surface",
)
_SKIP_SHADER_SUFFIXES = ("_light",)
_MAX_VISIT = 8000


def acquire_parameter_edit(
    scope, path: str, attr: str, handle: str, parameter: str, *, create: bool = True
):
    """``("", parameter)`` is the network output shader (Gaffer convention)."""
    import GafferScene

    def _one(shader_handle):
        return GafferScene.EditScopeAlgo.acquireParameterEdit(
            scope,
            path,
            attr,
            (shader_handle, parameter),
            createIfNecessary=create,
        )

    handles = [""]
    if handle and handle not in handles:
        handles.append(handle)
    last_error = None
    for shader_handle in handles:
        try:
            tweak = _one(shader_handle)
        except Exception as exc:
            last_error = exc
            continue
        if tweak is not None:
            return tweak
    if last_error is not None and create:
        raise last_error
    return None


def resolve_edit_scope(node):
    """Internal ``__shaderEdits`` first, then an ``editScope`` input if present."""
    try:
        import Gaffer
    except Exception:
        return None
    child = node.getChild(EDIT_SCOPE) if hasattr(node, "getChild") else None
    if isinstance(child, Gaffer.EditScope):
        return child
    plug = node.getChild("editScope") if hasattr(node, "getChild") else None
    if plug is None:
        return None

    def _as_scope(source):
        if source is None:
            return None
        try:
            owner = source.node()
        except Exception:
            return None
        if isinstance(owner, Gaffer.EditScope):
            return owner
        return None

    try:
        found = Gaffer.PlugAlgo.findSource(plug, _as_scope)
        if found is not None:
            return found
    except Exception:
        pass
    try:
        return _as_scope(plug.getInput())
    except Exception:
        return None


def has_scene_input(node) -> bool:
    if "in" not in node:
        return False
    try:
        return node["in"].getInput() is not None
    except Exception:
        return False


def with_scene_context(node, fn: Callable):
    script = node.scriptNode()
    context = script.context() if script is not None else None
    if context is not None:
        with context:
            return fn()
    return fn()


def shader_network(attrs) -> tuple[str | None, Any]:
    if attrs is None:
        return None, None
    try:
        import IECoreScene
    except Exception:
        IECoreScene = None
    preferred = None
    fallback = None
    for key in attrs.keys():
        try:
            value = attrs[key]
        except Exception:
            continue
        type_name = value.__class__.__name__
        is_network = type_name == "ShaderNetwork" or (
            IECoreScene is not None
            and isinstance(value, IECoreScene.ShaderNetwork)
        )
        if not is_network:
            continue
        item = (str(key), value)
        if str(key) in SURFACE_ATTRS:
            preferred = item
            break
        if fallback is None:
            fallback = item
    if preferred is not None:
        return preferred
    return fallback if fallback is not None else (None, None)


def network_output_handle(network) -> str:
    if network is None:
        return ""
    get_output = getattr(network, "getOutput", None)
    if not callable(get_output):
        return ""
    try:
        output = get_output()
        handle = getattr(output, "shader", None)
        return str(handle or "")
    except Exception:
        return ""


def shader_type_name(shader) -> str:
    """IECore Shader.name — the type / Value column (e.g. standard_surface)."""
    if shader is None:
        return ""
    getter = getattr(shader, "getName", None)
    if callable(getter):
        try:
            return str(getter() or "")
        except Exception:
            pass
    return str(getattr(shader, "name", "") or "")


def network_output_shader(network) -> tuple[str, Any]:
    """``(shader type, shader)`` for the network output."""
    if network is None:
        return "", None
    get_output = getattr(network, "getOutput", None)
    get_shader = getattr(network, "getShader", None)
    if callable(get_output) and callable(get_shader):
        try:
            output = get_output()
            handle = getattr(output, "shader", None)
            if handle:
                shader = get_shader(handle)
                return shader_type_name(shader) or str(handle), shader
        except Exception:
            pass
    shaders = network_shaders(network)
    if not shaders:
        return "", None
    handle = next(iter(shaders))
    shader = shaders[handle]
    return shader_type_name(shader) or handle, shader


def network_shaders(network) -> dict[str, Any]:
    found: dict[str, Any] = {}
    shaders_fn = getattr(network, "shaders", None)
    if callable(shaders_fn):
        try:
            data = shaders_fn()
            if isinstance(data, dict):
                for handle, shader in data.items():
                    found[str(handle)] = shader
                return found
        except Exception:
            pass
    handle = network_output_handle(network)
    get_shader = getattr(network, "getShader", None)
    if handle and callable(get_shader):
        try:
            shader = get_shader(handle)
        except Exception:
            shader = None
        if shader is not None:
            found[handle] = shader
    return found


def is_surface_shader(name: str) -> bool:
    text = (name or "").strip()
    if not text:
        return False
    lower = text.lower()
    for suffix in _SKIP_SHADER_SUFFIXES:
        if lower.endswith(suffix):
            return False
    return True


def set_plug_from_data(plug, data) -> bool:
    value = data.value if hasattr(data, "value") else data
    try:
        plug.setValue(value)
        return True
    except Exception:
        pass
    if hasattr(value, "value"):
        try:
            plug.setValue(value.value)
            return True
        except Exception:
            pass
    return False


_PARAM_ORDER_CACHE: dict[str, tuple[str, ...]] = {}


def shader_parameter_names(shader) -> list[str]:
    if shader is None:
        return []
    params = getattr(shader, "parameters", None)
    if not params or not hasattr(params, "keys"):
        return []
    names = []
    for name in params.keys():
        text = str(name)
        if not text or text.startswith("__"):
            continue
        names.append(text)
    order = _shader_definition_parameter_order(shader)
    if not order:
        return names
    rank = {name: index for index, name in enumerate(order)}
    names.sort(
        key=lambda name: (0, rank[name]) if name in rank else (1, name.lower())
    )
    return names


def _shader_definition_parameter_order(shader) -> tuple[str, ...]:
    """Plug order from a loaded shader node — same as create-mode attributes."""
    shader_type = shader_type_name(shader)
    if not shader_type:
        return ()
    cached = _PARAM_ORDER_CACHE.get(shader_type)
    if cached is not None:
        return cached
    order = _load_shader_parameter_order(shader_type)
    _PARAM_ORDER_CACHE[shader_type] = order
    return order


def _load_shader_parameter_order(shader_type: str) -> tuple[str, ...]:
    node = _reference_shader_node(shader_type)
    if node is None or "parameters" not in node:
        return ()
    names = []
    try:
        plugs = node["parameters"].children()
    except Exception:
        return ()
    for plug in plugs:
        try:
            name = plug.getName()
        except Exception:
            continue
        if not name or name.startswith("__"):
            continue
        names.append(name)
    return tuple(names)


def _reference_shader_node(shader_type: str):
    try:
        import GafferArnold

        node = GafferArnold.ArnoldShader("_shadingTkParamOrder")
        node.loadShader(shader_type)
        return node
    except Exception:
        pass
    try:
        import GafferOSL

        node = GafferOSL.OSLShader("_shadingTkParamOrder")
        node.loadShader(shader_type)
        return node
    except Exception:
        return None


def apply_shader_parameters(target, shader) -> int:
    if target is None or "parameters" not in target or shader is None:
        return 0
    params = getattr(shader, "parameters", None)
    if not params or not hasattr(params, "items"):
        return 0
    applied = 0
    dest = target["parameters"]
    for name, data in params.items():
        if name not in dest:
            continue
        if set_plug_from_data(dest[name], data):
            applied += 1
    return applied


def iter_shader_networks(attrs):
    if attrs is None:
        return
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
        is_network = type_name == "ShaderNetwork" or (
            IECoreScene is not None
            and isinstance(value, IECoreScene.ShaderNetwork)
        )
        if is_network:
            yield str(key), value


def _parent_path(path: str) -> str | None:
    if path in ("", "/"):
        return None
    parent = path.rsplit("/", 1)[0]
    return parent if parent else "/"


def _inherited_surface(scene, path: str, attr: str, network) -> bool:
    parent = _parent_path(path)
    if parent is None:
        return False
    try:
        parent_attrs = scene.attributes(parent)
    except Exception:
        return False
    if parent_attrs is None or attr not in parent_attrs:
        return False
    handle = network_output_handle(network)
    parent_handle = network_output_handle(parent_attrs[attr])
    return bool(handle) and handle == parent_handle


def _shader_hit(scene, path: str, attr: str, network) -> dict | None:
    shader_type, shader = network_output_shader(network)
    handle = network_output_handle(network) or shader_type
    if not handle or not is_surface_shader(shader_type or handle):
        return None
    return {
        "path": path,
        "paths": [path],
        "shader": handle,
        "type": shader_type,
        "attr": attr,
        "handle": handle,
        "object": _has_object(scene, path),
    }


def _merge_hit(found: dict, hit: dict) -> None:
    handle = hit["handle"]
    existing = found.get(handle)
    if existing is None:
        found[handle] = hit
        return
    existing["paths"].append(hit["path"])
    if existing.get("object") and not hit.get("object"):
        existing["path"] = hit["path"]
        existing["object"] = False
        existing["attr"] = hit["attr"]
        existing["type"] = hit["type"]


def _has_object(scene, path: str) -> bool:
    try:
        obj = scene.object(path)
    except Exception:
        return False
    if obj is None:
        return False
    type_name = obj.typeName() if hasattr(obj, "typeName") else type(obj).__name__
    return type_name not in ("NullObject",)


def list_existing_shaders(node) -> list[dict]:
    """Authoring locations of surface shaders on ``in`` (not inherited mesh hits)."""
    if not has_scene_input(node):
        return []

    def _collect() -> list[dict]:
        scene = node["in"]
        found: dict[str, dict] = {}
        visits = [0]

        def visit(path: str) -> None:
            if visits[0] >= _MAX_VISIT or len(found) >= _MAX_VISIT:
                return
            visits[0] += 1
            try:
                if path != "/" and not scene.exists(path):
                    return
            except Exception:
                return
            try:
                attrs = scene.attributes(path)
            except Exception:
                attrs = None
            attr, network = shader_network(attrs)
            if (
                attr
                and network is not None
                and not _inherited_surface(scene, path, attr, network)
            ):
                hit = _shader_hit(scene, path, attr, network)
                if hit is not None:
                    _merge_hit(found, hit)
            try:
                children = list(scene.childNames(path) or [])
            except Exception:
                children = []
            for child in children:
                leaf = str(child)
                if path == "/":
                    visit("/" + leaf)
                else:
                    visit(path + "/" + leaf)

        visit("/")
        items = list(found.values())
        items.sort(
            key=lambda item: (
                item["shader"].lower(),
                item.get("type") or "",
                item["path"],
            )
        )
        return items

    try:
        return with_scene_context(node, _collect)
    except Exception:
        return []


def list_sampling_shaders(node) -> list[dict]:
    """Locations whose shader networks expose sample-like parameters."""
    if not has_scene_input(node):
        return []
    from ._sampling import sample_param_names

    def _collect() -> list[dict]:
        scene = node["in"]
        found: list[dict] = []
        visits = [0]

        def visit(path: str) -> None:
            if visits[0] >= _MAX_VISIT or len(found) >= _MAX_VISIT:
                return
            visits[0] += 1
            try:
                if path != "/" and not scene.exists(path):
                    return
            except Exception:
                return
            try:
                attrs = scene.attributes(path)
            except Exception:
                attrs = None
            for attr, network in iter_shader_networks(attrs):
                shader_type, shader = network_output_shader(network)
                handle = network_output_handle(network) or shader_type
                params = sample_param_names(shader)
                if handle and params:
                    found.append(
                        {
                            "path": path,
                            "shader": handle,
                            "type": shader_type,
                            "attr": attr,
                            "params": params,
                        }
                    )
            try:
                children = list(scene.childNames(path) or [])
            except Exception:
                children = []
            for child in children:
                leaf = str(child)
                if path == "/":
                    visit("/" + leaf)
                else:
                    visit(path + "/" + leaf)

        visit("/")
        found.sort(key=lambda item: (item["shader"].lower(), item["path"]))
        return found

    try:
        return with_scene_context(node, _collect)
    except Exception:
        return []


def read_location_sampling_shader(node, path: str) -> tuple[str, Any, list[str]]:
    path = (path or "").strip()
    if not path or not has_scene_input(node):
        return "", None, []
    from ._sampling import sample_param_names

    def _read():
        scene = node["in"]
        if not scene.exists(path):
            return "", None, []
        attrs = scene.attributes(path)
        for _attr, network in iter_shader_networks(attrs):
            shader_type, shader = network_output_shader(network)
            handle = network_output_handle(network) or shader_type
            params = sample_param_names(shader)
            if handle and params:
                return handle, shader, params
        return "", None, []

    try:
        return with_scene_context(node, _read)
    except Exception:
        return "", None, []


def read_location_shader(node, path: str) -> tuple[str, Any]:
    handle, shader, _attr, _shader_type = read_location_shader_edit(node, path)
    return handle, shader


def _child_path(path: str, child: Any) -> str:
    leaf = str(child)
    if path == "/":
        return "/" + leaf
    return path + "/" + leaf


def _network_contains_handle(network, handle: str) -> bool:
    handle = (handle or "").strip()
    if not handle or network is None:
        return False
    if network_output_handle(network) == handle:
        return True
    return handle in network_shaders(network)


def locations_bound_to_shader(scene, handle: str, limit: int = 4000) -> tuple[list[str], bool]:
    """Locations where ``handle`` is the effective shader.

    Includes the prim the shader is authored on and leaf prims that inherit
    it (the meshes under that assignment). ``limit`` stops a ``...`` assignment
    from selecting the whole stage. The second value is True when the walk
    stopped early.
    """
    handle = (handle or "").strip()
    if not handle or scene is None:
        return [], False
    found: list[str] = []
    seen: set[str] = set()
    visits = [0]
    truncated = [False]

    def add(path: str) -> None:
        if not path or path == "/" or path in seen:
            return
        if len(found) >= limit:
            truncated[0] = True
            return
        seen.add(path)
        found.append(path)

    def visit(path: str, inherited: dict[str, bool]) -> None:
        if visits[0] >= _MAX_VISIT or truncated[0]:
            if visits[0] >= _MAX_VISIT:
                truncated[0] = True
            return
        visits[0] += 1
        try:
            if path != "/" and not scene.exists(path):
                return
        except Exception:
            return
        local: dict[str, bool] = {}
        try:
            attrs = scene.attributes(path)
        except Exception:
            attrs = None
        if attrs is not None:
            for attr, network in iter_shader_networks(attrs):
                local[attr] = _network_contains_handle(network, handle)
        effective = dict(inherited)
        effective.update(local)
        bound = any(effective.values())
        authors = any(local.values())
        try:
            children = list(scene.childNames(path) or [])
        except Exception:
            children = []
        if bound and (authors or not children):
            add(path)
        if truncated[0]:
            return
        for child in children:
            visit(_child_path(path, child), effective)

    visit("/", {})
    return found, truncated[0]


def _full_attributes(scene, path: str):
    full = getattr(scene, "fullAttributes", None)
    if not callable(full):
        return None
    try:
        return full(path)
    except Exception:
        return None


def _effective_networks(scene, path: str) -> list[tuple[str, Any]]:
    """Shader networks at ``path``, including ones inherited from parents."""
    attrs = _full_attributes(scene, path)
    if attrs is not None:
        return list(iter_shader_networks(attrs))
    chain: list[str] = []
    current = path or "/"
    guard = 0
    while current and guard < 256:
        chain.append(current)
        if current == "/":
            break
        parent = current.rsplit("/", 1)[0]
        current = parent if parent else "/"
        guard += 1
    by_attr: dict[str, Any] = {}
    for item in reversed(chain):
        try:
            attrs = scene.attributes(item)
        except Exception:
            attrs = None
        if attrs is None:
            continue
        for attr, network in iter_shader_networks(attrs):
            by_attr[attr] = network
    return list(by_attr.items())


def assigned_shader_handles(scene, paths: list[str]) -> list[str]:
    """Output shader handles effective at ``paths`` (surface first)."""
    if scene is None:
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in paths or []:
        path = str(raw or "").strip()
        if not path:
            continue
        surface: list[str] = []
        other: list[str] = []
        for attr, network in _effective_networks(scene, path):
            handle = network_output_handle(network)
            if not handle:
                continue
            if attr in SURFACE_ATTRS:
                surface.append(handle)
            else:
                other.append(handle)
        for handle in surface + other:
            if handle in seen:
                continue
            seen.add(handle)
            ordered.append(handle)
    return ordered


def read_location_shader_edit(node, path: str) -> tuple[str, Any, str, str]:
    """``handle (Name), shader, attribute, type (Value)`` at ``path``."""
    path = (path or "").strip()
    if not path or not has_scene_input(node):
        return "", None, "", ""

    def _read():
        scene = node["in"]
        if not scene.exists(path):
            return "", None, "", ""
        attr, network = shader_network(scene.attributes(path))
        shader_type, shader = network_output_shader(network)
        handle = network_output_handle(network) or shader_type
        return handle, shader, attr or "", shader_type

    try:
        return with_scene_context(node, _read)
    except Exception:
        return "", None, "", ""
