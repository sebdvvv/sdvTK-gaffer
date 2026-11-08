# sdvRenderAttributes

Primitive attributes for rendering, plus a MeshType at the front of the node. Arnold, RenderMan, and Cycles. Drop it after `sdvRenderSettings` when a look needs both.

**Help** on the node opens this page.

**Enable Catmull-Clark Subdivision type** sits under **Renderer**. On sets that MeshType to Catmull-Clark for every mesh. Off leaves interpolation unchanged.

| Tab |  |
| --- | --- |
| **Main** | Renderer, the Catmull-Clark toggle, and the list of attribute sets. |
| **{set name}** | Native attributes for that set. The tab title is the Attribute Set name. |

**Add {Renderer}Attributes Set** adds a set (max 8). The label follows the renderer, for example **Add ArnoldAttributes Set**. Each set has its own **Remove** button. **Clear** resets that set’s name, paths, and values without deleting it.

| Control |  |
| --- | --- |
| **Attribute Set** | Name of the set. Renames the tab. Default `ArnoldAttributesSet1`, and the same pattern for the other engines. |
| **Prim Path** | Locations that receive these attributes. Scene picker. Gaffer expressions work. |
| **+ / −** | Extra prim-path fields. All paths for a set go into one PathFilter. |
| **Clear** | Reset name, paths, and attribute values for that set. |
| **Remove** | Delete this set. Later sets shift down. |

Later sets override earlier ones where paths overlap.

Copy / Paste / Reset on the card header copies the engine, the Catmull-Clark toggle, and attribute sets onto another `sdvRenderAttributes`. Reset restores attribute defaults and keeps the engine.
