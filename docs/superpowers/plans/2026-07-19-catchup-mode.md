# Catch-Up Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--catch-up` to `manage_porkbun.py` to diff live Porkbun DNS against local config, report conflicts, and commit porkbun-only records to a new branch in the `etc` submodule.

**Architecture:** All new logic lives in `scripts/manage_porkbun.py`. A new `diff_domain()` function produces a `DomainDiff` dataclass by comparing desired vs existing state. A `print_catchup_report()` formats it for humans. A `write_catchup_to_config()` appends records to the right config file. A `create_catchup_branch()` handles git in the `etc` submodule. `main()` gets a new `--catch-up` flag that replaces the sync path.

**Tech Stack:** Python 3, click, pytest, subprocess (for git ops), existing `gen_key`/`load_domain`/`get_records` functions.

## Global Constraints

- Python virtualenv is at `.venv/`; run all commands as `.venv/bin/python` or `.venv/bin/pytest`
- No live DNS changes — `--catch-up` never calls `create_record()` or `delete_record()`
- `_acme-challenge.*` records are filtered from all output and never written to config
- Config files live in `etc/files/<domain>` (static) or `etc/templates/<domain>.j2` (template); detect by checking if the `.j2` exists
- Branch created in `etc/` submodule only, not in parent repo
- `--catch-up --dry-run` = report only, no git operations
- All tests use `.venv/bin/pytest tests/ -v`

---

## File Map

| File | Role |
|------|------|
| `scripts/manage_porkbun.py` | All new functions added here; `main()` modified |
| `tests/__init__.py` | Empty, marks tests as a package |
| `tests/test_diff_domain.py` | Unit tests for `diff_domain()` and `DomainDiff` |
| `tests/test_catchup_output.py` | Unit tests for `print_catchup_report()` output |
| `tests/test_write_catchup.py` | Unit tests for `write_catchup_to_config()` |
| `requirements.txt` | Add `pytest` |

---

## Task 1: Test infrastructure and DomainDiff dataclass

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_diff_domain.py`
- Modify: `scripts/manage_porkbun.py` — add `dataclasses` import and `DomainDiff`
- Modify: `requirements.txt` — add `pytest`

**Interfaces:**
- Produces: `DomainDiff` dataclass importable from `scripts.manage_porkbun`

- [ ] **Step 1: Add pytest to requirements.txt**

```
requests
jinja2
click
pytest
```

- [ ] **Step 2: Create `tests/__init__.py`** (empty file)

- [ ] **Step 3: Add `DomainDiff` dataclass to `manage_porkbun.py`**

Add `from dataclasses import dataclass, field` to the imports at the top, then add this class after the global constants block (after line 26, before `setup_logging`):

```python
@dataclass
class DomainDiff:
    porkbun_only: list = field(default_factory=list)    # non-conflict porkbun records
    config_only: list = field(default_factory=list)     # non-conflict config records
    value_conflicts: list = field(default_factory=list) # list of (porkbun_rec, config_rec)
    ttl_conflicts: list = field(default_factory=list)   # list of (porkbun_rec, config_rec)
    in_sync: int = 0
    skipped_acme: int = 0
```

- [ ] **Step 4: Write a smoke test to confirm the dataclass is importable**

Create `tests/test_diff_domain.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.manage_porkbun import DomainDiff


def test_domaindiff_defaults():
    d = DomainDiff()
    assert d.porkbun_only == []
    assert d.config_only == []
    assert d.value_conflicts == []
    assert d.ttl_conflicts == []
    assert d.in_sync == 0
    assert d.skipped_acme == 0
