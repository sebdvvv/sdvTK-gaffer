"""sdvTk — Gaffer lighting / shading / render toolkit nodes."""

from ._compat import alias_package
from .ArnoldLight import ArnoldLight
from .ArnoldPhysicalSky import ArnoldPhysicalSky
from .ShadingTk import ShadingTk
from .sdvRenderSettings import sdvRenderSettings

alias_package("ArnoldLight", "sdvTkGaffer.ArnoldLight")
alias_package("ArnoldPhysicalSky", "sdvTkGaffer.ArnoldPhysicalSky")
alias_package("ShadingTk", "sdvTkGaffer.ShadingTk")
alias_package("sdvRenderSettings", "sdvTkGaffer.sdvRenderSettings")

__all__ = [
    "ArnoldLight",
    "ArnoldPhysicalSky",
    "ShadingTk",
    "sdvRenderSettings",
]
