"""Copy / paste / reset of public plugs and internal shader parameters.

Identity (prim name, path, mode, connections) is left alone so a look can
move between env lights without replacing the destination in the scene.
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

_INTERNAL_PREFIXES = ("__light", "__shader_")
_LIGHT_EXTRA_PLUGS = ("defaultLight", "mute", "sets", "visualiserAttributes")


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
        if "parameters" in child:
            for plug in child["parameters"].children():
                if plug.getName().startswith("__"):
                    continue
                if plug.direction() != Gaffer.Plug.Direction.In:
                    continue
                yield plug, "{}.parameters.{}".format(name, plug.getName())
        if name.startswith("__light"):
            for extra in _LIGHT_EXTRA_PLUGS:
                if extra in child:
                    yield child[extra], "{}.{}".format(name, extra)


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
