"""sdvTk menu: Options, Shader Manager, Texture Manager, About."""

from __future__ import annotations

import os
import traceback

import Gaffer
import GafferUI
import IECore

from sdvTkGafferUI import prefs
from sdvTkGafferUI.prefs import (
    CTRL_DOUBLE_CLICK_NODE_EDITOR,
    DOUBLE_CLICK_ENTER,
    GRAPH_VIEW_NAV_MENU,
    HIERARCHY_BROWSE_ONLY,
    MSE_GITHUB,
    SHOW_CONTENTS_SINGLE_PANE,
    MULTI_SCRIPT_EDITOR_FOLDER,
    USE_MULTI_SCRIPT_EDITOR,
)

def _run(dialog) -> int:
    runner = getattr(dialog, "exec", None)
    if not callable(runner):
        runner = dialog.exec_
    return runner()


def install(application=None) -> None:
    if application is None:
        return
    menu = GafferUI.ScriptWindow.menuDefinition(application)
    menu.append(
        "/sdvTk/Options",
        {"command": _open_options, "description": "sdvTk preferences"},
    )
    menu.append(
        "/sdvTk/Shader Manager",
        {
            "command": _open_shader_manager,
            "description": "Open ShadingTk Manager on the Shaders tab",
        },
    )
    menu.append(
        "/sdvTk/Texture Manager",
        {
            "command": _open_texture_manager,
            "description": "Open ShadingTk Manager on the Textures tab",
        },
    )
    menu.append(
        "/sdvTk/Lights Manager",
        {
            "command": _open_lights_manager,
            "description": "Lights in the script, with filters, shaders and textures",
        },
    )
    menu.append(
        "/sdvTk/About",
        {"command": _open_about, "description": "About sdvTk"},
    )


def _script_from_menu(menu):
    try:
        window = menu.ancestor(GafferUI.ScriptWindow)
    except Exception:
        window = None
    if window is None:
        return None
    try:
        return window.scriptNode()
    except Exception:
        return None


def _qt_parent():
    from Qt import QtWidgets

    app = QtWidgets.QApplication.instance()
    if app is None:
        return None
    return app.activeWindow()


_DIALOG_STYLE = """
    QDialog { background-color: #2b2b2b; color: #dfdfdf; }
    QLabel { color: #dfdfdf; }
    QLineEdit {
        background-color: #1e1e1e; color: #dfdfdf;
        border: 1px solid #555555; border-radius: 3px; padding: 4px 6px;
    }
    QLineEdit:focus { border: 1px solid #ffaa00; }
    QCheckBox { color: #dfdfdf; spacing: 8px; font-size: 10pt; }
    QCheckBox::indicator {
        width: 14px; height: 14px;
        border: 1px solid #666666; border-radius: 2px; background: #1e1e1e;
    }
    QCheckBox::indicator:checked { background: #5a4310; border: 1px solid #ffaa00; }
    QCheckBox:disabled { color: #777777; }
    QPushButton {
        background-color: #3a3a3a; color: #dfdfdf;
        border: 1px solid #555555; border-radius: 3px; padding: 5px 12px;
    }
    QPushButton:hover { background-color: #4a4a4a; border: 1px solid #ffaa00; }
    QPushButton#PrimaryButton {
        background-color: #5a4310; border: 1px solid #ffaa00; font-weight: bold;
    }
"""


def _gaffer_version() -> str:
    try:
        return Gaffer.About.versionString()
    except Exception:
        return "?"


def _license_url() -> str:
    root = os.environ.get("GAFFER_ROOT") or ""
    if not root:
        try:
            root = os.path.dirname(os.path.dirname(os.path.dirname(Gaffer.__file__)))
        except Exception:
            root = ""
    path = os.path.normpath(
        os.path.join(root, "doc", "gaffer", "html", "Appendices", "License", "index.html")
    )
    if os.name == "nt":
        return "file:///" + path.replace("\\", "/")
    return "file://" + path


