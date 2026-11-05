"""Copy / paste / reset of public plugs and internal shader parameters.

Identity (prim name, path, mode, connections) is left alone so a look can
move between lights without replacing the destination in the scene.
"""

from __future__ import annotations

import Gaffer

# Scene placement and graph identity — not part of a look preset.
_IDENTITY_PLUGS = frozenset(
    {
        "in",
        "out",
        "enabled",
        "mode",
        "name",
        "primPath",
        "editPath",
        "label",
        "user",
    }
)

_INTERNAL_PREFIXES = ("__light", "__shader_", "__gobo")


def snapshot(node: Gaffer.Node) -> dict:
    return {"kind": type(node).__name__, "values": _collect(node)}


def apply_snapshot(node: Gaffer.Node, data: dict | None) -> int:
    if not isinstance(data, dict):
        return 0
    if data.get("kind") != type(node).__name__:
        return 0
    values = data.get("values")
    if not isinstance(values, dict):
        return 0
    return _apply(node, values)


def reset_values(node: Gaffer.Node) -> None:
    for plug, _path in _editable_plugs(node):
        _reset_plug(plug)


def transfer_parameters(node: Gaffer.Node, from_shader: str, to_shader: str) -> int:
    """Copy every matching shader parameter from one internal light to another.

    Used when ``lightType`` (or ``skyType``) changes so shared look values
    (color, exposure, contribution, …) survive the switch. Type-only plugs
    stay on the source light and are left alone on the destination.
    """
    if not from_shader or not to_shader or from_shader == to_shader:
        return 0
    internal = getattr(node, "_internal_light_name", None)
    if not callable(internal):
        return 0
    src_name = internal(from_shader)
    dst_name = internal(to_shader)
    if src_name not in node or dst_name not in node:
        return 0
    src = node[src_name]
    dst = node[dst_name]
    if "parameters" not in src or "parameters" not in dst:
        return 0
    return _copy_matching_plugs(src["parameters"], dst["parameters"])


def _collect(node: Gaffer.Node) -> dict:
    values: dict[str, object] = {}
    for plug, path in _editable_plugs(node):
        _store_plug(plug, path, values)
    return values


def _apply(node: Gaffer.Node, values: dict) -> int:
    applied = 0
    items = sorted(
        values.items(),
        key=lambda item: (0 if item[0] in ("lightType", "skyType") else 1, item[0]),
    )
    for path, value in items:
        plug = _plug_at(node, path)
        if plug is None or plug.getInput() is not None:
            continue
        setter = getattr(plug, "setValue", None)
        if not callable(setter):
            continue
        try:
            setter(value)
            applied += 1
        except Exception:
            pass
    return applied


def _editable_plugs(node: Gaffer.Node):
    for plug in node.children(Gaffer.Plug):
        name = plug.getName()
        if name in _IDENTITY_PLUGS or name.startswith("__"):
            continue
        if plug.direction() != Gaffer.Plug.Direction.In:
            continue
        yield plug, name
    for child in node.children(Gaffer.Node):
        name = child.getName()
        if not name.startswith(_INTERNAL_PREFIXES):
            continue
        if "parameters" not in child:
            continue
        for plug in child["parameters"].children():
            if plug.getName().startswith("__"):
                continue
            if plug.direction() != Gaffer.Plug.Direction.In:
                continue
            yield plug, "{}.parameters.{}".format(name, plug.getName())


def _store_plug(plug: Gaffer.Plug, path: str, values: dict) -> None:
    if plug.getInput() is not None:
        return
    getter = getattr(plug, "getValue", None)
    # TransformPlug is a ValuePlug whose getValue is the full matrix;
    # store translate/rotate/scale so paste matches the Node Editor.
    if isinstance(plug, Gaffer.TransformPlug) or not callable(getter):
        for child in plug.children():
            if isinstance(child, Gaffer.Plug):
                _store_plug(child, path + "." + child.getName(), values)
        return
    try:
        values[path] = getter()
    except Exception:
        for child in plug.children():
            if isinstance(child, Gaffer.Plug):
                _store_plug(child, path + "." + child.getName(), values)


def _copy_matching_plugs(src: Gaffer.Plug, dst: Gaffer.Plug) -> int:
    copied = 0
    for child in src.children():
        name = child.getName()
        if name.startswith("__") or name not in dst:
            continue
        copied += _copy_plug_value(child, dst[name])
    return copied


def _copy_plug_value(src: Gaffer.Plug, dst: Gaffer.Plug) -> int:
    if dst.getInput() is not None:
        return 0
    if dst.direction() != Gaffer.Plug.Direction.In:
        return 0
    getter = getattr(src, "getValue", None)
    setter = getattr(dst, "setValue", None)
    if callable(getter) and callable(setter) and not isinstance(
        src, Gaffer.TransformPlug
    ):
        try:
            value = getter()
        except Exception:
            value = None
        else:
            try:
                if dst.getValue() == value:
                    return 0
            except Exception:
                pass
            try:
                setter(value)
                return 1
            except Exception:
                pass
    return _copy_matching_plugs(src, dst)


def _reset_plug(plug: Gaffer.Plug) -> None:
    if plug.getInput() is not None:
        return
    reset = getattr(plug, "setToDefault", None)
    if callable(reset):
        try:
            reset()
            return
        except Exception:
            pass
    for child in plug.children():
        if isinstance(child, Gaffer.Plug):
            _reset_plug(child)


def _plug_at(node: Gaffer.Node, path: str):
    current = node
    for part in path.split("."):
        try:
            current = current[part]
        except Exception:
            return None
    return current
