# sdvUSDWriter

Writes the scene to USD renderable stage.
Includes UsdRender settings, products,, vars, lights and primvars translated from Gaffer's render globals.




<img width="573" height="395" alt="gaffer_2026-11-11_21-39-19" src="https://github.com/user-attachments/assets/e0338a43-1da1-48b2-9e3f-b4942648cc45" />


<img width="573" height=auto alt="gaffer_2026-11-11_21-40-53" src="https://github.com/user-attachments/assets/7dadcaf9-12f3-43c4-9c5a-13a72e16846d" />

**Render → sdvUSDWriter.** One scene input. **Frames** is Current Frame, Full Range (the script timeline), or Custom Range. **Write USD** dispatches the scene write for those frames. **USD Write All** writes that scene and then authors the render settings, products, and vars. A LocalDispatcher in the graph is not required. Evaluating the scene does not write the file. **out** passes the scene through and stays hidden.

**Extension** is a menu of `.usd`, `.usda`, `.usdc`, and `.usdz`. Changing it rewrites the extension on **File Name**. `.usdz` is packaged from a crate layer.

**Renderer** is the first control: Arnold, RenderMan, or Cycles. Only that engine's options are written. Arnold `ai:` options are stored as `arnold:` so Arnold USD can read them. RenderMan stays `ri:` and Cycles stays `cycles:`. Standard render globals are included for every engine.

**Camera** sets the renderable camera on the RenderSettings prim. Leave it empty to use `render:camera` from the scene.

## What gets authored

| Prim | Default path | Source |
| --- | --- | --- |
| Scope | `/Render` | Always created |
| RenderSettings | `/Render/Settings` | Standard options in the scene globals |
| Scope | `/Render/Products` | Always created. One RenderProduct per output file when outputs exist |
| Scope | `/Render/Vars` | Always created. One RenderVar per AOV when outputs exist |

`renderSettingsPrimPath` on the stage points at the settings prim. **Render Root** and **Settings Name** change the settings path. Products and Vars stay next to it.

**File Outputs Only** skips `ieDisplay` outputs. Turn it off to write those too.

Settings come from the first frame in the file. If an output's expanded file name changes across the range, `productName` is time-sampled on the same time base as the scene.

## Settings

| Gaffer global | USD |
| --- | --- |
| **Camera** on this node, or else `render:camera` | `camera` relationship |
| `render:shutter` | `shutterOpen` / `shutterClose` on that camera |
| `render:resolution` × `render:resolutionMultiplier` | `resolution` |
| `render:pixelAspectRatio` | `pixelAspectRatio` |
| `render:filmFit` | `aspectRatioConformPolicy` |
| `render:cropWindow` and overscan | `dataWindowNDC` |
| `render:depthOfField` | `disableDepthOfField` |
| `sampleMotion`, transform blur, deformation blur | `disableMotionBlur` |
| `render:includedPurposes` | `includedPurposes` |
| `ai:background` (Arnold) | That shader network on `/mtl/background/nodeGraph`, linked from `arnold:global:background`. Wins over `render:backgroundColor` |
| `render:backgroundColor` (Arnold) | `arnold:flat` on that same graph when `ai:background` is not set |
| `ri:displayfilter` (RenderMan) | That shader network on `/mtl/displayfilter/nodeGraph`, linked from `ri:displayfilter` |
| `cycles:background:shader` (Cycles) | That shader network on `/mtl/cyclesBackground/nodeGraph`, linked from `cycles:background:shader` |
| selected engine's options (`ai:` → `arnold:`, `ri:`, `cycles:`) | attributes on the settings prim |

Film fit:

| Gaffer | USD |
| --- | --- |
| Horizontal | `adjustApertureHeight` |
| Vertical | `adjustApertureWidth` |
| Fit | `expandAperture` |
| Fill | `cropAperture` |
| Distort | `adjustPixelAspectRatio` |

Crop is top-left in Gaffer and bottom-left in USD, so the Y axis is flipped. Overscan is extra data window outside 0–1. It is not baked into `resolution`.

An option is written only when it is enabled in the globals. `render:inclusions` is stored as a string and does not prune the scene.

## AOVs

Outputs that share a file name become one RenderProduct. The data string on the output becomes the RenderVar:

| Output data | dataType | sourceName | sourceType |
| --- | --- | --- | --- |
| `rgba` | `color4f` | `rgba` | `raw` |
| `color diffuse` | `color3f` | `diffuse` | `raw` |
| `float Z` | `float` | `Z` | `raw` |
| `lpe C.*` | `color3f` | `C.*` | `lpe` |

The original data string and output parameters (layer name, filter, quantize) are kept as `gaffer:*` attributes on the var. The driver (`exr`, `deepexr`, …) is `gaffer:driver` on the product. `deepexr` sets `productType` to `deepRaster`.
