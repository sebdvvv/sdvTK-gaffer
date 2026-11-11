"""sdvTk — Gaffer Node Editor / metadata for toolkit nodes."""

from sdvTkGaffer._compat import alias_package

from . import ArnoldLightUI  # noqa: F401
from . import ArnoldPhysicalSkyUI  # noqa: F401
from . import ShadingTkUI  # noqa: F401
from . import sdvRenderAttributesUI  # noqa: F401
from . import sdvRenderSettingsUI  # noqa: F401
from . import sdvUSDWriterUI  # noqa: F401

alias_package("ArnoldLightUI", "sdvTkGafferUI.ArnoldLightUI")
alias_package("ArnoldPhysicalSkyUI", "sdvTkGafferUI.ArnoldPhysicalSkyUI")
alias_package("ShadingTkUI", "sdvTkGafferUI.ShadingTkUI")
alias_package("sdvRenderAttributesUI", "sdvTkGafferUI.sdvRenderAttributesUI")
alias_package("sdvRenderSettingsUI", "sdvTkGafferUI.sdvRenderSettingsUI")
alias_package("sdvUSDWriterUI", "sdvTkGafferUI.sdvUSDWriterUI")
