#!/usr/bin/env python3
"""Decode a classic mobile QQ message database into structured records.

The database is a plain SQLite file. This module reads it, decodes the obfuscated message and
account columns with a repeating XOR key, and returns one record per text message. It never writes
back to the source and never contacts the network.

The key is supplied by the caller. Recover it with tools/qq_keyfind.py against a running client, or
pass a known key. See docs/REVERSE_ENGINEERING.md for why the key cannot be guessed reliably from
the database alone.

Record shape (one per msgtype -1000 message with text):
  {"text", "is_me", "ctx": "dm"|"group", "ts", "sender", "conv", "uniseq"}
"""
import argparse
import json
import os
import sqlite3
import sys

from qq_field_cipher import decode_field

TEXT_MSGTYPE = -1000


def _tables(cur):
    rows = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    out = []
    for (name,) in rows:
        n = name.decode() if isinstance(name, bytes) else name
        if n.startswith("mr_friend"):
            out.append((n, "dm"))
        elif n.startswith("mr_troop"):
            out.append((n, "group"))
    return out


def _dec_text(blob, key):
    if not blob:
        return None
    try:
        return decode_field(bytes(blob), key).decode("utf-8")
    except UnicodeDecodeError:
        return None


def decode_db(db_path: str, key: bytes, owner_uin: str):
    """Yield decoded records from a classic QQ database. Read only."""
    db = sqlite3.connect(db_path)
    db.text_factory = bytes
    cur = db.cursor()
    try:
        for table, ctx in _tables(cur):
            conv = "qq_" + table.split("_")[2][:12]
            q = ("SELECT issend, msgData, senderuin, time, uniseq FROM '%s' "
                 "WHERE msgtype=? AND msgData IS NOT NULL" % table)
            for issend, md, su, ts, uniseq in cur.execute(q, (TEXT_MSGTYPE,)):
                text = _dec_text(md, key)
                if not text or not text.strip():
                    continue
                sender = _dec_text(su, key) if su else None
                is_me = (issend == 2) or (sender == owner_uin)
                yield {
                    "text": text,
                    "is_me": bool(is_me),
                    "ctx": ctx,
                    "ts": int(ts) if ts is not None else None,
                    "sender": "qq_me" if is_me else ("qq_" + (sender or "unknown")),
                    "conv": conv,
                    "uniseq": str(uniseq),
                }
    finally:
        db.close()


def decode_rate(db_path: str, key: bytes) -> float:
    """Fraction of text messages that decode to valid UTF-8 with this key. A correct key gives a
    rate at or near 1.0; a wrong key gives a rate near 0. Used to validate a recovered key."""
    db = sqlite3.connect(db_path)
    db.text_factory = bytes
    cur = db.cursor()
    total = ok = 0
    try:
        for table, _ in _tables(cur):
            q = ("SELECT msgData FROM '%s' WHERE msgtype=? AND msgData IS NOT NULL" % table)
            for (md,) in cur.execute(q, (TEXT_MSGTYPE,)):
                if not md:
                    continue
                total += 1
                try:
                    decode_field(bytes(md), key).decode("utf-8")
                    ok += 1
                except UnicodeDecodeError:
                    pass
    finally:
        db.close()
    return ok / total if total else 0.0


def main():
    ap = argparse.ArgumentParser(description="decode a classic QQ message database")
    ap.add_argument("--db", required=True, help="path to the pulled <uin>.db")
    ap.add_argument("--key", required=True, help="repeating XOR key (ascii)")
    ap.add_argument("--owner", required=True, help="owner account number")
    ap.add_argument("--out", required=True, help="output jsonl path (must be outside this repo)")
    a = ap.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.abspath(a.out).startswith(repo):
        sys.stderr.write("ERROR: refusing to write decoded chat history inside the repo. "
                         "Decoded messages are DATA; write them outside this repository.\n")
        return 2

    key = a.key.encode()
    rate = decode_rate(a.db, key)
    if rate < 0.9:
        sys.stderr.write("ERROR: only %.0f%% of messages decode with this key. The key is wrong "
                         "or the database is not classic QQ.\n" % (rate * 100))
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    n = me = 0
    with open(a.out, "w", encoding="utf-8") as f:
        for rec in decode_db(a.db, key, a.owner):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
            me += 1 if rec["is_me"] else 0
    print("decoded %d text messages (%d yours, %d others) at %.0f%% key coverage -> %s"
          % (n, me, n - me, rate * 100, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
