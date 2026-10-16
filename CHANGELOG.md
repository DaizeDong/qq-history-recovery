# Changelog

## Unreleased

- Removed the guards and style submodules, the gate workflows (pii-guard, dash-guard) and fleet-sync. `.githooks` forwards to the local fleet-guards and fleet-style checkouts named by `git config fleet.guards` and `fleet.style` and blocks when either is unset or missing; commits also run the dash check on added lines. `tools/storage_paths.py` and `tools/qqnt_contacts.py` resolve the companion through the installed `fleet_guards.runtime.companion_resolver` (`pip install -e "$(git config --get fleet.guards)"`).
- Contact resolution: `tools/qqnt_contacts.py` decrypts the sibling `profile_info.db` with the existing QQNT decryptor and writes a uid to name mapping, so decoded messages can be labeled with a person instead of an opaque `u_` id. Resolution order is the owner's remark, then the nickname, then the raw uid, which is kept as is rather than guessed at. `--friends-only` restricts it to `buddy_list`. The mapping is DATA and is written outside the repo.

## 0.1.0 (2026-08-30)

Initial release. Recover QQ chat history from all three Tencent stores.

- Desktop QQNT path: stream decrypt nt_msg.db (SQLCipher 4 under a 1024 byte custom header, params pinned by page HMAC verification) and extract text from the protobuf message column, skipping quoted replies.
- Mobile classic path: adb pull, frida 16 key bootstrap, offline repeating XOR decode.
- Import monitor: Frida hook of the desktop to phone migration that showed the import drops text and revealed the desktop store path.
- Full reverse engineering journey and environment traps documented in docs/JOURNEY.md.
- Synthetic fixtures and unit tests; data boundary gates so no real history enters the repo.
