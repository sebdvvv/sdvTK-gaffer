"""Snapshot tree of ShadingTk textures: TxLibrary + shader:input connections."""

from __future__ import annotations

import functools
import os

import Gaffer
import GafferUI
import IECore

from sdvTkGaffer.ShadingTk._textureIO import CONVERT_FORMATS, find_maketx, find_txmake
from ._editor import clear_container, expand_h, native_widget, param_label, plug_widget

_IMAGE_EXT = {".exr", ".tx", ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".hdr", ".tga"}
_PREVIEW_SIZE = 28


def _qt():
    from Qt import QtCore, QtGui, QtWidgets

    return QtCore, QtGui, QtWidgets


class TextureManagerWindow(GafferUI.Window):
    """Frozen tree of this ShadingTk plus textures fed from upstream nodes."""

    def __init__(self, node, **kw) -> None:
        kw.setdefault("sizeMode", GafferUI.Window.SizeMode.Manual)
        try:
            GafferUI.Window.__init__(self, "ShadingTk Texture Manager", **kw)
        except TypeError:
            kw.pop("sizeMode", None)
            GafferUI.Window.__init__(self, "ShadingTk Texture Manager", **kw)
        self.__node = node
        try:
            self.__node.ensureTextureSettingsPlugs()
        except Exception:
            pass
        self.__snapshot = {"library": [], "shaders": []}
        self.__icons: dict[str, object] = {}
        QtCore, QtGui, QtWidgets = _qt()

        column = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=6, borderWidth=8
        )
        main = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=6
        )
        header = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=6
        )
        self.__hint = GafferUI.Label(
            "TxLibrary holds textures stored on this node, plus any fed "
            "from upstream ShadingTk nodes. Select a texture to edit "
            "its attributes on the right. Drops stay on this node."
        )
        header.append(self.__hint, expand=True)
        expand_btn = GafferUI.Button("Expand")
        expand_btn.setToolTip("Expand the whole tree.")
        expand_btn.clickedSignal().connect(
            Gaffer.WeakMethod(self.__onExpandAll), scoped=True
        )
        collapse_btn = GafferUI.Button("Collapse")
        collapse_btn.setToolTip("Collapse the whole tree.")
        collapse_btn.clickedSignal().connect(
            Gaffer.WeakMethod(self.__onCollapseAll), scoped=True
        )
        refresh_btn = GafferUI.Button("Refresh")
        refresh_btn.setToolTip(
            "Reload the snapshot from this ShadingTk and upstream nodes."
        )
        refresh_btn.clickedSignal().connect(
            Gaffer.WeakMethod(self.refresh), scoped=True
        )
        header.append(expand_btn)
        header.append(collapse_btn)
        header.append(refresh_btn)
        main.append(header)

        tools = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=6
        )
        add_btn = GafferUI.Button("Add files…")
        add_btn.clickedSignal().connect(
            Gaffer.WeakMethod(self.__onAddFiles), scoped=True
        )
        tools.append(add_btn)
        remove_btn = GafferUI.Button("Remove selected")
        remove_btn.setToolTip(
            "Remove a texture stored on this ShadingTk from TxLibrary. "
            "Shader connections to it are disconnected first."
        )
        remove_btn.clickedSignal().connect(
            Gaffer.WeakMethod(self.__onRemove), scoped=True
        )
        tools.append(remove_btn)
        unused_btn = GafferUI.Button("Remove unused")
        unused_btn.setToolTip(
            "Remove TxLibrary textures on this node that are not "
            "connected to any shader input."
        )
        unused_btn.clickedSignal().connect(
            Gaffer.WeakMethod(self.__onRemoveUnused), scoped=True
        )
        tools.append(unused_btn)
        main.append(tools)

        self.__tree = _TextureTree(self)
        self.__treeWidget = GafferUI.Widget(self.__tree)
        self.__inspectorHint = GafferUI.Label(
            "Select a texture to edit its node attributes."
        )
        self.__inspectorForm = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=6
        )
        inspector = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=6, borderWidth=4
        )
        inspector.append(GafferUI.Label("<b>Attributes</b>"))
        inspector.append(self.__inspectorHint)
        inspector.append(self.__inspectorForm)
        inspector_scroll = GafferUI.ScrolledContainer(
            horizontalMode=GafferUI.ScrollMode.Never, borderWidth=0
        )
        inspector_scroll.setChild(inspector)
        try:
            split = GafferUI.SplitContainer(
                GafferUI.SplitContainer.Orientation.Horizontal
            )
            split.append(self.__treeWidget)
            split.append(inspector_scroll)
            main.append(split, expand=True)
        except Exception:
            row = GafferUI.ListContainer(
                GafferUI.ListContainer.Orientation.Horizontal, spacing=8
            )
            row.append(self.__treeWidget, expand=True)
            row.append(inspector_scroll, expand=True)
            main.append(row, expand=True)
        self.__selected = {}
        try:
            self.__tree.itemSelectionChanged.connect(self.__onTreeSelection)
        except Exception:
            pass
        try:
            QtCore, QtGui, QtWidgets = _qt()
            delete = QtWidgets.QShortcut(QtGui.QKeySequence.Delete, self.__tree)
            delete.activated.connect(self.__onRemove)
            self.__deleteShortcut = delete
        except Exception:
            pass

        settings = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=8, borderWidth=4
        )
        self.__buildSettings(settings)
        settings_scroll = GafferUI.ScrolledContainer(
            horizontalMode=GafferUI.ScrollMode.Never, borderWidth=0
        )
        settings_scroll.setChild(settings)
        self.__tabs = GafferUI.TabbedContainer()
        try:
            self.__tabs.append(main, "Main")
            self.__tabs.append(settings_scroll, "Settings")
        except TypeError:
            self.__tabs.addChild(main)
            self.__tabs.setLabel(main, "Main")
            self.__tabs.addChild(settings_scroll)
            self.__tabs.setLabel(settings_scroll, "Settings")
        try:
            signal = getattr(self.__tabs, "currentChangedSignal", None)
            if signal is None:
                signal = getattr(self.__tabs, "currentTabChangedSignal", None)
            if signal is not None:
                signal().connect(
                    Gaffer.WeakMethod(self.__onTabChanged), scoped=True
                )
        except Exception:
            pass
        column.append(self.__tabs, expand=True)
        self.__status = GafferUI.Label("")
        column.append(self.__status)
        self.setChild(column)
        try:
            self._qtWidget().resize(980, 560)
        except Exception:
            pass

        self.__dropEnter = self.dragEnterSignal().connect(
            Gaffer.WeakMethod(self.__dragEnter), scoped=True
        )
        self.__drop = self.dropSignal().connect(
            Gaffer.WeakMethod(self.__drop), scoped=True
        )
        try:
            self._qtWidget().setAcceptDrops(True)
        except Exception:
            pass
        self.__plugDirtied = self.__node.plugDirtiedSignal().connect(
            Gaffer.WeakMethod(self.__onSettingsPlug), scoped=True
        )
        self.refresh()

    def node(self):
        return self.__node

    def refresh(self, *unused) -> None:
        try:
            self.__snapshot = self.__node.textureManagerSnapshot() or {
                "library": [],
                "shaders": [],
            }
        except Exception as exc:
            self.__snapshot = {"library": [], "shaders": []}
            IECore.msg(IECore.Msg.Level.Warning, "ShadingTk", str(exc))
        self.__rebuildTree()
        self.__restoreSelection()
        self.__fillInspector()
        library = self.__snapshot.get("library") or []
        local = sum(1 for item in library if item.get("local"))
        inherited = len(library) - local
        try:
            self.__status.setText(
                "Snapshot — {} local, {} from upstream. Refresh to rescan.".format(
                    local, inherited
                )
            )
        except Exception:
            pass
        self.__refreshSettings()

    def __onTabChanged(self, *unused) -> None:
        self.__refreshSettings()

    def __onSettingsPlug(self, plug) -> None:
        try:
            name = plug.getName()
        except Exception:
            return
        if name in (
            "textureRoot",
            "textureUseExisting",
            "textureNextToScene",
            "textureOpenCommand",
        ):
            self.__refreshSettings()

    def __buildSettings(self, form: GafferUI.ListContainer) -> None:
        form.append(
            GafferUI.Label(
                "Dropped and imported textures are copied into the "
                "project texture folder before they are stored on this "
                "ShadingTk. That folder is saved with the node so a "
                "later session can scan and relink missing files."
            )
        )
        form.append(GafferUI.Label("Scene path"))
        self.__sceneField = GafferUI.TextWidget()
        try:
            self.__sceneField.setEditable(False)
        except Exception:
            pass
        form.append(self.__sceneField)
        form.append(GafferUI.Label("Project"))
        self.__projectField = GafferUI.TextWidget()
        try:
            self.__projectField.setEditable(False)
        except Exception:
            pass
        form.append(self.__projectField)
        form.append(GafferUI.Label("Context"))
        try:
            self.__contextField = GafferUI.MultiLineTextWidget()
        except Exception:
            self.__contextField = GafferUI.TextWidget()
        try:
            self.__contextField.setEditable(False)
        except Exception:
            pass
        form.append(self.__contextField)
        self.__addPlugRow(
            form,
            "Use existing file if already at destination",
            "textureUseExisting",
        )
        self.__addPlugRow(
            form,
            "Put textures next to the scene in /textures/",
            "textureNextToScene",
        )
        form.append(GafferUI.Label("Default texture location"))
        self.__addPlugRow(form, "Folder", "textureRoot")
        self.__resolvedField = GafferUI.TextWidget()
        try:
            self.__resolvedField.setEditable(False)
        except Exception:
            pass
        form.append(self.__resolvedField)
        reset_btn = GafferUI.Button("Use Gaffer project /texture")
        reset_btn.setToolTip(
            "Clear the override and use ~/gaffer/projects/<project>/texture "
            "or ${project:rootDirectory}/texture."
        )
        reset_btn.clickedSignal().connect(
            Gaffer.WeakMethod(self.__onResetTextureRoot), scoped=True
        )
        form.append(reset_btn)
        self.__addPlugRow(
            form,
            "Open command ({file})",
            "textureOpenCommand",
        )
        scan_btn = GafferUI.Button("Scan missing textures")
        scan_btn.setToolTip(
            "Search the texture folder, scene /textures/, and project "
            "root for files whose links are lost."
        )
        scan_btn.clickedSignal().connect(
            Gaffer.WeakMethod(self.__onScanTextures), scoped=True
        )
        form.append(scan_btn)

    def __addPlugRow(self, form, label: str, plug_name: str) -> None:
        row = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=6
        )
        row.append(GafferUI.Label(label))
        try:
            widget = native_widget(self.__node[plug_name])
        except Exception:
            widget = GafferUI.PlugValueWidget.create(self.__node[plug_name])
        if widget is not None:
            row.append(widget, expand=True)
        form.append(row)

    def __refreshSettings(self) -> None:
        info = {}
        try:
            info = self.__node.textureLocationInfo() or {}
        except Exception as exc:
            IECore.msg(IECore.Msg.Level.Warning, "ShadingTk", str(exc))
        scene = info.get("scene") or "(unsaved script)"
        project = info.get("project") or ""
        root = info.get("projectRoot") or ""
        project_text = project
        if root:
            project_text = "{} — {}".format(project, root) if project else root
        try:
            self.__sceneField.setText(scene)
            self.__projectField.setText(project_text or "(unknown)")
            lines = ["{} = {}".format(key, value) for key, value in (info.get("context") or [])]
            self.__contextField.setText("\n".join(lines) if lines else "(no project/script variables)")
            self.__resolvedField.setText(
                "Copying into: {}".format(info.get("resolvedDir") or "")
            )
        except Exception:
            pass

    def __onResetTextureRoot(self, *unused) -> None:
        script = self.__node.scriptNode()
        with Gaffer.UndoScope(script):
            self.__node.ensureTextureSettingsPlugs()
            self.__node["textureRoot"].setValue("")
            self.__node["textureNextToScene"].setValue(False)
        self.__refreshSettings()
        self.__setStatus("Using Gaffer project /texture.")

    def __onScanTextures(self, *unused) -> None:
        script = self.__node.scriptNode()
        with Gaffer.UndoScope(script):
            result = self.__node.scanLibraryTextures()
        self.refresh()
        relinked = result.get("relinked") or []
        missing = result.get("missing") or []
        self.__setStatus(
            "Scan: {} relinked, {} still missing.".format(len(relinked), len(missing))
        )

    def __rebuildTree(self) -> None:
        QtCore, QtGui, QtWidgets = _qt()
        role = QtCore.Qt.UserRole
        tree = self.__tree
        tree.clear()
        library_root = QtWidgets.QTreeWidgetItem(["TxLibrary", "", "This node + upstream"])
        library_root.setData(0, role, {"kind": "library"})
        tree.addTopLevelItem(library_root)
        for item in self.__snapshot.get("library") or []:
            source = "this node" if item.get("local") else (
                item.get("sourceNode") or "upstream"
            )
            child = QtWidgets.QTreeWidgetItem(
                [
                    item.get("name") or "",
                    os.path.basename(item.get("path") or ""),
                    source,
                ]
            )
            child.setData(
                0,
                role,
                {
                    "kind": "texture",
                    "name": item.get("name") or "",
                    "path": item.get("path") or "",
                    "local": bool(item.get("local")),
                    "sourceNode": item.get("sourceNode") or "",
                },
            )
            child.setIcon(0, self.__previewIcon(item.get("path") or ""))
            child.setToolTip(0, item.get("path") or "")
            library_root.addChild(child)

        for shader in self.__snapshot.get("shaders") or []:
            title = shader.get("name") or shader.get("key") or "shader"
            shader_item = QtWidgets.QTreeWidgetItem(
                [title, shader.get("type") or "", "shader"]
            )
            shader_item.setData(
                0,
                role,
                {
                    "kind": "shader",
                    "key": shader.get("key") or "",
                    "name": title,
                },
            )
            tree.addTopLevelItem(shader_item)
            grouped: dict[str, list] = {}
            order: list[str] = []
            for connection in shader.get("connections") or []:
                label = connection.get("label") or connection.get("plug") or ""
                if label not in grouped:
                    grouped[label] = []
                    order.append(label)
                grouped[label].append(connection)
            for label in order:
                connections = grouped[label]
                input_item = QtWidgets.QTreeWidgetItem([label, "", "input"])
                spec = connections[0]
                input_item.setData(
                    0,
                    role,
                    {
                        "kind": "input",
                        "key": shader.get("key") or "",
                        "plug": spec.get("plug") or "",
                        "component": spec.get("component") or "",
                        "label": label,
                    },
                )
                shader_item.addChild(input_item)
                for connection in connections:
                    name = connection.get("texture") or ""
                    if not name:
                        continue
                    tex = QtWidgets.QTreeWidgetItem(
                        [
                            name,
                            os.path.basename(connection.get("path") or ""),
                            "connected",
                        ]
                    )
                    tex.setData(
                        0,
                        role,
                        {
                            "kind": "connection",
                            "name": name,
                            "path": connection.get("path") or "",
                            "key": shader.get("key") or "",
                            "plug": connection.get("plug") or "",
                            "component": connection.get("component") or "",
                            "label": connection.get("label") or "",
                            "local": True,
                        },
                    )
                    tex.setIcon(0, self.__previewIcon(connection.get("path") or ""))
                    input_item.addChild(tex)
        tree.expandAll()

    def __previewIcon(self, path: str):
        QtCore, QtGui, QtWidgets = _qt()
        key = path or ""
        cached = self.__icons.get(key)
        if cached is not None:
            return cached
        size = QtCore.QSize(_PREVIEW_SIZE, _PREVIEW_SIZE)
        pixmap = QtGui.QPixmap(size)
        pixmap.fill(QtGui.QColor(42, 42, 46))
        if path and os.path.isfile(path):
            loaded = QtGui.QPixmap(path)
            if not loaded.isNull():
                pixmap = loaded.scaled(
                    size,
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation,
                )
        icon = QtGui.QIcon(pixmap)
        self.__icons[key] = icon
        return icon

    def __onExpandAll(self, *unused) -> None:
        self.__tree.expandAll()

    def __onCollapseAll(self, *unused) -> None:
        self.__tree.collapseAll()

    def selectedPayload(self) -> dict:
        items = self.__tree.selectedItems()
        if not items:
            return {}
        return self.payloadAt(items[0])

    def payloadAt(self, item) -> dict:
        if item is None:
            return {}
        QtCore, QtGui, QtWidgets = _qt()
        data = item.data(0, QtCore.Qt.UserRole) or {}
        return dict(data) if isinstance(data, dict) else {}

    def __onTreeSelection(self, *unused) -> None:
        self.__selected = self.selectedPayload()
        self.__fillInspector()

    def __restoreSelection(self) -> None:
        wanted = dict(self.__selected or {})
        if not wanted:
            return
        QtCore, QtGui, QtWidgets = _qt()
        role = QtCore.Qt.UserRole
        stack = []
        for index in range(self.__tree.topLevelItemCount()):
            stack.append(self.__tree.topLevelItem(index))
        match = None
        while stack:
            item = stack.pop()
            data = item.data(0, role) or {}
            if (
                data.get("kind") == wanted.get("kind")
                and data.get("name") == wanted.get("name")
                and data.get("plug") == wanted.get("plug")
                and data.get("component") == wanted.get("component")
            ):
                match = item
                break
            for index in range(item.childCount()):
                stack.append(item.child(index))
        if match is not None:
            try:
                self.__tree.blockSignals(True)
                self.__tree.setCurrentItem(match)
            finally:
                self.__tree.blockSignals(False)

    def __fillInspector(self) -> None:
        payload = self.selectedPayload() or self.__selected or {}
        clear_container(self.__inspectorForm)
        kind = payload.get("kind")
        name = payload.get("name") or ""
        if kind not in ("texture", "connection") or not name:
            try:
                self.__inspectorHint.setText(
                    "Select a texture to edit its node attributes."
                )
                self.__inspectorHint.setVisible(True)
            except Exception:
                pass
            return
        node = None
        try:
            node = self.__node.textureNodeByName(name)
        except Exception:
            node = None
        if node is None:
            try:
                self.__inspectorHint.setText(
                    "Texture '{}' is not stored on this ShadingTk.".format(name)
                )
                self.__inspectorHint.setVisible(True)
            except Exception:
                pass
            return
        try:
            self.__inspectorHint.setVisible(False)
        except Exception:
            pass
        self.__inspectorForm.append(GafferUI.Label("<b>{}</b>".format(name)))
        plugs = []
        try:
            plugs = list(self.__node.textureParameterPlugs(node))
        except Exception:
            plugs = []
        if not plugs:
            self.__inspectorForm.append(
                GafferUI.Label("No editable attributes on this texture.")
            )
            return
        for plug in plugs:
            widget = plug_widget(plug)
            if widget is None:
                continue
            row = GafferUI.ListContainer(
                GafferUI.ListContainer.Orientation.Horizontal, spacing=8
            )
            row.append(GafferUI.Label(param_label(plug)))
            expand_h(widget)
            row.append(widget, expand=True)
            self.__inspectorForm.append(row)

    def __onAddFiles(self, *unused) -> None:
        QtCore, QtGui, QtWidgets = _qt()
        chosen, _filter = QtWidgets.QFileDialog.getOpenFileNames(
            self._qtWidget(),
            "Add textures",
            "",
            "Images (*.exr *.tx *.tif *.tiff *.png *.jpg *.jpeg *.hdr *.tga);;All (*)",
        )
        self.addPaths(chosen)

    def __onRemove(self, *unused) -> None:
        payload = self.selectedPayload()
        kind = payload.get("kind")
        if kind == "connection":
            self.disconnectTexture(
                payload.get("key") or "",
                payload.get("plug") or "",
                payload.get("component") or "",
            )
            return
        if kind != "texture":
            self.__setStatus("Select a texture in TxLibrary to remove.")
            return
        if not payload.get("local"):
            self.__setStatus(
                "Inherited textures stay on {}.".format(
                    payload.get("sourceNode") or "the upstream ShadingTk"
                )
            )
            return
        name = payload.get("name") or ""
        if not name:
            return
        script = self.__node.scriptNode()
        with Gaffer.UndoScope(script):
            ok = self.__node.removeLibraryTexture(name)
        self.__selected = {}
        self.refresh()
        self.__setStatus(
            "Removed {}.".format(name) if ok else "Could not remove {}.".format(name)
        )

    def __onRemoveUnused(self, *unused) -> None:
        names = []
        try:
            names = list(self.__node.unusedLibraryTextureNames())
        except Exception:
            names = []
        if not names:
            self.__setStatus("No unused textures on this ShadingTk.")
            return
        script = self.__node.scriptNode()
        with Gaffer.UndoScope(script):
            removed = self.__node.removeUnusedLibraryTextures()
        self.__selected = {}
        self.refresh()
        self.__setStatus(
            "Removed {} unused texture{}.".format(
                len(removed), "" if len(removed) == 1 else "s"
            )
        )

    def __dragEnter(self, widget, event) -> bool:
        return bool(self.__pathsFromEvent(event))

    def __drop(self, widget, event) -> bool:
        paths = self.__pathsFromEvent(event)
        if not paths:
            return False
        self.addPaths(paths)
        return True

    def addPaths(self, paths) -> None:
        added = 0
        script = self.__node.scriptNode()
        with Gaffer.UndoScope(script):
            for raw in paths:
                path = str(raw or "").replace("\\", "/").strip()
                if not path or not os.path.isfile(path):
                    continue
                try:
                    self.__node.ingestLibraryTexture(path)
                    added += 1
                except Exception as exc:
                    IECore.msg(IECore.Msg.Level.Warning, "ShadingTk", str(exc))
        self.refresh()
        self.__setStatus(
            "Stored {} texture{} on this ShadingTk.".format(
                added, "" if added == 1 else "s"
            )
        )

    def connectTexture(
        self, texture_name: str, shader_key: str, plug_name: str, component: str = ""
    ) -> None:
        if not texture_name or not shader_key or not plug_name:
            return
        script = self.__node.scriptNode()
        with Gaffer.UndoScope(script):
            ok = self.__node.connectLibraryTexture(
                texture_name, shader_key, plug_name, component
            )
        self.refresh()
        self.__setStatus(
            "Connected {} to {}.".format(
                texture_name, "{}.{}".format(plug_name, component) if component else plug_name
            )
            if ok
            else "Could not connect {}.".format(texture_name)
        )

    def disconnectTexture(
        self, shader_key: str, plug_name: str, component: str = ""
    ) -> None:
        script = self.__node.scriptNode()
        with Gaffer.UndoScope(script):
            ok = self.__node.disconnectLibraryTexture(shader_key, plug_name, component)
        self.refresh()
        self.__setStatus("Disconnected." if ok else "Nothing to disconnect.")

    def showItemMenu(self, item, global_pos) -> None:
        payload = self.payloadAt(item)
        kind = payload.get("kind")
        if kind not in ("texture", "connection"):
            return
        QtCore, QtGui, QtWidgets = _qt()
        menu = QtWidgets.QMenu(self.__tree)
        texture_name = payload.get("name") or ""
        local = self.__isLocalTexture(texture_name, payload)
        rename = menu.addAction("Rename…")
        rename.setEnabled(local)
        rename.triggered.connect(
            functools.partial(self.__renameFromMenu, texture_name)
        )
        open_act = menu.addAction("Open")
        open_act.triggered.connect(
            functools.partial(
                self.__openFromMenu, texture_name, payload.get("path") or "", ""
            )
        )
        open_with = menu.addMenu("Open With")
        default_open = open_with.addAction("Default application")
        default_open.triggered.connect(
            functools.partial(
                self.__openFromMenu,
                texture_name,
                payload.get("path") or "",
                "__default__",
            )
        )
        custom_open = open_with.addAction("Custom command…")
        custom_open.triggered.connect(
            functools.partial(
                self.__openWithCommandFromMenu,
                texture_name,
                payload.get("path") or "",
            )
        )
        convert_menu = menu.addMenu("Convert To")
        for ext, label in CONVERT_FORMATS:
            action = convert_menu.addAction(label)
            action.triggered.connect(
                functools.partial(self.__convertFromMenu, texture_name, ext)
            )
        if find_maketx():
            action = convert_menu.addAction("TX (Arnold maketx)")
            action.triggered.connect(
                functools.partial(self.__convertFromMenu, texture_name, "tx")
            )
        if find_txmake():
            action = convert_menu.addAction("TEX (RenderMan txmake)")
            action.triggered.connect(
                functools.partial(self.__convertFromMenu, texture_name, "tex")
            )
        menu.addSeparator()
        remove_act = menu.addAction("Remove from TxLibrary")
        remove_act.setEnabled(local)
        remove_act.triggered.connect(
            functools.partial(self.__removeFromMenu, texture_name)
        )
        menu.addSeparator()
        connect_menu = menu.addMenu("Connect To")
        shaders = list(self.__snapshot.get("shaders") or [])
        if not shaders:
            action = connect_menu.addAction("No shaders in this snapshot")
            action.setEnabled(False)
        for shader in shaders:
            shader_menu = connect_menu.addMenu(shader.get("name") or shader.get("key"))
            live = self.__node.shaderFromTextureManagerKey(shader.get("key") or "")
            inputs = []
            try:
                inputs = list(self.__node.connectableTextureInputs(live))
            except Exception:
                inputs = []
            if not inputs:
                empty = shader_menu.addAction("No color / RGB / RGBA inputs")
                empty.setEnabled(False)
                continue
            self.__fillConnectInputMenu(
                shader_menu, texture_name, shader.get("key") or "", inputs
            )
        disconnect_menu = menu.addMenu("Disconnect From")
        targets = self.__disconnectTargets(texture_name)
        if not targets:
            action = disconnect_menu.addAction("Not connected in this snapshot")
            action.setEnabled(False)
        for target in targets:
            label = "{} / {}".format(target["shader"], target["label"])
            action = disconnect_menu.addAction(label)
            action.triggered.connect(
                functools.partial(
                    self.__disconnectFromMenu,
                    target["key"],
                    target["plug"],
                    target["component"],
                )
            )
        popup = getattr(menu, "exec", None)
        if popup is None:
            popup = menu.exec_
        popup(global_pos)

    def __isLocalTexture(self, texture_name: str, payload: dict) -> bool:
        if payload.get("kind") == "texture":
            return bool(payload.get("local"))
        for item in self.__snapshot.get("library") or []:
            if item.get("name") == texture_name:
                return bool(item.get("local"))
        return False

    def __removeFromMenu(self, texture_name: str, *unused) -> None:
        if not texture_name:
            return
        script = self.__node.scriptNode()
        with Gaffer.UndoScope(script):
            ok = self.__node.removeLibraryTexture(texture_name)
        self.__selected = {}
        self.refresh()
        self.__setStatus(
            "Removed {}.".format(texture_name)
            if ok
            else "Could not remove {}.".format(texture_name)
        )

    def __renameFromMenu(self, texture_name: str, *unused) -> None:
        QtCore, QtGui, QtWidgets = _qt()
        text, accepted = QtWidgets.QInputDialog.getText(
            self.__tree,
            "Rename texture",
            "Name",
            text=texture_name,
        )
        if not accepted or not str(text).strip():
            return
        script = self.__node.scriptNode()
        try:
            with Gaffer.UndoScope(script):
                renamed = self.__node.renameLibraryTexture(texture_name, str(text))
        except Exception as exc:
            self.__setStatus(str(exc))
            return
        self.refresh()
        self.__setStatus("Renamed to {}.".format(renamed))

    def __openFromMenu(
        self, texture_name: str, path: str, command: str, *unused
    ) -> None:
        try:
            self.__node.openLibraryTexture(texture_name, path=path, command=command)
        except Exception as exc:
            self.__setStatus(str(exc))

    def __openWithCommandFromMenu(
        self, texture_name: str, path: str, *unused
    ) -> None:
        QtCore, QtGui, QtWidgets = _qt()
        current = ""
        try:
            current = self.__node["textureOpenCommand"].getValue() or ""
        except Exception:
            current = ""
        text, accepted = QtWidgets.QInputDialog.getText(
            self.__tree,
            "Open with command",
            "Command ({file} is the texture path)",
            text=current,
        )
        if not accepted:
            return
        command = str(text or "").strip()
        script = self.__node.scriptNode()
        with Gaffer.UndoScope(script):
            self.__node.ensureTextureSettingsPlugs()
            self.__node["textureOpenCommand"].setValue(command)
        self.__openFromMenu(texture_name, path, command)

    def __convertFromMenu(self, texture_name: str, extension: str, *unused) -> None:
        script = self.__node.scriptNode()
        try:
            with Gaffer.UndoScope(script):
                stored = self.__node.convertLibraryTexture(texture_name, extension)
        except Exception as exc:
            self.__setStatus(str(exc))
            return
        self.refresh()
        self.__setStatus("Converted to {}.".format(stored))

    def __fillConnectInputMenu(
        self, menu, texture_name: str, shader_key: str, inputs: list
    ) -> None:
        grouped = self.__groupConnectInputs(inputs)
        id_groups = []
        for plug, group in grouped:
            if self.__isIdInputName(plug):
                id_groups.append((plug, group))
            else:
                self.__addPlugConnectItems(
                    menu, texture_name, shader_key, plug, group
                )
        if not id_groups:
            return
        id_menu = menu.addMenu("id")
        for plug, group in id_groups:
            self.__addPlugConnectItems(
                id_menu, texture_name, shader_key, plug, group
            )

    def __addPlugConnectItems(
        self, menu, texture_name: str, shader_key: str, plug: str, group: dict
    ) -> None:
        whole = group.get("whole")
        components = list(group.get("components") or [])
        if not components:
            if whole:
                action = menu.addAction(plug)
                action.triggered.connect(
                    functools.partial(
                        self.__connectFromMenu,
                        texture_name,
                        shader_key,
                        plug,
                        "",
                    )
                )
            return
        plug_menu = menu.addMenu(plug)
        if whole:
            action = plug_menu.addAction(plug)
            action.triggered.connect(
                functools.partial(
                    self.__connectFromMenu,
                    texture_name,
                    shader_key,
                    plug,
                    "",
                )
            )
        for spec in components:
            channel = spec.get("component") or ""
            label = spec.get("label") or (
                "{}.{}".format(plug, channel) if channel else plug
            )
            action = plug_menu.addAction(label)
            action.triggered.connect(
                functools.partial(
                    self.__connectFromMenu,
                    texture_name,
                    shader_key,
                    spec.get("plug") or plug,
                    channel,
                )
            )

    @staticmethod
    def __groupConnectInputs(inputs: list) -> list:
        order = []
        grouped = {}
        for spec in inputs:
            plug = spec.get("plug") or spec.get("label") or ""
            if plug not in grouped:
                grouped[plug] = {"whole": None, "components": []}
                order.append(plug)
            if spec.get("component"):
                grouped[plug]["components"].append(spec)
            else:
                grouped[plug]["whole"] = spec
        return [(plug, grouped[plug]) for plug in order]

    @staticmethod
    def __isIdInputName(name: str) -> bool:
        text = str(name or "")
        if not text:
            return False
        lower = text.lower()
        return lower.startswith("id")

    def __connectFromMenu(
        self, texture_name: str, shader_key: str, plug_name: str, component: str, *unused
    ) -> None:
        self.connectTexture(texture_name, shader_key, plug_name, component)

    def __disconnectFromMenu(
        self, shader_key: str, plug_name: str, component: str, *unused
    ) -> None:
        self.disconnectTexture(shader_key, plug_name, component)

    def __disconnectTargets(self, texture_name: str) -> list[dict]:
        found = []
        for shader in self.__snapshot.get("shaders") or []:
            for connection in shader.get("connections") or []:
                if not connection.get("texture") or connection.get("texture") != texture_name:
                    continue
                found.append(
                    {
                        "key": shader.get("key") or "",
                        "shader": shader.get("name") or "",
                        "plug": connection.get("plug") or "",
                        "component": connection.get("component") or "",
                        "label": connection.get("label") or connection.get("plug") or "",
                    }
                )
        return found

    def __setStatus(self, text: str) -> None:
        try:
            self.__status.setText(text)
        except Exception:
            pass

    @staticmethod
    def __pathsFromEvent(event) -> list[str]:
        data = getattr(event, "data", None)
        found = []
        if isinstance(data, str):
            found.append(data)
        elif isinstance(data, (list, tuple)):
            found.extend(str(item) for item in data)
        else:
            getter = getattr(data, "value", None)
            if isinstance(getter, str):
                found.append(getter)
        paths = []
        for raw in found:
            text = str(raw or "").replace("\\", "/").strip()
            if text.startswith("file://"):
                text = text[7:]
            ext = os.path.splitext(text)[1].lower()
            if ext in _IMAGE_EXT or os.path.isfile(text):
                paths.append(text)
        return paths


