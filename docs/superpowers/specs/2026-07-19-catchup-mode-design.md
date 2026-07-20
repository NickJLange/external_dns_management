# Catch-Up Mode Design

**Date:** 2026-07-19  
**Feature:** `--catch-up` flag for `manage_porkbun.py`

---

## Problem

The existing `--dry-run` flag shows what operations the sync would run, but frames everything as "would create / would delete" — opaque for auditing drift. When Porkbun has records not in local config (e.g. Clerk auth CNAMEs added manually, IP changes in live DNS, ACME challenge leftovers), there is no way to see the full picture and pull missing records back into config without running a live sync.

---

## Solution

Add `--catch-up` to the existing `click` command. When set, it replaces the sync path entirely (no Porkbun records are created or deleted) and instead:

1. Prints a human-readable diff report per domain showing what differs and why
2. Appends porkbun-only records to the appropriate config files on a new git branch in the `etc` submodule

`--catch-up --dry-run` = diff report only; no branch or commit created.

---

## Observed Real-World State (validated 2026-07-19)

Dry-run against all domains revealed the kinds of drift catch-up must handle:

| Domain | Porkbun-only | Config-only | Notes |
|--------|-------------|-------------|-------|
| nicklange.family | 12 | 6 | 6 IP conflicts (newyork IP changed), 6 ACME TXT leftovers, 1 duplicate SPF |
| 5l-labs.com | 2 | 0 | 2 ACME TXT leftovers only |
| wafuu.design | 3 | 1 | 2 ACME TXTs + 1 TTL-only conflict on SPF mx record |
| recruiter-rankings.com | 6 | 1 | 5 Clerk auth CNAMEs not in config (real catch-up candidates) + 1 TTL conflict |

---

## Diff Categories

Using the existing `gen_key` (name + content + type + ttl) as the matching key, the diff produces four buckets:

### 1. Porkbun-only (non-conflict)
In live DNS but not in config, with no matching `(name, type)` in the config-only set. Candidates to pull into config.

Example: `CNAME clerk.recruiter-rankings.com → frontend-api.clerk.services`

### 2. Config-only (non-conflict)
In config but not in live DNS, with no matching `(name, type)` in the porkbun-only set. Would be created on next sync.

### 3. Value conflicts
Same `(name, type)` appears in both porkbun-only and config-only with different `content`. A record exists in both places but disagrees on its value.

Example: `A eva.nicklange.family` — Porkbun has `96.246.42.235`, config has `74.101.18.186`

### 4. TTL-only conflicts
Same `(name, type, content)` but different TTL. Appears as porkbun-only + config-only pair with identical content but different TTL. Flagged separately since the fix is just a TTL update, not a content decision.

Example: `TXT wafuu.design v=spf1 mx ...` — Porkbun TTL=600, config TTL=300

### Filtered: `_acme-challenge` records
ACME DNS-01 challenge TXT records added transiently by lego. These are present in Porkbun as leftover validation tokens and must never be pulled into config or treated as conflicts. Filtered from all output.

---

## Output Format

```
=== nicklange.family ===

  PORKBUN-ONLY — not in config (2 records):
  [>] CNAME  clerk.recruiter-rankings.com        frontend-api.clerk.services   ttl=600
  [>] CNAME  accounts.recruiter-rankings.com     accounts.clerk.services       ttl=600

  CONFIG-ONLY — not in Porkbun (0 records):
  (none)

  VALUE CONFLICTS — same name+type, different content (6 records):
  [~] A  eva.nicklange.family         porkbun=96.246.42.235   config=74.101.18.186   ttl=60
  [~] A  kjol.nicklange.family        porkbun=96.246.42.235   config=74.101.18.186   ttl=60
  ...

  TTL CONFLICTS — same name+type+content, different TTL (1 record):
  [t] TXT  wafuu.design  v=spf1 mx ...   porkbun-ttl=600   config-ttl=300

  Skipped: 6 _acme-challenge TXT records (transient lego tokens, ignored)
  In sync: 19 records match exactly
```

---

## Config File Updates (branch commit step)

When not in `--dry-run` mode and there are records to write:

**Branch:** `catchup/YYYY-MM-DD` cut in the `etc` submodule (error if branch already exists).