def _feature_html() -> str:
    return """
<html><body style="color:#dfdfdf; font-family:'Segoe UI',Arial,sans-serif; font-size:10pt;">
<p style="margin:0 0 4px 0; font-size:12pt;">
  <b>Gaffer {version}</b>
</p>
<p style="margin:0 0 14px 0;">
  <a href="{license_url}" style="color:#ffaa00;">License</a>
</p>
<p style="margin:0 0 8px 0;">sdvTk</p>
<p style="margin:10px 0 4px 0;"><b>Panels</b></p>
<ul style="margin:0; padding-left:18px; line-height:1.5;">
  <li>Python Editor (from pw_MultiScriptEditor — MIT License)
    (<a href="{mse}" style="color:#ffaa00;">github</a>) — optional; the folder below is applied at startup</li>
  <li>ShadingTk Manager (Shaders and Textures)</li>
</ul>
<p style="margin:10px 0 4px 0;"><b>UI tweaks</b></p>
<ul style="margin:0; padding-left:18px; line-height:1.5;">
  <li>Arnold Viewer Shading / Lighting / Textures: Full as default</li>
  <li>Unsaved-changes dialog: Cancel | Discard | Save</li>
  <li>Optional: Hierarchy View browse without retriggering the Viewer</li>
  <li>Hierarchy View: Select Shaders assigned to primitive</li>
</ul>
<p style="margin:10px 0 4px 0;"><b>Graph &amp; editors</b></p>
<ul style="margin:0; padding-left:18px; line-height:1.5;">
  <li>Middle-click closes editor tabs (Graph Editor, Viewer, …)</li>
  <li>Graph View right-click menu has navigation (◀ and /)</li>
  <li>Double-click enters content nodes, when that option is on</li>
</ul>
</body></html>
""".format(version=_gaffer_version(), license_url=_license_url(), mse=MSE_GITHUB)


def _open_options(*unused) -> None:
    _SdvTkDialog(_qt_parent()).show_modal()


def _package_nodes():
    from sdvTkGaffer import (
        ArnoldLight,
        ArnoldPhysicalSky,
        ShadingTk,
        sdvRenderAttributes,
        sdvRenderSettings,
    )

    return (
        ("ArnoldLight", ArnoldLight),
        ("ArnoldPhysicalSky", ArnoldPhysicalSky),
        ("ShadingTk", ShadingTk),
        ("sdvRenderSettings", sdvRenderSettings),
        ("sdvRenderAttributes", sdvRenderAttributes),
    )


def _about_html() -> str:
    links = []
    for name, _cls in _package_nodes():
        links.append(
            '<a href="sdvtk://node/{name}" style="color:#ffaa00; text-decoration:none;">{name}</a>'.format(
                name=name
            )
        )
    return """
<html><body style="color:#dfdfdf; font-family:'Segoe UI',Arial,sans-serif; font-size:10pt;">
<p style="margin:0 0 6px 0; font-size:14pt;"><b>sdvTk</b></p>
<p style="margin:0 0 10px 0;">Author name: Sébastien Durand</p>
<p style="margin:0 0 10px 0;">License: MIT</p>
<p style="margin:0 0 10px 0;">
  <a href="https://github.com/sebdvvv/sdvTK-gaffer" style="color:#ffaa00;">https://github.com/sebdvvv/sdvTK-gaffer</a>
</p>
<p style="margin:0 0 14px 0;">2026</p>
<p style="margin:0 0 12px 0;">Gaffer 1.7+ / Arnold 7.4+ / RenderMan 27+ / Cycles</p>
<p style="margin:0 0 4px 0;"><b>Nodes</b></p>
<p style="margin:0; line-height:1.7;">{links}</p>
</body></html>
""".format(links="<br>".join(links))


