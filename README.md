# sdvTK-gaffer

Lighting and shading helpers for [Gaffer](https://www.gafferhq.org/) + Arnold. Personal open-source contributions for a quicker production-shaped Arnold lighting workflow. Each piece is its own repo so you can install only what you need.

Arnold is supported now. RenderMan is planned.

| Repo | What it is |
| --- | --- |
| [arnoldLight-gaffer](https://github.com/sebdvvv/arnoldLight-gaffer) | `ArnoldLight` — one node to add an Arnold light (area, spot, mesh, …) |
| [arnoldPhysicalSky-gaffer](https://github.com/sebdvvv/arnoldPhysicalSky-gaffer) | `ArnoldPhysicalSky` — HDRI / physical sky / color env light |
| [shadingTk-gaffer](https://github.com/sebdvvv/shadingTk-gaffer) | `ShadingTk` — assign Arnold shaders (up to 8 slots) |
| [lightsConfig-gaffer](https://github.com/sebdvvv/lightsConfig-gaffer) | Light and AOV setup |
| [arnoldConfig-gaffer](https://github.com/sebdvvv/arnoldConfig-gaffer) | Arnold renderer config |

Install each repo on its own (`PYTHONPATH` + `GAFFER_STARTUP_PATHS`). See that repo’s README for details.
