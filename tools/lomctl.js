// lomctl.js - Live Object Model playground for the "LOM Console" M4L device.
// Max's js object is ES5: use var, no arrow functions, no template literals.
// autowatch reloads this file automatically whenever you save it.
//
// Commands (buttons, or any message sent to the js object):
//   info · tracks · devices · tempo [bpm] · newclip · watch · unwatch
//   seed [n] · roll [k] · euclid k [n] [rot] [pitch] · help

autowatch = 1;
inlets = 1;
outlets = 1;

// ---------------------------------------------------------------- helpers

function log() {
    var s = "";
    for (var i = 0; i < arguments.length; i++) {
        s += arguments[i] + (i < arguments.length - 1 ? " " : "");
    }
    post(s + "\n");
}

// LiveAPI .get() always returns an array, even for single values.
function get1(obj, prop) {
    var v = obj.get(prop);
    return (v && v.length) ? v[0] : v;
}

// Message args can arrive as symbols depending on the sender; coerce.
function num(v, dflt) {
    if (v === undefined || v === null || v === "") { return dflt; }
    var f = parseFloat(v);
    return isNaN(f) ? dflt : f;
}

// Never build LiveAPI objects at file scope - the device may not be in the
// Live set yet. Build them lazily inside functions, which is why every entry
// point below constructs its own.
function song() { return new LiveAPI("live_set"); }

// ------------------------------------------------------------ entry points

// live.thisdevice bangs this once the device is fully loaded into the set.
function bang() {
    log("[lomctl] loaded - commands:", cmdList());
}

function help() {
    log("commands:", cmdList());
    log("euclid k [n=16] [rot=0] [pitch=36] - Euclidean clip in the selected empty slot");
    log("seed [n] - set/show the RNG seed  ·  roll [k=5] - print k random values");
}

function info() {
    var s = song();
    var app = new LiveAPI("live_app");
    log("---------------- Live Set ----------------");
    log("Live version :", app.call("get_version_string"));
    log("tempo        :", get1(s, "tempo"));
    log("signature    :", get1(s, "signature_numerator") + "/" + get1(s, "signature_denominator"));
    log("playing      :", get1(s, "is_playing"));
    log("song time    :", get1(s, "current_song_time"));
    log("tracks       :", s.getcount("tracks"));
    log("return tracks:", s.getcount("return_tracks"));
    log("scenes       :", s.getcount("scenes"));
}

function tracks() {
    var s = song();
    var n = s.getcount("tracks");
    log("---------------- Tracks (" + n + ") ----------------");
    for (var i = 0; i < n; i++) {
        var t = new LiveAPI("live_set tracks " + i);
        var vol = new LiveAPI("live_set tracks " + i + " mixer_device volume");
        log(i,
            "|", get1(t, "name"),
            "| midi:", get1(t, "has_midi_input"),
            "| vol:", get1(vol, "value").toFixed(3),
            "| mute:", get1(t, "mute"),
            "| solo:", get1(t, "solo"),
            "| devices:", t.getcount("devices"));
    }
}

// Walks the devices (and rack chains) of whichever track is selected in Live.
function devices() {
    var t = new LiveAPI("live_set view selected_track");
    log("---------------- Devices on '" + get1(t, "name") + "' ----------------");
    var n = t.getcount("devices");
    if (n === 0) { log("(none)"); return; }
    for (var i = 0; i < n; i++) {
        var base = t.unquotedpath + " devices " + i;
        dumpDevice(base, i + "", "");
    }
}

function dumpDevice(path, label, indent) {
    var dev = new LiveAPI(path);
    log(indent + label, "|", get1(dev, "name"),
        "| class:", get1(dev, "class_name"),
        "| params:", dev.getcount("parameters"));
    var np = dev.getcount("parameters");
    for (var p = 0; p < np; p++) {
        var par = new LiveAPI(path + " parameters " + p);
        log(indent + "    [" + p + "]", get1(par, "name"),
            "=", get1(par, "value"),
            "(" + get1(par, "min") + ".." + get1(par, "max") + ")");
    }
    // Racks nest: chains -> devices -> chains ...
    var nc = dev.getcount("chains");
    for (var c = 0; c < nc; c++) {
        var chain = new LiveAPI(path + " chains " + c);
        log(indent + "  chain " + c + ":", get1(chain, "name"));
        var nd = chain.getcount("devices");
        for (var dd = 0; dd < nd; dd++) {
            dumpDevice(path + " chains " + c + " devices " + dd, dd + "", indent + "    ");
        }
    }
}