```

- [ ] **Step 5: Run the test — expect PASS**

```bash
.venv/bin/pytest tests/test_diff_domain.py -v
```

Expected output contains: `test_domaindiff_defaults PASSED`

- [ ] **Step 6: Commit**

```bash
git add scripts/manage_porkbun.py tests/__init__.py tests/test_diff_domain.py requirements.txt
git commit -m "feat(catchup): add DomainDiff dataclass and test scaffold"
```

---

## Task 2: `diff_domain()` function

**Files:**
- Modify: `scripts/manage_porkbun.py` — add `diff_domain()`
- Modify: `tests/test_diff_domain.py` — full test suite

**Interfaces:**
- Consumes: `gen_key(record: dict) -> str` (already exists at line 67)
- Produces: `diff_domain(domain: str, desired: dict, existing: dict) -> DomainDiff`

The `desired` and `existing` dicts are both keyed by `gen_key()` output, values are record dicts with keys `name`, `type`, `content`, `ttl`, `prio`.

- [ ] **Step 1: Write all failing tests first**

Replace the contents of `tests/test_diff_domain.py` with:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.manage_porkbun import DomainDiff, diff_domain, gen_key


def make_record(name, rtype, content, ttl="600", prio="None"):
    return {"name": name, "type": rtype, "content": content, "ttl": ttl, "prio": prio}


def keyed(record):
    return {gen_key(record): record}


# --- acme filtering ---

def test_acme_records_are_filtered_from_porkbun():
    acme = make_record("_acme-challenge.example.com", "TXT", "sometoken")
    result = diff_domain("example.com", {}, keyed(acme))
    assert result.porkbun_only == []
    assert result.skipped_acme == 1


def test_acme_records_are_filtered_from_desired():
    acme = make_record("_acme-challenge.example.com", "TXT", "sometoken")
    result = diff_domain("example.com", keyed(acme), {})
    assert result.config_only == []
    assert result.skipped_acme == 1


# --- in sync ---

def test_matching_records_counted_as_in_sync():
    rec = make_record("example.com", "A", "1.2.3.4")
    result = diff_domain("example.com", keyed(rec), keyed(rec))
    assert result.in_sync == 1
    assert result.porkbun_only == []
    assert result.config_only == []


# --- porkbun-only ---

def test_porkbun_only_record_no_name_type_match_in_config():
    pb_rec = make_record("clerk.example.com", "CNAME", "frontend-api.clerk.services")
    result = diff_domain("example.com", {}, keyed(pb_rec))
    assert len(result.porkbun_only) == 1
    assert result.porkbun_only[0]["name"] == "clerk.example.com"


# --- config-only ---

def test_config_only_record_no_name_type_match_in_porkbun():
    cfg_rec = make_record("newyork.example.com", "A", "1.2.3.4")
    result = diff_domain("example.com", keyed(cfg_rec), {})
    assert len(result.config_only) == 1
    assert result.config_only[0]["name"] == "newyork.example.com"


# --- value conflicts ---

def test_value_conflict_same_name_type_different_content():
    pb_rec = make_record("eva.example.com", "A", "96.246.42.235", ttl="60")
    cfg_rec = make_record("eva.example.com", "A", "74.101.18.186", ttl="60")
    result = diff_domain("example.com", keyed(cfg_rec), keyed(pb_rec))
    assert len(result.value_conflicts) == 1
    pb_out, cfg_out = result.value_conflicts[0]
    assert pb_out["content"] == "96.246.42.235"
    assert cfg_out["content"] == "74.101.18.186"
    assert result.porkbun_only == []
    assert result.config_only == []


# --- TTL conflicts ---

def test_ttl_conflict_same_name_type_content_different_ttl():
    pb_rec = make_record("example.com", "TXT", "v=spf1 include:_spf.porkbun.com ~all", ttl="600")
    cfg_rec = make_record("example.com", "TXT", "v=spf1 include:_spf.porkbun.com ~all", ttl="300")
    result = diff_domain("example.com", keyed(cfg_rec), keyed(pb_rec))
    assert len(result.ttl_conflicts) == 1
    pb_out, cfg_out = result.ttl_conflicts[0]
    assert pb_out["ttl"] == "600"
    assert cfg_out["ttl"] == "300"
    assert result.value_conflicts == []


# --- multiple record types with same name ---

def test_multiple_records_same_name_different_type_not_confused():
    pb_mx = make_record("example.com", "MX", "fwd1.porkbun.com")
    cfg_txt = make_record("example.com", "TXT", "v=spf1 include:_spf.porkbun.com ~all")
    result = diff_domain("example.com", keyed(cfg_txt), keyed(pb_mx))
    assert len(result.porkbun_only) == 1
    assert len(result.config_only) == 1
    assert result.value_conflicts == []
```

