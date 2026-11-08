"""Lights Manager: scene lights, their filters and shader networks."""

from __future__ import annotations

import fnmatch
import functools

import Gaffer
import GafferScene
import GafferUI
import IECore

from ._editor import clear_container, expand_h, param_label, plug_widget, widget_is_alive

_WINDOWS: dict[int, "LightsManagerWindow"] = {}

_TEXTURE_SHADERS = {
    "image",
    "latlong_image",
    "PxrTexture",
    "PxrPtexture",
    "PxrNormalMap",
    "PxrBump",
    "PxrBakeTexture",
    "PxrMultiTexture",
}

_PASS_THROUGH = {"Gaffer::Dot", "Gaffer::BoxIn", "Gaffer::BoxOut", "Gaffer::Switch"}

_LABEL_W = 160


def acquire_lights_manager(script, parent=None):
    """Open the Lights Manager for this script."""
    key_id = id(script)
    window = _WINDOWS.get(key_id)
    if window is None or not widget_is_alive(window):
        window = LightsManagerWindow(script)
        _WINDOWS[key_id] = window
        if parent is not None:
            try:
                parent.addChildWindow(window)
            except Exception:
                pass
    try:
        window.refresh()
        window.setVisible(True)
        window.reveal()
        qt_window = window._qtWidget()
        qt_window.raise_()
        qt_window.activateWindow()
    except Exception:
        pass
    return window


def _qt():
    from Qt import QtCore, QtGui, QtWidgets

    return QtCore, QtGui, QtWidgets


def _type_leaf(node) -> str:
    return (node.typeName() or "").split(":")[-1]


def _is_toolkit_light(node) -> bool:
    """sdvTk light boxes (ArnoldLight, ArnoldPhysicalSky), not GafferArnold lights."""
    leaf = _type_leaf(node)
    if leaf not in ("ArnoldLight", "ArnoldPhysicalSky"):
        return False
    module = (node.typeName() or "").split("::")[0]
    if module in ("GafferArnold", "GafferScene", "GafferRenderMan"):
        return False
    return True


def _is_scene_light(node) -> bool:
    if _is_toolkit_light(node):
        return False
    try:
        if isinstance(node, GafferScene.Light):
            return True
    except Exception:
        pass
    return _type_leaf(node) in {
        "ArnoldLight",
        "ArnoldMeshLight",
        "RenderManLight",
        "RenderManMeshLight",
    }


def _is_light_filter(node) -> bool:
    try:
        if isinstance(node, GafferScene.LightFilter):
            return True
    except Exception:
        pass
    return _type_leaf(node) in {"ArnoldLightFilter", "RenderManLightFilter"} or (
        _type_leaf(node).endswith("LightFilter")
    )


def _is_shader_node(node) -> bool:
    if _is_light_filter(node) or _is_scene_light(node) or _is_toolkit_light(node):
        return False
    try:
        if isinstance(node, GafferScene.Shader):
            return True
    except Exception:
        pass
    leaf = _type_leaf(node)
    return leaf in {"ArnoldShader", "RenderManShader"} or leaf.endswith("Shader")


def _plug_string(node, name: str) -> str:
    plug = node.getChild(name) if node is not None else None
    if plug is None or not hasattr(plug, "getValue"):
        return ""
    try:
        value = plug.getValue()
    except Exception:
        return ""
    if isinstance(value, str):
        return value.strip()
    return ""


def _param_string(node, name: str) -> str:
    direct = _plug_string(node, name)
    if direct:
        return direct
    params = node.getChild("parameters") if node is not None else None
    if params is None:
        return ""
    return _plug_string(params, name)


def _shader_name(node) -> str:
    internal = node.getChild("__shader") if node is not None else None
    if internal is not None:
        got = _plug_string(internal, "name")
        if got:
            return got
    if _is_scene_light(node) or _is_light_filter(node) or _is_toolkit_light(node):
        return ""
    return _plug_string(node, "name")


