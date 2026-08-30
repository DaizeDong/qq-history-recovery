#!/usr/bin/env python3
"""Recover the field cipher key by reading decoded messages out of a running QQ client.

Why this exists: the database stores msgData obfuscated, and the key cannot be recovered reliably
from the database alone. But the running client has already decoded messages in memory. Each
in memory MessageRecord carries the plain text in its msg field and its uniseq, and the same
uniseq keys the encrypted row in the database. One long message gives an aligned plain, cipher pair,
and the repeating key falls straight out of the XOR.

Bootstrap once, then decode the whole database offline with tools/qq_decode.py. The client only has
to be running; nothing is written to it and nothing is patched.

Requirements: frida 16.x on both sides. Frida 17 removed the Java bridge from the injected agent,
so `Java` is undefined and this cannot work. The device ships frida-server-16 for exactly this
reason. See docs/REVERSE_ENGINEERING.md.
"""
import argparse
import sqlite3
import sys
import time

from qq_field_cipher import detect_period_from_known_plaintext
from qq_decode import decode_rate

MAIN_PROCESS = "com.tencent.mobileqq"

# Read decoded (uniseq, msg) pairs out of every loaded MessageFor* instance on the Java heap.
JS = r"""
if (typeof Java === 'undefined') {
  send({fatal: "Java bridge missing. Use frida 16.x; frida 17 dropped the built in Java bridge."});
} else {
  Java.perform(function () {
    var subs = [];
    Java.enumerateLoadedClasses({
      onMatch: function (n) {
        if (/com\.tencent\.mobileqq\.data\.MessageFor[A-Za-z]+$/.test(n)) subs.push(n);
      },
      onComplete: function () {
        subs.forEach(function (cn) {
          try {
            Java.choose(cn, {
              onMatch: function (inst) {
                try {
                  var msg = inst.msg.value;
                  if (msg && msg.length > 0) {
                    send({uniseq: inst.uniseq.value.toString(), msg: msg});
                  }
                } catch (e) {}
              },
              onComplete: function () {}
            });
          } catch (e) {}
        });
        send({done: true});
      }
    });
  });
}
"""


def _db_ciphertext_by_uniseq(db_path):
    db = sqlite3.connect(db_path)
    db.text_factory = bytes
    cur = db.cursor()
    out = {}
    tables = [r[0].decode() for r in
              cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for t in tables:
        if not (t.startswith("mr_friend") or t.startswith("mr_troop")):
            continue
        q = "SELECT uniseq, msgData FROM '%s' WHERE msgtype=-1000 AND msgData IS NOT NULL" % t
        for uniseq, md in cur.execute(q):
            if md:
                out[str(uniseq)] = bytes(md)
    db.close()
    return out


def _collect_memory_pairs(host, pid, seconds):
    import frida
    dev = frida.get_device_manager().add_remote_device(host)
    session = dev.attach(pid) if pid else dev.attach(MAIN_PROCESS)
    script = session.create_script(JS)
    pairs = {}
    state = {"done": False, "fatal": None}

    def on_message(message, data):
        if message.get("type") == "send":
            p = message["payload"]
            if p.get("fatal"):
                state["fatal"] = p["fatal"]
            elif p.get("done"):
                state["done"] = True
            elif p.get("uniseq"):
                pairs[p["uniseq"]] = p["msg"]
        elif message.get("type") == "error":
            state["fatal"] = message.get("description")

    script.on("message", on_message)
    script.load()
    for _ in range(seconds):
        time.sleep(1)
        if state["done"] or state["fatal"]:
            break
    try:
        session.detach()
    except Exception:
        pass
    if state["fatal"]:
        raise RuntimeError(state["fatal"])
    return pairs


def recover_key(db_path, host="127.0.0.1:27044", pid=0, seconds=20, max_period=64):
    """Recover the repeating field key. Returns (key_bytes, coverage_float)."""
    mem = _collect_memory_pairs(host, pid, seconds)
    if not mem:
        raise RuntimeError("no decoded messages in memory. Open QQ and let a chat load, then retry.")
    cipher_by_uniseq = _db_ciphertext_by_uniseq(db_path)
    # aligned pairs, longest first: a longer known plaintext pins a longer period unambiguously
    aligned = []
    for uniseq, text in mem.items():
        ct = cipher_by_uniseq.get(uniseq)
        if ct:
            aligned.append((uniseq, text.encode("utf-8"), ct))
    if not aligned:
        raise RuntimeError("no uniseq overlap between memory and database. Wrong database for this "
                           "account, or no loaded message is also stored locally.")
    aligned.sort(key=lambda a: -min(len(a[1]), len(a[2])))
    _, plain, cipher = aligned[0]
    key = detect_period_from_known_plaintext(cipher, plain, max_period=max_period)
    coverage = decode_rate(db_path, key)
    return key, coverage


def main():
    ap = argparse.ArgumentParser(description="recover the QQ field key from a running client")
    ap.add_argument("--db", required=True, help="path to the pulled <uin>.db")
    ap.add_argument("--host", default="127.0.0.1:27044", help="frida remote device host:port")
    ap.add_argument("--pid", type=int, default=0, help="QQ main process pid (0 = resolve by name)")
    ap.add_argument("--seconds", type=int, default=20, help="how long to scan the heap")
    a = ap.parse_args()
    try:
        key, coverage = recover_key(a.db, a.host, a.pid, a.seconds)
    except Exception as e:
        sys.stderr.write("ERROR: %s\n" % e)
        return 1
    if coverage < 0.9:
        sys.stderr.write("ERROR: recovered a key that only covers %.0f%% of messages. The longest "
                         "known plaintext was too short to pin the period. Load a longer chat and "
                         "retry.\n" % (coverage * 100))
        return 1
    # the key is ascii digits in practice; print it plainly so the operator can pass it to qq_decode
    try:
        shown = key.decode("ascii")
    except UnicodeDecodeError:
        shown = key.hex()
    print("recovered key: %s  (period %d, coverage %.0f%%)" % (shown, len(key), coverage * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
