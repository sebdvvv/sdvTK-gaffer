"""sdvTk — Gaffer lighting / shading / render toolkit nodes."""

from ._compat import alias_package
from .ArnoldLight import ArnoldLight
from .ArnoldPhysicalSky import ArnoldPhysicalSky
from .ShadingTk import ShadingTk
from .sdvRenderAttributes import sdvRenderAttributes
from .sdvRenderSettings import sdvRenderSettings
from .sdvUSDWriter import sdvUSDWriter

alias_package("ArnoldLight", "sdvTkGaffer.ArnoldLight")
alias_package("ArnoldPhysicalSky", "sdvTkGaffer.ArnoldPhysicalSky")
alias_package("ShadingTk", "sdvTkGaffer.ShadingTk")
alias_package("sdvRenderAttributes", "sdvTkGaffer.sdvRenderAttributes")
alias_package("sdvRenderSettings", "sdvTkGaffer.sdvRenderSettings")
alias_package("sdvUSDWriter", "sdvTkGaffer.sdvUSDWriter")

__all__ = [
    "ArnoldLight",
    "ArnoldPhysicalSky",
    "ShadingTk",
    "sdvRenderAttributes",
    "sdvRenderSettings",
    "sdvUSDWriter",
]