def _is_texture(node) -> bool:
    if not _is_shader_node(node):
        return False
    leaf = _shader_name(node).split(":")[-1]
    lowered = leaf.lower()
    if leaf in _TEXTURE_SHADERS or lowered.endswith("_image") or "texture" in lowered:
        return True
    return lowered in {"image", "latlong"}


def _display_shader(node, kind: str) -> str:
    if _is_toolkit_light(node):
        try:
            for child in Gaffer.Node.RecursiveRange(node):
                if child is node or not _is_scene_light(child):
                    continue
                got = _shader_name(child)
                if got:
                    return got.split(":")[-1]
        except Exception:
            pass
        return _type_leaf(node)
    if kind == "lightFilter":
        got = _shader_name(node).split(":")[-1]
        if got == "gobo":
            return "aiGobo"
        return got or "lightFilter"
    got = _shader_name(node).split(":")[-1]
    return got or _type_leaf(node)


def _upstream_node(plug, seen: set[int]):
    try:
        src = plug.getInput()
    except Exception:
        return None
    if src is None:
        return None
    node = src.node()
    if node is None or id(node) in seen:
        return None
    type_name = node.typeName()
    if type_name not in _PASS_THROUGH:
        return node
    seen.add(id(node))
    if type_name == "Gaffer::Switch":
        array = node.getChild("in")
        index = 0
        try:
            index = int(node["index"].getValue())
        except Exception:
            index = 0
        if array is not None and 0 <= index < len(list(array.children())):
            return _upstream_node(array[index], seen)
        return None
    incoming = node.getChild("in")
    if incoming is None:
        return None
    return _upstream_node(incoming, seen)


def _interesting(node) -> bool:
    return (
        _is_shader_node(node)
        or _is_light_filter(node)
        or _is_scene_light(node)
        or _is_toolkit_light(node)
    )


def _linked_nodes(node) -> list:
    params = node.getChild("parameters")
    if isinstance(params, Gaffer.Plug):
        roots = [params]
    else:
        roots = [child for child in node.children() if isinstance(child, Gaffer.Plug)]
    found = []
    seen: set[int] = set()

    def visit(plug) -> None:
        src = _upstream_node(plug, set())
        if src is not None and src is not node and id(src) not in seen and _interesting(src):
            seen.add(id(src))
            found.append(src)
        try:
            children = list(plug.children())
        except Exception:
            children = []
        for child in children:
            if isinstance(child, Gaffer.Plug):
                visit(child)

    for root in roots:
        visit(root)
    return found


def _names(node) -> list[str]:
    names = [node.getName()]
    got = _plug_string(node, "name")
    if got:
        names.append(got.strip("/").split("/")[-1])
        names.append(got)
    return [name for name in names if name]


def _locations(node) -> list[str]:
    locs = []
    for name in _names(node):
        locs.append(name if name.startswith("/") else "/" + name.strip("/"))
    if _is_toolkit_light(node):
        prim = _plug_string(node, "primPath").strip("/")
        leaf = (_plug_string(node, "name").strip().strip("/") or node.getName()).split("/")[-1]
        if prim and leaf:
            locs.append("/{}/{}".format(prim, leaf))
        if leaf:
            locs.append("/" + leaf)
    return locs


def _filter_matches(filt, light) -> bool:
    raw = _param_string(filt, "filteredLights")
    if not raw:
        return False
    names = set(_names(light))
    locs = set(_locations(light))
    for token in raw.replace(",", " ").split():
        token = token.strip()
        if not token:
            continue
        leaf = token.replace("\\", "/").rstrip("/").split("/")[-1]
        if token in locs or token in names or leaf in names:
            return True
    return False


def _path_hits(path: str, light) -> bool:
    path = str(path).replace("\\", "/").strip()
    if path in ("", "/"):
        return False
    leaf = path.rstrip("/").split("/")[-1]
    names = _names(light)
    locs = _locations(light)
    if leaf in ("*", "..."):
        body = path.rstrip("/")
        prefix = body.rsplit("/", 1)[0] if "/" in body else ""
        if prefix in ("", "*", "..."):
            return True
        return any(
            loc == prefix or loc.startswith(prefix + "/") or fnmatch.fnmatch(loc, prefix)
            for loc in locs
        )
    if any(fnmatch.fnmatch(name, leaf) or name == leaf for name in names):
        return True
    return any(fnmatch.fnmatch(loc, path) or loc == path for loc in locs)


