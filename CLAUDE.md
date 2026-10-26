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
  (two bugs fixed, see below). **Cookie expired ~2026-09-19** and re-pairing has
  not succeeded since: `/api/v1/challenge` returned HTTP 500 on 2026-10-26 even
  with Move in Standalone and its API answering 200. Pair before switching to
  Control Live — the manual says an authenticated session survives the switch.
- **`pack-picker.py`** — indexes the packs, picks 16 one-shots onto a pad layout,
  stages or builds a kit, pushes samples or a preset bundle.
- **`mr18.py`** — reads and controls the Midas MR18 over OSC/UDP 10024.
  `probe`, `scan`, `info`, `state`, `monitor`, `meters`, `get`, `set`.
- **`BisonteKit`** — MIDI Remote Script, a JSON command channel into Live.
  Loaded and answering `actions_version: 4` (2026-10-26).
- **Death Valley kit** — 16 pads built by script in Live on notes 36–51, Drum Sampler
  cells, chokes on 42/44/46. Track named `Death Valley`.
  **It IS saved**, as `Death Valley/death_valley_1 Project/Untitled.als`
  (27 Aug 11:50) — Live's default filename, not an unsaved set. The older
  `death_valley_1.als` (26 Aug) holds the same 16 DrumCells but under the stale
  track name `Bisonte Club Kit`, so **`Untitled.als` is the one to open.**

Immediate next steps, in order:

1. In Live: open `Untitled.als` (above) and **Save As `death_valley_1`** to
   consolidate onto the name the project uses. Overwriting in that direction is
   safe — the target is the older, staler file. The reverse destroys the kit.
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

**Move sends NO MIDI in Standalone Mode.** Its pads drive its internal engine and
nothing leaves the device — measured 2026-10-26: 445 messages over two minutes,
every one of them `0xFE` Active Sensing, on all four ports. It still *receives*
MIDI and plays it, so a working "it makes sound" test proves nothing about
output. **Switch to Control Live Mode**: hold **`•••`** (bottom-right, right of
Undo — it is NOT labelled "Shift") and press **Step 2** (gear icon, 2nd of the 16
bottom buttons) → wheel to `Control Live` → press wheel. Double-press `•••` to
lock it. The entry then reads `Standalone` to switch back.

**Do not use `en10` or the Move API to detect the mode** — both stay up in
Control Live (the manual only says Move *Manager* is inaccessible). Monitoring
raw MIDI is the only reliable test.

**In Control Live, Move is a control surface, not a keyboard.** It disarms the
MIDI tracks, manages arming itself, and creates its own clips. What arrives is
its control layer (pitches 87–96 at velocity 1), not playable notes — press
**`≡`** (left, beside Back) for Note Mode to get real pitches.

**CoreMIDI shows four Move ports; Live shows three.** The *User Port* is missing
from Live's routing list. Nothing arrives on it either, so it is not the cause of
a silent Move, but it rules the port out as a workaround.

**macOS has no built-in MIDI monitor.** `python-rtmidi` in a throwaway venv is
the only way to see what a device actually transmits, independent of Live — and
Live being in the loop is what made this take hours. Remember to pass
`ignore_types(active_sense=False)` first to confirm the link, then filter it back
out so real data is visible.

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

# --- Midas MR18 mixer over OSC (ethernet is control only; audio is USB) ---
tools/mr18.py probe                 # broadcast discovery, per-interface
tools/mr18.py scan                  # unicast sweep of each local /24
tools/mr18.py state   <host>        # faders, gains, phantom, mutes
tools/mr18.py meters  <host>        # /meters/1, PRE-gain, per physical jack
tools/mr18.py get /headamp/02 <host>
tools/mr18.py set /headamp/02 0.5833 <host>    # 0.5833 = +30 dB
```

**Find the MR18 by ARP, not broadcast.** It ignores `/info` sent to
`169.254.255.255` but answers ARP: check `en5` is `status: active` first, then
`arp -an | grep en5` and look for `73:c3:d8`. Its link-local address changes
between sessions. A DHCP lease on `en5` means the cable is in the router, not
the mixer.

### Driving Live

```bash
B=~/Music/Ableton/"Move Kits"
echo '{"cmd":"ping"}'  > "$B/_command.json"          # -> {"ok":true,"actions_version":4}
echo '{"cmd":"probe"}' > "$B/_command.json"          # browser API surface + tracks
python3 -c 'import json;print(json.dumps({"cmd":"build","kit":"<kit.json>","name":"Death Valley"}))' > "$B/_command.json"
echo '{"cmd":"cells","track":"Death Valley"}' > "$B/_command.json"
echo '{"cmd":"delete_track","track":"Bisonte Club Kit"}' > "$B/_command.json"

# recording and routing (v4)
echo '{"cmd":"song_info"}'   > "$B/_command.json"    # which .als is open; is it saved
echo '{"cmd":"inputs"}'      > "$B/_command.json"    # audio track routing + what Live offers
echo '{"cmd":"midi_inputs"}' > "$B/_command.json"    # same for MIDI tracks
echo '{"cmd":"surfaces"}'    > "$B/_command.json"    # which control surface slots are filled
echo '{"cmd":"rec","name":"Ch2 Mic","type":"Ext. In","channel":"2","arm":true}' > "$B/_command.json"
echo '{"cmd":"levels"}'      > "$B/_command.json"    # meters + monitoring, one shot per call
echo '{"cmd":"fire","track":"Ch2 Mic","slot":0}' > "$B/_command.json"   # start recording
echo '{"cmd":"transport","action":"stop"}' > "$B/_command.json"
echo '{"cmd":"clips","track":"Ch2 Mic"}' > "$B/_command.json"           # incl. file_path on disk
echo '{"cmd":"clip_notes","track":"1-MIDI","slot":0}' > "$B/_command.json"
echo '{"cmd":"track_set","name":"Ch2 Mic","monitor":2,"volume":0.85}' > "$B/_command.json"
# then read "$B/_result.json"; errors and tracebacks in "$B/_bisontekit.log"
```

**Live's own settings are not in the LOM.** The audio input device, the MIDI
port Track/Sync/Remote switches, and **saving the set** are application
preferences — no script can touch them, and `song.file_path` / `song.name` are
read-only (empty string means the set was never saved). Everything downstream
of those — tracks, routing, arming, transport, clips — is scriptable.

`surfaces` reports which slots are *occupied*, not whether a surface's MIDI
ports are bound: BisonteKit itself sits in a slot with no MIDI port at all.
Port assignments live in `Preferences.cfg`, which is binary.

`actions.py` is exec'd fresh on every command — edit it freely, no restart. Only a
change to `BisonteKit.py` (the polling core) needs Live restarted, and Live only scans
for control surfaces at startup. It is enabled in **Settings → Link, Tempo & MIDI**,
slot 2 (macOS calls it Settings, not Preferences). Slot 1 holds Move — leave it.

Note: Live is now running `BisonteKit.py` **v4** — it picked it up on a restart.
Live 12.4.1 as of 2026-10-26.

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
