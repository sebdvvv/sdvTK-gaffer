"""Select scene prims bound to a shader, and shaders assigned to a prim.

Shader Manager: right-click a shader, then "Select Objects Bound to Shader/Material".
Hierarchy View: right-click a prim, then "Select Shaders assigned to primitive".
"""

from __future__ import annotations

import traceback

import Gaffer
import IECore

_PATCHED = False
_MENU_PATH = "/Select Shaders assigned to primitive"
_DIVIDER_PATH = "/__sdvTkSelectShadersDivider"

_ASSIGNMENTS = (
    ("global", "globalAssign", "globalPath"),
    ("matte", "matteEnabled", "mattePath"),
    ("diag", "diagEnabled", "diagPath"),
    ("mix", "mixEnabled", "mixPath"),
)


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


def select_objects_bound_to_shader(node, keys) -> str:
    """Select meshes and prims bound to these Shader Manager keys."""
    keys = [str(key) for key in (keys or []) if str(key or "").strip()]
    if node is None or not keys:
        return "No shader selected."
    script = None
    try:
        script = node.scriptNode()
    except Exception:
        script = None
    handles = []
    seen_handles: set[str] = set()
    for key in keys:
        handle = _handle_for_key(node, key)
        if handle and handle not in seen_handles:
            seen_handles.add(handle)
            handles.append(handle)
    paths: list[str] = []
    truncated = False
    if handles:
        try:
            from sdvTkGaffer.ShadingTk._scene import (
                locations_bound_to_shader,
                with_scene_context,
            )

            def _walk():
                scene = node["out"] if "out" in node else None
                found: list[str] = []
                hit_limit = False
                seen: set[str] = set()
                for handle in handles:
                    locations, limited = locations_bound_to_shader(scene, handle)
                    hit_limit = hit_limit or limited
                    for path in locations:
                        if path in seen:
                            continue
                        seen.add(path)
                        found.append(path)
                return found, hit_limit

            paths, truncated = with_scene_context(node, _walk)
        except Exception as exc:
            IECore.msg(IECore.Msg.Level.Warning, "ShadingTk", str(exc))
            paths = []
            truncated = False
    if not paths:
        paths = _authored_paths(node, keys)
    if not paths:
        message = "No objects are bound to this shader."
        IECore.msg(IECore.Msg.Level.Warning, "ShadingTk", message)
        return message
    if not _set_selected_prim_paths(script, paths):
        message = "Could not select {} bound prim{}.".format(
            len(paths), "" if len(paths) == 1 else "s"
        )
        IECore.msg(IECore.Msg.Level.Warning, "ShadingTk", message)
        return message
    message = "Selected {} bound prim{}.".format(
        len(paths), "" if len(paths) == 1 else "s"
    )
    if truncated:
        message += " The search stopped early."
    IECore.msg(IECore.Msg.Level.Info, "ShadingTk", message)
    return message


def _append_hierarchy_item(hierarchy, pathListing, menuDefinition) -> None:
    for path in (_DIVIDER_PATH, _MENU_PATH):
        try:
            menuDefinition.remove(path, raiseIfMissing=False)
        except TypeError:
            try:
                menuDefinition.remove(path)
            except Exception:
                pass
        except Exception:
            pass
    selection = pathListing.getSelection()[0]
    try:
        empty = bool(selection.isEmpty())
    except Exception:
        empty = True
    scene = None
    try:
        scene = hierarchy.scene()
    except Exception:
        scene = None
    menuDefinition.append(_DIVIDER_PATH, {"divider": True})
    menuDefinition.append(
        _MENU_PATH,
        {
            "command": _select_shaders_for_hierarchy,
            "active": (not empty) and scene is not None,
            "description": "Select the shaders assigned to the selected "
            "primitives, and show the shader in ShadingTk Manager.",
        },
    )


