"""RenderMan USD translation.

``ri:`` options stay ``ri:``. An ``ri:displayfilter`` network, including a
background display filter, is written as a node graph and linked from the
render settings.
"""

from __future__ import annotations

ID = "renderman"
LABEL = "RenderMan"
PREFIX = "ri:"
ROOT_OPTION_TYPE = "RenderManOptions"


def owns(name: str) -> bool:
    return str(name or "").startswith(PREFIX)


def translate(name: str) -> str:
    return str(name or "")


def alias(name: str):
    return None


_DISPLAY_FILTER_GRAPH = "/mtl/displayfilter/nodeGraph"


def author_background(stage, settings_prim, members) -> set:
    """Write ``ri:displayfilter`` when it is a shader network.

    An empty result leaves the option for the normal writer. Failures are
    not raised.
    """
    from .network import author_shader_network, shader_network

    if settings_prim is None:
        return set()
    network = shader_network(members.get("option:ri:displayfilter"))
    if network is None:
        return set()
    try:
        authored = author_shader_network(
            stage,
            settings_prim,
            network,
            graph_path=_DISPLAY_FILTER_GRAPH,
            graph_type="NodeGraph",
            terminal="out",
            link_name="ri:displayfilter",
            node_id=_node_id,
            scopes=("/mtl", "/mtl/displayfilter"),
        )
    except Exception:
        authored = False
    if not authored:
        return set()
    return {"ri:displayfilter"}


def _node_id(name: str) -> str:
    return str(name or "")


def finish(stage) -> bool:
    return False
