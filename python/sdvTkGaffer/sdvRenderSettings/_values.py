"""Copy / paste / reset of public plugs and renderer options/attributes."""

from __future__ import annotations

import Gaffer

from ._data import (
    ENGINE_ORDER,
    INTERNAL_STANDARD_OPTIONS,
    internal_attributes,
    internal_options,
)
from ._presets import apply_name_values, snapshot_name_values

_SKIP = frozenset({"in", "out", "enabled", "user", "presetFolder", "renderEngine"})


def snapshot(node: Gaffer.Node) -> dict:
    return {
        "kind": type(node).__name__,
        "values": _collect_public(node),
        "options": _collect_settings(node, options=True),
        "attributes": _collect_settings(node, options=False),
        "standard": _collect_standard(node),
    }


def apply_snapshot(node: Gaffer.Node, data: dict | None, ensure=None) -> int:
    if not isinstance(data, dict):
        return 0
    if data.get("kind") != type(node).__name__:
        return 0
    applied = _apply_public(node, data.get("values") or {})
    if callable(ensure):
        ensure()
    applied += _apply_settings(node, data.get("options") or {}, options=True)
    applied += _apply_settings(node, data.get("attributes") or {}, options=False)
    applied += _apply_standard(node, data.get("standard") or {})
    return applied


def reset_values(node: Gaffer.Node) -> None:
    standard = node.getChild(INTERNAL_STANDARD_OPTIONS)
    if standard is not None and "options" in standard:
        _reset_plug(standard["options"])
    for engine in ENGINE_ORDER:
        child = node.getChild(internal_options(engine))
        if child is not None and "options" in child:
            _reset_plug(child["options"])
        for index in range(1, 9):
            attr = node.getChild(internal_attributes(engine, index))
            if attr is not None and "attributes" in attr:
                _reset_plug(attr["attributes"])
    for name in ("background", "backgroundColor"):
        plug = node.getChild(name)
        if plug is not None:
            _reset_plug(plug)


def _collect_standard(node: Gaffer.Node) -> dict:
    child = node.getChild(INTERNAL_STANDARD_OPTIONS)
    if child is None or "options" not in child:
        return {}
    return snapshot_name_values(child["options"])


def _apply_standard(node: Gaffer.Node, data: dict) -> int:
    if not isinstance(data, dict) or not data:
        return 0
    child = node.getChild(INTERNAL_STANDARD_OPTIONS)
    if child is None or "options" not in child:
        return 0
    return apply_name_values(child["options"], data)


def _collect_public(node: Gaffer.Node) -> dict:
    values: dict[str, object] = {}
    for plug, path in _public_plugs(node):
        _store_plug(plug, path, values)
    return values


def _collect_settings(node: Gaffer.Node, *, options: bool) -> dict:
    result: dict[str, dict] = {}
    for engine in ENGINE_ORDER:
        if options:
            child = node.getChild(internal_options(engine))
            if child is None or "options" not in child:
                continue
            result[engine] = snapshot_name_values(child["options"])
            continue
        slots: dict[str, dict] = {}
        for index in range(1, 9):
            child = node.getChild(internal_attributes(engine, index))
            if child is None or "attributes" not in child:
                continue
            slots[str(index)] = snapshot_name_values(child["attributes"])
        if slots:
            result[engine] = slots
    return result


def _apply_public(node: Gaffer.Node, values: dict) -> int:
    applied = 0
    if not isinstance(values, dict):
        return 0
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


def _apply_settings(node: Gaffer.Node, data: dict, *, options: bool) -> int:
    if not isinstance(data, dict):
        return 0
    applied = 0
    for engine, payload in data.items():
        if options:
            child = node.getChild(internal_options(engine))
            if child is None or "options" not in child:
                continue
            applied += apply_name_values(child["options"], payload)
            continue
        if not isinstance(payload, dict):
            continue
        for index, values in payload.items():
            try:
                slot = int(index)
            except (TypeError, ValueError):
                continue
            child = node.getChild(internal_attributes(engine, slot))
            if child is None or "attributes" not in child:
                continue
            applied += apply_name_values(child["attributes"], values)
    return applied


def _public_plugs(node: Gaffer.Node):
    for plug in node.children(Gaffer.Plug):
        name = plug.getName()
        if name in _SKIP or name.startswith("__"):
            continue
        if plug.direction() != Gaffer.Plug.Direction.In:
            continue
        yield plug, name


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