- [ ] **Step 2: Run tests — expect all to FAIL**

```bash
.venv/bin/pytest tests/test_diff_domain.py -v
```

Expected: multiple `FAILED` with `ImportError: cannot import name 'diff_domain'`

- [ ] **Step 3: Implement `diff_domain()` in `manage_porkbun.py`**

Add this function after the `DomainDiff` dataclass:

```python
def diff_domain(domain: str, desired: dict, existing: dict) -> DomainDiff:
    """Compare desired config state vs live Porkbun state, categorise differences."""
    diff = DomainDiff()

    def is_acme(record: dict) -> bool:
        return record.get("name", "").startswith("_acme-challenge.")

    # Filter acme records from both sides
    clean_desired = {}
    clean_existing = {}
    for key, rec in desired.items():
        if is_acme(rec):
            diff.skipped_acme += 1
        else:
            clean_desired[key] = rec
    for key, rec in existing.items():
        if is_acme(rec):
            diff.skipped_acme += 1
        else:
            clean_existing[key] = rec

    desired_keys = set(clean_desired.keys())
    existing_keys = set(clean_existing.keys())

    # Records present in both — in sync
    diff.in_sync = len(desired_keys & existing_keys)

    # Keys only in one side
    only_in_existing = existing_keys - desired_keys
    only_in_desired = desired_keys - existing_keys

    # Group each side by (name.lower(), type.lower()) for conflict detection
    def by_name_type(records: dict) -> dict:
        grouped = {}
        for rec in records.values():
            k = (rec["name"].lower(), rec["type"].lower())
            grouped.setdefault(k, []).append(rec)
        return grouped

    existing_by_nt = by_name_type({k: clean_existing[k] for k in only_in_existing})
    desired_by_nt = by_name_type({k: clean_desired[k] for k in only_in_desired})

    conflict_nts = set(existing_by_nt.keys()) & set(desired_by_nt.keys())

    for nt in conflict_nts:
        for pb_rec in existing_by_nt[nt]:
            for cfg_rec in desired_by_nt[nt]:
                if pb_rec["content"] == cfg_rec["content"]:
                    # Same content, different TTL
                    diff.ttl_conflicts.append((pb_rec, cfg_rec))
                else:
                    # Different content — value conflict
                    diff.value_conflicts.append((pb_rec, cfg_rec))

    # True porkbun-only: in existing but name+type not in desired at all
    for nt, recs in existing_by_nt.items():
        if nt not in conflict_nts:
            diff.porkbun_only.extend(recs)

    # True config-only: in desired but name+type not in existing at all
    for nt, recs in desired_by_nt.items():
        if nt not in conflict_nts:
            diff.config_only.extend(recs)

    return diff
```

- [ ] **Step 4: Run tests — expect all to PASS**

```bash
.venv/bin/pytest tests/test_diff_domain.py -v
```

Expected: all 9 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add scripts/manage_porkbun.py tests/test_diff_domain.py
git commit -m "feat(catchup): add diff_domain() with full test coverage"
```

---

## Task 3: `print_catchup_report()`

**Files:**
- Modify: `scripts/manage_porkbun.py` — add `print_catchup_report()`
- Create: `tests/test_catchup_output.py`

**Interfaces:**
- Consumes: `DomainDiff` (from Task 1), `diff_domain()` (from Task 2)
- Produces: `print_catchup_report(domain: str, diff: DomainDiff) -> None` — writes to stdout

- [ ] **Step 1: Write failing tests**

Create `tests/test_catchup_output.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.manage_porkbun import DomainDiff, print_catchup_report


def make_record(name, rtype, content, ttl="600", prio="None"):
    return {"name": name, "type": rtype, "content": content, "ttl": str(ttl), "prio": prio}


