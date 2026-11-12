"""Arnold USD translation: option names, lights, and surface shaders.

``ai:`` options are written as ``arnold:``. An ``ai:background`` shader network
is written as the background node graph. When that network is absent, an
enabled ``render:backgroundColor`` becomes an ``arnold:flat`` shader on the
same graph. The network wins when both are set. A missing background is left
unauthored.
"""

from __future__ import annotations

ID = "arnold"
LABEL = "Arnold"
PREFIX = "ai:"
DEST = "arnold:"
ROOT_OPTION_TYPE = "ArnoldOptions"

# Same layout arnold-usd writes for options.background: a string on the
# RenderSettings prim points at an ArnoldNodeGraph, and that graph's
# background terminal connects to a flat shader.
_BACKGROUND_GRAPH = "/mtl/background/nodeGraph"
_BACKGROUND_SHADER = _BACKGROUND_GRAPH + "/flat"


def owns(name: str) -> bool:
    return str(name or "").startswith(PREFIX)


def translate(name: str) -> str:
    name = str(name or "")
    return DEST + name[len(PREFIX) :]


def alias(name: str):
    return None


def author_background(stage, settings_prim, members) -> set:
    """Author the Arnold background and return the option names consumed.

    ``ai:background`` is written when it is a shader network. That network
    wins over ``render:backgroundColor``, which is used only when the network
    is absent. An empty result leaves both options for the normal writer.
    Failures are not raised.
    """
    if settings_prim is None:
        return set()
    from .network import author_shader_network, shader_network

    network = shader_network(members.get("option:ai:background"))
    if network is not None:
        try:
            authored = author_shader_network(
                stage,
                settings_prim,
                network,
                graph_path=_BACKGROUND_GRAPH,
                graph_type="ArnoldNodeGraph",
                terminal="background",
                link_name="arnold:global:background",
                node_id=_arnold_node_id,
                scopes=("/mtl", "/mtl/background"),
                name_attr="primvars:arnold:name",
            )
        except Exception:
            authored = False
        if not authored:
            return set()
        return {"ai:background", "render:backgroundColor"}

    data = members.get("option:render:backgroundColor")
    if data is None:
        return set()
    color = _color3(data)
    if color is None:
        return set()
    try:
        _author_flat_background(stage, settings_prim, color)
    except Exception:
        return set()
    return {"render:backgroundColor"}


def _color3(data):
    value = data
    if hasattr(data, "value") and not isinstance(data, (str, bytes)):
        value = data.value
    if value is None:
        return None
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except Exception:
        return None