**What gets written:**

| Category | Action |
|----------|--------|
| Porkbun-only (non-conflict) | Appended as live config lines |
| Value conflicts | Both versions appended as commented lines for human review |
| TTL conflicts | Porkbun version appended as commented line (human picks which TTL) |
| Config-only | Nothing — already in config |
| `_acme-challenge` | Nothing — filtered out entirely |

**Append format for non-conflicts** (to `etc/files/<domain>` or `etc/templates/<domain>.j2`):
```
# catchup 2026-07-19
CNAME  clerk.recruiter-rankings.com    frontend-api.clerk.services    600
CNAME  accounts.recruiter-rankings.com accounts.clerk.services        600
```

**Append format for conflicts:**
```
# CONFLICT: choose one and remove the other
# CONFIG:   A    eva.nicklange.family    74.101.18.186    60
# PORKBUN:  A    eva.nicklange.family    96.246.42.235    60
```

**Append format for TTL conflicts:**
```
# TTL CONFLICT: same record, different TTL — choose one
# CONFIG-TTL:   TXT  wafuu.design  "v=spf1 mx include:_spf.porkbun.com ~all"  300
# PORKBUN-TTL:  TXT  wafuu.design  "v=spf1 mx include:_spf.porkbun.com ~all"  600
```

**Template files** (`nicklange.family.j2`): writes raw IPs, not template variables. A `# TODO: replace raw IPs with template vars if applicable` comment is added above the appended block.

**Commit message:** `catchup: add N records, flag M conflicts across K domains`

The parent repo's submodule pointer is **not** auto-updated. You update it when raising the catchup PR.

---

## Implementation

### New function: `diff_domain(domain, desired, existing) → DomainDiff`

Returns a dataclass:
```python
@dataclass
class DomainDiff:
    porkbun_only: list[dict]      # non-conflict porkbun records to pull
    config_only: list[dict]       # non-conflict config records (info only)
    value_conflicts: list[tuple]  # (porkbun_record, config_record)
    ttl_conflicts: list[tuple]    # (porkbun_record, config_record)
    in_sync: int                  # count of matching records
    skipped_acme: int             # count of filtered _acme-challenge records
```

Algorithm:
1. Filter `_acme-challenge.*` from both sets
2. Use `gen_key` sets to find porkbun-only and config-only keys
3. Group porkbun-only by `(name.lower(), type.lower())` and config-only by the same
4. Where a `(name, type)` appears in both: check if content differs (value conflict) or only TTL differs (TTL conflict)
5. Remaining: true porkbun-only and config-only

### New function: `print_catchup_report(domain, diff: DomainDiff)`

Formats and prints the per-domain report to stdout.

### New function: `write_catchup_to_config(domain, diff: DomainDiff, date_str: str)`

Appends records to the appropriate file in `etc/files/` or `etc/templates/`. Detects template domains by checking if a `.j2` file exists.

### New function: `create_catchup_branch(date_str: str) → str`

Runs `git checkout -b catchup/{date_str}` in the `etc` submodule. Returns branch name. Raises if branch already exists.

### Modified: `main()`

```python
@click.option("--catch-up", is_flag=True, help="Diff Porkbun vs config and optionally pull porkbun-only records to a new config branch")
```

When `--catch-up` set:
- Skip template processing and file copying (no `output/` needed — load config files directly)
- Load desired state directly from `etc/files/<domain>` and `etc/templates/<domain>.j2` (rendered)
- For each domain: call `get_records()`, then `diff_domain()`, then `print_catchup_report()`
- If not `--dry-run` and any domain has records to write: call `create_catchup_branch()` then `write_catchup_to_config()` for each domain, then commit

### Known limitation

MX/SRV priority mismatches for otherwise-matching records are invisible — `gen_key` excludes `prio`. These will not be surfaced in catch-up output. Acceptable for now; prio is rarely the source of meaningful drift.

---

## Files to Modify

| File | Change |
|------|--------|
| `scripts/manage_porkbun.py` | Add `--catch-up` flag, `diff_domain()`, `print_catchup_report()`, `write_catchup_to_config()`, `create_catchup_branch()`, modify `main()` |

No other files modified by the implementation (config writes happen at runtime on the catchup branch).
