"""YAML shader presets for ShadingTk slots."""

from __future__ import annotations

import os
import re
from typing import Any

import imath

from ._data import STANDARD_SURFACE, shader_file_prefix, shader_type_plug

PRESET_ENV = "SHADINGTK_PRESET_PATH"
_NAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_NAME_OK = re.compile(r"^[A-Za-z0-9._-]+$")


def builtin_presets_dir() -> str:
    """``presets/ShadingTk`` under the sdvTK-gaffer root."""
    return os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "..",
            "..",
            "presets",
            "ShadingTk",
        )
    )


def _gaffer_bin_dir() -> str:
    try:
        cwd = os.path.normcase(os.path.abspath(os.getcwd()))
    except Exception:
        cwd = ""
    if not cwd or os.path.basename(cwd) != "bin":
        return ""
    for executable in ("gaffer.exe", "gaffer.cmd", "gaffer"):
        if os.path.isfile(os.path.join(cwd, executable)):
            return cwd
    return ""


def is_gaffer_bin_dir(path: str) -> bool:
    """True for Gaffer's ``bin`` (cwd of ``gaffer.exe``) — never store presets there."""
    text = os.path.normpath(os.path.expandvars(os.path.expanduser((path or "").strip())))
    if not text:
        return False
    try:
        resolved = os.path.normcase(os.path.abspath(text))
    except Exception:
        resolved = os.path.normcase(text)
    gaffer_bin = _gaffer_bin_dir()
    if gaffer_bin and (
        resolved == gaffer_bin or resolved.startswith(gaffer_bin + os.sep)
    ):
        return True
    if os.path.basename(resolved) != "bin":
        return False
    for executable in ("gaffer.exe", "gaffer.cmd", "gaffer"):
        if os.path.isfile(os.path.join(resolved, executable)):
            return True
    return False


def discovered_presets_dir() -> str:
    """Absolute ``../../presets`` path when that folder exists, else ``""``."""
    folder = builtin_presets_dir()
    if folder and os.path.isdir(folder) and not is_gaffer_bin_dir(folder):
        return folder
    return ""


def bind_preset_folder(node) -> None:
    """Write ``../../presets`` into ``presetFolder`` when discovered; else leave blank."""
    if node is None or "presetFolder" not in node:
        return
    found = discovered_presets_dir()
    try:
        current = (node["presetFolder"].getValue() or "").strip()
    except Exception:
        return
    if current and not is_gaffer_bin_dir(current):
        return
    try:
        node["presetFolder"].setValue(found)
    except Exception:
        pass


def _clean_dir(path: str) -> str:
    text = os.path.normpath(os.path.expandvars(os.path.expanduser((path or "").strip())))
    if not text:
        return ""
    if not os.path.isabs(text):
        text = os.path.normpath(os.path.join(os.path.dirname(builtin_presets_dir()), text))
    if is_gaffer_bin_dir(text):
        return ""
    return text


def user_preset_dirs(node=None) -> list[str]:
    dirs: list[str] = []
    if node is not None and "presetFolder" in node:
        try:
            custom = (node["presetFolder"].getValue() or "").strip()
        except Exception:
            custom = ""
        custom = _clean_dir(custom)
        if custom:
            dirs.append(custom)
    extra = os.environ.get(PRESET_ENV) or os.environ.get(
        "SHADINGOVERRIDE_PRESET_PATH", ""
    )
    for part in extra.split(os.pathsep):
        part = _clean_dir(part)
        if part:
            dirs.append(part)
    return dirs


