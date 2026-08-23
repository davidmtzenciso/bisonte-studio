# Bisonte — Ableton Live + Move Setup

Reference documentation for this machine's Ableton environment: where everything
lives, how Live is scripted with Max for Live, and how the Ableton Move connects
over Wi-Fi and USB.

Last verified: 2026-08-20 (Live 12.3.2, Move firmware 2.0.5 / AbletonOS 3.18).

---

## 1. Layout

| What | Where |
|---|---|
| Ableton Live 12.3.2 Suite | `/Volumes/Bisonte/Applications/Ableton Live 12 Suite.app` |
| Live projects | `/Volumes/Bisonte/Bisonte/` (e.g. `Nueva1 Project/`) |
| User Library | `~/Music/Ableton/User Library/` |
| Max for Live runtime (bundled Max 9.0.9) | inside the Live app, `Contents/App-Resources/Max/` |
| Factory MIDI Remote Scripts (144 incl. `Move`) | inside the Live app, `Contents/App-Resources/MIDI Remote Scripts/` |
| LOM Console device (ours) | `~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/` |
| Move Sets pulled from the device | `~/Music/Ableton/Move Sets/` |
| System Python | 3.10.5 (`/Library/Frameworks/Python.framework/...`) — stdlib only is enough for all tooling here |

---

## 2. Scripting Ableton Live

Every route into Live manipulates the same **Live Object Model (LOM)** — a tree of
`song → tracks → clip_slots / devices → parameters`. Options, in the order we
evaluated them:

1. **Max for Live** (official, chosen) — devices ship with the set; JS via `LiveAPI`.
2. **MIDI Remote Scripts** — Python loaded by Live from the User Library; how AbletonOSC and every controller integration works.
3. **AbletonOSC + pylive** — full LOM over OSC (port 11000) for external control from any language.
4. **MIDI via IAC bus** — crude triggering only.
5. **Offline `.als` editing** — see §5; powerful for batch work.
6. **ClyphX Pro** (commercial) / community **Ableton MCP** servers.

### 2.1 LOM Console (our Max for Live device)

Files:

```
~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/
├── LOM Console.amxd   # the device — generated from Live's factory template
└── lomctl.js          # all the logic — edit this, not the patcher
```

Usage: drag **LOM Console** from Live's browser (User Library → Presets → Audio
Effects → Max Audio Effect) onto any track. Output goes to the **Max Console**
(right-click device title bar → Open Max Window).

Buttons: `info` (set overview) · `tracks` (all tracks) · `devices` (device +
parameter dump of the selected track, recursing into racks) · `tempo 128` ·
`newclip` (4-beat MIDI clip in the selected empty slot) · `watch`/`unwatch`
(observers on tempo, transport, track selection).

`lomctl.js` hot-reloads on save (`autowatch = 1`). The whole API surface:

```js
var t = new LiveAPI("live_set tracks 0");  // navigate
t.get("name")[0]                           // read  — get() always returns an array
t.set("name", "Bass")                      // write
t.getcount("devices")                      // count children
t.call("stop_all_clips")                   // invoke
api.property = "tempo"                     // observe — callback fires on change
```

Gotchas:

- **Never construct `LiveAPI` at file scope** — the device may not be in the set
  yet. `live.thisdevice` bangs the script on load; build objects inside functions.
- The `js` object is **ES5** (no `let`, arrows, template literals). Max 9's `v8`
  object exists for modern JS if ever needed.
- Presentation-mode device height limit is 168 px.

### 2.2 Regenerating the device

The `.amxd` was built programmatically. Format: sequence of chunks
`ampf | meta | ptch`, each `4-byte tag + uint32 LE length + payload`; the `ptch`
payload is the Max patcher JSON, NUL-terminated. Factory templates live in the
app at `Contents/App-Resources/Misc/Max Devices/`.

---

## 3. Ableton Move — two independent connections

### 3.1 Control-surface mode (USB only)

1. On Move: **Shift + Step 2** → Setup menu → wheel to **Control Live** → press wheel.
2. Connect USB-C, open Live — auto-configures (check Settings → Link/Tempo/MIDI).
3. Requires Live ≥ 12.1. The `Move` remote script ships with Live; nothing to install.

