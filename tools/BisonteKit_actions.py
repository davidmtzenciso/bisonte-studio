"""BisonteKit actions - re-read and exec'd on every command, so edits here
take effect without restarting Live.

`run(command)` returns whatever should land in _result.json.
Names provided by the caller: Live, log, os, json, BASE.
"""

VERSION = 4


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
    if name == "inputs":
        return inputs(command)
    if name == "rec":
        return rec(command)
    if name == "levels":
        return levels(command)
    if name == "track_set":
        return track_set(command)
    if name == "fire":
        return fire(command)
    if name == "transport":
        return transport(command)
    if name == "clips":
        return clips(command)
    if name == "delete_clip":
        return delete_clip(command)
    if name == "midi_inputs":
        return midi_inputs(command)
    if name == "clip_notes":
        return clip_notes(command)
    if name == "midi_track":
        return midi_track(command)
    if name == "surfaces":
        return surfaces(command)
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


def _routing_names(items):
    out = []
    for item in items:
        try:
            out.append(item.display_name)
        except Exception:
            continue
    return out


def inputs(command):
    """Report the input routings Live currently offers, per audio track.

    The lists come from Live's active audio input device, so they only
    show MR18 channels once the mixer's USB cable is in AND Live's audio
    input device is set to it. Choosing that device is NOT scriptable --
    it is an application preference, not part of the LOM -- so it stays a
    manual step in Live's Settings -> Audio.
    """
    song = song_of()
    tracks = []
    for track in song.tracks:
        try:
            if not track.has_audio_input:
                continue
        except Exception:
            continue
        row = {"name": track.name}
        try:
            row["type"] = track.input_routing_type.display_name
            row["channel"] = track.input_routing_channel.display_name
            row["available_types"] = _routing_names(
                track.available_input_routing_types)
            row["available_channels"] = _routing_names(
                track.available_input_routing_channels)
        except Exception as e:
            row["error"] = str(e)
        tracks.append(row)
    return {"ok": True, "actions_version": VERSION, "audio_tracks": tracks}


def rec(command):
    """Point an audio track at one hardware input and arm it.

    {"cmd":"rec","name":"Ch2","type":"MR18","channel":"2","arm":true}

    `type` is matched case-insensitively as a substring, because the
    device's spelling varies (MR18 / X-AIR / MR18 USB). `channel` is
    matched exactly first, then as a substring, so "2" cannot silently
    land on "12". Monitoring is left at Live's default on purpose: the
    user is usually wearing the headphones.
    """
    song = song_of()
    title = command.get("name") or "Rec"
    want_type = (command.get("type") or "").lower()
    want_chan = str(command.get("channel") or "")

    track = track_named(title)
    created = False
    if track is None:
        song.create_audio_track(-1)
        track = song.tracks[len(song.tracks) - 1]
        try:
            track.name = title
        except Exception:
            pass
        created = True

    chose = {}
    missed = {}

    if want_type:
        hit = None
        for t in track.available_input_routing_types:
            if want_type in t.display_name.lower():
                hit = t
                break
        if hit is None:
            missed["type"] = _routing_names(
                track.available_input_routing_types)
        else:
            track.input_routing_type = hit
            chose["type"] = hit.display_name

    if want_chan:
        avail = list(track.available_input_routing_channels)
        hit = None
        for c in avail:                      # exact first
            if c.display_name.strip().lower() == want_chan.strip().lower():
                hit = c
                break
        if hit is None:                      # then substring
            for c in avail:
                if want_chan.lower() in c.display_name.lower():
                    hit = c
                    break
        if hit is None:
            missed["channel"] = _routing_names(avail)
        else:
            track.input_routing_channel = hit
            chose["channel"] = hit.display_name

    armed = None
    if command.get("arm"):
        try:
            track.arm = 1
            armed = bool(track.arm)
        except Exception as e:
            missed["arm"] = str(e)

    return {"ok": not missed, "actions_version": VERSION,
            "track": title, "created": created, "chose": chose,
            "armed": armed, "unmatched_wanted": missed,
            "now": {"type": track.input_routing_type.display_name,
                    "channel": track.input_routing_channel.display_name}}


def levels(command):
    """One instantaneous meter + monitoring reading per audio track.

    Deliberately NOT a loop: actions run on Live's own thread, so
    sleeping here would stall the application. Call it repeatedly from
    outside to watch a level over time.

    current_monitoring_state: 0 = In, 1 = Auto, 2 = Off. An armed track
    on Auto IS monitoring its input, which for a live mic means it is
    already in the monitor path.
    """
    rows = []
    for track in song_of().tracks:
        try:
            if not track.has_audio_input:
                continue
        except Exception:
            continue
        row = {"name": track.name}
        for attr in ("arm", "current_monitoring_state",
                     "input_meter_level", "output_meter_level"):
            try:
                row[attr] = getattr(track, attr)
            except Exception:
                row[attr] = None
        rows.append(row)
    return {"ok": True, "actions_version": VERSION, "tracks": rows}


