"""Slot limits, Arnold shader menus, and plug names."""

from __future__ import annotations

import IECore

MAX_SLOTS = 8
MAX_PATHS = 8
STANDARD_SURFACE = "standard_surface"
MODE_CREATE = "create"
MODE_EDIT = "edit"

META_UI_NAME = "ui.name"
META_NODE_MENU_CATEGORY = "gaffer.nodeMenu.category"

SLOT_SHADERS = (
    ("standard_surface", "StandardSurface"),
    ("open_pbr_surface", "Open PBR Surface"),
    ("car_paint", "CarPaint"),
    ("standard_volume", "StandardVolume"),
    ("standard_hair", "StandardHair"),
    ("layer_shader", "LayerShader"),
    ("mix_shader", "MixShader"),
    ("matte", "Matte"),
    ("toon", "Toon"),
    ("utility", "Utility"),
)

FALLBACK_TEXTURE_SHADERS = (
    ("checkerboard", "Checkerboard"),
    ("image", "Image"),
    ("noise", "Noise"),
    ("cell_noise", "Cell Noise"),
    ("ramp_rgb", "Ramp RGB"),
    ("triplanar", "Triplanar"),
    ("physical_texture", "Physical Texture"),
)

COLOR_PARAMETER_NAMES = (
    "base_color",
    "color",
    "diffuse_color",
    "Kd_color",
    "albedo",
    "emission_color",
)


SLOT_META = "shadingTk:slot"
ROLE_META = "shadingTk:role"

ALL_SHADER_NAME = "all_shd"
MATTE_SHADER_NAME = "matte_shd"
DIAG_SHADER_NAME = "diag_shd"
MIX_SHADER_NAME = "mix_shd"
DEFAULT_NAME_SUFFIX = "shd"

TRANSFER_SKIP_SHADERS = frozenset({"layer_shader", "mix_shader"})
MAX_MIX_INPUTS = 8
MIX_SHADER = "mix_shader"
LAYER_SHADER = "layer_shader"

GLOBAL_FILTER = "__allFilter"
GLOBAL_ASSIGN = "__allAssign"
GLOBAL_SWITCH = "__allSwitch"
GLOBAL_TEXTURE = "__allTexture"
MATTE_FILTER = "__matteFilter"
MATTE_ASSIGN = "__matteAssign"
MATTE_SWITCH = "__matteSwitch"
DIAG_FILTER = "__diagFilter"
DIAG_ASSIGN = "__diagAssign"
DIAG_SWITCH = "__diagSwitch"
MIX_FILTER = "__mixFilter"
MIX_ASSIGN = "__mixAssign"
MIX_SWITCH = "__mixSwitch"

DIAGNOSTIC_SHADERS = (
    ("utility", "Utility"),
    ("ambient_occlusion", "Ambient Occlusion"),
    ("wireframe", "Wireframe"),
    ("facing_ratio", "Facing Ratio"),
    ("curvature", "Curvature"),
    ("flat", "Flat"),
    ("motion_vector", "Motion Vector"),
    ("shadow_matte", "Shadow Matte"),
)

UTILITY_COLOR_MODES = (
    ("ng", "Geometric Normal"),
    ("n", "Smooth Normal"),
    ("bary", "Barycentric"),
    ("uv", "UV"),
    ("u", "U"),
    ("v", "V"),
    ("primitive", "Primitive ID"),
    ("object", "Object"),
    ("shader", "Shader"),
    ("instance", "Instance"),
    ("color", "Color"),
)

PARAM_ALIASES = {
    "base_color": (
        "base_color",
        "color",
        "diffuse_color",
        "Kd_color",
        "albedo",
    ),
    "color": ("color", "base_color", "diffuse_color", "Kd_color", "albedo"),
    "specular": ("specular", "specular_weight", "Ks"),
    "specular_color": ("specular_color", "Ks_color"),
    "specular_roughness": ("specular_roughness", "roughness"),
    "metalness": ("metalness", "metallic"),
    "base": ("base", "base_weight", "Kd"),
    "emission": ("emission", "emission_weight"),
    "emission_color": ("emission_color",),
    "coat": ("coat", "coat_weight", "clearcoat"),
    "coat_color": ("coat_color", "clearcoat_color"),
    "coat_roughness": ("coat_roughness", "clearcoat_roughness"),
    "transmission": ("transmission", "transmission_weight"),
    "transmission_color": ("transmission_color",),
    "specular_IOR": ("specular_IOR", "ior", "IOR"),
    "opacity": ("opacity",),
    "normal": ("normal", "normal_camera"),
    "sheen": ("sheen", "sheen_weight"),
    "sheen_color": ("sheen_color",),
    "subsurface": ("subsurface", "subsurface_weight"),
    "subsurface_color": ("subsurface_color",),
    "subsurface_radius": ("subsurface_radius",),
    "anisotropy": ("anisotropy", "specular_anisotropy"),
    "thin_walled": ("thin_walled",),
}


def mix_input_plug(index: int) -> str:
    return "mixInput{}".format(index)


def slot_label(index: int) -> str:
    return "_shd{}".format(index)


def shader_handle_name(text: str, index: int) -> str:
    """Gaffer node name used as the ShaderNetwork handle (ai:surface Name)."""
    cleaned = []
    for char in (text or "").strip().replace(" ", "_"):
        if char.isalnum() or char == "_":
            cleaned.append(char)
    name = "".join(cleaned)
    if not name or not (name[0].isalpha() or name[0] == "_"):
        return slot_label(index)
    return name


