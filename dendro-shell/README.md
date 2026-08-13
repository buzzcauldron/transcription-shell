# dendro-shell has moved

**dendro-shell** is now a standalone repository:

**https://github.com/buzzcauldron/dendro**

(If that URL 404s, the split history is already on this repo’s
[`dendro-shell-split`](https://github.com/buzzcauldron/transcription-shell/tree/dendro-shell-split)
branch — publish it with the commands below.)

## Publish the standalone repo (one-time)

```bash
# 1. Create an empty public repo: https://github.com/new → buzzcauldron/dendro
#    (no README / license / gitignore)

# 2. Push the prepared split history:
git clone --branch dendro-shell-split --single-branch \
  https://github.com/buzzcauldron/transcription-shell.git dendro-shell
cd dendro-shell
git checkout -B main
git remote set-url origin https://github.com/buzzcauldron/dendro.git
git push -u origin main
```

## Install / run (after publish)

```bash
git clone https://github.com/buzzcauldron/dendro.git
cd dendro-shell
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[ui,train,dev]"
dendro open examples/cracked_disc.png
```
