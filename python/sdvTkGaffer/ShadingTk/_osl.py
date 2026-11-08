"""OSL slots for ShadingTk.

Checkbox off: the text is an OSLCode shader body. Gaffer compiles it on edit.
Checkbox on: Compile OSL writes a temporary .osl, runs oslc, and puts the
compiled shader in the OSL Path folder (OSL_SHADER_PATHS).
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import Gaffer
import GafferScene
import IECore

from ._box import parse_prim_paths, set_filter_paths
from ._data import MAX_SLOTS, internal_displacement

_SHADER_NAME = re.compile(r"(?m)^\s*shader\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_KINDS = (
    Gaffer.FloatPlug,
    Gaffer.IntPlug,
    Gaffer.Color3fPlug,
    Gaffer.Color4fPlug,
    Gaffer.StringPlug,
)
_BODY_NOTE = (
    "// Shader body for OSLCode. fbm() is inlined; "
    "this node cannot declare functions or #include noise_lib.h.\n"
)


def osl_name_plug(index: int) -> str:
    return "oslName{}".format(index)


def osl_code_plug(index: int) -> str:
    return "oslCode{}".format(index)


def osl_external_plug(index: int) -> str:
    return "oslExternal{}".format(index)


def osl_prim_plug(index: int) -> str:
    return "oslPrim{}".format(index)


def default_osl_folder() -> str:
    """``~/gaffer/shaders`` — the home directory's Gaffer shader folder."""
    folder = os.path.join(os.path.expanduser("~"), "gaffer", "shaders")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        pass
    return folder.replace("\\", "/")


def examples_dir() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[3] / "osl"


def _fbm(target: str, point: str, octaves: int) -> str:
    return (
        "float {target} = 0.0;\n"
        "{{\n"
        "    float amp = 0.5;\n"
        "    point q = {point};\n"
        "    for (int i = 0; i < {octaves}; i++) {{\n"
        '        {target} += amp * noise("perlin", q, t);\n'
        "        q *= 2.0;\n"
        "        amp *= 0.5;\n"
        "    }}\n"
        "}}\n"
    ).format(target=target, point=point, octaves=octaves)


def _warp_prefix() -> str:
    return (
        "point p = P * Scale;\n"
        "float t = Time * Speed;\n"
        "\n"
        + _fbm("fbm_p", "p", 3)
        + _fbm("fbm_b", "p + vector(5.2, 1.3, 2.7)", 3)
        + _fbm("fbm_c", "p + vector(9.1, 4.7, 0.3)", 3)
        + "vector w = vector(fbm_p, fbm_b, fbm_c);\n"
    )


_SURFACE_COLOR = """
// thin-film style angle dependence: color cycles as the view angle changes
float facing = abs(dot(normalize(N), normalize(I)));
float phase = (1.0 - facing) * FilmThickness + n * Rings * 0.25 + t * 0.5;

// cosine palette (Inigo Quilez style): offset phases per channel = rainbow
color a = color(0.5, 0.5, 0.5);
color b = color(0.5, 0.5, 0.5);
color c = color(1.0, 1.0, 1.0);
color d = color(0.0, 0.33, 0.67);
color rainbow = a + b * cos(M_2PI * (c * phase + d));

// push saturation for the psychedelic look
float lum = luminance(rainbow);
Color = mix(color(lum), rainbow, Saturation);

// banded mask, useful for driving emission, roughness or metalness
Mask = 0.5 + 0.5 * sin(n * Rings * M_2PI + t);
"""

SURFACE_FLOATS = (
    ("Time", 0.0),
    ("Scale", 1.5),
    ("Speed", 0.25),
    ("WarpAmount", 0.6),
    ("FilmThickness", 1.5),
    ("Rings", 6.0),
    ("Saturation", 1.2),
)
SURFACE_OUTPUTS = (("Color", "color"), ("Mask", "float"))
DISPLACEMENT_FLOATS = (
    ("Time", 0.0),
    ("Scale", 1.5),
    ("Speed", 0.25),
    ("WarpAmount", 0.6),
    ("Height", 0.1),
)
DISPLACEMENT_OUTPUTS = (("Displacement", "float"),)

SURFACE_BODY = (
    _BODY_NOTE
    + _warp_prefix()
    + "\npoint pw = p + w * WarpAmount;\n"
    + _fbm("n", "pw", 4)
    + _SURFACE_COLOR
)
DISPLACEMENT_BODY = (
    _BODY_NOTE
    + _warp_prefix()
    + "\n"
    + _fbm("n", "p + w * WarpAmount", 4)
    + "\nDisplacement = n * Height;\n"
)

