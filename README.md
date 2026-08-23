# Bisonte — Move + Live studio

Tooling and method docs for a Move → Live workflow. Audio, Sets and Packs are
deliberately **not** tracked here; this repo is the code and the writing.

## Contents

| Path | What |
|---|---|
| `Move Field Guide.html` | How Move talks to this machine — USB control surface vs Wi-Fi file API |
| `Move to Live Playbook.html` | The overall cycle: sketch → sync → commit → mutate → arrange → render |
| `Layer Stack Method.html` | Overdub method — one part at a time, played against a rendered bed |
| `Song Template.html` | The default song shape — 104-bar form, layer participation grid, folder skeleton |
| `SETUP.md` | Machine setup: paths, LOM/Max notes, Move Manager API reference |
| `tools/move-sync.py` | Move Manager client — `list`, `sets`, `pull`, `push` |
| `tools/new-song.sh` | Scaffold a song project: folders + `SONG.md` with the form table |
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
