# sdvTK-gaffer

This is an open-source contribution to [Gaffer](https://github.com/GafferHQ/gaffer), for anyone who wants a quick, production-shaped Arnold lighting workflow instead of wiring stock nodes by hand. It is designed around production-standard requirements, including a single node that provides every element needed for natural sky lighting.

<img width="1206" height="403" alt="gaffer_2026-11-07_12-24-30" src="https://github.com/user-attachments/assets/108f2ca8-53bc-4e8f-bb66-37128f4f2b62" />


`ShadingTk`, `sdvRenderSettings`, and `sdvRenderAttributes` support Arnold, RenderMan, and Cycles. 

| Node |  | Node menu |
| --- | --- | --- |
| `ArnoldLight` | One node for any Arnold light (area, spot, mesh, …) | **Arnold → ArnoldLight** |
| `ArnoldPhysicalSky` | Natural sky: physical sky, HDRI, or a flat colour dome | **Arnold → ArnoldPhysicalSky** |
| `ShadingTk` | Assign, mix, texture, and edit shaders | **Arnold → ShadingTk** |
| `sdvRenderSettings` | Renderer options | **Render → sdvRenderSettings** |
| `sdvRenderAttributes` | MeshType and renderer attribute sets | **Render → sdvRenderAttributes** |

Gaffer type names stay the same (`ArnoldLight.ArnoldLight`, and the same pattern for the others), so existing `.gfr` scripts keep loading.

Drop any of them on a scene connection. **In** is the top plug, **out** is the bottom. Disable the node and the scene passes through unchanged.

Tested on **Gaffer 1.7.5** and **Arnold 1.7.5.4**.

---

## Install

Set two variables to this repo.

Linux:

```bash
export PYTHONPATH="/path/to/sdvTK-gaffer/python:${PYTHONPATH}"
export GAFFER_STARTUP_PATHS="/path/to/sdvTK-gaffer/startup:${GAFFER_STARTUP_PATHS}"
```

Windows:

```bat
set PYTHONPATH=C:\path\to\sdvTK-gaffer\python;%PYTHONPATH%
set GAFFER_STARTUP_PATHS=C:\path\to\sdvTK-gaffer\startup;%GAFFER_STARTUP_PATHS%
```

Arnold Viewer settings set at startup to Shading, Lighting, and Textures to **Full**.

---

## Gaffer UI & interaction Mods

Middle-click closes a layout tab (Graph Editor, Viewer, and the other editors).

**sdvTk → Options** saves preferences in `~/gaffer/sdvtk_prefs.json`.

- **Double-click enters content nodes** — double-click a Box, Reference, or EditScope to open its contents.
- **Navigate node contents through a single pane** — that navigation stays in the current Graph Editor.
- **Ctrl + Double-click opens Node editor panels** — Ctrl+double-click opens a Node Editor for the node.
- **Graph View right-click menu has navigation** — the graph menu includes back (◀) and root (/).
- **Scene Hierarchy: browse without retriggering the Viewer** — expand and collapse in the Hierarchy View while the Viewer keeps its Visible Set.
- **Replace the Python Editor with [pw_MultiScriptEditor](https://github.com/sebdvvv/pw_MultiScriptEditor)** — set the folder that contains `multi_script_editor`. The next launch adds it to `PYTHONPATH` and docks that editor under the Graph Editor.

---

## ArnoldLight

A single Gaffer node wrapping any Arnold light type, with input and output ports. Drop it on a scene line, pick a type, set the look. Skydome, HDRI, and physical sky live on `ArnoldPhysicalSky`.

### Create and Edit

**Create** (default) authors a new light.

**Edit** picks an existing light from the incoming scene. The node loads its type, transform, and parameters and authors at the same name and path as that light. Prim Name, Label, and Prim Path are greyed — they follow the menu selection. The graph name gets an `_edit` suffix. Mesh Light keeps the mesh.

### Tabs

| Tab |  |
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

Mesh Light turns an existing mesh into a light.

1. Light Type → **Mesh Light**.
2. **Prim Path** appears on the Light tab (and on the Prim Path tab). Pick the mesh from the incoming scene, for example `/geo/lampShade`.
3. Set colour and exposure as usual.

Prim Path is the filter that chooses which prims emit. Type a path, pick from the scene browser, or put a Gaffer expression on Prim Path. Several meshes: separate paths with spaces.

In Edit mode, picking an existing mesh light fills Prim Path with that full location.

### Light types

Area (quad, the default), disk, cylinder, point, spot, distant, photometric, mesh.

---

## ArnoldPhysicalSky

Single node providing all required elements for natural sky lighting. It adds one Arnold environment light into the scene.

- **Physical Sky** (default) — `physical_sky` drives the skydome colour
- **HDRI** — an image shader drives colour
- **Color** — a plain skydome

**Create** authors a new env light. The prim is `physicalSky1` (or `skydome1` / `color1`). The graph node is `ArnoldPhysicalSky1`. An optional Label prefixes the prim (`key1_physicalSky`). Prim Path defaults to `/LIGHTS` (one group). Extra groups are created only when you add path levels (max 4).

**Edit** picks an existing skydome on `in`, loads its values, and authors this light at the same name and path. The graph node gets an `_edit` suffix. Prim Name, Label, and Prim Path follow that selection.

**Split Camera / Lighting** (when this Arnold build has `ray_switch`) locks Env Light Type and feeds camera rays and lighting rays from different sources. Dome intensity, exposure, and transform still apply to both. Turning Split off returns to Env Light Type. Each side can be Physical Sky, HDRI, or Color, with its own exposure and colour grade.

| Tab |  |
| --- | --- |
| **Light** | Env Light Type, Split, label, prim name, and the sky shader (sun, turbidity, HDRI file, colour, …). |
| **Transform** | Place and rotate the dome. |
| **UV Transform** | Place an HDRI on the dome. With Split on, each side has its own UV on the Light tab. |
| **Prim Path** | Group path. Same rules as `ArnoldLight` (`/LIGHTS`, max 4 levels). |
| **Arnold** | Contribution and samples. |
| **Light Linking** | Which objects see this dome. |
| **Viz** | Viewer drawing for the light. |

Copy / Paste / Reset on the card header copy the look onto another `ArnoldPhysicalSky`. They keep the destination name and path.

---

## ShadingTk

ShadingTk is a single-node toolkit for using all Gaffer shading capabilities. It automates the usual material, shader, and texture tasks — assign looks, plug in maps, load presets, tweak an existing shader, override samples — without wiring a chain of stock nodes by hand.

**Create** assigns new shaders, a MixShader, and textures.

**Edit** loads an existing surface shader. It does not replace or rename that shader.

| Tab | When |  |
| --- | --- | --- |
| **Main** | Create | Nested tabs: **Globals**, **Shader slots** (**Add Shader slot**, then **Remove** on a slot), and **MixShader**. |
| **Edit Shader** | Edit | Tweak one existing surface shader. The node creates an EditScope after the incoming assignment and writes parameter edits there. Pick a shader; parameters load in this tab. |
| **Edit Binding** | Edit | Copy an existing surface shader onto other prims. The shader is not duplicated. |
| **Sampling** | Both | Renderer shading samples and optional shader-sample overrides. Off until you enable it. Uses **Render Engine** on the node (Arnold, Cycles, or RenderMan). |
| **Settings** | Both | In Create mode, naming (auto-name, prefix, suffix). |

**ShadingTk Manager** sits on the node, directly under **Render Engine**, above the tabs. It is one window with a **Shaders** tab and a **Textures** tab. Shaders are listed in the order they connect, ending at a texture or at the shader itself. Select a shader to edit its attributes, including the TXT button on RGB colours. Textures are listed first. **Edit** on a shader slot opens that shader on the Shaders tab. The **sdvTk** menu items **Shader Manager** and **Texture Manager** open the same window on the matching tab.

In Shader Manager, **Presets** loads or saves YAML looks. Built-in samples live in `presets/ShadingTk/`. Point **Preset Folder** at your own directory, or set `SHADINGTK_PRESET_PATH`.

Copy / Paste / Reset on the card header move values between ShadingTk nodes.

### Still to implement

- Automated UDIM setup/recognition/toggle
- Animated texture support

---

## sdvRenderSettings

Renderer options. Tweak them globally on the renderer instead of wiring a stack of Options nodes. Arnold, RenderMan, and Cycles.

| Tab |  |
| --- | --- |
| **Standard Options** | Gaffer’s standard render options, including the default renderer. |
| **{Engine} Options** | Native `ArnoldOptions`, `RenderManOptions`, or `CyclesOptions`. Preset menu, Save, and Load. |

**Enable Subdivision** and **Enable Displacement** sit under **Renderer** and drive the matching viewport Arnold toggles.

### Presets

On the Options tab: **Preset**, **Save**, **Load**. YAML is read from:

1. This repo’s `presets/sdvRenderSettings/` folder
2. **Preset Folder** on the Options tab (optional)
3. `SDVRENDERSETTINGS_PRESET_PATH` (optional extra folders, `:` / `;` separated)

Shipped samples: Arnold Preview, Draft, and Production; RenderMan Draft and Production; Cycles Draft and Production.

Save writes `{Engine}_{Name}.yaml`. Load can pick any YAML file. Applying a preset for another engine switches the engine, then loads options.

Copy / Paste / Reset on the card header copies the engine and options onto another `sdvRenderSettings`. Reset restores option defaults and keeps the engine.

## sdvRenderAttributes

Primitive attributes for rendering, plus a MeshType at the front of the node. Arnold, RenderMan, and Cycles. Drop it after `sdvRenderSettings` when a look needs both.

**Enable Catmull-Clark Subdivision type** sits under **Renderer**. On sets that MeshType to Catmull-Clark for every mesh. Off leaves interpolation unchanged.

| Tab |  |
| --- | --- |
| **{Engine} Attributes** | List of attribute sets. **+** / **−** add or remove sets (0–8). |

Each set adds a tab named after it (default `ArnoldAttributesSet1`, and the same pattern for the other engines). That tab shows the native attributes plugs.

| Control |  |
| --- | --- |
| **Attribute Set** | Name of the set. Renames the tab. |
| **Prim Path** | Locations that receive these attributes. Scene picker. Gaffer expressions work. |
| **+ / −** | Extra prim-path fields. All paths for a set go into one PathFilter. |
| **Clear** | Reset name, paths, and attribute values for that set. |

Later sets override earlier ones where paths overlap.

Copy / Paste / Reset on the card header copies the engine, the Catmull-Clark toggle, and attribute sets onto another `sdvRenderAttributes`. Reset restores attribute defaults and keeps the engine.
