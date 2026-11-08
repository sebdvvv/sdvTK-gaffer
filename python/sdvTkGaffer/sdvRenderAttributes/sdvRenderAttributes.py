"""sdvRenderAttributes — MeshType, then up to 8 renderer attribute sets.

Arnold, RenderMan, or Cycles. A MeshType sits at the front of the
network. Enable Catmull-Clark Subdivision type turns that MeshType
to catmullClark; off leaves interpolation unchanged. This is
``sdvRenderAttributes.sdvRenderAttributes``.
"""

from __future__ import annotations

import Gaffer
import GafferScene
import IECore

from sdvTkGaffer.sdvRenderSettings._box import (
    ENABLED_SWITCH,
    BoxNetworkSerialiser,
    SceneInsertMixin,
    add_enabled_switch,
    set_filter_paths,
    set_plug_value,
    set_switch_index,
    sync_enabled_switch,
)
from sdvTkGaffer.sdvRenderSettings._data import (
    ENGINE_LABELS,
    ENGINE_ORDER,
    MAX_PATHS,
    MAX_SLOTS,
    default_engine,
    default_set_name,
    internal_attributes,
    internal_filter,
    internal_switch,
    make_attributes_node,
    path_count_plug,
    path_plug,
    set_name_plug,
)

INTERNAL_MESH_TYPE = "__meshType"
CATMULL_CLARK = "catmullClark"