def run_report(domain, diff, capsys):
    print_catchup_report(domain, diff)
    return capsys.readouterr().out


def test_domain_header_printed(capsys):
    out = run_report("example.com", DomainDiff(), capsys)
    assert "=== example.com ===" in out


def test_in_sync_count_printed(capsys):
    diff = DomainDiff(in_sync=42)
    out = run_report("example.com", diff, capsys)
    assert "42 records in sync" in out


def test_porkbun_only_section_shown(capsys):
    rec = make_record("clerk.example.com", "CNAME", "frontend-api.clerk.services")
    diff = DomainDiff(porkbun_only=[rec])
    out = run_report("example.com", diff, capsys)
    assert "PORKBUN-ONLY" in out
    assert "[>]" in out
    assert "clerk.example.com" in out
    assert "frontend-api.clerk.services" in out


def test_config_only_section_shown(capsys):
    rec = make_record("newyork.example.com", "A", "1.2.3.4")
    diff = DomainDiff(config_only=[rec])
    out = run_report("example.com", diff, capsys)
    assert "CONFIG-ONLY" in out
    assert "[+]" in out
    assert "newyork.example.com" in out


def test_value_conflict_shown(capsys):
    pb = make_record("eva.example.com", "A", "96.246.42.235", ttl="60")
    cfg = make_record("eva.example.com", "A", "74.101.18.186", ttl="60")
    diff = DomainDiff(value_conflicts=[(pb, cfg)])
    out = run_report("example.com", diff, capsys)
    assert "VALUE CONFLICT" in out
    assert "[~]" in out
    assert "96.246.42.235" in out
    assert "74.101.18.186" in out


def test_ttl_conflict_shown(capsys):
    pb = make_record("example.com", "TXT", "v=spf1 include:_spf.porkbun.com ~all", ttl="600")
    cfg = make_record("example.com", "TXT", "v=spf1 include:_spf.porkbun.com ~all", ttl="300")
    diff = DomainDiff(ttl_conflicts=[(pb, cfg)])
    out = run_report("example.com", diff, capsys)
    assert "TTL CONFLICT" in out
    assert "[t]" in out
    assert "porkbun-ttl=600" in out
    assert "config-ttl=300" in out


def test_skipped_acme_count_shown(capsys):
    diff = DomainDiff(skipped_acme=4)
    out = run_report("example.com", diff, capsys)
    assert "4 _acme-challenge" in out


def test_none_section_shown_when_empty(capsys):
    diff = DomainDiff(in_sync=5)
    out = run_report("example.com", diff, capsys)
    assert "(none)" in out
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
.venv/bin/pytest tests/test_catchup_output.py -v
```

Expected: `ImportError: cannot import name 'print_catchup_report'`

- [ ] **Step 3: Implement `print_catchup_report()` in `manage_porkbun.py`**

Add after `diff_domain()`:

```python
def print_catchup_report(domain: str, diff: DomainDiff) -> None:
    """Print a human-readable catch-up diff report for one domain."""
    print(f"\n=== {domain} ===\n")

    print(f"  PORKBUN-ONLY — not in config ({len(diff.porkbun_only)} records):")
    if diff.porkbun_only:
        for r in diff.porkbun_only:
            print(f"  [>] {r['type']:<6} {r['name']:<45} {r['content']:<40} ttl={r['ttl']}")
    else:
        print("  (none)")

    print(f"\n  CONFIG-ONLY — not in Porkbun ({len(diff.config_only)} records):")
    if diff.config_only:
        for r in diff.config_only:
            print(f"  [+] {r['type']:<6} {r['name']:<45} {r['content']:<40} ttl={r['ttl']}")
    else:
        print("  (none)")

    if diff.value_conflicts:
        print(f"\n  VALUE CONFLICTS — same name+type, different content ({len(diff.value_conflicts)} records):")
        for pb_rec, cfg_rec in diff.value_conflicts:
            print(f"  [~] {pb_rec['type']:<6} {pb_rec['name']}")
            print(f"        porkbun={pb_rec['content']}   config={cfg_rec['content']}   ttl={pb_rec['ttl']}")

    if diff.ttl_conflicts:
        print(f"\n  TTL CONFLICTS — same record, different TTL ({len(diff.ttl_conflicts)} records):")
        for pb_rec, cfg_rec in diff.ttl_conflicts:
            print(f"  [t] {pb_rec['type']:<6} {pb_rec['name']:<45} {pb_rec['content'][:40]}")
            print(f"        porkbun-ttl={pb_rec['ttl']}   config-ttl={cfg_rec['ttl']}")

    if diff.skipped_acme:
        print(f"\n  Skipped: {diff.skipped_acme} _acme-challenge TXT records (transient lego tokens, ignored)")

    print(f"\n  {diff.in_sync} records in sync")
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
.venv/bin/pytest tests/test_catchup_output.py -v
```

Expected: all 8 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add scripts/manage_porkbun.py tests/test_catchup_output.py
git commit -m "feat(catchup): add print_catchup_report() with output tests"
```

