"""Hierarchy View: select the node that created the selected primitive.

Right-click a prim, then "Select Node". The node is added to the selection.
The Graph Editor is left where it is. Alt+E still opens that node in a Node Editor.
"""

from __future__ import annotations

import traceback

import Gaffer
import IECore

_PATCHED = False
_MENU_PATH = "/Select Node"
_MENU_PATHS = "/Select Nodes"
_LOOKUP_LIMIT = 32


def install(application=None) -> bool:
    """Add the Hierarchy View item. Safe to call once at GUI startup."""
    global _PATCHED
    if _PATCHED:
        return True
    try:
        import GafferSceneUI
    except Exception:
        return False
    cls = getattr(GafferSceneUI, "HierarchyView", None)
    if cls is None:
        return False
    name = "_HierarchyView__columnContextMenuSignal"
    original = getattr(cls, name, None)
    if original is None:
        print("[sdvTk] HierarchyView context menu hook not found.")
        return False

    def _wrapped(self, column, pathListing, menuDefinition):
        result = original(self, column, pathListing, menuDefinition)
        try:
            columns = pathListing.getColumns()
            if columns and columns.index(column) != 0:
                return result
        except Exception:
            return result
        try:
            _append_hierarchy_item(self, pathListing, menuDefinition)
        except Exception:
            traceback.print_exc()
        return result

    setattr(cls, name, _wrapped)
    _PATCHED = True
    return True


def _append_hierarchy_item(hierarchy, pathListing, menuDefinition) -> None:
    for path in (_MENU_PATH, _MENU_PATHS):
        _remove(menuDefinition, path)
    paths = _selected_paths(pathListing)
    scene = None
    try:
        scene = hierarchy.scene()
    except Exception:
        scene = None
    nodes = []
    if scene is not None and paths and len(paths) <= _LOOKUP_LIMIT:
        nodes = _source_nodes(hierarchy, paths)
    if len(nodes) > 1 or len(paths) > _LOOKUP_LIMIT:
        label = _MENU_PATHS
        description = "Select the nodes that created the selected primitives."
    elif len(nodes) == 1:
        label = "/Select Node '{}'".format(_menu_name(nodes[0]))
        description = "Select the node that created the selected primitive."
    else:
        label = _MENU_PATH
        description = "Select the node that created the selected primitive."
    _remove(menuDefinition, label)
    menuDefinition.append(
        label,
        {
            "command": _select_node_for_hierarchy,
            "active": bool(paths) and scene is not None and (
                bool(nodes) or len(paths) > _LOOKUP_LIMIT
            ),
            "description": description,
        },
    )


def _select_node_for_hierarchy(menu) -> None:
    """Look up the Hierarchy View from the menu so the command does not capture it."""
    try:
        import GafferSceneUI
    except Exception:
        return
    try:
        hierarchy = menu.ancestor(GafferSceneUI.HierarchyView)
    except Exception:
        hierarchy = None
    if hierarchy is None:
        return
    try:
        pathListing = hierarchy.sceneListing()
    except Exception:
        pathListing = None
    if pathListing is None:
        return
    try:
        script = hierarchy.scriptNode()
    except Exception:
        script = None
    paths = _selected_paths(pathListing)
    if script is None or not paths:
        return
    try:
        scene = hierarchy.scene()
    except Exception:
        scene = None
    if scene is None:
        IECore.msg(
            IECore.Msg.Level.Warning,
            "sdvTk",
            "The Hierarchy View has no scene to read the node from.",
        )
        return
    nodes = _source_nodes(hierarchy, paths)
    if not nodes:
        IECore.msg(
            IECore.Msg.Level.Warning,
            "sdvTk",
            "No node was found for the selected primitive.",
        )
        return
    _select_nodes(script, nodes)
    names = ", ".join(_node_name(node) for node in nodes)
    IECore.msg(
        IECore.Msg.Level.Info,
        "sdvTk",
        "Selected {}.".format(names),
    )


def _source_nodes(hierarchy, paths: list[str]) -> list:
    import GafferScene

    try:
        scene = hierarchy.scene()
    except Exception:
        scene = None
    if scene is None:
        return []
    nodes = []
    seen: set[int] = set()
    try:
        context = hierarchy.context()
    except Exception:
        context = None
    if context is None:
        return []
    with context:
        for path in paths:
            node = _source_node(scene, path)
            if node is None or id(node) in seen:
                continue
            seen.add(id(node))
            nodes.append(node)
    return nodes


def _source_node(scene, path: str):
    import GafferScene

    try:
        source = GafferScene.SceneAlgo.source(scene, path)
    except Exception:
        return None
    if source is None:
        return None
    try:
        node = Gaffer.MetadataAlgo.firstViewableNode(source)
    except Exception:
        node = None
    if node is not None:
        return node
    try:
        return source.node()
    except Exception:
        return None


def _selected_paths(pathListing) -> list[str]:
    try:
        selection = pathListing.getSelection()[0]
    except Exception:
        return []
    try:
        if selection.isEmpty():
            return []
        return [str(path) for path in selection.paths()]
    except Exception:
        return []


def _select_nodes(script, nodes: list) -> None:
    try:
        selection = script.selection()
        selection.clear()
        for node in nodes:
            selection.add(node)
    except Exception:
        traceback.print_exc()


def _remove(menuDefinition, path: str) -> None:
    try:
        menuDefinition.remove(path, raiseIfMissing=False)
    except TypeError:
        try:
            menuDefinition.remove(path)
        except Exception:
            pass
    except Exception:
        pass


def _node_name(node) -> str:
    try:
        return str(node.getName() or "")
    except Exception:
        return "node"


def _menu_name(node) -> str:
    return _node_name(node).replace("/", " ").replace("'", "")
