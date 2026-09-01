#!/usr/bin/env python3
"""Extract text messages from a decrypted QQNT nt_msg.db into structured records.

Run this on the PLAINTEXT database that ntdecrypt produced (see docs/JOURNEY.md), never on the
encrypted original. It reads the private table c2c_msg_table and the group table group_msg_table,
pulls the owner's and the peers' text out of the protobuf message column, and writes one JSON object
per text message.

The message store uses numeric column names and a protobuf content column. The columns that matter:
  40020  sender uid (a u_... string, not a uin)
  40030  peer uin for a private chat, or the group number for a group chat
  40050  send time, unix seconds
  40800  the message content, a protobuf whose text elements carry the text in field 45101
The owner is the uid that appears as sender across every conversation, so it is simply the most
common 40020 value. A quoted reply keeps the original text under field 47423, which is skipped so a
reply does not re-import the message it answers.

Record shape (one per text message):
  {"text", "is_me", "ctx": "dm"|"group", "ts", "sender", "conv", "is_forward": false}

No real identifier appears in this file. Any example uid or uin is synthetic.
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import Counter

TEXT_FIELD = 45101      # protobuf field carrying a text element's UTF-8 content
QUOTE_FIELD = 47423     # a reply's quoted original; skipped so replies do not re-import quotes


def _uvarint(b, i):
    r = s = 0
    while i < len(b):
        x = b[i]; r |= (x & 0x7f) << s; i += 1
        if not x & 0x80:
            return r, i
        s += 7
        if s > 63:
            return None, i
    return None, i


def _collect_text(b, out):
    """Walk a protobuf blob, appending every field-45101 UTF-8 string, never descending a quote."""
    i = 0
    while i < len(b):
        tag, i = _uvarint(b, i)
        if tag is None:
            return
        fn, wt = tag >> 3, tag & 7
        if wt == 0:
            _, i = _uvarint(b, i)
            if _ is None:
                return
        elif wt == 2:
            ln, i = _uvarint(b, i)
            if ln is None or i + ln > len(b):
                return
            val = b[i:i + ln]; i += ln
            if fn == TEXT_FIELD:
                try:
                    s = val.decode("utf-8")
                    if s.strip():
                        out.append(s)
                except UnicodeDecodeError:
                    pass
            elif fn == QUOTE_FIELD:
                continue
            elif ln >= 2 and (val[0] & 0x07) in (0, 2, 5) and val[0] >= 8:
                _collect_text(val, out)          # a nested element container
        elif wt == 5:
            i += 4
        elif wt == 1:
            i += 8
        else:
            return


def message_text(blob):
    out = []
    _collect_text(blob, out)
    return " ".join(out).strip()


def owner_uid(cur):
    """The owner's uid is the sender that appears across the most private messages."""
    counts = Counter()
    for (u,) in cur.execute('SELECT "40020" FROM c2c_msg_table WHERE "40020" IS NOT NULL'):
        counts[bytes(u)] += 1
    if not counts:
        raise RuntimeError("no senders in c2c_msg_table; is this a decrypted QQNT db?")
    return counts.most_common(1)[0][0]


def _rows(cur, table, ctx, owner):
    q = ('SELECT "40800", "40020", "40030", "40050" FROM %s WHERE "40800" IS NOT NULL' % table)
    for blob, sender, conv, ts in cur.execute(q):
        text = message_text(bytes(blob))
        if not text:
            continue
        is_me = bytes(sender) == owner if sender is not None else False
        yield {
            "text": text,
            "is_me": bool(is_me),
            "ctx": ctx,
            "ts": int(ts) if ts is not None else None,
            "sender": "qq_me" if is_me else ("qq_" + (bytes(sender).decode("latin1") if sender else "unknown")),
            "conv": "qq_%s" % (conv if conv is not None else "unknown"),
            "is_forward": False,
        }


def main():
    ap = argparse.ArgumentParser(description="extract text messages from a decrypted QQNT nt_msg.db")
    ap.add_argument("--db", required=True, help="path to the DECRYPTED nt_msg.db (plaintext SQLite)")
    ap.add_argument("--out", required=True, help="output jsonl path (must be outside this repo)")
    ap.add_argument("--groups", action="store_true",
                    help="also read group_msg_table. Off by default: measured on a real store, groups "
                         "were 466163 of 575119 messages but held only 1231 of the owner's own 48523, "
                         "so they are four fifths of the volume and under three percent of what the "
                         "owner actually wrote. Turn it on when the group traffic itself is the point.")
    a = ap.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.abspath(a.out).startswith(repo):
        sys.stderr.write("ERROR: refusing to write decoded chat history inside the repo. It is DATA.\n")
        return 2

    db = sqlite3.connect(a.db)
    db.text_factory = bytes
    cur = db.cursor()
    owner = owner_uid(cur)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    n = me = 0
    with open(a.out, "w", encoding="utf-8") as f:
        tables = [("c2c_msg_table", "dm")]
        if a.groups:
            tables.append(("group_msg_table", "group"))
        for table, ctx in tables:
            for rec in _rows(cur, table, ctx, owner):
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
                me += 1 if rec["is_me"] else 0
    db.close()
    print("extracted %d text messages (%d yours, %d others) -> %s" % (n, me, n - me, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
