# Runtime Backup Runbook

The runtime backup script preserves student state and external-research evidence without touching the live deployment.

## Scope

The default archive includes:

- `var/app.db` for sessions and chat messages
- `var/auth.db` for local accounts
- `var/assessment.db` for assessment state
- `var/chat_history/` for learning events and profile projections
- `var/artifacts/tool_results/` for large tool and web-research results

Generated screenshots, benchmark reports, Chroma indexes, caches, and `.env` are intentionally excluded. The first group is reproducible or deployment-specific; `.env` contains secrets and must be backed up through the secret-management system.

## Create And Verify

Run from the repository root:

```bash
.venv/bin/python scripts/runtime_backup.py backup
.venv/bin/python scripts/runtime_backup.py verify var/backups/backup-<timestamp>.tar.gz
```

The archive contains `manifest.json` with SHA-256 hashes. SQLite files are copied through SQLite's backup API; directory snapshots should be taken while the backend is quiescent when a strict point-in-time view is required.

Missing default paths are recorded in the manifest. Add `--strict` when a backup must fail instead of recording a missing path.

## Restore Verification

Restore only into a new target directory. The command refuses an existing target and verifies every manifest entry before moving the payload into place:

```bash
.venv/bin/python scripts/runtime_backup.py restore \
  var/backups/backup-<timestamp>.tar.gz \
  --target /tmp/ds-course-agent-restore-check
```

This produces `/tmp/ds-course-agent-restore-check/var/...`; it does not replace the live `var/` tree. A production restore still requires an explicit operator plan, service quiescence, and a separate backup of the current state.

## Retention

Retention is preview-only by default and always preserves the newest archive:

```bash
.venv/bin/python scripts/runtime_backup.py retention --keep-days 30
```

Deleting old backup archives requires the exact confirmation token:

```bash
.venv/bin/python scripts/runtime_backup.py retention \
  --keep-days 30 --prune --confirm-prune DELETE
```

The retention command only removes matching backup archives. It never deletes live chat history, databases, or research artifacts.
