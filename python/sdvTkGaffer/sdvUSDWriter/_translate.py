"""Map Gaffer render globals onto UsdRender settings, products, and vars.

The layer file is written first. These functions add the render prims to that file.
Arnold light shaders bound to transforms become UsdLux lights: shared fields on
``inputs:``, Arnold-only fields on ``primvars:arnold:``. Surface materials connect
``outputs:surface`` to the Arnold shader and drop Gaffer metadata.
"""

from __future__ import annotations

import os

_DISPLAY_DRIVERS = {"iedisplay", "idisplay"}

_FILM_FIT_BY_VALUE = {
    0: "adjustApertureHeight",  # Horizontal
    1: "adjustApertureWidth",  # Vertical
    2: "expandAperture",  # Fit
    3: "cropAperture",  # Fill
    4: "adjustPixelAspectRatio",  # Distort
}

_FILM_FIT_BY_NAME = {
    "horizontal": "adjustApertureHeight",
    "vertical": "adjustApertureWidth",
    "fit": "expandAperture",
    "fill": "cropAperture",
    "distort": "adjustPixelAspectRatio",
}

# First token of an Output data string → UsdRenderVar dataType.
_DATA_TYPES = {
    "color": "color3f",
    "color3": "color3f",
    "color3f": "color3f",
    "rgb": "color3f",
    "color4": "color4f",
    "color4f": "color4f",
    "rgba": "color4f",
    "float": "float",
    "double": "float",
    "int": "int",
    "integer": "int",
    "uint": "uint",
    "vector": "vector3f",
    "vector3": "vector3f",
    "normal": "normal3f",
    "point": "point3f",
    "float2": "float2",
    "float3": "float3",
    "float4": "float4",
    "matrix": "matrix4d",
    "lpe": "color3f",
}

_CROP_KEYS = (
    "render:cropWindow",
    "render:overscan",
    "render:overscanTop",
    "render:overscanBottom",
    "render:overscanLeft",
    "render:overscanRight",
)

_MOTION_KEYS = (
    "sampleMotion",
    "render:transformBlur",
    "render:deformationBlur",
)

_SILENT_DATA = {"CompoundData", "CompoundObject", "PathMatcherData", "NullObject"}


def prim_token(name: str) -> str:
    """USD prim name. Spaces and punctuation collapse to underscores."""
    chars = []
    for char in str(name or ""):
        chars.append(char if char.isalnum() or char == "_" else "_")
    token = "".join(chars).strip("_")
    while "__" in token:
        token = token.replace("__", "_")
    if not token:
        token = "prim"
    if token[0].isdigit():
        token = "_" + token
    return token


def attribute_name(name: str) -> str:
    """USD attribute name. Colons stay so ``ai:AA_samples`` is preserved."""
    chars = []
    for char in str(name or ""):
        chars.append(char if char.isalnum() or char in "_:" else "_")
    token = "".join(chars).strip(":_")
    while "__" in token:
        token = token.replace("__", "_")
    if not token:
        token = "attr"
    if token[0].isdigit():
        token = "_" + token
    return token


def unique_token(name: str, used: set) -> str:
    base = prim_token(name)
    token = base
    index = 2
    while token in used:
        token = "{}_{}".format(base, index)
        index += 1
    used.add(token)
    return token


def film_fit_policy(value):
    """Gaffer ``render:filmFit`` → ``aspectRatioConformPolicy`` token."""
    if value is None:
        return None
    if isinstance(value, str):
        return _FILM_FIT_BY_NAME.get(value.strip().lower())
    try:
        return _FILM_FIT_BY_VALUE.get(int(value))
    except (TypeError, ValueError):
        return None


def scaled_resolution(resolution, multiplier):
    """``render:resolution`` times ``render:resolutionMultiplier``."""
    if resolution is None:
        return None
    mult = 1.0 if multiplier is None else float(multiplier)
    width = int(float(resolution[0]) * mult + 0.5)
    height = int(float(resolution[1]) * mult + 0.5)
    if width < 1 or height < 1:
        return None
    return (width, height)


