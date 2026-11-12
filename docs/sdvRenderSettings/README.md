# sdvRenderSettings

Renderer options. Tweak them globally on the renderer instead of wiring a stack of Options nodes. Arnold, RenderMan, and Cycles.

**Help** on the node opens this page.

| Tab |  |
| --- | --- |
| **Standard Options** | Gaffer’s standard render options, including the default renderer. |
| **{Engine} Options** | Native `ArnoldOptions`, `RenderManOptions`, or `CyclesOptions`. Preset menu, Save, and Load. |

**Enable Subdivision** and **Enable Displacement** sit under **Renderer** and drive the matching viewport Arnold toggles.

**Background** and **Background Color** sit under those toggles. Turn Background on to author that colour for the active renderer. Arnold gets a `flat` shader on Arnold Background, RenderMan a `PxrBackgroundDisplayFilter` on a Display Filter, and Cycles a background shader on Cycles Background. Switching renderer enables only that engine's nodes.

### Presets

On the Options tab: **Preset**, **Save**, **Load**. YAML is read from:

1. This repo’s `presets/sdvRenderSettings/` folder
2. **Preset Folder** on the Options tab (optional)
3. `SDVRENDERSETTINGS_PRESET_PATH` (optional extra folders, `:` / `;` separated)

Shipped samples: Arnold Preview, Draft, and Production; RenderMan Draft and Production; Cycles Draft and Production.

Save writes `{Engine}_{Name}.yaml`. Load can pick any YAML file. Applying a preset for another engine switches the engine, then loads options.

Copy / Paste / Reset on the card header copies the engine and options onto another `sdvRenderSettings`. Reset restores option defaults and keeps the engine.