class sdvRenderAttributes(SceneInsertMixin, Gaffer.Box):
    """MeshType plus optional per-prim renderer attribute sets."""

    def __init__(self, name: str = "sdvRenderAttributes"):
        Gaffer.Box.__init__(self, name)

        engine = default_engine()
        self.addChild(GafferScene.ScenePlug("in", Gaffer.Plug.Direction.In))
        engine_plug = Gaffer.StringPlug("renderEngine", defaultValue=engine)
        self.addChild(engine_plug)
        self.addChild(
            Gaffer.IntPlug(
                "slotCount",
                defaultValue=0,
                minValue=0,
                maxValue=MAX_SLOTS,
            )
        )
        catmull = Gaffer.BoolPlug("enableCatmullClark", defaultValue=False)
        self.addChild(catmull)
        Gaffer.Metadata.registerValue(catmull, "nodule:type", "")
        Gaffer.Metadata.registerValue(
            catmull, "label", "Enable Catmull-Clark Subdivision type"
        )
        Gaffer.Metadata.registerValue(
            catmull,
            "description",
            "Turns the MeshType at the start of this node to "
            "Catmull-Clark. Off leaves mesh interpolation unchanged.",
        )
        Gaffer.Metadata.registerValue(engine_plug, "nodule:type", "")
        Gaffer.Metadata.registerValue(
            engine_plug, "plugValueWidget:type", "GafferUI.PresetsPlugValueWidget"
        )
        for value, label in ENGINE_LABELS.items():
            Gaffer.Metadata.registerValue(engine_plug, "preset:" + label, value)

        for index in range(1, MAX_SLOTS + 1):
            self.__add_slot_plugs(index, engine)

        mesh = GafferScene.MeshType(INTERNAL_MESH_TYPE)
        self.addChild(mesh)
        mesh["in"].setInput(self["in"])
        set_plug_value(mesh["meshType"], "")

        switch = add_enabled_switch(self, mesh["out"])
        Gaffer.PlugAlgo.promote(switch["out"])

        self._bind_signals()
        self.__slotsReady = True
        self._sync_driven_plugs()

    def __add_slot_plugs(self, index: int, engine: str) -> None:
        name_plug = Gaffer.StringPlug(
            set_name_plug(index), defaultValue=default_set_name(engine, index)
        )
        count_plug = Gaffer.IntPlug(
            path_count_plug(index), defaultValue=1, minValue=1, maxValue=MAX_PATHS
        )
        self.addChild(name_plug)
        self.addChild(count_plug)
        Gaffer.Metadata.registerValue(name_plug, "nodule:type", "")
        Gaffer.Metadata.registerValue(count_plug, "nodule:type", "")
        Gaffer.Metadata.registerValue(name_plug, "label", "Attribute Set")
        for path_index in range(1, MAX_PATHS + 1):
            path = Gaffer.StringPlug(path_plug(index, path_index), defaultValue="")
            self.addChild(path)
            Gaffer.Metadata.registerValue(path, "label", "PrimPath(es) :")
            Gaffer.Metadata.registerValue(
                path,
                "plugValueWidget:type",
                "GafferUI.StringPlugValueWidget",
            )
            Gaffer.Metadata.registerValue(path, "nodule:type", "")

    def __getitem__(self, key):
        if isinstance(key, str):
            self._maybe_ensure_from_child_name(key)
        return Gaffer.Box.__getitem__(self, key)

    def _maybe_ensure_from_child_name(self, name: str) -> None:
        if not getattr(self, "_sdvRenderAttributes__slotsReady", False):
            return
        if self.getChild(name) is not None:
            return
        for prefix in ("__pathFilter", "__slotSwitch"):
            if name.startswith(prefix):
                suffix = name[len(prefix) :]
                if suffix.isdigit():
                    self._ensure_slot(int(suffix))
                return
        for item in ENGINE_ORDER:
            prefix = "__{}Attributes".format(item)
            if name.startswith(prefix):
                suffix = name[len(prefix) :]
                if suffix.isdigit():
                    self._ensure_slot(int(suffix))
                return

    def meshTypeNode(self) -> Gaffer.Node | None:
        return self.getChild(INTERNAL_MESH_TYPE)

    def _ensure_slots(self, count: int) -> None:
        for index in range(1, max(0, min(int(count), MAX_SLOTS)) + 1):
            self._ensure_slot(index)

    def _ensure_slot(self, index: int) -> None:
        if index < 1 or index > MAX_SLOTS:
            return
        for previous in range(1, index):
            self._ensure_slot(previous)
        if self.getChild(internal_switch(index)) is not None:
            return
        source = self._mesh_out()
        if index > 1:
            prev = self.getChild(internal_switch(index - 1))
            if prev is not None:
                source = prev["out"]
        self.__add_slot_network(index, source)
        enabled = self.getChild(ENABLED_SWITCH)
        if enabled is not None:
            enabled["in"][1].setInput(self._chain_tail())
        self._sync_driven_plugs()

    def _mesh_out(self):
        mesh = self.getChild(INTERNAL_MESH_TYPE)
        if mesh is not None and "out" in mesh:
            return mesh["out"]
        return self["in"]

    def _wire_mesh(self) -> None:
        mesh = self.getChild(INTERNAL_MESH_TYPE)
        if mesh is None or "in" not in mesh:
            return
        _set_input(mesh["in"], self["in"])

    def _chain_tail(self):
        for index in range(MAX_SLOTS, 0, -1):
            switch = self.getChild(internal_switch(index))
            if switch is not None:
                return switch["out"]
        return self._mesh_out()

    def __add_slot_network(self, index: int, source) -> None:
        path_filter = self.getChild(internal_filter(index))
        if path_filter is None:
            path_filter = GafferScene.PathFilter(internal_filter(index))
            self.addChild(path_filter)
            path_filter["paths"].setValue(IECore.StringVectorData())

        previous = source
        current = self.currentEngine()
        for item in ENGINE_ORDER:
            child_name = internal_attributes(item, index)
            attr = self.getChild(child_name)
            if attr is None:
                attr = make_attributes_node(item, child_name)
                if attr is None:
                    continue
                self.addChild(attr)
            attr["in"].setInput(previous)
            if "filter" in attr:
                attr["filter"].setInput(path_filter["out"])
            if "enabled" in attr:
                attr["enabled"].setValue(item == current)
            previous = attr["out"]

        slot_switch = self.getChild(internal_switch(index))
        if slot_switch is None:
            slot_switch = Gaffer.Switch(internal_switch(index))
            self.addChild(slot_switch)
            slot_switch.setup(GafferScene.ScenePlug("in"))
            slot_switch["in"].resize(2)
        slot_switch["in"][0].setInput(source)
        slot_switch["in"][1].setInput(previous)

    def _sync_driven_plugs(self) -> None:
        self._wire_mesh()
        sync_enabled_switch(self)
        self._sync_mesh_type()
        engine = self.currentEngine()
        try:
            count = int(self["slotCount"].getValue())
        except Exception:
            count = 0
        for index in range(1, MAX_SLOTS + 1):
            if self.getChild(internal_switch(index)) is None:
                continue
            active = count >= index
            set_switch_index(self, internal_switch(index), 1 if active else 0)
            for item in ENGINE_ORDER:
                attr = self.getChild(internal_attributes(item, index))
                if attr is None or "enabled" not in attr:
                    continue
                set_plug_value(attr["enabled"], item == engine and active)
            try:
                path_count = int(self[path_count_plug(index)].getValue())
            except Exception:
                path_count = 1
            path_count = max(1, min(path_count, MAX_PATHS))
            paths = []
            for path_index in range(1, path_count + 1):
                try:
                    raw = (self[path_plug(index, path_index)].getValue() or "").replace(
                        "\\", "/"
                    ).strip()
                except Exception:
                    raw = ""
                if not raw:
                    continue
                paths.append(raw if raw.startswith("/") else "/" + raw)
            set_filter_paths(self, internal_filter(index), paths)
        enabled = self.getChild(ENABLED_SWITCH)
        if enabled is not None:
            enabled["in"][1].setInput(self._chain_tail())

    def _sync_mesh_type(self) -> None:
        mesh = self.meshTypeNode()
        if mesh is None or "meshType" not in mesh:
            return
        on = False
        try:
            on = bool(self["enableCatmullClark"].getValue())
        except Exception:
            on = False
        set_plug_value(mesh["meshType"], CATMULL_CLARK if on else "")
        if "enabled" in mesh:
            set_plug_value(mesh["enabled"], on)

    def currentEngine(self) -> str:
        try:
            value = (self["renderEngine"].getValue() or "").strip()
        except Exception:
            value = ""
        return value or default_engine()

    def attributesNode(self, index: int) -> Gaffer.Node | None:
        return self.getChild(internal_attributes(self.currentEngine(), index))

    def addSlot(self) -> None:
        count = self["slotCount"].getValue()
        if count >= MAX_SLOTS:
            return
        next_index = count + 1
        engine = self.currentEngine()
        name_plug = self[set_name_plug(next_index)]
        current = (name_plug.getValue() or "").strip()
        baked = default_set_name(default_engine(), next_index)
        if not current or current == baked:
            name_plug.setValue(default_set_name(engine, next_index))
        self._ensure_slots(next_index)
        self["slotCount"].setValue(next_index)

    def removeSlot(self, index: int | None = None) -> None:
        count = int(self["slotCount"].getValue())
        if count < 1:
            return
        if index is None:
            index = count
        self.removeSlotAt(index)

    def removeSlotAt(self, index: int) -> None:
        """Drop one set and shift the later sets down."""
        count = int(self["slotCount"].getValue())
        if index < 1 or index > count:
            return
        self._ensure_slots(count)
        snapshots = [self._slot_snapshot(src) for src in range(index + 1, count + 1)]
        self._shifting = True
        try:
            for offset, snap in enumerate(snapshots):
                self._apply_slot_snapshot(index + offset, snap)
            self.clearSlot(count)
        finally:
            self._shifting = False
        self["slotCount"].setValue(count - 1)

    def _slot_snapshot(self, index: int) -> dict:
        from sdvTkGaffer.sdvRenderSettings._presets import snapshot_name_values

        paths = []
        for path_index in range(1, MAX_PATHS + 1):
            try:
                paths.append(self[path_plug(index, path_index)].getValue())
            except Exception:
                paths.append("")
        attributes = {}
        for item in ENGINE_ORDER:
            attr = self.getChild(internal_attributes(item, index))
            if attr is None or "attributes" not in attr:
                continue
            attributes[item] = snapshot_name_values(attr["attributes"])
        try:
            path_count = int(self[path_count_plug(index)].getValue())
        except Exception:
            path_count = 1
        try:
            name = self[set_name_plug(index)].getValue()
        except Exception:
            name = ""
        return {
            "name": name,
            "pathCount": path_count,
            "paths": paths,
            "attributes": attributes,
        }

    def _apply_slot_snapshot(self, index: int, snap: dict) -> None:
        from sdvTkGaffer.sdvRenderSettings._presets import apply_name_values

        self._ensure_slot(index)
        self[set_name_plug(index)].setValue(snap.get("name") or "")
        count = max(1, min(int(snap.get("pathCount") or 1), MAX_PATHS))
        self[path_count_plug(index)].setValue(count)
        paths = list(snap.get("paths") or [])
        for path_index in range(1, MAX_PATHS + 1):
            value = paths[path_index - 1] if path_index <= len(paths) else ""
            self[path_plug(index, path_index)].setValue(value or "")
        attributes = snap.get("attributes") or {}
        for item in ENGINE_ORDER:
            payload = attributes.get(item)
            if not isinstance(payload, dict):
                continue
            attr = self.getChild(internal_attributes(item, index))
            if attr is None or "attributes" not in attr:
                continue
            apply_name_values(attr["attributes"], payload)

    def addPath(self, index: int) -> None:
        plug = self[path_count_plug(index)]
        count = plug.getValue()
        if count >= MAX_PATHS:
            return
        plug.setValue(count + 1)

    def removePath(self, index: int) -> None:
        plug = self[path_count_plug(index)]
        count = plug.getValue()
        if count <= 1:
            return
        self[path_plug(index, count)].setValue("")
        plug.setValue(count - 1)

    def clearSlot(self, index: int) -> None:
        self[set_name_plug(index)].setValue(
            default_set_name(self.currentEngine(), index)
        )
        self[path_count_plug(index)].setValue(1)
        for path_index in range(1, MAX_PATHS + 1):
            self[path_plug(index, path_index)].setValue("")
        for item in ENGINE_ORDER:
            attr = self.getChild(internal_attributes(item, index))
            if attr is None or "attributes" not in attr:
                continue
            _reset_plug(attr["attributes"])

    def copyValues(self) -> dict:
        from sdvTkGaffer.sdvRenderSettings._values import snapshot

        return snapshot(self)

    def pasteValues(self, data: dict | None) -> int:
        from sdvTkGaffer.sdvRenderSettings._values import apply_snapshot

        applied = apply_snapshot(
            self, data, ensure=lambda: self._ensure_slots(self["slotCount"].getValue())
        )
        self._sync_driven_plugs()
        return applied

    def resetValues(self) -> None:
        from sdvTkGaffer.sdvRenderSettings._values import reset_values

        reset_values(self)
        self._sync_driven_plugs()

    def _bind_signals(self) -> None:
        self.__plugSetConnection = self.plugSetSignal().connect(
            Gaffer.WeakMethod(self._on_plug_set), scoped=True
        )

    def _on_plug_set(self, plug: Gaffer.Plug) -> None:
        name = plug.getName()
        if getattr(self, "_shifting", False):
            return
        if name == "slotCount":
            try:
                self._ensure_slots(int(plug.getValue()))
            except Exception:
                pass
        if getattr(self, "_sdvRenderAttributes__slotsReady", False):
            self._sync_driven_plugs()


