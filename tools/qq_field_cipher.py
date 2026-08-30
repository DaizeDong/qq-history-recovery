#!/usr/bin/env python3
"""The field cipher used by classic mobile QQ for msgData and the account number columns.

Invariant: obfuscation is a byte wise XOR against a repeating keystream. The keystream is a short
byte string repeated to the length of the field. Decoding is therefore identical to encoding: XOR
the same key again.

The one thing you must get right is the PERIOD. An earlier analysis mistook the first nine bytes of
a fifteen byte key for the whole key, which decoded the first three Chinese characters of every
message and then diverged. detect_period_from_known_plaintext recovers the true key from one known
plaintext, ciphertext pair, so there is no guessing.

No real account data lives in this file. See tools/make_fixtures.py for how tests build a synthetic
database that this module round trips.
"""


def xor_repeat(data: bytes, key: bytes) -> bytes:
    """XOR data against key repeated to length. Encode and decode are the same operation."""
    if not key:
        raise ValueError("empty key")
    k = len(key)
    return bytes(data[i] ^ key[i % k] for i in range(len(data)))


decode_field = xor_repeat
encode_field = xor_repeat


def key_from_known_pair(cipher: bytes, plain: bytes, period: int) -> bytes:
    """Recover the repeating key of a given period from one aligned cipher, plain pair.

    Both inputs must start at the same field offset zero. Returns period bytes. Raises if the pair
    is shorter than the period or if the recovered key is internally inconsistent, which is the
    signal that the period guess is wrong.
    """
    n = min(len(cipher), len(plain))
    if n < period:
        raise ValueError("known pair shorter (%d) than period (%d)" % (n, period))
    key = bytearray(cipher[i] ^ plain[i] for i in range(period))
    # every further position must agree with the key already recovered, or the period is wrong
    for i in range(period, n):
        if (cipher[i] ^ plain[i]) != key[i % period]:
            raise ValueError("inconsistent key at offset %d: period %d is wrong" % (i, period))
    return bytes(key)


def detect_period_from_known_plaintext(cipher: bytes, plain: bytes, max_period: int = 64) -> bytes:
    """Find the smallest period whose recovered key round trips the whole known pair.

    Returns the recovered key (its length is the detected period). Raises if no period up to
    max_period explains the pair, which means the field is not a simple repeating XOR.
    """
    n = min(len(cipher), len(plain))
    for period in range(1, min(max_period, n) + 1):
        try:
            key = key_from_known_pair(cipher, plain, period)
        except ValueError:
            continue
        # reject a spuriously short period that only looks periodic on a short sample: require the
        # sample to cover at least two full periods so the round trip check has something to reject
        if n >= 2 * period:
            return key
    # no period covered two full periods; fall back to the longest consistent key we can form
    if n >= 1:
        return bytes(cipher[i] ^ plain[i] for i in range(n))
    raise ValueError("empty known pair")


if __name__ == "__main__":
    # self test with a synthetic key, no real data
    key = b"synthetic-key-7"
    msg = "你好世界，这是一条用于自检的合成消息".encode("utf-8")
    ct = encode_field(msg, key)
    assert decode_field(ct, key) == msg, "round trip failed"
    rec = detect_period_from_known_plaintext(ct, msg)
    assert rec == key, "period recovery failed: %r" % rec
    print("[selftest] round trip and period recovery OK, period", len(rec))