def _graph_editor(script):
    if script is None:
        return None
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
        return None
    try:
        editors = list(window.getLayout().editors(GafferUI.GraphEditor))
    except Exception:
        return None
    for editor in editors:
        try:
            if editor.visible():
                return editor
        except Exception:
            return editor
    return editors[0] if editors else None


def _graph_root(script, editor):
    if editor is not None:
        try:
            return editor.graphGadget().getRoot()
        except Exception:
            pass
    return script


def _root_is_read_only(root) -> bool:
    if root is None:
        return False
    try:
        if Gaffer.MetadataAlgo.readOnly(root):
            return True
    except Exception:
        pass
    getter = getattr(Gaffer.MetadataAlgo, "getChildNodesAreReadOnly", None)
    if not callable(getter):
        return False
    try:
        return bool(getter(root))
    except Exception:
        return False


def _place_node(editor, node, index: int) -> None:
    import imath

    graph = editor.graphGadget()
    widget = editor.graphGadgetWidget()
    center = widget.getViewportGadget().rasterToGadgetSpace(
        imath.V2f(widget.size()) / 2.0,
        gadget=graph,
    ).p0
    step = 18.0
    column = index % 4
    row = index // 4
    Gaffer.Metadata.registerValue(node, "nodeGadget:x", float(center.x) + column * step)
    Gaffer.Metadata.registerValue(node, "nodeGadget:y", float(center.y) - row * step)


def _frame_node(editor, node) -> None:
    from Qt import QtCore

    def _go() -> None:
        try:
            if editor.graphGadget().nodeGadget(node) is None:
                return
            editor.frame([node], extend=True)
        except Exception:
            pass

    try:
        QtCore.QTimer.singleShot(0, _go)
    except Exception:
        pass


def _create_package_node(script, name: str, created: dict) -> None:
    classes = dict(_package_nodes())
    cls = classes.get(name)
    if cls is None:
        return
    if script is None:
        IECore.msg(
            IECore.Msg.Level.Warning,
            "sdvTk",
            "Open a script before creating {}.".format(name),
        )
        return
    editor = _graph_editor(script)
    root = _graph_root(script, editor)
    if _root_is_read_only(root):
        IECore.msg(
            IECore.Msg.Level.Warning,
            "sdvTk",
            "The current graph is read-only.",
        )
        return
    index = int(created.get("count") or 0)
    try:
        with Gaffer.UndoScope(script):
            node = cls()
            root.addChild(node)
            if editor is not None:
                _place_node(editor, node, index)
            else:
                Gaffer.Metadata.registerValue(node, "nodeGadget:x", float(index) * 18.0)
                Gaffer.Metadata.registerValue(node, "nodeGadget:y", float(index) * -18.0)
            script.selection().clear()
            script.selection().add(node)
    except Exception as exc:
        IECore.msg(IECore.Msg.Level.Error, "sdvTk", str(exc))
        return
    created["count"] = index + 1
    if editor is not None:
        _frame_node(editor, node)
    IECore.msg(
        IECore.Msg.Level.Info,
        "sdvTk",
        "Created {}.".format(node.getName()),
    )