def shader_file_prefix(shader_name: str) -> str:
    """Compact type token for preset files, e.g. standard_surface → StandardSurface."""
    for name, label in SLOT_SHADERS:
        if name == shader_name:
            return "".join(label.split())
    return "".join(_display_name(shader_name or "").split()) or "Shader"


def shader_type_plug(index: int) -> str:
    return "shaderType{}".format(index)


def shader_name_plug(index: int) -> str:
    return "shaderName{}".format(index)


def texture_type_plug(index: int) -> str:
    return "textureType{}".format(index)


def displacement_type_plug(index: int) -> str:
    return "displacementType{}".format(index)


def path_count_plug(index: int) -> str:
    return "pathCount{}".format(index)


def path_plug(slot: int, path_index: int) -> str:
    return "path{}_{}".format(slot, path_index)


def internal_shader(index: int) -> str:
    return "__shader{}".format(index)


def internal_texture(index: int) -> str:
    return "__texture{}".format(index)


def internal_disp_map(index: int) -> str:
    return "__dispMap{}".format(index)


def internal_displacement(index: int) -> str:
    return "__displacement{}".format(index)


def internal_disp_assign(index: int) -> str:
    return "__dispAssign{}".format(index)


def internal_disp_switch(index: int) -> str:
    return "__dispSwitch{}".format(index)


def internal_filter(index: int) -> str:
    return "__pathFilter{}".format(index)


def internal_assign(index: int) -> str:
    return "__assign{}".format(index)


def internal_switch(index: int) -> str:
    return "__slotSwitch{}".format(index)


TEXTURES_BOX = "Textures"
LIBRARY_PREFIX = "lib:"

EDIT_SHADER = "__editShader"
EDIT_FILTER = "__editFilter"
EDIT_ASSIGN = "__editAssign"
EDIT_SWITCH = "__editSwitch"
EDIT_SCOPE = "__shaderEdits"


def assign_source_plug(index: int) -> str:
    return "assignSource{}".format(index)


def assign_path_plug(index: int) -> str:
    return "assignPath{}".format(index)


def internal_reassign_filter(index: int) -> str:
    return "__reassignFilter{}".format(index)


def internal_reassign_copy(index: int) -> str:
    return "__reassignCopy{}".format(index)


def internal_reassign_switch(index: int) -> str:
    return "__reassignSwitch{}".format(index)


def assign_slot_label(index: int) -> str:
    return "Assign {}".format(index)


def _display_name(shader_name: str, node_entry=None) -> str:
    if node_entry is not None:
        try:
            import arnold

            value = arnold.AtStringStruct()
            if arnold.AiMetaDataGetStr(node_entry, "", META_UI_NAME, value):
                name = arnold.AtStringToStr(value)
                if name:
                    return name
        except Exception:
            pass
    return " ".join(
        IECore.CamelCase.toSpaced(part) for part in shader_name.split("_")
    )


def _ai_metadata_str(node_entry, param_name: str, name: str):
    try:
        import arnold

        value = arnold.AtStringStruct()
        if arnold.AiMetaDataGetStr(node_entry, param_name, name, value):
            return arnold.AtStringToStr(value)
    except Exception:
        pass
    return None


def _iter_shader_entries():
    import arnold
    import IECoreArnold
    import GafferArnold  # noqa: F401

    with IECoreArnold.UniverseBlock(writable=False):
        it = arnold.AiUniverseGetNodeEntryIterator(arnold.AI_NODE_SHADER)
        try:
            while not arnold.AiNodeEntryIteratorFinished(it):
                yield arnold.AiNodeEntryIteratorGetNext(it)
        finally:
            arnold.AiNodeEntryIteratorDestroy(it)


def _category(node_entry) -> str:
    return (_ai_metadata_str(node_entry, "", META_NODE_MENU_CATEGORY) or "").strip()


_TEXTURE_SHADERS: list[tuple[str, str]] | None = None
_KNOWN_NAMES: set[str] | None = None


def list_slot_shaders() -> list[tuple[str, str]]:
    """Shaders offered on each slot (fixed Arnold set)."""
    return list(SLOT_SHADERS)


def list_texture_shaders() -> list[tuple[str, str]]:
    """Arnold texture / procedural shaders for a quick color/diffuse map."""
    global _TEXTURE_SHADERS
    if _TEXTURE_SHADERS is not None:
        return _TEXTURE_SHADERS
    found: list[tuple[str, str]] = []
    try:
        import arnold

        for entry in _iter_shader_entries():
            name = arnold.AiNodeEntryGetName(entry)
            category = _category(entry).lower()
            if "texture" in category or name in {n for n, _ in FALLBACK_TEXTURE_SHADERS}:
                if _category(entry) == "":
                    continue
                found.append((name, _display_name(name, entry)))
    except Exception:
        _TEXTURE_SHADERS = list(FALLBACK_TEXTURE_SHADERS)
        return _TEXTURE_SHADERS
    # Keep fallback names even if category metadata missed them.
    have = {name for name, _ in found}
    for name, label in FALLBACK_TEXTURE_SHADERS:
        if name not in have:
            found.append((name, label))
    found.sort(key=lambda item: item[1].lower())
    _TEXTURE_SHADERS = found or list(FALLBACK_TEXTURE_SHADERS)
    return _TEXTURE_SHADERS


def known_shader_names() -> set[str]:
    global _KNOWN_NAMES
    if _KNOWN_NAMES is None:
        _KNOWN_NAMES = {name for name, _ in list_slot_shaders()} | {
            STANDARD_SURFACE
        }
    return _KNOWN_NAMES