def _select_shaders_for_hierarchy(menu) -> None:
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
        scene = hierarchy.scene()
    except Exception:
        scene = None
    script = None
    try:
        script = hierarchy.scriptNode()
    except Exception:
        script = None
    if scene is None or script is None:
        IECore.msg(
            IECore.Msg.Level.Warning,
            "ShadingTk",
            "The Hierarchy View has no scene to read shaders from.",
        )
        return
    try:
        paths = [str(path) for path in pathListing.getSelection()[0].paths()]
    except Exception:
        paths = []
    if not paths:
        return
    from sdvTkGaffer.ShadingTk._scene import assigned_shader_handles

    try:
        with hierarchy.context():
            handles = assigned_shader_handles(scene, paths)
    except Exception as exc:
        IECore.msg(IECore.Msg.Level.Warning, "ShadingTk", str(exc))
        return
    if not handles:
        IECore.msg(
            IECore.Msg.Level.Warning,
            "ShadingTk",
            "No shader is assigned to the selected primitive.",
        )
        return
    matches = _shadingtk_matches(script, handles)
    if not matches:
        matches = _assignment_matches(script, paths)
    if matches:
        nodes = []
        seen_nodes: set[int] = set()
        for node, _key, _handle in matches:
            if id(node) in seen_nodes:
                continue
            seen_nodes.add(id(node))
            nodes.append(node)
        _select_nodes(script, nodes)
        preferred = _preferred_node(scene, nodes) or nodes[0]
        key = ""
        for handle in handles:
            for node, match_key, match_handle in matches:
                if node.isSame(preferred) and match_handle == handle:
                    key = match_key
                    break
            if key:
                break
        if not key:
            for node, match_key, _handle in matches:
                if node.isSame(preferred):
                    key = match_key
                    break
        try:
            from sdvTkGafferUI.ShadingTkUI._managerWindow import (
                acquire_shadingtk_manager,
            )

            acquire_shadingtk_manager(preferred, shader_key=key or None)
        except Exception:
            traceback.print_exc()
        names = []
        seen_names: set[str] = set()
        for _node, _key, handle in matches:
            if handle in seen_names:
                continue
            seen_names.add(handle)
            names.append(handle)
        IECore.msg(
            IECore.Msg.Level.Info,
            "ShadingTk",
            "Opened ShadingTk Manager on {}.".format(", ".join(names)),
        )
        return
    nodes = _shader_nodes_named(script, handles)
    if not nodes:
        IECore.msg(
            IECore.Msg.Level.Warning,
            "ShadingTk",
            "Shader {} is assigned, but no shader node was found.".format(
                ", ".join(handles)
            ),
        )
        return
    _select_nodes(script, _visible_nodes(nodes))
    IECore.msg(
        IECore.Msg.Level.Info,
        "ShadingTk",
        "Selected shader node{} {}.".format(
            "" if len(nodes) == 1 else "s",
            ", ".join(_node_name(node) for node in nodes),
        ),
    )


def _handle_for_key(node, key: str) -> str:
    shader = None
    try:
        shader = node.shaderFromManagerKey(key)
    except Exception:
        shader = None
    if shader is None:
        return ""
    try:
        return str(shader.getName() or "")
    except Exception:
        return ""


def _authored_paths(node, keys: list[str]) -> list[str]:
    from sdvTkGaffer.ShadingTk._box import parse_prim_paths
    from sdvTkGaffer.ShadingTk._data import MAX_PATHS, path_count_plug, path_plug

    found: list[str] = []
    seen: set[str] = set()
    for key in keys:
        for path in _authored_paths_for_key(
            node, key, parse_prim_paths, path_plug, path_count_plug, MAX_PATHS
        ):
            if _is_pattern(path) or path in seen:
                continue
            seen.add(path)
            found.append(path)
    return found


def _authored_paths_for_key(
    node, key, parse_prim_paths, path_plug, path_count_plug, max_paths
) -> list[str]:
    key = (key or "").strip()
    if key.startswith("slot:"):
        try:
            index = int(key.split(":", 1)[1])
            count = int(node["slotCount"].getValue())
        except Exception:
            return []
        if index < 1 or index > count:
            return []
        try:
            path_count = int(node[path_count_plug(index)].getValue())
        except Exception:
            path_count = 1
        path_count = max(1, min(path_count, max_paths))
        texts = []
        for path_index in range(1, path_count + 1):
            try:
                texts.append(node[path_plug(index, path_index)].getValue() or "")
            except Exception:
                texts.append("")
        return parse_prim_paths(*texts)
    for name, flag, plug_name in _ASSIGNMENTS:
        if name != key:
            continue
        try:
            if not bool(node[flag].getValue()):
                return []
            return parse_prim_paths(node[plug_name].getValue() or "")
        except Exception:
            return []
    return []


def _is_pattern(path: str) -> bool:
    return any(token in (path or "") for token in ("...", "*", "?", "["))


def _set_selected_prim_paths(script, paths: list[str]) -> bool:
    if script is None or not paths:
        return False
    matcher = IECore.PathMatcher(list(paths))
    try:
        import GafferSceneUI

        algo = getattr(GafferSceneUI, "ScriptNodeAlgo", None)
        if algo is not None and hasattr(algo, "setSelectedPaths"):
            algo.setSelectedPaths(script, matcher)
            return True
        context_algo = getattr(GafferSceneUI, "ContextAlgo", None)
        context = getattr(script, "context", lambda: None)()
        if context_algo is not None and context is not None:
            context_algo.setSelectedPaths(context, matcher)
            return True
    except Exception:
        return False
    return False


