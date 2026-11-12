"""Cycles USD translation.

``cycles:`` options stay ``cycles:``. A ``cycles:background:shader`` network
is written as a node graph and linked from the render settings.
"""

from __future__ import annotations

ID = "cycles"
LABEL = "Cycles"
PREFIX = "cycles:"
ROOT_OPTION_TYPE = "CyclesOptions"


def owns(name: str) -> bool:
    return str(name or "").startswith(PREFIX)


def translate(name: str) -> str:
    return str(name or "")


def alias(name: str):
    return None


_BACKGROUND_GRAPH = "/mtl/cyclesBackground/nodeGraph"


def author_background(stage, settings_prim, members) -> set:
    """Write ``cycles:background:shader`` when it is a shader network.

    An empty result leaves the option for the normal writer. Failures are
    not raised.
    """
    from .network import author_shader_network, shader_network

    if settings_prim is None:
        return set()
    network = shader_network(members.get("option:cycles:background:shader"))
    if network is None:
        return set()
    try:
        authored = author_shader_network(
            stage,
            settings_prim,
            network,
            graph_path=_BACKGROUND_GRAPH,
            graph_type="NodeGraph",
            terminal="surface",
            link_name="cycles:background:shader",
            node_id=_node_id,
            scopes=("/mtl", "/mtl/cyclesBackground"),
        )
    except Exception:
        authored = False
    if not authored:
        return set()
    return {"cycles:background:shader"}


def _node_id(name: str) -> str:
    name = str(name or "")
    if name.startswith("cycles:"):
        return name
    return "cycles:" + name


def finish(stage) -> bool:
    return False
