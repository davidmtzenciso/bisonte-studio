# Music Project — working notes

Ableton Live 12.4 + Ableton Move studio on the Bisonte drive. This file is the
handoff: what is here, what is true, and what to do next. Written 2026-08-26.

## Layout

| Path | What |
|---|---|
| `Music Project/ableton toolkit/` | **This git repo** — Python utilities, the Live/Move tooling, and the writing. No audio, no sets. |
| `Music Project/ableton toolkit/tools/` | `lomctl.js`, `LOM Console.amxd`, `move-sync.py`, `pack-picker.py`, `BisonteKit.py`, `BisonteKit_actions.py`, `new-song.sh` |
| `Music Project/Bisonte/` | A **different, older project** (`Nueva1 Project`). Leave it alone. |
| `Music Project/Death Valley/` | Current song. `death_valley_1 Project/death_valley_1.als` |
| `Music Project/Ableton/` | `Factory Packs/` (~30 GB), `User Library/`, `Move Sets/`, `Live Recordings/` |
| `~/Music/Ableton/User Library/Move Kits/` | Staged kits — inside User Library so Live's browser can see them |
| `~/Music/Ableton/Move Kits/` | BisonteKit command channel: `_command.json`, `_result.json`, `_bisontekit.log` |

Runtime copies are **symlinks into the repo**, so edit the repo file:

```bash
~/Music/Ableton/"Move Sets"/move-sync.py                    -> tools/move-sync.py
~/Music/Ableton/"User Library"/Presets/"Audio Effects"/"Max Audio Effect"/lomctl.js  -> tools/lomctl.js
~/Music/Ableton/"User Library"/"Remote Scripts"/BisonteKit/__init__.py -> tools/BisonteKit.py
~/Music/Ableton/"User Library"/"Remote Scripts"/BisonteKit/actions.py  -> tools/BisonteKit_actions.py
```

## Where the work stands

Done and verified against real hardware:

- **`lomctl.js`** — `seed`/`roll` (32-bit LCG, deterministic) and `euclid k [n] [rot] [pitch]`
  writing Euclidean patterns into the selected empty clip slot. Buttons added to the
  device. **Not yet run inside Live** — logic is node-tested only.
- **`move-sync.py`** — pulls Sets, lists Move's storage, and now genuinely uploads
  (two bugs fixed, see below). Cookie valid ~30 days from 2026-08-20.
- **`pack-picker.py`** — indexes the packs, picks 16 one-shots onto a pad layout,
  stages or builds a kit, pushes samples or a preset bundle.
- **`BisonteKit`** — MIDI Remote Script, a JSON command channel into Live. Currently
  loaded and answering (`{"cmd":"ping"}` → `actions_version: 3`).
- **Death Valley kit** — 16 pads built by script in Live on notes 36–51, Drum Sampler
  cells, chokes on 42/44/46. Track named `Death Valley` in the open set.

Immediate next steps, in order:

1. In Live: **save the set** (the built `Death Valley` track is unsaved).
2. Select the Drum Rack → **⌘G** to wrap it in an Instrument Rack → add one
   **Saturator** after the Drum Rack inside that rack. This mirrors the factory
   `Bisonte Club 1` structure Move expects.
3. Right-click the **outer Instrument Rack** title bar → **Export ABL Preset** →
   save as `Death Valley.ablpresetbundle`.
4. `python3 tools/pack-picker.py preset "<path>.ablpresetbundle"` — uploads to Move's
   `Track Presets/`. Move must be in **Standalone**, not Control Live.
5. Verify on Move, then delete the stale `Bisonte Club Kit (stage)` folder and the
   old mirrored track if the set still has one.

Open, not started: `mutate`, `markov`, `graph`, `arrange`, `density` in `lomctl.js`;
a `kit` command so `euclid 5 16 0 hat` can address pads by name.

## Facts that cost hours — do not re-derive

**Live Pack samples are encrypted.** 10,378 of the 10,889 `.aif` files under
`Ableton/Factory Packs/` are AIFF-C with Ableton's `able` compression. Only Live can
decode them — `afinfo`/`afconvert` refuse every one. The 511 plain files are
Convolution Reverb impulse responses; the 4,037 `.ogg` files are browser preview
thumbnails. **Pack audio can never be uploaded to Move as samples.** The route is
Live's preset export, which embeds decoded audio.

**Do not parse audio headers by searching for `COMM`.** Those bytes occur inside
compressed data too, yielding invented sample rates. Walk the IFF chunk list and read
COMM's compressionType. `pack-picker.probe()` does this correctly.

**Live's browser does not index symlinks.** A staged folder of symlinks reports zero
children to `browser.user_library` walks and to Places; the same folder with real
copies reports 16. `pack-picker stage` copies for this reason.

**`browser.load_item` ignores `rack.view.selected_drum_pad`.** Loading that way put
every sample on note `128 - N` — a kick aimed at 36 landed on 92, mirroring the kit.
Use `browser.hotswap_target = pad` instead, and verify by diffing which pads gained a
chain. Verified 16/16 on 36–51.

**Only a MIDI Remote Script can load devices or samples.** The LOM (Max for Live,
AbletonOSC, `lomctl.js`) has no such call. `Live.Browser` exists only inside a Remote
Script. AppleScript is useless — Live ships no dictionary.

