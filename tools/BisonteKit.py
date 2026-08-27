# BisonteKit - a command channel into Ableton Live.
#
# The Live Object Model cannot load devices or samples; only a MIDI Remote
# Script gets Live.Browser, which is how Push loads sounds. This script polls
# a JSON command file and acts on it, so anything outside Live - a shell, a
# build script - can drive the browser.
#
#   echo '{"cmd":"probe"}' > ~/Music/Ableton/"Move Kits"/_command.json
#
# Results land in _result.json, errors in _bisontekit.log, next to it.
#
# The logic lives in actions.py, which is read and exec'd fresh on every
# command. Only this file is imported by Live, so editing actions.py takes
# effect immediately - no restart, no control-surface toggle.

import json
import os
import time
import traceback

import Live

VERSION = 2

HERE = os.path.dirname(os.path.abspath(__file__))
ACTIONS = os.path.join(HERE, "actions.py")

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


class BisonteKit(object):
    """Live duck-types this object; every method below is one it may call."""

    def __init__(self, c_instance):
        self._c_instance = c_instance
        self._tick = 0
        log("loaded v%d - Live %s"
            % (VERSION, Live.Application.get_application().get_version_string()))

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
            self._remove(CMD)
            return
        self._remove(CMD)
        self._dispatch(command)

    # ---- plumbing -------------------------------------------------------
    def _remove(self, path):
        try:
            os.remove(path)
        except OSError:
            pass

    def _write(self, payload):
        try:
            with open(RESULT, "w") as f:
                json.dump(payload, f, indent=1, default=str)
        except Exception as e:
            log("could not write result: %s" % e)

    def _dispatch(self, command):
        log("cmd %s" % command.get("cmd", "?"))
        try:
            namespace = {"Live": Live, "log": log, "os": os, "json": json,
                         "BASE": BASE, "__name__": "bisonte_actions"}
            with open(ACTIONS) as f:
                source = f.read()
            exec(compile(source, ACTIONS, "exec"), namespace)
            self._write(namespace["run"](command))
        except Exception:
            tb = traceback.format_exc()
            log(tb)
            self._write({"ok": False, "error": tb})
