"""YAML render-settings presets (engine + options + attribute sets)."""

from __future__ import annotations

import os
import re
from typing import Any

import imath

from ._data import ENGINE_ARNOLD, default_engine, path_plug, set_name_plug

PRESET_ENV = "SDVRENDERSETTINGS_PRESET_PATH"
_NAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_NAME_OK = re.compile(r"^[A-Za-z0-9._-]+$")


def builtin_presets_dir() -> str:
    """``presets/sdvRenderSettings`` under the sdvTK-gaffer root."""
    return os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "..",
            "..",
            "presets",
            "sdvRenderSettings",
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
    extra = os.environ.get(PRESET_ENV, "")
    for part in extra.split(os.pathsep):
        part = _clean_dir(part)
        if part:
            dirs.append(part)
    return dirs


def preset_search_dirs(node=None) -> list[tuple[str, str]]:
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
    return _clean_dir(builtin_presets_dir())


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
            engine = str(data.get("engine") or ENGINE_ARNOLD)
            by_key["{}:{}".format(engine, name.lower())] = {
                "name": name,
                "engine": engine,
                "options": data.get("options") or {},
                "slots": data.get("slots") or [],
                "path": path,
                "source": source,
            }
    presets = list(by_key.values())
    presets.sort(key=lambda item: (item["engine"], item["name"].lower()))
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


def snapshot_settings(node) -> dict:
    engine = default_engine()
    try:
        engine = node["renderEngine"].getValue() or engine
    except Exception:
        pass
    options = {}
    options_node = node.optionsNode()
    if options_node is not None and "options" in options_node:
        options = snapshot_name_values(options_node["options"])
    slots = []
    try:
        count = int(node["slotCount"].getValue())
    except Exception:
        count = 0
    for index in range(1, count + 1):
        paths = []
        try:
            path_count = int(node[path_count_plug_name(index)].getValue())
        except Exception:
            path_count = 1
        for path_index in range(1, path_count + 1):
            try:
                text = (node[path_plug(index, path_index)].getValue() or "").strip()
            except Exception:
                text = ""
            if text:
                paths.append(text)
        try:
            name = node[set_name_plug(index)].getValue() or ""
        except Exception:
            name = ""
        attributes = {}
        attr = node.attributesNode(index)
        if attr is not None and "attributes" in attr:
            attributes = snapshot_name_values(attr["attributes"])
        slots.append({"name": name, "paths": paths, "attributes": attributes})
    return {
        "name": "",
        "engine": engine,
        "options": options,
        "slots": slots,
    }


def path_count_plug_name(index: int) -> str:
    return "pathCount{}".format(index)


def apply_preset(node, preset: dict) -> int:
    applied = 0
    engine = str(preset.get("engine") or "")
    if engine and "renderEngine" in node:
        try:
            if node["renderEngine"].getValue() != engine:
                node["renderEngine"].setValue(engine)
                applied += 1
        except Exception:
            pass
    options_node = node.optionsNode()
    if options_node is not None and "options" in options_node:
        applied += apply_name_values(
            options_node["options"], preset.get("options") or {}
        )
    slots = preset.get("slots") or []
    if (
        isinstance(slots, list)
        and slots
        and callable(getattr(node, "_ensure_slots", None))
    ):
        node._ensure_slots(len(slots))
        try:
            node["slotCount"].setValue(min(len(slots), 8))
        except Exception:
            pass
        for index, slot in enumerate(slots, start=1):
            if index > 8 or not isinstance(slot, dict):
                break
            name = str(slot.get("name") or "")
            if name:
                try:
                    node[set_name_plug(index)].setValue(name)
                    applied += 1
                except Exception:
                    pass
            paths = slot.get("paths") or []
            if isinstance(paths, list):
                count = max(1, min(len(paths), 8))
                try:
                    node[path_count_plug_name(index)].setValue(count)
                except Exception:
                    pass
                for path_index in range(1, 9):
                    value = paths[path_index - 1] if path_index <= len(paths) else ""
                    try:
                        node[path_plug(index, path_index)].setValue(str(value))
                        applied += 1
                    except Exception:
                        pass
            attr = node.attributesNode(index)
            if attr is not None and "attributes" in attr:
                applied += apply_name_values(
                    attr["attributes"], slot.get("attributes") or {}
                )
    return applied


