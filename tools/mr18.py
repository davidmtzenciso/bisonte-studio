#!/usr/bin/env python3
"""Read and control the Midas MR18 over OSC/UDP.

The mixer answers on udp/10024. Ethernet is control only - audio is USB.

    mr18.py probe                 discover the mixer by broadcast
    mr18.py scan [prefix ...]     unicast sweep of each local /24
    mr18.py info [host]           /xinfo + /status
    mr18.py state [host]          faders, headamp gains, mutes for ch 1-18
    mr18.py monitor [host]        /config/solo/* (monitor + phones bus)
    mr18.py meters [host]         /meters/1, pre-gain, per physical jack
    mr18.py get <addr> [host]     read one address
    mr18.py set <addr> <v> [host] write one address (float, int or string)

Host defaults to $MR18_HOST, else whatever `probe` finds.

Quirks that cost hours, kept here so they stay fixed:
  - headamp indices are 1-based and stop at 16: /headamp/01 .. /headamp/16.
    /headamp/00 does not exist and silently times out. Worse, ANY index
    above 16 answers with a single bogus 0.375 (+15 dB) instead of
    nothing, so trust a reply only when it carries two values,
    [gain, phantom]. Input 11 is /headamp/11.
  - there is no /ch/17 or /ch/18. 16 mono channels, then a stereo aux
    return (/rtn/aux) and two FX returns (/rtn/1, /rtn/2), all line
    level with no preamp.
  - /meters/1 is PRE-gain, so it reads 20-30 dB below the M AIR Edit meters
    and does not move when headamp gain changes.
  - the phones jack follows the monitor bus and cannot be rerouted; a
    separate headphone mix needs an aux bus.
"""
import os
import re
import select
import socket
import struct
import subprocess
import sys
import time

PORT = 10024
TIMEOUT = 0.35


# ---------------------------------------------------------------- OSC codec

def _pad(b):
    return b + b"\0" * (4 - len(b) % 4)


def encode(addr, *args):
    tags = ","
    body = b""
    for a in args:
        if isinstance(a, bool):
            tags += "i"
            body += struct.pack(">i", int(a))
        elif isinstance(a, int):
            tags += "i"
            body += struct.pack(">i", a)
        elif isinstance(a, float):
            tags += "f"
            body += struct.pack(">f", a)
        else:
            tags += "s"
            body += _pad(str(a).encode())
    return _pad(addr.encode()) + _pad(tags.encode()) + body


