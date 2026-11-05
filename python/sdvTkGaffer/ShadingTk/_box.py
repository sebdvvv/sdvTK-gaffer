"""Enabled passthrough, Graph Editor insert, and Box serialisation."""

from __future__ import annotations

import Gaffer
import GafferScene
import IECore

ENABLED_SWITCH = "__enabledSwitch"


def add_enabled_plug(node: Gaffer.Node) -> Gaffer.BoolPlug:
    if "enabled" not in node:
        node.addChild(
            Gaffer.BoolPlug("enabled", Gaffer.Plug.Direction.In, True)
        )
    return node["enabled"]


def add_enabled_switch(
    node: Gaffer.Node,
    processed_out: Gaffer.Plug,
    in_plug: Gaffer.Plug | None = None,
    *,
    passthrough: bool = True,
) -> Gaffer.Switch:
    """Switch: ``in`` when disabled, *processed_out* when enabled."""
    add_enabled_plug(node)
    switch = Gaffer.Switch(ENABLED_SWITCH)
    node.addChild(switch)
    switch.setup(GafferScene.ScenePlug("in"))
    switch["in"].resize(2)
    if passthrough:
        in_plug = in_plug if in_plug is not None else node["in"]
        switch["in"][0].setInput(in_plug)
    switch["in"][1].setInput(processed_out)
    return switch


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


def set_switch_index(parent: Gaffer.Node, name: str, index: int) -> None:
    switch = parent.getChild(name)
    if switch is None or "index" not in switch:
        return
    set_plug_value(switch["index"], int(index))


def sync_enabled_switch(node: Gaffer.Node) -> None:
    enabled = True
    try:
        enabled = bool(node["enabled"].getValue())
    except Exception:
        pass
    set_switch_index(node, ENABLED_SWITCH, 1 if enabled else 0)


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


def persist_internal_shader_node(child: Gaffer.GraphComponent) -> bool:
    if not isinstance(child, Gaffer.Node):
        return False
    type_name = child.typeName()
    return type_name.startswith("GafferArnold::") and (
        type_name.endswith("ArnoldShader")
        or type_name.endswith("ArnoldDisplacement")
    )


class SceneInsertMixin:
    """Graph Editor insert: ``out`` corresponds to scene ``in``."""

    def correspondingInput(self, output: Gaffer.Plug) -> Gaffer.Plug | None:
        try:
            if "out" in self and "in" in self and output.isSame(self["out"]):
                return self["in"]
        except Exception:
            pass
        parent = super()
        fn = getattr(parent, "correspondingInput", None)
        if callable(fn):
            return fn(output)
        return None


class BoxNetworkSerialiser(Gaffer.NodeSerialiser):
    """Rebuild internals in ``__init__``; still persist ``__uiPosition``."""

    def childNeedsSerialisation(
        self, child: Gaffer.GraphComponent, serialisation: Gaffer.Serialisation
    ) -> bool:
        if isinstance(child, Gaffer.Node):
            return False
        if child.getName() == "__uiPosition":
            return True
        return super().childNeedsSerialisation(child, serialisation)

    def childNeedsConstruction(
        self, child: Gaffer.GraphComponent, serialisation: Gaffer.Serialisation
    ) -> bool:
        if isinstance(child, Gaffer.Node):
            return False
        if child.getName() == "__uiPosition":
            return True
        return super().childNeedsConstruction(child, serialisation)
