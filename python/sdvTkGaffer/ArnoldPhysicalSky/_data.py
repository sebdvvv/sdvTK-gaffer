"""Arnold environment / sky types and Node Editor parameter filters."""

from __future__ import annotations

SKYDOME_LIGHT = "skydome_light"
PHYSICAL_SKY_SHADER = "physical_sky"
IMAGE_SHADER = "image"
RAY_SWITCH_SHADER = "ray_switch"
COLOR_CORRECT_SHADER = "color_correct"
SPLIT_CAMERA = "camera"
SPLIT_LIGHTING = "lighting"
INTERNAL_RAY_SWITCH = "__shader_ray_switch"

# Node default is Physical Sky. One skydome_light; Sky Type is exclusive
# and reconnects ``color`` (HDRI / Physical Sky shader, or a plain colour).
ARNOLD_SKY_TYPES = (
    ("skydome", "HDRI"),
    ("physical_sky", "Physical Sky"),
    ("color", "Color"),
)

# skyType → (Arnold shader name, internal shader node name)
ARNOLD_SKY_SHADERS = {
    "skydome": (IMAGE_SHADER, "__shader_image"),
    "physical_sky": (PHYSICAL_SKY_SHADER, "__shader_physical_sky"),
}


def side_shader_child(side: str, sky_type: str) -> str | None:
    """Internal shader for one split side.

    Camera reuses the unsplit shader, so those edits remain when Split
    is turned off. Lighting has its own copy.
    """
    spec = ARNOLD_SKY_SHADERS.get(sky_type)
    if not spec:
        return None
    if side == SPLIT_LIGHTING:
        return spec[1] + "_lighting"
    return spec[1]


def side_grade_child(side: str) -> str:
    return "__shader_grade_{}".format(side)

ARNOLD_SKY_DRIVEN_PARAMETERS = {
    "skydome": frozenset({"color"}),
    "physical_sky": frozenset({"color"}),
    "color": frozenset(),
}

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

# Arnold image-shader UV Coordinates — place the HDRI on the dome.
UV_PARAMETERS = frozenset(
    {
        "uvcoords",
        "uvset",
        "soffset",
        "toffset",
        "swrap",
        "twrap",
        "sscale",
        "tscale",
        "sflip",
        "tflip",
        "swap_st",
    }
)
