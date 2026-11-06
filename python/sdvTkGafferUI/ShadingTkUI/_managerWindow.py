"""One window for Shader Manager and Texture Manager, split by tabs."""

from __future__ import annotations

import Gaffer
import GafferUI

from ._shaderManager import ShaderManagerWindow
from ._textureManager import TextureManagerWindow

_WINDOWS: dict[int, "ShadingTkManagerWindow"] = {}


def acquire_shadingtk_manager(
    node,
    parent=None,
    page: str | None = None,
    shader_key: str | None = None,
    texture_name: str | None = None,
):
    """One ShadingTk Manager window for this node.

    ``page`` is ``"shaders"`` or ``"textures"`` and selects that tab.
    ``shader_key`` opens the Shaders tab on that shader.
    ``texture_name`` opens the Textures tab on that library texture.
    """
    from ._editor import widget_is_alive

    key_id = id(node)
    window = _WINDOWS.get(key_id)
    if window is None or not widget_is_alive(window):
        window = ShadingTkManagerWindow(node)
        _WINDOWS[key_id] = window
        if parent is not None:
            try:
                parent.addChildWindow(window)
            except Exception:
                pass
    shader_key = (shader_key or "").strip()
    texture_name = (texture_name or "").strip()
    if shader_key:
        try:
            window.showShader(shader_key)
        except Exception:
            pass
    elif texture_name:
        try:
            window.showTexture(texture_name)
        except Exception:
            pass
    elif page:
        try:
            window.showPage(page)
        except Exception:
            pass
    try:
        window.setVisible(True)
        window.reveal()
        qt_window = window._qtWidget()
        qt_window.raise_()
        qt_window.activateWindow()
    except Exception:
        pass
    return window


class ShadingTkManagerWindow(GafferUI.Window):
    """Shaders and textures for one ShadingTk, each on its own tab."""

    def __init__(self, node, **kw) -> None:
        kw.setdefault("sizeMode", GafferUI.Window.SizeMode.Manual)
        try:
            GafferUI.Window.__init__(self, "ShadingTk Manager", **kw)
        except TypeError:
            kw.pop("sizeMode", None)
            GafferUI.Window.__init__(self, "ShadingTk Manager", **kw)
        self.__node = node
        self.__connections: list = []
        self.__shaders = ShaderManagerWindow(node)
        self.__textures = TextureManagerWindow(node)
        tabs = GafferUI.TabbedContainer()
        try:
            tabs.append(self.__shaders, "Shaders")
            tabs.append(self.__textures, "Textures")
        except TypeError:
            tabs.addChild(self.__shaders)
            tabs.setLabel(self.__shaders, "Shaders")
            tabs.addChild(self.__textures)
            tabs.setLabel(self.__textures, "Textures")
        self.__tabs = tabs
        self.setChild(tabs)
        try:
            self._qtWidget().resize(980, 560)
        except Exception:
            pass
        self.__connections.append(
            self.dragEnterSignal().connect(
                Gaffer.WeakMethod(self.__onDragEnter), scoped=True
            )
        )
        self.__connections.append(
            self.dropSignal().connect(
                Gaffer.WeakMethod(self.__onDrop), scoped=True
            )
        )
        try:
            self._qtWidget().setAcceptDrops(True)
        except Exception:
            pass

    def node(self):
        return self.__node

    def showPage(self, page: str) -> None:
        child = self.__textures if page == "textures" else self.__shaders
        try:
            self.__tabs.setCurrent(child)
        except Exception:
            pass

    def showShader(self, key: str) -> None:
        self.showPage("shaders")
        self.__shaders.showShader(key)

    def showTexture(self, name: str) -> None:
        self.showPage("textures")
        self.__textures.showTexture(name)

    def refresh(self, *unused) -> None:
        try:
            self.__shaders.refresh()
        except Exception:
            pass

    def __onDragEnter(self, widget, event) -> bool:
        try:
            return self.__textures.dragEnter(widget, event)
        except Exception:
            return False

    def __onDrop(self, widget, event) -> bool:
        try:
            accepted = self.__textures.drop(widget, event)
        except Exception:
            return False
        if accepted:
            self.showPage("textures")
        return accepted
