# Bridges training continuity (monthly automation)

Cursor Automation cron runs `scripts/bridges_training_continuity.sh` to keep Kraken HTR and Tesseract training jobs healthy on PSC Bridges2.

## Required secret

Cloud agents cannot use interactive SSH. Add one of these to the automation **Secrets**:

| Secret | Value |
|--------|--------|
| `BRIDGES_SSH_KEY` | Full PEM private key for your PSC account (preferred) |
| `BRIDGES_SSH_KEY_FILE` | Path to an existing key file on the agent VM |

Optional overrides:

| Variable | Default |
|----------|---------|
| `BRIDGES_LOGIN` | `bridges2.psc.edu` |
| `BRIDGES_DTN` | `data.bridges2.psc.edu` |
| `BRIDGES_USER` | `sstrickland` |

Without a key, the check exits **2** (`cannot SSH to bridges2.psc.edu`) and remediation is skipped.

## Manual run

```bash
# Health check only
bash scripts/bridges_training_automation_check.sh

# Check + remediate (cancel orphans, sync scripts, resubmit HTR/tess)
bash scripts/bridges_training_continuity.sh

# Dry run
bash scripts/bridges_training_continuity.sh --dry-run
```

## What remediation does

1. Run remote health check (queue, recent failures, artifacts, kraken venv smoke test).
2. Cancel `DependencyNeverSatisfied` orphan jobs.
3. `sync_scripts_to_bridges.sh` — push latest `scripts/` to the ocean project.
4. Fix kraken numpy/matplotlib and venv paths on Bridges.
5. `bridges_resubmit_htr.sh` — resume timed-out r6, submit downstream r7/anglicana, or full chain.
6. Resubmit `tess-pre1800` if no `lat_pre1800.traineddata` model yet.

## Critical jobs

| Job name | Purpose |
|----------|---------|
| `htr-r6-core` | Core Latin HTR fine-tune (Kraken) |
| `htr-r7-full` | Full corpus HTR (depends on r6) |
| `htr-anglicana` | Anglicana legal register HTR |
| `tess-pre1800` | Tesseract pre-1800 Latin fine-tune |