def data_window_ndc(crop, overscan_enabled, left, right, top, bottom):
    """Gaffer crop (origin top-left) plus overscan → USD ``dataWindowNDC``.

    USD's window is (xmin, ymin, xmax, ymax) with the origin at the bottom
    left. A unit window is the schema default, so this returns None for it.
    """
    if crop is None and not overscan_enabled:
        return None
    minx, miny, maxx, maxy = (0.0, 0.0, 1.0, 1.0) if crop is None else tuple(crop)
    if overscan_enabled:
        left = 0.0 if left is None else float(left)
        right = 0.0 if right is None else float(right)
        top = 0.0 if top is None else float(top)
        bottom = 0.0 if bottom is None else float(bottom)
    else:
        left = right = top = bottom = 0.0
    window = (
        float(minx) - left,
        1.0 - (float(maxy) + bottom),
        float(maxx) + right,
        1.0 - (float(miny) - top),
    )
    if all(abs(value - default) < 1.0e-6 for value, default in zip(window, (0.0, 0.0, 1.0, 1.0))):
        return None
    return window


def motion_blur_disabled(sample_motion, transform_blur, deformation_blur):
    """True when UsdRender ``disableMotionBlur`` should be on.

    None means the globals do not say, and the attribute is left unauthored.
    """
    if sample_motion is False:
        return True
    if transform_blur is True or deformation_blur is True:
        return False
    if transform_blur is False and deformation_blur is False:
        return True
    return None


def parse_output_data(data: str) -> dict:
    """Gaffer Output data string → RenderVar sourceName, dataType, sourceType.

    ``rgba`` is color4f. ``color diffuse`` is color3f / diffuse.
    ``float Z`` is float / Z. ``lpe C.*`` is an LPE of color3f.
    """
    text = (data or "").strip()
    if not text:
        return {"dataType": "color3f", "sourceName": "", "sourceType": "raw"}
    parts = text.split()
    if len(parts) == 1:
        token = parts[0]
        if token.lower() in ("rgba", "rgbaa"):
            return {"dataType": "color4f", "sourceName": token, "sourceType": "raw"}
        return {"dataType": "color3f", "sourceName": token, "sourceType": "raw"}
    head = parts[0].lower()
    if head not in _DATA_TYPES:
        return {"dataType": "color3f", "sourceName": text, "sourceType": "raw"}
    source = " ".join(parts[1:])
    source_type = "raw"
    if head == "lpe":
        source_type = "lpe"
    elif source.lower().startswith("lpe "):
        source_type = "lpe"
        source = source[4:].strip()
    return {
        "dataType": _DATA_TYPES[head],
        "sourceName": source,
        "sourceType": source_type,
    }


def group_records(records: list) -> list:
    """One product per (file name, driver). Vars stay in output-name order."""
    groups = []
    index = {}
    for record in sorted(records, key=lambda item: item["name"]):
        key = (record["fileName"], record["driver"])
        slot = index.get(key)
        if slot is None:
            index[key] = len(groups)
            groups.append(
                {
                    "fileName": record["fileName"],
                    "driver": record["driver"],
                    "outputs": [record],
                }
            )
        else:
            groups[slot]["outputs"].append(record)
    return groups


def product_prim_name(group: dict) -> str:
    outputs = group["outputs"]
    if len(outputs) == 1:
        return prim_token(outputs[0]["name"])
    base = os.path.basename(str(group["fileName"]).replace("\\", "/"))
    stem, _ext = os.path.splitext(base)
    token = prim_token(stem.replace("#", ""))
    if token == "prim":
        token = prim_token(outputs[0]["name"])
    return token


_USD_EXTENSIONS = (".usd", ".usda", ".usdc", ".usdz")


def replace_extension(file_name: str, extension: str) -> str:
    """Swap a USD suffix, or append one when the path has none."""
    ext = str(extension or "").strip().lstrip(".").lower()
    if not ext or not file_name:
        return file_name
    suffix = "." + ext
    root, old = os.path.splitext(file_name)
    if old.lower() in _USD_EXTENSIONS:
        return root + suffix
    return file_name + suffix


def scene_write_path(file_name: str):
    """Path the layer write should use, and the usdz package path if needed.

    `.usdz` is not written directly. Those packages are built from a
    crate file next to the destination, then the crate is removed.
    """
    if str(file_name).lower().endswith(".usdz"):
        return file_name + ".author.usdc", file_name
    return file_name, None


