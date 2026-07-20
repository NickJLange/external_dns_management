#!/usr/bin/env python3
import json
import requests
import re
import sys
import os
import shutil
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from pprint import pprint, pformat

import click
import logging
import configparser
from jinja2 import Environment, FileSystemLoader

# Global constants
PORKBUN_PUBLIC_API_KEY = "porkbun_api_key"
PORKBUN_PRIVATE_API_KEY = "porkbun_secret_api_key"
PORKBUN_REST_ENDPOINT = "porkbun_rest_endpoint"

@dataclass
class DomainDiff:
    porkbun_only: list = field(default_factory=list)    # non-conflict porkbun records
    config_only: list = field(default_factory=list)     # non-conflict config records
    value_conflicts: list = field(default_factory=list) # list of (porkbun_rec, config_rec)
    ttl_conflicts: list = field(default_factory=list)   # list of (porkbun_rec, config_rec)
    in_sync: int = 0
    skipped_acme: int = 0


# Global variables
basic_rest_data = dict()
base_endpoint: str = None
base_dir: Path = None
logger: logging.Logger = logging.getLogger(__name__)

###################### WARNING
## Will blow away entries that are not found in config - this is the law
## Will leave carve out for anything found north of a NS record (indicating served by another provider)


def diff_domain(domain: str, desired: dict, existing: dict) -> DomainDiff:
    """Compare desired config state vs live Porkbun state, categorise differences."""
    diff = DomainDiff()

    def is_acme(record: dict) -> bool:
        return record.get("name", "").startswith("_acme-challenge.")

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

    diff.in_sync = len(desired_keys & existing_keys)

    only_in_existing = existing_keys - desired_keys
    only_in_desired = desired_keys - existing_keys

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
        pb_recs = list(existing_by_nt[nt])
        cfg_recs = list(desired_by_nt[nt])
        matched_pb, matched_cfg = set(), set()
        for i, pb_rec in enumerate(pb_recs):
            for j, cfg_rec in enumerate(cfg_recs):
                if j in matched_cfg:
                    continue
                if pb_rec["content"] == cfg_rec["content"]:
                    pb_prio = str(pb_rec.get("prio") or "0")
                    cfg_prio = str(cfg_rec.get("prio") or "0")
                    if pb_prio == cfg_prio:
                        diff.ttl_conflicts.append((pb_rec, cfg_rec))
                    else:
                        diff.value_conflicts.append((pb_rec, cfg_rec))
                    matched_pb.add(i)
                    matched_cfg.add(j)
                    break
        unmatched_pb = [r for i, r in enumerate(pb_recs) if i not in matched_pb]
        unmatched_cfg = [r for j, r in enumerate(cfg_recs) if j not in matched_cfg]
        for pb_rec in unmatched_pb:
            for cfg_rec in unmatched_cfg:
                diff.value_conflicts.append((pb_rec, cfg_rec))

    for nt, recs in existing_by_nt.items():
        if nt not in conflict_nts:
            diff.porkbun_only.extend(recs)

    for nt, recs in desired_by_nt.items():
        if nt not in conflict_nts:
            diff.config_only.extend(recs)

    return diff


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
        content = f'"{rec["content"]}"' if " " in rec["content"] else rec["content"]
        lines.append(f"{rec['type']:<6}  {rec['name']:<45}  {content:<40}  {rec['ttl']}{prio_part}\n")

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


def create_catchup_branch(date_str: str) -> str:
    """Create a catchup/<date_str> branch in the etc/ submodule."""
    etc_path = str(base_dir / "etc")
    status = subprocess.run(
        ["git", "-C", etc_path, "status", "--porcelain"],
        capture_output=True, text=True, check=True
    )
    if status.stdout.strip():
        raise RuntimeError("etc/ submodule has uncommitted changes — commit or stash them before running catch-up")
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
    msg = (
        f"catchup: add {n_records} records, flag {n_conflicts} conflicts "
        f"across {n_domains} domains ({date_str})"
    )
    subprocess.run(["git", "-C", etc_path, "commit", "-m", msg], check=True)
    logger.info(f"Committed catchup changes to etc/ on branch catchup/{date_str}")


