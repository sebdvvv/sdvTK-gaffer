"""Copy / paste / reset of public shading plugs."""

from __future__ import annotations

import Gaffer

_SKIP = frozenset(
    {
        "in",
        "out",
        "enabled",
        "user",
        "presetFolder",
        "editLoaded",
        "samplingEditLoaded",
    }
)


def snapshot(node: Gaffer.Node) -> dict:
    return {"kind": type(node).__name__, "values": _collect(node)}


def apply_snapshot(node: Gaffer.Node, data: dict | None, reload=None) -> int:
    if not isinstance(data, dict):
        return 0
    if data.get("kind") != type(node).__name__:
        return 0
    values = data.get("values")
    if not isinstance(values, dict):
        return 0
    public = {key: value for key, value in values.items() if not key.startswith("__")}
    internal = {key: value for key, value in values.items() if key.startswith("__")}
    applied = _apply(node, public)
    if callable(reload):
        reload()
    applied += _apply(node, internal)
    return applied


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
    for path, value in values.items():
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
        if name in _SKIP or name.startswith("__"):
            continue
        if plug.direction() != Gaffer.Plug.Direction.In:
            continue
        yield plug, name
    for child in node.children(Gaffer.Node):
        name = child.getName()
        if not name.startswith(("__shader", "__texture", "__dispMap", "__displacement")):
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
    if not callable(getter):
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