EXAMPLES = (
    {
        "key": "iridescence",
        "label": "Iridescent surface (.osl)",
        "filename": "psychedelic_iridescence.osl",
        "shader": "psychedelic_iridescence",
        "external": True,
    },
    {
        "key": "displacement",
        "label": "Animated displacement (.osl)",
        "filename": "animated_displacement.osl",
        "shader": "animated_displacement",
        "external": True,
    },
    {
        "key": "iridescence_body",
        "label": "Iridescent surface (OSLCode body)",
        "filename": "",
        "shader": "psychedelic_iridescence",
        "external": False,
        "body": SURFACE_BODY,
        "floats": SURFACE_FLOATS,
        "outputs": SURFACE_OUTPUTS,
    },
    {
        "key": "displacement_body",
        "label": "Animated displacement (OSLCode body)",
        "filename": "",
        "shader": "animated_displacement",
        "external": False,
        "body": DISPLACEMENT_BODY,
        "floats": DISPLACEMENT_FLOATS,
        "outputs": DISPLACEMENT_OUTPUTS,
    },
)


def osl_examples() -> list[tuple[str, str]]:
    return [(item["key"], item["label"]) for item in EXAMPLES]


def _example(key: str) -> dict:
    for item in EXAMPLES:
        if item["key"] == key:
            return item
    raise IECore.Exception("Unknown OSL example '{}'.".format(key))


def _loading(node: Gaffer.Node) -> bool:
    script = node.scriptNode()
    if script is None:
        return False
    is_executing = getattr(script, "isExecuting", None)
    if not callable(is_executing):
        return False
    try:
        return bool(is_executing())
    except Exception:
        return False


def _set_status(node: Gaffer.Node, index: int, message: str) -> None:
    status = getattr(node, "_oslStatus", None)
    if status is None:
        status = {}
        node._oslStatus = status
    status[index] = message


def osl_status(node: Gaffer.Node, index: int) -> str:
    return getattr(node, "_oslStatus", {}).get(index, "")


def _short(exc: BaseException) -> str:
    text = str(exc).strip()
    if len(text) > 600:
        text = text[:600] + "…"
    return text


def _plug_index(name: str, prefix: str) -> int | None:
    if not name.startswith(prefix):
        return None
    suffix = name[len(prefix) :]
    if not suffix.isdigit():
        return None
    return int(suffix)


def _hide(plug: Gaffer.Plug) -> None:
    Gaffer.Metadata.registerValue(plug, "nodule:type", "")
    Gaffer.Metadata.registerValue(plug, "layout:visibilityActivator", "never")


def ensure_osl_plugs(node: Gaffer.Node) -> None:
    flags = Gaffer.Plug.Flags.Default
    folder = default_osl_folder()
    if "oslCount" not in node:
        node.addChild(
            Gaffer.IntPlug(
                "oslCount",
                defaultValue=0,
                minValue=0,
                maxValue=MAX_SLOTS,
                flags=flags,
            )
        )
    if "oslPath" not in node:
        node.addChild(Gaffer.StringPlug("oslPath", defaultValue=folder, flags=flags))
    else:
        path_plug = node["oslPath"]
        current = (path_plug.getValue() or "").strip()
        previous = ""
        try:
            previous = (path_plug.defaultValue() or "").strip()
        except Exception:
            previous = ""
        if not current and not previous:
            path_plug.setValue(folder)
    if "oslFrameRate" not in node:
        node.addChild(
            Gaffer.FloatPlug(
                "oslFrameRate",
                defaultValue=24.0,
                minValue=1.0,
                flags=flags,
            )
        )
    _hide(node["oslCount"])
    path = node["oslPath"]
    _hide(path)
    Gaffer.Metadata.registerValue(path, "label", "OSL Path folder")
    Gaffer.Metadata.registerValue(
        path,
        "description",
        "Folder compiled OSL shaders are written to. "
        "It is prepended to OSL_SHADER_PATHS.",
    )
    Gaffer.Metadata.registerValue(
        path, "plugValueWidget:type", "GafferUI.FileSystemPathPlugValueWidget"
    )
    Gaffer.Metadata.registerValue(path, "path:leaf", False)
    rate = node["oslFrameRate"]
    _hide(rate)
    Gaffer.Metadata.registerValue(rate, "label", "Framerate")
    Gaffer.Metadata.registerValue(
        rate,
        "description",
        "Frames per second for Drive Time. "
        "Time = context.getFrame() / Framerate.",
    )
    for index in range(1, MAX_SLOTS + 1):
        name = osl_name_plug(index)
        code = osl_code_plug(index)
        external = osl_external_plug(index)
        if name not in node:
            node.addChild(Gaffer.StringPlug(name, defaultValue="", flags=flags))
        if code not in node:
            node.addChild(
                Gaffer.StringPlug(
                    code,
                    defaultValue="",
                    flags=flags,
                    substitutions=IECore.StringAlgo.Substitutions.NoSubstitutions,
                )
            )
        if external not in node:
            node.addChild(Gaffer.BoolPlug(external, defaultValue=False, flags=flags))
        prim = osl_prim_plug(index)
        if prim not in node:
            node.addChild(Gaffer.StringPlug(prim, defaultValue="", flags=flags))
        _hide(node[name])
        _hide(node[code])
        _hide(node[external])
        _hide(node[prim])
        Gaffer.Metadata.registerValue(node[prim], "label", "PrimPath(s)")
        Gaffer.Metadata.registerValue(node[name], "label", "Name")
        Gaffer.Metadata.registerValue(
            node[external], "label", "Compile externally with `oslc`"
        )
        Gaffer.Metadata.registerValue(
            node[code],
            "plugValueWidget:type",
            "GafferUI.MultiLineStringPlugValueWidget",
        )
        Gaffer.Metadata.registerValue(
            node[code], "multiLineStringPlugValueWidget:role", "code"
        )
        Gaffer.Metadata.registerValue(node[code], "fixedLineHeight", 16)


