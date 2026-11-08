"""Shader Manager: shaders in connection order, attributes on the right."""

from __future__ import annotations

import functools
import os

import imath

import Gaffer
import GafferUI
import IECore

from sdvTkGaffer.ShadingTk._data import (
    displacement_type_plug,
    shader_file_prefix,
    shader_type_plug,
    slot_label,
)
from ._editor import (
    clear_container,
    expand_h,
    native_widget,
    param_label,
    plug_widget,
)

_LABEL_W = 130


def acquire_shader_manager(node, parent=None, key: str | None = None):
    """Open ShadingTk Manager on the Shaders tab."""
    from ._managerWindow import acquire_shadingtk_manager

    shader_key = (key or "").strip() or None
    return acquire_shadingtk_manager(
        node, parent, page="shaders", shader_key=shader_key
    )


def _qt():
    from Qt import QtCore, QtGui, QtWidgets

    return QtCore, QtGui, QtWidgets


def _payload_matches(data, wanted: dict) -> bool:
    """Match a tree row. Fields omitted from ``wanted`` are not compared."""
    if not isinstance(data, dict) or not wanted:
        return False
    if data.get("kind") != wanted.get("kind"):
        return False
    for field in ("key", "name", "label", "path"):
        if field not in wanted:
            continue
        if (data.get(field) or "") != (wanted.get(field) or ""):
            return False
    return True


def _spaced(name: str) -> str:
    text = (name or "").replace(".", " ").replace("_", " ")
    return " ".join(part.capitalize() for part in text.split()) or name