// Writing to the LOM: "tempo 128" from a message box lands here.
function tempo(bpm) {
    if (bpm === undefined) { log("tempo is", get1(song(), "tempo")); return; }
    song().set("tempo", num(bpm, 120));
    log("tempo set to", num(bpm, 120));
}

// Creating content: needs a MIDI track with an EMPTY clip slot selected.
function newclip() {
    var slot = new LiveAPI("live_set view highlighted_clip_slot");
    if (!slot.id || slot.id === 0) { log("no clip slot selected"); return; }
    if (get1(slot, "has_clip")) { log("slot already has a clip - pick an empty one"); return; }

    var beats = 4;
    slot.call("create_clip", beats);

    var clip = new LiveAPI("live_set view highlighted_clip_slot clip");
    clip.set("name", "made by lomctl");

    // Legacy note API - still the most JS-friendly way to write notes.
    // note <pitch> <start_beat> <duration> <velocity> <muted>
    var pitches = [60, 63, 67, 70];
    clip.call("set_notes");
    clip.call("notes", pitches.length);
    for (var i = 0; i < pitches.length; i++) {
        clip.call("note", pitches[i], i, 0.9, 100, 0);
    }
    clip.call("done");
    log("created a " + beats + "-beat clip with " + pitches.length + " notes");
}

// ------------------------------------------------------------- randomness

// 32-bit LCG (Numerical Recipes constants). ES5 has no Math.imul, but
// 1664525 * (2^32-1) stays below 2^53, so plain doubles remain exact.
// Same seed -> same stream -> any generated clip can be regenerated.
var _rngSeed = 1;
var _rngState = 1;

function seed(n) {
    if (n === undefined) { log("seed is", _rngSeed, "(state " + _rngState + ")"); return; }
    var v = num(n, NaN);
    if (isNaN(v)) { log("usage: seed <integer>"); return; }
    v = Math.floor(Math.abs(v)) % 4294967296;
    _rngSeed = v;
    _rngState = v;
    log("seed set to", v);
}

function rnd() {
    _rngState = (_rngState * 1664525 + 1013904223) % 4294967296;
    return _rngState / 4294967296;
}

// Determinism check: "seed 7" then "roll 3" prints the same three values
// every time, on any machine.
function roll(k) {
    k = Math.max(1, Math.floor(num(k, 5)));
    var out = [];
    for (var i = 0; i < k; i++) { out.push(rnd().toFixed(6)); }
    log("roll:", out.join(" "));
}

// ------------------------------------------------------------- generators

// Live 11+ dictionary API, falling back to the legacy note list that
// newclip() uses if this Live build rejects it.
// notes: [{pitch, start_time, duration, velocity}, ...]
function writeNotes(clip, notes) {
    try {
        clip.call("add_new_notes", { notes: notes });
        return "add_new_notes";
    } catch (e) {
        clip.call("set_notes");
        clip.call("notes", notes.length);
        for (var i = 0; i < notes.length; i++) {
            var nt = notes[i];
            clip.call("note", nt.pitch, nt.start_time, nt.duration, nt.velocity, 0);
        }
        clip.call("done");
        return "legacy";
    }
}