def _collect_paths(node, paths: list[str], seen: set[int]) -> None:
    if node is None or id(node) in seen:
        return
    seen.add(id(node))
    if node.typeName() == "GafferScene::PathFilter":
        plug = node.getChild("paths")
        if plug is None:
            return
        try:
            value = plug.getValue()
        except Exception:
            return
        try:
            items = list(value)
        except Exception:
            items = []
        for item in items:
            text = str(item).strip()
            if text:
                paths.append(text)
        return
    for child in node.children():
        if not isinstance(child, Gaffer.Plug):
            continue
        src = _upstream_node(child, set())
        if src is not None and src is not node:
            _collect_paths(src, paths, seen)


def _assignment_map(nodes, lights) -> dict[int, set[int]]:
    """Light-filter node id -> scene light ids referenced by a ShaderAssignment."""
    found: dict[int, set[int]] = {}
    for node in nodes:
        if node.typeName() != "GafferScene::ShaderAssignment":
            continue
        shader_plug = node.getChild("shader")
        if shader_plug is None:
            continue
        filt = _upstream_node(shader_plug, set())
        if filt is None or not _is_light_filter(filt):
            continue
        filter_plug = node.getChild("filter")
        if filter_plug is None:
            continue
        paths: list[str] = []
        _collect_paths(_upstream_node(filter_plug, set()), paths, set())
        if not paths:
            continue
        for light in lights:
            if any(_path_hits(path, light) for path in paths):
                found.setdefault(id(filt), set()).add(id(light))
    return found


def _toolkit_owner(node, toolkit_ids: set[int]):
    parent = node.parent()
    while parent is not None:
        if id(parent) in toolkit_ids:
            return parent
        try:
            parent = parent.parent()
        except Exception:
            break
    return None


def _entry(node, script, kind: str, children: list) -> dict:
    try:
        path = node.relativeName(script)
    except Exception:
        path = node.getName()
    return {
        "name": node.getName(),
        "path": path,
        "shader": _display_shader(node, kind),
        "kind": kind,
        "children": children,
    }


def _branch(node, script, seen: set[int]):
    if node is None or id(node) in seen:
        return None
    if _is_light_filter(node):
        kind = "lightFilter"
    elif _is_texture(node):
        kind = "texture"
    elif _is_shader_node(node):
        kind = "shader"
    elif _is_scene_light(node) or _is_toolkit_light(node):
        seen.add(id(node))
        return _entry(node, script, "light", [])
    else:
        return None
    seen.add(id(node))
    children = []
    for src in _linked_nodes(node):
        child = _branch(src, script, seen)
        if child is not None:
            children.append(child)
    return _entry(node, script, kind, children)


def _light_links(light) -> list:
    sources = [light]
    if _is_toolkit_light(light):
        try:
            for child in Gaffer.Node.RecursiveRange(light):
                if child is not light and _is_scene_light(child):
                    sources.append(child)
        except Exception:
            pass
    found = []
    seen: set[int] = set()
    for source in sources:
        for src in _linked_nodes(source):
            if id(src) in seen:
                continue
            seen.add(id(src))
            found.append(src)
    return found