def _open_about(menu=None, *unused) -> None:
    from Qt import QtCore
    from Qt.QtGui import QDesktopServices
    from Qt.QtWidgets import QDialog, QDialogButtonBox, QFrame, QTextBrowser, QVBoxLayout

    script = _script_from_menu(menu) if menu is not None else None
    created = {"count": 0}
    dialog = QDialog(_qt_parent())
    dialog.setWindowTitle("About sdvTk")
    dialog.setModal(True)
    dialog.setMinimumWidth(420)
    dialog.setStyleSheet(_DIALOG_STYLE)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(14, 14, 14, 12)
    body = QTextBrowser()
    body.setOpenLinks(False)
    body.setOpenExternalLinks(False)
    body.setFrameShape(QFrame.NoFrame)
    body.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    body.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    body.setStyleSheet(
        "QTextBrowser { background-color: #2b2b2b; color: #dfdfdf; border: none; }"
    )
    body.setHtml(_about_html())

    def _on_anchor(url) -> None:
        scheme = ""
        try:
            scheme = str(url.scheme() or "")
        except Exception:
            scheme = ""
        if scheme.lower() == "sdvtk":
            name = ""
            try:
                name = str(url.path() or "").replace("\\", "/").strip().strip("/")
            except Exception:
                name = ""
            if "/" in name:
                name = name.rsplit("/", 1)[-1]
            if not name:
                try:
                    text = str(url.toString() or "")
                except Exception:
                    text = ""
                marker = "sdvtk://node/"
                if marker in text:
                    name = text.split(marker, 1)[1].split("?", 1)[0].strip("/")
            _create_package_node(script, name, created)
            return
        try:
            QDesktopServices.openUrl(url)
        except Exception:
            traceback.print_exc()

    body.anchorClicked.connect(_on_anchor)
    body.document().setTextWidth(dialog.minimumWidth() - 28)
    body.setFixedHeight(max(int(body.document().size().height()) + 12, 140))
    layout.addWidget(body)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok)
    buttons.button(QDialogButtonBox.Ok).setObjectName("PrimaryButton")
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)
    _run(dialog)


