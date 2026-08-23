#!/usr/bin/env python3
"""Pull Sets off an Ableton Move over Wi-Fi via the Move Manager HTTP API.

    python3 move-sync.py sets          # download every Set as <Name>.ablbundle
    python3 move-sync.py list          # browse Move's file tree
    python3 move-sync.py pull Samples  # mirror a raw bucket (Samples, Recordings...)

First run pairs with Move: it shows a confirmation code on its display, you
type it here, and the session cookie (valid 30 days) is cached next to this
script. Move must be in Standalone Mode (not Control Live) to pair.
"""

import http.cookiejar, json, os, sys, urllib.error, urllib.parse, urllib.request

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
    else:
        sys.exit(__doc__)
