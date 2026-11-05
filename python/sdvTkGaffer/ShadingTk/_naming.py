"""Auto-name slot shaders from picked prim paths."""

from __future__ import annotations

from ._data import DEFAULT_NAME_SUFFIX, shader_handle_name, slot_label


def split_prim_paths(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for raw in (text or "").replace(",", " ").split():
        path = raw.replace("\\", "/").strip()
        if not path:
            continue
        if not path.startswith("/"):
            path = "/" + path
        if path in seen:
            continue
        seen.add(path)
        found.append(path)
    return found


def prim_leaf(path: str) -> str:
    parts = [part for part in (path or "").strip("/").split("/") if part]
    return parts[-1] if parts else "prim"


def prim_parent_leaf(path: str) -> str:
    parts = [part for part in (path or "").strip("/").split("/") if part]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else "parent"


def auto_name_from_paths(
    paths: list[str], prefix: str = "", suffix: str = DEFAULT_NAME_SUFFIX
) -> str:
    """Name from a Pick: one leaf, same-parent group, or variousPick."""
    prefix = (prefix or "").strip()
    suffix = (suffix or "").strip() or DEFAULT_NAME_SUFFIX
    cleaned = []
    seen: set[str] = set()
    for path in paths:
        text = str(path or "").replace("\\", "/").strip()
        if not text:
            continue
        if not text.startswith("/"):
            text = "/" + text
        if text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        stem = prim_leaf(cleaned[0])
        number = ""
    else:
        parents = [prim_parent_leaf(path) for path in cleaned]
        if len(set(parents)) == 1:
            stem = parents[0]
        else:
            stem = "variousPick"
        number = "1"
    parts = [prefix, stem, number]
    body = "".join(parts)
    if suffix:
        return "{}_{}".format(body, suffix) if body else suffix
    return body or slot_label(1)


def _name_token(text: str) -> str:
    cleaned = []
    for char in (text or "").strip().replace(" ", "_"):
        if char.isalnum() or char == "_":
            cleaned.append(char)
    return "".join(cleaned)


def _split_stem_number(stem: str) -> tuple[str, int]:
    i = len(stem)
    while i > 0 and stem[i - 1].isdigit():
        i -= 1
    if i == 0 or i == len(stem):
        return stem, 1
    return stem[:i], int(stem[i:])


def unique_shader_name(
    wanted: str, taken: set[str], index: int, suffix: str = ""
) -> str:
    base = shader_handle_name(wanted, index)
    taken_lower = {name.lower() for name in taken}
    if base.lower() not in taken_lower:
        return base
    tag = ""
    token = _name_token(suffix)
    if token:
        ending = "_{}".format(token)
        if base.endswith(ending) and len(base) > len(ending):
            tag = ending
    stem = base[: -len(tag)] if tag else base
    core, current = _split_stem_number(stem)
    n = current + 1 if stem != core else 2
    while True:
        candidate = shader_handle_name("{}{}{}".format(core, n, tag), index)
        if candidate.lower() not in taken_lower:
            return candidate
        n += 1
