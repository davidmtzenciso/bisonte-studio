#!/usr/bin/env python3
"""Build 16-pad Move drum kits from what this machine actually has.

    python3 pack-picker.py scan [--force]        # index audio, plain vs protected
    python3 pack-picker.py roles                 # what is available per pad role
    python3 pack-picker.py stage "Club Kit" --seed 7
    python3 pack-picker.py build "Club Kit" --from ~/Music/Ableton/"Move Sets"
    python3 pack-picker.py push  "Club Kit"
    python3 pack-picker.py preset "Club Kit.ablpresetbundle"

Two paths, because Live Pack samples are encrypted:

  packs  -> almost every .aif in a Factory Pack is AIFF-C with Ableton's 'able'
            compression. Only Live can decode it, so it can never be uploaded
            as a sample. `stage` picks 16, symlinks them in pad order, and you
            drag them into a Drum Rack in Live and File > Export Preset. Live
            decodes and embeds the audio; `preset` uploads the resulting
            .ablpresetbundle to Move, which is the officially supported route.

  audio  -> anything plain PCM (your renders, Move recordings, your own
            samples) goes straight on with `build` + `push`, converted to
            44.1 kHz by afconvert when needed.

Same seed + same index = same kit, either way.
"""

import argparse, json, os, random, re, shutil, struct, subprocess, sys, urllib.parse

PACKS = os.environ.get(
    "BISONTE_PACKS", "/Volumes/Bisonte/Music Project/Ableton/Factory Packs")
# Kits live inside the User Library so Live's browser can see them - the
# BisonteKit remote script loads samples by walking browser.user_library.
KITS = os.path.expanduser(
    os.environ.get("BISONTE_KITS", "~/Music/Ableton/User Library/Move Kits"))
CACHE = os.path.expanduser("~/.cache/bisonte/pack-index.json")

MOVE_RATE = 44100
MOVE_MAX_BYTES = 100_000_000          # Allowed-Post-File-Size on Samples/
AUDIO_EXT = (".aif", ".aiff", ".aifc", ".wav", ".wave")

# Pad layout, mirroring the factory "Bisonte Club 1" kit: note 36 is the
# bottom-left pad, ascending left to right then upwards.
PADS = [
    (36, "kick"), (37, "rim"),     (38, "snare"), (39, "clap"),
    (40, "snare"), (41, "tom"),    (42, "hat"),   (43, "tom"),
    (44, "hat"),  (45, "tom"),     (46, "crash"), (47, "perc"),
    (48, "shaker"), (49, "cymbal"), (50, "tambourine"), (51, "perc"),
]
CHOKE = {42: 1, 44: 1, 46: 1}         # hats and crash cut each other off

# Longest a one-shot may be, per role. Only checked for plain audio - a
# protected file's length is unreadable, so its folder has to be trusted.
MAXLEN = {"kick": 2.0, "snare": 2.0, "clap": 2.0, "rim": 1.5, "hat": 2.0,
          "tom": 3.0, "crash": 6.0, "cymbal": 6.0, "shaker": 2.0,
          "tambourine": 2.5, "perc": 3.0}

# First hit wins, so "crash" beats "cymbal" and "rim" beats "snare".
ROLES = [
    ("crash",      ("crash*",)),
    ("rim",        ("rim*", "sidestick*", "side stick*", "cross stick*")),
    ("hat",        ("hihat*", "hi-hat*", "hi hat*", "openhat*", "hat*")),
    ("clap",       ("clap*", "snap*")),
    ("snare",      ("snare*",)),
    ("kick",       ("kick*", "boom*")),
    ("tom",        ("tom*",)),
    ("shaker",     ("shaker*", "maraca*")),
    ("tambourine", ("tamb*",)),
    ("cymbal",     ("cymbal*", "ride*", "splash*", "china*", "gong*")),
    ("perc",       ("percussion*", "perc*", "conga*", "bongo*", "cowbell*",
                    "woodblock*", "clave*", "triangle*", "tabla*", "djembe*",
                    "cajon*", "block*")),
]

# A keyword only counts at the start of a word, so "Bottom" is not a tom and
# "Chat" is not a hat. A trailing * lets it run on into the rest of the word
# ("tamb*" catches Tambourin), otherwise the word has to end there too.
_WORD = {}


def _matches(kw, text):
    rx = _WORD.get(kw)
    if rx is None:
        body = re.escape(kw[:-1]) if kw.endswith("*") else re.escape(kw) + r"(?![a-z])"
        rx = _WORD[kw] = re.compile(r"(?<![a-z])" + body)
    return rx.search(text) is not None