def package_usdz(source: str, destination: str) -> None:
    import os
    import time
    from pxr import UsdUtils

    if not UsdUtils.CreateNewUsdzPackage(source, destination):
        import IECore

        raise IECore.Exception(
            'sdvUSDWriter: failed to package "{}" as "{}"'.format(source, destination)
        )
    for _attempt in range(10):
        try:
            os.remove(source)
            return
        except OSError:
            time.sleep(0.05)


_ENGINE_OPTIONS = {
    "arnold": ("ai:", "arnold:"),
    "renderman": ("ri:", "ri:"),
    "cycles": ("cycles:", "cycles:"),
}

_ENGINE_LABELS = {
    "arnold": "Arnold",
    "renderman": "RenderMan",
    "cycles": "Cycles",
}


def renderer_option_name(option_name: str, renderer: str):
    """USD attribute for a Gaffer option, or None when another engine owns it.

    Arnold globals use ``ai:`` and are written as ``arnold:`` so Arnold USD
    can read them. RenderMan stays ``ri:`` and Cycles stays ``cycles:``.
    Standard ``render:`` options are kept for every engine.
    """
    renderer = (renderer or "").strip().lower()
    name = str(option_name or "")
    for engine, (source, _dest) in _ENGINE_OPTIONS.items():
        if name.startswith(source):
            if renderer and engine != renderer:
                return None
            dest = _ENGINE_OPTIONS[engine][1]
            if dest != source:
                return dest + name[len(source) :]
            return name
    return name


def renderer_label(renderer: str) -> str:
    return _ENGINE_LABELS.get((renderer or "").strip().lower(), renderer or "")


def members_from_globals(compound) -> dict:
    source = compound.members() if hasattr(compound, "members") else compound
    return {str(key): value for key, value in source.items()}


def author_render_settings(
    file_name,
    samples,
    render_root,
    settings_name,
    file_outputs_only,
    camera=None,
    renderer=None,
):
    """Open ``file_name`` and author RenderSettings, RenderProducts, and RenderVars.

    ``samples`` is a list of ``(time_in_seconds, globals_members)`` for the
    frames written into this file. Schema settings come from the first sample.
    ``productName`` is time-sampled when the expanded file name changes.
    """
    import IECore
    from pxr import Usd

    if not samples:
        return
    stage = Usd.Stage.Open(file_name)
    if not stage:
        raise IECore.Exception(
            'sdvUSDWriter: failed to open "{}" to author render settings'.format(file_name)
        )
    _author_stage(
        stage,
        samples,
        render_root,
        settings_name,
        bool(file_outputs_only),
        camera or None,
        renderer or None,
    )
    if not stage.GetRootLayer().Save():
        raise IECore.Exception(
            'sdvUSDWriter: failed to save render settings to "{}"'.format(file_name)
        )


def _author_stage(stage, samples, render_root, settings_name, file_outputs_only, camera=None, renderer=None):
    from pxr import Sdf, UsdRender

    root = _prim_path(render_root or "/Render", "/Render")
    settings_token = prim_token(settings_name or "Settings")
    if settings_token in ("Vars", "Products"):
        import IECore

        raise IECore.Exception(
            "sdvUSDWriter: settings name '{}' clashes with the Vars and Products "
            "scopes under {}.".format(settings_token, root)
        )
    if root.IsAbsoluteRootPath():
        settings_path = Sdf.Path("/").AppendChild(settings_token)
        vars_root = Sdf.Path("/Vars")
        products_root = Sdf.Path("/Products")
    else:
        settings_path = root.AppendChild(settings_token)
        vars_root = root.AppendChild("Vars")
        products_root = root.AppendChild("Products")

    _ensure_scope(stage, settings_path.GetParentPath())
    _ensure_scope(stage, vars_root)
    _ensure_scope(stage, products_root)

    first = samples[0][1]
    records = _output_records(first, file_outputs_only)
    groups = group_records(records)
    names_by_output = {
        record["name"]: _product_names(record["name"], samples) for record in records
    }

    used_vars = set()
    used_products = set()
    var_paths = {}
    product_paths = []
    for group in groups:
        ordered = []
        for record in group["outputs"]:
            parsed = parse_output_data(record["data"])
            if not parsed["sourceName"]:
                parsed = dict(parsed)
                parsed["sourceName"] = record["name"]
            key = _var_key(parsed, record["parameters"])
            path = var_paths.get(key)
            if path is None:
                path = vars_root.AppendChild(
                    unique_token(_var_prim_name(record, parsed), used_vars)
                )
                _define_var(stage, path, parsed, record)
                var_paths[key] = path
            ordered.append(path)
        product_path = products_root.AppendChild(
            unique_token(product_prim_name(group), used_products)
        )
        _define_product(stage, product_path, group, ordered, names_by_output)
        product_paths.append(product_path)

    settings = UsdRender.Settings.Define(stage, settings_path)
    _require_type(settings.GetPrim(), "RenderSettings")
    consumed = _apply_settings(stage, settings, first, camera)
    settings.CreateProductsRel().SetTargets(product_paths)
    _set_render_settings_path(stage, settings_path)
    _write_extra_options(settings.GetPrim(), first, consumed, renderer)
    _promote_arnold_lights(stage)
    _promote_arnold_shaders(stage)
    _drop_root_option_prims(stage)


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
    changed = _promote_arnold_lights(stage)
    changed = _promote_arnold_shaders(stage) or changed
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


