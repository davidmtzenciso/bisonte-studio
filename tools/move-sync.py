#!/usr/bin/env python3
"""Pull Sets off an Ableton Move over Wi-Fi via the Move Manager HTTP API.

    python3 move-sync.py sets          # download every Set as <Name>.ablbundle
    python3 move-sync.py list          # browse Move's file tree
    python3 move-sync.py pull Samples  # mirror a raw bucket (Samples, Recordings...)
    python3 move-sync.py push bed_v03.wav "Bisonte Club 2"
                                       # upload into Samples/Bisonte/<Song>/
    python3 move-sync.py push Beds/*.wav "Bisonte Club 2" --tempo 124
                                       # ...and check each is a whole number of bars

First run pairs with Move: it shows a confirmation code on its display, you
type it here, and the session cookie (valid 30 days) is cached next to this
script. Move must be in Standalone Mode (not Control Live) to pair — and
uploads are refused in Control Live mode too.
"""

import http.cookiejar, json, os, sys, urllib.error, urllib.parse, urllib.request, wave

HOST = os.environ.get("MOVE_HOST", "http://move.local")
HERE = os.path.dirname(os.path.abspath(__file__))
JAR = os.path.join(HERE, ".move-cookies.txt")

cj = http.cookiejar.LWPCookieJar(JAR)
if os.path.exists(JAR):
    cj.load(ignore_discard=True)
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def call(path, data=None, method=None, raw=False, timeout=120):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        HOST + path, data=body, method=method,
        headers={"Accept": "application/json, */*",
                 **({"Content-Type": "application/json"} if body else {})})
    with opener.open(req, timeout=timeout) as r:
        payload = r.read()
    return payload if raw else json.loads(payload or b"null")


def authenticated():
    try:
        call("/api/v1/is-move-running")
        return True
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False
        raise


def pair():
    print("Asking Move to show a confirmation code...")
    try:
        call("/api/v1/challenge", method="POST", raw=True)
    except urllib.error.HTTPError as e:
        if e.code == 500:
            sys.exit("Move refused: switch it to Standalone Mode and retry.")
        sys.exit("Pairing request failed (HTTP %d). Wake Move's screen and retry." % e.code)

    code = input("Enter the code shown on Move's display: ").strip()
    try:
        call("/api/v1/challenge-response", data={"secret": code}, method="POST")
    except urllib.error.HTTPError as e:
        sys.exit("Wrong code." if e.code == 401 else "Pairing failed (HTTP %d)." % e.code)

    cj.save(ignore_discard=True)
    os.chmod(JAR, 0o600)
    print("Paired. Session cached in %s\n" % JAR)


# NOTE: 'path' values in API responses are already URL-encoded ("Alice%20Ivy").
# Reuse them verbatim when building URLs; unquote only for display/filenames.
def listdir(enc_parts):
    path = "/api/v1/files/" + "/".join(enc_parts)
    return call(path).get("paths", [])


def download_sets():
    for entry in listdir(["Sets"]):
        sid = entry["path"]  # UUID folder
        for sub in listdir(["Sets", sid]):
            name = urllib.parse.unquote(sub["path"])
            fname = os.path.join(HERE, name + ".ablbundle")
            blob = call("/api/v1/files/Sets/%s/%s/Song.abl" % (sid, sub["path"]), raw=True)
            open(fname, "wb").write(blob)
            print("%-24s %10d bytes" % (name + ".ablbundle", len(blob)))


def walk(enc_parts, depth=0, limit=3):
    for entry in listdir(enc_parts):
        name = urllib.parse.unquote(entry["path"]).rstrip("/").split("/")[-1]
        kind = "dir " if entry.get("isDirectory") else "file"
        size = entry.get("size")
        print("  " * depth + "%s %s%s" % (kind, name, "" if size is None else "  (%d bytes)" % size))
        if entry.get("isDirectory") and depth < limit:
            walk(enc_parts + [entry["path"]], depth + 1, limit)


def pull(enc_parts, dest):
    os.makedirs(dest, exist_ok=True)
    for entry in listdir(enc_parts):
        name = urllib.parse.unquote(entry["path"]).rstrip("/").split("/")[-1]
        target = os.path.join(dest, name)
        if entry.get("isDirectory"):
            pull(enc_parts + [entry["path"]], target)
        else:
            print("  %s" % target)
            blob = call("/api/v1/files/" + "/".join(enc_parts + [entry["path"]]), raw=True)
            open(target, "wb").write(blob)