# Not drum one-shots: loops drift, multisamples are one note of an instrument,
# previews are 32 kbps browser thumbnails, IRs are reverb impulses.
EXCLUDE = ("loop", "chord", "multisampled", "/notes/", "/previews/", "/irs/",
           "vocal", "synth", "bass", "piano", "keys", "guitar", "organ",
           "flute", "xylophone", "melodica", "whistle", "drone", "brass",
           "string", "impulse")


def role_of(rel):
    low = "/" + rel.lower().replace(os.sep, "/")
    if any(x in low for x in EXCLUDE):
        return None
    for role, keys in ROLES:
        if any(_matches(k, low) for k in keys):
            return role
    return None


# ----------------------------------------------------------------- headers

def _ext80(b):
    """80-bit IEEE extended float - how AIFF stores its sample rate."""
    exp = struct.unpack(">H", b[:2])[0]
    man = struct.unpack(">Q", b[2:10])[0]
    if exp == 0 and man == 0:
        return 0.0
    sign = -1 if exp & 0x8000 else 1
    return sign * man * 2.0 ** ((exp & 0x7FFF) - 16383 - 63)


def probe(path):
    """Walk the container properly - searching for b'COMM' finds it inside
    compressed data too, which is how encrypted packs pass for real audio.

    Returns (kind, channels, bits, rate, seconds) with kind one of
    'plain' | 'protected' | 'unreadable'.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(12)
            if len(head) < 12 or head[:4] not in (b"FORM", b"RIFF"):
                return ("unreadable", 0, 0, 0, 0.0)

            if head[:4] == b"RIFF":                             # WAV
                buf = head + f.read(65536)
                i, j = buf.find(b"fmt "), buf.find(b"data")
                if i < 0 or j < 0 or len(buf) < i + 24:
                    return ("unreadable", 0, 0, 0, 0.0)
                tag, ch, rate, _, align, bits = struct.unpack("<HHIIHH", buf[i + 8:i + 24])
                if tag not in (1, 3, 0xFFFE):                   # not plain PCM/float
                    return ("protected", ch, bits, rate, 0.0)
                nbytes = struct.unpack("<I", buf[j + 4:j + 8])[0]
                secs = (nbytes / align / rate) if align and rate else 0.0
                return ("plain", ch, bits, rate, secs)

            form, pos = head[8:12], 12                          # AIFF / AIFC
            for _ in range(40):
                f.seek(pos)
                h = f.read(8)
                if len(h) < 8:
                    break
                tag, size = h[:4], struct.unpack(">I", h[4:8])[0]
                if tag == b"COMM":
                    d = f.read(min(size, 40))
                    if len(d) < 18:
                        break
                    ch, frames, bits = struct.unpack(">hIh", d[:8])
                    rate = _ext80(d[8:18])
                    comp = d[18:22].decode("latin1") if len(d) >= 22 else "NONE"
                    secs = frames / rate if rate else 0.0
                    if form == b"AIFF" or comp in ("NONE", "sowt", "twos", "fl32", "FL32"):
                        return ("plain", ch, bits, int(round(rate)), secs)
                    return ("protected", ch, bits, int(round(rate)), secs)
                pos += 8 + size + (size & 1)
    except (OSError, struct.error):
        return ("unreadable", 0, 0, 0, 0.0)
    return ("unreadable", 0, 0, 0, 0.0)


# ------------------------------------------------------------------- index

def index_tree(root, source):
    """Every audio file under root that maps to a pad role."""
    items = []
    if not os.path.isdir(root):
        return items
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if fn.startswith(".") or not fn.lower().endswith(AUDIO_EXT):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            role = role_of(rel)
            if role is None:
                continue
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            kind, ch, bits, rate, secs = probe(full)
            if kind == "unreadable":
                continue
            if kind == "plain":
                if size > MOVE_MAX_BYTES:
                    continue
                if secs <= 0.02 or secs > MAXLEN.get(role, 3.0):
                    continue
            group = rel.split(os.sep)[0] if source == "packs" else os.path.basename(root)
            items.append({"root": root, "rel": rel, "source": source,
                          "pack": group, "role": role, "kind": kind,
                          "ch": ch, "bits": bits, "rate": rate,
                          "secs": round(secs, 3), "size": size})
    return items


def scan(force=False, extra=None, quiet=False):
    if os.path.exists(CACHE) and not force:
        with open(CACHE) as f:
            return json.load(f)
    items = index_tree(PACKS, "packs")
    for root in (extra or []):
        items += index_tree(os.path.expanduser(root), "audio")
    seen, uniq = set(), []
    for i in sorted(items, key=lambda d: (d["source"], d["rel"])):
        key = (i["kind"], os.path.basename(i["rel"]).lower())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(i)
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as f:
        json.dump(uniq, f)
    if not quiet:
        pl = sum(1 for i in uniq if i["kind"] == "plain")
        pr = len(uniq) - pl
        print("indexed %d one-shots: %d plain, %d Live-only (encrypted pack audio)"
              % (len(uniq), pl, pr))
        print("cache: %s" % CACHE)
    return uniq


def roles_report(items):
    print("%-12s %7s %7s   %s" % ("role", "plain", "Live-only", "packs"))
    for role in sorted({p[1] for p in PADS}):
        got = [i for i in items if i["role"] == role]
        pl = [i for i in got if i["kind"] == "plain"]
        pr = [i for i in got if i["kind"] == "protected"]
        print("%-12s %7d %7d   %s"
              % (role, len(pl), len(pr), len({i["pack"] for i in got})))
    print("\nplain = uploadable to Move as samples · Live-only = stage + export a preset")


# ------------------------------------------------------------------ picking

def pick(items, seed, kind, packs=None, spread=True):
    pool = [i for i in items if i["kind"] == kind and (not packs or i["pack"] in packs)]
    rng = random.Random(seed)
    by_role = {}
    for i in pool:
        by_role.setdefault(i["role"], []).append(i)

    chosen, used = [], set()
    for note, role in PADS:
        cands = list(by_role.get(role, []))
        if not cands:
            chosen.append((note, role, None))
            continue
        rng.shuffle(cands)
        if spread:
            fresh = [c for c in cands if c["pack"] not in used]
            cands = fresh + cands if fresh else cands
        item = cands[0]
        by_role[role] = [c for c in by_role[role] if c["rel"] != item["rel"]]
        used.add(item["pack"])
        chosen.append((note, role, item))
    return chosen


def safe(name):
    return re.sub(r"[^A-Za-z0-9 &()#'.-]", "_", name).strip()


def show(chosen):
    print("%-4s %-11s %-40s %-24s %s" % ("pad", "role", "sample", "pack", "audio"))
    for note, role, item in chosen:
        if item is None:
            print("%-4d %-11s -- nothing matched --" % (note, role))
            continue
        detail = ("%d Hz %.2fs" % (item["rate"], item["secs"])
                  if item["kind"] == "plain" else "Live-only")
        print("%-4d %-11s %-40s %-24s %s"
              % (note, role, os.path.basename(item["rel"])[:40], item["pack"][:24], detail))


# ------------------------------------------------------- the Live-only path

STAGE_STEPS = """\
1. In Live, add a **Drum Rack** to a MIDI track and drop a **Drum Sampler**
   on pad C1 (note 36) so the rack is the kind Move understands.
