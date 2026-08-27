"""BisonteKit actions - re-read and exec'd on every command, so edits here
take effect without restarting Live.

`run(command)` returns whatever should land in _result.json.
Names provided by the caller: Live, log, os, json, BASE.
"""

VERSION = 3


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
    """Drum Rack lives under browser.drums as well as instruments."""
    for root in (browser.drums, browser.instruments, browser.sounds):
        hit = walk(root, name, limit=2)
        if hit is not None and getattr(hit, "is_loadable", False):
            return hit
    return None


def filled(rack):
    """Which pads currently hold a chain, by the note the LOM reports."""
    out = set()
    for pad in rack.drum_pads:
        try:
            if len(pad.chains):
                out.add(pad.note)
        except Exception:
            continue
    return out


def run(command):
    name = command.get("cmd", "")
    if name == "probe":
        return probe(command)
    if name == "build":
        return build(command)
    if name == "cells":
        return cells(command)
    if name == "delete_track":
        return delete_track(command)
    if name == "ping":
        return {"ok": True, "actions_version": VERSION}
    return {"ok": False, "error": "unknown cmd %r" % name}


def song_of():
    return Live.Application.get_application().get_document()


def track_named(name):
    for track in song_of().tracks:
        if track.name == name:
            return track
    return None


def probe(command):
    browser = Live.Application.get_application().browser
    out = {"ok": True, "actions_version": VERSION,
           "browser_attrs": sorted(a for a in dir(browser) if not a.startswith("_")),
           "roots": {}}
    for attr in ("instruments", "drums", "sounds", "samples", "user_library",
                 "packs", "current_project", "user_folders"):
        root = getattr(browser, attr, None)
        if root is not None:
            out["roots"][attr] = [getattr(c, "name", "?")
                                  for c in children_of(root)][:40]
    song = song_of()
    out["song"] = {"tracks": [t.name for t in song.tracks],
                   "selected": song.view.selected_track.name}
    return out


def cells(command):
    """What the LOM thinks is on each pad - compare against the saved .als,
    which is the only ground truth for a pad's real receiving note."""
    track = track_named(command["track"]) if command.get("track") \
        else song_of().view.selected_track
    if track is None:
        return {"ok": False, "error": "no such track"}
    if not len(track.devices):
        return {"ok": False, "error": "track has no devices"}
    rack = track.devices[0]
    rows = []
    for pad in rack.drum_pads:
        try:
            if not len(pad.chains):
                continue
            chain = pad.chains[0]
            device = chain.devices[0].name if len(chain.devices) else "-"
            rows.append({"note": pad.note, "name": pad.name, "device": device,
                         "choke": chain.choke_group})
        except Exception:
            continue
    return {"ok": True, "actions_version": VERSION, "track": track.name,
            "device": rack.name, "cells": rows}


def delete_track(command):
    song = song_of()
    wanted = command.get("track")
    removed = []
    for track in list(song.tracks):
        if track.name == wanted:
            song.delete_track(list(song.tracks).index(track))
            removed.append(wanted)
    return {"ok": bool(removed), "removed": removed,
            "tracks": [t.name for t in song.tracks]}


def build(command):
    """Create a MIDI track, load a Drum Rack, put one sample on each pad.

    Targeting is via browser.hotswap_target: setting rack.view.selected_drum_pad
    and calling load_item put every sample on note 128-N instead, mirroring the
    whole kit. Hotswap addresses a pad directly.
    """
    app = Live.Application.get_application()
    browser = app.browser
    song = song_of()

    with open(command["kit"]) as f:
        kit = json.load(f)
    pads = [p for p in kit.get("pads", []) if p.get("file")]
    if not pads:
        return {"ok": False, "error": "kit has no pads with files"}
    title = command.get("name") or kit.get("kit", "Kit")

    folder = None
    for candidate in (command.get("folder"), kit["kit"] + " (stage)", kit["kit"]):
        if candidate:
            folder = walk(browser.user_library, candidate)
            if folder is not None:
                break
    if folder is None:
        return {"ok": False,
                "error": "no staged folder for %r under User Library" % kit["kit"]}
    by_name = {}
    for child in children_of(folder):
        by_name[child.name] = child
        by_name[os.path.splitext(child.name)[0]] = child
    if not by_name:
        return {"ok": False, "error": "staged folder is empty to the browser - "
                                      "Live does not index symlinks, stage copies"}

    rack_item = find_device(browser, "Drum Rack")
    if rack_item is None:
        return {"ok": False, "error": "Drum Rack not found in the browser"}

    # Replace a previous build of the same kit rather than piling up tracks.
    replaced = []
    for track in list(song.tracks):
        if track.name == title:
            song.delete_track(list(song.tracks).index(track))
            replaced.append(title)

    song.create_midi_track(-1)
    track = song.tracks[len(song.tracks) - 1]
    song.view.selected_track = track
    try:
        track.name = title
    except Exception:
        pass
    browser.load_item(rack_item)
    if not len(track.devices):
        return {"ok": False, "error": "Drum Rack did not load onto the new track"}
    rack = track.devices[0]
    pad_by_note = {}
    for pad in rack.drum_pads:
        pad_by_note[pad.note] = pad
    log("build %r - %d staged items, replaced %d track(s)"
        % (title, len(children_of(folder)), len(replaced)))

    placed, missing, routes = [], [], {}
    for pad in pads:
        item = by_name.get(pad["file"]) or by_name.get(
            os.path.splitext(pad["file"])[0])
        target = pad_by_note.get(pad["note"])
        if item is None:
            missing.append({"note": pad["note"], "why": "sample not in browser",
                            "file": pad["file"]})
            continue
        if target is None:
            missing.append({"note": pad["note"], "why": "no drum pad at that note"})
            continue

        before = filled(rack)
        route = "hotswap"
        try:
            browser.hotswap_target = target
            browser.load_item(item)
        except Exception as e:
            log("hotswap %d: %s" % (pad["note"], e))
            route = "selected_drum_pad"
            rack.view.selected_drum_pad = target
            browser.load_item(item)
        finally:
            try:
                browser.hotswap_target = None
            except Exception:
                pass

        landed = sorted(filled(rack) - before)
        if not landed:
            missing.append({"note": pad["note"], "why": "load produced no chain",
                            "file": pad["file"]})
            continue
        routes[route] = routes.get(route, 0) + 1
        if landed != [pad["note"]]:
            missing.append({"note": pad["note"], "why": "landed on %s" % landed,
                            "file": pad["file"]})
            continue

        if pad.get("choke"):
            try:
                target.chains[0].choke_group = pad["choke"]
            except Exception as e:
                log("choke %d: %s" % (pad["note"], e))
        try:
            target.name = "%d %s" % (pad["note"], pad["role"])
        except Exception:
            pass
        placed.append(pad["note"])

    return {"ok": not missing, "actions_version": VERSION, "track": title,
            "replaced": replaced, "placed": placed, "missing": missing,
            "loaded_via": routes,
            "note_range": [min(filled(rack)), max(filled(rack))] if filled(rack) else []}