def raise_catchup_pr(date_str: str, n_records: int, n_conflicts: int, n_domains: int) -> str:
    """Push the catchup branch and open a PR in the etc/ submodule repo."""
    etc_path = str(base_dir / "etc")
    branch = f"catchup/{date_str}"

    push = subprocess.run(
        ["git", "-C", etc_path, "push", "-u", "origin", branch],
        capture_output=True, text=True
    )
    if push.returncode != 0:
        logger.error(f"Failed to push {branch}: {push.stderr.strip()}")
        return None

    body = (
        f"## Catch-up DNS sync — {date_str}\n\n"
        f"- **{n_records}** porkbun-only records added as live entries\n"
        f"- **{n_conflicts}** conflicts (value or TTL) left as commented pairs for manual resolution\n"
        f"- **{n_domains}** domains processed\n\n"
        "### Review notes\n"
        "- Uncommented lines are safe to keep — they mirror what Porkbun already serves.\n"
        "- `# CONFLICT:` blocks need a manual choice: pick one line, delete the other.\n"
        "- `# TTL CONFLICT:` blocks: pick the TTL you want, write the live record, delete both comments.\n"
        "- Template domains (`*.j2`): replace raw IPs with template vars where applicable.\n\n"
        "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
    )

    result = subprocess.run(
        [
            "gh", "pr", "create",
            "--base", "main",
            "--head", branch,
            "--title", f"catchup: DNS sync {date_str} ({n_records} records, {n_conflicts} conflicts)",
            "--body", body,
        ],
        capture_output=True, text=True, cwd=str(base_dir / "etc")
    )
    if result.returncode != 0:
        logger.error(f"gh pr create failed: {result.stderr.strip()}")
        return None
    return result.stdout.strip()


def setup_logging(verbose: bool = False):
    """Setup logging with appropriate level based on verbose flag"""
    global logger
    logger = logging.getLogger(__name__)

    # Clear any existing handlers
    logger.handlers.clear()

    # Set level based on verbose flag
    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)

    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "[%(asctime)s] - [%(name)s] - [%(levelname)s] - [%(funcName)s:%(lineno)d] - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


def discover_base_dir():
    """Discover the base directory based on script location"""
    global logger
    global base_dir
    script_path = Path(__file__).resolve()
    # Go up one level from scripts/ to get the project root
    base_dir = script_path.parent.parent
    logger.debug(f"Base directory discovered: {base_dir}")
    return base_dir


def gen_key(ds: dict[str, str]) -> str:
    """Generate a unique key for a DNS record"""
    prio = str(ds.get("prio") or "0")
    if prio in ("None", ""):
        prio = "0"
    key = "_".join(
        [ds["name"].lower(), ds["content"], ds["type"].lower(), str(ds["ttl"]).lower(), prio]
    )
    return key


def init_config():
    """Initialize configuration from config.ini file"""
    global logger

    config_location = base_dir / "etc" / "config.ini"
    app_config = dict()
    config = configparser.ConfigParser(allow_no_value=True)
    config.optionxform = str
    try:
        config.read(config_location)

        # Load domains
        app_config["domains"] = list()
        for domain in config["domains"]:
            app_config["domains"].append(domain)

        # Load API credentials
        app_config[PORKBUN_PUBLIC_API_KEY] = config.get(
            "general",
            PORKBUN_PUBLIC_API_KEY,
            fallback=os.environ.get("PORKBUN_API_KEY", ""),
        )
        app_config[PORKBUN_PRIVATE_API_KEY] = config.get(
            "general",
            PORKBUN_PRIVATE_API_KEY,
            fallback=os.environ.get("PORKBUN_SECRET_API_KEY", ""),
        )
        app_config["porkbun_rest_endpoint"] = config.get(
            "general",
            "porkbun_rest_endpoint",
            fallback=os.environ.get("PORKBUN_REST_ENDPOINT"),
        )

        # Load public IPs
        app_config["public_ips"] = dict()
        if "public_ips" in config:
            for key in config["public_ips"]:
                app_config["public_ips"][key] = config["public_ips"][key]

        logger.info(f"Successfully read configs from: {config_location}")
        logger.debug(f"Config: {pformat(app_config)}")

    except configparser.Error as e:
        logger.error(f"Couldn't read configs from: {config_location} - {e}")
        sys.exit(1)
    except FileNotFoundError:
        logger.error(f"Config file not found: {config_location}")
        sys.exit(1)

    return app_config


def process_templates(app_config):
    """Process Jinja2 templates and output to ../output folder"""
    global logger

    templates_dir = base_dir / "etc" / "templates"
    output_dir = base_dir / "output"

    # Create output directory if it doesn't exist
    output_dir.mkdir(exist_ok=True)

    if not templates_dir.exists():
        logger.debug(f"Templates directory not found: {templates_dir}")
        return

    # Setup Jinja2 environment
    env = Environment(loader=FileSystemLoader(templates_dir))

    # Process all .j2 files
    for template_file in templates_dir.glob("*.j2"):
        logger.info(f"Processing template: {template_file.name}")

        try:
            template = env.get_template(template_file.name)
            rendered = template.render(**app_config["public_ips"])

            # Remove .j2 extension for output file
            output_file = output_dir / template_file.stem

            with open(output_file, "w") as f:
                f.write(rendered)

            logger.debug(f"Template {template_file.name} rendered to {output_file}")

        except Exception as e:
            logger.error(f"Error processing template {template_file.name}: {e}")


