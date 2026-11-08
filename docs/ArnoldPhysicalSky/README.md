# ArnoldPhysicalSky

Single node providing all required elements for natural sky lighting. It adds one Arnold environment light into the scene.

**Help** on the node opens this page.

- **Physical Sky** (default) — `physical_sky` drives the skydome colour
- **HDRI** — an image shader drives colour
- **Color** — a plain skydome

**Create** authors a new env light. The prim is `physicalSky1` (or `skydome1` / `color1`). The graph node is `ArnoldPhysicalSky1`. An optional Label prefixes the prim (`key1_physicalSky`). Prim Path defaults to `/LIGHTS` (one group). Extra groups are created only when you add path levels (max 4).

**Edit** picks an existing skydome on `in`, loads its values, and authors this light at the same name and path. The graph node gets an `_edit` suffix. Prim Name, Label, and Prim Path follow that selection.

**Split Camera / Lighting** (when this Arnold build has `ray_switch`) locks Env Light Type and feeds camera rays and lighting rays from different sources. Dome intensity, exposure, and transform still apply to both. Turning Split off returns to Env Light Type. Each side can be Physical Sky, HDRI, or Color, with its own exposure and colour grade.

| Tab |  |
| --- | --- |
| **Light** | Env Light Type, then Label and Name side by side, then Enable Sun and Enable Sky. Split and the sky shader follow. |
| **Transform** | Place and rotate the dome. |
| **UV Transform** | Place an HDRI on the dome. With Split on, each side has its own UV on the Light tab. |
| **Prim Path** | Group path. Same rules as `ArnoldLight` (`/LIGHTS`, max 4 levels). |
| **Arnold** | Contribution and samples. |
| **Light Linking** | Which objects see this dome. |
| **Sampling** | Volume Samples, Sampling Mode, and Resolution. |
| **Viz** | GL Drawing Mode, then the light's viewer attributes. |

Copy / Paste / Reset on the card header copy the look onto another `ArnoldPhysicalSky`. They keep the destination name and path.