class _TextureTree:
    """QTreeWidget host — constructed so GafferUI.Widget can wrap it."""

    def __new__(cls, owner: TextureManagerWindow):
        QtCore, QtGui, QtWidgets = _qt()

        class _Tree(QtWidgets.QTreeWidget):
            def __init__(self) -> None:
                QtWidgets.QTreeWidget.__init__(self)
                self._owner = owner
                self.setColumnCount(3)
                self.setHeaderLabels(["Name", "File", "Source"])
                self.setRootIsDecorated(True)
                self.setAlternatingRowColors(True)
                self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
                self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
                self.setDragEnabled(True)
                self.setAcceptDrops(True)
                self.setDropIndicatorShown(True)
                self.setIconSize(QtCore.QSize(_PREVIEW_SIZE, _PREVIEW_SIZE))
                self.setExpandsOnDoubleClick(True)
                self.customContextMenuRequested.connect(self._onMenu)
                try:
                    self.header().setStretchLastSection(True)
                    self.setColumnWidth(0, 260)
                    self.setColumnWidth(1, 220)
                except Exception:
                    pass

            def _onMenu(self, pos) -> None:
                item = self.itemAt(pos)
                if item is None:
                    return
                self._owner.showItemMenu(item, self.viewport().mapToGlobal(pos))

            def mimeTypes(self):
                types = list(QtWidgets.QTreeWidget.mimeTypes(self))
                types.append("application/x-shadingtk-texture")
                types.append("text/uri-list")
                return types

            def mimeData(self, items):
                data = QtWidgets.QTreeWidget.mimeData(self, items)
                if not items:
                    return data
                payload = self._owner.payloadAt(items[0])
                if payload.get("kind") in ("texture", "connection") and payload.get("name"):
                    data.setData(
                        "application/x-shadingtk-texture",
                        bytes(payload.get("name") or "", "utf-8"),
                    )
                return data

            def dragEnterEvent(self, event) -> None:
                mime = event.mimeData()
                if mime.hasUrls() or mime.hasFormat("application/x-shadingtk-texture"):
                    event.acceptProposedAction()
                    return
                QtWidgets.QTreeWidget.dragEnterEvent(self, event)

            def dragMoveEvent(self, event) -> None:
                event.acceptProposedAction()

            def dropEvent(self, event) -> None:
                mime = event.mimeData()
                if mime.hasUrls():
                    paths = []
                    for url in mime.urls():
                        local = url.toLocalFile() if hasattr(url, "toLocalFile") else ""
                        if local:
                            paths.append(local)
                    self._owner.addPaths(paths)
                    event.acceptProposedAction()
                    return
                if mime.hasFormat("application/x-shadingtk-texture"):
                    raw = bytes(mime.data("application/x-shadingtk-texture")).decode(
                        "utf-8"
                    )
                    pos = event.pos() if hasattr(event, "pos") else event.position().toPoint()
                    target = self.itemAt(pos)
                    payload = self._owner.payloadAt(target)
                    shader_key = payload.get("key") or ""
                    plug = payload.get("plug") or ""
                    component = payload.get("component") or ""
                    if payload.get("kind") == "shader":
                        node = self._owner.node()
                        shader = node.shaderFromTextureManagerKey(shader_key)
                        inputs = node.connectableTextureInputs(shader)
                        color = next(
                            (item for item in inputs if not item.get("component")),
                            None,
                        )
                        if color:
                            plug = color.get("plug") or ""
                            component = ""
                    if shader_key and plug:
                        self._owner.connectTexture(raw, shader_key, plug, component)
                        event.acceptProposedAction()
                        return
                    event.ignore()
                    return
                QtWidgets.QTreeWidget.dropEvent(self, event)

        return _Tree()