def track_set(command):
    """Set arm / monitoring / volume on one track by name.

    {"cmd":"track_set","name":"Ch2 Mic","monitor":0,"volume":0.0}

    monitor: 0 = In, 1 = Auto, 2 = Off.

    Volume is applied BEFORE monitoring so a track can be silenced first
    and only then opened up - the input meter is pre-fader, so signal can
    be verified without putting a live mic into somebody's headphones.
    """
    track = track_named(command.get("name", ""))
    if track is None:
        return {"ok": False, "error": "no track named %r"
                % command.get("name")}
    done = {}
    if "volume" in command:
        try:
            track.mixer_device.volume.value = float(command["volume"])
            done["volume"] = track.mixer_device.volume.value
        except Exception as e:
            done["volume_error"] = str(e)
    if "monitor" in command:
        try:
            track.current_monitoring_state = int(command["monitor"])
            done["monitor"] = track.current_monitoring_state
        except Exception as e:
            done["monitor_error"] = str(e)
    if "arm" in command:
        try:
            track.arm = 1 if command["arm"] else 0
            done["arm"] = bool(track.arm)
        except Exception as e:
            done["arm_error"] = str(e)
    return {"ok": True, "actions_version": VERSION,
            "track": track.name, "applied": done}


def fire(command):
    """Fire a clip slot. On an armed audio track with an EMPTY slot this
    starts recording into it; Session view keeps it contained to this
    track rather than rolling the whole arrangement.

    {"cmd":"fire","track":"Ch2 Mic","slot":0}
    """
    track = track_named(command.get("track", ""))
    if track is None:
        return {"ok": False, "error": "no track named %r"
                % command.get("track")}
    idx = int(command.get("slot", 0))
    try:
        slot = track.clip_slots[idx]
    except Exception as e:
        return {"ok": False, "error": "slot %d: %s" % (idx, e)}
    had = slot.has_clip
    slot.fire()
    return {"ok": True, "actions_version": VERSION, "track": track.name,
            "slot": idx, "had_clip_before": had,
            "is_recording": getattr(slot, "is_recording", None)}


def transport(command):
    """Start or stop the transport. {"cmd":"transport","action":"stop"}"""
    song = song_of()
    act = command.get("action", "")
    try:
        if act == "stop":
            song.stop_playing()
        elif act == "play":
            song.start_playing()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "actions_version": VERSION, "action": act,
            "is_playing": song.is_playing}


def clips(command):
    """Report the clips on a track, with length and sample path if audio."""
    track = track_named(command.get("track", ""))
    if track is None:
        return {"ok": False, "error": "no track named %r"
                % command.get("track")}
    out = []
    for i, slot in enumerate(track.clip_slots):
        if not slot.has_clip:
            continue
        clip = slot.clip
        row = {"slot": i, "name": clip.name, "length": clip.length,
               "is_recording": getattr(slot, "is_recording", None)}
        for attr in ("file_path", "sample_length"):
            try:
                row[attr] = getattr(clip, attr)
            except Exception:
                pass
        out.append(row)
    return {"ok": True, "actions_version": VERSION,
            "track": track.name, "clips": out}


def delete_clip(command):
    """Remove a clip from a slot. Does NOT delete the recorded sample on
    disk - Live keeps that in the project's Samples/Recorded folder, and
    throwing away someone's audio is not this command's business.

    {"cmd":"delete_clip","track":"Ch2 Mic","slot":0}
    """
    track = track_named(command.get("track", ""))
    if track is None:
        return {"ok": False, "error": "no track named %r"
                % command.get("track")}
    idx = int(command.get("slot", 0))
    try:
        slot = track.clip_slots[idx]
    except Exception as e:
        return {"ok": False, "error": "slot %d: %s" % (idx, e)}
    if not slot.has_clip:
        return {"ok": True, "actions_version": VERSION,
                "track": track.name, "slot": idx, "note": "already empty"}
    name = slot.clip.name
    slot.delete_clip()
    return {"ok": True, "actions_version": VERSION, "track": track.name,
            "slot": idx, "deleted": name, "has_clip": slot.has_clip}