class ShaderManagerWindow(GafferUI.ListContainer):
    """Shader-centric tree. The right pane is the shader attribute editor."""

    def __init__(self, node, **kw) -> None:
        GafferUI.ListContainer.__init__(
            self,
            GafferUI.ListContainer.Orientation.Vertical,
            spacing=6,
            borderWidth=8,
            **kw,
        )
        self.__node = node
        self.__selected = {}
        self.__watched: set[int] = set()
        self.__refreshing = False
        self.__connections: list = []
        self.__txtConnections: list = []
        QtCore, QtGui, QtWidgets = _qt()

        header = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=6
        )
        header.append(
            GafferUI.Label(
                "Shaders in the order they connect. A texture or the shader "
                "itself is the end of each branch. Select a shader to edit "
                "its attributes."
            ),
            expand=True,
        )
        expand_btn = GafferUI.Button("Expand")
        self.__connections.append(
            expand_btn.clickedSignal().connect(
                Gaffer.WeakMethod(self.__onExpandAll), scoped=True
            )
        )
        collapse_btn = GafferUI.Button("Collapse")
        self.__connections.append(
            collapse_btn.clickedSignal().connect(
                Gaffer.WeakMethod(self.__onCollapseAll), scoped=True
            )
        )
        refresh_btn = GafferUI.Button("Refresh")
        self.__connections.append(
            refresh_btn.clickedSignal().connect(
                Gaffer.WeakMethod(self.refresh), scoped=True
            )
        )
        header.append(expand_btn)
        header.append(collapse_btn)
        header.append(refresh_btn)
        self.append(header)

        self.__tree = _ShaderTree(self)
        self.__treeWidget = GafferUI.Widget(self.__tree)
        self.__inspectorHint = GafferUI.Label("Select a shader to edit its attributes.")
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
            self.append(split, expand=True)
        except Exception:
            row = GafferUI.ListContainer(
                GafferUI.ListContainer.Orientation.Horizontal, spacing=8
            )
            row.append(self.__treeWidget, expand=True)
            row.append(inspector_scroll, expand=True)
            self.append(row, expand=True)
        try:
            self.__tree.itemSelectionChanged.connect(self.__onTreeSelection)
        except Exception:
            pass
        self.__status = GafferUI.Label("")
        self.append(self.__status)
        try:
            self.__connections.append(
                self.__node.plugSetSignal().connect(
                    Gaffer.WeakMethod(self.__onNodePlug), scoped=True
                )
            )
        except Exception:
            pass
        self.refresh()

    def node(self):
        return self.__node

    def showShader(self, key: str) -> None:
        key = (key or "").strip()
        if not key:
            return
        self.__selected = {"kind": "shader", "key": key}
        self.refresh()
        try:
            self.setVisible(True)
            self.reveal()
        except Exception:
            pass

    def refresh(self, *unused) -> None:
        if self.__refreshing:
            return
        self.__refreshing = True
        try:
            try:
                snapshot = self.__node.shaderManagerSnapshot() or {"roots": []}
            except Exception as exc:
                snapshot = {"roots": []}
                IECore.msg(IECore.Msg.Level.Warning, "ShadingTk", str(exc))
            self.__snapshot = snapshot
            self.__rebuildTree()
            self.__restoreSelection()
            self.__fillInspector()
            count = self.__countShaders(snapshot.get("roots") or [])
            try:
                self.__status.setText("{} shader{}.".format(count, "" if count == 1 else "s"))
            except Exception:
                pass
        finally:
            self.__refreshing = False

    def __onNodePlug(self, plug) -> None:
        name = plug.getName() if plug is not None else ""
        structural = (
            name in ("slotCount", "mixEnabled", "mixType", "mixName", "mixCount", "globalAssign", "matteEnabled", "diagEnabled", "diagShader", "oslCount")
            or name.startswith("shaderType")
            or name.startswith("shaderName")
            or name.startswith("oslName")
            or name.startswith("oslExternal")
            or name.startswith("textureType")
            or name.startswith("displacementType")
            or name.startswith("mixInput")
        )
        if structural:
            self.refresh()

    def __onShaderInput(self, plug) -> None:
        self.refresh()

    def __watch(self, node) -> None:
        if node is None or id(node) in self.__watched:
            return
        self.__watched.add(id(node))
        try:
            node.plugInputChangedSignal().connect(
                Gaffer.WeakMethod(self.__onShaderInput), scoped=True
            )
        except Exception:
            pass

    def __countShaders(self, roots) -> int:
        total = 0
        for item in roots:
            total += 1
            total += self.__countShaders(item.get("children") or [])
        return total

    def __rebuildTree(self) -> None:
        QtCore, QtGui, QtWidgets = _qt()
        tree = self.__tree
        tree.clear()
        role = QtCore.Qt.UserRole
        for root in self.__snapshot.get("roots") or []:
            self.__addShaderItem(tree, None, root, role)
        watched = set()
        self.__watchTree(self.__snapshot.get("roots") or [], watched)

    def __watchTree(self, nodes, watched) -> None:
        for item in nodes:
            key = item.get("key") or ""
            try:
                shader = self.__node.shaderFromManagerKey(key)
            except Exception:
                shader = None
            if shader is not None and id(shader) not in watched:
                watched.add(id(shader))
                self.__watch(shader)
            self.__watchTree(item.get("children") or [], watched)

    def __addShaderItem(self, tree, parent, data, role) -> None:
        QtCore, QtGui, QtWidgets = _qt()
        item = QtWidgets.QTreeWidgetItem(
            [data.get("name") or data.get("key") or "shader", data.get("type") or "", "shader"]
        )
        item.setData(
            0,
            role,
            {"kind": "shader", "key": data.get("key") or "", "name": data.get("name") or ""},
        )
        if parent is None:
            tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        item.setExpanded(True)
        for child in data.get("children") or []:
            self.__addShaderItem(tree, item, child, role)
        for endpoint in data.get("endpoints") or []:
            label = _spaced(endpoint.get("label") or "")
            name = endpoint.get("name") or ""
            path = endpoint.get("path") or ""
            detail = os.path.basename(path) if path else name
            leaf = QtWidgets.QTreeWidgetItem([label, detail, "texture"])
            leaf.setData(
                0,
                role,
                {
                    "kind": "texture",
                    "name": name,
                    "path": path,
                    "label": endpoint.get("label") or "",
                    "state": endpoint.get("state") or "",
                },
            )
            color = None
            if endpoint.get("state") == "missing":
                color = QtGui.QColor("#e53935")
            elif endpoint.get("state") == "connected":
                color = QtGui.QColor("#43a047")
            if color is not None:
                leaf.setForeground(0, color)
                leaf.setForeground(1, color)
            item.addChild(leaf)

    def __onExpandAll(self, *unused) -> None:
        self.__tree.expandAll()

    def __onCollapseAll(self, *unused) -> None:
        self.__tree.collapseAll()

    def __onTreeSelection(self, *unused) -> None:
        items = self.__tree.selectedItems()
        if not items:
            self.__selected = {}
        else:
            self.__selected = self.__payload(items[0])
        if not self.__refreshing:
            self.__fillInspector()

    def __payload(self, item) -> dict:
        if item is None:
            return {}
        QtCore, QtGui, QtWidgets = _qt()
        data = item.data(0, QtCore.Qt.UserRole) or {}
        return dict(data) if isinstance(data, dict) else {}

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
            if _payload_matches(data, wanted):
                match = item
                break
            for index in range(item.childCount()):
                stack.append(item.child(index))
        if match is None:
            return
        parent = match.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        try:
            self.__tree.blockSignals(True)
            self.__tree.clearSelection()
            match.setSelected(True)
            self.__tree.setCurrentItem(match)
            self.__tree.scrollToItem(match)
        finally:
            self.__tree.blockSignals(False)

    def __fillInspector(self) -> None:
        self.__txtConnections.clear()
        clear_container(self.__inspectorForm)
        payload = dict(self.__selected or {})
        kind = payload.get("kind")
        if kind == "texture":
            self.__fillTexture(payload)
            return
        if kind != "shader":
            try:
                self.__inspectorHint.setText("Select a shader to edit its attributes.")
                self.__inspectorHint.setVisible(True)
            except Exception:
                pass
            return
        try:
            self.__inspectorHint.setVisible(False)
        except Exception:
            pass
        key = payload.get("key") or ""
        try:
            shader = self.__node.shaderFromManagerKey(key)
        except Exception:
            shader = None
        if shader is None:
            self.__inspectorForm.append(GafferUI.Label("This shader is not available."))
            return
        title = payload.get("name") or key
        shader_type = ""
        try:
            if "name" in shader:
                shader_type = shader["name"].getValue() or ""
        except Exception:
            shader_type = ""
        header = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=6
        )
        header.append(GafferUI.Label("<b>{}</b>".format(title)))
        if shader_type:
            header.append(GafferUI.Label(shader_type))
        header.append(GafferUI.Spacer(imath.V2i(8, 1)), expand=True)
        if key.startswith("slot:"):
            try:
                index = int(key.split(":", 1)[1])
            except Exception:
                index = 0
            if index:
                presets = GafferUI.MenuButton(
                    "Presets",
                    menu=GafferUI.Menu(functools.partial(self.__presetMenu, index)),
                )
                header.append(presets)
        self.__inspectorForm.append(header)
        if key.startswith("slot:"):
            try:
                self.__addRow("Preset Folder", native_widget(self.__node["presetFolder"]))
            except Exception:
                pass
        self.__inspectorForm.append(GafferUI.Label("Material"))
        plugs = []
        try:
            plugs = list(self.__node._editable_params(shader))
        except Exception:
            plugs = []
        if key == "mix":
            plugs = [
                plug
                for plug in plugs
                if not plug.getName().startswith(("input", "shader", "enable"))
            ]
        for plug in plugs:
            self.__addParamRow(plug)
        if key.startswith("slot:"):
            self.__addDisplacement(int(key.split(":", 1)[1]))

    def __fillTexture(self, payload) -> None:
        try:
            self.__inspectorHint.setVisible(False)
        except Exception:
            pass
        name = payload.get("name") or ""
        try:
            node = self.__node.textureNodeByName(name)
        except Exception:
            node = None
        if node is None:
            self.__inspectorForm.append(GafferUI.Label("Texture '{}' is not on this node.".format(name)))
            return
        self.__inspectorForm.append(GafferUI.Label("<b>{}</b>".format(name)))
        plugs = []
        try:
            plugs = list(self.__node.textureParameterPlugs(node))
        except Exception:
            plugs = []
        for plug in plugs:
            self.__addParamRow(plug)

    def __addDisplacement(self, index: int) -> None:
        self.__inspectorForm.append(GafferUI.Label("<b>Displacement</b>"))
        try:
            self.__addRow("Map", native_widget(self.__node[displacement_type_plug(index)]))
        except Exception:
            return
        kind = ""
        try:
            kind = (self.__node[displacement_type_plug(index)].getValue() or "").strip()
        except Exception:
            kind = ""
        if not kind:
            return
        try:
            plugs = list(self.__node.displacementParameterPlugs(index))
        except Exception:
            plugs = []
        for plug in plugs:
            self.__addParamRow(plug)

    def __addParamRow(self, plug) -> None:
        widget = plug_widget(plug)
        if widget is None:
            return
        label = param_label(plug)
        try:
            marked = bool(self.__node.plugHasTextureInput(plug))
        except Exception:
            marked = False
        if marked:
            label = '<font color="#43a047">{} (has Textures)</font>'.format(label)
        row = self.__addRow(label, widget, text=marked)
        self.__addTxt(row, plug)

    def __addRow(self, label, widget, text=False):
        row = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=8
        )
        lbl = GafferUI.Label(label)
        try:
            if not text:
                lbl._qtWidget().setFixedWidth(_LABEL_W)
        except Exception:
            pass
        row.append(lbl)
        expand_h(widget)
        row.append(widget, expand=True)
        self.__inspectorForm.append(row)
        return row

    def __addTxt(self, row, plug) -> None:
        try:
            accepts = self.__node.plugAcceptsRgbTexture(plug)
        except Exception:
            accepts = False
        if not accepts:
            return
        button = GafferUI.Button("TXT")
        try:
            button._qtWidget().setFixedWidth(46)
        except Exception:
            pass
        self.__styleTxt(button, plug)
        self.__txtConnections.append(
            button.clickedSignal().connect(
                functools.partial(Gaffer.WeakMethod(self.__onTxt), plug),
                scoped=True,
            )
        )
        row.append(button)

    def __styleTxt(self, button, plug) -> None:
        state = "none"
        path = ""
        node_name = ""
        try:
            state = self.__node.texturePlugState(plug)
        except Exception:
            state = "none"
        source = None
        try:
            source = self.__node.textureSourceNode(plug)
        except Exception:
            source = None
        if source is not None:
            try:
                node_name = source.getName() or ""
            except Exception:
                node_name = ""
            try:
                if "parameters" in source and "filename" in source["parameters"]:
                    path = source["parameters"]["filename"].getValue() or ""
            except Exception:
                path = ""
        colors = {
            "none": ("#5e5e5e", "#e6e6e6"),
            "connected": ("#2e7d32", "#ffffff"),
            "missing": ("#c62828", "#ffffff"),
        }
        background, foreground = colors.get(state, colors["none"])
        try:
            button._qtWidget().setStyleSheet(
                "QPushButton {{ background-color: {}; color: {}; "
                "border: 1px solid #222222; border-radius: 2px; "
                "font-weight: bold; padding: 1px 4px; }}".format(background, foreground)
            )
        except Exception:
            pass
        if state == "none":
            tip = "Choose a texture or a file texture for this colour."
        elif state == "missing":
            tip = "Texture file is missing ({}). Opens the texture node.".format(path or node_name or "empty path")
        else:
            tip = "Opens {}.".format(node_name or "the texture node")
            if path:
                tip = "Opens {} ({})".format(node_name or "texture", path)
        try:
            button.setToolTip(tip)
        except Exception:
            pass

    def __onTxt(self, plug, *unused) -> None:
        try:
            state = self.__node.texturePlugState(plug)
        except Exception:
            state = "none"
        try:
            if state == "none":
                self.__chooseTexture(plug)
            else:
                source = None
                try:
                    source = self.__node.textureSourceNode(plug)
                except Exception:
                    source = None
                self.__openTexture(source)
        except Exception as exc:
            IECore.msg(IECore.Msg.Level.Warning, "ShadingTk", str(exc))
        self.refresh()

    def __chooseTexture(self, plug) -> None:
        from Qt.QtWidgets import QComboBox, QDialog, QVBoxLayout

        dialog = QDialog(self._qtWidget().window())
        dialog.setWindowTitle("Texture")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)
        combo = QComboBox()
        combo.addItem("None", "")
        combo.addItem("File texture…", "__file__")
        try:
            choices = list(self.__node.texturePlugChoices())
        except Exception:
            choices = []
        for value, label in choices:
            combo.addItem(label, value)
        layout.addWidget(combo)
        picked = {"value": None}

        def _activate(index) -> None:
            picked["value"] = combo.itemData(index)
            dialog.accept()

        combo.activated.connect(_activate)
        dialog.setFixedWidth(280)
        runner = getattr(dialog, "exec", None) or dialog.exec_
        if runner() != QDialog.Accepted:
            return
        value = picked["value"]
        if value is None:
            value = ""
        value = str(value)
        script = self.__node.scriptNode()
        node = None
        if value == "__file__":
            from Qt.QtWidgets import QFileDialog

            chosen, _filter = QFileDialog.getOpenFileName(
                dialog,
                "File texture",
                "",
                "Images (*.exr *.tx *.tif *.tiff *.png *.jpg *.jpeg *.hdr *.tga);;All (*)",
            )
            if not chosen:
                return
            with Gaffer.UndoScope(script):
                try:
                    name = self.__node.ingestLibraryTexture(chosen)
                except Exception as exc:
                    IECore.msg(IECore.Msg.Level.Warning, "ShadingTk", str(exc))
                    return
                node = self.__node.assignPlugTexture(plug, "lib:" + name)
        else:
            with Gaffer.UndoScope(script):
                node = self.__node.assignPlugTexture(plug, value)
        if node is None:
            return
        try:
            file_texture = self.__node.textureNodeHasFile(node)
        except Exception:
            file_texture = False
        if file_texture:
            self.__openTexture(node)

    def __openTexture(self, node) -> None:
        if node is None:
            return
        in_box = False
        try:
            in_box = self.__node._node_in_textures_box(node)
        except Exception:
            in_box = False
        if in_box:
            from ._textureManager import acquire_texture_manager

            parent = None
            try:
                parent = self.ancestor(GafferUI.Window) or self
            except Exception:
                parent = self
            window = acquire_texture_manager(self.__node, parent)
            try:
                window.showTexture(node.getName())
            except Exception:
                pass
            return
        try:
            GafferUI.NodeEditor.acquire(node, floating=True)
        except Exception:
            pass

    def __presetMenu(self, index: int, *unused) -> IECore.MenuDefinition:
        md = IECore.MenuDefinition()
        label = slot_label(index)
        presets = []
        try:
            presets = list(self.__node.listPresets())
        except Exception:
            presets = []
        current_type = ""
        try:
            current_type = self.__node[shader_type_plug(index)].getValue() or ""
        except Exception:
            current_type = ""
        if not presets:
            md.append("/No presets found", {"active": False})
        else:
            matching = [item for item in presets if item.get("shader") == current_type]
            other = [item for item in presets if item.get("shader") != current_type]
            for preset in matching:
                md.append(
                    "/" + preset["name"],
                    {
                        "command": functools.partial(self.__applyPreset, index, preset["name"], preset.get("shader")),
                    },
                )
            if matching and other:
                md.append("/__divA", {"divider": True})
            for preset in other:
                prefix = shader_file_prefix(str(preset.get("shader") or ""))
                md.append(
                    "/Other/{}/{}".format(prefix, preset["name"]),
                    {
                        "command": functools.partial(self.__applyPreset, index, preset["name"], preset.get("shader")),
                        "description": "Loads {} on {}".format(preset.get("shader"), label),
                    },
                )
        md.append("/__divOps", {"divider": True})
        md.append("/Save Preset…", {"command": functools.partial(self.__savePreset, index)})
        md.append("/Reset Shader", {"command": functools.partial(self.__resetShader, index)})
        return md

    def __applyPreset(self, index, name, shader=None, *unused) -> None:
        script = self.__node.scriptNode()
        with Gaffer.UndoScope(script):
            self.__node.applyPreset(index, name, shader)
        self.refresh()

    def __savePreset(self, index, *unused) -> None:
        from Qt.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self._qtWidget(), "Save Preset", "Preset name")
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            return
        try:
            path = self.__node.savePreset(index, name)
        except Exception as exc:
            IECore.msg(IECore.Msg.Level.Error, "ShadingTk", str(exc))
            return
        IECore.msg(IECore.Msg.Level.Info, "ShadingTk", "Saved preset '{}' to {}.".format(name, path))

    def __resetShader(self, index, *unused) -> None:
        script = self.__node.scriptNode()
        with Gaffer.UndoScope(script):
            self.__node.resetSlotShader(index)
        self.refresh()


    def showItemMenu(self, item, global_pos) -> None:
        payload = self.__payload(item)
        clicked_shader = payload.get("kind") == "shader" and bool(payload.get("key"))
        selected = []
        try:
            selected = list(self.__tree.selectedItems())
        except Exception:
            selected = []
        if item is not None and item not in selected:
            targets = [item]
        else:
            targets = selected or ([item] if item is not None else [])
        keys = []
        seen = set()
        for target in targets:
            data = self.__payload(target)
            if data.get("kind") != "shader":
                continue
            key = data.get("key") or ""
            if not key or key in seen:
                continue
            seen.add(key)
            keys.append(key)
        if not keys and not clicked_shader:
            return
        QtCore, QtGui, QtWidgets = _qt()
        menu = QtWidgets.QMenu(self.__tree)
        action = menu.addAction("Select Objects Bound to Shader/Material")
        action.setEnabled(bool(keys))
        if keys:
            action.triggered.connect(
                functools.partial(self.__selectBoundObjects, tuple(keys))
            )
        popup = getattr(menu, "exec", None)
        if popup is None:
            popup = menu.exec_
        popup(global_pos)

    def __selectBoundObjects(self, keys, *unused) -> None:
        from sdvTkGafferUI.shaderBinding import select_objects_bound_to_shader

        message = select_objects_bound_to_shader(self.__node, keys)
        try:
            self.__status.setText(message)
        except Exception:
            pass


