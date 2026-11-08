# ShadingTk

ShadingTk is a single-node toolkit for using all Gaffer shading capabilities. It automates the usual material, shader, and texture tasks — assign looks, plug in maps, load presets, tweak an existing shader, override samples — without wiring a chain of stock nodes by hand.

**Help** on the node opens this page.

**Create** assigns new shaders, a MixShader, and textures.

**Edit** loads an existing surface shader. It does not replace or rename that shader.

| Tab | When |  |
| --- | --- | --- |
| **Globals** | Create | Scene-wide assignment, matte, and diagnostic shader. |
| **Shader Binding slots** | Create | **Add Shader slot**, then **Remove** on a slot. |
| **MixShader** | Create | Mix the slot shaders. |
| **Edit Shader** | Edit | Tweak one existing surface shader. The node creates an EditScope after the incoming assignment and writes parameter edits there. Pick a shader; parameters load in this tab. |
| **Edit Binding** | Edit | Copy an existing surface shader onto other prims. The shader is not duplicated. |
| **OSL slots** | Both | OSL slots, added like shader slots. Each slot is a section you can expand and collapse. Checkbox off: the text is an OSLCode shader body (no helper functions, no `#include`), compiled on edit and saved in the scene. Checkbox on: **Compile OSL** writes a temporary `.osl`, runs `oslc`, and puts the shader in **OSL Path folder**. **Connect output** plugs Color, Mask, or Displacement into a shader slot. **Drive Time** sets `Time = context.getFrame() / Framerate`. |
| **Compiled OSL shader** | Both | One tab per shader, named after it, once that slot has a shader. Pick prims to assign it with a ShaderAssignment. Color and Mask stay outputs you connect elsewhere. A Displacement output also assigns an Arnold displacement on those prims. **Edit** opens it in Shader Manager. |
| **Sampling** | Both | Renderer shading samples and optional shader-sample overrides. Off until you enable it. Uses **Render Engine** on the node (Arnold, Cycles, or RenderMan). |
| **Settings** | Both | In Create mode, naming (auto-name, prefix, suffix). **OSL Path folder** defaults to `~/gaffer/shaders` and is prepended to `OSL_SHADER_PATHS`. **Framerate** is the divisor used by Drive Time. |

**ShadingTk Manager** sits on the node, directly under **Render Engine**, above the tabs. It is one window with a **Shaders** tab and a **Textures** tab. Shaders are listed in the order they connect, ending at a texture or at the shader itself. Select a shader to edit its attributes, including the TXT button on RGB colours. Textures are listed first. **Edit** on a shader slot opens that shader on the Shaders tab. The **sdvTk** menu items **Shader Manager** and **Texture Manager** open the same window on the matching tab.

In Shader Manager, **Presets** loads or saves YAML looks. Built-in samples live in `presets/ShadingTk/`. Point **Preset Folder** at your own directory, or set `SHADINGTK_PRESET_PATH`.

Copy / Paste / Reset on the card header move values between ShadingTk nodes.

### OSL

Examples live in `osl/`: `noise_lib.h`, `psychedelic_iridescence.osl`, and `animated_displacement.osl`. The Examples menu loads those files (external compile) or an OSLCode body with the same noise inlined. Compile copies `noise_lib.h` into the OSL Path folder when that folder does not already have one. The default folder is `~/gaffer/shaders`.

A compiled shader is assigned onto the prims in its own tab. Color and Mask are not separate assignments: connect them into a shader slot (base color, emission, specular color, roughness, metalness). A Displacement output assigns an Arnold displacement of that shader on the same prims; the mesh needs subdivision. Those OSL shaders also show up in Shader Manager. Keep Time, Scale, Speed, and WarpAmount equal on the surface and displacement shaders so the bands stay on the ridges.

### Still to implement

- Automated UDIM setup/recognition/toggle
- Animated texture support