def _dynamic_flags() -> int:
    return Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic


def ensure_osl_code(node: Gaffer.Node, index: int):
    try:
        import GafferOSL
    except Exception as exc:
        raise IECore.Exception("GafferOSL is not available ({})".format(exc))
    name = "__oslCode{}".format(index)
    existing = node.getChild(name)
    if existing is not None:
        return existing
    code = GafferOSL.OSLCode(name)
    node.addChild(code)
    return code


def ensure_osl_shader(node: Gaffer.Node, index: int):
    try:
        import GafferOSL
    except Exception as exc:
        raise IECore.Exception("GafferOSL is not available ({})".format(exc))
    name = "__oslShader{}".format(index)
    existing = node.getChild(name)
    if existing is not None:
        return existing
    shader = GafferOSL.OSLShader(name)
    node.addChild(shader)
    return shader


def osl_is_assignable(node: Gaffer.Node, index: int) -> bool:
    """True once this slot has a compiled OSL shader to assign."""
    osl = active_osl_node(node, index)
    if osl is None or "out" not in osl:
        return False
    try:
        external = bool(node[osl_external_plug(index)].getValue())
    except Exception:
        external = False
    if external:
        try:
            return bool((osl["name"].getValue() or "").strip())
        except Exception:
            return False
    try:
        return bool((node[osl_code_plug(index)].getValue() or "").strip())
    except Exception:
        return False


def active_osl_node(node: Gaffer.Node, index: int):
    external = False
    try:
        external = bool(node[osl_external_plug(index)].getValue())
    except Exception:
        external = False
    child = "__oslShader{}".format(index) if external else "__oslCode{}".format(index)
    return node.getChild(child)


def _connect_shader_out(destination, osl) -> None:
    if destination is None or osl is None or "out" not in osl:
        return
    out = osl["out"]
    try:
        destination.setInput(out)
        return
    except Exception:
        pass
    for name in ("shader", "closure", "Ci", "Color", "Displacement"):
        if name not in out:
            continue
        try:
            destination.setInput(out[name])
            return
        except Exception:
            continue
    raise IECore.Exception(
        "Could not connect {} into the assignment.".format(osl.getName())
    )


def _drop_named(node: Gaffer.Node, *names: str) -> None:
    for name in names:
        child = node.getChild(name)
        if child is not None:
            node.removeChild(child)