def _event_pos(event):
    if hasattr(event, "position"):
        try:
            return event.position().toPoint()
        except Exception:
            pass
    return event.pos()


class _ShaderTree:
    def __new__(cls, owner: ShaderManagerWindow):
        QtCore, QtGui, QtWidgets = _qt()

        class _Tree(QtWidgets.QTreeWidget):
            def __init__(self) -> None:
                QtWidgets.QTreeWidget.__init__(self)
                self._owner = owner
                self.setColumnCount(3)
                self.setHeaderLabels(["Name", "Detail", "Kind"])
                self.setRootIsDecorated(True)
                self.setAlternatingRowColors(True)
                self.setSelectionMode(
                    QtWidgets.QAbstractItemView.ExtendedSelection
                )
                self.setExpandsOnDoubleClick(True)
                self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
                self.customContextMenuRequested.connect(self._onMenu)
                try:
                    self.header().setStretchLastSection(True)
                    self.setColumnWidth(0, 280)
                    self.setColumnWidth(1, 220)
                except Exception:
                    pass

            def mousePressEvent(self, event) -> None:
                if event.button() == QtCore.Qt.RightButton:
                    item = self.itemAt(_event_pos(event))
                    if item is not None and item.isSelected():
                        event.accept()
                        self.customContextMenuRequested.emit(_event_pos(event))
                        return
                QtWidgets.QTreeWidget.mousePressEvent(self, event)

            def _onMenu(self, pos) -> None:
                self._owner.showItemMenu(self.itemAt(pos), self.viewport().mapToGlobal(pos))

        return _Tree()
