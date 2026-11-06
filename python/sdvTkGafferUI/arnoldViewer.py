"""Register the Arnold SceneView with sdvTk viewer settings.

Shading, Lighting, and Textures default to Full. The settings graph is
``startup/gui/arnoldViewerSettings.gfr``. Registration is deferred so it
runs after Gaffer's stock ``gui/viewer.py``.
"""

from __future__ import annotations

import functools
import os

import Gaffer
import GafferScene
import GafferUI

_FULL = ("shading", "lighting", "texturing")


def settings_path() -> str | None:
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(os.path.join(here, "..", "..", "startup", "gui"))
    roots = [repo]
    env = os.environ.get("GAFFER_STARTUP_PATHS") or ""
    roots.extend(part for part in env.split(os.pathsep) if part)
    for root in roots:
        candidate = os.path.join(root, "gui", "arnoldViewerSettings.gfr")
        if not os.path.isfile(candidate):
            candidate = os.path.join(root, "arnoldViewerSettings.gfr")
        if os.path.isfile(candidate):
            return candidate
    return None


def _load_full(file_name: str):
    script = Gaffer.ScriptNode()
    script["fileName"].setValue(file_name)
    script.load()
    settings = script["ViewerSettings"]
    for plug_name in _FULL:
        try:
            plug = settings[plug_name]
            plug.setValue("full")
            plug.resetDefault()
        except Exception as exc:
            print("[sdvTk] Could not set Arnold Viewer {} to Full: {}".format(plug_name, exc))
    script["Processor"] = GafferScene.SceneProcessor()
    script.execute(
        script.serialise(parent=script["ViewerSettings"]),
        parent=script["Processor"],
    )
    script["Processor"]["BoxIn"]["__in"].setInput(script["Processor"]["in"])
    script["Processor"]["out"].setInput(script["Processor"]["BoxOut"]["__out"])
    for plug in Gaffer.ValuePlug.InputRange(script["Processor"]):
        plug.setToDefault()
    return script["Processor"]


def install_full_shading_default() -> bool:
    try:
        import GafferArnold  # noqa: F401
        import GafferSceneUI
    except Exception:
        return False
    path = settings_path()
    if not path:
        print("[sdvTk] arnoldViewerSettings.gfr not found — skip Full shading default")
        return False
    GafferSceneUI.SceneView.registerRenderer(
        "Arnold",
        functools.partial(_load_full, path),
    )
    return True


def install_progress_log_defaults() -> bool:
    try:
        import GafferArnold
    except Exception:
        return False
    for plug in (
        "options.logProgress.enabled",
        "options.logProgress.value",
        "options.consoleProgress.enabled",
        "options.consoleProgress.value",
        "options.ai:log:progress.enabled",
        "options.ai:log:progress.value",
        "options.ai:console:progress.enabled",
        "options.ai:console:progress.value",
    ):
        Gaffer.Metadata.registerValue(GafferArnold.ArnoldOptions, plug, "userDefault", True)
    return True


def install(application=None) -> None:
    try:
        install_progress_log_defaults()
    except Exception as exc:
        print("[sdvTk] Arnold progress log defaults failed: {}".format(exc))

    def _deferred():
        try:
            install_full_shading_default()
        except Exception as exc:
            print("[sdvTk] Arnold Full shading install failed: {}".format(exc))
        return False

    try:
        GafferUI.EventLoop.addIdleCallback(_deferred)
    except Exception:
        try:
            install_full_shading_default()
        except Exception as exc:
            print("[sdvTk] Arnold Full shading install failed: {}".format(exc))
