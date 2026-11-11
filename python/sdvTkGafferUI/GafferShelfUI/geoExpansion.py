"""Force open Scene Views to draw geometry instead of bounding boxes."""

import gc

import GafferSceneUI
import GafferUI

FORCED_DEPTH = 1000

_active = False
_original_depths = {}


def _scene_views():
    windows = [o for o in gc.get_objects() if isinstance(o, GafferUI.ScriptWindow)]
    for window in windows:
        try:
            viewers = window.getLayout().editors(GafferUI.Viewer)
        except Exception:
            continue
        for viewer in viewers:
            view = viewer.view()
            if view is not None and isinstance(view, GafferSceneUI.SceneView):
                yield view


def _scene_gadget(view):
    try:
        return view.viewportGadget().getPrimaryChild()
    except Exception:
        return None


def _clamped(plug, depth):
    try:
        if plug.hasMaxValue():
            return min(depth, plug.maxValue())
    except Exception:
        pass
    return depth


def _force(view, depth):
    plug = view.getChild("minimumExpansionDepth")
    key = id(view)
    if plug is not None:
        if key not in _original_depths:
            _original_depths[key] = (view, plug.getValue())
        target = _clamped(plug, depth)
        if plug.getValue() != target:
            plug.setValue(target)
    gadget = _scene_gadget(view)
    if gadget is not None:
        try:
            if gadget.getMinimumExpansionDepth() < depth:
                gadget.setMinimumExpansionDepth(depth)
        except Exception:
            pass


def _restore(view):
    plug = view.getChild("minimumExpansionDepth")
    original = _original_depths.pop(id(view), (None, 0))[1]
    if plug is not None:
        plug.setValue(original)
    gadget = _scene_gadget(view)
    if gadget is not None:
        try:
            gadget.setMinimumExpansionDepth(original)
        except Exception:
            pass


def _apply(depth):
    count = 0
    for view in _scene_views():
        count += 1
        if depth is None:
            _restore(view)
        else:
            _force(view, depth)
    return count


def on(depth=None):
    global _active, FORCED_DEPTH
    if depth is not None:
        FORCED_DEPTH = int(depth)
    _active = True
    count = _apply(FORCED_DEPTH)
    print(
        "[sdvTk Shelf] Forced Geometry Mode: ON, depth=%d (%d viewer(s))"
        % (FORCED_DEPTH, count)
    )


def off():
    global _active
    _active = False
    count = _apply(None)
    print("[sdvTk Shelf] Forced Geometry Mode: OFF (%d viewer(s) restored)" % count)


def is_active():
    return bool(_active)


def set_depth(depth):
    global FORCED_DEPTH
    FORCED_DEPTH = int(depth)
    if _active:
        _apply(FORCED_DEPTH)
    print("[sdvTk Shelf] Depth set to %d" % FORCED_DEPTH)


def toggle_bounding_boxes(script_node=None, active=True, depth=None):
    if active:
        on(depth)
    else:
        off()


def report():
    for view in _scene_views():
        plug = view.getChild("minimumExpansionDepth")
        gadget = _scene_gadget(view)
        print("view:", view.getName())
        print("  plug depth   :", plug.getValue() if plug is not None else "NO PLUG")
        if plug is not None and plug.hasMaxValue():
            print("  plug max     :", plug.maxValue())
        try:
            print("  gadget depth :", gadget.getMinimumExpansionDepth())
        except Exception:
            print("  gadget depth : n/a")