class _SdvTkDialog:
    """Feature list, preference checkboxes, and a link to the prefs folder."""

    def __init__(self, parent=None) -> None:
        from Qt import QtCore
        from Qt.QtGui import QCursor
        from Qt.QtWidgets import (
            QCheckBox,
            QDialog,
            QDialogButtonBox,
            QFrame,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QTextBrowser,
            QVBoxLayout,
        )

        self._dialog = QDialog(parent)
        self._dialog.setWindowTitle("sdvTk")
        self._dialog.setModal(True)
        self._dialog.setMinimumWidth(520)
        self._dialog.setStyleSheet(_DIALOG_STYLE)

        root = QVBoxLayout(self._dialog)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(10)

        body = QTextBrowser()
        body.setOpenExternalLinks(True)
        body.setFrameShape(QFrame.NoFrame)
        body.setHtml(_feature_html())
        body.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        body.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        body.setStyleSheet(
            "QTextBrowser { background-color: #2b2b2b; color: #dfdfdf; border: none; }"
        )
        body.document().setTextWidth(self._dialog.minimumWidth() - 28)
        body.setFixedHeight(max(int(body.document().size().height()) + 16, 220))
        root.addWidget(body)

        prefs_box = QVBoxLayout()
        prefs_box.setContentsMargins(18, 0, 4, 0)
        prefs_box.setSpacing(4)

        self._cb_double_click = QCheckBox(
            "Double-click enters content nodes (Box, Reference, EditScope, …)"
        )
        self._cb_double_click.setChecked(prefs.double_click_enter_contents())
        prefs_box.addWidget(self._cb_double_click)

        self._cb_single_pane = QCheckBox("Navigate node contents through a single pane")
        self._cb_single_pane.setChecked(prefs.show_contents_single_pane())
        self._cb_single_pane.setStyleSheet("margin-left: 22px;")
        prefs_box.addWidget(self._cb_single_pane)

        self._cb_ctrl_node_editor = QCheckBox("Ctrl + Double-click opens Node editor panels")
        self._cb_ctrl_node_editor.setChecked(prefs.ctrl_double_click_node_editor())
        self._cb_ctrl_node_editor.setStyleSheet("margin-left: 22px;")
        prefs_box.addWidget(self._cb_ctrl_node_editor)

        self._cb_nav_menu = QCheckBox("Graph View right-click menu has navigation (◀ and /)")
        self._cb_nav_menu.setChecked(prefs.graph_view_nav_menu())
        prefs_box.addWidget(self._cb_nav_menu)

        self._cb_hierarchy_browse = QCheckBox(
            "Scene Hierarchy: browse without retriggering the Viewer"
        )
        self._cb_hierarchy_browse.setChecked(prefs.hierarchy_browse_only())
        self._cb_hierarchy_browse.setToolTip(
            "Expand / collapse locations in the Hierarchy View without "
            "updating the Visible Set. The Viewer stays stable while browsing."
        )
        prefs_box.addWidget(self._cb_hierarchy_browse)

        self._cb_mse = QCheckBox("Replace the Python Editor with pw_MultiScriptEditor")
        self._cb_mse.setChecked(prefs.use_multi_script_editor())
        self._cb_mse.setToolTip(
            "Applies the next time Gaffer starts. Startup adds the folder "
            "below to PYTHONPATH, then imports multi_script_editor.\n" + MSE_GITHUB
        )
        prefs_box.addWidget(self._cb_mse)

        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(22, 0, 0, 0)
        folder_row.setSpacing(8)
        folder_label = QLabel("Folder")
        folder_label.setToolTip(
            "Folder that contains the multi_script_editor package, "
            "or the package folder itself."
        )
        self._mse_folder = QLineEdit(prefs.multi_script_editor_folder())
        self._mse_folder.setPlaceholderText(
            "Path to pw_MultiScriptEditor (contains multi_script_editor)"
        )
        self._mse_folder.setToolTip(folder_label.toolTip() + "\n" + MSE_GITHUB)
        browse = QPushButton("Browse…")
        browse.setToolTip("Choose the pw_MultiScriptEditor folder")
        browse.clicked.connect(self._browse_mse_folder)
        folder_row.addWidget(folder_label)
        folder_row.addWidget(self._mse_folder, 1)
        folder_row.addWidget(browse)
        prefs_box.addLayout(folder_row)

        self._mse_status = QLabel("")
        self._mse_status.setStyleSheet("margin-left: 22px; color: #9a9a9a; font-size: 8pt;")
        prefs_box.addWidget(self._mse_status)
        self._mse_folder.textChanged.connect(self._refresh_mse_status)
        self._refresh_mse_status()

        root.addLayout(prefs_box)
        self._cb_double_click.toggled.connect(self._sync_enabled)
        self._sync_enabled()

        gaffer_dir = prefs.gaffer_user_dir()
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)
        footer.setSpacing(8)
        self._path_btn = QPushButton(gaffer_dir)
        self._path_btn.setFlat(True)
        self._path_btn.setCursor(QCursor(QtCore.Qt.PointingHandCursor))
        self._path_btn.setToolTip("Open user Gaffer folder:\n{}".format(gaffer_dir))
        self._path_btn.setStyleSheet(
            "QPushButton {"
            "  color: #ffaa00; background: transparent; border: none;"
            "  text-align: left; padding: 2px 0; font-size: 8pt;"
            "}"
            "QPushButton:hover { color: #ffcc55; text-decoration: underline; }"
        )
        self._path_btn.clicked.connect(lambda: _open_folder(gaffer_dir))
        footer.addWidget(self._path_btn, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setObjectName("PrimaryButton")
        buttons.accepted.connect(self._on_accept)
        footer.addWidget(buttons, 0)
        root.addLayout(footer)
        self._dialog.adjustSize()

    def _browse_mse_folder(self) -> None:
        from Qt.QtWidgets import QFileDialog

        current = self._mse_folder.text().strip()
        start = current if current and os.path.isdir(current) else os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(
            self._dialog,
            "pw_MultiScriptEditor folder",
            start,
        )
        if chosen:
            self._mse_folder.setText(os.path.normpath(chosen))

    def _refresh_mse_status(self, *_args) -> None:
        text = self._mse_folder.text().strip()
        if not text:
            self._mse_status.setText(
                "Choose the folder that contains multi_script_editor. "
                "Saved with these options and added to PYTHONPATH on the next launch."
            )
            self._mse_status.setStyleSheet("margin-left: 22px; color: #9a9a9a; font-size: 8pt;")
            return
        located = prefs.locate_multi_script_editor(text)
        if located:
            self._mse_status.setText("Found multi_script_editor. Applied the next time Gaffer starts.")
            self._mse_status.setStyleSheet("margin-left: 22px; color: #9dcc6a; font-size: 8pt;")
            return
        self._mse_status.setText(
            "Point this at the folder that contains the multi_script_editor package."
        )
        self._mse_status.setStyleSheet("margin-left: 22px; color: #d08080; font-size: 8pt;")

    def _sync_enabled(self, *_args) -> None:
        on = self._cb_double_click.isChecked()
        self._cb_single_pane.setEnabled(on)
        self._cb_ctrl_node_editor.setEnabled(on)

    def _on_accept(self) -> None:
        from Qt.QtWidgets import QDialog

        prefs.save(
            {
                DOUBLE_CLICK_ENTER: self._cb_double_click.isChecked(),
                SHOW_CONTENTS_SINGLE_PANE: self._cb_single_pane.isChecked(),
                CTRL_DOUBLE_CLICK_NODE_EDITOR: self._cb_ctrl_node_editor.isChecked(),
                GRAPH_VIEW_NAV_MENU: self._cb_nav_menu.isChecked(),
                HIERARCHY_BROWSE_ONLY: self._cb_hierarchy_browse.isChecked(),
                USE_MULTI_SCRIPT_EDITOR: self._cb_mse.isChecked(),
                MULTI_SCRIPT_EDITOR_FOLDER: self._mse_folder.text().strip(),
            }
        )
        try:
            from sdvTkGafferUI.uiTweaks import sync_graph_view_nav_menu

            sync_graph_view_nav_menu()
        except Exception:
            traceback.print_exc()
        self._dialog.done(QDialog.Accepted)

    def show_modal(self) -> None:
        _run(self._dialog)


def _open_folder(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    path = os.path.normpath(path)
    try:
        if os.name == "nt":
            os.startfile(path)  # noqa: S606
        else:
            import subprocess
            import sys

            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, path])  # noqa: S603
    except Exception as exc:
        print("[sdvTk] Could not open {}: {}".format(path, exc))


