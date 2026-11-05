"""Renderer shading-sample option names and ShaderTweaks helpers."""

from __future__ import annotations

ENGINE_ARNOLD = "arnold"
ENGINE_RENDERMAN = "renderman"
ENGINE_CYCLES = "cycles"

ENGINE_ORDER = (ENGINE_ARNOLD, ENGINE_RENDERMAN, ENGINE_CYCLES)

ENGINE_LABELS = {
    ENGINE_ARNOLD: "Arnold",
    ENGINE_RENDERMAN: "RenderMan",
    ENGINE_CYCLES: "Cycles",
}

SAMPLING_ARNOLD_OPTIONS = "__samplingArnoldOptions"
SAMPLING_CYCLES_OPTIONS = "__samplingCyclesOptions"
SAMPLING_RENDERMAN_OPTIONS = "__samplingRenderManOptions"
SAMPLING_TWEAKS = "__samplingTweaks"
SAMPLING_TWEAKS_FILTER = "__samplingTweaksFilter"
SAMPLING_LIGHT_TWEAKS = "__samplingLightTweaks"
SAMPLING_EDIT_TWEAKS = "__samplingEditTweaks"
SAMPLING_EDIT_FILTER = "__samplingEditFilter"

ENGINE_OPTIONS_NODE = {
    ENGINE_ARNOLD: SAMPLING_ARNOLD_OPTIONS,
    ENGINE_CYCLES: SAMPLING_CYCLES_OPTIONS,
    ENGINE_RENDERMAN: SAMPLING_RENDERMAN_OPTIONS,
}

ENGINE_SURFACE_ATTR = {
    ENGINE_ARNOLD: "ai:surface",
    ENGINE_CYCLES: "cycles:surface",
    ENGINE_RENDERMAN: "ri:surface",
}

SAMPLE_OPTION_KEYS = {
    ENGINE_ARNOLD: (
        "ai:AA_samples",
        "ai:GI_diffuse_samples",
        "ai:GI_specular_samples",
        "ai:GI_transmission_samples",
        "ai:GI_sss_samples",
        "ai:GI_volume_samples",
        "ai:light_samples",
        "ai:enable_adaptive_sampling",
        "ai:AA_samples_max",
        "ai:AA_adaptive_threshold",
    ),
    ENGINE_CYCLES: (
        "cycles:session:samples",
        "cycles:integrator:use_adaptive_sampling",
        "cycles:integrator:adaptive_threshold",
        "cycles:integrator:adaptive_min_samples",
        "cycles:integrator:light_sampling_threshold",
        "cycles:integrator:sample_clamp_direct",
        "cycles:integrator:sample_clamp_indirect",
    ),
    ENGINE_RENDERMAN: (
        "ri:hider:maxsamples",
        "ri:hider:minsamples",
        "ri:Ri:PixelVariance",
        "ri:hider:adaptivemetric",
    ),
}

SAMPLE_TWEAK_NAMES = (
    "samples",
    "sss_samples",
    "volume_samples",
    "diffuse_samples",
    "specular_samples",
    "transmission_samples",
    "light_samples",
)


def engine_available(engine: str) -> bool:
    modules = {
        ENGINE_ARNOLD: "GafferArnold",
        ENGINE_RENDERMAN: "GafferRenderMan",
        ENGINE_CYCLES: "GafferCycles",
    }
    module = modules.get(engine)
    if not module:
        return False
    try:
        __import__(module)
        return True
    except Exception:
        return False


def available_engines() -> tuple[str, ...]:
    found = tuple(engine for engine in ENGINE_ORDER if engine_available(engine))
    return found or (ENGINE_ARNOLD,)


def default_engine() -> str:
    for engine in ENGINE_ORDER:
        if engine_available(engine):
            return engine
    return ENGINE_ARNOLD


def engine_label(engine: str) -> str:
    return ENGINE_LABELS.get(engine, engine or "Arnold")


def make_options_node(engine: str, name: str):
    try:
        if engine == ENGINE_ARNOLD:
            import GafferArnold

            return GafferArnold.ArnoldOptions(name)
        if engine == ENGINE_RENDERMAN:
            import GafferRenderMan

            return GafferRenderMan.RenderManOptions(name)
        if engine == ENGINE_CYCLES:
            import GafferCycles

            return GafferCycles.CyclesOptions(name)
    except Exception:
        return None
    return None


def import_engine_ui(engine: str) -> None:
    try:
        if engine == ENGINE_ARNOLD:
            import GafferArnoldUI  # noqa: F401
        elif engine == ENGINE_RENDERMAN:
            import GafferRenderManUI  # noqa: F401
        elif engine == ENGINE_CYCLES:
            import GafferCyclesUI  # noqa: F401
    except Exception:
        pass


def is_sample_param(name: str) -> bool:
    text = (name or "").strip()
    if not text:
        return False
    if text in SAMPLE_TWEAK_NAMES:
        return True
    lower = text.lower()
    return "sample" in lower


def sample_param_names(shader) -> list[str]:
    if shader is None:
        return []
    params = getattr(shader, "parameters", None)
    if params is None:
        return []
    try:
        keys = list(params.keys())
    except Exception:
        return []
    return [str(key) for key in keys if is_sample_param(str(key))]


def persist_sampling_node(child) -> bool:
    try:
        name = child.getName()
    except Exception:
        return False
    return name.startswith("__sampling")