def sync_osl_scene(node: Gaffer.Node, index: int) -> None:
    """ShaderAssignment for the OSL shader, plus displacement when that output exists.

    Color and Mask are shader outputs. They are connected into other shaders,
    not assigned on their own. Displacement is a float output, so when it
    exists the same OSL shader is also the Arnold displacement map.
    """
    if not osl_is_assignable(node, index):
        _drop_named(
            node,
            "__oslFilter{}".format(index),
            "__oslAssign{}".format(index),
            "__oslDisp{}".format(index),
            "__oslDispAssign{}".format(index),
        )
        if hasattr(node, "_rewire_outputs"):
            node._rewire_outputs()
        return
    osl = active_osl_node(node, index)
    filter_name = "__oslFilter{}".format(index)
    path_filter = node.getChild(filter_name)
    if path_filter is None:
        path_filter = GafferScene.PathFilter(filter_name)
        node.addChild(path_filter)
    try:
        text = node[osl_prim_plug(index)].getValue()
    except Exception:
        text = ""
    set_filter_paths(node, filter_name, parse_prim_paths(text))
    assign_name = "__oslAssign{}".format(index)
    assign = node.getChild(assign_name)
    if assign is None:
        assign = GafferScene.ShaderAssignment(assign_name)
        node.addChild(assign)
    try:
        assign["filter"].setInput(path_filter["out"])
    except Exception:
        pass
    _connect_shader_out(assign["shader"], osl)
    displacement = None
    if "out" in osl and "Displacement" in osl["out"]:
        candidate = osl["out"]["Displacement"]
        if isinstance(candidate, Gaffer.FloatPlug):
            displacement = candidate
    disp_name = "__oslDisp{}".format(index)
    disp_assign_name = "__oslDispAssign{}".format(index)
    if displacement is None:
        _drop_named(node, disp_name, disp_assign_name)
    else:
        try:
            import GafferArnold
        except Exception:
            GafferArnold = None
        disp = node.getChild(disp_name) if GafferArnold is not None else None
        if disp is None and GafferArnold is not None:
            try:
                disp = GafferArnold.ArnoldDisplacement(disp_name)
                node.addChild(disp)
            except Exception:
                disp = None
        map_plug = None
        if disp is not None:
            if "map" in disp:
                map_plug = disp["map"]
            elif "parameters" in disp and "map" in disp["parameters"]:
                map_plug = disp["parameters"]["map"]
        if map_plug is not None:
            try:
                map_plug.setInput(osl["out"])
            except Exception:
                try:
                    map_plug.setInput(displacement)
                except Exception:
                    pass
        disp_assign = node.getChild(disp_assign_name)
        if disp is not None and disp_assign is None:
            disp_assign = GafferScene.ShaderAssignment(disp_assign_name)
            node.addChild(disp_assign)
        if disp_assign is not None and disp is not None:
            try:
                disp_assign["filter"].setInput(path_filter["out"])
            except Exception:
                pass
            if "out" in disp and "shader" in disp_assign:
                try:
                    disp_assign["shader"].setInput(disp["out"])
                except Exception:
                    pass
    if hasattr(node, "_rewire_outputs"):
        node._rewire_outputs()


def _ensure_float(code_node, name: str, default: float, assign: bool) -> None:
    params = code_node["parameters"]
    if name not in params:
        params[name] = Gaffer.FloatPlug(
            name, defaultValue=default, flags=_dynamic_flags()
        )
    elif assign:
        params[name].setValue(default)


def _ensure_output(code_node, name: str, kind: str) -> None:
    out = code_node["out"]
    if name in out:
        return
    flags = _dynamic_flags()
    if kind == "color":
        out[name] = Gaffer.Color3fPlug(
            name, direction=Gaffer.Plug.Direction.Out, flags=flags
        )
    else:
        out[name] = Gaffer.FloatPlug(
            name, direction=Gaffer.Plug.Direction.Out, flags=flags
        )


def sync_osl_code(node: Gaffer.Node, index: int) -> None:
    if node[osl_external_plug(index)].getValue():
        return
    code_node = ensure_osl_code(node, index)
    source = node[osl_code_plug(index)].getValue()
    if code_node["code"].getValue() != source:
        code_node["code"].setValue(source)
    if not source.strip():
        _set_status(node, index, "")
        return
    try:
        code_node["__shaderName"].getValue()
    except Exception as exc:
        _set_status(node, index, _short(exc))
        try:
            sync_osl_scene(node, index)
        except Exception:
            pass
        return
    _set_status(node, index, "OSLCode compiled.")
    try:
        sync_osl_scene(node, index)
    except Exception as exc:
        _set_status(node, index, _short(exc))


def _apply_signature(node: Gaffer.Node, index: int, spec: dict) -> None:
    code_node = ensure_osl_code(node, index)
    for name, default in spec.get("floats") or ():
        _ensure_float(code_node, name, default, assign=True)
    for name, kind in spec.get("outputs") or ():
        _ensure_output(code_node, name, kind)


