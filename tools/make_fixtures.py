#!/usr/bin/env python3
"""Generate a synthetic classic mobile QQ database for tests and examples.

Every value here is invented. The owner is account 10000, the friends are 10001 and 10002, the
group is 20001, and the message text is self evidently a fixture. The field cipher uses the
synthetic key SYNTHKEY01234AB, never the real one. A real chat row cannot be produced by this
generator, so pasting a real message in as a shortcut would stand out immediately and would not
survive review.

The output database has the same shape the decoder reads from a real device: a plain SQLite file
whose message tables are named by the uppercase md5 of the peer identifier, whose text messages
carry msgtype -1000, and whose msgData and account columns are XOR obfuscated.

Usage: python make_fixtures.py [out_path]   (default tools/fixtures/synthetic_qq.db)
"""
import hashlib
import os
import sqlite3
import sys

from qq_field_cipher import encode_field

SYNTH_KEY = b"SYNTHKEY01234AB"   # 15 bytes, obviously not a real key
OWNER = "10000"

# (table_kind, peer_id, [(issend, sender, text, ts)])
CONVERSATIONS = [
    ("friend", "10001", [
        (2, "10000", "这是一条合成的自己发出的短消息", 1700000001),
        (1, "10001", "这是一条合成的对方回复消息，长度稍微长一点用来覆盖多个周期的解码", 1700000002),
        (2, "10000", "好的收到，合成消息用于自检", 1700000003),
    ]),
    ("friend", "10002", [
        (1, "10002", "合成好友二发来的一句话", 1700000101),
        (2, "10000", "回复合成好友二，这里再补一段较长的文本确保跨越十五字节的密钥周期若干次", 1700000102),
    ]),
    ("troop", "20001", [
        (2, "10000", "合成群里自己发的一条", 1700000201),
        (1, "10003", "合成群友发的一条", 1700000202),
    ]),
]


def table_name(kind: str, peer: str) -> str:
    md5 = hashlib.md5(peer.encode()).hexdigest().upper()
    return "mr_%s_%s_New" % (kind, md5)


def build(out_path: str) -> None:
    d = os.path.dirname(out_path)
    if d:
        os.makedirs(d, exist_ok=True)
    if os.path.exists(out_path):
        os.remove(out_path)
    db = sqlite3.connect(out_path)
    c = db.cursor()
    uniseq = 1
    for kind, peer, msgs in CONVERSATIONS:
        tn = table_name(kind, peer)
        c.execute(
            "CREATE TABLE '%s' (uniseq INTEGER, msgtype INTEGER, issend INTEGER, "
            "time INTEGER, senderuin BLOB, selfuin BLOB, frienduin BLOB, msgData BLOB)" % tn)
        for issend, sender, text, ts in msgs:
            c.execute(
                "INSERT INTO '%s' (uniseq, msgtype, issend, time, senderuin, selfuin, frienduin, "
                "msgData) VALUES (?,?,?,?,?,?,?,?)" % tn,
                (uniseq, -1000, issend, ts,
                 encode_field(sender.encode(), SYNTH_KEY),
                 encode_field(OWNER.encode(), SYNTH_KEY),
                 encode_field(peer.encode(), SYNTH_KEY),
                 encode_field(text.encode("utf-8"), SYNTH_KEY)))
            uniseq += 1
    db.commit()
    db.close()


def main():
    import argparse
    ap = argparse.ArgumentParser(description="build a synthetic classic QQ database")
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "fixtures"),
        help="output directory the fixture database is written into")
    a = ap.parse_args()
    out = os.path.join(a.out, "synthetic_qq.db")
    build(out)
    print("wrote synthetic QQ database ->", out)
    print("owner", OWNER, "key", SYNTH_KEY.decode(), "period", len(SYNTH_KEY))


if __name__ == "__main__":
    main()
