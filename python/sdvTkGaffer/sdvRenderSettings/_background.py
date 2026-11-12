"""Background colour rig inside sdvRenderSettings.

One public colour drives the active engine's own background:

- Arnold: ``flat`` shader into Arnold Background (``ai:background``)
- RenderMan: ``PxrBackgroundDisplayFilter`` into a Display Filter (``ri:displayfilter``)
- Cycles: a background shader into Cycles Background (``cycles:background:shader``)

The other engines' nodes stay disabled.
"""

from __future__ import annotations

import Gaffer
import imath

from ._data import ENGINE_ARNOLD, ENGINE_CYCLES, ENGINE_ORDER, ENGINE_RENDERMAN

_COLOR = imath.Color3f(0.18, 0.18, 0.18)


def internal_background(engine: str) -> str:
    return "__{}Background".format(engine)


def internal_background_shader(engine: str) -> str:
    return "__{}BackgroundShader".format(engine)


def add_background_plugs(node: Gaffer.Node) -> None:
    if "background" not in node:
        enabled = Gaffer.BoolPlug("background", defaultValue=False)
        node.addChild(enabled)
        Gaffer.Metadata.registerValue(enabled, "nodule:type", "")
        Gaffer.Metadata.registerValue(enabled, "label", "Background")
        Gaffer.Metadata.registerValue(
            enabled,
            "description",
            "Authors a background colour for the active renderer. "
            "Arnold uses a flat background shader, RenderMan a "
            "PxrBackgroundDisplayFilter, and Cycles a background shader.",
        )
    if "backgroundColor" not in node:
        color = Gaffer.Color3fPlug("backgroundColor", defaultValue=_COLOR)
        node.addChild(color)
        Gaffer.Metadata.registerValue(color, "nodule:type", "")
        Gaffer.Metadata.registerValue(color, "label", "Background Color")
        Gaffer.Metadata.registerValue(
            color,
            "description",
            "Colour used by the active renderer's background. "
            "Background has to be on for this to be authored.",
        )


def ensure_background_rigs(node: Gaffer.Node) -> None:
    """Create each engine's background nodes once, and drive their colour."""
    for engine in ENGINE_ORDER:
        _ensure_engine(node, engine)


def sync_background(node: Gaffer.Node, engine: str) -> None:
    """Enable only the active engine's background, and only while Background is on."""
    use = False
    try:
        use = bool(node["background"].getValue())
    except Exception:
        use = False
    for item in ENGINE_ORDER:
        processor = node.getChild(internal_background(item))
        if processor is None or "enabled" not in processor:
            continue
        from ._box import set_plug_value

        set_plug_value(processor["enabled"], use and item == engine)


def _ensure_engine(node: Gaffer.Node, engine: str) -> None:
    from ._box import set_plug_value

    processor_name = internal_background(engine)
    processor = node.getChild(processor_name)
    shader = node.getChild(internal_background_shader(engine))
    if processor is None or shader is None:
        try:
            made = _make_engine(engine)
        except Exception:
            return
        if made is None:
            return
        shader, processor, color_plug, shader_input = made
        node.addChild(shader)
        node.addChild(processor)
        try:
            processor[shader_input].setInput(shader["out"])
        except Exception:
            node.removeChild(processor)
            node.removeChild(shader)
            return
        if "enabled" in processor:
            set_plug_value(processor["enabled"], False)
    else:
        color_plug = _color_plug(shader)
    if color_plug is None or "backgroundColor" not in node:
        return
    try:
        if color_plug.getInput() is None:
            color_plug.setInput(node["backgroundColor"])
    except Exception:
        pass


def _make_engine(engine: str):
    shader_name = internal_background_shader(engine)
    processor_name = internal_background(engine)
    if engine == ENGINE_ARNOLD:
        import GafferArnold

        shader = GafferArnold.ArnoldShader(shader_name)
        shader.loadShader("flat")
        processor = GafferArnold.ArnoldBackground(processor_name)
        return shader, processor, _color_plug(shader), "shader"
    if engine == ENGINE_RENDERMAN:
        import GafferRenderMan

        shader = GafferRenderMan.RenderManShader(shader_name)
        shader.loadShader("PxrBackgroundDisplayFilter")
        processor = GafferRenderMan.RenderManDisplayFilter(processor_name)
        return shader, processor, _color_plug(shader), "displayFilter"
    if engine == ENGINE_CYCLES:
        import GafferCycles

        shader = GafferCycles.CyclesShader(shader_name)
        _load_first(shader, ("background", "background_shader"))
        processor = GafferCycles.CyclesBackground(processor_name)
        return shader, processor, _color_plug(shader), "shader"
    return None


def _load_first(shader: Gaffer.Node, names: tuple) -> None:
    last = None
    for name in names:
        try:
            shader.loadShader(name)
            return
        except Exception as exc:
            last = exc
    if last is not None:
        raise last
    raise RuntimeError("No background shader to load")


def _color_plug(shader: Gaffer.Node):
    parameters = shader.getChild("parameters") if shader is not None else None
    if parameters is None:
        return None
    for name in ("backgroundColor", "color"):
        if name in parameters:
            return parameters[name]
    return None