---

## Task 4: `write_catchup_to_config()`

**Files:**
- Modify: `scripts/manage_porkbun.py` — add `write_catchup_to_config()`
- Create: `tests/test_write_catchup.py`

**Interfaces:**
- Consumes: `DomainDiff` (Task 1), `base_dir: Path` (global)
- Produces: `write_catchup_to_config(domain: str, diff: DomainDiff, date_str: str) -> Path` — returns path of file written to

- [ ] **Step 1: Write failing tests**

Create `tests/test_write_catchup.py`:

```python
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
import scripts.manage_porkbun as mp
from scripts.manage_porkbun import DomainDiff, write_catchup_to_config


def make_record(name, rtype, content, ttl="600", prio="None"):
    return {"name": name, "type": rtype, "content": content, "ttl": str(ttl), "prio": prio}


def setup_fake_etc(tmp_path, domain, is_template=False):
    """Create a fake etc/ structure so write_catchup_to_config has files to append to."""
    files_dir = tmp_path / "etc" / "files"
    templates_dir = tmp_path / "etc" / "templates"
    files_dir.mkdir(parents=True)
    templates_dir.mkdir(parents=True)

    if is_template:
        tmpl = templates_dir / f"{domain}.j2"
        tmpl.write_text(f"[{domain}]\n# existing template content\n")
    else:
        f = files_dir / domain
        f.write_text(f"[{domain}]\n# existing config\n")

    mp.base_dir = tmp_path
    return tmp_path


def test_porkbun_only_record_appended_as_live_entry(tmp_path):
    setup_fake_etc(tmp_path, "example.com")
    rec = make_record("clerk.example.com", "CNAME", "frontend-api.clerk.services")
    diff = DomainDiff(porkbun_only=[rec])

    write_catchup_to_config("example.com", diff, "2026-07-19")

    content = (tmp_path / "etc" / "files" / "example.com").read_text()
    assert "# catchup 2026-07-19" in content
    assert "CNAME" in content
    assert "clerk.example.com" in content
    assert "frontend-api.clerk.services" in content
    assert content.count("#") <= 2  # only the header comment, not commented-out records


def test_value_conflict_appended_as_comments(tmp_path):
    setup_fake_etc(tmp_path, "example.com")
    pb = make_record("eva.example.com", "A", "96.246.42.235", ttl="60")
    cfg = make_record("eva.example.com", "A", "74.101.18.186", ttl="60")
    diff = DomainDiff(value_conflicts=[(pb, cfg)])

    write_catchup_to_config("example.com", diff, "2026-07-19")

    content = (tmp_path / "etc" / "files" / "example.com").read_text()
    assert "# CONFLICT" in content
    assert "# CONFIG:" in content
    assert "74.101.18.186" in content
    assert "# PORKBUN:" in content
    assert "96.246.42.235" in content
    # Neither version should be a live (uncommented) record
    lines = [l for l in content.splitlines() if "eva.example.com" in l]
    assert all(l.strip().startswith("#") for l in lines)


def test_ttl_conflict_appended_as_comments(tmp_path):
    setup_fake_etc(tmp_path, "example.com")
    pb = make_record("example.com", "TXT", "v=spf1 include:_spf.porkbun.com ~all", ttl="600")
    cfg = make_record("example.com", "TXT", "v=spf1 include:_spf.porkbun.com ~all", ttl="300")
    diff = DomainDiff(ttl_conflicts=[(pb, cfg)])

    write_catchup_to_config("example.com", diff, "2026-07-19")

    content = (tmp_path / "etc" / "files" / "example.com").read_text()
    assert "# TTL CONFLICT" in content
    assert "# CONFIG-TTL:" in content
    assert "300" in content
    assert "# PORKBUN-TTL:" in content
    assert "600" in content


def test_template_domain_writes_to_j2_file(tmp_path):
    setup_fake_etc(tmp_path, "nicklange.family", is_template=True)
    rec = make_record("new.nicklange.family", "A", "1.2.3.4")
    diff = DomainDiff(porkbun_only=[rec])

    write_catchup_to_config("nicklange.family", diff, "2026-07-19")

    content = (tmp_path / "etc" / "templates" / "nicklange.family.j2").read_text()
    assert "new.nicklange.family" in content
    assert "# TODO: replace raw IPs with template vars if applicable" in content


def test_nothing_written_when_diff_is_empty(tmp_path):
    setup_fake_etc(tmp_path, "example.com")
    original = (tmp_path / "etc" / "files" / "example.com").read_text()

    write_catchup_to_config("example.com", DomainDiff(), "2026-07-19")

    content = (tmp_path / "etc" / "files" / "example.com").read_text()
    assert content == original
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
.venv/bin/pytest tests/test_write_catchup.py -v
```

