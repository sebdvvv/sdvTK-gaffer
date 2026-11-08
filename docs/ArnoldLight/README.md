# ArnoldLight

A single Gaffer node wrapping any Arnold light type, with input and output ports. Drop it on a scene line, pick a type, set the look. Skydome, HDRI, and physical sky live on `ArnoldPhysicalSky`.

**Help** on the node opens this page.

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
