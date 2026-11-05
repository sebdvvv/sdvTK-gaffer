"""Arnold light types and Node Editor parameter filters."""

from __future__ import annotations

MESH_LIGHT = "mesh_light"
GAFFER_ARNOLD_LIGHT = "ArnoldLight"
GAFFER_ARNOLD_MESH_LIGHT = "ArnoldMeshLight"

LIGHT_SHADER_TO_GAFFER_TYPE = {
    MESH_LIGHT: GAFFER_ARNOLD_MESH_LIGHT,
}

# Area (quad) first = default. No skydome — that is ArnoldPhysicalSky.
ARNOLD_LIGHT_TYPES = (
    ("quad_light", "Area Light"),
    ("disk_light", "Disk Light"),
    ("cylinder_light", "Cylinder Light"),
    ("point_light", "Point Light"),
    ("spot_light", "Spot Light"),
    ("distant_light", "Distant Light"),
    ("photometric_light", "Photometric Light"),
    (MESH_LIGHT, "Mesh Light"),
)

CONTRIBUTION_PARAMETERS = frozenset(
    {
        "camera",
        "transmission",
        "diffuse",
        "specular",
        "sss",
        "indirect",
        "volume",
        "max_bounces",
        "aov",
        "samples",
        "normalize",
    }
)

# Missing key or None = show every non-contribution parameter on the Light tab.
LIGHT_PARAMETER_FILTER = {}

SPOT_LIGHT = "spot_light"

# Shape / beam controls — only plugs that exist on the *current* light appear.
SHAPING_PARAMETERS = frozenset(
    {
        "roundness",
        "soft_edge",
        "cone_angle",
        "penumbra_angle",
        "cosine_power",
        "spread",
        "lens_radius",
        "aspect_ratio",
        "angle",
    }
)

SHAPING_LABELS = {
    "roundness": "Roundness",
    "soft_edge": "Soft Edge",
    "cone_angle": "Cone Angle",
    "penumbra_angle": "Cone Softness",
    "cosine_power": "Focus",
    "spread": "Spread",
    "lens_radius": "Lens Radius",
    "aspect_ratio": "Aspect Ratio",
    "angle": "Angle",
}

# Spot gobo projection UV (Arnold gobo filter). Tried in this order.
GOBO_UV_PARAMETERS = (
    "offset",
    "sloc",
    "tloc",
    "scale",
    "sscale",
    "tscale",
    "rotate",
    "srot",
    "wrap",
    "wrap_mode",
)

GOBO_FOCUS_PARAMETERS = ("cosine_power", "lens_radius")

# Image-shader UV — the gobo filter already exposes projection UV.
GOBO_MAP_HIDE = frozenset(
    {
        "sscale",
        "tscale",
        "soffset",
        "toffset",
        "sflip",
        "tflip",
        "swap_st",
        "swrap",
        "twrap",
        "uvset",
        "uvcoords",
        "start_channel",
        "single_channel",
        "sflip",
    }
)

GOBO_MAP_OFF = "off"
GOBO_MAP_FILE = "file"
GOBO_MAP_NOISE = "noise"
GOBO_MAP_CELL = "cell_noise"

GOBO_MAP_TYPES = (
    (GOBO_MAP_OFF, "Off"),
    (GOBO_MAP_FILE, "File"),
    (GOBO_MAP_NOISE, "Noise"),
    (GOBO_MAP_CELL, "Cell Noise"),
)

INTERNAL_LIGHT = "__light"
INTERNAL_GOBO = "__gobo"
INTERNAL_GOBO_GROUP = "__goboGroup"
INTERNAL_GOBO_IMAGE = "__goboImage"
INTERNAL_GOBO_NOISE = "__goboNoise"
INTERNAL_GOBO_CELL = "__goboCell"
GOBO_GROUP_NAME = "gobos"


def parameter_section(plug_name: str) -> str:
    """Which Node Editor tab a light parameter belongs on."""
    if plug_name in CONTRIBUTION_PARAMETERS:
        return "arnold"
    if plug_name in SHAPING_PARAMETERS:
        return "shaping"
    return "light"


def gaffer_light_type(shader_name: str) -> str:
    return LIGHT_SHADER_TO_GAFFER_TYPE.get(shader_name, GAFFER_ARNOLD_LIGHT)


def uses_mesh_light_node(shader_name: str) -> bool:
    return gaffer_light_type(shader_name) == GAFFER_ARNOLD_MESH_LIGHT