_ROOT_OPTION_TYPES = ("ArnoldOptions", "RenderManOptions", "CyclesOptions")


def _drop_root_option_prims(stage):
    """Scene export writes engine globals as a root prim. The same values are on RenderSettings."""
    root = stage.GetPseudoRoot()
    for child in list(root.GetChildren()):
        if child.GetTypeName() in _ROOT_OPTION_TYPES:
            stage.RemovePrim(child.GetPath())


def _set_render_settings_path(stage, path):
    try:
        stage.SetMetadata("renderSettingsPrimPath", str(path))
    except Exception as exc:
        _warn("Could not set renderSettingsPrimPath: {}".format(exc))


def _prim_path(text, fallback):
    from pxr import Sdf

    raw = (text or "").strip() or fallback
    if not raw.startswith("/"):
        raw = "/" + raw
    path = Sdf.Path(raw)
    if path.IsAbsoluteRootPath() or path.IsPrimPath():
        return path
    import IECore

    raise IECore.Exception('sdvUSDWriter: "{}" is not a prim path'.format(raw))


def _ensure_scope(stage, path):
    from pxr import UsdGeom

    if not path or path.IsAbsoluteRootPath():
        return
    parent = path.GetParentPath()
    if parent and not parent.IsAbsoluteRootPath():
        _ensure_scope(stage, parent)
    if not stage.GetPrimAtPath(path):
        UsdGeom.Scope.Define(stage, path)


def _require_type(prim, type_name):
    if prim and prim.GetTypeName() == type_name:
        return
    import IECore

    found = prim.GetTypeName() if prim else ""
    raise IECore.Exception(
        'sdvUSDWriter: cannot author {} at "{}": that location is already a {}.'.format(
            type_name,
            prim.GetPath() if prim else "<missing>",
            found or "untyped prim",
        )
    )


def _output_records(members, file_outputs_only):
    if not any(key.startswith("output:") for key in members):
        return []
    import IECoreScene

    records = []
    for key, value in members.items():
        if not key.startswith("output:"):
            continue
        if not isinstance(value, IECoreScene.Output):
            continue
        driver = str(value.getType() or "")
        if file_outputs_only and driver.lower() in _DISPLAY_DRIVERS:
            continue
        data = str(value.getData() or "")
        file_name = str(value.getName() or "")
        if not data or not file_name:
            continue
        records.append(
            {
                "name": key[len("output:") :],
                "fileName": file_name,
                "driver": driver,
                "data": data,
                "parameters": _parameter_map(value),
            }
        )
    return records


def _parameter_map(output):
    params = output.parameters()
    items = params.items() if hasattr(params, "items") else ()
    return {str(key): value for key, value in items}


def _product_names(output_name, samples):
    """(time, file name) for one output. Missing frames keep the previous name."""
    found = []
    last = None
    for time, members in samples:
        match = None
        for record in _output_records(members, file_outputs_only=False):
            if record["name"] == output_name:
                match = record["fileName"]
                break
        if match is None:
            match = last
        if match is not None:
            found.append((time, match))
            last = match
    return found