def load_osl_example(node: Gaffer.Node, index: int, key: str) -> None:
    ensure_osl_plugs(node)
    spec = _example(key)
    if spec["filename"]:
        path = examples_dir() / spec["filename"]
        source = path.read_text(encoding="utf-8")
    else:
        source = spec.get("body") or ""
    node._oslMute = True
    try:
        node[osl_external_plug(index)].setValue(bool(spec["external"]))
        node[osl_code_plug(index)].setValue(source)
        if spec.get("shader"):
            node[osl_name_plug(index)].setValue(spec["shader"])
    finally:
        node._oslMute = False
    if spec["external"]:
        _set_status(
            node,
            index,
            "Loaded {}. Set OSL Path folder in Settings, then press Compile OSL.".format(
                spec["shader"]
            ),
        )
        return
    _apply_signature(node, index, spec)
    sync_osl_code(node, index)


def clean_identifier(name: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", name or "")
    if not cleaned or cleaned[0].isdigit():
        cleaned = fallback + cleaned
    return cleaned or fallback


def add_osl_plug(
    node: Gaffer.Node, index: int, name: str, kind: str, output: bool = False
) -> None:
    code_node = ensure_osl_code(node, index)
    parent = code_node["out"] if output else code_node["parameters"]
    fallback = "out" if output else "param"
    plug_name = clean_identifier(name, fallback)
    if plug_name in parent:
        base = plug_name
        suffix = 2
        while plug_name in parent:
            plug_name = "{}{}".format(base, suffix)
            suffix += 1
    if output:
        _ensure_output(code_node, plug_name, "color" if kind == "color" else "float")
    elif kind == "color":
        parent[plug_name] = Gaffer.Color3fPlug(plug_name, flags=_dynamic_flags())
    elif kind == "int":
        parent[plug_name] = Gaffer.IntPlug(plug_name, flags=_dynamic_flags())
    else:
        parent[plug_name] = Gaffer.FloatPlug(plug_name, flags=_dynamic_flags())
    if not node[osl_external_plug(index)].getValue():
        sync_osl_code(node, index)


def add_osl_slot(node: Gaffer.Node) -> None:
    ensure_osl_plugs(node)
    count = int(node["oslCount"].getValue())
    if count >= MAX_SLOTS:
        return
    index = count + 1
    node["oslCount"].setValue(index)
    if node[osl_external_plug(index)].getValue():
        return
    try:
        ensure_osl_code(node, index)
    except Exception as exc:
        _set_status(node, index, _short(exc))


def _move_child(node: Gaffer.Node, source_name: str, dest_name: str) -> None:
    source = node.getChild(source_name)
    dest = node.getChild(dest_name)
    if dest is not None:
        node.removeChild(dest)
    if source is not None:
        source.setName(dest_name)


def _copy_slot(node: Gaffer.Node, source: int, dest: int) -> None:
    node[osl_name_plug(dest)].setValue(node[osl_name_plug(source)].getValue())
    node[osl_code_plug(dest)].setValue(node[osl_code_plug(source)].getValue())
    node[osl_external_plug(dest)].setValue(node[osl_external_plug(source)].getValue())
    node[osl_prim_plug(dest)].setValue(node[osl_prim_plug(source)].getValue())


def _clear_slot(node: Gaffer.Node, index: int) -> None:
    node[osl_name_plug(index)].setValue("")
    node[osl_code_plug(index)].setValue("")
    node[osl_external_plug(index)].setValue(False)
    node[osl_prim_plug(index)].setValue("")


def _delete_child(node: Gaffer.Node, name: str) -> None:
    child = node.getChild(name)
    if child is not None:
        node.removeChild(child)


def remove_osl_slot(node: Gaffer.Node, index: int) -> None:
    ensure_osl_plugs(node)
    count = int(node["oslCount"].getValue())
    if index < 1 or index > count:
        return
    node._oslMute = True
    try:
        for slot in range(index, count):
            _copy_slot(node, slot + 1, slot)
            _move_child(node, "__oslCode{}".format(slot + 1), "__oslCode{}".format(slot))
            _move_child(
                node, "__oslShader{}".format(slot + 1), "__oslShader{}".format(slot)
            )
            _move_child(node, "__oslTime{}".format(slot + 1), "__oslTime{}".format(slot))
            _move_child(node, "__oslFilter{}".format(slot + 1), "__oslFilter{}".format(slot))
            _move_child(node, "__oslAssign{}".format(slot + 1), "__oslAssign{}".format(slot))
            _move_child(node, "__oslDisp{}".format(slot + 1), "__oslDisp{}".format(slot))
            _move_child(
                node,
                "__oslDispAssign{}".format(slot + 1),
                "__oslDispAssign{}".format(slot),
            )
            _retarget_time(node, slot)
        _clear_slot(node, count)
        for name in (
            "__oslCode{}",
            "__oslShader{}",
            "__oslTime{}",
            "__oslFilter{}",
            "__oslAssign{}",
            "__oslDisp{}",
            "__oslDispAssign{}",
        ):
            _delete_child(node, name.format(count))
        status = getattr(node, "_oslStatus", {})
        for slot in range(index, count):
            status[slot] = status.get(slot + 1, "")
        status.pop(count, None)
        node._oslStatus = status
        node["oslCount"].setValue(count - 1)
    finally:
        node._oslMute = False
    if hasattr(node, "_rewire_outputs"):
        node._rewire_outputs()


def shader_name_from_source(source: str) -> str:
    match = _SHADER_NAME.search(source or "")
    if match is None:
        return ""
    return match.group(1)


def resolve_shader_name(node: Gaffer.Node, index: int, source: str) -> str:
    declared = shader_name_from_source(source)
    if declared:
        return declared
    typed = ""
    try:
        typed = node[osl_name_plug(index)].getValue().strip()
    except Exception:
        typed = ""
    if typed:
        return clean_identifier(typed, "osl")
    return "osl_{}".format(index)


def _folder(node: Gaffer.Node, create: bool = False) -> str:
    raw = ""
    try:
        raw = node["oslPath"].getValue().strip()
    except Exception:
        raw = ""
    if not raw:
        return ""
    folder = os.path.normpath(os.path.expanduser(raw))
    if create:
        os.makedirs(folder, exist_ok=True)
    return folder


def prepend_shader_path(folder: str) -> None:
    folder = os.path.normpath(folder)
    current = os.environ.get("OSL_SHADER_PATHS", "")
    parts = [part for part in current.split(os.pathsep) if part]
    folded = [os.path.normcase(os.path.normpath(part)) for part in parts]
    if os.path.normcase(folder) in folded:
        return
    os.environ["OSL_SHADER_PATHS"] = (
        folder + (os.pathsep + current if current else "")
    )


def _install_noise_header(folder: str) -> None:
    source = examples_dir() / "noise_lib.h"
    dest = os.path.join(folder, "noise_lib.h")
    if os.path.isfile(dest) or not source.is_file():
        return
    shutil.copyfile(str(source), dest)


def oslc_executable() -> str:
    names = ("oslc.exe", "oslc") if os.name == "nt" else ("oslc",)
    candidates = []
    root = os.environ.get("GAFFER_ROOT", "")
    if root:
        candidates.extend(os.path.join(root, "bin", name) for name in names)
    for name in names:
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ""


def _forward(path: str) -> str:
    return path.replace("\\", "/")


def compile_osl(node: Gaffer.Node, index: int) -> str:
    ensure_osl_plugs(node)
    if not node[osl_external_plug(index)].getValue():
        raise IECore.Exception(
            "Turn on Compile externally with oslc. "
            "While it is off, the text is an OSLCode shader body and Gaffer compiles it on edit."
        )
    source = node[osl_code_plug(index)].getValue()
    if not source.strip():
        raise IECore.Exception("The OSL source is empty.")
    folder = _folder(node, create=False)
    if not folder:
        raise IECore.Exception(
            "Set OSL Path folder in Settings. Compiled shaders are written there."
        )
    os.makedirs(folder, exist_ok=True)
    _install_noise_header(folder)
    shader_name = resolve_shader_name(node, index, source)
    node._oslMute = True
    try:
        if shader_name_from_source(source):
            node[osl_name_plug(index)].setValue(shader_name)
    finally:
        node._oslMute = False
    oso = os.path.join(folder, shader_name + ".oso")
    oslc = oslc_executable()
    if not oslc:
        raise IECore.Exception(
            "oslc was not found. Launch this from Gaffer so bin/oslc is available."
        )
    temp_dir = tempfile.mkdtemp(prefix="sdvtk_osl_")
    tmp = os.path.join(temp_dir, shader_name + ".osl")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(source)
        installed = os.path.join(folder, "noise_lib.h")
        if os.path.isfile(installed):
            shutil.copyfile(installed, os.path.join(temp_dir, "noise_lib.h"))
        command = [
            oslc,
            "-I" + _forward(folder),
            "-I" + _forward(str(examples_dir())),
            "-o",
            _forward(oso),
            _forward(tmp),
        ]
        run = {
            "capture_output": True,
            "text": True,
            "timeout": 120,
            "stdin": subprocess.DEVNULL,
        }
        if os.name == "nt":
            run["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(command, **run)
        except OSError as exc:
            raise IECore.Exception("Could not run oslc ({})".format(exc))
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "oslc failed").strip()
            raise IECore.Exception(detail or "oslc failed")
        if not os.path.isfile(oso) or os.path.getsize(oso) == 0:
            raise IECore.Exception("oslc did not write {}.".format(oso))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    prepend_shader_path(folder)
    shader = ensure_osl_shader(node, index)
    current = ""
    try:
        current = shader["name"].getValue()
    except Exception:
        current = ""
    try:
        shader.loadShader(shader_name, keepExistingValues=current == shader_name)
    except Exception as exc:
        raise IECore.Exception(
            "Compiled {} but could not load it ({})".format(oso, exc)
        )
    message = "Compiled {}.".format(oso)
    _set_status(node, index, message)
    try:
        sync_osl_scene(node, index)
    except Exception as exc:
        _set_status(node, index, _short(exc))
        raise
    return message


def _reload_external(node: Gaffer.Node, index: int) -> None:
    source = node[osl_code_plug(index)].getValue()
    if not source.strip():
        return
    folder = _folder(node, create=False)
    if not folder or not os.path.isdir(folder):
        _set_status(node, index, "Not compiled yet. Press Compile OSL.")
        return
    shader_name = resolve_shader_name(node, index, source)
    oso = os.path.join(folder, shader_name + ".oso")
    if not os.path.isfile(oso):
        _set_status(node, index, "Not compiled yet. Press Compile OSL.")
        return
    prepend_shader_path(folder)
    shader = ensure_osl_shader(node, index)
    current = ""
    try:
        current = shader["name"].getValue()
    except Exception:
        current = ""
    if current != shader_name:
        shader.loadShader(shader_name, keepExistingValues=False)
    _set_status(node, index, "Loaded {}.".format(oso))
    sync_osl_scene(node, index)


def restore_osl_slots(node: Gaffer.Node) -> None:
    ensure_osl_plugs(node)
    try:
        count = int(node["oslCount"].getValue())
    except Exception:
        return
    for index in range(1, count + 1):
        try:
            if node[osl_external_plug(index)].getValue():
                _reload_external(node, index)
            else:
                if node.getChild("__oslCode{}".format(index)) is None and node[
                    osl_code_plug(index)
                ].getValue().strip():
                    ensure_osl_code(node, index)
                if node.getChild("__oslCode{}".format(index)) is not None:
                    sync_osl_code(node, index)
                elif osl_is_assignable(node, index):
                    sync_osl_scene(node, index)
        except Exception as exc:
            _set_status(node, index, _short(exc))


def _parameter_plugs(osl) -> list:
    if osl is None or "parameters" not in osl:
        return []
    return [plug for plug in osl["parameters"].children() if _is_kind(plug)]


def _is_kind(plug) -> bool:
    return isinstance(plug, _KINDS)


def plugs_match(source, dest) -> bool:
    return any(
        isinstance(source, kind) and isinstance(dest, kind) for kind in _KINDS
    )


def osl_parameter_plugs(node: Gaffer.Node, index: int) -> list:
    return _parameter_plugs(active_osl_node(node, index))


def osl_output_plugs(node: Gaffer.Node, index: int) -> list:
    osl = active_osl_node(node, index)
    if osl is None or "out" not in osl:
        return []
    return [plug for plug in osl["out"].children() if _is_kind(plug)]


def displacement_map_plug(node: Gaffer.Node, slot: int):
    disp = node.getChild(internal_displacement(slot))
    if disp is None:
        return None
    parameters = disp.getChild("parameters")
    if parameters is not None and "map" in parameters:
        plug = parameters["map"]
        if _is_kind(plug):
            return plug
    if "map" in disp and _is_kind(disp["map"]):
        return disp["map"]
    return None


def connect_targets(node: Gaffer.Node, index: int) -> list[dict]:
    outputs = osl_output_plugs(node, index)
    if not outputs:
        return []
    try:
        count = int(node["slotCount"].getValue())
    except Exception:
        count = 0
    items = []
    for output in outputs:
        for slot in range(1, count + 1):
            shader = None
            try:
                shader = node.slotShader(slot)
            except Exception:
                shader = None
            if shader is not None and "parameters" in shader:
                for parm in shader["parameters"].children():
                    if not plugs_match(output, parm):
                        continue
                    label = "{} to slot {} {}".format(
                        output.getName(), slot, parm.getName()
                    )
                    items.append(
                        {
                            "label": label.replace("/", " "),
                            "output": output.getName(),
                            "slot": slot,
                            "parameter": parm.getName(),
                            "displacement": False,
                        }
                    )
            disp = displacement_map_plug(node, slot)
            if disp is not None and plugs_match(output, disp):
                items.append(
                    {
                        "label": "{} to slot {} displacement map".format(
                            output.getName(), slot
                        ),
                        "output": output.getName(),
                        "slot": slot,
                        "parameter": "",
                        "displacement": True,
                    }
                )
    return items


def connect_osl_output(
    node: Gaffer.Node,
    index: int,
    output: str,
    slot: int,
    parameter: str = "",
    displacement: bool = False,
) -> None:
    osl = active_osl_node(node, index)
    if osl is None or "out" not in osl or output not in osl["out"]:
        raise IECore.Exception(
            "This OSL slot has no {} output yet. "
            "Edit the OSLCode plugs, or Compile OSL first.".format(output)
        )
    source = osl["out"][output]
    if displacement:
        target = displacement_map_plug(node, slot)
        if target is None:
            raise IECore.Exception(
                "Shader slot {} has no displacement map. "
                "Give that slot a displacement shader first.".format(slot)
            )
    else:
        shader = node.slotShader(slot)
        if shader is None or "parameters" not in shader or parameter not in shader["parameters"]:
            raise IECore.Exception(
                "Shader slot {} has no {} parameter.".format(slot, parameter)
            )
        target = shader["parameters"][parameter]
    target.setInput(source)
    _set_status(
        node,
        index,
        "Connected {}.".format(output),
    )


def _time_expression(osl_name: str) -> str:
    return (
        'parent["{}"]["parameters"]["Time"] = context.getFrame() / parent["oslFrameRate"]'.format(
            osl_name
        )
    )


def _set_time_expression(expr, osl) -> None:
    expr.setExpression(_time_expression(osl.getName()), "python")


def _retarget_time(node: Gaffer.Node, index: int) -> None:
    expr = node.getChild("__oslTime{}".format(index))
    if expr is None:
        return
    osl = active_osl_node(node, index)
    if osl is None or "parameters" not in osl or "Time" not in osl["parameters"]:
        node.removeChild(expr)
        return
    try:
        _set_time_expression(expr, osl)
    except Exception:
        pass


def drive_osl_time(node: Gaffer.Node, index: int) -> None:
    osl = active_osl_node(node, index)
    if osl is None or "parameters" not in osl or "Time" not in osl["parameters"]:
        raise IECore.Exception(
            "This shader has no Time parameter yet. "
            "Load an example, add a Time plug, or Compile OSL first."
        )
    name = "__oslTime{}".format(index)
    expr = node.getChild(name)
    if expr is None:
        expr = Gaffer.Expression(name)
        node.addChild(expr)
    _set_time_expression(expr, osl)
    _set_status(
        node,
        index,
        "Time = context.getFrame() / Framerate.",
    )


def on_osl_plug_set(node: Gaffer.Node, plug: Gaffer.Plug) -> bool:
    if getattr(node, "_oslMute", False) or _loading(node):
        return False
    name = plug.getName()
    index = _plug_index(name, "oslCode")
    if index is not None:
        try:
            if node[osl_external_plug(index)].getValue():
                _set_status(node, index, "Source changed. Press Compile OSL.")
            else:
                sync_osl_code(node, index)
        except Exception as exc:
            _set_status(node, index, _short(exc))
        return True
    index = _plug_index(name, "oslPrim")
    if index is not None:
        try:
            sync_osl_scene(node, index)
        except Exception as exc:
            _set_status(node, index, _short(exc))
        return True
    index = _plug_index(name, "oslExternal")
    if index is None:
        return False
    try:
        if plug.getValue():
            _set_status(node, index, "Press Compile OSL to compile this file with oslc.")
        else:
            sync_osl_code(node, index)
        sync_osl_scene(node, index)
    except Exception as exc:
        _set_status(node, index, _short(exc))
    return True


def persist_osl_node(child) -> bool:
    if not isinstance(child, Gaffer.Node):
        return False
    try:
        name = child.getName()
    except Exception:
        return False
    if not name.startswith("__osl"):
        return False
    type_name = ""
    try:
        type_name = child.typeName()
    except Exception:
        return False
    return type_name in (
        "GafferOSL::OSLCode",
        "GafferOSL::OSLShader",
        "Gaffer::Expression",
    )
