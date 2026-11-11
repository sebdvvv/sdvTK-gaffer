"""Help button: open this node's README in the browser."""

from __future__ import annotations

import functools

import GafferUI

REPO = "https://github.com/sebdvvv/sdvTK-gaffer"
BRANCH = "main"

NODE_READMES = (
    "ArnoldLight",
    "ArnoldPhysicalSky",
    "ShadingTk",
    "sdvRenderSettings",
    "sdvRenderAttributes",
    "sdvUSDWriter",
)


def readme_url(node) -> str:
    name = type(node).__name__ if node is not None else ""
    if name in NODE_READMES:
        return "{}/blob/{}/docs/{}/README.md".format(REPO, BRANCH, name)
    return "{}/blob/{}/README.md".format(REPO, BRANCH)


def open_node_readme(node, *unused) -> None:
    from Qt.QtCore import QUrl
    from Qt.QtGui import QDesktopServices

    QDesktopServices.openUrl(QUrl(readme_url(node)))


def append_help_button(header, node, connections: list) -> GafferUI.Button:
    """Top-right Help, after Reset."""
    button = GafferUI.Button("Help")
    name = type(node).__name__ if node is not None else "this node"
    try:
        button.setToolTip("Open the {} README in a browser.".format(name))
    except Exception:
        pass
    connections.append(
        button.clickedSignal().connect(
            functools.partial(open_node_readme, node),
            scoped=True,
        )
    )
    header.append(button)
    return button