def scene_light_tree(script) -> list[dict]:
    """Lights in the script, with filters, shaders and textures underneath."""
    try:
        nodes = [node for node in Gaffer.Node.RecursiveRange(script) if isinstance(node, Gaffer.Node)]
    except Exception:
        nodes = []
    toolkit = [node for node in nodes if _is_toolkit_light(node)]
    toolkit_ids = {id(node) for node in toolkit}
    lights = list(toolkit)
    contained: list[tuple] = []
    loose = []
    for node in nodes:
        owner = _toolkit_owner(node, toolkit_ids)
        if owner is not None and node is not owner:
            if _is_light_filter(node):
                contained.append((node, owner))
            continue
        if _is_scene_light(node):
            lights.append(node)
        elif _is_light_filter(node):
            loose.append(node)
    lights.sort(key=lambda node: node.getName())
    assignments = _assignment_map(nodes, lights)
    attached: dict[int, list] = {}
    for filt, owner in sorted(contained, key=lambda pair: pair[0].getName()):
        attached.setdefault(id(owner), []).append(filt)
    orphans = []
    for filt in loose:
        matched = False
        for light in lights:
            if _filter_matches(filt, light) or id(light) in assignments.get(id(filt), ()):
                attached.setdefault(id(light), []).append(filt)
                matched = True
        if not matched:
            orphans.append(filt)
    roots = []
    for light in lights:
        seen = {id(light)}
        children = []
        for filt in attached.get(id(light), []):
            item = _branch(filt, script, seen)
            if item is not None:
                children.append(item)
        for src in _light_links(light):
            item = _branch(src, script, seen)
            if item is not None:
                children.append(item)
        roots.append(_entry(light, script, "light", children))
    for filt in orphans:
        item = _branch(filt, script, set())
        if item is not None:
            roots.append(item)
    return roots


def _skip_plug(plug) -> bool:
    name = plug.getName()
    if name.startswith("__") or name in ("in", "out", "user"):
        return True
    try:
        if plug.direction() == Gaffer.Plug.Direction.Out:
            return True
    except Exception:
        pass
    return False


def _value_plugs(node, kind: str) -> list:
    plugs = []
    if kind in ("light", "lightFilter") and not _is_toolkit_light(node):
        for name in ("enabled", "name"):
            plug = node.getChild(name)
            if isinstance(plug, Gaffer.ValuePlug) and not _skip_plug(plug):
                plugs.append(plug)
    elif kind in ("shader", "texture"):
        plug = node.getChild("enabled")
        if isinstance(plug, Gaffer.ValuePlug):
            plugs.append(plug)
    if _is_toolkit_light(node):
        roots = [child for child in node.children() if isinstance(child, Gaffer.Plug)]
    else:
        params = node.getChild("parameters")
        roots = [params] if isinstance(params, Gaffer.Plug) else []

    def walk(plug) -> None:
        if _skip_plug(plug):
            return
        if isinstance(plug, Gaffer.ValuePlug):
            plugs.append(plug)
            return
        try:
            children = [child for child in plug.children() if isinstance(child, Gaffer.Plug)]
        except Exception:
            children = []
        if not children:
            return
        for child in children:
            walk(child)

    seen = {id(plug) for plug in plugs}
    for root in roots:
        before = len(plugs)
        walk(root)
        if len(plugs) == before and isinstance(root, Gaffer.ValuePlug) and id(root) not in seen:
            plugs.append(root)
    unique = []
    seen_ids: set[int] = set()
    for plug in plugs:
        if id(plug) in seen_ids:
            continue
        seen_ids.add(id(plug))
        unique.append(plug)
    return unique