def copy_files():
    """Copy files from files/ directory to ../output folder verbatim"""
    global logger

    files_dir = base_dir / "etc" / "files"
    output_dir = base_dir / "output"

    # Create output directory if it doesn't exist
    output_dir.mkdir(exist_ok=True)

    if not files_dir.exists():
        logger.debug(f"Files directory not found: {files_dir}")
        return

    # Copy all files
    for file_path in files_dir.iterdir():
        if file_path.is_file():
            dest_path = output_dir / file_path.name
            shutil.copy2(file_path, dest_path)
            logger.info(f"Copied {file_path.name} to output directory")
            logger.debug(f"Source: {file_path}, Destination: {dest_path}")


def load_domain(domain):
    """Load domain configuration from output directory"""
    global logger
    config_location = base_dir / "output" / domain
    desired_state = dict()
    #    config = configparser.ConfigParser(allow_no_value=True, delimiters=["|"])

    try:
        with open(config_location, "r") as f:
            header = f.readline()
            if (
                domain not in header
                or not header.startswith("[")
                or not header.strip().endswith("]")
            ):
                logger.error(f"Invalid config format in {config_location}")
                return desired_state

            for raw in f:
                if raw.strip().startswith("#") or not raw.strip():
                    continue  # Skip comments and empty lines
                parts = [p.strip() for p in shlex.split(raw)]
                if len(parts) < 4:
                    logger.warning(f"Skipping malformed record: {raw}")
                    continue

                ds = {
                    "type": parts[0],
                    "name": parts[1],
                    "content": parts[2],
                    "ttl": parts[3],
                    "prio": "None",
                }

                # Handle priority for MX and SRV records
                if len(parts) > 4 and parts[4].strip():
                    ds["prio"] = parts[4]

                key = gen_key(ds)
                desired_state[key] = ds

            logger.info(
                f"Successfully read domain config for {domain} from: {config_location}"
            )
            logger.debug(f"Desired state for {domain}: {pformat(desired_state)}")

    except configparser.Error as e:
        logger.error(f"Couldn't read configs from: {config_location} - {e}")
    except FileNotFoundError:
        logger.error(f"Domain config file not found: {config_location}")

    return desired_state


def runner(method, url_args=None, data_args=None):
    """Execute API calls to Porkbun"""
    global basic_rest_data
    global base_endpoint
    global logger

    full_url = [base_endpoint, method]
    if url_args:
        full_url.extend(url_args)
    url = "/".join(full_url)

    req_data = dict(basic_rest_data)
    if data_args:
        req_data = basic_rest_data | data_args

    logger.info(f"API Call: {method} - {url}")
    logger.debug(f"Payload: {pformat(req_data)}")

    try:
        payload = json.dumps(req_data)
        req = requests.post(url, data=payload)
        req.raise_for_status()
        response = json.loads(req.text)
        logger.debug(f"API Response: {req.text}")
        return response
    except requests.HTTPError as e:
        try:
            api_msg = req.json().get("message", f"HTTP {req.status_code}")
        except Exception:
            api_msg = f"HTTP {req.status_code}"
        logger.error(f"HTTP error from API ({req.status_code}): {api_msg}")
        return {"status": "ERROR", "message": api_msg}
    except requests.RequestException as e:
        logger.error(f"API request failed: {e}")
        return {"status": "ERROR", "message": str(e)}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse API response: {e}")
        return {"status": "ERROR", "message": "Invalid JSON response"}


def create_record(domain, add_key, record, dry_run=False):
    """Create a DNS record"""
    global logger
    response = None
    method = "dns/create"
    data = {
        "type": record["type"].upper(),
        "ttl": record["ttl"],
        "content": record["content"],
        "name": re.split(r"\.?" + re.escape(domain) + r"$", record["name"])[0],
    }

    if "prio" in record and record["prio"] != "None" and record["prio"] != "0":
        data["prio"] = record["prio"]

    if dry_run:
        logger.info(
            f"DRY RUN: Would create record {add_key} {data['type']} {data['name']} -> {data['content']}"
        )
    else:
        logger.debug(f"Creating record: {pformat(data)}")
        response = runner(method, url_args=[domain], data_args=data)
        if response and response.get("status") == "SUCCESS":
            logger.info(f"Created record {data['type']} {data['name']} -> {data['content']}")
        else:
            logger.error(
                f"Failed to create record {data['type']} {data['name']} -> {data['content']}: "
                f"{response.get('message', 'unknown error') if response else 'no response'}"
            )

    return response