Expected: `ImportError: cannot import name 'write_catchup_to_config'`

- [ ] **Step 3: Implement `write_catchup_to_config()` in `manage_porkbun.py`**

Add after `print_catchup_report()`:

```python
def write_catchup_to_config(domain: str, diff: DomainDiff, date_str: str) -> None:
    """Append porkbun-only records and conflict comments to the domain config file."""
    has_content = diff.porkbun_only or diff.value_conflicts or diff.ttl_conflicts
    if not has_content:
        return

    is_template = (base_dir / "etc" / "templates" / f"{domain}.j2").exists()
    if is_template:
        target = base_dir / "etc" / "templates" / f"{domain}.j2"
    else:
        target = base_dir / "etc" / "files" / domain

    lines = [f"\n# catchup {date_str}\n"]

    if is_template and diff.porkbun_only:
        lines.append("# TODO: replace raw IPs with template vars if applicable\n")

    for rec in diff.porkbun_only:
        prio_part = f"    {rec['prio']}" if rec.get("prio") and rec["prio"] not in ("None", "0") else ""
        lines.append(f"{rec['type']:<6}  {rec['name']:<45}  {rec['content']:<40}  {rec['ttl']}{prio_part}\n")

    for pb_rec, cfg_rec in diff.value_conflicts:
        prio_part = f"    {cfg_rec['prio']}" if cfg_rec.get("prio") and cfg_rec["prio"] not in ("None", "0") else ""
        lines.append(f"# CONFLICT: choose one and remove the other\n")
        lines.append(f"# CONFIG:   {cfg_rec['type']:<6}  {cfg_rec['name']:<45}  {cfg_rec['content']:<40}  {cfg_rec['ttl']}{prio_part}\n")
        lines.append(f"# PORKBUN:  {pb_rec['type']:<6}  {pb_rec['name']:<45}  {pb_rec['content']:<40}  {pb_rec['ttl']}\n")

    for pb_rec, cfg_rec in diff.ttl_conflicts:
        lines.append(f"# TTL CONFLICT: same record, different TTL — choose one\n")
        lines.append(f"# CONFIG-TTL:   {cfg_rec['type']:<6}  {cfg_rec['name']:<45}  \"{cfg_rec['content']}\"  {cfg_rec['ttl']}\n")
        lines.append(f"# PORKBUN-TTL:  {pb_rec['type']:<6}  {pb_rec['name']:<45}  \"{pb_rec['content']}\"  {pb_rec['ttl']}\n")

    with open(target, "a") as f:
        f.writelines(lines)

    logger.info(f"Wrote catchup entries for {domain} to {target}")
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
.venv/bin/pytest tests/test_write_catchup.py -v
```