class LightsManagerWindow(GafferUI.Window):
    """Tree of lights. The right pane edits the selected node's attributes."""

    def __init__(self, script, **kw) -> None:
        kw.setdefault("sizeMode", GafferUI.Window.SizeMode.Manual)
        try:
            GafferUI.Window.__init__(self, "Lights Manager", **kw)
        except TypeError:
            kw.pop("sizeMode", None)
            GafferUI.Window.__init__(self, "Lights Manager", **kw)
        self.__script = script
        self.__refreshing = False
        self.__connections: list = []
        self.__selectedPath = ""

        column = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Vertical, spacing=6, borderWidth=8
        )
        header = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=6
        )
        header.append(
            GafferUI.Label(
                "Lights in the script. Filters, shaders and textures hang off "
                "each light. Select a row to edit its attributes."
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
        column.append(header)

        self.__tree = _LightsTree(self)
        self.__treeWidget = GafferUI.Widget(self.__tree)
        self.__inspectorHint = GafferUI.Label("Select a light, filter or shader.")
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
            split = GafferUI.SplitContainer(GafferUI.SplitContainer.Orientation.Horizontal)
            split.append(self.__treeWidget)
            split.append(inspector_scroll)
            column.append(split, expand=True)
        except Exception:
            row = GafferUI.ListContainer(
                GafferUI.ListContainer.Orientation.Horizontal, spacing=8
            )
            row.append(self.__treeWidget, expand=True)
            row.append(inspector_scroll, expand=True)
            column.append(row, expand=True)
        try:
            self.__tree.itemSelectionChanged.connect(self.__onTreeSelection)
        except Exception:
            pass
        self.__status = GafferUI.Label("")
        column.append(self.__status)
        self.setChild(column)
        try:
            self._qtWidget().resize(1100, 640)
        except Exception:
            pass
        self.refresh()

    def scriptNode(self):
        return self.__script

    def refresh(self, *unused) -> None:
        if self.__refreshing:
            return
        self.__refreshing = True
        try:
            try:
                roots = scene_light_tree(self.__script)
            except Exception as exc:
                roots = []
                IECore.msg(IECore.Msg.Level.Warning, "Lights Manager", str(exc))
            self.__roots = roots
            self.__rebuildTree(roots)
            self.__restoreSelection()
            self.__fillInspector()
            count = sum(1 for item in roots if item.get("kind") == "light")
            try:
                if count:
                    self.__status.setText(
                        "{} light{}.".format(count, "" if count == 1 else "s")
                    )
                else:
                    self.__status.setText("No lights in this script.")
            except Exception:
                pass
        finally:
            self.__refreshing = False

    def __rebuildTree(self, roots: list) -> None:
        QtCore, QtGui, QtWidgets = _qt()
        tree = self.__tree
        tree.blockSignals(True)
        try:
            tree.clear()
            role = QtCore.Qt.UserRole
            for root in roots:
                self.__addItem(tree, None, root, role, QtGui)
        finally:
            tree.blockSignals(False)

    def __addItem(self, tree, parent, data, role, QtGui) -> None:
        QtCore, QtGuiMod, QtWidgets = _qt()
        del QtGuiMod
        item = QtWidgets.QTreeWidgetItem(
            [data.get("name") or "", data.get("shader") or "", data.get("kind") or ""]
        )
        item.setData(
            0,
            role,
            {
                "path": data.get("path") or "",
                "kind": data.get("kind") or "",
                "name": data.get("name") or "",
            },
        )
        if data.get("kind") == "texture":
            color = QtGui.QColor("#43a047")
            item.setForeground(0, color)
            item.setForeground(1, color)
        if parent is None:
            tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        item.setExpanded(True)
        for child in data.get("children") or []:
            self.__addItem(tree, item, child, role, QtGui)

    def __restoreSelection(self) -> None:
        path = self.__selectedPath
        if not path:
            return
        QtCore, QtGui, QtWidgets = _qt()
        role = QtCore.Qt.UserRole

        def walk(item):
            payload = item.data(0, role)
            if isinstance(payload, dict) and payload.get("path") == path:
                return item
            for index in range(item.childCount()):
                found = walk(item.child(index))
                if found is not None:
                    return found
            return None

        tree = self.__tree
        found = None
        for index in range(tree.topLevelItemCount()):
            found = walk(tree.topLevelItem(index))
            if found is not None:
                break
        if found is None:
            return
        tree.blockSignals(True)
        try:
            tree.setCurrentItem(found)
        finally:
            tree.blockSignals(False)

    def __payload(self, item) -> dict:
        if item is None:
            return {}
        QtCore, QtGui, QtWidgets = _qt()
        data = item.data(0, QtCore.Qt.UserRole)
        return data if isinstance(data, dict) else {}

    def __node_from_path(self, path: str):
        path = (path or "").strip()
        if not path or self.__script is None:
            return None
        try:
            node = self.__script.descendant(path)
        except Exception:
            node = None
        if isinstance(node, Gaffer.Node):
            return node
        return None

    def __current_payload(self) -> dict:
        try:
            item = self.__tree.currentItem()
        except Exception:
            item = None
        return self.__payload(item)

    def __onTreeSelection(self, *unused) -> None:
        if self.__refreshing:
            return
        payload = self.__current_payload()
        self.__selectedPath = payload.get("path") or ""
        self.__fillInspector()

    def __fillInspector(self) -> None:
        clear_container(self.__inspectorForm)
        payload = self.__current_payload()
        node = self.__node_from_path(payload.get("path") or "")
        if node is None:
            try:
                self.__inspectorHint.setText("Select a light, filter or shader.")
            except Exception:
                pass
            return
        kind = payload.get("kind") or ""
        shader = _display_shader(node, kind)
        try:
            self.__inspectorHint.setText(
                "<b>{}</b>    {}    {}".format(node.getName(), shader, kind)
            )
        except Exception:
            pass
        plugs = _value_plugs(node, kind)
        if not plugs:
            self.__inspectorForm.append(GafferUI.Label("No editable attributes."))
            return
        for plug in plugs:
            self.__addParamRow(plug)

    def __addParamRow(self, plug) -> None:
        widget = plug_widget(plug)
        if widget is None:
            return
        row = GafferUI.ListContainer(
            GafferUI.ListContainer.Orientation.Horizontal, spacing=8
        )
        label = GafferUI.Label(param_label(plug))
        try:
            label._qtWidget().setFixedWidth(_LABEL_W)
        except Exception:
            pass
        row.append(label)
        expand_h(widget)
        row.append(widget, expand=True)
        self.__inspectorForm.append(row)

    def __onExpandAll(self, *unused) -> None:
        try:
            self.__tree.expandAll()
        except Exception:
            pass

    def __onCollapseAll(self, *unused) -> None:
        try:
            self.__tree.collapseAll()
        except Exception:
            pass

    def showItemMenu(self, item, global_pos) -> None:
        payload = self.__payload(item)
        node = self.__node_from_path(payload.get("path") or "")
        if node is None:
            return
        try:
            self.__tree.setCurrentItem(item)
        except Exception:
            pass
        QtCore, QtGui, QtWidgets = _qt()
        menu = QtWidgets.QMenu(self.__tree)
        action = menu.addAction("Select Node '{}'".format(node.getName()))
        action.triggered.connect(functools.partial(self.__selectNode, payload.get("path") or ""))
        popup = getattr(menu, "exec", None)
        if popup is None:
            popup = menu.exec_
        popup(global_pos)

    def __selectNode(self, path: str, *unused) -> None:
        node = self.__node_from_path(path)
        script = self.__script
        if node is None or script is None:
            return
        try:
            selection = script.selection()
            selection.clear()
            selection.add(node)
        except Exception as exc:
            IECore.msg(IECore.Msg.Level.Warning, "Lights Manager", str(exc))
            return
        try:
            script.setFocus(node)
        except Exception:
            pass
        try:
            self.__status.setText("Selected '{}'.".format(node.getName()))
        except Exception:
            pass


def _event_pos(event):
    if hasattr(event, "position"):
        try:
            return event.position().toPoint()
        except Exception:
            pass
    return event.pos()


class _LightsTree:
    def __new__(cls, owner: LightsManagerWindow):
        QtCore, QtGui, QtWidgets = _qt()

        class _Tree(QtWidgets.QTreeWidget):
            def __init__(self) -> None:
                QtWidgets.QTreeWidget.__init__(self)
                self._owner = owner
                self.setColumnCount(3)
                self.setHeaderLabels(["Name", "Shader", "Kind"])
                self.setRootIsDecorated(True)
                self.setAlternatingRowColors(True)
                self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
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
                self._owner.showItemMenu(
                    self.itemAt(pos), self.viewport().mapToGlobal(pos)
                )

        return _Tree()
