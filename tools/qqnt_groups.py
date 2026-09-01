#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read the group roster out of a QQNT group_info.db: which groups you are in and how big each one is.

Why this exists: a corpus built from someone's own words wants the small private groups and not the
thousand member ones, and the message store alone cannot tell them apart. Counting distinct speakers in
the log is only a lower bound, because most members of a large group never say anything; measured here,
a group with 659 speakers in the log and a group with 8 both look like "some speakers" until you ask how
many members they actually have.

group_info.db is the same Tencent wrapped SQLCipher 4 format as nt_msg.db under the same key, so the
existing decryptor opens it unchanged.

The schema uses numeric column names again, told apart by their value distributions on a real store:
  table group_list, one row per group you are in
  column "60001" the group number, and it joins to the conv id in decoded group messages
  column "60006" the current member count, median 153, ranging 3 to 2986. This is the number you want.
  column "60005" the group's capacity tier, only ever 200, 500, 1000, 2000 or 3000, which is what a
                 group can hold and not what it holds. Reading it as the size would call every small
                 group a two hundred person one.
  table group_member3 also exists with one row per member, so a count per group agrees with 60006; it
                 is the fallback when group_list is missing.

Usage:
  python tools/qqnt_groups.py --db group_info.db --key "<16 char key>" --out ~/qq-out/groups.json
  python tools/qqnt_groups.py --db group_info_plain.db --out ~/qq-out/groups.json
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
COL_GID, COL_SIZE, COL_CAP = "60001", "60006", "60005"


def looks_encrypted(path):
    with open(path, "rb") as f:
        return f.read(16) != b"SQLite format 3\x00"


def decrypt(src, key):
    if not key:
        raise SystemExit("this database is encrypted; pass --key or set $QQNT_KEY")
    tmp = tempfile.mkdtemp(prefix="qqgroups_")
    copy = os.path.join(tmp, "in.db")
    shutil.copy2(src, copy)
    plain = os.path.join(tmp, "plain.db")
    r = subprocess.run([sys.executable, os.path.join(HERE, "qqnt_decrypt.py"),
                        "--in", copy, "--out", plain, "--key", key],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not os.path.exists(plain):
        shutil.rmtree(tmp, ignore_errors=True)
        raise SystemExit("decryption failed: %s" % ((r.stderr or r.stdout or "").strip()[:300]))
    return plain, tmp


def read_groups(plain):
    c = sqlite3.connect(plain)
    out = {}
    try:
        for gid, size, cap in c.execute("select [%s],[%s],[%s] from group_list" % (COL_GID, COL_SIZE, COL_CAP)):
            gid = str(gid)
            if not re.fullmatch(r"\d+", gid):
                continue
            out[gid] = {"members": int(size) if isinstance(size, int) else None,
                        "capacity": int(cap) if isinstance(cap, int) else None,
                        "source": "group_list"}
    except sqlite3.DatabaseError:
        pass
    try:
        # Fallback and cross check: one row per member. Only fills groups group_list did not cover, so a
        # partially synced roster cannot silently overwrite the number the client itself reports.
        for gid, n in c.execute("select [%s], count(*) from group_member3 group by [%s]" % (COL_GID, COL_GID)):
            gid = str(gid)
            if not re.fullmatch(r"\d+", gid) or gid in out:
                continue
            out[gid] = {"members": int(n), "capacity": None, "source": "group_member3"}
    except sqlite3.DatabaseError:
        pass
    finally:
        c.close()
    if not out:
        raise SystemExit("no groups found; the schema may have changed, refusing to report an empty roster as success")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="group_info.db, encrypted or already decrypted")
    ap.add_argument("--key", default=os.environ.get("QQNT_KEY"))
    ap.add_argument("--out", help="output json path (must be outside this repo)")
    a = ap.parse_args()
    tmp = None
    src = a.db
    if looks_encrypted(src):
        src, tmp = decrypt(src, a.key)
    try:
        groups = read_groups(src)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    sizes = sorted(g["members"] for g in groups.values() if g["members"])
    small = sum(1 for s in sizes if s < 20)
    print("%d groups, member count median %d, smallest %d, largest %d; %d have fewer than 20 members"
          % (len(groups), sizes[len(sizes) // 2] if sizes else 0,
             sizes[0] if sizes else 0, sizes[-1] if sizes else 0, small))
    if not a.out:
        return 0
    dest = os.path.abspath(os.path.expanduser(a.out))
    if dest.startswith(REPO + os.sep):
        sys.stderr.write("ERROR: refusing to write the group roster inside the repo. It is DATA.\n")
        return 2
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False)
    print("wrote %s" % dest)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