def _open_shader_manager(menu, *unused) -> None:
    _open_shading_manager(menu, "shader")


def _open_lights_manager(menu, *unused) -> None:
    script = _script_from_menu(menu)
    if script is None:
        return
    parent = None
    try:
        parent = menu.ancestor(GafferUI.ScriptWindow)
    except Exception:
        parent = None
    from sdvTkGafferUI.ShadingTkUI._lightsManager import acquire_lights_manager

    acquire_lights_manager(script, parent)


def _open_texture_manager(menu, *unused) -> None:
    _open_shading_manager(menu, "texture")


def _open_shading_manager(menu, kind: str) -> None:
    script = _script_from_menu(menu)
    if script is None:
        return
    from sdvTkGaffer.ShadingTk.ShadingTk import ShadingTk

    node = None
    try:
        for selected in script.selection():
            if isinstance(selected, ShadingTk):
                node = selected
                break
    except Exception:
        node = None
    if node is None:
        try:
            for candidate in Gaffer.Node.RecursiveRange(script):
                if isinstance(candidate, ShadingTk):
                    node = candidate
                    break
        except Exception:
            node = None
    if node is None:
        IECore.msg(
            IECore.Msg.Level.Warning,
            "sdvTk",
            "Add a ShadingTk node to open the {} Manager.".format(
                "Shader" if kind == "shader" else "Texture"
            ),
        )
        return
    parent = None
    try:
        parent = menu.ancestor(GafferUI.ScriptWindow)
    except Exception:
        parent = None
    if kind == "shader":
        from sdvTkGafferUI.ShadingTkUI._shaderManager import acquire_shader_manager

        acquire_shader_manager(node, parent)
        return
    from sdvTkGafferUI.ShadingTkUI._textureManager import acquire_texture_manager

    acquire_texture_manager(node, parent)