def preset_search_dirs(node=None) -> list[tuple[str, str]]:
    """``(path, source)`` — node folder first, then discovered ``../../presets``."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(path: str, source: str) -> None:
        folder = _clean_dir(path)
        if not folder:
            return
        key = os.path.normcase(folder)
        if key in seen:
            return
        seen.add(key)
        found.append((folder, source))

    for path in user_preset_dirs(node):
        add(path, "user")
    add(discovered_presets_dir(), "built-in")
    return found


def save_dir(node=None) -> str:
    dirs = user_preset_dirs(node)
    if dirs:
        return dirs[0]
    found = discovered_presets_dir()
    if found:
        return found
    expected = _clean_dir(builtin_presets_dir())
    return expected


def dialog_start_dir(node=None) -> str:
    """Existing folder for file dialogs — never Gaffer ``bin`` / cwd."""
    for candidate in (
        save_dir(node),
        discovered_presets_dir(),
        _clean_dir(builtin_presets_dir()),
        os.path.dirname(_clean_dir(builtin_presets_dir())),
    ):
        folder = _clean_dir(candidate)
        if folder and os.path.isdir(folder):
            return folder
    return ""


def list_presets(node=None) -> list[dict]:
    """Unique presets by shader + display name. Later folders override earlier ones."""
    by_key: dict[str, dict] = {}
    for folder, source in preset_search_dirs(node):
        if not os.path.isdir(folder):
            continue
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for filename in names:
            if not filename.lower().endswith((".yaml", ".yml")):
                continue
            path = os.path.join(folder, filename)
            data = load_preset_file(path)
            if not data:
                continue
            name = str(data.get("name") or os.path.splitext(filename)[0])
            shader = str(data.get("shader") or STANDARD_SURFACE)
            by_key["{}:{}".format(shader, name.lower())] = {
                "name": name,
                "shader": shader,
                "parameters": data.get("parameters") or {},
                "path": path,
                "source": source,
            }
    presets = list(by_key.values())
    presets.sort(key=lambda item: (item["shader"], item["name"].lower()))
    return presets


def load_preset_file(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError:
        return None
    data = _parse_yaml(raw)
    if not isinstance(data, dict):
        return None
    return data


def snapshot_slot(node, index: int) -> dict:
    shader = node.slotShader(index)
    shader_name = STANDARD_SURFACE
    try:
        shader_name = node[shader_type_plug(index)].getValue() or STANDARD_SURFACE
    except Exception:
        pass
    parameters: dict[str, Any] = {}
    if shader is not None and "parameters" in shader:
        for plug in shader["parameters"].children():
            if plug.getName().startswith("__"):
                continue
            if plug.getInput() is not None:
                continue
            value = _plug_to_yaml(plug)
            if value is not None:
                parameters[plug.getName()] = value
    return {
        "name": "",
        "shader": shader_name,
        "parameters": parameters,
    }


def apply_preset(node, index: int, preset: dict) -> int:
    shader_name = str(preset.get("shader") or STANDARD_SURFACE)
    try:
        if node[shader_type_plug(index)].getValue() != shader_name:
            node[shader_type_plug(index)].setValue(shader_name)
        else:
            node._load_slot_shader(index)
    except Exception:
        node._load_slot_shader(index)
    shader = node.slotShader(index)
    if shader is None or "parameters" not in shader:
        return 0
    applied = 0
    params = preset.get("parameters") or {}
    if not isinstance(params, dict):
        return 0
    for name, value in params.items():
        if name not in shader["parameters"]:
            continue
        if _set_plug_from_yaml(shader["parameters"][name], value):
            applied += 1
    return applied


def existing_preset_stems(node=None) -> set[str]:
    """Lowercased YAML stems already on disk."""
    stems: set[str] = set()
    for preset in list_presets(node):
        path = str(preset.get("path") or "")
        if path:
            stems.add(os.path.splitext(os.path.basename(path))[0].lower())
    folder = save_dir(node)
    if os.path.isdir(folder):
        try:
            listing = os.listdir(folder)
        except OSError:
            listing = []
        for filename in listing:
            if filename.lower().endswith((".yaml", ".yml")):
                stems.add(os.path.splitext(filename)[0].lower())
    return stems


def existing_preset_keys(node=None) -> set[str]:
    """``shader:name`` keys already in use."""
    keys: set[str] = set()
    for preset in list_presets(node):
        label = str(preset.get("name") or "").strip()
        shader = str(preset.get("shader") or "")
        if label:
            keys.add("{}:{}".format(shader, label.lower()))
    return keys


def look_name(name: str, shader: str = "") -> str:
    """Display name with a redundant ``StandardSurface_`` prefix stripped."""
    text = (name or "").strip()
    prefix = shader_file_prefix(shader) if shader else ""
    if prefix and text.lower().startswith(prefix.lower() + "_"):
        rest = text[len(prefix) + 1 :]
        if rest:
            return rest
    return text


def validate_preset_name(name: str, node=None, shader: str | None = None) -> str | None:
    """Error text if *name* cannot be saved, otherwise ``None``."""
    text = look_name(name, shader or "")
    if not text:
        return "Enter a preset name."
    if any(ch.isspace() for ch in text):
        return "Preset names cannot contain spaces."
    if not _NAME_OK.match(text):
        return "Use only letters, numbers, '.', '_' and '-'."
    shader_name = shader or STANDARD_SURFACE
    stem = os.path.splitext(filename_for(text, shader_name))[0].lower()
    if stem in existing_preset_stems(node):
        return "A preset named '{}' already exists.".format(text)
    if "{}:{}".format(shader_name, text.lower()) in existing_preset_keys(node):
        return "A preset named '{}' already exists.".format(text)
    return None


def save_slot_preset(node, index: int, name: str, folder: str | None = None) -> str:
    shader = STANDARD_SURFACE
    try:
        shader = node[shader_type_plug(index)].getValue() or STANDARD_SURFACE
    except Exception:
        pass
    text = look_name(name, shader)
    error = validate_preset_name(text, node, shader)
    if error:
        raise ValueError(error)
    data = snapshot_slot(node, index)
    data["name"] = text
    data["shader"] = shader
    target = _clean_dir(folder or save_dir(node))
    if not target:
        raise ValueError(
            "No preset folder. Create ../../presets next to this module, "
            "or choose a Preset Folder."
        )
    path = os.path.join(target, filename_for(text, shader))
    if os.path.exists(path):
        raise ValueError("A preset named '{}' already exists.".format(text))
    write_preset(path, data)
    return path


def write_preset(path: str, data: dict) -> None:
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    payload = {
        "name": data.get("name") or os.path.splitext(os.path.basename(path))[0],
        "shader": data.get("shader") or STANDARD_SURFACE,
        "parameters": data.get("parameters") or {},
    }
    text = _dump_yaml(payload)
    with open(path, "x", encoding="utf-8") as handle:
        handle.write(text)


def filename_for(name: str, shader: str = "") -> str:
    text = look_name(name, shader)
    if not _NAME_OK.match(text):
        text = _NAME_SAFE.sub("_", text).strip("._")
    text = text or "preset"
    prefix = shader_file_prefix(shader) if shader else ""
    if prefix:
        return "{}_{}.yaml".format(prefix, text)
    return "{}.yaml".format(text)


def _parse_yaml(text: str):
    try:
        import yaml

        return yaml.safe_load(text)
    except Exception:
        pass
    return None


def _dump_yaml(data: dict) -> str:
    try:
        import yaml

        return yaml.safe_dump(
            data, sort_keys=False, default_flow_style=None, allow_unicode=True
        )
    except Exception:
        pass
    lines = [
        "name: {}".format(_scalar(data.get("name"))),
        "shader: {}".format(_scalar(data.get("shader"))),
        "parameters:",
    ]
    params = data.get("parameters") or {}
    for key, value in params.items():
        lines.append("  {}: {}".format(key, _flow(value)))
    return "\n".join(lines) + "\n"


def _scalar(value) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    if re.search(r"[:#\n]", text) or text == "":
        return json_dumps_fallback(text)
    return text


def json_dumps_fallback(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _flow(value) -> str:
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_flow(v) for v in value) + "]"
    return _scalar(value)


def _plug_to_yaml(plug):
    getter = getattr(plug, "getValue", None)
    if not callable(getter):
        return None
    try:
        value = getter()
    except Exception:
        return None
    return _value_to_yaml(value)


def _value_to_yaml(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return value
    for attr in ("x", "y", "z", "w"):
        if not hasattr(value, "x"):
            break
        parts = []
        for name in ("x", "y", "z", "w"):
            if hasattr(value, name):
                parts.append(float(getattr(value, name)))
        return parts
    if hasattr(value, "r") and hasattr(value, "g") and hasattr(value, "b"):
        parts = [float(value.r), float(value.g), float(value.b)]
        if hasattr(value, "a"):
            parts.append(float(value.a))
        return parts
    return None


def _set_plug_from_yaml(plug, value) -> bool:
    if plug.getInput() is not None:
        return False
    setter = getattr(plug, "setValue", None)
    if not callable(setter):
        return False
    coerced = _coerce_for_plug(plug, value)
    try:
        setter(coerced)
        return True
    except Exception:
        pass
    if isinstance(value, (list, tuple)) and hasattr(plug, "setValue"):
        try:
            if len(value) >= 3 and "Color3f" in type(plug).__name__:
                setter(imath.Color3f(*[float(v) for v in value[:3]]))
                return True
        except Exception:
            pass
    return False


def _coerce_for_plug(plug, value):
    type_name = type(plug).__name__
    if isinstance(value, (list, tuple)):
        nums = [float(v) for v in value]
        if "Color4f" in type_name and len(nums) >= 4:
            return imath.Color4f(*nums[:4])
        if "Color3f" in type_name and len(nums) >= 3:
            return imath.Color3f(*nums[:3])
        if "V3f" in type_name and len(nums) >= 3:
            return imath.V3f(*nums[:3])
        if "V2f" in type_name and len(nums) >= 2:
            return imath.V2f(*nums[:2])
        if "Color4f" in type_name and len(nums) >= 3:
            return imath.Color4f(nums[0], nums[1], nums[2], 1.0)
    if "Bool" in type_name:
        return bool(value)
    if "Int" in type_name and not isinstance(value, bool):
        return int(value)
    if "Float" in type_name:
        return float(value)
    if "String" in type_name:
        return str(value)
    return value
