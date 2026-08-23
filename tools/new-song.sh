#!/usr/bin/env bash
# new-song.sh — scaffold a song project for the layer-stack workflow.
#
#   ./new-song.sh "Bisonte Club 2" [tempo] [key]
#
# Creates the folder skeleton and a SONG.md carrying the arrangement
# skeleton, so tempo, key and form are decided once and written down.

set -euo pipefail

ROOT="${BISONTE_PROJECTS:-/Volumes/Bisonte/Music Project/Bisonte}"
NAME="${1:-}"
TEMPO="${2:-124}"
KEY="${3:-TBD}"

if [ -z "$NAME" ]; then
  echo "usage: $(basename "$0") \"<Song Name>\" [tempo] [key]" >&2
  exit 64
fi

[ -d "$ROOT" ] || { echo "projects root not found: $ROOT" >&2; exit 66; }

DIR="$ROOT/$NAME Project"
if [ -e "$DIR" ]; then
  echo "already exists: $DIR" >&2
  exit 73
fi

mkdir -p "$DIR"/{Beds,Parts,Renders/master,Renders/stems,Renders/seeds}

cat > "$DIR/SONG.md" <<EOF
# $NAME

| | |
|---|---|
| Tempo | **$TEMPO** BPM |
| Key | **$KEY** |
| Started | $(date +%Y-%m-%d) |

Tempo and key are decided at L1 and never change. Everything above L1 is
played against a bed rendered at this tempo.

## Form

104 bars. Every section is a multiple of 8, so any 8-bar bed loops cleanly
into any section. Section names are also the Live scene names and the
terminals the \`arrange\` grammar expands to.

| # | Section | Bars | Ends | Energy | L1 drums | L2 bass | L3 rhythm | L4 lead | L5 atmos | L6 prod |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | INTRO | 16 | 16 | 1 | filtered | — | — | — | ● | riser → |
| 2 | A | 16 | 32 | 3 | ● | ● | ● | — | ● | — |
| 3 | B | 16 | 48 | 4 | ● | ● | ● | ● | ● | — |
| 4 | BREAK | 8 | 56 | 2 | no kick | — | ● | — | ● | tension |
| 5 | B' | 16 | 72 | 5 | ● | ● | ● | ● | ● | fills |
| 6 | A' | 16 | 88 | 3 | ● | ● | — | ● | ● | — |
| 7 | OUTRO | 16 | 104 | 1 | filtered | ● | — | — | ● | — |

Read a **column**: a layer with ● in every row is playing too much. Read a
**row**: a section where every layer is on has nowhere left to build.

## Tracking log

One line per part as it lands. Bed version is what the part was played against.

| Layer | Move Set | Bed | Instrument | Done |
|---|---|---|---|---|
| L1 drummer | \`$NAME L1 drummer\` | — | | |
| L2 bassist | \`$NAME L2 bassist\` | bed_v01 | | |
| L3 rhythm | \`$NAME L3 rhythm\` | bed_v02 | | |
| L4 lead | \`$NAME L4 lead\` | bed_v03 | | |
| L5 atmos | \`$NAME L5 atmos\` | bed_v04 | | |
| L6 prod | — (in Live) | bed_v05 | | |

## Decisions

- Kick/bass relationship:
- What only this track has:
- Reference record:
EOF

cat > "$DIR/Beds/README.txt" <<'EOF'
Headphone mixes. One per layer committed, exactly 8 bars, render tail 0 ms,
44.1k/16-bit, normalize off.

bed_v01.wav = L1 only.  bed_v02.wav = L1+L2.  And so on.

Upload to Move at Samples/Bisonte/<Song>/ before tracking the next part.
Move must be in Standalone mode or the upload is refused.
EOF

cat > "$DIR/Parts/README.txt" <<'EOF'
Layer bundles pulled from Move, one per part: "<Song> L2 bassist.ablbundle".

These are the last state Move and Live share. Once a part is dragged into the
Live set it never returns to Move — duplicate the Set on Move first if the
idea might keep evolving on the hardware.
EOF

printf '%s\n' \
  "created: $DIR" \
  "" \
  "  SONG.md            tempo $TEMPO, key $KEY, form + tracking log" \
  "  Beds/              bed_vNN.wav, 8 bars each" \
  "  Parts/             layer bundles from Move" \
  "  Renders/           master, stems, seeds" \
  "" \
  "next: track L1 on Move as \"$NAME L1 drummer\" at $TEMPO BPM"
