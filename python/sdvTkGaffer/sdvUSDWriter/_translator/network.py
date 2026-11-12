"""Write a Gaffer shader network as USD shaders under a node graph.

Arnold, Cycles, and RenderMan each point a render-settings attribute at
that graph. The graph terminal connects to the network output.
"""

from __future__ import annotations


def shader_network(data):
    if data is None or type(data).__name__ != "ShaderNetwork":
        return None
    if not hasattr(data, "shaders") or not hasattr(data, "getOutput"):
        return None
    return data


def author_shader_network(
    stage,
    settings_prim,
    network,
    *,
    graph_path: str,
    graph_type: str,
    terminal: str,
    link_name: str,
    node_id,
    scopes: tuple,
    name_attr: str | None = None,
) -> bool:
    """Author ``network`` and link it from ``settings_prim``. False if it has no output."""
    from pxr import Sdf, UsdShade

    from .common import _usd_value, prim_token

    shaders = _network_shaders(network)
    if not shaders or settings_prim is None:
        return False
    output_handle, output_port = _endpoint(network.getOutput())
    if output_handle not in {handle for handle, _shader in shaders}:
        return False
    output_port = _port(output_port or "out")

    for scope in scopes:
        _ensure_scope(stage, scope)
    graph = stage.DefinePrim(graph_path, graph_type)
    if name_attr:
        graph_name = graph.CreateAttribute(name_attr, Sdf.ValueTypeNames.String, custom=False)
        graph_name.Set(graph_path)

    used = set()
    paths = {}
    usd_shaders = {}
    for handle, shader in shaders:
        name = prim_token(handle)
        while name in used:
            name = name + "_"
        used.add(name)
        path = graph_path + "/" + name
        paths[handle] = path
        usd_shader = UsdShade.Shader.Define(stage, path)
        usd_shader.CreateIdAttr(node_id(_shader_field(shader, "name", "getName")))
        if name_attr:
            node_name = usd_shader.GetPrim().CreateAttribute(
                name_attr, Sdf.ValueTypeNames.String, custom=False
            )
            node_name.Set(handle)
        _author_shader_parameters(usd_shader, shader, _usd_value)
        usd_shaders[handle] = usd_shader

    for handle, _shader in shaders:
        for connection in _connections(network, handle):
            source_handle, source_port = _endpoint(connection.source)
            dest_handle, dest_port = _endpoint(connection.destination)
            source = usd_shaders.get(source_handle)
            dest = usd_shaders.get(dest_handle)
            if source is None or dest is None or not dest_port:
                continue
            source_output = source.CreateOutput(
                _port(source_port or "out"), Sdf.ValueTypeNames.Token
            )
            dest_input = _input_for_connection(dest, _port(dest_port))
            dest_input.ConnectToSource(source_output)

    output_path = paths[output_handle] + ".outputs:" + output_port
    usd_shaders[output_handle].CreateOutput(output_port, Sdf.ValueTypeNames.Token)
    terminal_attr = graph.CreateAttribute(
        "outputs:" + terminal, Sdf.ValueTypeNames.Token, custom=False
    )
    terminal_attr.SetConnections([Sdf.Path(output_path)])
    link = settings_prim.CreateAttribute(link_name, Sdf.ValueTypeNames.String, custom=False)
    link.Set(graph_path)
    return True


def _author_shader_parameters(usd_shader, shader, usd_value) -> None:
    for name, data in _parameter_items(shader):
        port = _port(name)
        if not port or port == "out":
            continue
        converted = usd_value(data)
        if converted is None:
            continue
        value, type_name = converted
        usd_shader.CreateInput(port, type_name).Set(value)


def _input_for_connection(usd_shader, port):
    from pxr import Sdf

    existing = usd_shader.GetInput(port)
    if existing:
        return existing
    return usd_shader.CreateInput(port, Sdf.ValueTypeNames.Token)


def _network_shaders(network):
    shaders = network.shaders()
    if hasattr(shaders, "items"):
        return [(str(handle), shader) for handle, shader in shaders.items()]
    return [(str(handle), shaders[handle]) for handle in shaders]


def _connections(network, handle):
    connected = getattr(network, "inputConnections", None)
    if connected is None:
        return []
    return list(connected(handle))


def _endpoint(parameter):
    if isinstance(parameter, (tuple, list)):
        shader = parameter[0] if parameter else ""
        name = parameter[1] if len(parameter) > 1 else ""
        return str(shader), str(name or "")
    return str(getattr(parameter, "shader", "") or ""), str(getattr(parameter, "name", "") or "")


def _parameter_items(shader):
    parameters = getattr(shader, "parameters", None) or {}
    if hasattr(parameters, "items"):
        return list(parameters.items())
    return [(name, parameters[name]) for name in parameters]


def _shader_field(shader, field, getter):
    value = getattr(shader, field, None)
    if callable(value):
        value = value()
    if value:
        return str(value)
    method = getattr(shader, getter, None)
    if method is None:
        return ""
    return str(method() or "")


def _port(name: str) -> str:
    from .common import attribute_name

    return attribute_name(str(name or "").replace(".", ":"))


def _ensure_scope(stage, path) -> None:
    from pxr import UsdGeom

    if stage.GetPrimAtPath(path):
        return
    UsdGeom.Scope.Define(stage, path)
