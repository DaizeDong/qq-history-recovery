#!/usr/bin/env python3
"""Resolve QQNT uids to human names by extracting the contact table from profile_info.db.

A decoded message from tools/qqnt_decode.py identifies the other party only by a QQNT uid, a string
shaped like u_SyntheticUid0000000000. That is unreadable: you cannot tell from it who you were talking
to. The names are not missing from the export, they were never in the message store. They live one file
over, in `profile_info.db`, in the same `nt_qq\\nt_db\\` directory as `nt_msg.db`, and that file is the
same Tencent wrapped SQLCipher 4 format with the same parameters and the same 16 character client key.
So tools/qqnt_decrypt.py opens it unchanged, and this tool shells out to it rather than reimplementing
any decryption.

The schema uses numeric column names, like the message store does. In table `profile_info_v6`:
  1000    the QQNT uid, the join key, the same u_ prefixed string that appears as a message sender
  20002   nickname. Almost every row has one. This is the display name.
  20009   the OWNER's private remark for that contact. Only real friends get one, so most rows are
          empty, and when it is present it is the better name to show.
  20011   the contact's signature line. NOT a name. It is longer prose and must never be used as one.
Table `buddy_list` holds only the accepted friends, keyed by the same uid in column 1000. Pass
--friends-only to restrict the mapping to it.

Resolution order: remark, then nickname, then the raw uid. The uid survives when neither name exists,
because an unresolved id is honest and a guessed name is not. Showing one person's name over another
person's messages is worse than showing no name at all, so this tool never infers a name from anything
but those two columns.

The mapping is real identity data. It is DATA under .dataclass.json, so it is written outside this
repository, by default under the private companion directory that tools/datadir.py resolves. The key
comes from the command line or $QQNT_KEY and is never written to any file. The decrypted plaintext
copy of profile_info.db is deleted after extraction unless you pass --keep-plain.

Usage: python qqnt_contacts.py --db profile_info.db --key "<16 char key>" --out ~/qq-out/contacts.json
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# datadir moved into the guards submodule: one copy for the fleet instead of one per repo,
# which had already begun to drift. The insert above stays, because sibling modules in this
# same tools/ directory are still imported by bare name.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "guards", "tools"))
import datadir

SKILL = "qq-history-recovery"
TABLE = "profile_info_v6"
BUDDY_TABLE = "buddy_list"
UID_COL = "1000"
NICK_COL = "20002"
REMARK_COL = "20009"

PLAIN_MAGIC = b"SQLite format 3\x00"


def _text(v):
    """Column values arrive as str, bytes or None. Return a clean str, or an empty string."""
    if v is None:
        return ""
    if isinstance(v, bytes):
        v = v.decode("utf-8", "replace")
    return str(v).strip()


def resolve_name(uid, nick, remark):
    """Pick the name to show, and say where it came from. Never invents one.

    Returns (name, source) where source is "remark", "nick", or "uid" when neither name exists.
    """
    if remark:
        return remark, "remark"
    if nick:
        return nick, "nick"
    return uid, "uid"


def _columns(cur, table):
    return {row[1] for row in cur.execute('PRAGMA table_info("%s")' % table)}


def _friend_uids(cur):
    """The uid set from buddy_list, or None when the table is absent."""
    try:
        cols = _columns(cur, BUDDY_TABLE)
    except sqlite3.DatabaseError:
        return None
    if UID_COL not in cols:
        return None
    out = set()
    for (u,) in cur.execute('SELECT "%s" FROM "%s"' % (UID_COL, BUDDY_TABLE)):
        u = _text(u)
        if u:
            out.add(u)
    return out


def extract_contacts(db_path, friends_only=False):
    """Read profile_info_v6 out of a DECRYPTED profile db into {uid: {name, nick, remark, source}}.

    Later rows for the same uid win, since the store keeps the newest profile last.
    """
    conn = sqlite3.connect(db_path)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    cur = conn.cursor()
    try:
        cols = _columns(cur, TABLE)
        if UID_COL not in cols:
            raise RuntimeError(
                "table %s has no column %s; is this a decrypted profile_info.db?" % (TABLE, UID_COL))
        keep = _friend_uids(cur) if friends_only else None
        if friends_only and keep is None:
            raise RuntimeError("--friends-only was asked for but %s is not in this database" % BUDDY_TABLE)
        nick_sel = '"%s"' % NICK_COL if NICK_COL in cols else "NULL"
        remark_sel = '"%s"' % REMARK_COL if REMARK_COL in cols else "NULL"
        q = 'SELECT "%s", %s, %s FROM "%s"' % (UID_COL, nick_sel, remark_sel, TABLE)
        out = {}
        for uid, nick, remark in cur.execute(q):
            uid = _text(uid)
            if not uid:
                continue
            if keep is not None and uid not in keep:
                continue
            nick = _text(nick)
            remark = _text(remark)
            name, source = resolve_name(uid, nick, remark)
            out[uid] = {"name": name, "nick": nick, "remark": remark, "source": source}
        return out
    finally:
        conn.close()


def _is_plaintext(path):
    with open(path, "rb") as f:
        return f.read(16) == PLAIN_MAGIC


def decrypt_profile_db(src, dst, key):
    """Run tools/qqnt_decrypt.py on the profile db. Same format, same params, no second decryptor."""
    tool = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qqnt_decrypt.py")
    rc = subprocess.call([sys.executable, tool, "--in", src, "--out", dst, "--key", key])
    if rc != 0:
        raise RuntimeError("qqnt_decrypt.py failed with exit code %d" % rc)


def main():
    ap = argparse.ArgumentParser(description="extract a uid to name mapping from a QQNT profile_info.db")
    ap.add_argument("--db", required=True, help="path to profile_info.db, encrypted or already decrypted")
    ap.add_argument("--out", help="output json path (must be outside this repo); "
                                  "defaults to contacts.json in the private data dir")
    ap.add_argument("--key", help="the 16 character passphrase from the client; "
                                  "or set $QQNT_KEY. Not needed if --db is already plaintext")
    ap.add_argument("--friends-only", action="store_true",
                    help="keep only uids present in buddy_list")
    ap.add_argument("--keep-plain", action="store_true",
                    help="keep the decrypted profile database instead of deleting it")
    a = ap.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if a.out:
        out = os.path.abspath(a.out)
        if out.startswith(repo):
            sys.stderr.write("ERROR: refusing to write a contact mapping inside the repo. It is DATA.\n")
            return 2
    else:
        try:
            out = str(datadir.data_path(SKILL, "contacts.json"))
        except datadir.DataDirNotInitialized as e:
            sys.stderr.write("ERROR: %s\n" % e)
            return 2

    plain = _is_plaintext(a.db)
    key = a.key or os.environ.get("QQNT_KEY", "")
    if not plain and not key:
        sys.stderr.write("ERROR: %s is encrypted, so it needs --key or $QQNT_KEY.\n" % a.db)
        return 2

    tmp = out + ".profile_plain.db"
    made_tmp = False
    try:
        if plain:
            print("input is already plaintext, decoding it directly")
            src = a.db
        else:
            decrypt_profile_db(a.db, tmp, key)
            made_tmp = True
            src = tmp
        contacts = extract_contacts(src, friends_only=a.friends_only)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(contacts, f, ensure_ascii=False, indent=1, sort_keys=True)
    except (RuntimeError, sqlite3.DatabaseError) as e:
        # An unreadable profile db is a failure, never an empty mapping: a mapping that silently
        # came back with nothing looks identical to a store that had no names in it.
        sys.stderr.write("ERROR: %s\n" % e)
        return 1
    finally:
        if made_tmp and not a.keep_plain and os.path.exists(tmp):
            os.remove(tmp)

    by = {"remark": 0, "nick": 0, "uid": 0}
    for rec in contacts.values():
        by[rec["source"]] += 1
    print("mapped %d uids (%d by remark, %d by nickname, %d unresolved) -> %s"
          % (len(contacts), by["remark"], by["nick"], by["uid"], out))
    if made_tmp and a.keep_plain:
        print("kept the decrypted profile database at %s; it is DATA, delete it when done" % tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
