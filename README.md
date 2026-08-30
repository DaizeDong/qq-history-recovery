# qq-history-recovery

Recover your own QQ chat history from every place Tencent keeps it, and turn it into structured JSON.
This repository is both a set of tools and a field notebook: the full reverse engineering journey and
every environment trick that cost real time are written down in `docs/JOURNEY.md`, so the next person
skips the walls this one hit.

Chat history is private data. It never enters this repository. Only synthetic fixtures ship, and a data
boundary gate enforces it. Every account number and key in the code and docs is a placeholder.

## The three stores

QQ keeps the same conversations in three different shapes, and they are not equal in completeness.

The mobile client keeps a plain SQLite file whose message fields are XOR obfuscated with a short
repeating key. It is the easiest to decode and the least complete, because a free account only roams
about the last six months.

The desktop classic client keeps `Msg3.0.db`, and the message manager exports `.bak` files, both in a
Tencent SQLCipher variant whose key comes from a running classic client. If only QQNT is installed, this
key route is not available, because QQNT does not load the classic key module.

The desktop QQNT client keeps `nt_qq\nt_db\nt_msg.db`, a two gigabyte SQLCipher database with years of
history. This is the archive that actually delivers, and it is the main path here.

## The QQNT pipeline, end to end

First get the key. QQNT issues a sixteen character SQLCipher key at login and keeps it only in memory.
The QQBackup project's Windows key extractor reads it by launching the client under a debugger with a
breakpoint on its key function. Quit QQ completely first, or the extractor's instance merges into the
already running one and the breakpoint never fires, then run the extractor and log in to the window it
opens.

Then decrypt and read:

```
python tools/qqnt_decrypt.py --in nt_msg.db --out nt_msg_plain.db --key "<16 char key>"
python tools/qqnt_decode.py  --db nt_msg_plain.db --out ~/qq-out/qq.jsonl
```

`qqnt_decrypt.py` handles the format this repo pinned by evidence: a 1024 byte custom header, then a
standard SQLCipher 4 stream whose salt is the sixteen bytes at offset 1024, decrypted with kdf_iter
4000, PBKDF2 HMAC SHA512, page 4096, AES-256-CBC, and page HMAC SHA1. It streams page by page, verifies
every page's HMAC, and refuses to write a corrupt database. `qqnt_decode.py` reads the decrypted
database, pulls each message's text out of the protobuf content column, decides who sent it, and writes
one JSON record per text message. It writes only outside this repository, since the output is data.

## The mobile pipeline

For the mobile store, `tools/qq_pull.py` pulls the database over adb, `tools/qq_keyfind.py` bootstraps
the repeating XOR key from the running client with frida 16, and `tools/qq_decode.py` decodes it
offline. See `docs/JOURNEY.md` for the period trap that makes the key look unrecoverable when it is not.

## The import monitor

`tools/qq_import_monitor.py` attaches to the phone client during a desktop to phone migration and logs
what its native backup library decrypts. It is how we learned that the import carries only file records
and drops the text, and how we found the desktop store's path on disk. It hooks only; it never forces a
library to load and never writes to the client.

## Requirements

Python with `cryptography` for the QQNT decryptor, and `frida==16.7.19` for the mobile and monitor
tools (frida 17 removed the Java bridge and cannot hook the Android client). The QQNT key extractor is
the PowerShell script from the QQBackup project and needs the QQNT client installed. Run the offline
decode and parse steps with QQ closed, on a copy of the database, never on the original.

## Data boundary

Pulled databases, decrypted stores, and decoded output are all real run output. They are declared in
`.dataclass.json` and never committed. Tests run against synthetic protobuf messages and a synthetic
mobile database built by the generators in `tools/`, so nothing real is needed to exercise the code.
