"""BisonteKit actions - re-read and exec'd on every command, so edits here
take effect without restarting Live.

`run(command)` returns whatever should land in _result.json.
Names provided by the caller: Live, log, os, json, BASE.
"""

VERSION = 2


def children_of(item):
    try:
        return list(item.children)
    except Exception:
        return []


def walk(item, want, depth=0, limit=6):
    """Depth-first search of a browser subtree for a child named `want`."""
    children = children_of(item)
    for child in children:
        try:
            if child.name == want:
                return child
        except Exception:
            continue
    if depth < limit:
        for child in children:
            try:
                if child.is_folder:
                    hit = walk(child, want, depth + 1, limit)
                    if hit is not None:
                        return hit
            except Exception:
                continue
    return None


def find_device(browser, name):
    """Drum Rack lives under browser.drums, not instruments - check both."""
    for root in (browser.drums, browser.instruments, browser.sounds):
        hit = walk(root, name, limit=2)
        if hit is not None and getattr(hit, "is_loadable", False):
            return hit
    return None


def run(command):
    name = command.get("cmd", "")
    if name == "probe":
        return probe(command)
    if name == "build":
        return build(command)
    if name == "ping":
        return {"ok": True, "actions_version": VERSION}
    return {"ok": False, "error": "unknown cmd %r" % name}


def probe(command):
    browser = Live.Application.get_application().browser
    out = {"ok": True, "actions_version": VERSION,
           "browser_attrs": sorted(a for a in dir(browser) if not a.startswith("_")),
           "roots": {}}
    for attr in ("instruments", "drums", "sounds", "samples", "user_library",
                 "packs", "current_project", "user_folders"):
        root = getattr(browser, attr, None)
        if root is None:
            continue
        out["roots"][attr] = [getattr(c, "name", "?") for c in children_of(root)][:40]
    song = Live.Application.get_application().get_document()
    out["song"] = {"tracks": [t.name for t in song.tracks],
                   "selected": song.view.selected_track.name}
    return out


def build(command):
    """Create a MIDI track, load a Drum Rack, load one sample per pad."""
    app = Live.Application.get_application()
    browser = app.browser
    song = app.get_document()

    with open(command["kit"]) as f:
        kit = json.load(f)
    pads = [p for p in kit.get("pads", []) if p.get("file")]
    if not pads:
        return {"ok": False, "error": "kit has no pads with files"}

    # The staged folder sits in the User Library so the browser can see it.
    folder = None
    for candidate in (command.get("folder"), kit["kit"] + " (stage)", kit["kit"]):
        if candidate:
            folder = walk(browser.user_library, candidate)
            if folder is not None:
                break
    if folder is None:
        return {"ok": False, "error": "no staged folder for %r under User Library"
                                      % kit["kit"]}
    by_name = {}
    for child in children_of(folder):
        by_name[child.name] = child
        by_name[os.path.splitext(child.name)[0]] = child
    log("browser folder %r -> %d items" % (folder.name, len(children_of(folder))))

    rack_item = find_device(browser, "Drum Rack")
    if rack_item is None:
        return {"ok": False, "error": "Drum Rack not found in the browser"}

    song.create_midi_track(-1)
    track = song.tracks[len(song.tracks) - 1]
    song.view.selected_track = track
    try:
        track.name = kit.get("kit", "Kit")
    except Exception:
        pass
    browser.load_item(rack_item)

    if not len(track.devices):
        return {"ok": False, "error": "Drum Rack did not load onto the new track"}
    rack = track.devices[0]
    pad_by_note = {}
    for drum_pad in rack.drum_pads:
        pad_by_note[drum_pad.note] = drum_pad

    placed, missing, how = [], [], {}
    for pad in pads:
        item = by_name.get(pad["file"]) or by_name.get(
            os.path.splitext(pad["file"])[0])
        target = pad_by_note.get(pad["note"])
        if item is None:
            missing.append({"note": pad["note"], "why": "sample not in browser",
                            "file": pad["file"]})
            continue
        if target is None:
            missing.append({"note": pad["note"], "why": "no such drum pad"})
            continue

        # Selecting the pad is the documented way; hotswap is the fallback
        # when a load lands nowhere.
        rack.view.selected_drum_pad = target
        song.view.select_device(rack)
        browser.load_item(item)
        route = "selected_drum_pad"

        if not len(target.chains):
            try:
                browser.hotswap_target = target
                browser.load_item(item)
                browser.hotswap_target = None
                route = "hotswap"
            except Exception as e:
                log("hotswap %d: %s" % (pad["note"], e))

        if not len(target.chains):
            missing.append({"note": pad["note"], "why": "load produced no chain",
                            "file": pad["file"]})
            continue

        how[route] = how.get(route, 0) + 1
        if pad.get("choke"):
            try:
                target.chains[0].choke_group = pad["choke"]
            except Exception as e:
                log("choke %d: %s" % (pad["note"], e))
        try:
            target.name = "%s %s" % (pad["note"], pad["role"])
        except Exception:
            pass
        placed.append(pad["note"])

    return {"ok": not missing, "actions_version": VERSION, "track": track.name,
            "placed": placed, "missing": missing, "loaded_via": how,
            "devices": [d.name for d in track.devices],
            "cells": [(p.note, p.chains[0].devices[0].name)
                      for p in rack.drum_pads
                      if len(p.chains) and len(p.chains[0].devices)][:20]}