def _reset_plug(plug: Gaffer.Plug) -> None:
    reset = getattr(plug, "setToDefault", None)
    if callable(reset):
        try:
            reset()
            return
        except Exception:
            pass
    for child in plug.children():
        if isinstance(child, Gaffer.Plug):
            _reset_plug(child)


def _set_input(plug: Gaffer.Plug, source: Gaffer.Plug) -> None:
    try:
        current = plug.getInput()
    except Exception:
        current = None
    if current is not None:
        try:
            if current.isSame(source):
                return
        except Exception:
            pass
    try:
        plug.setInput(source)
    except Exception:
        pass


sdvRenderAttributes.__module__ = "sdvRenderAttributes.sdvRenderAttributes"
IECore.registerRunTimeTyped(sdvRenderAttributes)

Gaffer.Metadata.registerNode(
    sdvRenderAttributes,
    "description",
    "MeshType, then up to eight renderer attribute sets "
    "(Arnold / RenderMan / Cycles), each with its own PathFilter. "
    "Enable Catmull-Clark Subdivision type sets that MeshType to "
    "Catmull-Clark. Off leaves mesh interpolation unchanged. "
    "Unused engine nodes are disabled.",
)


class _sdvRenderAttributesSerialiser(BoxNetworkSerialiser):
    def childNeedsConstruction(
        self, child: Gaffer.GraphComponent, serialisation: Gaffer.Serialisation
    ) -> bool:
        if isinstance(child, Gaffer.Plug) and child.getName() == "out":
            return False
        return super().childNeedsConstruction(child, serialisation)


Gaffer.Serialisation.registerSerialiser(
    sdvRenderAttributes, _sdvRenderAttributesSerialiser()
)
