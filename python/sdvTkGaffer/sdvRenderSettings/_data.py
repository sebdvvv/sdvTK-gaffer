"""Engine ids, slot limits, and internal node / plug names."""

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

MAX_SLOTS = 8
MAX_PATHS = 8


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
    if found:
        return found
    return (ENGINE_CYCLES,)


def default_engine() -> str:
    """Arnold if present, else RenderMan, else Cycles (fail-safe)."""
    if engine_available(ENGINE_ARNOLD):
        return ENGINE_ARNOLD
    if engine_available(ENGINE_RENDERMAN):
        return ENGINE_RENDERMAN
    return ENGINE_CYCLES


def engine_label(engine: str) -> str:
    return ENGINE_LABELS.get(engine, engine or "Cycles")


def default_set_name(engine: str, index: int) -> str:
    return "{}AttributesSet{}".format(engine_label(engine).replace(" ", ""), index)


def set_name_plug(index: int) -> str:
    return "setName{}".format(index)


def path_count_plug(index: int) -> str:
    return "pathCount{}".format(index)


def path_plug(slot: int, path_index: int) -> str:
    return "path{}_{}".format(slot, path_index)


INTERNAL_STANDARD_OPTIONS = "__standardOptions"


def internal_options(engine: str) -> str:
    return "__{}Options".format(engine)


def internal_attributes(engine: str, index: int) -> str:
    return "__{}Attributes{}".format(engine, index)


def internal_filter(index: int) -> str:
    return "__pathFilter{}".format(index)


def internal_switch(index: int) -> str:
    return "__slotSwitch{}".format(index)


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


def make_attributes_node(engine: str, name: str):
    try:
        if engine == ENGINE_ARNOLD:
            import GafferArnold

            return GafferArnold.ArnoldAttributes(name)
        if engine == ENGINE_RENDERMAN:
            import GafferRenderMan

            return GafferRenderMan.RenderManAttributes(name)
        if engine == ENGINE_CYCLES:
            import GafferCycles

            return GafferCycles.CyclesAttributes(name)
    except Exception:
        return None
    return None


def import_engine_ui(engine: str) -> None:
    """Load renderer UI metadata so PlugLayout gets native sections."""
    try:
        if engine == ENGINE_ARNOLD:
            import GafferArnoldUI  # noqa: F401
        elif engine == ENGINE_RENDERMAN:
            import GafferRenderManUI  # noqa: F401
        elif engine == ENGINE_CYCLES:
            import GafferCyclesUI  # noqa: F401
    except Exception:
        pass
