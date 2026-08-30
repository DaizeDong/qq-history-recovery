#!/usr/bin/env python3
"""Round trip tests for the QQ decoder, on a synthetic database with no real data.

The tests must be able to fail: the poison case decodes with a wrong key and asserts the coverage
collapses, so a decoder that ignored its key would be caught here.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import make_fixtures
from qq_field_cipher import decode_field, encode_field, detect_period_from_known_plaintext
from qq_decode import decode_db, decode_rate


def _fixture():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "synthetic_qq.db")
    make_fixtures.build(p)
    return p


def test_round_trip():
    p = _fixture()
    recs = list(decode_db(p, make_fixtures.SYNTH_KEY, make_fixtures.OWNER))
    texts = [r["text"] for r in recs]
    assert any("自己发出的短消息" in t for t in texts), "expected owner message not decoded"
    assert any("对方回复消息" in t for t in texts), "expected peer message not decoded"
    # every synthetic message decoded to valid utf8
    assert len(recs) == 7, "expected 7 messages, got %d" % len(recs)
    print("[test] round_trip OK: %d messages decoded" % len(recs))


def test_is_me_and_ctx():
    p = _fixture()
    recs = list(decode_db(p, make_fixtures.SYNTH_KEY, make_fixtures.OWNER))
    mine = [r for r in recs if r["is_me"]]
    assert len(mine) == 4, "expected 4 owner messages, got %d" % len(mine)
    assert all(r["sender"] == "qq_me" for r in mine)
    assert any(r["ctx"] == "dm" for r in recs) and any(r["ctx"] == "group" for r in recs)
    print("[test] is_me and ctx OK: %d owner, dm+group present" % len(mine))


def test_period_detection():
    plain = "用于周期检测的合成明文，需要跨越密钥周期若干次以便可靠判定".encode("utf-8")
    ct = encode_field(plain, make_fixtures.SYNTH_KEY)
    key = detect_period_from_known_plaintext(ct, plain)
    assert key == make_fixtures.SYNTH_KEY, "recovered wrong key %r" % key
    print("[test] period_detection OK: recovered %d byte key" % len(key))


def test_poison_wrong_key():
    p = _fixture()
    good = decode_rate(p, make_fixtures.SYNTH_KEY)
    bad = decode_rate(p, b"WRONGKEYWRONGKEY")
    assert good > 0.99, "good key should decode nearly everything, got %.2f" % good
    assert bad < good, "wrong key must decode strictly worse, got bad=%.2f good=%.2f" % (bad, good)
    print("[test] poison OK: good=%.2f wrong=%.2f" % (good, bad))


def main():
    fails = 0
    for fn in (test_round_trip, test_is_me_and_ctx, test_period_detection, test_poison_wrong_key):
        try:
            fn()
        except AssertionError as e:
            print("[FAIL]", fn.__name__, e)
            fails += 1
    print("=== %s ===" % ("all passed" if fails == 0 else "%d failed" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
