"""Hierarchy View browse-only: expand the tree without updating the Visible Set.

Gaffer writes Hierarchy expansion into the script Visible Set, which the
Viewer uses to reload locations. When the preference is on, expand and
collapse stay local to the listing.
"""

from __future__ import annotations

_PATCHED = False
_ORIGINAL_EXPANSION_CHANGED = None
_ORIGINAL_VISIBLE_SET_CHANGED = None


def _browse_only() -> bool:
    from sdvTkGafferUI import prefs

    return prefs.hierarchy_browse_only()


def _expansion_changed(self, pathListing):
    if _browse_only():
        return None
    return _ORIGINAL_EXPANSION_CHANGED(self, pathListing)


def _visible_set_changed(self, scriptNode):
    if _browse_only():
        return None
    return _ORIGINAL_VISIBLE_SET_CHANGED(self, scriptNode)


def install(application=None) -> bool:
    """Patch HierarchyView once. The preference is read on each expand."""
    global _PATCHED
    global _ORIGINAL_EXPANSION_CHANGED
    global _ORIGINAL_VISIBLE_SET_CHANGED
    if _PATCHED:
        return True
    try:
        import GafferSceneUI
    except Exception:
        return False
    cls = getattr(GafferSceneUI, "HierarchyView", None)
    if cls is None:
        return False
    expansion_name = "_HierarchyView__expansionChanged"
    visible_name = "_HierarchyView__visibleSetChanged"
    orig_expansion = getattr(cls, expansion_name, None)
    orig_visible = getattr(cls, visible_name, None)
    if orig_expansion is None or orig_visible is None:
        print("[sdvTk] HierarchyView hooks not found — browse-only preference disabled.")
        return False
    _ORIGINAL_EXPANSION_CHANGED = orig_expansion
    _ORIGINAL_VISIBLE_SET_CHANGED = orig_visible
    setattr(cls, expansion_name, _expansion_changed)
    setattr(cls, visible_name, _visible_set_changed)
    _PATCHED = True
    return True
