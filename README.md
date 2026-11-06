# sdvTK-gaffer

This is an open-source contribution to [Gaffer](https://github.com/GafferHQ/gaffer), for anyone who wants a quick, production-shaped Arnold lighting workflow instead of wiring stock nodes by hand. It is designed around production-standard requirements, including a single node that provides every element needed for natural sky lighting.

One toolkit for lighting, shading, and render settings. 

<img width="856" height="333" alt="gaffer_2026-11-05_22-15-37" src="https://github.com/user-attachments/assets/1eb7f2e6-bf20-454e-b743-1b78dc23c4e7" />

`ShadingTk` and `sdvRenderSettings` support Arnold, RenderMan, and Cycles. 

| Node | What it is | Node menu |
| --- | --- | --- |
| `ArnoldLight` | One node for any Arnold light (area, spot, mesh, …) | **Arnold → ArnoldLight** |
| `ArnoldPhysicalSky` | Natural sky: physical sky, HDRI, or a flat colour dome | **Arnold → ArnoldPhysicalSky** |
| `ShadingTk` | Assign, mix, texture, and edit shaders | **Arnold → ShadingTk** |
| `sdvRenderSettings` | Renderer options and attribute sets | **Render → sdvRenderSettings** |

Gaffer type names stay the same (`ArnoldLight.ArnoldLight`, and the same pattern for the others), so existing `.gfr` scripts keep loading.

Drop any of them on a scene connection. **In** is the top plug, **out** is the bottom. Disable the node and the scene passes through unchanged.

Tested on **Gaffer 1.7.5** and **Arnold 1.7.5.4**.

---

## Install

Set two variables to this repo:

```bash
export PYTHONPATH="/path/to/sdvTK-gaffer/python:${PYTHONPATH}"
export GAFFER_STARTUP_PATHS="/path/to/sdvTK-gaffer/startup:${GAFFER_STARTUP_PATHS}"
```

Windows: use `;` instead of `:`. Farm / `gaffer execute` needs the same variables.

Restart Gaffer. The four nodes appear in the menus above.



```
python/sdvTkGaffer/      node implementations
python/sdvTkGafferUI/    Node Editor cards
startup/gui/sdvTk.py     registers every node
presets/ShadingTk/
presets/sdvRenderSettings/
icons/
```

---

## ArnoldLight

A single Gaffer node wrapping any Arnold light type, with input and output ports. Drop it on a scene line, pick a type, set the look. This is not Gaffer’s stock `ArnoldLight`. Skydome, HDRI, and physical sky live on `ArnoldPhysicalSky`.

Select the node. The Node Editor shows a card: **Mode**, then tabs. Copy / Paste / Reset sit on the card header. They copy the look (type, transform, GL drawing, shader values). They do not overwrite the destination name or path.

### Create and Edit

**Create** (default) authors a new light.

**Edit** picks an existing light from the incoming scene. The node loads its type, transform, and parameters and authors at the same name and path as that light. Prim Name, Label, and Prim Path are greyed — they follow the menu selection. The graph name gets an `_edit` suffix. Mesh Light does not prune the mesh.

### Tabs

| Tab | What it is |
| --- | --- |
| **Light** | Type, name, viewer drawing, and the everyday look (colour, exposure, …). Fields change with the type. |
| **Shaping** | Beam and shape controls that exist on the current type (cone, penumbra, spread, roundness, …). |
| **Gobo/Masking** | Spot Light only. **Gobo Map** is Off, File, Noise, or Cell Noise. Projection UV and the gobo filter sit on this tab. Other types show a note and nothing else. |
| **Transform** | Place and rotate the light. Hidden for Mesh Light. |
| **Prim Path** | Where the light sits in the hierarchy. |
| **Arnold** | Contribution and samples (camera, diffuse, specular, …) so the Light tab stays short. |

**GL Drawing** is viewer-only: follow the Viewer Drawing menu, or force Off / Wireframe / Colour / Texture on this light.

### Names

Label, type, prim name, and the graph node stay in sync.

| What you set | What you get |
| --- | --- |
| **Label** | Your name for the light (`key`, `sun`, `bounce`). |
| **Light Type** | Suffix on the prim: `areaLight`, `diskLight`, `spotLight`, … (no underscores). |
| **Prim Name** | Built for you: `{label}{number}_{type}` → `key1_areaLight`. The number bumps if the name is already used. |
| **Graph node** | `ArnoldLight_` + Prim Name → `ArnoldLight_key1_areaLight`. Edit mode adds `_edit`. |
| **Prim Path** | Parent groups, created only when this field has a path. Default is `/LIGHTS` (one group). `/apath` and `/apath/` are one group. Max **4** levels: `/LGT/natural` creates `LGT`, then `natural`, then the light. Clear the field and the light sits at the scene root. |

Change Label or Type and the prim name and graph node name follow. An empty Label is allowed; the prim is then `areaLight1`, `spotLight1`, …

### Mesh Light

Mesh Light does not create a new light prim. It turns an existing mesh into a light.

1. Light Type → **Mesh Light**.
2. **Prim Path** appears on the Light tab (and on the Prim Path tab). Pick the mesh from the incoming scene, for example `/geo/lampShade`.
3. Set colour and exposure as usual.

Prim Path is the filter that chooses which prims emit. Type a path, pick from the scene browser, or put a Gaffer expression on Prim Path. Several meshes: separate paths with spaces.

In Edit mode, picking an existing mesh light fills Prim Path with that full location. The mesh is not deleted. Transform, Label, and Prim Name hide — that is expected for this type.

### Light types

Area (quad, the default), disk, cylinder, point, spot, distant, photometric, mesh.

Still outside this node: barndoors, blockers, decay filters, and light linking. Light linking for a sky dome is on `ArnoldPhysicalSky`.

---

## ArnoldPhysicalSky

A single node providing all required elements for natural sky lighting. It adds one Arnold environment light into the scene.

- **Physical Sky** (default) — `physical_sky` drives the skydome colour
- **HDRI** — an image shader drives colour
- **Color** — a plain skydome

**Create** authors a new env light. The prim is `physicalSky1` (or `skydome1` / `color1`). The graph node is `ArnoldPhysicalSky1`. An optional Label prefixes the prim (`key1_physicalSky`). Prim Path defaults to `/LIGHTS` (one group). Extra groups are created only when you add path levels (max 4).

**Edit** picks an existing skydome on `in`, loads its values, and authors this light at the same name and path. The graph node gets an `_edit` suffix. Prim Name, Label, and Prim Path follow that selection.

**Split Camera / Lighting** (when this Arnold build has `ray_switch`) locks Env Light Type and feeds camera rays and lighting rays from different sources. Dome intensity, exposure, and transform still apply to both. Turning Split off returns to Env Light Type. Each side can be Physical Sky, HDRI, or Color, with its own exposure and colour grade.

| Tab | What it is |
| --- | --- |
| **Light** | Env Light Type, Split, label, prim name, and the sky shader (sun, turbidity, HDRI file, colour, …). |
| **Transform** | Place and rotate the dome. |
| **UV Transform** | Place an HDRI on the dome. With Split on, each side has its own UV on the Light tab. |
| **Prim Path** | Group path. Same rules as `ArnoldLight` (`/LIGHTS`, max 4 levels). |
| **Arnold** | Contribution and samples. |
| **Light Linking** | Which objects see this dome. |
| **Viz** | Viewer drawing for the light. |

Copy / Paste / Reset on the card header copy the look onto another `ArnoldPhysicalSky`. They keep the destination name and path.

Regular lights (area, spot, mesh, …) are `ArnoldLight`.

---

## ShadingTk

ShadingTk is a single-node toolkit for using all Gaffer shading capabilities. It automates the usual material, shader, and texture tasks — assign looks, plug in maps, load presets, tweak an existing shader, override samples — without wiring a chain of stock nodes by hand.

Needs Gaffer with Arnold, RenderMan, or Cycles. It starts empty. Add shader slots when you need them (up to eight). Each slot is a shader type, a shader name, and the prims it lands on. The shader list follows **Render Engine** in Settings.

**Create** assigns new shaders, a MixShader, and textures.

**Edit** loads an existing surface shader. It does not replace or rename that shader.

| Tab | When | What it is |
| --- | --- | --- |
| **Main** | Create | Nested tabs: **Globals**, **Shader slots** (**Add Shader slot**, then **Remove** on a slot), and **MixShader**. |
| **Shaders** | Create | One material tab per slot — attributes, and a shared tab for values applied across slots. |
| **Textures** | Create | Maps for the slots (image, noise, triplanar, and the other texture shaders for the current engine). |
| **Edit Shader** | Edit | Tweak one existing surface shader. The node creates an EditScope after the incoming assignment and writes parameter edits there. Pick a shader; parameters load in this tab. |
| **Edit Binding** | Edit | Copy an existing surface shader onto other prims. The shader is not duplicated. |
| **Sampling** | Both | Renderer shading samples and optional shader-sample overrides. Off until you enable it. Uses **Render Engine** from Settings (Arnold, Cycles, or RenderMan). |
| **Settings** | Both | **Render Engine**. In Create mode, also naming (auto-name, prefix, suffix). |

On a material tab, **Presets** loads or saves YAML looks. Built-in samples live in `presets/ShadingTk/`. Point **Preset Folder** at your own directory, or set `SHADINGTK_PRESET_PATH`.

Copy / Paste / Reset on the card header move values between ShadingTk nodes.

---

## sdvRenderSettings

A single node for render settings and primitive attributes related to rendering. Tweak them globally on the renderer, or locally on prims, instead of wiring a stack of Options and Attributes nodes. One node covers Arnold, RenderMan, and Cycles.

**Renderer** is always visible. A new node defaults to Arnold when Arnold is installed, otherwise RenderMan, otherwise Cycles. A node already saved in a scene keeps its stored engine. Switching engine disables every internal Options and Attributes node that is not for that engine, so unused renderers do not run.

| Tab | What it is |
| --- | --- |
| **Standard Options** | Gaffer’s standard render options, including the default renderer. |
| **{Engine} Options** | Native `ArnoldOptions`, `RenderManOptions`, or `CyclesOptions`. Preset menu, Save, and Load. |
| **{Engine} Attributes** | List of attribute sets. **+** / **−** add or remove sets (0–8). |

Each set adds a tab named after it (default `ArnoldAttributesSet1`, and the same pattern for the other engines). That tab shows the native attributes plugs.

| Control | What it does |
| --- | --- |
| **Attribute Set** | Name of the set. Renames the tab. |
| **Prim Path** | Locations that receive these attributes. Scene picker. Gaffer expressions work. |
| **+ / −** | Extra prim-path fields. All paths for a set go into one PathFilter. |
| **Clear** | Reset name, paths, and attribute values for that set. |

Later sets override earlier ones where paths overlap.

### Presets

On the Options tab: **Preset**, **Save**, **Load**. YAML is read from:

1. This repo’s `presets/sdvRenderSettings/` folder
2. **Preset Folder** on the Options tab (optional)
3. `SDVRENDERSETTINGS_PRESET_PATH` (optional extra folders, `:` / `;` separated)

Shipped samples: Arnold Preview, Draft, and Production; RenderMan Draft and Production; Cycles Draft and Production.

Save writes `{Engine}_{Name}.yaml`. Load can pick any YAML file. Applying a preset for another engine switches the engine, then loads options and any attribute sets stored in the file.

Copy / Paste / Reset on the card header copies the engine, options, and attribute sets onto another `sdvRenderSettings`. Reset restores option and attribute defaults and keeps the engine.