def decode(d):
    def rs(i):
        e = d.index(b"\0", i)
        return d[i:e].decode("utf-8", "replace"), (e // 4 + 1) * 4

    addr, i = rs(0)
    if i >= len(d):
        return addr, []
    tags, i = rs(i)
    args = []
    for t in tags[1:]:
        if t == "s":
            v, i = rs(i)
            args.append(v)
        elif t == "i":
            args.append(struct.unpack(">i", d[i:i + 4])[0])
            i += 4
        elif t == "f":
            args.append(struct.unpack(">f", d[i:i + 4])[0])
            i += 4
        elif t == "b":
            n = struct.unpack(">i", d[i:i + 4])[0]
            args.append(d[i + 4:i + 4 + n])
            i += 4 + (n + 3) // 4 * 4
    return addr, args


# ------------------------------------------------------------------ scaling

def fader_db(f):
    """MR18 fader taper -> dB. Unity (0 dB) is 0.75."""
    if f >= 0.5:
        return f * 40 - 30
    if f >= 0.25:
        return f * 80 - 50
    if f >= 0.0625:
        return f * 160 - 70
    return f * 480 - 90


def headamp_db(f):
    """Preamp gain maps 0.0-1.0 to -12 .. +60 dB."""
    return f * 72 - 12


def fmt_db(x):
    """One decimal, signed, with no '-0.0'.

    Unity arrives as the float32 nearest 0.75 (0.74975...), so the taper
    yields a hair below zero and a plain format prints '-0.0 dB' for a
    fader sitting exactly on unity.
    """
    v = round(x, 1)
    if v == 0:
        v = 0.0
    return f"{v:+.1f}"


# ----------------------------------------------------------------- transport

class MR18:
    def __init__(self, host):
        self.host = host
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.s.settimeout(TIMEOUT)

    def send(self, addr, *args):
        self.s.sendto(encode(addr, *args), (self.host, PORT))

    def ask(self, addr, *args):
        self.send(addr, *args)
        for _ in range(6):
            try:
                data, _src = self.s.recvfrom(8192)
            except socket.timeout:
                return None
            a, v = decode(data)
            if a == addr:
                return v
        return None

    def ask_many(self, addrs, rounds=4):
        """Fire every request, collect, then re-ask whatever stayed silent.

        Two reasons this is not a single pass. The mixer drops OSC when
        flooded, so the sends are paced; and a reply lost in transit would
        otherwise print as "-" in a state table, reading as "this channel
        does not exist" when the value was merely lost - the same kind of
        misreport as a blocked probe looking like a dead mixer.
        """
        want = list(dict.fromkeys(addrs))
        out = {}
        for _ in range(rounds):
            missing = [a for a in want if a not in out]
            if not missing:
                break
            for a in missing:
                self.send(a)
                time.sleep(0.002)
            misses = 0
            while len(out) < len(want) and misses < 2:
                try:
                    data, _src = self.s.recvfrom(8192)
                except socket.timeout:
                    misses += 1
                    continue
                a, v = decode(data)
                if a in want and a not in out:
                    out[a] = v
        return out


# ----------------------------------------------------------------- discovery

def _ifconfig():
    try:
        return subprocess.run(["ifconfig"], capture_output=True, text=True,
                              timeout=5).stdout
    except Exception:
        return ""


def broadcast_pairs():
    """[(own_addr, broadcast_addr, ifname)] per broadcast-capable interface.

    The socket must be BOUND to own_addr before sending to broadcast_addr.
    With several interfaces up, macOS otherwise routes a datagram aimed at
    169.254.255.255 by the routing table and tries to ARP it, failing with
    EHOSTDOWN instead of putting it on the wire the mixer is on. Binding
    also avoids the EADDRNOTAVAIL that 255.255.255.255 raises unbound.
    """
    pairs, seen = [], set()
    for block in re.split(r"\n(?=\S)", _ifconfig()):
        if "POINTOPOINT" in block:
            continue
        name = block.split(":", 1)[0].strip()
        for m in re.finditer(
                r"inet (\d+\.\d+\.\d+\.\d+).*?broadcast "
                r"(\d+\.\d+\.\d+\.\d+)", block):
            own, bcast = m.group(1), m.group(2)
            if own.startswith("127.") or (own, bcast) in seen:
                continue
            seen.add((own, bcast))
            pairs.append((own, bcast, name))
    return pairs


def broadcast_targets():
    """Deduplicated broadcast addresses (for display and callers)."""
    out, seen = [], set()
    for _own, bcast, _n in broadcast_pairs():
        if bcast not in seen:
            seen.add(bcast)
            out.append(bcast)
    return out or ["255.255.255.255"]


def local_subnets():
    """Broadcast-capable /24s this Mac is on, as (prefix, own_address).

    Only interfaces that advertise a broadcast address qualify. A VPN
    tunnel (utun*, POINTOPOINT, /32 netmask) has no broadcast domain and
    no mixer behind it, so sweeping it would fire 254 useless datagrams
    into somebody else's network.
    """
    nets = []
    for block in re.split(r"\n(?=\S)", _ifconfig()):
        if "POINTOPOINT" in block:
            continue
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+).*?broadcast", block,
                      re.S)
        if not m or m.group(1).startswith("127."):
            continue
        prefix = m.group(1).rsplit(".", 1)[0]
        if prefix not in [p for p, _ in nets]:
            nets.append((prefix, m.group(1)))
    return nets


