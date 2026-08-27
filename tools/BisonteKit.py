# BisonteKit - a command channel into Ableton Live.
#
# The Live Object Model cannot load devices or samples; only a MIDI Remote
# Script gets Live.Browser, which is how Push loads sounds. This script polls
# a JSON command file and acts on it, so anything outside Live - a shell, a
# build script - can drive the browser.
#
#   echo '{"cmd":"probe"}'                   > ~/Music/Ableton/Move Kits/_command.json
#   echo '{"cmd":"build","kit":"<kit.json>"}' > ~/Music/Ableton/Move Kits/_command.json
#
# Results and errors land in _result.json and _bisontekit.log next to it.
# Enable it under Preferences > Link/Tempo/MIDI as a Control Surface; Live
# only notices a new script at startup.

import json
import os
import time
import traceback

import Live

BASE = os.path.join(os.path.expanduser("~"), "Music", "Ableton", "Move Kits")
CMD = os.path.join(BASE, "_command.json")
RESULT = os.path.join(BASE, "_result.json")
LOG = os.path.join(BASE, "_bisontekit.log")

POLL_TICKS = 10          # update_display runs ~10x a second, so poll ~1s


def log(msg):
    try:
        os.makedirs(BASE, exist_ok=True)
        with open(LOG, "a") as f:
            f.write("%s  %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def create_instance(c_instance):
    return BisonteKit(c_instance)


def walk(item, want, depth=0, limit=6):
    """Depth-first search of the browser tree for a child called `want`."""
    try:
        children = list(item.children)
    except Exception:
        return None
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


def children_of(item):
    try:
        return list(item.children)
    except Exception:
        return []


class BisonteKit(object):
    """Live duck-types this object; every method below is one it may call."""

    def __init__(self, c_instance):
        self._c_instance = c_instance
        self._tick = 0
        log("loaded - Live %s"
            % Live.Application.get_application().get_version_string())

    # ---- the interface Live expects ------------------------------------
    def disconnect(self):
        log("disconnected")

    def connect_script_instances(self, instances):
        pass

    def can_lock_to_devices(self):
        return False

    def suggest_input_port(self):
        return ""

    def suggest_output_port(self):
        return ""

    def suggest_map_mode(self, cc_no, channel):
        return Live.MidiMap.MapMode.absolute

    def request_rebuild_midi_map(self):
        pass

    def build_midi_map(self, midi_map_handle):
        pass

    def refresh_state(self):
        pass

    def receive_midi(self, midi_bytes):
        pass

    def update_display(self):
        self._tick += 1
        if self._tick % POLL_TICKS:
            return
        if not os.path.exists(CMD):
            return
        try:
            with open(CMD) as f:
                command = json.load(f)
        except Exception as e:
            log("unreadable command: %s" % e)
            self._clear()
            return
        self._clear()
        self._dispatch(command)

    # ---- plumbing -------------------------------------------------------
    def _clear(self):
        try:
            os.remove(CMD)
        except OSError:
            pass

    def _write(self, payload):
        try:
            with open(RESULT, "w") as f:
                json.dump(payload, f, indent=1)
        except Exception as e:
            log("could not write result: %s" % e)

    def _dispatch(self, command):
        name = command.get("cmd", "")
        log("cmd %s" % name)
        try:
            if name == "probe":
                self._write(self._probe())
            elif name == "build":
                self._write(self._build(command))
            else:
                self._write({"ok": False, "error": "unknown cmd %r" % name})
        except Exception:
            tb = traceback.format_exc()
            log(tb)
            self._write({"ok": False, "error": tb})

    # ---- commands -------------------------------------------------------
    def _probe(self):
        """Report the browser API surface, so the build step can stop guessing."""
        browser = Live.Application.get_application().browser
        out = {"ok": True, "browser_attrs": sorted(dir(browser)), "roots": {}}
        for attr in ("instruments", "drums", "sounds", "samples", "user_library",
                     "packs", "current_project", "user_folders", "audio_effects"):
            root = getattr(browser, attr, None)
            if root is None:
                continue
            if isinstance(root, (list, tuple)):
                out["roots"][attr] = [getattr(i, "name", "?") for i in root][:40]
                continue
            out["roots"][attr] = [getattr(c, "name", "?") for c in children_of(root)][:40]

        sample = None
        for c in children_of(getattr(browser, "instruments", None) or []):
            sample = c
            break
        if sample is not None:
            out["item_attrs"] = sorted(dir(sample))
            out["item_example"] = {"name": sample.name,
                                   "is_folder": getattr(sample, "is_folder", None),
                                   "is_loadable": getattr(sample, "is_loadable", None),
                                   "uri": getattr(sample, "uri", None)}
        song = Live.Application.get_application().get_document()
        out["song"] = {"tracks": len(song.tracks),
                       "selected": song.view.selected_track.name}
        return out

    def _build(self, command):
        """Create a MIDI track, load a Drum Rack, and load one sample per pad.

        The kit.json is pack-picker's: {"kit": name, "pads": [{note, role,
        file}, ...]}. Samples are matched by filename in the browser, so the
        staged folder has to live somewhere the browser can see - inside the
        User Library.
        """
        app = Live.Application.get_application()
        browser = app.browser
        song = app.get_document()

        with open(command["kit"]) as f:
            kit = json.load(f)
        pads = [p for p in kit.get("pads", []) if p.get("file")]
        if not pads:
            return {"ok": False, "error": "kit has no pads with files"}

        folder = walk(browser.user_library, command.get("folder", kit["kit"]))
        if folder is None:
            return {"ok": False,
                    "error": "no folder %r under User Library - stage the kit there"
                             % command.get("folder", kit["kit"])}
        by_name = {}
        for child in children_of(folder):
            by_name[child.name] = child
        log("browser folder %r has %d items" % (folder.name, len(by_name)))

        song.create_midi_track(-1)
        track = song.tracks[len(song.tracks) - 1]
        song.view.selected_track = track
        track.name = kit.get("kit", "Kit")

        rack_item = walk(browser.instruments, "Drum Rack")
        if rack_item is None:
            return {"ok": False, "error": "Drum Rack not found in browser.instruments"}
        browser.load_item(rack_item)

        if not track.devices:
            return {"ok": False, "error": "Drum Rack did not load onto the track"}
        rack = track.devices[0]

        placed, missing = [], []
        for pad in pads:
            item = by_name.get(pad["file"])
            if item is None:
                stem = os.path.splitext(pad["file"])[0]
                item = by_name.get(stem)
            if item is None:
                missing.append(pad["file"])
                continue
            target = None
            for drum_pad in rack.drum_pads:
                if drum_pad.note == pad["note"]:
                    target = drum_pad
                    break
            if target is None:
                missing.append("no pad %d" % pad["note"])
                continue
            rack.view.selected_drum_pad = target
            browser.load_item(item)
            if pad.get("choke"):
                try:
                    target.chains[0].choke_group = pad["choke"]
                except Exception as e:
                    log("choke %d: %s" % (pad["note"], e))
            placed.append(pad["note"])

        return {"ok": not missing, "track": track.name,
                "placed": placed, "missing": missing,
                "devices": [d.name for d in track.devices]}
