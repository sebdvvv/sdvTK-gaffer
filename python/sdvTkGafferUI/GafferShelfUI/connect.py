"""
Connect Node — shelf tool for wiring selected Gaffer nodes.

Selection order matters:
  Connect         — chain out→in in selection order (max 10 nodes);
                    with exactly 2 nodes, retries the reverse if A→B fails
  Disconnect      — 1 node: isolate (+ bypass if single input); 2+: between selection
  Insert Between  — first = upstream, second = downstream, last = node to insert
  Merge Scenes    — create MergeScenes; wire each selected scene out → in[i]
"""

from __future__ import print_function

import Gaffer
import GafferScene
import GafferUI
import imath

def _get_qt():
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtGui, QtWidgets
    return QtCore, QtWidgets, QtGui


def _dialog_exec(dialog):
    runner = getattr(dialog, "exec", None)
    if callable(runner):
        return runner()
    return dialog.exec_()

MAX_CONNECT_NODES = 10

# Preferred output plug names (first match wins)
_OUT_NAMES = ("out", "output", "Output")
# Preferred single-input names shown first when listing candidates
_IN_PRIORITY = ("in", "input", "Input", "filter", "shader")


def _selected_nodes(scriptNode):
    """Nodes in selection order (StandardSet preserves add order)."""
    return [n for n in scriptNode.selection() if isinstance(n, Gaffer.Node)]


def _plug_label(plug):
    try:
        return plug.relativeName(plug.node())
    except Exception:
        return plug.getName()


def _find_output(node):
    """Best output plug on *node* for graph-style connections."""
    for name in _OUT_NAMES:
        if name in node:
            plug = node[name]
            if isinstance(plug, Gaffer.Plug) and plug.direction() == Gaffer.Plug.Direction.Out:
                return plug
    for plug in node.children(Gaffer.Plug):
        if plug.getName() == "user":
            continue
        if plug.direction() == Gaffer.Plug.Direction.Out:
            return plug
    return None


def _iter_input_plugs(node):
    """Yield all connectable input plugs (including ArrayPlug children)."""
    for plug in node.children(Gaffer.Plug):
        if plug.getName() == "user":
            continue
        if isinstance(plug, Gaffer.ArrayPlug):
            for child in plug.children():
                if child.direction() == Gaffer.Plug.Direction.In:
                    yield child
        elif plug.direction() == Gaffer.Plug.Direction.In:
            yield plug


def _iter_output_plugs(node):
    """Yield all connectable output plugs (including ArrayPlug children)."""
    for plug in node.children(Gaffer.Plug):
        if plug.getName() == "user":
            continue
        if isinstance(plug, Gaffer.ArrayPlug):
            for child in plug.children():
                if child.direction() == Gaffer.Plug.Direction.Out:
                    yield child
        elif plug.direction() == Gaffer.Plug.Direction.Out:
            yield plug


def _candidate_inputs(dest, source_out):
    """
    Input plugs on *dest* that can accept *source_out*.

    ArrayPlug children (e.g. Group.in[0]) are listed individually.

    Prefers **unconnected** plugs so an already-wired source can still
    fan-out into a free input on *dest* instead of replacing an existing
    link (or no-opping on a plug that already has this source).
    """
    candidates = []
    if source_out is None:
        return candidates

    for plug in _iter_input_plugs(dest):
        try:
            if plug.acceptsInput(source_out):
                candidates.append(plug)
        except Exception:
            pass

    def _sort_key(p):
        name = p.getName()
        parent = p.parent()
        parent_name = parent.getName() if isinstance(parent, Gaffer.Plug) else name
        try:
            pri = _IN_PRIORITY.index(parent_name)
        except ValueError:
            try:
                pri = _IN_PRIORITY.index(name)
            except ValueError:
                pri = 100
        index = 0
        if isinstance(parent, Gaffer.ArrayPlug):
            try:
                index = list(parent.children()).index(p)
            except Exception:
                pass
        return (pri, parent_name, index, name)

    candidates.sort(key=_sort_key)

    free = []
    occupied_other = []
    occupied_same = []
    for plug in candidates:
        try:
            current = plug.getInput()
        except Exception:
            current = None
        if current is None:
            free.append(plug)
        elif current.isSame(source_out):
            occupied_same.append(plug)
        else:
            occupied_other.append(plug)

    # Free slots first — source may already be connected elsewhere (or here).
    if free:
        return free
    # No free slot: offer replacement of other drivers.
    if occupied_other:
        return occupied_other
    # Only plugs already driven by this source (nothing new to wire).
    return occupied_same