def midi_inputs(command):
    """Report MIDI tracks' input routing plus what Live currently offers.

    Like inputs() but for has_midi_input tracks. The available types come
    from Live's MIDI port configuration, so a controller only appears
    here once its Track/Sync/Remote switches are on in Settings -> Link,
    Tempo & MIDI. Those switches are an application preference, not part
    of the LOM, so they stay a manual step.
    """
    tracks = []
    for track in song_of().tracks:
        try:
            if not track.has_midi_input:
                continue
        except Exception:
            continue
        row = {"name": track.name}
        for attr in ("arm", "current_monitoring_state"):
            try:
                row[attr] = getattr(track, attr)
            except Exception:
                row[attr] = None
        try:
            row["type"] = track.input_routing_type.display_name
            row["channel"] = track.input_routing_channel.display_name
            row["available_types"] = _routing_names(
                track.available_input_routing_types)
            row["available_channels"] = _routing_names(
                track.available_input_routing_channels)
        except Exception as e:
            row["error"] = str(e)
        tracks.append(row)
    return {"ok": True, "actions_version": VERSION,
            "midi_tracks": tracks, "track_count": len(song_of().tracks)}


def clip_notes(command):
    """Count and sample the notes in a MIDI clip - proof that a
    controller actually reached Live, not just that a clip exists.

    {"cmd":"clip_notes","track":"1-MIDI","slot":0}
    """
    track = track_named(command.get("track", ""))
    if track is None:
        return {"ok": False, "error": "no track named %r"
                % command.get("track")}
    idx = int(command.get("slot", 0))
    try:
        slot = track.clip_slots[idx]
    except Exception as e:
        return {"ok": False, "error": "slot %d: %s" % (idx, e)}
    if not slot.has_clip:
        return {"ok": True, "actions_version": VERSION,
                "track": track.name, "slot": idx, "note": "slot is empty"}
    clip = slot.clip
    out = {"ok": True, "actions_version": VERSION, "track": track.name,
           "slot": idx, "clip": clip.name, "length": clip.length}
    try:
        notes = clip.get_notes_extended(0, 128, 0.0, clip.length)
        out["note_count"] = len(notes)
        out["notes"] = [{"pitch": n.pitch, "start": round(n.start_time, 3),
                         "velocity": n.velocity} for n in notes[:12]]
    except Exception as e:
        out["notes_error"] = str(e)
    return out


def midi_track(command):
    """Create or reuse a MIDI track, point it at one input, arm it.

    {"cmd":"midi_track","name":"T-Ext","type":"External Port","arm":true}

    The audio-side rec() cannot do this: create_midi_track is a separate
    call and a MIDI track has no headamp or channel pair to match. Type
    is matched as a substring of Live's display name.
    """
    song = song_of()
    title = command.get("name") or "MIDI In"
    want = (command.get("type") or "").lower()

    track = track_named(title)
    created = False
    if track is None:
        song.create_midi_track(-1)
        track = song.tracks[len(song.tracks) - 1]
        try:
            track.name = title
        except Exception:
            pass
        created = True

    chose, missed = {}, {}
    if want:
        hit = None
        for t in track.available_input_routing_types:
            if want in t.display_name.lower():
                hit = t
                break
        if hit is None:
            missed["type"] = _routing_names(
                track.available_input_routing_types)
        else:
            track.input_routing_type = hit
            chose["type"] = hit.display_name
    if command.get("arm"):
        try:
            track.arm = 1
        except Exception as e:
            missed["arm"] = str(e)
    return {"ok": not missed, "actions_version": VERSION, "track": title,
            "created": created, "chose": chose, "unmatched": missed,
            "now": track.input_routing_type.display_name,
            "armed": bool(track.arm)}


def surfaces(command):
    """Report the control surfaces Live has instantiated, per slot.

    Shows which slots are OCCUPIED. It does NOT show whether a surface's
    MIDI ports are bound: Live instantiates a selected script with or
    without ports, and BisonteKit itself is proof - it sits in a slot and
    talks over files with no MIDI port at all. Port assignments live in
    Preferences.cfg, which is binary and not readable here, so whether a
    surface can actually reach its hardware has to be read off the pane
    in Settings -> Link, Tempo & MIDI.
    """
    app = Live.Application.get_application()
    rows = []
    try:
        css = app.control_surfaces
    except Exception as e:
        return {"ok": False, "error": "control_surfaces: %s" % e}
    for i, cs in enumerate(css):
        if cs is None:
            rows.append({"slot": i + 1, "surface": None})
            continue
        row = {"slot": i + 1, "surface": type(cs).__name__}
        for attr in ("name", "instance_name", "_suggested_input_port",
                     "_suggested_output_port"):
            try:
                v = getattr(cs, attr)
                row[attr] = str(v)
            except Exception:
                pass
        rows.append(row)
    return {"ok": True, "actions_version": VERSION, "surfaces": rows}
