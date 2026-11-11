"""Node Editor presentation for ``sdvUSDWriter.sdvUSDWriter``."""

from __future__ import annotations

import Gaffer
import GafferDispatch
import GafferSceneUI  # noqa: F401  registers the scene path widget
import GafferUI
import IECore

from sdvTkGaffer.sdvUSDWriter.sdvUSDWriter import sdvUSDWriter


class _Actions(GafferUI.ListContainer):
    """Scene write, then the same write plus render settings."""

    def __init__(self, node):
        GafferUI.ListContainer.__init__(
            self, GafferUI.ListContainer.Orientation.Vertical, spacing=4
        )
        self.__node = node
        write = GafferUI.Button("Write USD")
        write_all = GafferUI.Button("USD Write All")
        self.append(write)
        self.append(write_all)
        write.clickedSignal().connect(Gaffer.WeakMethod(self.__write))
        write_all.clickedSignal().connect(Gaffer.WeakMethod(self.__write_all))

    def __write(self, button):
        self.__run("write")

    def __write_all(self, button):
        self.__run("write_all")

    def __run(self, method):
        script = self.__node.scriptNode()
        with script.context():
            with Gaffer.UndoScope(script, Gaffer.UndoScope.State.Disabled):
                with GafferUI.ErrorDialogue.ErrorHandler(
                    title="Errors Occurred During Dispatch",
                    parentWindow=self.ancestor(GafferUI.Window),
                ):
                    getattr(self.__node, method)()


Gaffer.Metadata.registerNode(

    sdvUSDWriter,

    "layout:customWidget:actions:widgetType",
    "sdvTkGafferUI.sdvUSDWriterUI.sdvUSDWriterUI._Actions",
    "layout:customWidget:actions:section",
    "",
    "layout:customWidget:actions:index",
    100,
    "layout:activator:never",
    lambda node: False,
    "layout:activator:customFrames",
    lambda node: node["framesMode"].getValue()
    == GafferDispatch.Dispatcher.FramesMode.CustomRange,
    "layout:customWidget:dispatcherCreationWidget:visibilityActivator",
    "never",

    plugs={

        "in": {
            "nodule:type": "GafferUI::StandardNodule",
            "noduleLayout:section": "top",
            "plugValueWidget:type": "",
        },

        "out": {
            "nodule:type": "",
            "plugValueWidget:type": "",
        },

        "user": {
            "plugValueWidget:type": "",
            "nodule:type": "",
        },

        "task": {
            "nodule:type": "",
        },

        "preTasks": {
            "nodule:type": "",
        },

        "preTasks.*": {
            "nodule:type": "",
        },

        "postTasks": {
            "nodule:type": "",
        },

        "postTasks.*": {
            "nodule:type": "",
        },

        "renderer": {
            "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
            "preset:Arnold": "arnold",
            "preset:RenderMan": "renderman",
            "preset:Cycles": "cycles",
            "layout:section": "",
            "layout:index": 0,
            "label": "Renderer",
        },

        "fileName": {
            "plugValueWidget:type": "GafferUI.FileSystemPathPlugValueWidget",
            "path:leaf": True,
            "path:bookmarks": "sceneCache",
            "fileSystemPath:extensions": "usd usda usdc usdz",
            "fileSystemPath:extensionsLabel": "Show only USD files",
            "layout:section": "",
            "layout:index": 1,
        },

        "extension": {
            "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
            "preset:.usd": "usd",
            "preset:.usda": "usda",
            "preset:.usdc": "usdc",
            "preset:.usdz": "usdz",
            "layout:section": "",
            "layout:index": 2,
        },

        "camera": {
            "plugValueWidget:type": "GafferSceneUI.ScenePathPlugValueWidget",
            "path:valid": True,
            "scenePathPlugValueWidget:setNames": IECore.StringVectorData(["__cameras"]),
            "scenePathPlugValueWidget:setsLabel": "Show only cameras",
            "layout:section": "",
            "layout:index": 4,
            "label": "Camera",
        },

        "renderRoot": {
            "layout:section": "",
            "layout:index": 5,
        },

        "settingsName": {
            "layout:section": "",
            "layout:index": 6,
        },

        "fileOutputsOnly": {
            "layout:section": "",
            "layout:index": 7,
        },

        "framesMode": {
            "plugValueWidget:type": "GafferUI.PresetsPlugValueWidget",
            "preset:Current Frame": GafferDispatch.Dispatcher.FramesMode.CurrentFrame,
            "preset:Full Range": GafferDispatch.Dispatcher.FramesMode.FullRange,
            "preset:Custom Range": GafferDispatch.Dispatcher.FramesMode.CustomRange,
            "layout:section": "",
            "layout:index": 10,
            "label": "Frames",
        },

        "frameRange": {
            "layout:section": "",
            "layout:index": 11,
            "layout:visibilityActivator": "customFrames",
            "label": "Frame Range",
        },

        "enabled": {
            "layout:section": "",
            "layout:index": 9,
        },

        "dispatcher": {
            "plugValueWidget:type": "GafferUI.LayoutPlugValueWidget",
            "layout:section": "",
            "layout:index": 8,
            "label": "",
        },

        "dispatcher.immediate": {
            "label": "Immediate",
        },

        "dispatcher.batchSize": {
            "plugValueWidget:type": "",
        },

        "dispatcher.isolated": {
            "plugValueWidget:type": "",
        },

    },

)