def delete_record(domain, record_id, record=None, dry_run=False):
    """Delete a DNS record"""
    response = None
    label = f"{record['type']} {record['name']} -> {record['content']}" if record else f"ID {record_id}"
    if dry_run:
        logger.info(f"DRY RUN: Would delete record {label} (ID {record_id})")
    else:
        method = "dns/delete"
        response = runner(method, url_args=[domain, record_id])
        if response and response.get("status") == "SUCCESS":
            logger.info(f"Deleted record {label}")
        else:
            logger.error(
                f"Failed to delete record {label}: "
                f"{response.get('message', 'unknown error') if response else 'no response'}"
            )

    return response


def check_credentials():
    """Check API credentials"""
    return runner("ping")


def get_records(domain):
    """Get all DNS records for a domain"""
    global logger
    method = "dns/retrieve"
    response = runner(method, url_args=[domain])

    if response["status"] == "ERROR":
        logger.error(
            f"Error getting domain {domain}. Check domain and API access settings."
        )
        return dict()

    existing = dict()
    for entry in response.get("records", []):
        if not entry.get("prio"):
            entry["prio"] = "None"
        key = gen_key(entry)
        existing[key] = entry

    logger.debug(f"Retrieved {len(existing)} existing records for {domain}")
    return existing


def process_domain(domain, dry_run=False):
    """Process a single domain - compare desired vs existing state and make changes"""
    global logger
    logger.info(f"Processing domain: {domain}")

    # Load desired state from output directory
    desired = load_domain(domain)
    if not desired:
        logger.warning(f"No configuration found for domain {domain}")
        return

    # Get existing state from Porkbun
    existing = get_records(domain)

    # Calculate differences
    deletes = set(existing.keys()) - set(desired.keys())
    adds = set(desired.keys()) - set(existing.keys())

    logger.info(
        f"Domain {domain}: {len(adds)} records to add, {len(deletes)} records to delete"
    )

    # Delete records that shouldn't exist
    for delete_key in deletes:
        record = existing[delete_key]
        # Carve-out: never delete NS records for delegated subdomains.
        # Apex NS records (name == domain) are managed via config; subdomain NS
        # records indicate delegation to another provider and must be preserved.
        if record.get("type", "").upper() == "NS" and record.get("name", "").lower() != domain.lower():
            logger.info(f"Skipping deletion of delegated NS record: {record['name']} -> {record['content']}")
            continue
        if "id" in record:
            delete_record(domain, record["id"], record=record, dry_run=dry_run)
        else:
            logger.warning(f"Cannot delete record without ID: {delete_key}")

    # Create new records
    for add_key in adds:
        record = desired[add_key]
        create_record(domain, add_key, record, dry_run=dry_run)


@click.command()
@click.option(
    "--dry-run", is_flag=True, help="Show what would be done without making changes"
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option(
    "--domain", help="Process only this domain instead of all configured domains"
)
@click.option(
    "--catch-up", "catch_up", is_flag=True,
    help="Diff Porkbun vs config and optionally pull porkbun-only records to a new config branch"
)
def main(dry_run, verbose, domain, catch_up):
    """Manage Porkbun DNS records from configuration files"""
    global basic_rest_data, base_endpoint

    # Setup logging
    setup_logging(verbose)

    # Discover base directory
    discover_base_dir()

    # Initialize configuration
    app_config = init_config()

    # Setup API credentials
    basic_rest_data = {
        "secretapikey": app_config[PORKBUN_PRIVATE_API_KEY],
        "apikey": app_config[PORKBUN_PUBLIC_API_KEY],
    }
    base_endpoint = app_config["porkbun_rest_endpoint"]

    # Check credentials — always validate; only hard-exit on failure when not dry-run
    logger.info("Checking API credentials...")
    res = check_credentials()
    if res.get("status") == "SUCCESS":
        our_ip = res.get("yourIp", "unknown")
        logger.info(f"API credentials valid. Your IP: {our_ip}")
    else:
        logger.error(f"Failed to verify API credentials: {res.get('message', 'unknown error')}")
        if not dry_run:
            sys.exit(1)
        logger.warning("Continuing in dry-run mode with unverified credentials")

    # Process templates and copy files
    logger.info("Processing templates...")
    process_templates(app_config)

    logger.info("Copying files...")
    copy_files()

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
                d = diff_domain(domain_name, desired, existing)
                diffs[domain_name] = d
                print_catchup_report(domain_name, d)
                total_records += len(d.porkbun_only)
                total_conflicts += len(d.value_conflicts) + len(d.ttl_conflicts)
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
            for domain_name, d in diffs.items():
                write_catchup_to_config(domain_name, d, date_str)
            commit_catchup(date_str, total_records, total_conflicts, len(diffs))
            print(f"\nCatchup branch created: {branch} (in etc/ submodule)")
            pr_url = raise_catchup_pr(date_str, total_records, total_conflicts, len(diffs))
            if pr_url:
                print(f"PR raised: {pr_url}")
            else:
                logger.error("PR creation failed — branch is pushed, raise the PR manually")
                sys.exit(1)
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


if __name__ == "__main__":
    main()