def _choose_input(dest_node, candidates, parent=None):
    """Return chosen plug, or None if cancelled. Auto-picks when only one."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    QtCore, QtWidgets, _QtGui = _get_qt()
    Qt = QtCore.Qt

    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle("Connect Node")
    dialog.setModal(True)
    dialog.setMinimumWidth(280)
    dialog.setStyleSheet("""
        QDialog { background-color: #2b2b2b; color: #dfdfdf; }
        QLabel { color: #dfdfdf; font-size: 10pt; }
        QPushButton {
            background-color: #3a3a3a; color: #dfdfdf;
            border: 1px solid #555555; border-radius: 3px;
            padding: 8px 12px; text-align: left;
        }
        QPushButton:hover { border: 1px solid #ffaa00; background-color: #4a4a4a; }
        QPushButton#CancelButton { text-align: center; color: #aaaaaa; }
    """)

    layout = QtWidgets.QVBoxLayout(dialog)
    layout.setSpacing(8)
    layout.setContentsMargins(14, 14, 14, 12)

    label = QtWidgets.QLabel("Select input for <b>%s</b>:" % dest_node.getName())
    label.setTextFormat(Qt.RichText)
    layout.addWidget(label)

    chosen = {"plug": None}

    def _pick(plug):
        chosen["plug"] = plug
        dialog.accept()

    for plug in candidates:
        btn = QtWidgets.QPushButton(_plug_label(plug))
        btn.clicked.connect(lambda checked=False, p=plug: _pick(p))
        layout.addWidget(btn)

    cancel = QtWidgets.QPushButton("Cancel")
    cancel.setObjectName("CancelButton")
    cancel.clicked.connect(dialog.reject)
    layout.addWidget(cancel)

    if _dialog_exec(dialog) != QtWidgets.QDialog.Accepted:
        return None
    return chosen["plug"]


def _parent_widget(scriptNode):
    try:
        window = GafferUI.ScriptWindow.acquire(scriptNode)
        if window is not None:
            return window._qtWidget()
    except Exception:
        pass
    return None


def _connect_pair(source, dest, parent_widget):
    """
    Connect source.out → dest.in (with multi-input popup if needed).

    If *source* is already wired elsewhere, still connects into a free input
    on *dest* (fan-out). Returns (ok, message). ok False + message None
    means user cancelled.
    """
    source_out = _find_output(source)
    if source_out is None:
        return False, "No output plug on '%s'." % source.getName()

    candidates = _candidate_inputs(dest, source_out)
    if not candidates:
        return (
            False,
            "No compatible input on '%s' for '%s.%s'."
            % (dest.getName(), source.getName(), source_out.getName()),
        )

    # Only plugs already driven by this source — already linked, nothing to add.
    already_only = True
    for plug in candidates:
        try:
            current = plug.getInput()
        except Exception:
            current = None
        if current is None or not current.isSame(source_out):
            already_only = False
            break
    if already_only:
        return (
            True,
            "Already linked %s.%s → %s (skipped)"
            % (source.getName(), source_out.getName(), dest.getName()),
        )

    dest_in = _choose_input(dest, candidates, parent=parent_widget)
    if dest_in is None:
        return False, None  # cancelled

    dest_in.setInput(source_out)
    return (
        True,
        "%s.%s → %s.%s"
        % (source.getName(), source_out.getName(), dest.getName(), _plug_label(dest_in)),
    )


def connect_nodes(scriptNode):
    """
    Chain-connect selected nodes in selection order (out → in).

    With exactly two nodes, if A→B has no compatible plugs, try B→A
    (selection order is often undefined). Max ``MAX_CONNECT_NODES`` nodes.
    """
    nodes = _selected_nodes(scriptNode)
    if len(nodes) < 2:
        print("[Connect Node] Select at least two nodes (in connection order).")
        return False

    if len(nodes) > MAX_CONNECT_NODES:
        print(
            "[Connect Node] Selection has %d nodes — connecting the first %d "
            "(max %d)."
            % (len(nodes), MAX_CONNECT_NODES, MAX_CONNECT_NODES)
        )
        nodes = nodes[:MAX_CONNECT_NODES]

    parent = _parent_widget(scriptNode)

    # Two nodes: try selection order, then reverse if incompatible.
    if len(nodes) == 2:
        a, b = nodes[0], nodes[1]
        with Gaffer.UndoScope(scriptNode):
            ok, msg = _connect_pair(a, b, parent)
            if msg is None and not ok:
                print(
                    "[Connect Node] Cancelled at '%s' → '%s'."
                    % (a.getName(), b.getName())
                )
                return False
            if ok:
                print("[Connect Node] %s" % msg)
                print("[Connect Node] Done — 1 link(s).")
                return True

            fwd_err = msg
            print(
                "[Connect Node] %s → %s failed (%s) — trying reverse…"
                % (a.getName(), b.getName(), fwd_err)
            )
            ok2, msg2 = _connect_pair(b, a, parent)
            if msg2 is None and not ok2:
                print(
                    "[Connect Node] Cancelled at '%s' → '%s'."
                    % (b.getName(), a.getName())
                )
                return False
            if ok2:
                print("[Connect Node] %s (reversed)" % msg2)
                print("[Connect Node] Done — 1 link(s).")
                return True

            print(
                "[Connect Node] Both directions failed:\n"
                "  %s → %s: %s\n"
                "  %s → %s: %s"
                % (
                    a.getName(), b.getName(), fwd_err,
                    b.getName(), a.getName(), msg2,
                )
            )
            print("[Connect Node] No connections made.")
            return False

    linked = []
    with Gaffer.UndoScope(scriptNode):
        for i in range(len(nodes) - 1):
            source, dest = nodes[i], nodes[i + 1]
            ok, msg = _connect_pair(source, dest, parent)
            if msg is None and not ok:
                print("[Connect Node] Cancelled at '%s' → '%s'." % (
                    source.getName(), dest.getName()
                ))
                break
            if not ok:
                print("[Connect Node] Skip %s → %s: %s" % (
                    source.getName(), dest.getName(), msg
                ))
                continue
            linked.append(msg)
            print("[Connect Node] %s" % msg)

    if not linked:
        print("[Connect Node] No connections made.")
        return False

    print("[Connect Node] Done — %d link(s)." % len(linked))
    return True


def _is_dot(node):
    """True for Gaffer.Dot (pass-through) nodes."""
    try:
        if isinstance(node, Gaffer.Dot):
            return True
    except Exception:
        pass
    return type(node).__name__ == "Dot"


def _node_in_set(node, node_set):
    for other in node_set:
        if node is not None and node.isSame(other):
            return True
    return False


def _input_source_node(inp_plug):
    try:
        connected = inp_plug.getInput()
    except Exception:
        return None, None
    if connected is None:
        return None, None
    try:
        return connected, connected.node()
    except Exception:
        return connected, None


def _dot_input_for_output(dot, out_plug):
    """Input plug on *dot* that feeds *out_plug* (Gaffer Dot mirroring)."""
    try:
        corresponding = dot.correspondingInput(out_plug)
        if corresponding is not None:
            return corresponding
    except Exception:
        pass
    if "in" in dot:
        try:
            return dot["in"]
        except Exception:
            pass
    for plug in _iter_input_plugs(dot):
        return plug
    return None


def _trace_through_dots(inp_plug):
    """
    Walk upstream from *inp_plug*, skipping Dot nodes only.

    Returns
        (source_plug, source_node, dots, dot_input_plugs)
    where *dots* / *dot_input_plugs* are the intermediate Dot chain
    (nearest-to-dest first). If there is no Dot chain, *dots* is empty
    and source is the immediate driver.
    """
    dots = []
    dot_inputs = []
    current_in = inp_plug
    seen = set()

    while current_in is not None:
        src_plug, src_node = _input_source_node(current_in)
        if src_plug is None or src_node is None:
            return None, None, dots, dot_inputs

        node_id = id(src_node)
        if node_id in seen:
            return None, None, dots, dot_inputs
        seen.add(node_id)

        if _is_dot(src_node):
            din = _dot_input_for_output(src_node, src_plug)
            if din is None:
                return None, None, dots, dot_inputs
            dots.append(src_node)
            dot_inputs.append(din)
            current_in = din
            continue

        return src_plug, src_node, dots, dot_inputs

    return None, None, dots, dot_inputs


def _clear_plug_input(inp_plug, removed, note=None):
    """Clear *inp_plug*'s input once; append a log line to *removed*."""
    src_plug, src_node = _input_source_node(inp_plug)
    if src_plug is None:
        return False
    try:
        src_name = src_node.getName() if src_node is not None else "?"
    except Exception:
        src_name = "?"
    try:
        dest_node = inp_plug.node()
        dest_name = dest_node.getName() if dest_node is not None else "?"
    except Exception:
        dest_name = "?"
    inp_plug.setInput(None)
    line = "%s → %s.%s" % (src_name, dest_name, _plug_label(inp_plug))
    if note:
        line = "%s (%s)" % (line, note)
    removed.append(line)
    return True


def _disconnect_single_node(scriptNode, node):
    """
    Strip all connections on one node.

    If the node has **exactly one** connected input, bypass-reconnect that
    upstream output into every former downstream input of this node::

        A → Selected → B   becomes   A → B   (Selected isolated)

    With multiple inputs, only isolate (no bypass).
    """
    removed = []
    bridged = []
    cleared = set()

    def _clear(plug, note=None):
        if plug is None:
            return
        pid = id(plug)
        if pid in cleared:
            return
        if _clear_plug_input(plug, removed, note=note):
            cleared.add(pid)

    # Snapshot connections before clearing
    connected_inputs = []
    for inp_plug in _iter_input_plugs(node):
        src_plug, src_node = _input_source_node(inp_plug)
        if src_plug is not None:
            connected_inputs.append((inp_plug, src_plug, src_node))

    destinations = []
    for out_plug in _iter_output_plugs(node):
        try:
            dests = list(out_plug.outputs())
        except Exception:
            dests = []
        for dest in dests:
            destinations.append(dest)

    bypass_src = None
    if len(connected_inputs) == 1:
        bypass_src = connected_inputs[0][1]  # upstream output plug

    with Gaffer.UndoScope(scriptNode):
        for inp_plug, _src, _src_node in connected_inputs:
            _clear(inp_plug, note="input")

        for dest in destinations:
            _clear(dest, note="output")

        # Bypass: upstream → former downstream(s)
        if bypass_src is not None and destinations:
            for dest in destinations:
                try:
                    # Skip if already wired (shouldn't be after clear)
                    if dest.getInput() is not None:
                        continue
                except Exception:
                    continue
                try:
                    if not dest.acceptsInput(bypass_src):
                        print(
                            "[Disconnect Node] Bypass skip — %s does not accept %s.%s"
                            % (
                                _plug_label(dest),
                                bypass_src.node().getName(),
                                bypass_src.getName(),
                            )
                        )
                        continue
                except Exception as e:
                    print("[Disconnect Node] Bypass skip — %s" % e)
                    continue
                dest.setInput(bypass_src)
                bridged.append(
                    "%s.%s → %s.%s"
                    % (
                        bypass_src.node().getName(),
                        bypass_src.getName(),
                        dest.node().getName(),
                        _plug_label(dest),
                    )
                )

    if not removed and not bridged:
        print(
            "[Disconnect Node] '%s' has no input/output connections."
            % node.getName()
        )
        return False

    for line in removed:
        print("[Disconnect Node] %s" % line)
    for line in bridged:
        print("[Disconnect Node] Bypass %s" % line)
    print(
        "[Disconnect Node] Done — %d link(s) removed from '%s'%s."
        % (
            len(removed),
            node.getName(),
            (", %d bypass" % len(bridged)) if bridged else "",
        )
    )
    return True


def disconnect_nodes(scriptNode):
    """
    Disconnect selected nodes.

    - **1 node:** clear all inputs/outputs; if it had exactly one input,
      reconnect that upstream into the former downstream node(s) (bypass).
    - **2+ nodes:** clear links *between* the selection.
      - Direct: selected → selected
      - Via Dot: if ``first → Dot → other``, only clear ``Dot.in ← first``
        (never the Dot *output* into the downstream node).
    """
    nodes = _selected_nodes(scriptNode)
    if not nodes:
        print("[Disconnect Node] Select at least one node.")
        return False

    if len(nodes) == 1:
        return _disconnect_single_node(scriptNode, nodes[0])

    first = nodes[0]
    selected_set = list(nodes)
    removed = []
    cleared = set()  # id(plug) already cleared this undo step

    def _clear(plug, note=None):
        if plug is None:
            return
        pid = id(plug)
        if pid in cleared:
            return
        if _clear_plug_input(plug, removed, note=note):
            cleared.add(pid)

    with Gaffer.UndoScope(scriptNode):
        for dest in nodes:
            for inp_plug in _iter_input_plugs(dest):
                src_plug, src_node, dots, dot_inputs = _trace_through_dots(inp_plug)
                if src_node is None:
                    continue
                if not _node_in_set(src_node, selected_set):
                    continue
                if src_node.isSame(dest):
                    continue

                if not dots:
                    # Direct selected → selected
                    _clear(inp_plug)
                    continue

                # Via Dot: only unhook the *first* selected node from the Dot
                # (Dot input). Leave Dot.out → dest connected.
                if not src_node.isSame(first):
                    continue
                # Nearest-to-dest first → last entry is the Dot fed by *first*
                for din in reversed(dot_inputs):
                    _din_plug, din_src = _input_source_node(din)
                    if din_src is not None and din_src.isSame(first):
                        _clear(din, note="first→Dot")
                        break

    if not removed:
        print(
            "[Disconnect Node] No connections between the selected nodes "
            "(including first→Dot)."
        )
        return False

    for line in removed:
        print("[Disconnect Node] %s" % line)
    print("[Disconnect Node] Done — %d link(s) removed." % len(removed))
    return True


def insert_between(scriptNode):
    """
    Insert last-selected node between the first two (stub for next iteration).

    Expected selection: upstream, downstream, then the node to insert.
    """
    nodes = _selected_nodes(scriptNode)
    if len(nodes) < 3:
        print(
            "[Connect Node] Insert Between — select upstream, downstream, "
            "then the node to insert (3 nodes)."
        )
        return False

    upstream, downstream, insert = nodes[0], nodes[1], nodes[-1]
    print(
        "[Connect Node] Insert Between — not implemented yet "
        "(%s → %s → %s)."
        % (upstream.getName(), insert.getName(), downstream.getName())
    )
    return False


def _scene_output(node):
    """Return a ``ScenePlug`` output on *node*, or ``None``."""
    if node is None:
        return None
    if "out" in node:
        plug = node["out"]
        try:
            if (
                isinstance(plug, GafferScene.ScenePlug)
                and plug.direction() == Gaffer.Plug.Direction.Out
            ):
                return plug
        except Exception:
            pass
    for plug in _iter_output_plugs(node):
        try:
            if isinstance(plug, GafferScene.ScenePlug):
                return plug
        except Exception:
            pass
    return None


def _graph_for_parent(scriptNode, parent):
    """Return ``(graphEditor, graphGadget)`` viewing *parent*, or ``(None, None)``."""
    try:
        window = GafferUI.ScriptWindow.acquire(scriptNode)
        if window is None:
            return None, None
        for ge in window.getLayout().editors(GafferUI.GraphEditor) or []:
            try:
                gg = ge.graphGadget()
                if gg.getRoot().isSame(parent):
                    return ge, gg
            except Exception:
                continue
    except Exception:
        pass
    return None, None


def merge_scenes(scriptNode):
    """
    Create ``MergeScenes`` and connect each selected node's scene output
    into consecutive ``in[0]``, ``in[1]``, … inputs (selection order).

    Nodes without a scene output are skipped. Needs at least two valid
    scene sources in the same graph parent.
    """
    nodes = _selected_nodes(scriptNode)
    if len(nodes) < 2:
        print(
            "[Connect Node] Merge Scenes — select at least 2 scene nodes "
            "(order = MergeScenes input order)."
        )
        return False

    sources = []
    skipped = []
    for node in nodes:
        out = _scene_output(node)
        if out is None:
            skipped.append(node.getName())
        else:
            sources.append((node, out))

    if skipped:
        print(
            "[Connect Node] Merge Scenes — skipped (no scene output): %s"
            % ", ".join(skipped)
        )

    if len(sources) < 2:
        print(
            "[Connect Node] Merge Scenes — need at least 2 nodes with a "
            "scene output (got %d)."
            % len(sources)
        )
        return False

    parent = sources[0][0].parent()
    if parent is None:
        print("[Connect Node] Merge Scenes — selection has no parent graph.")
        return False
    for node, _out in sources[1:]:
        if node.parent() is None or not node.parent().isSame(parent):
            print(
                "[Connect Node] Merge Scenes — all selected nodes must be "
                "in the same graph."
            )
            return False

    graphEditor, graphGadget = _graph_for_parent(scriptNode, parent)
    linked = []

    with Gaffer.UndoScope(scriptNode):
        merge = GafferScene.MergeScenes()
        parent.addChild(merge)
        try:
            with scriptNode.context():
                Gaffer.NodeAlgo.applyUserDefaults(merge)
        except Exception:
            pass

        for i, (node, out) in enumerate(sources):
            try:
                merge["in"][i].setInput(out)
                linked.append(node.getName())
            except Exception as e:
                print(
                    "[Connect Node] Merge Scenes — failed %s → in[%d]: %s"
                    % (node.getName(), i, e)
                )

        if len(linked) < 2:
            try:
                parent.removeChild(merge)
            except Exception:
                pass
            print(
                "[Connect Node] Merge Scenes — aborted (fewer than 2 "
                "connections succeeded)."
            )
            return False

        if graphGadget is not None:
            try:
                last = sources[-1][0]
                pos = graphGadget.getNodePosition(last)
                graphGadget.setNodePosition(merge, pos + imath.V2f(8, -6))
            except Exception:
                try:
                    graphGadget.getLayout().positionNode(graphGadget, merge)
                except Exception:
                    pass

        scriptNode.selection().clear()
        scriptNode.selection().add(merge)
        if graphEditor is not None:
            try:
                graphEditor.frame([merge], extend=True)
            except Exception:
                pass

    print(
        "[Connect Node] Merge Scenes — %s → %s (%d input(s))."
        % (", ".join(linked), merge.getName(), len(linked))
    )
    return True