Expected: all 5 tests `PASSED`

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add scripts/manage_porkbun.py tests/test_write_catchup.py
git commit -m "feat(catchup): add write_catchup_to_config() with file write tests"
```

---

## Task 5: `create_catchup_branch()` and git commit

**Files:**
- Modify: `scripts/manage_porkbun.py` — add `create_catchup_branch()` and `commit_catchup()`

**Interfaces:**
- Produces:
  - `create_catchup_branch(date_str: str) -> str` — creates `catchup/<date_str>` in `etc/` submodule, returns branch name
  - `commit_catchup(date_str: str, n_records: int, n_conflicts: int, n_domains: int) -> None` — stages all changes in `etc/` and commits

No unit tests for git operations (they require a real git repo). Manual verification in Step 4.

- [ ] **Step 1: Add `subprocess` import to `manage_porkbun.py`**

Add to the imports block at the top:

```python
import subprocess
from datetime import date
```

- [ ] **Step 2: Implement `create_catchup_branch()` and `commit_catchup()`**

Add after `write_catchup_to_config()`:

```python
def create_catchup_branch(date_str: str) -> str:
    """Create a catchup/<date_str> branch in the etc/ submodule."""
    etc_path = str(base_dir / "etc")
    branch = f"catchup/{date_str}"
    result = subprocess.run(
        ["git", "-C", etc_path, "checkout", "-b", branch],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to create branch {branch} in etc/: {result.stderr.strip()}"
        )
    logger.info(f"Created branch {branch} in etc/ submodule")
    return branch


def commit_catchup(date_str: str, n_records: int, n_conflicts: int, n_domains: int) -> None:
    """Stage and commit all catchup changes in the etc/ submodule."""
    etc_path = str(base_dir / "etc")
    subprocess.run(["git", "-C", etc_path, "add", "-A"], check=True)
    msg = f"catchup: add {n_records} records, flag {n_conflicts} conflicts across {n_domains} domains ({date_str})"
    subprocess.run(["git", "-C", etc_path, "commit", "-m", msg], check=True)
    logger.info(f"Committed catchup changes to etc/ on branch catchup/{date_str}")
