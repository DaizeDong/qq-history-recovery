#!/usr/bin/env python3
"""Unit tests for the QQNT contact extractor, on a synthetic profile database with no real data.

The database is built here with the same numeric column names the real store uses, so the tests prove
the resolution order without needing a real profile_info.db and without any real identifier. Every uid,
nickname and remark below is invented.

These tests can fail: the signature case asserts that column 20011 never becomes a name, so an
extractor that treated any populated column as a display name would be caught here.
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qqnt_contacts import extract_contacts, resolve_name

UID_BOTH = "u_SyntheticUid0000000001"      # has a remark and a nickname
UID_NICK = "u_SyntheticUid0000000002"      # nickname only
UID_BARE = "u_SyntheticUid0000000003"      # neither, only a signature
UID_STRANGER = "u_SyntheticUid0000000004"  # nickname, but not in buddy_list

ROWS = [
    (UID_BOTH, "AcmeUser", "AcmeRemark", "signature line for the both case"),
    (UID_NICK, "AcmeNickOnly", "", "signature line for the nick case"),
    (UID_BARE, "", "", "a signature is prose, not a name, and must never be used as one"),
    (UID_STRANGER, "AcmeStranger", "", ""),
]


def _fixture(with_buddy_list=True):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "synthetic_profile_info.db")
    db = sqlite3.connect(p)
    db.execute('CREATE TABLE profile_info_v6 ("1000" TEXT, "20002" TEXT, "20009" TEXT, "20011" TEXT)')
    db.executemany('INSERT INTO profile_info_v6 VALUES (?,?,?,?)', ROWS)
    if with_buddy_list:
        db.execute('CREATE TABLE buddy_list ("1000" TEXT)')
        db.executemany('INSERT INTO buddy_list VALUES (?)',
                       [(UID_BOTH,), (UID_NICK,), (UID_BARE,)])
    db.commit()
    db.close()
    return p


def test_remark_beats_nick():
    c = extract_contacts(_fixture())
    rec = c[UID_BOTH]
    assert rec["name"] == "AcmeRemark", "remark must win, got %r" % rec["name"]
    assert rec["source"] == "remark", rec["source"]
    assert rec["nick"] == "AcmeUser", "the nickname must still be carried, got %r" % rec["nick"]
    print("[test] remark_beats_nick OK")


def test_nick_when_no_remark():
    c = extract_contacts(_fixture())
    rec = c[UID_NICK]
    assert rec["name"] == "AcmeNickOnly", rec["name"]
    assert rec["source"] == "nick", rec["source"]
    assert rec["remark"] == "", rec["remark"]
    print("[test] nick_when_no_remark OK")


def test_uid_survives_when_unnamed():
    c = extract_contacts(_fixture())
    rec = c[UID_BARE]
    assert rec["name"] == UID_BARE, "the uid must survive, got %r" % rec["name"]
    assert rec["source"] == "uid", rec["source"]
    print("[test] uid_survives_when_unnamed OK")


def test_signature_is_never_a_name():
    # column 20011 is a signature line. It is populated for every row above, and it must never
    # appear as anyone's name, not even for the row that has no other name at all.
    c = extract_contacts(_fixture())
    sigs = {r[3] for r in ROWS if r[3]}
    for uid, rec in c.items():
        assert rec["name"] not in sigs, "signature leaked into the name of %s: %r" % (uid, rec["name"])
    print("[test] signature_is_never_a_name OK")


def test_friends_only_filters():
    c = extract_contacts(_fixture(), friends_only=True)
    assert UID_STRANGER not in c, "a uid outside buddy_list must be dropped"
    assert set(c) == {UID_BOTH, UID_NICK, UID_BARE}, sorted(c)
    full = extract_contacts(_fixture())
    assert UID_STRANGER in full, "without the flag every profile row must be kept"
    print("[test] friends_only_filters OK: %d friends of %d profiles" % (len(c), len(full)))


def test_friends_only_refuses_without_buddy_list():
    try:
        extract_contacts(_fixture(with_buddy_list=False), friends_only=True)
    except RuntimeError:
        print("[test] friends_only_refuses_without_buddy_list OK")
        return
    raise AssertionError("--friends-only must refuse when buddy_list is absent, not return everything")


def test_resolve_name_order():
    assert resolve_name("u_x", "nick", "remark") == ("remark", "remark")
    assert resolve_name("u_x", "nick", "") == ("nick", "nick")
    assert resolve_name("u_x", "", "") == ("u_x", "uid")
    print("[test] resolve_name_order OK")


def main():
    fails = 0
    tests = (test_remark_beats_nick, test_nick_when_no_remark, test_uid_survives_when_unnamed,
             test_signature_is_never_a_name, test_friends_only_filters,
             test_friends_only_refuses_without_buddy_list, test_resolve_name_order)
    for fn in tests:
        try:
            fn()
        except AssertionError as e:
            print("[FAIL]", fn.__name__, e)
            fails += 1
    print("=== %s ===" % ("all passed" if fails == 0 else "%d failed" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