def _var_key(parsed, parameters):
    return (
        parsed["sourceName"],
        parsed["dataType"],
        parsed["sourceType"],
        _param_signature(parameters),
    )


def _param_signature(parameters):
    parts = []
    for key in sorted(parameters):
        value = _plain(parameters[key])
        parts.append((key, repr(value)))
    return tuple(parts)


def _var_prim_name(record, parsed):
    layer = _string_param(record["parameters"], "layerName")
    if layer:
        return prim_token(layer)
    if parsed["sourceName"]:
        return prim_token(parsed["sourceName"])
    return prim_token(record["name"])


def _string_param(parameters, name):
    value = _plain(parameters.get(name))
    if value is None:
        return ""
    return str(value)


def _define_var(stage, path, parsed, record):
    from pxr import UsdRender

    var = UsdRender.Var.Define(stage, path)
    _require_type(var.GetPrim(), "RenderVar")
    var.CreateDataTypeAttr().Set(parsed["dataType"])
    var.CreateSourceNameAttr().Set(parsed["sourceName"])
    var.CreateSourceTypeAttr().Set(parsed["sourceType"])
    prim = var.GetPrim()
    _set_custom(prim, "gaffer:data", record["data"])
    for name, data in record["parameters"].items():
        if not _set_custom(prim, "gaffer:" + name, data):
            _warn_skipped("{}:{}".format(record["name"], name), data)


def _define_product(stage, path, group, ordered_vars, names_by_output):
    from pxr import Usd, UsdRender

    product = UsdRender.Product.Define(stage, path)
    _require_type(product.GetPrim(), "RenderProduct")
    driver = (group["driver"] or "").lower()
    product_type = "deepRaster" if driver in ("deepexr", "deep", "deep_exr") else "raster"
    product.CreateProductTypeAttr().Set(product_type)
    _set_custom(product.GetPrim(), "gaffer:driver", group["driver"])
    if ordered_vars:
        product.CreateOrderedVarsRel().SetTargets(ordered_vars)
    names = _group_product_names(group, names_by_output)
    if not names:
        names = [(None, group["fileName"])]
    attr = product.CreateProductNameAttr()
    same = len({name for _time, name in names}) <= 1
    if same or any(time is None for time, _name in names):
        attr.Set(names[0][1])
        return
    for time, name in names:
        attr.Set(name, Usd.TimeCode(time))


def _group_product_names(group, names_by_output):
    """File name samples for a product. Outputs in a group share a file."""
    lead = group["outputs"][0]["name"]
    return list(names_by_output.get(lead, []))


