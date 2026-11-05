# sdvTK-gaffer

One Gaffer toolkit for lighting, shading, and render settings. Install this repo instead of five separate node packages.

Arnold is supported now. RenderMan and Cycles are supported on `sdvRenderSettings`.

| Node | What it is | Node menu |
| --- | --- | --- |
| `ArnoldLight` | One node to add an Arnold light (area, spot, mesh, …) | **Arnold → ArnoldLight** |
| `ArnoldPhysicalSky` | HDRI / physical sky / color env light | **Arnold → ArnoldPhysicalSky** |
| `ShadingTk` | Assign Arnold shaders (up to 8 slots) | **Arnold → ShadingTk** |
| `sdvRenderSettings` | Renderer options and attribute sets (Arnold / RenderMan / Cycles) | **Render → sdvRenderSettings** |

Gaffer type names stay the same (`ArnoldLight.ArnoldLight`, …), so existing `.gfr` scripts keep loading.

---

## Install

Set two variables to this repo (not the old per-node repos):

```bash
export PYTHONPATH="/path/to/sdvTK-gaffer/python:${PYTHONPATH}"
export GAFFER_STARTUP_PATHS="/path/to/sdvTK-gaffer/startup:${GAFFER_STARTUP_PATHS}"
```

Windows: use `;` instead of `:`. Farm / `gaffer execute` needs the same variables.

Restart Gaffer. You should see the four nodes in the menus above.

If you still have the old `arnoldLight-gaffer`, `shadingTk-gaffer`, … paths on `PYTHONPATH` / `GAFFER_STARTUP_PATHS`, remove them so only this toolkit is loaded.

---

## Layout

```
python/sdvTkGaffer/      node implementations
python/sdvTkGafferUI/    Node Editor cards and metadata
startup/gui/sdvTk.py     one startup file registers every node
presets/ShadingTk/
presets/sdvRenderSettings/
icons/
```

---

## Nodes

Drop any of them on a scene connection. **In** top, **out** bottom. Disable = passthrough.

**ArnoldLight** — Create / Edit, named hierarchy under Prim Path (default `/LIGHTS`), mesh lights, spot gobos.

**ArnoldPhysicalSky** — HDRI, physical sky, or color environment.

**ShadingTk** — Create slots, MixShader, textures, sampling; Edit assigns or tweaks existing shaders.

**sdvRenderSettings** — Engine options plus up to eight attribute sets. YAML presets live in `presets/sdvRenderSettings/`. Shader presets live in `presets/ShadingTk/`.

Tested on **Gaffer 1.7.5**.
