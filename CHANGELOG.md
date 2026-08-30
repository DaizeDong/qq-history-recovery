# Changelog

## 0.1.0 (2026-08-30)

Initial release. Recover QQ chat history from all three Tencent stores.

- Desktop QQNT path: stream decrypt nt_msg.db (SQLCipher 4 under a 1024 byte custom header, params pinned by page HMAC verification) and extract text from the protobuf message column, skipping quoted replies.
- Mobile classic path: adb pull, frida 16 key bootstrap, offline repeating XOR decode.
- Import monitor: Frida hook of the desktop to phone migration that showed the import drops text and revealed the desktop store path.
- Full reverse engineering journey and environment traps documented in docs/JOURNEY.md.
- Synthetic fixtures and unit tests; data boundary gates so no real history enters the repo.
