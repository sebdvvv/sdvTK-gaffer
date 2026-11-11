"""sdvUSDWriter — scene USD plus UsdRender settings, products, and vars.

One scene input. An empty scene is the base, and the input is the layer.
Render globals become ``/Render/Settings``, ``RenderProduct``, and ``RenderVar`` prims.
"""

from __future__ import annotations

import Gaffer
import GafferDispatch
import GafferScene
import GafferUSD
import IECore

from ._translate import (
    author_render_settings,
    members_from_globals,
    package_usdz,
    promote_arnold_lights,
    replace_extension,
    scene_write_path,
)

from sdvTkGaffer.sdvRenderSettings._data import default_engine

_SCENE_FILE_VARIABLE = "sdvUSDWriter:sceneFile"
_RENDER_VARIABLE = "sdvUSDWriter:render"


class sdvUSDWriter(GafferDispatch.TaskNode):
    """Write a USD file and author UsdRender prims from the scene globals.

    Arnold lights are written as UsdLux prims.
    """

    def __init__(self, name: str = "sdvUSDWriter"):
        GafferDispatch.TaskNode.__init__(self, name)

        self.addChild(GafferScene.ScenePlug("in", Gaffer.Plug.Direction.In))
        self.addChild(Gaffer.StringPlug("renderer", defaultValue=default_engine()))
        self.addChild(Gaffer.StringPlug("fileName", defaultValue=""))
        extension = Gaffer.StringPlug("extension", defaultValue="usd")
        self.addChild(extension)
        self.addChild(Gaffer.StringPlug("camera", defaultValue=""))
        self.addChild(Gaffer.StringPlug("renderRoot", defaultValue="/Render"))
        self.addChild(Gaffer.StringPlug("settingsName", defaultValue="Settings"))
        self.addChild(Gaffer.BoolPlug("fileOutputsOnly", defaultValue=True))
        self.addChild(
            Gaffer.IntPlug(
                "framesMode",
                defaultValue=int(GafferDispatch.Dispatcher.FramesMode.FullRange),
            )
        )
        self.addChild(Gaffer.StringPlug("frameRange", defaultValue="1-100"))
        self._updatingExtension = False
        self.__plugSetConnection = self.plugSetSignal().connect(
            Gaffer.WeakMethod(self.__plugSet)
        )

        out = GafferScene.ScenePlug(
            "out",
            Gaffer.Plug.Direction.Out,
            Gaffer.Plug.Flags.Default & ~Gaffer.Plug.Flags.Serialisable,
        )
        self.addChild(out)
        out.setInput(self["in"])
        self._wire_writer()
        self._wire_dispatcher()
        _enable_immediate(self)

    def write(self) -> None:
        """Dispatch the layer writer for the script frame range."""
        writer = self._wire_writer()
        dispatcher = self._wire_dispatcher()
        scene_file, package = scene_write_path(self["fileName"].getValue())
        if not scene_file:
            return
        task = dispatcher["tasks"][0]
        previous = task.getInput()
        _set_input(task, writer["task"])
        try:
            with Gaffer.Context(Gaffer.Context.current()) as context:
                context[_SCENE_FILE_VARIABLE] = scene_file
                dispatcher["task"].execute()
        finally:
            if previous is None:
                task.setInput(None)
            else:
                _set_input(task, previous)
        promote_arnold_lights(scene_file)
        if package:
            package_usdz(scene_file, package)

    def write_all(self) -> None:
        """Write the scene and the render settings for the script frame range."""
        self._dispatch(True)

    def _dispatch(self, render: bool) -> None:
        with Gaffer.Context(Gaffer.Context.current()) as context:
            context[_RENDER_VARIABLE] = bool(render)
            self._wire_dispatcher()["task"].execute()

    def execute(self) -> None:
        frame = Gaffer.Context.current().getFrame()
        self.executeSequence([frame])

    def executeSequence(self, frames) -> None:
        frames = [float(frame) for frame in frames]
        if not frames:
            return
        if self["in"].getInput() is None:
            raise IECore.Exception("No input scene")

        files = self._files_for_frames(frames)
        if not files:
            return

        writer = self._wire_writer()
        for file_name, file_frames in files.items():
            scene_file, package = scene_write_path(file_name)
            with Gaffer.Context(Gaffer.Context.current()) as context:
                context[_SCENE_FILE_VARIABLE] = scene_file
                writer["task"].executeSequence(file_frames)
            if self._include_render():
                author_render_settings(
                    scene_file,
                    self._samples(file_frames),
                    self["renderRoot"].getValue(),
                    self["settingsName"].getValue(),
                    self["fileOutputsOnly"].getValue(),
                    self._camera(file_frames[0]),
                    self["renderer"].getValue(),
                )
            if package:
                package_usdz(scene_file, package)

    def hash(self, context):
        if self["fileName"].getValue() == "" or self["in"].getInput() is None:
            return IECore.MurmurHash()
        result = GafferDispatch.TaskNode.hash(self, context)
        self["fileName"].hash(result)
        _hash_scene(result, self["in"], context)
        self["renderRoot"].hash(result)
        self["settingsName"].hash(result)
        self["fileOutputsOnly"].hash(result)
        self["camera"].hash(result)
        self["renderer"].hash(result)
        result.append(context.hash())
        return result

    def requiresSequenceExecution(self) -> bool:
        return True

    def _wire_merges(self):
        blank = self._hidden_merge("mS1")
        merged = self._hidden_merge("mS2")
        _set_input(merged["in"][0], blank["out"])
        _set_input(merged["in"][1], self["in"])
        return blank, merged

    def _hidden_merge(self, name):
        node = self.getChild(name)
        if node is None:
            node = GafferScene.MergeScenes(name)
            self.addChild(node)
            Gaffer.Metadata.registerValue(node, "nodeGadget:visible", False)
            if name == "mS2":
                # Keep would leave the blank scene's globals. Merge lets the input win.
                node["globalsMode"].setValue(GafferScene.MergeScenes.Mode.Merge)
        return node

    def _wire_writer(self):
        blank, merged = self._wire_merges()
        writer = self.getChild("__writer")
        created = writer is None
        if created:
            leftover = self.getChild("__sceneWriter")
            if leftover is not None:
                self.removeChild(leftover)
            writer = GafferUSD.USDLayerWriter("__writer")
            self.addChild(writer)
            Gaffer.Metadata.registerValue(writer, "nodeGadget:visible", False)
            _enable_immediate(writer)
            scene_writer = writer.getChild("__sceneWriter")
            if scene_writer is not None:
                _enable_immediate(scene_writer)
        _set_input(writer["base"], blank["out"])
        _set_input(writer["layer"], merged["out"])
        # `.usdz` writes a crate file first; the package path stays on `fileName`.
        if created or writer["fileName"].getInput() is not None:
            if writer["fileName"].getInput() is not None:
                writer["fileName"].setInput(None)
            writer["fileName"].setValue("${" + _SCENE_FILE_VARIABLE + "}")
        return writer

    def _wire_dispatcher(self):
        dispatcher = self.getChild("__dispatcher")
        if dispatcher is None:
            dispatcher = GafferDispatch.LocalDispatcher("__dispatcher")
            self.addChild(dispatcher)
            Gaffer.Metadata.registerValue(dispatcher, "nodeGadget:visible", False)
            _enable_immediate(dispatcher)
        dispatcher["executeInBackground"].setValue(False)
        dispatcher["framesMode"].setValue(self["framesMode"].getValue())
        dispatcher["frameRange"].setValue(self["frameRange"].getValue())
        _set_input(dispatcher["tasks"][0], self["task"])
        return dispatcher

    def _include_render(self) -> bool:
        try:
            return bool(Gaffer.Context.current()[_RENDER_VARIABLE])
        except Exception:
            return True

    def _camera(self, frame):
        with Gaffer.Context(Gaffer.Context.current()) as context:
            context.setFrame(frame)
            camera = self["camera"].getValue().strip()
        return camera or None

    def __plugSet(self, plug) -> None:
        if self._updatingExtension or plug.getName() != "extension":
            return
        if self["fileName"].getInput() is not None:
            return
        updated = replace_extension(self["fileName"].getValue(), plug.getValue())
        if updated == self["fileName"].getValue():
            return
        self._updatingExtension = True
        try:
            self["fileName"].setValue(updated)
        finally:
            self._updatingExtension = False

    def _files_for_frames(self, frames):
        """Last run of frames that share a file name, in dispatch order."""
        segments = []
        with Gaffer.Context(Gaffer.Context.current()) as context:
            for frame in frames:
                context.setFrame(frame)
                file_name = self["fileName"].getValue()
                if not file_name:
                    continue
                if segments and segments[-1][0] == file_name:
                    segments[-1][1].append(frame)
                else:
                    segments.append([file_name, [frame]])
        files = {}
        for file_name, file_frames in segments:
            files[file_name] = file_frames
        return files

    def _samples(self, frames):
        samples = []
        with Gaffer.Context(Gaffer.Context.current()) as context:
            for frame in frames:
                context.setFrame(frame)
                samples.append(
                    (
                        context.getTime(),
                        members_from_globals(self["in"].globals()),
                    )
                )
        return samples