2. Open this folder in Finder, select all 16 files (they sort in pad order)
   and drag them onto pad C1. Live fills 36-51 in order.
3. Set the choke group of pads 42, 44 and 46 to 1 so the hats and crash cut
   each other off.
4. File > Export Preset, save as a **.ablpresetbundle** - Live decodes the
   pack audio and embeds it, downsampled to 44.1 kHz.
5. python3 pack-picker.py preset "<file>.ablpresetbundle"
"""


def stage(name, seed, packs=None, dry=False):
    """Pack samples are Live-only: symlink 16 of them in pad order so they can
    be dragged into a Drum Rack and exported as a preset bundle."""
    items = scan(quiet=True)
    chosen = pick(items, seed, "protected", packs)
    show(chosen)
    if dry:
        return None, []

    outdir = os.path.join(KITS, safe(name) + " (stage)")
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)

    pads = []
    for note, role, item in chosen:
        if item is None:
            pads.append({"note": note, "role": role, "file": None})
            continue
        src = os.path.join(item["root"], item["rel"])
        stem = safe(os.path.splitext(os.path.basename(item["rel"]))[0])[:48]
        link = "%d %s %s%s" % (note, role, stem, os.path.splitext(item["rel"])[1].lower())
        os.symlink(src, os.path.join(outdir, link))
        pads.append({"note": note, "role": role, "file": link, "choke": CHOKE.get(note),
                     "source": item["rel"], "pack": item["pack"], "kind": "protected"})
    return outdir, pads


# --------------------------------------------------------- the samples path

def place(item, note, role, outdir):
    """Copy at 44.1k, convert otherwise. Returns (filename, converted?)."""
    src = os.path.join(item["root"], item["rel"])
    stem = safe(os.path.splitext(os.path.basename(item["rel"]))[0])[:48]
    if item["rate"] == MOVE_RATE:
        ext = os.path.splitext(item["rel"])[1].lower()
        dst = os.path.join(outdir, "%d %s %s%s" % (note, role, stem, ext))
        shutil.copyfile(src, dst)
        return os.path.basename(dst), False
    dst = os.path.join(outdir, "%d %s %s.wav" % (note, role, stem))
    depth = "LEI16" if item["bits"] <= 16 else "LEI24"
    try:
        subprocess.run(["afconvert", src, dst, "-f", "WAVE",
                        "-d", "%s@%d" % (depth, MOVE_RATE), "--src-quality", "127"],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise SystemExit("afconvert refused %s\n  %s"
                         % (item["rel"], e.stderr.decode()[:200]))
    return os.path.basename(dst), True


def build(name, seed, sources, dry=False):
    items = scan(quiet=True)
    if sources:
        items += [i for src in sources for i in index_tree(os.path.expanduser(src), "audio")]
    chosen = pick(items, seed, "plain")
    show(chosen)
    if dry:
        return None, [], 0

    outdir = os.path.join(KITS, safe(name))
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)

    pads, converted = [], 0
    for note, role, item in chosen:
        if item is None:
            pads.append({"note": note, "role": role, "file": None})
            continue
        fname, conv = place(item, note, role, outdir)
        converted += bool(conv)
        pads.append({"note": note, "role": role, "file": fname, "choke": CHOKE.get(note),
                     "source": item["rel"], "pack": item["pack"], "kind": "plain",
                     "rate": item["rate"], "bits": item["bits"], "secs": item["secs"]})
    return outdir, pads, converted


def write_manifest(outdir, name, seed, pads, mode):
    kit = {"kit": name, "seed": seed, "layout": "bisonte-16", "mode": mode,
           "pads": pads}
    with open(os.path.join(outdir, "kit.json"), "w") as f:
        json.dump(kit, f, indent=1)

    cmd = "stage" if mode == "protected" else "build"
    out = ["# %s" % name, "",
           "Built by `pack-picker.py`. Regenerate exactly:", "",
           "    python3 pack-picker.py %s \"%s\" --seed %d" % (cmd, name, seed), "",
           "| pad | role | file | source | choke |",
           "|----:|------|------|--------|:-----:|"]
    for p in pads:
        if not p.get("file"):
            out.append("| %d | %s | — | | |" % (p["note"], p["role"]))
            continue
        out.append("| %d | %s | %s | %s | %s |"
                   % (p["note"], p["role"], p["file"], p.get("pack", ""),
                      p.get("choke") or ""))
    out += ["", "Notes 42, 44 and 46 share choke group 1 — hats and crash cut each",
            "other off, so do not stack them on the same step.", ""]
    if mode == "protected":
        out += ["## These are Live-only files", "",
                "Pack audio is AIFF-C with Ableton's `able` compression: only Live",
                "can decode it, so it cannot be uploaded to Move as samples.", "",
                STAGE_STEPS, ""]
    with open(os.path.join(outdir, "KIT.md"), "w") as f:
        f.write("\n".join(out))


# ----------------------------------------------------------------- shipping

def move_sync():
    """Reuse move-sync.py as a library - same cookie jar, same upload path.

    Import the symlinked runtime copy first: move-sync keeps its session
    cookie next to __file__, and that lives in Move Sets, not in the repo.
    """
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.expanduser("~/Music/Ableton/Move Sets/move-sync.py"),
                 os.path.join(here, "move-sync.py")):
        if os.path.exists(path):
            break
    else:
        sys.exit("move-sync.py not found - expected it in Move Sets or beside this script.")

    spec = importlib.util.spec_from_file_location("move_sync", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not mod.authenticated():
        if not sys.stdin.isatty():
            sys.exit("Not paired with Move, and no terminal to type the code into.\n"
                     "Run `python3 move-sync.py list` by hand once to re-pair.")
        mod.pair()
    return mod


def _refused(e):
    code = getattr(e, "code", None)
    if code in (401, 403, 405, 409, 500, 503):
        sys.exit("Upload refused (HTTP %s). Is Move in Control Live mode? "
                 "Switch it to Standalone and retry." % code)
    raise e


def push(name):
    outdir = os.path.join(KITS, safe(name))
    if not os.path.exists(os.path.join(outdir, "kit.json")):
        sys.exit("No kit at %s - run `build` first (or `stage` + `preset` for packs)."
                 % outdir)
    with open(os.path.join(outdir, "kit.json")) as f:
        kit = json.load(f)
    if kit.get("mode") == "protected":
        sys.exit("That kit is staged pack audio - Live has to export it.\n"
                 "See KIT.md, then: pack-picker.py preset <file>.ablpresetbundle")

    ms = move_sync()
    parts = ["Samples", "Bisonte", urllib.parse.quote(safe(name))]
    ms.ensure_dir(parts)
    sent = 0
    for pad in kit["pads"]:
        if not pad.get("file"):
            continue
        try:
            n = ms.post_file(parts, os.path.join(outdir, pad["file"]))
        except Exception as e:
            _refused(e)
        sent += 1
        print("  put   %-46s %8d bytes" % (pad["file"][:46], n))
    print("\n-> Samples/Bisonte/%s/  (%d samples)" % (safe(name), sent))


def preset(path):
    """Upload a Live-exported .ablpresetbundle into Move's Track Presets."""
    if not path.endswith(".ablpresetbundle"):
        sys.exit("Track Presets only accepts .ablpresetbundle (Live 12.1+: "
                 "File > Export Preset).")
    if not os.path.isfile(path):
        sys.exit("No such file: %s" % path)
    ms = move_sync()
    try:
        n = ms.post_file(["Track Presets"], path)
    except Exception as e:
        _refused(e)
    print("  put   %-46s %8d bytes" % (os.path.basename(path)[:46], n))
    print("\n-> Track Presets/  · on Move: hold a track button, pick the preset.")


