"""Enabled passthrough, Graph Editor insert, and Box serialisation."""

from __future__ import annotations

import Gaffer
import GafferScene

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


def enabled_switch_expression_line() -> str:
    return "parent['{}']['index'] = 1 if parent['enabled'] else 0".format(
        ENABLED_SWITCH
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


def persist_internal_shader_node(child: Gaffer.GraphComponent) -> bool:
    """True for Arnold lights/shaders whose plug values must survive save/paste.

    Infrastructure nodes (Switch, Group, MergeScenes, …) are rebuilt in
    ``__init__``. Serialising a Switch that already called ``setup()``
    tries to add ``in`` again and raises on copy-paste.
    """
    if not isinstance(child, Gaffer.Node):
        return False
    type_name = child.typeName()
    return type_name.startswith("GafferArnold::") and (
        type_name.endswith("ArnoldLight")
        or type_name.endswith("ArnoldMeshLight")
        or type_name.endswith("ArnoldShader")
        or type_name.endswith("ArnoldLightFilter")
    )


class BoxNetworkSerialiser(Gaffer.NodeSerialiser):
    """Rebuild internals in ``__init__``; still persist ``__uiPosition``."""

    def childNeedsSerialisation(
        self, child: Gaffer.GraphComponent, serialisation: Gaffer.Serialisation
    ) -> bool:
        if isinstance(child, Gaffer.Node):
            return persist_internal_shader_node(child)
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