def _apply_settings(stage, settings, members, camera_override=None):
    """Author schema attributes. Return option names fully represented."""
    from pxr import Gf, Vt

    consumed = set()
    resolution = scaled_resolution(
        _plain(members.get("option:render:resolution")),
        _plain(members.get("option:render:resolutionMultiplier")),
    )
    if resolution is not None:
        settings.CreateResolutionAttr().Set(Gf.Vec2i(resolution[0], resolution[1]))
        consumed.add("render:resolution")
        consumed.add("render:resolutionMultiplier")

    pixel_aspect = _plain(members.get("option:render:pixelAspectRatio"))
    if pixel_aspect is not None:
        settings.CreatePixelAspectRatioAttr().Set(float(pixel_aspect))
        consumed.add("render:pixelAspectRatio")

    fit_raw = _plain(members.get("option:render:filmFit"))
    policy = film_fit_policy(fit_raw)
    if policy:
        settings.CreateAspectRatioConformPolicyAttr().Set(policy)
        consumed.add("render:filmFit")
    elif fit_raw is not None:
        _warn("Skipped render:filmFit value {!r}".format(fit_raw))

    if any(("option:" + key) in members for key in _CROP_KEYS):
        overscan_on = bool(_plain(members.get("option:render:overscan")))
        window = data_window_ndc(
            _box2(_plain(members.get("option:render:cropWindow"))),
            overscan_on,
            _plain(members.get("option:render:overscanLeft")),
            _plain(members.get("option:render:overscanRight")),
            _plain(members.get("option:render:overscanTop")),
            _plain(members.get("option:render:overscanBottom")),
        )
        if window is not None:
            settings.CreateDataWindowNDCAttr().Set(Gf.Vec4f(*window))
        consumed.add("render:cropWindow")
        consumed.add("render:overscan")
        if overscan_on:
            consumed.update(
                (
                    "render:overscanTop",
                    "render:overscanBottom",
                    "render:overscanLeft",
                    "render:overscanRight",
                )
            )

    purposes = _plain(members.get("option:render:includedPurposes"))
    if purposes is not None:
        tokens = [str(item) for item in purposes if str(item)]
        settings.CreateIncludedPurposesAttr().Set(Vt.TokenArray(tokens))
        consumed.add("render:includedPurposes")

    depth = _plain(members.get("option:render:depthOfField"))
    dof = bool(depth)
    # A camera fStop with no Gaffer depth-of-field switch still enables Arnold DOF.
    settings.CreateDisableDepthOfFieldAttr().Set(not dof)
    if depth is not None:
        consumed.add("render:depthOfField")

    blur = motion_blur_disabled(
        _plain(members.get("option:sampleMotion")),
        _plain(members.get("option:render:transformBlur")),
        _plain(members.get("option:render:deformationBlur")),
    )
    if blur is not None:
        settings.CreateDisableMotionBlurAttr().Set(bool(blur))
        consumed.update(_MOTION_KEYS)

    if isinstance(camera_override, str):
        camera_override = camera_override.strip() or None
    globals_camera = _plain(members.get("option:render:camera"))
    camera = camera_override if camera_override else globals_camera
    if camera_override or globals_camera is not None:
        consumed.add("render:camera")
        path = _camera_path(camera)
        if path is not None:
            settings.CreateCameraRel().SetTargets([path])
            if not dof:
                _disable_camera_dof(stage, path)
            if _apply_shutter(stage, path, members):
                consumed.add("render:shutter")
    return consumed


def _camera_path(value):
    from pxr import Sdf

    text = str(value).strip()
    if not text:
        return None
    if not text.startswith("/"):
        text = "/" + text
    try:
        path = Sdf.Path(text)
    except Exception:
        return None
    if not path.IsPrimPath():
        return None
    return path


def _disable_camera_dof(stage, path) -> None:
    """USD treats a positive fStop as depth of field. 0 turns it off."""
    from pxr import UsdGeom

    prim = stage.GetPrimAtPath(path)
    if not prim or not prim.IsA(UsdGeom.Camera):
        return
    attr = UsdGeom.Camera(prim).GetFStopAttr()
    if not attr:
        return
    times = attr.GetTimeSamples()
    if times:
        for time in times:
            attr.Set(0.0, time)
    elif attr.HasAuthoredValue():
        attr.Set(0.0)


def _apply_shutter(stage, path, members):
    """Write ``render:shutter`` onto the camera. False if that could not be done."""
    from pxr import UsdGeom

    shutter = _plain(members.get("option:render:shutter"))
    if shutter is None:
        return False
    prim = stage.GetPrimAtPath(path)
    if not prim or not prim.IsA(UsdGeom.Camera):
        _warn(
            "Camera {} is not a UsdGeomCamera, so render:shutter was left as an attribute".format(
                path
            )
        )
        return False
    camera = UsdGeom.Camera(prim)
    open_attr = camera.CreateShutterOpenAttr()
    close_attr = camera.CreateShutterCloseAttr()
    open_attr.Clear()
    close_attr.Clear()
    open_attr.Set(float(shutter[0]))
    close_attr.Set(float(shutter[1]))
    return True


def _write_extra_options(prim, members, consumed, renderer=None):
    label = renderer_label(renderer)
    if label:
        _set_custom(prim, "render:defaultRenderer", label)
        consumed.add("render:defaultRenderer")
    for key, data in members.items():
        if not key.startswith("option:"):
            continue
        name = key[len("option:") :]
        if name in consumed:
            continue
        usd_name = renderer_option_name(name, renderer)
        if usd_name is None:
            continue
        if not _set_custom(prim, usd_name, data):
            _warn_skipped(name, data)