def scan(prefixes=None):
    """Unicast /info to every host in each local /24.

    Broadcast discovery is the documented X-Air method, but a switch may
    drop broadcast frames - this does not rely on them. 254 UDP datagrams
    go out in well under a second.
    """
    nets = [(p, None) for p in prefixes] if prefixes else local_subnets()
    if not nets:
        print("no local IPv4 subnet found")
        return {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(TIMEOUT)
    pkt = encode("/info")
    sent = 0
    errs = {}
    for prefix, _own in nets:
        print(f"sweeping {prefix}.1-254 on udp/{PORT} ...")
        for host in range(1, 255):
            try:
                s.sendto(pkt, (f"{prefix}.{host}", PORT))
                sent += 1
            except OSError as e:
                errs[e.strerror] = errs.get(e.strerror, 0) + 1
    for msg, n in errs.items():
        print(f"! {n} sends failed: {msg}")
    found = {}
    misses = 0
    while misses < 10:
        try:
            data, src = s.recvfrom(8192)
        except socket.timeout:
            misses += 1
            continue
        _a, v = decode(data)
        found.setdefault(src[0], [str(x) for x in v])
    # A send that never left the machine (EPERM, EADDRNOTAVAIL) means the
    # result proves nothing. "Host is down" / "No route to host" is just an
    # unused address in the sweep range - expected, and not a reason to
    # distrust the silence from every other host.
    blocked = sum(n for msg, n in errs.items()
                  if msg in ("Operation not permitted",
                             "Can't assign requested address"))
    print(f"# {sent} probes sent, {sum(errs.values())} failed "
          f"({blocked} blocked locally)")
    for ip, v in sorted(found.items()):
        print(f"  {ip}  {' | '.join(v)}")
    if found:
        return found
    if blocked or not sent:
        print("  INCONCLUSIVE - sends were blocked before leaving this "
              "machine, so silence says nothing about the mixer. Re-run "
              "outside the sandbox (prefix the command with `! ` in Claude "
              "Code) or lift the local firewall.")
    else:
        print(f"  CONCLUSIVE - {sent} hosts probed, no OSC device on "
              f"udp/{PORT}. The mixer is not on this subnet.")
    return found


def probe(targets=None, quiet=False):
    """Broadcast /info and /xinfo, one bound socket per interface.

    On a direct cable the mixer's link-local address is random across
    169.254.0.0/16, so broadcast is the only practical discovery - a /24
    sweep would look in the wrong 254 of 65534 addresses.
    """
    if targets:
        legs = [(None, t, "given") for t in targets]
    else:
        legs = [(own, bcast, name)
                for own, bcast, name in broadcast_pairs()]
    if not legs:
        if not quiet:
            print("no broadcast-capable interface is up")
        return {}
    if not quiet:
        shown = ", ".join(f"{b} via {n}" for _o, b, n in legs)
        print(f"probing {shown} on udp/{PORT} ...")

    socks, sent = [], 0
    for own, bcast, name in legs:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(TIMEOUT)
        if own:
            try:
                s.bind((own, 0))
            except OSError as e:
                if not quiet:
                    print(f"  bind {own} ({name}): {e}")
                s.close()
                continue
        ok = False
        for addr in ("/info", "/xinfo"):
            try:
                s.sendto(encode(addr), (bcast, PORT))
                ok = True
                sent += 1
            except OSError as e:
                if not quiet:
                    print(f"  send {addr} -> {bcast} via {name}: {e}")
        if ok:
            socks.append(s)
        else:
            s.close()

    found = {}
    if socks:
        deadline = time.time() + 2.5
        while True:
            left = deadline - time.time()
            if left <= 0:
                break
            ready, _, _ = select.select(socks, [], [], min(left, TIMEOUT))
            for s in ready:
                try:
                    data, src = s.recvfrom(8192)
                except OSError:
                    continue
                _a, v = decode(data)
                found.setdefault(src[0], [str(x) for x in v])
    for s in socks:
        s.close()

    if not quiet:
        for ip, v in sorted(found.items()):
            print(f"  {ip}  {' | '.join(v)}")
        if not found:
            if not sent:
                print("  NOTHING SENT - every interface refused the "
                      "broadcast; this says nothing about the mixer")
            else:
                print("  NO REPLIES - mixer off, unplugged, or not "
                      "answering OSC on this link")
    return found


def resolve(argv, idx):
    """Host from argv[idx], else $MR18_HOST, else probe."""
    if len(argv) > idx:
        return argv[idx]
    env = os.environ.get("MR18_HOST")
    if env:
        return env
    found = probe(quiet=True)
    if not found:
        sys.exit("mixer not found - run `mr18.py probe`, or pass a host")
    host = sorted(found)[0]
    print(f"# using {host}")
    return host


# ------------------------------------------------------------------ commands

def cmd_info(host):
    m = MR18(host)
    for a in ("/xinfo", "/status"):
        v = m.ask(a)
        print(f"{a:10} {' | '.join(str(x) for x in v) if v else '(no reply)'}")


def cmd_state(host):
    """Faders, gains and mutes for the 16 inputs and the three returns.

    There is no /ch/17 or /ch/18: the MR18 has 16 mono channels, a stereo
    aux return (/rtn/aux, no preamp) and two FX returns (/rtn/1, /rtn/2).
    Nor is there a /headamp/17 - the firmware answers ANY out-of-range
    index with a single bogus 0.375 (+15 dB), so an index is only real
    when the reply carries two values, [gain, phantom].
    """
    m = MR18(host)
    chans = [f"{i:02d}" for i in range(1, 17)]
    rtns = [("aux", "/rtn/aux"), ("fx1", "/rtn/1"), ("fx2", "/rtn/2")]

    faders = m.ask_many([f"/ch/{c}/mix/fader" for c in chans]
                        + [f"{p}/mix/fader" for _n, p in rtns])
    mutes = m.ask_many([f"/ch/{c}/mix/on" for c in chans]
                       + [f"{p}/mix/on" for _n, p in rtns])
    heads = m.ask_many([f"/headamp/{c}" for c in chans])

    print(f"{'ch':>4}  {'fader':>15}  {'gain':>9}  {'48V':>4}  state")
    for c in chans:
        f = faders.get(f"/ch/{c}/mix/fader")
        h = heads.get(f"/headamp/{c}")
        on = mutes.get(f"/ch/{c}/mix/on")
        fs = f"{f[0]:.3f} = {fmt_db(fader_db(f[0])):>7} dB" if f else "-"
        # a real headamp replies [gain, phantom]; one value means the
        # index does not exist and the firmware made something up
        if h and len(h) >= 2:
            gs = f"{fmt_db(headamp_db(h[0])):>6} dB"
            ps = "on" if h[1] else "-"
        else:
            gs, ps = "-", "-"
        st = ("ON" if on[0] else "MUTED") if on else "?"
        print(f"{int(c):>4}  {fs:>15}  {gs:>9}  {ps:>4}  {st}")

    for name, path in rtns:
        f = faders.get(f"{path}/mix/fader")
        on = mutes.get(f"{path}/mix/on")
        fs = f"{f[0]:.3f} = {fmt_db(fader_db(f[0])):>7} dB" if f else "-"
        st = ("ON" if on[0] else "MUTED") if on else "?"
        print(f"{name:>4}  {fs:>15}  {'-':>9}  {'-':>4}  {st}")
    print("# aux and fx returns are line level - no preamp to report")


def cmd_monitor(host):
    m = MR18(host)
    addrs = ["/config/solo/source", "/config/solo/level",
             "/config/solo/sourcetrim", "/config/solo/dimatt",
             "/config/solo/dim"]
    got = m.ask_many(addrs)
    for a in addrs:
        v = got.get(a)
        print(f"{a:26} {v[0] if v else '(no reply)'}")
    print("# the phones jack follows this bus and cannot be rerouted")


def cmd_meters(host):
    m = MR18(host)
    m.send("/meters", "/meters/1")
    for _ in range(12):
        try:
            data, _src = m.s.recvfrom(8192)
        except socket.timeout:
            continue
        a, v = decode(data)
        if a.startswith("/meters") and v and isinstance(v[0], bytes):
            blob = v[0]
            n = struct.unpack("<i", blob[:4])[0]
            vals = struct.unpack(f"<{n}h", blob[4:4 + n * 2])
            print("# /meters/1 is PRE-gain: reads below the app's meters")
            for i in range(min(16, n)):
                print(f"  jack {i + 1:>2}  {vals[i] / 256.0:+7.1f} dBFS")
            return
    print("no meter data - the mixer streams these only while subscribed")


def cmd_get(addr, host):
    v = MR18(host).ask(addr)
    if v is None:
        print(f"{addr}  (no reply - check the address; indices are 1-based)")
        return
    out = [f"{x:.4f}" if isinstance(x, float) else str(x) for x in v]
    line = f"{addr}  {' '.join(out)}"
    if addr.endswith("/fader") and isinstance(v[0], float):
        line += f"   = {fmt_db(fader_db(v[0]))} dB"
    elif re.fullmatch(r"/headamp/\d\d", addr) and isinstance(v[0], float):
        line += f"   = {fmt_db(headamp_db(v[0]))} dB"
    print(line)


def cmd_set(addr, raw, host):
    try:
        val = int(raw) if re.fullmatch(r"-?\d+", raw) else float(raw)
    except ValueError:
        val = raw
    m = MR18(host)
    m.send(addr, val)
    back = m.ask(addr)
    print(f"{addr} <- {val!r}   now: {back if back else '(no readback)'}")


# ---------------------------------------------------------------------- main

def main():
    argv = sys.argv[1:]
    cmd = argv[0] if argv else "probe"
    if cmd in ("-h", "--help", "help"):
        print(__doc__)
    elif cmd == "probe":
        probe(argv[1:] or None)
    elif cmd == "scan":
        scan(argv[1:] or None)
    elif cmd == "info":
        cmd_info(resolve(argv, 1))
    elif cmd == "state":
        cmd_state(resolve(argv, 1))
    elif cmd == "monitor":
        cmd_monitor(resolve(argv, 1))
    elif cmd == "meters":
        cmd_meters(resolve(argv, 1))
    elif cmd == "get":
        if len(argv) < 2:
            sys.exit("usage: mr18.py get <addr> [host]")
        cmd_get(argv[1], resolve(argv, 2))
    elif cmd == "set":
        if len(argv) < 3:
            sys.exit("usage: mr18.py set <addr> <value> [host]")
        cmd_set(argv[1], argv[2], resolve(argv, 3))
    else:
        sys.exit(f"unknown command {cmd!r} - see mr18.py --help")


if __name__ == "__main__":
    main()