def _hash_scene(result, scene, context) -> None:
    # ScenePlug.hash() reads bound with no scene:path. hierarchyHash sets it.
    with Gaffer.Context(context):
        result.append(GafferScene.SceneAlgo.hierarchyHash(scene, "/"))
        result.append(scene.globalsHash())
        result.append(scene.setNamesHash())
        for name in scene.setNames():
            result.append(scene.setHash(name))


def _enable_immediate(node) -> None:
    try:
        node["dispatcher"]["immediate"].setValue(True)
    except Exception:
        return


def _set_input(plug, source) -> None:
    current = None
    try:
        current = plug.getInput()
    except Exception:
        current = None
    if current is not None:
        try:
            if current.isSame(source):
                return
        except Exception:
            pass
    plug.setInput(source)


sdvUSDWriter.__module__ = "sdvUSDWriter.sdvUSDWriter"
IECore.registerRunTimeTyped(sdvUSDWriter)

Gaffer.Metadata.registerNode(
    sdvUSDWriter,
    "description",
    """
    Writes the input scene to a USD file, then can author UsdRender prims from
    the scene globals. **Frames** chooses the current frame, the script
    frame range, or a custom range. **Write USD** writes the scene for
    those frames. **USD Write All** writes the scene and the render settings.
    Evaluating the scene does not write the file.

    On top of that file, even when there are no outputs:

    - a Scope at `renderRoot` (default `/Render`)
    - a RenderSettings prim at `{renderRoot}/{settingsName}` (default
      `/Render/Settings`)
    - a Products scope and a Vars scope next to it
    - one RenderProduct per output file, when outputs exist
    - one RenderVar per AOV, when outputs exist

    Stage metadata `renderSettingsPrimPath` points at the settings prim.
    Settings are taken from the first frame in the file. When an output's
    expanded file name changes across the frame range, `productName` is
    time-sampled on the same time base as the scene.

    Renderer options for the selected engine are copied onto the settings
    prim. Arnold's `ai:` options are written as `arnold:`. RenderMan stays
    `ri:` and Cycles stays `cycles:`. `render:inclusions` is copied as a
    string and does not prune the scene.
    """,
    plugs={
        "renderer": {
            "description":
            """
            Engine whose options are written onto the RenderSettings prim.
            Arnold, RenderMan, or Cycles. Options for the other engines are
            left out. Arnold's `ai:` options are written as `arnold:`.
            """,
        },
        "in": {
            "description": "The scene to write.",
        },
        "out": {
            "description": "A direct pass-through of the input scene.",
        },
        "fileName": {
            "description":
            """
            The USD file to write. Use one file for the whole frame range.
            Extension changes from the menu rewrite this path.
            """,
        },
        "extension": {
            "description":
            """
            File type for `fileName`. Choosing an entry rewrites the extension
            on File Name. `.usd`, `.usda`, and `.usdc` are written directly.
            `.usdz` is packaged from a crate layer.
            """,
        },
        "camera": {
            "description":
            """
            Renderable camera. When set, this location is the `camera`
            target on the RenderSettings prim, in place of `render:camera`
            from the scene. Leave empty to use that global.
            """,
        },
        "renderRoot": {
            "description":
            """
            Parent prim for the render prims. Settings, Products, and Vars
            are created under this path. Default `/Render`.
            """,
        },
        "settingsName": {
            "description":
            """
            Name of the RenderSettings prim under `renderRoot`. Default
            `Settings`, which writes `/Render/Settings`.
            """,
        },
        "fileOutputsOnly": {
            "description":
            """
            Skip display drivers such as `ieDisplay`. Turn this off to write
            a RenderProduct for interactive outputs as well.
            """,
        },
        "framesMode": {
            "description":
            """
            Frames written by Write USD and USD Write All.

            Current Frame writes the frame on the timeline. Full Range writes
            the script frame range. Custom Range writes the Frame Range field.
            """,
        },
        "frameRange": {
            "description":
            """
            Frames used when Frames is Custom Range. `1-10` writes every
            frame from 1 to 10. `1-10x2` writes every second frame.
            """,
        },
        "dispatcher.immediate": {
            "description":
            """
            Execute this node in the dispatching process. The internal
            writer and dispatcher are immediate as well.
            """,
        },
    },
)