Wi-Fi does **not** work for this mode, and while Control Live is active the
file API below refuses uploads — the two modes are mutually exclusive.

### 3.2 Wi-Fi file transfer (Move Manager)

Move runs a web app + HTTP API at `http://move.local` (ports 80 and 22 open).

**Sync script** (stdlib-only, already paired):

```bash
cd ~/Music/Ableton/Move\ Sets
python3 move-sync.py sets              # download every Set as <Name>.ablbundle
python3 move-sync.py list              # browse Move's storage tree
python3 move-sync.py pull Recordings   # mirror a raw bucket (Samples, Recordings…)
```

Double-click any `.ablbundle` to open it in Live.

**Pairing:** session cookie lives in `.move-cookies.txt` next to the script
(mode 600, valid 30 days). When it expires the script re-pairs automatically:
Move shows a 6-digit code on its display, you type it in. Move must be in
Standalone Mode (its normal state) to pair.

**One-way door:** once a Move Set is saved as `.als` in Live it can never go
back to Move. Duplicate the Set on Move first if you want to keep iterating there.

### 3.3 Move Manager API (reverse-engineered from its JS bundle)

Auth — all `/api/v1/*` endpoints except `/language` need the session cookie:

```
POST /api/v1/challenge            # Move displays a code; requires header "Accept: application/json"
POST /api/v1/challenge-response   # body {"secret":"<code>"} → Set-Cookie:
                                  #   Ableton-Challenge-Response-Token=…  (Max-Age 30 days)
```

Files:

```
GET    /api/v1/files/                      # top level: Sets, Recordings, Samples,
                                           #   Track Presets, Audio Effects, MIDI Capture Logs
GET    /api/v1/files/<path>                # list dir / download file
POST   /api/v1/files/<path>                # mkdir, or multipart upload (?overwrite=true)
PATCH  /api/v1/files/<p>/<name>            # rename: {"path":"new/full/path"}
DELETE /api/v1/files/<path>                # delete
GET    /api/v1/convert/<path>.wav          # Move renders the file to audio
OPTIONS /api/v1/files/<path>               # capabilities + disk usage headers
```

Other useful endpoints: `is-move-running`, `system/version`, `cloud-auth/*`,
`ssh`, `syslog/zip`, `update`.

Quirks worth remembering:

- `path` values in responses are **already URL-encoded** (`Alice%20Ivy`) —
  reuse verbatim in URLs, unquote only for display. Double-encoding 404s.
- Sets live as `Sets/<uuid>/<Name>/Song.abl` (`isBundle: true`); downloading
  `Song.abl` yields the zip that Move Manager names `<Name>.ablbundle`.
- Unauthenticated requests → `401 {"error":"Unset credentials"}`;
  `POST /challenge` without an `Accept` header → bare 400.
- Wrong pairing code → 401; rate-limited → 429 with `Retry-After`.

---

## 4. Sets ↔ Live via Ableton Cloud (alternative)

Move Manager → Settings → enable Cloud; in Live sign in to Ableton Cloud; Sets
appear under **Places → Cloud** in the browser. Works, but Move Manager over
LAN is faster and doesn't burn hotspot data.

---

## 5. File formats cheat sheet

| Format | Structure | Notes |
|---|---|---|
| `.als` | gzipped XML | `gunzip -c Set.als > set.xml`, edit, `gzip -c set.xml > Set.als`. Undocumented schema, version-specific — copy first, Live closed. |
| `.amxd` | chunked: `tag + len(LE u32) + payload` | `ptch` chunk = patcher JSON, NUL-terminated. |
| `.ablbundle` | zip | `Song.abl` + `Samples/*.wav`. Live 12 / 11.2+ opens it directly. |
| `.abl` | Move/Note set inside the bundle | What Cloud syncs. |

---

## 6. Current inventory (2026-08-20)

Sets pulled from Move into `~/Music/Ableton/Move Sets/`: Alice Ivy, BNYX Demo
1–4, Heavy Mellow (50 MB — mostly samples), Jose Castillo. All bundles verified
to contain `Song.abl`.
