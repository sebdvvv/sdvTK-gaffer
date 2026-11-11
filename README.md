
# sdvTK-gaffer

This is an open-source contribution to [Gaffer](https://github.com/GafferHQ/gaffer), for anyone who wants a quick, production-shaped Arnold lighting workflow instead of wiring stock nodes by hand. It is designed around production-standard requirements, including a single node that provides every element needed for natural sky lighting.

One toolkit for lighting, shading, and render settings. Install this repo instead of the separate node packages.

<img width="1206" height="403" alt="gaffer_2026-11-07_12-24-30" src="https://github.com/user-attachments/assets/8c8a1a1d-7da6-4042-8522-b6aeda22ef0e" />

`ShadingTk`, `sdvRenderSettings`, and `sdvRenderAttributes` support Arnold, RenderMan, and Cycles. 

| Node |  | Node menu | README |
| --- | --- | --- | --- |
| `ArnoldLight` | One node for any Arnold light (area, spot, mesh, …) | **Arnold → ArnoldLight** | [ArnoldLight](docs/ArnoldLight/README.md) |
| `ArnoldPhysicalSky` | Natural sky: physical sky, HDRI, or a flat colour dome | **Arnold → ArnoldPhysicalSky** | [ArnoldPhysicalSky](docs/ArnoldPhysicalSky/README.md) |
| `ShadingTk` | Assign, mix, texture, and edit shaders | **Arnold → ShadingTk** | [ShadingTk](docs/ShadingTk/README.md) |
| `sdvRenderSettings` | Renderer options | **Render → sdvRenderSettings** | [sdvRenderSettings](docs/sdvRenderSettings/README.md) |
| `sdvRenderAttributes` | MeshType and renderer attribute sets | **Render → sdvRenderAttributes** | [sdvRenderAttributes](docs/sdvRenderAttributes/README.md) |

**Help** on a node opens that node's README in a browser.

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

Middle-click a layout tab to close it (Graph Editor, Viewer, and the other editors).

Closing a script that still has unsaved changes asks **Cancel | Discard | Save**. Discard is the middle button.

**sdvTk → Options** saves preferences in `~/gaffer/sdvtk_prefs.json`.

- **Double-click enters content nodes** — double-click a Box, Reference, or EditScope to open its contents.
- **Navigate node contents through a single pane** — that navigation stays in the current Graph Editor.
- **Ctrl + Double-click opens Node editor panels** — Ctrl+double-click opens a Node Editor for the node.
- **Graph View right-click menu has navigation** — the graph menu includes back (◀) and root (/).
- **Scene Hierarchy: browse without retriggering the Viewer** — expand and collapse in the Hierarchy View while the Viewer keeps its Visible Set.
- **Replace the Python Editor with [pw_MultiScriptEditor](https://github.com/sebdvvv/pw_MultiScriptEditor)** — set the folder that contains `multi_script_editor`. The next launch adds it to `PYTHONPATH` and docks that editor under the Graph Editor.

---

## Shelf

The shelf sits under the menu bar. Its tab reads **GAF**.

On first launch, sdvTk copies the shelf to `~/gaffer/shelves` when `sdvTk.json` is not already there. Gaffer then reads that local copy. Icons live in `~/gaffer/shelves/icons`.

The default buttons are Context, Forced Geometry, and the node connection tools on the left, and About at the far right.

Drop Python onto the shelf, or right-click it and choose **Add Action/Menu to shelf**. The dialog saves that code as a button or a menu on the local shelf.
