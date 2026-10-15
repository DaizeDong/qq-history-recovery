# qq-history-recovery storage

Source code stays in this repository. The default sibling PRIVATE companion is
`../qq-history-recovery-config`. Explicit `QQ_HISTORY_RECOVERY_CONFIG` or its `_DIR`
variant selects another root. Real records, credentials and recovery history belong
in a versioned PRIVATE companion, never a public or unknown-visibility source tree.

The companion preserves the existing file names and schemas, with `data/` reserved
for recovered outputs. Key files and sessions retain their original semantics.
The tool does not automatically log in, export, decrypt or consume a queue during
directory maintenance. Restore does not overwrite original message databases.

Keep keys, sessions, restored message evidence and the source schema together in
private version history. Rebuildable caches and failed temporary outputs may be
reviewed separately. `storage.contract.json` lists this preservation scope.

Path selection reuses the pinned guards datadir convention. Credential writers require the companion
checkout to exist before creating directories, sessions or key files; there is no runtime
visibility proof, the commit-time gates own that. Missing companions can be inspected by readers
but writes require restoring the private Git checkout. Explicit
overrides must be absolute; canonical source aliases are rejected.
