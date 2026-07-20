# External DNS Management — Developer Guide

## Setup

Always use the project virtualenv. Create it once:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

All script invocations must use the venv python:

```bash
.venv/bin/python scripts/manage_porkbun.py --dry-run
```

Note: avoid `--verbose` in dry-run — debug output includes plaintext API credentials.

## Running the script

**Dry-run (safe, no DNS changes):**
```bash
.venv/bin/python scripts/manage_porkbun.py --dry-run
.venv/bin/python scripts/manage_porkbun.py --dry-run --domain nicklange.family
```

**Live sync — only after reviewing dry-run output:**
```bash
.venv/bin/python scripts/manage_porkbun.py --domain nicklange.family
```

## Config

Credentials and domain lists live in the `etc/` submodule (`etc/config.ini`). The script also accepts `PORKBUN_API_KEY` and `PORKBUN_SECRET_API_KEY` environment variables as fallback, which is the preferred approach for avoiding plaintext keys in the submodule.

## Branches

- `main` — stable
- `etc` submodule has its own git history; `catchup/YYYY-MM-DD` branches are created there by `--catch-up`
