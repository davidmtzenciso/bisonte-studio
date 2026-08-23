// lomctl.js - Live Object Model playground for the "LOM Console" M4L device.
// Max's js object is ES5: use var, no arrow functions, no template literals.
// autowatch reloads this file automatically whenever you save it.

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

// Never build LiveAPI objects at file scope - the device may not be in the
// Live set yet. Build them lazily inside functions, which is why every entry
// point below constructs its own.
function song() { return new LiveAPI("live_set"); }

// ------------------------------------------------------------ entry points

// live.thisdevice bangs this once the device is fully loaded into the set.
function bang() {
    log("[lomctl] loaded");
    info();
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
    song().set("tempo", bpm);
    log("tempo set to", bpm);
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