def bars_of(path, tempo):
    """Length of a WAV in bars at `tempo` (4/4). None if it isn't readable PCM."""
    try:
        with wave.open(path, "rb") as w:
            seconds = w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, OSError):
        return None
    return seconds / (4.0 * 60.0 / tempo)


def ensure_dir(enc_parts):
    """Create each missing level of a directory path. Existing levels are left alone."""
    for i in range(1, len(enc_parts) + 1):
        branch = enc_parts[:i]
        try:
            listdir(branch)
            continue                                   # already there
        except urllib.error.HTTPError as e:
            if e.code not in (400, 404):        # Move answers 400 for "no such path"
                raise
        call("/api/v1/files/" + "/".join(branch) + "/", method="POST", raw=True)
        print("  mkdir  %s" % urllib.parse.unquote("/".join(branch)))


def post_file(enc_parts, local_path):
    """Multipart-upload one file to Samples/... , replacing any existing copy."""
    with open(local_path, "rb") as f:
        blob = f.read()
    name = os.path.basename(local_path)
    boundary = "----movesync%s" % os.urandom(12).hex()
    body = b"".join([
        ("--%s\r\n" % boundary).encode(),
        ('Content-Disposition: form-data; name="file"; filename="%s"\r\n' % name).encode(),
        b"Content-Type: application/octet-stream\r\n\r\n",
        blob,
        ("\r\n--%s--\r\n" % boundary).encode(),
    ])
    # POST to the DIRECTORY - the multipart part already carries the filename.
    # Posting to the file path makes Move treat the name as a folder and 400.
    url = "%s/api/v1/files/%s/?overwrite=true" % (HOST, "/".join(enc_parts))
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Accept": "application/json, */*",
                 "Content-Type": "multipart/form-data; boundary=%s" % boundary})
    with opener.open(req, timeout=600) as r:
        r.read()
    return len(blob)


def check_bed(local, tempo):
    """Return (ok, note). --tempo asserts these are beds, so a bad one is a hard skip."""
    bars = bars_of(local, tempo)
    if bars is None:
        return False, "[not a readable WAV]"
    if abs(bars - round(bars)) > 0.01:
        return False, "[%.2f bars at %g BPM - would drift]" % (bars, tempo)
    if round(bars) % 8:
        return False, "[%d bars - not a multiple of 8]" % round(bars)
    return True, "[%d bars ok]" % round(bars)


def push(files, song=None, tempo=None, force=False):
    parts = ["Samples", "Bisonte"] + ([urllib.parse.quote(song)] if song else [])
    ensure_dir(parts)
    skipped = 0
    for local in files:
        if not os.path.isfile(local):
            print("  skip   %s (not a file)" % local)
            continue
        note = ""
        if tempo:
            ok, note = check_bed(local, tempo)
            note = "  " + note
            if not ok and not force:
                print("  SKIP   %-28s %s" % (os.path.basename(local), note.strip()))
                skipped += 1
                continue
        try:
            n = post_file(parts, local)
        except urllib.error.HTTPError as e:
            if e.code in (403, 405, 409, 500, 503):
                sys.exit("Upload refused (HTTP %d). Is Move in Control Live mode? "
                         "Switch it to Standalone and retry." % e.code)
            raise
        print("  put    %-28s %9d bytes%s" % (os.path.basename(local), n, note))
    print("\n-> Samples/Bisonte%s/" % ("/" + song if song else ""))
    if skipped:
        sys.exit("\n%d file(s) skipped as unusable beds. Re-render at exactly 8 bars "
                 "with render tail 0, or pass --force to upload anyway." % skipped)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sets"

    if not authenticated():
        pair()

    if cmd == "sets":
        download_sets()
    elif cmd == "list":
        walk([])
    elif cmd == "pull":
        bucket = urllib.parse.quote(sys.argv[2]) if len(sys.argv) > 2 else "Samples"
        pull([bucket], os.path.join(HERE, urllib.parse.unquote(bucket)))
    elif cmd == "push":
        args, tempo, force = sys.argv[2:], None, False
        if "--force" in args:
            force = True
            args.remove("--force")
        if "--tempo" in args:
            i = args.index("--tempo")
            tempo = float(args[i + 1])
            del args[i:i + 2]
        files = [a for a in args if os.path.isfile(a)]
        rest = [a for a in args if a not in files]
        if not files:
            sys.exit('usage: move-sync.py push <file...> ["<Song>"] [--tempo 124] [--force]')
        push(files, rest[0] if rest else None, tempo, force)
    else:
        sys.exit(__doc__)