def _author_flat_background(stage, settings_prim, color) -> None:
    from pxr import Gf, Sdf, UsdShade

    graph = _define_background_graph(stage)
    shader = UsdShade.Shader.Define(stage, _BACKGROUND_SHADER)
    shader.CreateIdAttr("arnold:flat")
    shader.CreateInput("color", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    shader.CreateOutput("out", Sdf.ValueTypeNames.Token)
    _connect_background_terminal(graph, settings_prim, _BACKGROUND_SHADER + ".outputs:out")


def _define_background_graph(stage):
    from pxr import Sdf

    _ensure_scope(stage, "/mtl")
    _ensure_scope(stage, "/mtl/background")
    graph = stage.DefinePrim(_BACKGROUND_GRAPH, "ArnoldNodeGraph")
    name = graph.CreateAttribute(
        "primvars:arnold:name", Sdf.ValueTypeNames.String, custom=False
    )
    name.Set(_BACKGROUND_GRAPH)
    return graph


def _connect_background_terminal(graph, settings_prim, output_path) -> None:
    from pxr import Sdf

    terminal = graph.CreateAttribute(
        "outputs:background", Sdf.ValueTypeNames.Token, custom=False
    )
    terminal.SetConnections([Sdf.Path(output_path)])
    link = settings_prim.CreateAttribute(
        "arnold:global:background", Sdf.ValueTypeNames.String, custom=False
    )
    link.Set(_BACKGROUND_GRAPH)


def _arnold_node_id(name: str) -> str:
    name = str(name or "")
    if name.startswith("arnold:"):
        return name
    if name.startswith("ai:"):
        return "arnold:" + name[len("ai:") :]
    return "arnold:" + name


def _ensure_scope(stage, path) -> None:
    from pxr import UsdGeom

    if stage.GetPrimAtPath(path):
        return
    UsdGeom.Scope.Define(stage, path)


def finish(stage) -> bool:
    changed = _promote_arnold_lights(stage)
    return _promote_arnold_shaders(stage) or changed



# Shader id from the scene writer → UsdLux type and API schemas.
# An empty type keeps the prim type (mesh lights stay meshes).
_ARNOLD_LIGHTS = {
    "arnold:quad_light": ("RectLight", ("ArnoldQuadLightAPI",)),
    "arnold:disk_light": ("DiskLight", ("ArnoldDiskLightAPI",)),
    "arnold:point_light": ("SphereLight", ("ArnoldPointLightAPI",)),
    "arnold:spot_light": ("SphereLight", ("ArnoldPointLightAPI",)),
    "arnold:distant_light": ("DistantLight", ("ArnoldDistantLightAPI",)),
    "arnold:cylinder_light": ("CylinderLight", ("ArnoldLightAPI",)),
    "arnold:skydome_light": ("DomeLight", ("ArnoldSkydomeLightAPI",)),
    "arnold:photometric_light": ("DiskLight", ("ArnoldDiskLightAPI",)),
    "arnold:mesh_light": ("", ("MeshLightAPI", "ArnoldMeshLightAPI")),
}

_LUX_INPUTS = {
    "color": "inputs:color",
    "intensity": "inputs:intensity",
    "exposure": "inputs:exposure",
    "diffuse": "inputs:diffuse",
    "specular": "inputs:specular",
    "normalize": "inputs:normalize",
}

_SIZE_INPUTS = {
    "arnold:quad_light": {"width": "inputs:width", "height": "inputs:height"},
    "arnold:disk_light": {"radius": "inputs:radius"},
    "arnold:point_light": {"radius": "inputs:radius"},
    "arnold:spot_light": {"radius": "inputs:radius"},
    "arnold:cylinder_light": {
        "radius": "inputs:radius",
        "length": "inputs:length",
        "height": "inputs:length",
    },
    "arnold:distant_light": {"angle": "inputs:angle"},
}

_TEXTURE_INPUTS = {
    "arnold:quad_light": "inputs:texture:file",
    "arnold:skydome_light": "inputs:texture:file",
}

# Scene-writer types that disagree with the Arnold schema attribute type.
_PRIMVAR_TYPES = {
    "sampling_mode": "token",
    "filename": "asset",
    "format": "token",
    "portal_mode": "token",
}

_SHAPE_LIGHT_TYPES = ("", "Xform", "Scope")


def promote_arnold_lights(file_name) -> None:
    """Rewrite Arnold light shaders in ``file_name`` as UsdLux lights."""
    import IECore
    from pxr import Usd

    stage = Usd.Stage.Open(file_name)
    if not stage:
        raise IECore.Exception(
            'sdvUSDWriter: failed to open "{}" to author lights'.format(file_name)
        )
    changed = finish(stage)
    if not changed:
        return
    if not stage.GetRootLayer().Save():
        raise IECore.Exception(
            'sdvUSDWriter: failed to save lights to "{}"'.format(file_name)
        )


def _promote_arnold_lights(stage) -> bool:
    materials = {}
    for prim in stage.Traverse():
        if prim.GetTypeName() != "Material":
            continue
        shader, shader_id = _arnold_light_shader(prim)
        if shader is None:
            continue
        materials[prim.GetPath()] = (prim, shader, shader_id)
    if not materials:
        return False

    bindings = {path: [] for path in materials}
    for prim in stage.Traverse():
        relationship = prim.GetRelationship("material:binding")
        if not relationship or not relationship.HasAuthoredTargets():
            continue
        for target in relationship.GetTargets():
            if target in bindings:
                bindings[target].append(prim)

    changed = False
    drop = []
    for path, prims in bindings.items():
        if not prims:
            continue
        material, shader, shader_id = materials[path]
        converted_all = True
        for prim in prims:
            if not _can_convert_light(prim, shader_id):
                converted_all = False
                continue
            _convert_arnold_light(prim, shader, shader_id)
            changed = True
        if converted_all and not _shader_inputs_connected(shader):
            drop.append(material)
    parents = []
    for material in drop:
        parent = material.GetParent()
        stage.RemovePrim(material.GetPath())
        if parent:
            parents.append(parent)
    for parent in parents:
        if parent.IsValid() and parent.GetTypeName() == "Scope" and not parent.GetChildren():
            stage.RemovePrim(parent.GetPath())
    return changed


def _arnold_light_shader(material):
    from pxr import Usd

    stage = material.GetStage()
    output = material.GetAttribute("outputs:arnold:light")
    if output and output.HasAuthoredConnections():
        connections = output.GetConnections()
        if connections:
            shader = stage.GetPrimAtPath(connections[0].GetPrimPath())
            shader_id = _shader_id(shader)
            if shader_id in _ARNOLD_LIGHTS:
                return shader, shader_id
    for prim in Usd.PrimRange(material):
        if prim.GetTypeName() != "Shader":
            continue
        shader_id = _shader_id(prim)
        if shader_id in _ARNOLD_LIGHTS:
            return prim, shader_id
    return None, None


def _shader_id(shader) -> str:
    if not shader:
        return ""
    attribute = shader.GetAttribute("info:id")
    if not attribute:
        return ""
    return str(attribute.Get() or "")


def _can_convert_light(prim, shader_id) -> bool:
    if shader_id == "arnold:mesh_light":
        return prim.GetTypeName() in ("Mesh", "Xform", "Scope", "")
    return prim.GetTypeName() in _SHAPE_LIGHT_TYPES or prim.GetTypeName() == _ARNOLD_LIGHTS[shader_id][0]


def _shader_inputs_connected(shader) -> bool:
    for attribute in shader.GetAttributes():
        name = attribute.GetName()
        if name.startswith("inputs:") and attribute.HasAuthoredConnections():
            return True
    return False


def _convert_arnold_light(prim, shader, shader_id) -> None:
    type_name, apis = _ARNOLD_LIGHTS[shader_id]
    if type_name:
        prim.SetTypeName(type_name)
    _set_api_schemas(prim, apis, ("MaterialBindingAPI",))
    if prim.HasProperty("material:binding"):
        prim.RemoveProperty("material:binding")

    lux = dict(_LUX_INPUTS)
    lux.update(_SIZE_INPUTS.get(shader_id, {}))
    texture_name = _TEXTURE_INPUTS.get(shader_id)
    for attribute in shader.GetAttributes():
        name = attribute.GetName()
        if not name.startswith("inputs:"):
            continue
        param = name[len("inputs:") :]
        if param == "filename" and texture_name:
            _author_file(prim, texture_name, attribute)
            continue
        dest = lux.get(param)
        if dest:
            _author_shader_input(prim, dest, attribute)
            continue
        _author_shader_input(
            prim,
            "primvars:arnold:" + param,
            attribute,
            _PRIMVAR_TYPES.get(param),
        )
    if shader_id == "arnold:point_light" and not _shader_number(shader, "radius"):
        _set_bool(prim, "treatAsPoint", True)
    elif shader_id == "arnold:cylinder_light" and not _shader_number(shader, "radius"):
        _set_bool(prim, "treatAsLine", True)


def _set_api_schemas(prim, add, remove) -> None:
    from pxr import Sdf

    layer = prim.GetStage().GetRootLayer()
    spec = layer.GetPrimAtPath(prim.GetPath())
    if spec is None:
        spec = Sdf.CreatePrimInLayer(layer, prim.GetPath())
    current = spec.GetInfo("apiSchemas") if spec.HasInfo("apiSchemas") else Sdf.TokenListOp()
    dropped = {str(name) for name in remove}

    def kept(items):
        return [str(item) for item in items if str(item) not in dropped]

    prepended = kept(_list_op_items(current, "prependedItems"))
    appended = kept(_list_op_items(current, "appendedItems"))
    explicit = kept(_list_op_items(current, "explicitItems"))
    present = set(prepended) | set(appended) | set(explicit)
    for name in add:
        if name not in present:
            prepended.append(name)
            present.add(name)
    authored = Sdf.TokenListOp()
    if explicit:
        authored.explicitItems = explicit
    if prepended:
        authored.prependedItems = prepended
    if appended:
        authored.appendedItems = appended
    deleted = _list_op_items(current, "deletedItems")
    if deleted:
        authored.deletedItems = [str(item) for item in deleted]
    if not prepended and not appended and not explicit and not deleted:
        spec.ClearInfo("apiSchemas")
    else:
        spec.SetInfo("apiSchemas", authored)


def _list_op_items(list_op, name):
    value = getattr(list_op, name, None)
    if not value:
        return []
    return list(value)


def _author_file(prim, dest_name, source) -> None:
    _author_shader_input(prim, dest_name, source, "asset")


def _author_shader_input(prim, dest_name, source, type_key=None) -> None:
    from pxr import Sdf

    type_name = source.GetTypeName()
    if type_key == "token":
        type_name = Sdf.ValueTypeNames.Token
    elif type_key == "asset":
        type_name = Sdf.ValueTypeNames.Asset
    if source.HasAuthoredConnections():
        targets = source.GetConnections()
        if not targets:
            return
        prim.CreateAttribute(dest_name, type_name, custom=False).AddConnection(targets[0])
        return
    times = source.GetTimeSamples()
    if times:
        dest = prim.CreateAttribute(dest_name, type_name, custom=False)
        for time in times:
            value = _coerce_light_value(source.Get(time), type_key)
            if value is not None:
                dest.Set(value, time)
        return
    if not source.HasAuthoredValue():
        return
    value = _coerce_light_value(source.Get(), type_key)
    if value is None:
        return
    prim.CreateAttribute(dest_name, type_name, custom=False).Set(value)


def _coerce_light_value(value, type_key):
    from pxr import Sdf

    if value is None:
        return None
    if type_key == "asset":
        text = value if isinstance(value, str) else str(getattr(value, "path", value))
        if not text:
            return None
        return Sdf.AssetPath(text)
    if type_key == "token":
        text = str(value)
        if not text:
            return None
        return text
    if isinstance(value, str) and value == "":
        return None
    return value


def _shader_number(shader, name):
    attribute = shader.GetAttribute("inputs:" + name)
    if not attribute or not attribute.HasAuthoredValue():
        return 0
    value = attribute.Get()
    if value is None:
        return 0
    return value


def _set_bool(prim, name, value) -> None:
    from pxr import Sdf

    prim.CreateAttribute(name, Sdf.ValueTypeNames.Bool, custom=False).Set(bool(value))


# Authored zeros mean "no map". Leaving them set replaces the geometric normal.
_UNSET_VECTOR_INPUTS = ("normal", "coat_normal", "tangent")


def _promote_arnold_shaders(stage) -> bool:
    """Connect the universal surface output to the Arnold shader and drop Gaffer metadata."""
    changed = False
    for prim in stage.Traverse():
        if prim.GetTypeName() != "Material":
            continue
        if _rewire_arnold_material(prim):
            changed = True
    return changed


def _rewire_arnold_material(material) -> bool:
    output = material.GetAttribute("outputs:arnold:surface")
    if not output or not output.HasAuthoredConnections():
        return False
    targets = output.GetConnections()
    if not targets:
        return False
    shader = material.GetStage().GetPrimAtPath(targets[0].GetPrimPath())
    if not _shader_id(shader).startswith("arnold:"):
        return False
    _connect_surface(material, targets)
    from pxr import Usd

    for prim in Usd.PrimRange(material):
        if prim.GetTypeName() == "Shader":
            _strip_gaffer_metadata(prim)
            _drop_unset_vectors(prim)
    return True


def _connect_surface(material, targets) -> None:
    from pxr import Sdf

    surface = material.GetAttribute("outputs:surface")
    if surface and surface.HasAuthoredConnections():
        return
    if not surface:
        surface = material.CreateAttribute("outputs:surface", Sdf.ValueTypeNames.Token, custom=False)
    surface.SetConnections(targets)


def _strip_gaffer_metadata(prim) -> None:
    spec = prim.GetStage().GetRootLayer().GetPrimAtPath(prim.GetPath())
    if spec is None or not spec.HasInfo("customData"):
        return
    data = dict(spec.customData)
    cortex = data.get("cortex")
    if isinstance(cortex, dict):
        cortex = dict(cortex)
        blind = cortex.get("blindData")
        if isinstance(blind, dict):
            blind = {
                key: value
                for key, value in dict(blind).items()
                if not str(key).startswith("gaffer:")
            }
            if blind:
                cortex["blindData"] = blind
            else:
                cortex.pop("blindData", None)
        if cortex:
            data["cortex"] = cortex
        else:
            data.pop("cortex", None)
    if data:
        spec.customData = data
    else:
        spec.ClearInfo("customData")


def _drop_unset_vectors(shader) -> None:
    for name in _UNSET_VECTOR_INPUTS:
        attribute = shader.GetAttribute("inputs:" + name)
        if not attribute or attribute.HasAuthoredConnections() or attribute.GetNumTimeSamples():
            continue
        value = attribute.Get()
        if value is None:
            continue
        if all(abs(float(channel)) < 1.0e-8 for channel in value):
            shader.RemoveProperty(attribute.GetName())