def existing_preset_stems(node=None) -> set[str]:
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


def filename_for(name: str, engine: str = "") -> str:
    text = (name or "").strip()
    if not _NAME_OK.match(text):
        text = _NAME_SAFE.sub("_", text).strip("._")
    text = text or "preset"
    prefix = (engine or "render").capitalize()
    return "{}_{}.yaml".format(prefix, text)


def validate_preset_name(name: str, node=None, engine: str | None = None) -> str | None:
    text = (name or "").strip()
    if not text:
        return "Enter a preset name."
    if any(ch.isspace() for ch in text):
        return "Preset names cannot contain spaces."
    if not _NAME_OK.match(text):
        return "Use only letters, numbers, '.', '_' and '-'."
    stem = os.path.splitext(filename_for(text, engine or ""))[0].lower()
    if stem in existing_preset_stems(node):
        return "A preset named '{}' already exists.".format(text)
    return None


def save_settings_preset(node, name: str, folder: str | None = None) -> str:
    engine = default_engine()
    try:
        engine = node["renderEngine"].getValue() or engine
    except Exception:
        pass
    text = (name or "").strip()
    error = validate_preset_name(text, node, engine)
    if error:
        raise ValueError(error)
    data = snapshot_settings(node)
    data["name"] = text
    data["engine"] = engine
    target = _clean_dir(folder or save_dir(node))
    if not target:
        raise ValueError(
            "No preset folder. Create ../../presets next to this module, "
            "or choose a Preset Folder."
        )
    path = os.path.join(target, filename_for(text, engine))
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
        "engine": data.get("engine") or ENGINE_ARNOLD,
        "options": data.get("options") or {},
        "slots": data.get("slots") or [],
    }
    text = _dump_yaml(payload)
    with open(path, "x", encoding="utf-8") as handle:
        handle.write(text)


def snapshot_name_values(parent) -> dict:
    values: dict[str, Any] = {}
    if parent is None:
        return values
    for plug in parent.children():
        name = plug.getName()
        if name.startswith("__"):
            continue
        if "enabled" in plug and "value" in plug:
            try:
                enabled = bool(plug["enabled"].getValue())
            except Exception:
                continue
            value = _plug_to_yaml(plug["value"])
            values[name] = {"enabled": enabled, "value": value}
        else:
            nested = snapshot_name_values(plug)
            if nested:
                values[name] = nested
    return values


def apply_name_values(parent, data) -> int:
    if parent is None or not isinstance(data, dict):
        return 0
    applied = 0
    for name, payload in data.items():
        if name not in parent:
            continue
        plug = parent[name]
        if isinstance(payload, dict) and "enabled" in payload and "value" in plug:
            try:
                plug["enabled"].setValue(bool(payload.get("enabled")))
                applied += 1
            except Exception:
                pass
            if "value" in plug and _set_plug_from_yaml(plug["value"], payload.get("value")):
                applied += 1
        elif isinstance(payload, dict):
            applied += apply_name_values(plug, payload)
    return applied


def _parse_yaml(text: str):
    try:
        import yaml

        return yaml.safe_load(text)
    except Exception:
        return None


def _dump_yaml(data: dict) -> str:
    try:
        import yaml

        return yaml.safe_dump(
            data, sort_keys=False, default_flow_style=None, allow_unicode=True
        )
    except Exception:
        pass
    return "{}\n".format(data)


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
    if hasattr(value, "x"):
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
    if plug is None or plug.getInput() is not None:
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
    if isinstance(value, (list, tuple)):
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
    if "Bool" in type_name:
        return bool(value)
    if "Int" in type_name and not isinstance(value, bool):
        return int(value)
    if "Float" in type_name:
        return float(value)
    if "String" in type_name:
        return str(value)
    return value
