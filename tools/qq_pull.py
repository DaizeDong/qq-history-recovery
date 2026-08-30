#!/usr/bin/env python3
"""Pull the classic mobile QQ message database off a rooted device or emulator over adb.

The database is one plain SQLite file per logged in account at
  /data/data/com.tencent.mobileqq/databases/<uin>.db
This copies it to a local path outside the repo. It reads only; it changes nothing on the device.

The owner account number is the database file name. If several accounts have logged in, this lists
them and you pick one with --uin.

Notes for emulators (learned on MEmu): `adb shell` is already root there, and wrapping commands in
`su -c` can hang the shell, so this uses plain `adb shell`. On a real device that is not rooted this
cannot reach the database at all, which is expected.
"""
import argparse
import os
import subprocess
import sys

DB_DIR = "/data/data/com.tencent.mobileqq/databases"


def adb(serial, *args):
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True)


def list_account_dbs(serial):
    r = adb(serial, "shell", "ls %s" % DB_DIR)
    names = []
    for line in r.stdout.replace("\r", "").split("\n"):
        line = line.strip()
        # account databases are named <digits>.db, not the many helper databases
        if line.endswith(".db") and line[:-3].isdigit():
            names.append(line[:-3])
    return names


def main():
    ap = argparse.ArgumentParser(description="pull the classic QQ database over adb")
    ap.add_argument("--serial", default="", help="adb device serial (e.g. 127.0.0.1:21503)")
    ap.add_argument("--uin", default="", help="account number to pull (default: the only one)")
    ap.add_argument("--out", required=True, help="local output path (must be outside this repo)")
    a = ap.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.abspath(a.out).startswith(repo):
        sys.stderr.write("ERROR: refusing to pull the database into the repo. It is DATA; put it "
                         "outside this repository.\n")
        return 2

    accounts = list_account_dbs(a.serial)
    if not accounts:
        sys.stderr.write("ERROR: no <uin>.db found under %s. Is the device rooted, is QQ installed, "
                         "and has an account logged in?\n" % DB_DIR)
        return 1
    uin = a.uin or (accounts[0] if len(accounts) == 1 else "")
    if not uin:
        sys.stderr.write("Several accounts are present, pick one with --uin:\n  %s\n"
                         % "\n  ".join(accounts))
        return 1
    if uin not in accounts:
        sys.stderr.write("ERROR: account %s not among %s\n" % (uin, accounts))
        return 1

    src = "%s/%s.db" % (DB_DIR, uin)
    # copy to a world readable spot first, then pull, then remove the copy
    staging = "/sdcard/qq_pull_%s.db" % uin
    adb(a.serial, "shell", "cp '%s' %s" % (src, staging))
    adb(a.serial, "shell", "chmod 666 %s" % staging)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    r = adb(a.serial, "pull", staging, a.out)
    adb(a.serial, "shell", "rm -f %s" % staging)
    if not os.path.exists(a.out) or os.path.getsize(a.out) < 2048:
        sys.stderr.write("ERROR: pull failed or file too small.\n%s\n" % r.stdout)
        return 1
    print("pulled account %s -> %s (%d bytes)" % (uin, a.out, os.path.getsize(a.out)))
    print("owner uin: %s" % uin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
