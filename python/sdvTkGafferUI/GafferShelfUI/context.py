"""Print the current script context (frame, shot variables, and the rest)."""

from __future__ import print_function

import gc

import Gaffer

_BANNER = "============== Gaffer Scene INFOS =============="


def print_script_contexts(scriptNode=None):
    """Dump context names and values. One script, or every open script."""
    if scriptNode is not None:
        scripts = [scriptNode]
    else:
        scripts = [o for o in gc.get_objects() if isinstance(o, Gaffer.ScriptNode)]

    print(_BANNER)
    if not scripts:
        print("No ScriptNode found.")
        print(_BANNER)
        return []

    seen = set()
    lines = []
    for script in scripts:
        try:
            context = script.context()
            names = sorted(context.names())
        except Exception as error:
            print("Could not read context: %s" % error)
            continue
        for name in names:
            try:
                line = "%s : %s" % (name, context[name])
            except Exception as error:
                line = "%s : <error: %s>" % (name, error)
            if line in seen:
                continue
            seen.add(line)
            lines.append(line)
            print(line)

    if not lines:
        print("No context variables.")
    print(_BANNER)
    return lines
