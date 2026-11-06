"""Keep Viewer Arnold subdivision / displacement in step with sdvRenderSettings.

The two checkboxes drive ``renderer.arnold.enableSubdivision`` and
``enableDisplacement`` on every Scene View of the script (the toggles in
the viewport Arnold settings menu). The last ``sdvRenderSettings`` in the
script wins. When none remain, those toggles return to their defaults.
"""

from __future__ import annotations

import Gaffer
import GafferUI

_PLUGS = ("enableSubdivision", "enableDisplacement")
_WATCHED: set[int] = set()
_APPLYING = False
_INSTALLED = False


def watch(node) -> None:
    if id(node) in _WATCHED:
        return
    _WATCHED.add(id(node))
    # parentChangedSignal passes (child, oldParent). plugSetSignal passes the plug.
    node.plugSetSignal().connect(
        lambda *args, n=node: _on_node_plug(n, args[-1] if args else None),
        scoped=False,
    )
    node.parentChangedSignal().connect(
        lambda *args, n=node: _on_parent(n),
        scoped=False,
    )
    script = node.scriptNode()
    if script is not None:
        _sync(script)


def install(application=None) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    try:
        import GafferSceneUI

        GafferSceneUI.SceneView.instanceCreatedSignal().connect(_on_view_created, scoped=False)
    except Exception:
        pass
    GafferUI.ScriptWindow.instanceCreatedSignal().connect(_on_window, scoped=False)
    for window in _windows():
        _on_window(window)


def _windows():
    try:
        return list(GafferUI.ScriptWindow.instances())
    except Exception:
        return []


def _on_window(window) -> None:
    try:
        script = window.scriptNode()
    except Exception:
        return
    _scan(script)


def _on_view_created(view) -> None:
    try:
        view.plugSetSignal().connect(
            lambda *args, v=view: _on_view_plug(v, args[-1] if args else None),
            scoped=False,
        )
    except Exception:
        pass
    try:
        script = view.scriptNode()
    except Exception:
        script = None
    if script is not None:
        _sync(script)


def sync_node(node) -> None:
    """Push this node's checkboxes onto the script's Arnold viewports."""
    try:
        script = node.scriptNode()
    except Exception:
        script = None
    if script is not None:
        _sync(script)


def _scan(script) -> None:
    from sdvTkGaffer.sdvRenderSettings.sdvRenderSettings import sdvRenderSettings

    try:
        nodes = list(Gaffer.Node.RecursiveRange(script))
    except Exception:
        nodes = []
    for node in nodes:
        if isinstance(node, sdvRenderSettings):
            watch(node)
    _sync(script)


def _controllers(script):
    from sdvTkGaffer.sdvRenderSettings.sdvRenderSettings import sdvRenderSettings

    found = []
    try:
        nodes = Gaffer.Node.RecursiveRange(script)
    except Exception:
        return found
    for node in nodes:
        if isinstance(node, sdvRenderSettings):
            found.append(node)
    return found


def _scene_views(script):
    """Scene views live inside Viewer panels, not as layout editors."""
    try:
        window = GafferUI.ScriptWindow.acquire(script, createIfNecessary=False)
    except TypeError:
        try:
            window = GafferUI.ScriptWindow.acquire(script)
        except Exception:
            window = None
    except Exception:
        window = None
    if window is None:
        return []
    try:
        viewers = list(window.getLayout().editors(GafferUI.Viewer))
    except Exception:
        viewers = []
    found = []
    try:
        import GafferSceneUI
    except Exception:
        return found
    for viewer in viewers:
        candidates = []
        try:
            candidates.append(viewer.view())
        except Exception:
            pass
        try:
            candidates.extend(viewer._Viewer__views)
        except Exception:
            pass
        for view in candidates:
            if not isinstance(view, GafferSceneUI.SceneView):
                continue
            if any(existing.isSame(view) for existing in found):
                continue
            found.append(view)
    return found


def _child(plug, name):
    if plug is None or not name:
        return None
    try:
        if name in plug:
            return plug[name]
    except Exception:
        pass
    wanted = name.lower()
    try:
        for child in plug.children():
            if child.getName().lower() == wanted:
                return child
    except Exception:
        pass
    return None


def _arnold(view):
    renderer = _child(view, "renderer")
    return _child(renderer, "arnold")


def _on_node_plug(node, plug) -> None:
    if plug is None or plug.getName() not in _PLUGS:
        return
    script = node.scriptNode()
    if script is not None:
        _sync(script)


def _on_parent(node) -> None:
    script = node.scriptNode()
    if script is not None:
        _sync(script)
        return
    for window in _windows():
        try:
            _sync(window.scriptNode())
        except Exception:
            pass


def _on_view_plug(view, plug) -> None:
    global _APPLYING
    if _APPLYING or plug is None or plug.getName() not in _PLUGS:
        return
    parent = plug.parent()
    if parent is None or parent.getName().lower() != "arnold":
        return
    try:
        script = view.scriptNode()
    except Exception:
        return
    nodes = _controllers(script)
    if not nodes:
        return
    wanted = bool(nodes[-1][plug.getName()].getValue())
    try:
        current = bool(plug.getValue())
    except Exception:
        return
    if current != wanted:
        _apply([view], nodes[-1])


def _sync(script) -> None:
    views = _scene_views(script)
    nodes = _controllers(script)
    if not nodes:
        _restore(views)
        return
    _apply(views, nodes[-1])


def _apply(views, node) -> None:
    global _APPLYING
    _APPLYING = True
    try:
        for view in views:
            settings = _arnold(view)
            if settings is None:
                continue
            for name in _PLUGS:
                target = _child(settings, name)
                source = _child(node, name)
                if target is None or source is None:
                    continue
                try:
                    target.setValue(bool(source.getValue()))
                except Exception:
                    pass
    finally:
        _APPLYING = False


def _restore(views) -> None:
    global _APPLYING
    _APPLYING = True
    try:
        for view in views:
            settings = _arnold(view)
            if settings is None:
                continue
            for name in _PLUGS:
                plug = _child(settings, name)
                if plug is None:
                    continue
                reset = getattr(plug, "setToDefault", None)
                try:
                    if callable(reset):
                        reset()
                    else:
                        plug.setValue(False)
                except Exception:
                    pass
    finally:
        _APPLYING = False
