"""Copy, convert, and locate textures for the Texture Manager."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

_CONTEXT_TOKEN = re.compile(r"\$\{([^}]+)\}")

CONVERT_FORMATS = (
    ("exr", "EXR"),
    ("hdr", "HDRI"),
    ("png", "PNG"),
    ("tiff", "TIFF"),
    ("tga", "TGA"),
)


def scene_path(node) -> str:
    script = node.scriptNode() if node is not None else None
    if script is None or "fileName" not in script:
        return ""
    try:
        return str(script["fileName"].getValue() or "").replace("\\", "/")
    except Exception:
        return ""


def _raw_context_value(node, name: str) -> str:
    script = node.scriptNode() if node is not None else None
    if script is None:
        return ""
    try:
        context = script.context()
        if context is not None and name in context:
            value = context.get(name)
            if value is not None:
                return str(value).replace("\\", "/")
    except Exception:
        pass
    if "variables" not in script:
        return ""
    try:
        for child in script["variables"].children():
            key = ""
            if "name" in child:
                key = str(child["name"].getValue() or "")
            if key != name:
                continue
            if "value" in child:
                return str(child["value"].getValue() or "").replace("\\", "/")
    except Exception:
        pass
    return ""


def _unresolved_token(value: str) -> bool:
    text = (value or "").strip()
    return bool(text) and text.startswith("${") and text.endswith("}")


def _substitute_tokens(node, text: str, resolving: set[str] | None = None) -> str:
    if not text or "${" not in text:
        return text or ""
    resolving = resolving or set()

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in resolving:
            return "default" if key == "project:name" else ""
        nested = resolving | {key}
        if key in ("HOME", "USERPROFILE"):
            return os.path.expanduser("~").replace("\\", "/")
        raw = _raw_context_value(node, key).strip() if key == "project:name" else _raw_context_value(node, key)
        if key == "project:name" and (not raw or _unresolved_token(raw)):
            return "default"
        if not raw or _unresolved_token(raw):
            return ""
        return _substitute_tokens(node, raw, nested) or (
            "default" if key == "project:name" else ""
        )

    return _CONTEXT_TOKEN.sub(repl, text)


def context_value(node, name: str) -> str:
    if name == "project:name":
        return project_name(node)
    return _substitute_tokens(node, _raw_context_value(node, name))


def project_name(node) -> str:
    value = _raw_context_value(node, "project:name").strip()
    if not value or _unresolved_token(value):
        return "default"
    resolved = _substitute_tokens(node, value, {"project:name"}).strip()
    return resolved or "default"


def _expand_path(node, path: str) -> str:
    expanded = os.path.expandvars(
        os.path.expanduser(_substitute_tokens(node, path or ""))
    )
    return os.path.normpath(expanded).replace("\\", "/")


def project_root(node) -> str:
    root = _raw_context_value(node, "project:rootDirectory")
    if root:
        return _expand_path(node, root)
    return os.path.join(
        os.path.expanduser("~"), "gaffer", "projects", project_name(node)
    )


def default_texture_dir(node) -> str:
    return os.path.join(project_root(node), "texture").replace("\\", "/")


def scene_textures_dir(node) -> str:
    path = scene_path(node)
    if not path:
        return ""
    return os.path.join(os.path.dirname(path), "textures").replace("\\", "/")


def context_rows(node) -> list[tuple[str, str]]:
    names = (
        "script:name",
        "project:name",
        "project:rootDirectory",
        "image:rootDirectory",
        "frame",
    )
    rows = []
    seen = set()
    for name in names:
        value = context_value(node, name)
        if not value:
            continue
        rows.append((name, value))
        seen.add(name)
    script = node.scriptNode() if node is not None else None
    if script is None or "variables" not in script:
        return rows
    try:
        for child in script["variables"].children():
            key = str(child["name"].getValue() or "") if "name" in child else ""
            if not key or key in seen:
                continue
            value = ""
            if "value" in child:
                value = str(child["value"].getValue() or "")
            if value:
                rows.append((key, value.replace("\\", "/")))
                seen.add(key)
    except Exception:
        pass
    return rows


def resolved_texture_dir(node) -> str:
    next_to_scene = False
    custom = ""
    try:
        if "textureNextToScene" in node:
            next_to_scene = bool(node["textureNextToScene"].getValue())
        if "textureRoot" in node:
            custom = str(node["textureRoot"].getValue() or "").strip()
    except Exception:
        pass
    if next_to_scene:
        beside = scene_textures_dir(node)
        if beside:
            return beside
    if custom:
        return _expand_path(node, custom)
    return default_texture_dir(node)


def use_existing_texture(node) -> bool:
    try:
        if "textureUseExisting" in node:
            return bool(node["textureUseExisting"].getValue())
    except Exception:
        pass
    return True


def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    index = 2
    candidate = "{}_{}{}".format(root, index, ext)
    while os.path.exists(candidate):
        index += 1
        candidate = "{}_{}{}".format(root, index, ext)
    return candidate


def ingest_file(node, filepath: str) -> str:
    src = os.path.abspath(str(filepath or "")).replace("\\", "/")
    if not src or not os.path.isfile(src):
        raise OSError("Not a file: {}".format(filepath))
    dest_dir = resolved_texture_dir(node)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(src)).replace("\\", "/")
    if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dest)):
        return dest
    if os.path.isfile(dest) and use_existing_texture(node):
        return dest.replace("\\", "/")
    if os.path.isfile(dest):
        dest = unique_path(dest).replace("\\", "/")
    shutil.copy2(src, dest)
    return dest.replace("\\", "/")


def _exe(name: str, roots: list[str]) -> str:
    found = shutil.which(name)
    if found:
        return found
    binary = name + (".exe" if os.name == "nt" else "")
    for root in roots:
        if not root:
            continue
        candidate = os.path.join(root, "bin", binary)
        if os.path.isfile(candidate):
            return candidate
    return ""


def find_maketx() -> str:
    roots = [
        os.environ.get("ARNOLD_ROOT", ""),
        os.environ.get("ARNOLD_HOME", ""),
        os.environ.get("GAFFER_ROOT", ""),
    ]
    return _exe("maketx", roots)


def find_txmake() -> str:
    roots = [
        os.environ.get("RMANTREE", ""),
        os.environ.get("RMANTREE_LIB", ""),
        os.environ.get("GAFFER_ROOT", ""),
    ]
    return _exe("txmake", roots)


def find_oiiotool() -> str:
    return _exe("oiiotool", [os.environ.get("GAFFER_ROOT", "")])


def arnold_present() -> bool:
    if find_maketx():
        return True
    try:
        import GafferArnold  # noqa: F401

        return True
    except Exception:
        return False


def renderman_present() -> bool:
    if find_txmake():
        return True
    try:
        import GafferRenderMan  # noqa: F401

        return True
    except Exception:
        return False


def convert_tools() -> list[tuple[str, str]]:
    found = []
    maketx = find_maketx()
    txmake = find_txmake()
    oiio = find_oiiotool()
    if maketx and arnold_present():
        found.append(("maketx", maketx))
    if txmake and renderman_present():
        found.append(("txmake", txmake))
    if oiio:
        found.append(("oiiotool", oiio))
    if maketx and not any(item[0] == "maketx" for item in found):
        found.append(("maketx", maketx))
    if txmake and not any(item[0] == "txmake" for item in found):
        found.append(("txmake", txmake))
    return found


def _run(command: list[str]) -> None:
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": 180,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(command, **kwargs)
    if result.returncode == 0:
        return
    err = (result.stderr or b"").decode("utf-8", "replace").strip()
    out = (result.stdout or b"").decode("utf-8", "replace").strip()
    raise OSError(err or out or " ".join(command))


def convert_file(src: str, dest: str) -> str:
    src = os.path.abspath(src)
    dest = os.path.abspath(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    errors = []
    tools = convert_tools()
    if not tools:
        raise OSError(
            "No converter found (maketx, txmake, or oiiotool)."
        )
    for name, tool in tools:
        try:
            if name == "maketx":
                _run([tool, src, "-o", dest])
            elif name == "txmake":
                _run([tool, src, dest])
            else:
                _run([tool, src, "-o", dest])
            if os.path.isfile(dest):
                return dest.replace("\\", "/")
        except Exception as exc:
            errors.append("{}: {}".format(name, exc))
    raise OSError("Convert failed. " + " | ".join(errors))


def search_dirs(node) -> list[str]:
    found = []
    for path in (
        resolved_texture_dir(node),
        scene_textures_dir(node),
        default_texture_dir(node),
        project_root(node),
        os.path.join(project_root(node), "textures"),
    ):
        if path and os.path.isdir(path) and path not in found:
            found.append(path)
    return found


def find_matching_file(filename: str, directories: list[str]) -> str:
    name = os.path.basename(filename or "")
    if not name:
        return ""
    lower = name.lower()
    stem = os.path.splitext(name)[0].lower()
    for root in directories:
        try:
            for dirpath, _dirnames, files in os.walk(root):
                for item in files:
                    if item.lower() == lower:
                        return os.path.join(dirpath, item).replace("\\", "/")
        except Exception:
            continue
    for root in directories:
        try:
            for dirpath, _dirnames, files in os.walk(root):
                for item in files:
                    if os.path.splitext(item)[0].lower() == stem:
                        return os.path.join(dirpath, item).replace("\\", "/")
        except Exception:
            continue
    return ""


def open_file(path: str, command: str = "") -> None:
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise OSError("Missing file: {}".format(path))
    command = (command or "").strip()
    if command:
        filled = command.replace("{file}", path).replace("{path}", path)
        if "{file}" not in command and "{path}" not in command:
            filled = '{} "{}"'.format(command, path)
        subprocess.Popen(filled, shell=True)
        return
    try:
        from Qt import QtCore, QtGui

        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
        return
    except Exception:
        pass
    if os.name == "nt":
        os.startfile(path)
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
        return
    subprocess.Popen(["xdg-open", path])