def _shadingtk_matches(script, handles: list[str]) -> list[tuple]:
    wanted = set(handles)
    matches = []
    for node in _iter_shadingtk(script):
        try:
            entries = node._shader_manager_entries()
        except Exception:
            entries = []
        for entry in entries:
            shader = entry.get("node")
            names = set()
            entry_name = str(entry.get("name") or "")
            if entry_name:
                names.add(entry_name)
            try:
                shader_name = str(shader.getName() or "") if shader is not None else ""
            except Exception:
                shader_name = ""
            if shader_name:
                names.add(shader_name)
            hit = next((name for name in names if name in wanted), "")
            if not hit:
                continue
            matches.append((node, entry.get("key") or "", hit))
    return matches


def _assignment_matches(script, paths: list[str]) -> list[tuple]:
    """ShadingTk shaders whose PrimPath covers a selected location."""
    ranked = []
    for node in _iter_shadingtk(script):
        try:
            entries = node._shader_manager_entries()
        except Exception:
            entries = []
        for entry in entries:
            key = entry.get("key") or ""
            if not key:
                continue
            authored = _authored_paths(node, [key])
            score = _cover_score(paths, authored)
            if score < 0:
                continue
            ranked.append((score, node, key, entry.get("name") or key))
    if not ranked:
        return []
    ranked.sort(key=lambda item: item[0], reverse=True)
    best = ranked[0][0]
    return [(node, key, handle) for score, node, key, handle in ranked if score == best]


def _cover_score(selected: list[str], authored: list[str]) -> int:
    best = -1
    for prim in selected:
        for assignment in authored:
            if not _path_covers(assignment, prim):
                continue
            best = max(best, len((assignment or "").rstrip("/")))
    return best


def _path_covers(assignment: str, prim: str) -> bool:
    assigned = (assignment or "").rstrip("/") or "/"
    location = (prim or "").rstrip("/") or "/"
    if assigned == "/":
        return True
    return location == assigned or location.startswith(assigned + "/")


def _iter_shadingtk(root):
    from sdvTkGaffer.ShadingTk import ShadingTk

    stack = [root]
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        if node is None or id(node) in seen:
            continue
        seen.add(id(node))
        try:
            children = list(node.children())
        except Exception:
            children = []
        for child in children:
            if isinstance(child, ShadingTk):
                yield child
                continue
            if isinstance(child, Gaffer.Node):
                stack.append(child)


def _shader_nodes_named(script, handles: list[str]) -> list:
    wanted = set(handles)
    found = []
    seen: set[int] = set()
    stack = [script]
    while stack:
        node = stack.pop()
        if node is None or id(node) in seen:
            continue
        seen.add(id(node))
        try:
            children = list(node.children())
        except Exception:
            children = []
        for child in children:
            if not isinstance(child, Gaffer.Node):
                continue
            stack.append(child)
            try:
                name = str(child.getName() or "")
            except Exception:
                name = ""
            if name in wanted and _is_shader_node(child):
                found.append(child)
    return found


def _is_shader_node(node) -> bool:
    try:
        type_name = node.typeName()
    except Exception:
        return False
    return "Shader" in str(type_name)


def _visible_nodes(nodes: list) -> list:
    from sdvTkGaffer.ShadingTk import ShadingTk

    visible = []
    seen: set[int] = set()
    for node in nodes:
        shown = node
        try:
            parent = node.parent()
        except Exception:
            parent = None
        if isinstance(parent, ShadingTk):
            shown = parent
        if id(shown) in seen:
            continue
        seen.add(id(shown))
        visible.append(shown)
    return visible


def _preferred_node(scene_plug, nodes: list):
    if not nodes:
        return None
    if scene_plug is None:
        return nodes[0]
    try:
        start = scene_plug.node()
    except Exception:
        start = None
    wanted = {id(node) for node in nodes}
    found = _search_upstream(start, wanted, set())
    if found is not None:
        return found
    return nodes[0]


def _search_upstream(node, wanted: set[int], seen: set[int]):
    if node is None or id(node) in seen:
        return None
    seen.add(id(node))
    if id(node) in wanted:
        return node
    try:
        import GafferScene
    except Exception:
        return None
    try:
        children = list(node.children())
    except Exception:
        return None
    for child in children:
        if not isinstance(child, GafferScene.ScenePlug):
            continue
        try:
            if child.direction() != Gaffer.Plug.Direction.In:
                continue
            source = child.getInput()
        except Exception:
            continue
        if source is None:
            continue
        try:
            upstream = source.node()
        except Exception:
            upstream = None
        hit = _search_upstream(upstream, wanted, seen)
        if hit is not None:
            return hit
    return None


def _select_nodes(script, nodes: list) -> None:
    if script is None or not nodes:
        return
    try:
        selection = script.selection()
        selection.clear()
        for node in nodes:
            selection.add(node)
    except Exception:
        traceback.print_exc()


def _node_name(node) -> str:
    try:
        return str(node.getName() or "")
    except Exception:
        return "shader"