def _set_custom(prim, name, data):
    from pxr import Sdf

    converted = _usd_value(data)
    if converted is None:
        if isinstance(data, str):
            converted = (data, Sdf.ValueTypeNames.String)
        else:
            return False
    value, type_name = converted
    attr_name = attribute_name(name)
    attr = prim.CreateAttribute(
        attr_name,
        type_name,
        custom=True,
        variability=Sdf.VariabilityUniform,
    )
    attr.Set(value)
    return True


def _usd_value(data):
    from pxr import Sdf

    if data is None:
        return None
    if isinstance(data, str):
        return data, Sdf.ValueTypeNames.String

    import IECore
    from pxr import Gf, Vt

    bool_data = getattr(IECore, "BoolData", None)
    if bool_data and isinstance(data, bool_data):
        return bool(data.value), Sdf.ValueTypeNames.Bool
    if isinstance(data, IECore.IntData):
        return int(data.value), Sdf.ValueTypeNames.Int
    uint_data = getattr(IECore, "UIntData", None)
    if uint_data and isinstance(data, uint_data):
        return int(data.value), Sdf.ValueTypeNames.UInt
    if isinstance(data, IECore.FloatData):
        return float(data.value), Sdf.ValueTypeNames.Float
    double_data = getattr(IECore, "DoubleData", None)
    if double_data and isinstance(data, double_data):
        return float(data.value), Sdf.ValueTypeNames.Double
    string_types = [IECore.StringData]
    interned = getattr(IECore, "InternedStringData", None)
    if interned:
        string_types.append(interned)
    if isinstance(data, tuple(string_types)):
        return str(data.value), Sdf.ValueTypeNames.String
    if isinstance(data, IECore.V2iData):
        value = data.value
        return Gf.Vec2i(int(value[0]), int(value[1])), Sdf.ValueTypeNames.Int2
    if isinstance(data, IECore.V2fData):
        value = data.value
        return Gf.Vec2f(float(value[0]), float(value[1])), Sdf.ValueTypeNames.Float2
    v3i = getattr(IECore, "V3iData", None)
    if v3i and isinstance(data, v3i):
        value = data.value
        return Gf.Vec3i(int(value[0]), int(value[1]), int(value[2])), Sdf.ValueTypeNames.Int3
    if isinstance(data, IECore.V3fData):
        value = data.value
        return Gf.Vec3f(float(value[0]), float(value[1]), float(value[2])), Sdf.ValueTypeNames.Float3
    if isinstance(data, IECore.Color3fData):
        value = data.value
        return Gf.Vec3f(float(value[0]), float(value[1]), float(value[2])), Sdf.ValueTypeNames.Color3f
    color4 = getattr(IECore, "Color4fData", None)
    if color4 and isinstance(data, color4):
        value = data.value
        return (
            Gf.Vec4f(float(value[0]), float(value[1]), float(value[2]), float(value[3])),
            Sdf.ValueTypeNames.Color4f,
        )
    if isinstance(data, IECore.StringVectorData):
        return Vt.StringArray([str(item) for item in data]), Sdf.ValueTypeNames.StringArray
    if isinstance(data, IECore.IntVectorData):
        return Vt.IntArray([int(item) for item in data]), Sdf.ValueTypeNames.IntArray
    if isinstance(data, IECore.FloatVectorData):
        return Vt.FloatArray([float(item) for item in data]), Sdf.ValueTypeNames.FloatArray
    return None


def _plain(data):
    if data is None:
        return None
    if hasattr(data, "value") and not isinstance(data, (str, bytes)):
        return data.value
    return data


def _box2(value):
    if value is None:
        return None
    if isinstance(value, (tuple, list)) and len(value) == 4:
        return tuple(float(item) for item in value)
    minimum = value.min() if callable(getattr(value, "min", None)) else value.min
    maximum = value.max() if callable(getattr(value, "max", None)) else value.max
    return (float(minimum[0]), float(minimum[1]), float(maximum[0]), float(maximum[1]))


def _warn(message):
    import IECore

    IECore.msg(IECore.Msg.Level.Warning, "sdvUSDWriter", message)


def _warn_skipped(name, data):
    type_name = type(data).__name__
    if type_name in _SILENT_DATA:
        return
    _warn("Skipped option {} ({})".format(name, type_name))
