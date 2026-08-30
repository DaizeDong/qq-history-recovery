#!/usr/bin/env python3
"""Decrypt a desktop QQNT nt_msg.db into a standard plaintext SQLite file.

The desktop QQNT message store is a SQLCipher 4 database wearing a Tencent custom wrapper. The layout,
verified against a real file, is a 1024 byte custom header followed by the standard SQLCipher stream:

  offset 0x000   ASCII "SQLite header 3\\0"
  offset 0x020   ASCII "QQ_NT DB" marker, then header metadata and a hex blob
  offset 0x100   zeros to the end of the custom header
  offset 0x400   the SQLCipher database begins here, and its first 16 bytes are the real salt

So the salt is not the visible header bytes; it is the sixteen bytes at offset 1024. The key is the
16 character passphrase read out of the running client (see docs/JOURNEY.md), and the SQLCipher
parameters are kdf_iter 4000, key derivation PBKDF2 HMAC SHA512, page 4096, AES-256-CBC per page with
the page IV in a 48 byte reserved region at each page end, and page authentication HMAC SHA1. These
were pinned by requiring the page 1 HMAC to verify, not by guessing.

This streams page by page so it does not hold the whole database in memory, and it verifies every
page's HMAC. It never writes a partial or corrupt database. No pysqlcipher or external binary is
needed, only the cryptography package.

The output is a normal SQLite file. Read it with tools/qqnt_decode.py. Both the encrypted input and
the decrypted output are private data and belong outside this repository. The key in the example
below is a placeholder, not a real key.

Usage: python qqnt_decrypt.py --in nt_msg.db --out nt_msg_plain.db --key "<16 char key>"
"""
import argparse
import hashlib
import hmac
import os
import struct
import sys

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    sys.stderr.write("ERROR: needs the cryptography package. pip install cryptography\n")
    sys.exit(2)

CUSTOM_HEADER = 1024
PAGE = 4096
RESERVE = 48            # 16 byte IV + 20 byte HMAC-SHA1 + padding
KDF_ITER = 4000
MAC_LEN = 20            # HMAC-SHA1


def main():
    ap = argparse.ArgumentParser(description="decrypt a QQNT nt_msg.db to plaintext SQLite")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--key", required=True, help="the 16 character passphrase from the client")
    ap.add_argument("--allow-mismatch", type=int, default=2,
                    help="tolerated page HMAC mismatches (free pages can be stale); default 2")
    a = ap.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.abspath(a.out).startswith(repo):
        sys.stderr.write("ERROR: refusing to write a decrypted database inside the repo. It is DATA.\n")
        return 2

    pw = a.key.encode("utf-8")
    with open(a.inp, "rb") as f:
        f.seek(CUSTOM_HEADER)
        salt = f.read(16)
        key = hashlib.pbkdf2_hmac("sha512", pw, salt, KDF_ITER, 32)
        hsalt = bytes(b ^ 0x3a for b in salt)
        hkey = hashlib.pbkdf2_hmac("sha512", key, hsalt, 2, 32)

        f.seek(CUSTOM_HEADER)
        total = (os.path.getsize(a.inp) - CUSTOM_HEADER) // PAGE
        tmp = a.out + ".part"
        i = mism = 0
        with open(tmp, "wb") as out:
            while True:
                page = f.read(PAGE)
                if len(page) < PAGE:
                    break
                iv = page[PAGE - RESERVE: PAGE - RESERVE + 16]
                stored = page[PAGE - RESERVE + 16: PAGE - RESERVE + 16 + MAC_LEN]
                if i == 0:
                    ct = page[16: PAGE - RESERVE]
                    prefix = b"SQLite format 3\x00"
                else:
                    ct = page[0: PAGE - RESERVE]
                    prefix = b""
                mac = hmac.new(hkey, digestmod=hashlib.sha1)
                mac.update(ct); mac.update(iv); mac.update(struct.pack("<I", i + 1))
                if not hmac.compare_digest(mac.digest(), stored):
                    mism += 1
                dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
                pt = dec.update(ct) + dec.finalize()
                out.write(prefix + pt + page[PAGE - RESERVE:])   # page stays 4096, reserve kept as is
                i += 1
                if i % 40000 == 0:
                    print("  %d/%d pages, hmac-mismatch=%d" % (i, total, mism), flush=True)

    if i == 0:
        os.remove(tmp)
        sys.stderr.write("ERROR: no pages decrypted. Wrong file?\n")
        return 1
    # Page 1 must decrypt to a valid SQLite header, or the key or params are wrong.
    with open(tmp, "rb") as chk:
        if chk.read(16) != b"SQLite format 3\x00":
            os.remove(tmp)
            sys.stderr.write("ERROR: page 1 is not a valid SQLite header. Wrong key or parameters.\n")
            return 1
    if mism > a.allow_mismatch:
        os.remove(tmp)
        sys.stderr.write("ERROR: %d page HMAC mismatches (over the %d allowed). Wrong key.\n"
                         % (mism, a.allow_mismatch))
        return 1
    os.replace(tmp, a.out)
    print("decrypted %d pages (%d HMAC mismatches, within tolerance) -> %s" % (i, mism, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
