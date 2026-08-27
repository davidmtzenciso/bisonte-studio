# ableton toolkit

Python utilities and Max for Live code for an Ableton Live 12 + Move studio,
plus the method docs. `CLAUDE.md` is the working handoff: current state, the
constraints that cost hours to find, and every command.

Audio, Sets and Packs are deliberately **not** tracked here; this repo is the
code and the writing.

## Contents

| Path | What |
|---|---|
| `Move Field Guide.html` | How Move talks to this machine — USB control surface vs Wi-Fi file API |
| `Move to Live Playbook.html` | The overall cycle: sketch → sync → commit → mutate → arrange → render |
| `Layer Stack Method.html` | Overdub method — one part at a time, played against a rendered bed |
| `Song Template.html` | The default song shape — 104-bar form, layer participation grid, folder skeleton |
| `Worked Example.html` | One song end to end in six sessions, with real commands and failure modes |
| `CLAUDE.md` | Working handoff — state, hard-won constraints, command reference |
| `SETUP.md` | Machine setup: paths, LOM/Max notes, Move Manager API reference |
| `tools/move-sync.py` | Move Manager client — `list`, `sets`, `pull`, `push` |
| `tools/new-song.sh` | Scaffold a song project: folders + `SONG.md` with the form table |
| `tools/pack-picker.py` | Build 16-pad Move kits — stage pack samples for a Live preset export, or push plain audio straight to Move |
| `tools/BisonteKit.py` | MIDI Remote Script — a JSON command channel into Live, the only route with browser access to load devices and samples |
| `tools/BisonteKit_actions.py` | The commands themselves — re-read on every call, so edits need no Live restart |
| `tools/lomctl.js` | Max for Live device logic — the generative commands |
| `tools/LOM Console.amxd` | The device shell; logic lives in `lomctl.js` |

## Runtime locations

Live and `move-sync.py` load from fixed paths, so the repo copies are symlinked
into place rather than duplicated:

```bash
ln -sf "$PWD/tools/move-sync.py" ~/Music/Ableton/"Move Sets"/move-sync.py
ln -sf "$PWD/tools/lomctl.js" \
  ~/Music/Ableton/"User Library"/Presets/"Audio Effects"/"Max Audio Effect"/lomctl.js
```

`lomctl.js` hot-reloads on save (`autowatch = 1`), so editing it in the repo
reloads the device live.

## Factory Packs on Move

Live Packs cannot be used on Move, and the samples inside them are not a way
around that: 10,378 of the 10,889 `.aif` files in `Factory Packs/` are AIFF-C
with Ableton's `able` compression, which only Live can decode. CoreAudio will
not open one, so neither will Move. The 511 plain files are Convolution Reverb
impulse responses; the `.ogg` files are browser preview thumbnails.

Move's own API states the terms — `OPTIONS /api/v1/files/Samples/` answers
`.wav, .wave, .aif, .aiff, .aifc`, 100 MB per file, and `Track Presets/`
answers `.ablpresetbundle`. Uploading an encrypted `.aif` succeeds and stores
undecodable bytes, so "the upload worked" proves nothing.

Two real routes, both driven by `pack-picker.py`:

```bash
tools/pack-picker.py scan                       # index, plain vs Live-only
tools/pack-picker.py stage "Club Kit" --seed 7  # 16 pack samples, symlinked in pad order
#   drag them into a Drum Rack in Live, File > Export Preset
tools/pack-picker.py preset "Club Kit.ablpresetbundle"

tools/pack-picker.py build "Club Kit" --from Renders/seeds --push
```

The first is Ableton's supported path (Live 12.1+): Live decodes the pack
audio and embeds it in the bundle, downsampled to 44.1 kHz. The second is for
audio we own outright — renders, Move recordings, our own samples — converted
to 44.1 kHz by `afconvert` when needed.

Kits land in `~/Music/Ableton/Move Kits/<name>/` with a `kit.json` and a
`KIT.md` pad table. Same seed and same index rebuild the same kit.

## Driving Live from outside

The Live Object Model can create tracks, clips and notes and set parameters,
but it cannot load a device or a sample — there is no such call. Only a MIDI
Remote Script gets `Live.Browser`, which is how Push loads sounds.

`tools/BisonteKit.py` is that script: it polls a JSON file and acts on it, so
a shell can drive Live's browser.

```bash
ln -sfn "$PWD/tools/BisonteKit.py" \
  ~/Music/Ableton/"User Library"/"Remote Scripts"/BisonteKit/__init__.py
# Live only sees a new script at startup, then enable it under
# Preferences > Link/Tempo/MIDI as a Control Surface.

echo '{"cmd":"probe"}' > ~/Music/Ableton/"Move Kits"/_command.json
echo '{"cmd":"build","kit":"<kit.json>"}' > ~/Music/Ableton/"Move Kits"/_command.json
```

Results land in `_result.json`, errors and tracebacks in `_bisontekit.log`,
both next to the command file. `actions.py` is exec'd fresh per command,
so only a change to `BisonteKit.py` itself needs Live restarted.

**Live's browser does not index symlinks.** A staged folder of links reads
as empty to both Places and `browser.load_item`, which is why `stage`
copies. Verified: 0 items as links, 16 as copies. Kits stage inside the User Library because the
script finds samples by walking `browser.user_library`.

## Readable `.als` diffs

`.gitattributes` marks Live Sets as `diff=als`. Enable the filter once per clone:

```bash
git config diff.als.textconv 'gunzip -c'
```

`git diff` then shows the XML changes between song versions instead of "binary
files differ". Useful for seeing exactly what a generated clip changed.

## Not tracked

`.move-cookies.txt` (session credential), `*.ablbundle`, rendered audio,
`Samples/`, `Renders/`, installed Packs. See `.gitignore`.

## Starting a song

```bash
tools/new-song.sh "Bisonte Club 2" 124 "F minor"
```

Creates `<Song> Project/` under `/Volumes/Bisonte/Music Project/Bisonte/` with
`Beds/`, `Parts/`, `Renders/{master,stems,seeds}` and a `SONG.md` carrying the
104-bar form and a per-layer tracking log. Override the root with
`BISONTE_PROJECTS`.

## Pushing beds

```bash
cd "<Song> Project"
python3 ~/Music/Ableton/"Move Sets"/move-sync.py push Beds/bed_v03.wav "Bisonte Club 2" --tempo 124
```

Creates `Samples/Bisonte/<Song>/` on Move if missing and uploads with
`?overwrite=true`. Move must be in **Standalone** mode — uploads are refused in
Control Live, and the script says so rather than failing obscurely.

Passing `--tempo` asserts the files are beds: anything that isn't a whole
multiple of 8 bars at that tempo is refused, because a bed that is a few
milliseconds off drifts audibly by bar 8 and every part played against it
inherits the error. `--force` overrides. Without `--tempo` no check runs, so
one-shots and loops of any length push fine.

## Backlog

`lomctl.js` — `seed`, `euclid`, `mutate`, `markov`, then `graph`, `arrange`,
`density`. All ES5, all seeded, command + args + seed written into every
generated clip name so any result can be regenerated.