**"Save as Default Pad" is just a file.** Live's `Core Library/Defaults/Instruments/
Drum Sampler.adv` copied to `~/Music/Ableton/User Library/Defaults/Dropping Samples/
On Drum Rack/Sample on Drum Pad Default.adv` makes dropped samples become Drum
Sampler (`DrumCell`) cells instead of Simpler. **Already installed** — verified by
grepping a saved `.als`: 16 `<DrumCell`, 0 `<OriginalSimpler`.

**Move's API states its own terms** (`OPTIONS /api/v1/files/<dir>/`):
`Samples/` accepts `.wav .wave .aif .aiff .aifc`, 100 MB per file, ~48.8 GiB free;
`Track Presets/` accepts `.ablpresetbundle`. Move **stores an encrypted `.aif`
happily** — a successful upload proves nothing about playability. Move answers **400**
(not 404) for a missing path, and does **not** answer ICMP: test with `curl`, never
`ping`.

**Move over USB-C is a network interface**, not just MIDI. Plugging in creates
"Ableton Move USB Ethernet" (Mac gets 172.16.254.x, Move is 172.16.254.1) and
`move.local` resolves through it. It takes a few seconds to come up; a first failed
request means wait, not broken. Wi-Fi is optional.

**`move-sync.py` had two never-tested upload bugs** (fixed, commit 889ec83):
`post_file` posted to the file path, so Move treated the filename as a folder (400) —
POST to the *directory*, the multipart part carries the filename. And `ensure_dir`
only tolerated 404 for a missing directory. Importing `move-sync` as a library must
load the **symlinked copy** in `~/Music/Ableton/Move Sets/`, because it derives its
cookie-jar path from `__file__`.

**Don't poll Live during startup.** A command sent while Live is loading looks like a
dead script. Wait for `loaded vN` in `_bisontekit.log` before concluding anything.

## Tools

```bash
cd "/Volumes/Bisonte/Music Project/ableton toolkit"

# --- Move file API (Standalone mode only; uploads refused in Control Live) ---
python3 tools/move-sync.py list                 # browse Move's storage
python3 tools/move-sync.py sets                 # pull every Set as <Name>.ablbundle
python3 tools/move-sync.py pull Recordings      # mirror a bucket
python3 tools/move-sync.py push Beds/bed.wav "Song" --tempo 124

# --- kit building ---
python3 tools/pack-picker.py scan               # index packs: plain vs Live-only
python3 tools/pack-picker.py roles              # availability per pad role
python3 tools/pack-picker.py stage "Death Valley" --seed 7   # 16 pack samples -> User Library
python3 tools/pack-picker.py build "Kit" --from Renders/seeds --push   # plain audio -> Move
python3 tools/pack-picker.py preset "Kit.ablpresetbundle"    # -> Move Track Presets
```

### Driving Live

```bash
B=~/Music/Ableton/"Move Kits"
echo '{"cmd":"ping"}'  > "$B/_command.json"          # -> {"ok":true,"actions_version":3}
echo '{"cmd":"probe"}' > "$B/_command.json"          # browser API surface + tracks
python3 -c 'import json;print(json.dumps({"cmd":"build","kit":"<kit.json>","name":"Death Valley"}))' > "$B/_command.json"
echo '{"cmd":"cells","track":"Death Valley"}' > "$B/_command.json"
echo '{"cmd":"delete_track","track":"Bisonte Club Kit"}' > "$B/_command.json"
# then read "$B/_result.json"; errors and tracebacks in "$B/_bisontekit.log"
```

`actions.py` is exec'd fresh on every command — edit it freely, no restart. Only a
change to `BisonteKit.py` (the polling core) needs Live restarted, and Live only scans
for control surfaces at startup. It is enabled in **Settings → Link, Tempo & MIDI**,
slot 2 (macOS calls it Settings, not Preferences). Slot 1 holds Move — leave it.

Note: `tools/BisonteKit.py` on disk is **v4**; Live is running **v2**. The difference
is only defensive logging. It will pick up v4 on the next restart.

## Conventions

- **Seeds.** Every generated thing carries its command, arguments and seed in its name
  (`~euclid 5 16 0 p36`), so it can be regenerated. Same seed + same index = same kit.
- **Pad layout** mirrors the factory `Bisonte Club 1` kit: 36 kick, 37 rim, 38 snare,
  39 clap, 40 snare, 41 tom, 42 hat, 43 tom, 44 hat, 45 tom, 46 crash, 47 perc,
  48 shaker, 49 cymbal, 50 tambourine, 51 perc. Choke group 1 on 42, 44, 46.
- **One-way door.** A Move Set saved as `.als` can never go back to Move. Duplicate it
  on Move first if it should keep living there. Audio cycles back as samples; Sets don't.
- **The repo is code and writing.** `.gitignore` excludes audio, sets, `.adg`, `.adv`,
  `.ablpresetbundle` and `* Project/`.
- **ES5 only in `lomctl.js`** (Max's `js` object): `var`, no arrows, no template
  strings, no `Math.imul`. Never construct `LiveAPI` at file scope.

## The method (from the repo's own docs)

Read `*.html` in this repo — Move Field Guide, Move to Live Playbook, Layer Stack Method,
Song Template, Worked Example. The loop: sketch on Move → sync → commit to `.als` →
mutate with LOM Console → arrange → render → push audio back to Move's `Samples/`.
`SETUP.md` has the machine details and the Move Manager API reference.