# --------------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="index audio, plain vs Live-only")
    s.add_argument("--force", action="store_true")
    s.add_argument("--from", dest="extra", action="append", metavar="DIR",
                   help="also index this folder of plain audio (repeatable)")

    sub.add_parser("roles", help="what is available per pad role")

    st = sub.add_parser("stage", help="pick 16 pack samples to drag into Live")
    st.add_argument("name")
    st.add_argument("--seed", type=int, default=1)
    st.add_argument("--packs", help="comma-separated pack names to limit to")
    st.add_argument("--dry-run", action="store_true")

    b = sub.add_parser("build", help="pick 16 plain samples into a kit folder")
    b.add_argument("name")
    b.add_argument("--seed", type=int, default=1)
    b.add_argument("--from", dest="sources", action="append", metavar="DIR",
                   help="folder of plain audio to pick from (repeatable)")
    b.add_argument("--dry-run", action="store_true")
    b.add_argument("--push", action="store_true")

    p = sub.add_parser("push", help="upload a built kit's samples to Move")
    p.add_argument("name")

    pr = sub.add_parser("preset", help="upload a .ablpresetbundle to Move")
    pr.add_argument("path")
    return ap, ap.parse_args()


def run():
    _, a = main()
    packs = set(a.packs.split(",")) if getattr(a, "packs", None) else None

    if a.cmd == "scan":
        scan(force=a.force, extra=a.extra)
    elif a.cmd == "roles":
        roles_report(scan(quiet=True))
    elif a.cmd == "stage":
        outdir, pads = stage(a.name, a.seed, packs, a.dry_run)
        if a.dry_run:
            print("\ndry run - nothing written")
            return
        write_manifest(outdir, a.name, a.seed, pads, "protected")
        print("\n%d/16 pads staged in %s" % (sum(1 for p in pads if p["file"]), outdir))
        print("\n" + STAGE_STEPS)
    elif a.cmd == "build":
        outdir, pads, converted = build(a.name, a.seed, a.sources, a.dry_run)
        if a.dry_run:
            print("\ndry run - nothing written")
            return
        write_manifest(outdir, a.name, a.seed, pads, "plain")
        print("\n%d/16 pads · %d converted to 44.1k · %s"
              % (sum(1 for p in pads if p["file"]), converted, outdir))
        if a.push:
            print()
            push(a.name)
    elif a.cmd == "push":
        push(a.name)
    elif a.cmd == "preset":
        preset(a.path)


if __name__ == "__main__":
    run()