// euclid k [n=16] [rot=0] [pitch=36]
// Euclidean rhythm E(k,n) rotated by rot, one pitch, 16th-note steps, into
// the selected EMPTY clip slot. Step i of the base pattern is a hit iff
// (i*k) mod n < k; rot shifts the pattern later by rot steps.
// E(3,8) -> x..x..x.    E(5,16) -> x...x..x..x..x..
function euclid(k, n, rot, pitch) {
    k = Math.floor(num(k, NaN));
    n = Math.floor(num(n, 16));
    rot = Math.floor(num(rot, 0));
    pitch = Math.floor(num(pitch, 36));
    if (isNaN(k)) { log("usage: euclid k [n=16] [rot=0] [pitch=36]"); return; }
    if (n < 1 || n > 128) { log("euclid: n must be 1..128"); return; }
    if (k < 0 || k > n) { log("euclid: k must be 0..n"); return; }
    if (pitch < 0 || pitch > 127) { log("euclid: pitch must be 0..127"); return; }
    rot = ((rot % n) + n) % n;

    var slot = new LiveAPI("live_set view highlighted_clip_slot");
    if (!slot.id || slot.id === 0) { log("euclid: no clip slot selected"); return; }
    if (get1(slot, "has_clip")) { log("euclid: slot has a clip - pick an empty one"); return; }

    var STEP = 0.25;                       // 16th notes, in beats
    var notes = [];
    var pattern = "";
    for (var i = 0; i < n; i++) {
        var base = (((i - rot) % n) + n) % n;
        var hit = ((base * k) % n) < k;
        pattern += hit ? "x" : ".";
        if (hit) {
            notes.push({
                pitch: pitch,
                start_time: i * STEP,
                duration: STEP * 0.5,
                velocity: (i % 4 === 0) ? 110 : 96   // light accent on the quarters
            });
        }
    }

    slot.call("create_clip", n * STEP);
    var clip = new LiveAPI("live_set view highlighted_clip_slot clip");
    var how = "empty";
    if (notes.length > 0) { how = writeNotes(clip, notes); }
    var name = "~euclid " + k + " " + n + " " + rot + " p" + pitch;
    clip.set("name", name);
    log("euclid E(" + k + "," + n + ") rot " + rot + " -> " + pattern);
    log("created '" + name + "' -", notes.length, "notes,", (n * STEP), "beats, via", how);
}

// ------------------------------------------------------------ dispatcher

// Named functions above catch "euclid 5 16" style messages directly. This
// table backs `help` and catches anything sent as one whole-line symbol.
// Function declarations hoist, so referring to them here is safe.
var COMMANDS = {
    help: help, info: info, tracks: tracks, devices: devices,
    tempo: tempo, newclip: newclip, watch: watch, unwatch: unwatch,
    seed: seed, roll: roll, euclid: euclid
};

function cmdList() {
    var names = [];
    for (var k in COMMANDS) { names.push(k); }
    return names.join(" ");
}

function anything() {
    var toks;
    if (String(messagename).indexOf(" ") >= 0) {
        toks = String(messagename).replace(/^\s+|\s+$/g, "").split(/\s+/);
        toks = toks.concat(arrayfromargs(arguments));
    } else {
        toks = [String(messagename)].concat(arrayfromargs(arguments));
    }
    var fn = COMMANDS[toks[0]];
    if (!fn) { log("unknown command '" + toks[0] + "' - try:", cmdList()); return; }
    fn.apply(this, toks.slice(1));
}

// ------------------------------------------------------------- observation

var observers = {};

function watch() {
    unwatch();

    observers.tempo = new LiveAPI(onTempo, "live_set");
    observers.tempo.property = "tempo";

    observers.playing = new LiveAPI(onPlaying, "live_set");
    observers.playing.property = "is_playing";

    observers.selection = new LiveAPI(onSelectedTrack, "live_set view");
    observers.selection.property = "selected_track";

    log("[lomctl] watching tempo, transport and track selection");
}

function unwatch() {
    for (var k in observers) {
        if (observers[k]) { observers[k].property = ""; observers[k] = null; }
    }
    observers = {};
}

// Observer callbacks receive ["property_name", value...].
function onTempo(args) {
    if (args[0] === "tempo") {
        log("[watch] tempo ->", args[1]);
        outlet(0, "tempo", args[1]);
    }
}

function onPlaying(args) {
    if (args[0] === "is_playing") {
        log("[watch] transport ->", args[1] ? "play" : "stop");
        outlet(0, "playing", args[1]);
    }
}

function onSelectedTrack(args) {
    if (args[0] === "selected_track") {
        var t = new LiveAPI("live_set view selected_track");
        log("[watch] selected track ->", get1(t, "name"));
        outlet(0, "selected", get1(t, "name"));
    }
}

// Max calls this when the device is removed or the file is reloaded.
function notifydeleted() {
    unwatch();
}