```

- [ ] **Step 3: Run full test suite to check nothing broke**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests `PASSED`

- [ ] **Step 4: Manual smoke test of branch creation (dry run — won't write anything)**

```bash
.venv/bin/python scripts/manage_porkbun.py --catch-up --dry-run 2>&1 | head -5
```

Expected at this point: `Error: No such option: --catch-up` (the flag doesn't exist yet — confirming we haven't broken anything)

- [ ] **Step 5: Commit**

```bash
git add scripts/manage_porkbun.py
git commit -m "feat(catchup): add create_catchup_branch() and commit_catchup()"
```

---

## Task 6: Wire `--catch-up` into `main()` and end-to-end test

**Files:**
- Modify: `scripts/manage_porkbun.py` — add `--catch-up` option to `main()`, add catch-up path

**Interfaces:**
- Consumes: all functions from Tasks 1-5
- Produces: working `--catch-up` and `--catch-up --dry-run` CLI flags

- [ ] **Step 1: Add `--catch-up` option and catch-up path to `main()`**

Add the new option decorator (below the existing `--domain` option):

```python
@click.option(
    "--catch-up", "catch_up", is_flag=True,
    help="Diff Porkbun vs config and optionally pull porkbun-only records to a new config branch"
)
```

Update the `main` function signature to include `catch_up`:

```python
def main(dry_run, verbose, domain, catch_up):
```

Add the catch-up path at the end of `main()`, replacing the existing domain processing block with:

```python
    # Determine which domains to process
    if domain:
        if domain not in app_config["domains"]:
            logger.error(f"Domain '{domain}' not found in configuration")
            sys.exit(1)
        domains_to_process = [domain]
    else:
        domains_to_process = app_config["domains"]

    if catch_up:
        # --- catch-up mode: diff only, no sync ---
        total_records = 0
        total_conflicts = 0
        diffs = {}
        for domain_name in domains_to_process:
            try:
                desired = load_domain(domain_name)
                existing = get_records(domain_name)
                diff = diff_domain(domain_name, desired, existing)
                diffs[domain_name] = diff
                print_catchup_report(domain_name, diff)
                total_records += len(diff.porkbun_only)
                total_conflicts += len(diff.value_conflicts) + len(diff.ttl_conflicts)
            except Exception as e:
                logger.error(f"Error processing domain {domain_name}: {e}")
                if verbose:
                    import traceback
                    traceback.print_exc()

        has_anything_to_write = any(
            d.porkbun_only or d.value_conflicts or d.ttl_conflicts
            for d in diffs.values()
        )

        if not dry_run and has_anything_to_write:
            date_str = date.today().isoformat()
            branch = create_catchup_branch(date_str)
            for domain_name, diff in diffs.items():
                write_catchup_to_config(domain_name, diff, date_str)
            commit_catchup(date_str, total_records, total_conflicts, len(diffs))
            print(f"\nCatchup branch created: {branch} (in etc/ submodule)")
            print("Review changes and raise a PR from etc/ when ready.")
        elif dry_run and has_anything_to_write:
            print(f"\nDRY RUN: would create catchup branch and commit {total_records} records + {total_conflicts} conflicts")
    else:
        # --- normal sync mode ---
        for domain_name in domains_to_process:
            try:
                process_domain(domain_name, dry_run=dry_run)
            except Exception as e:
                logger.error(f"Error processing domain {domain_name}: {e}")
                if verbose:
                    import traceback
                    traceback.print_exc()

    logger.info("Processing complete")
```

- [ ] **Step 2: Run full test suite**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all tests `PASSED`

- [ ] **Step 3: End-to-end dry-run smoke test against live Porkbun**

```bash
.venv/bin/python scripts/manage_porkbun.py --catch-up --dry-run 2>&1
```

Expected output includes:
- `=== nicklange.family ===`
- `VALUE CONFLICTS` section with the newyork IP records
- `=== recruiter-rankings.com ===`
- `PORKBUN-ONLY` section with the 5 Clerk CNAMEs
- `DRY RUN: would create catchup branch`
- No errors

- [ ] **Step 4: Verify `--dry-run` alone still works (no regression)**

```bash
.venv/bin/python scripts/manage_porkbun.py --dry-run --domain 5l-labs.com 2>&1 | grep -E "DRY RUN|Processing complete"
```

Expected: `DRY RUN: Would delete record...` lines and `Processing complete`

- [ ] **Step 5: Commit**

```bash
git add scripts/manage_porkbun.py
git commit -m "feat(catchup): wire --catch-up flag into main(), end-to-end flow complete"
```

- [ ] **Step 6: Push and update PR**

```bash
git push
```

---

## Self-Review

**Spec coverage check:**
- ✅ `--catch-up` flag (Task 6)
- ✅ `--catch-up --dry-run` = report only (Task 6)
- ✅ `_acme-challenge` filtered from all output (Task 2 `diff_domain`)
- ✅ Four diff categories: porkbun-only, config-only, value conflicts, TTL conflicts (Task 2)
- ✅ Human-readable report (Task 3)
- ✅ Non-conflict records appended as live entries (Task 4)
- ✅ Conflict pairs appended as commented lines (Task 4)
- ✅ TTL conflicts appended as commented pairs (Task 4)
- ✅ Template domains detected and written to `.j2` file (Task 4)
- ✅ Branch `catchup/YYYY-MM-DD` in `etc/` submodule (Task 5)
- ✅ Single commit in `etc/` (Task 5)
- ✅ Parent repo submodule pointer NOT auto-updated (by design — not in code)
- ✅ Known limitation noted: prio mismatches invisible (in spec, not code)
