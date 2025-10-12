#!/usr/bin/env python3
import json
import requests
import re
import sys
import os
import shutil
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

# Global variables
basic_rest_data = dict()
base_endpoint = None
base_dir = None
logger = None

###################### WARNING
## Will blow away entries that are not found in config - this is the law
## Will leave carve out for anything found north of a NS record (indicating served by another provider)


def setup_logging(verbose=False):
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
        "[%(asctime)s] - [%(name)s] - [%(levelname)s] - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger


def discover_base_dir():
    """Discover the base directory based on script location"""
    global base_dir
    script_path = Path(__file__).resolve()
    # Go up one level from scripts/ to get the project root
    base_dir = script_path.parent.parent
    logger.debug(f"Base directory discovered: {base_dir}")
    return base_dir


def gen_key(ds):
    """Generate a unique key for a DNS record"""
    key = "_".join([ds["name"], ds["content"], ds["type"], ds["ttl"]]).lower()
    return key


def init_config():
    """Initialize configuration from config.ini file"""
    config_location = base_dir / "etc" / "config.ini"
    app_config = dict()
    config = configparser.ConfigParser(allow_no_value=True)
    
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
            
            with open(output_file, 'w') as f:
                f.write(rendered)
                
            logger.debug(f"Template {template_file.name} rendered to {output_file}")
            
        except Exception as e:
            logger.error(f"Error processing template {template_file.name}: {e}")


def copy_files():
    """Copy files from files/ directory to ../output folder verbatim"""
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
    config_location = base_dir / "output" / domain
    desired_state = dict()
    config = configparser.ConfigParser(allow_no_value=True, delimiters=["|"])
    
    try:
        config.read(config_location)
        
        if domain not in config:
            logger.error(f"Domain [{domain}] section not found in {config_location}")
            return desired_state
            
        for raw in config[domain]:
            if raw.strip().startswith('#') or not raw.strip():
                continue  # Skip comments and empty lines
                
            parts = re.split(r"\s{4}", raw)
            if len(parts) < 4:
                logger.warning(f"Skipping malformed record: {raw}")
                continue
                
            ds = {
                "name": parts[1],
                "type": parts[0],
                "prio": "None",
                "ttl": parts[3],
                "content": parts[2],
            }
            
            # Handle priority for MX and SRV records
            if len(parts) > 4 and parts[4].strip():
                ds["prio"] = parts[4]
                
            key = gen_key(ds)
            desired_state[key] = ds
            
        logger.info(f"Successfully read domain config for {domain} from: {config_location}")
        logger.debug(f"Desired state for {domain}: {pformat(desired_state)}")
        
    except configparser.Error as e:
        logger.error(f"Couldn't read configs from: {config_location} - {e}")
    except FileNotFoundError:
        logger.error(f"Domain config file not found: {config_location}")
        
    return desired_state


def runner(method, url_args=None, data_args=None, dry_run=False):
    """Execute API calls to Porkbun"""
    global basic_rest_data
    global base_endpoint
    
    full_url = [base_endpoint, method]
    if url_args:
        full_url.extend(url_args)
    url = "/".join(full_url)
    
    req_data = dict(basic_rest_data)
    if data_args:
        req_data = basic_rest_data | data_args
        
    logger.info(f"API Call: {method} - {url}")
    logger.debug(f"Payload: {pformat(req_data)}")
    
    if dry_run:
        logger.info(f"DRY RUN: Would call {url} with payload: {pformat(req_data)}")
        return {"status": "DRY_RUN", "message": "Dry run - no actual API call made"}
    
    try:
        payload = json.dumps(req_data)
        req = requests.post(url, data=payload)
        response = json.loads(req.text)
        logger.debug(f"API Response: {req.text}")
        return response
    except requests.RequestException as e:
        logger.error(f"API request failed: {e}")
        return {"status": "ERROR", "message": str(e)}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse API response: {e}")
        return {"status": "ERROR", "message": "Invalid JSON response"}


def create_record(domain, record, dry_run=False):
    """Create a DNS record"""
    method = "dns/create"
    data = {
        "type": record["type"].upper(),
        "ttl": record["ttl"],
        "content": record["content"],
        "name": re.split(r".?%s" % domain, record["name"])[0],
    }
    
    if "prio" in record and record["prio"] != "None" and record["prio"] != "0":
        data["prio"] = record["prio"]
        
    logger.debug(f"Creating record: {pformat(data)}")
    response = runner(method, url_args=[domain], data_args=data, dry_run=dry_run)
    
    if dry_run:
        logger.info(f"DRY RUN: Would create record {record['type']} {record['name']} -> {record['content']}")
    else:
        logger.info(f"Created record {record['type']} {record['name']} -> {record['content']}")
        
    return response


def delete_record(domain, record_id, dry_run=False):
    """Delete a DNS record"""
    method = "dns/delete"
    response = runner(method, url_args=[domain, record_id], dry_run=dry_run)
    
    if dry_run:
        logger.info(f"DRY RUN: Would delete record ID {record_id}")
    else:
        logger.info(f"Deleted record ID {record_id}")
        
    return response


def check_credentials(dry_run=False):
    """Check API credentials"""
    return runner("ping", dry_run=dry_run)


def get_records(domain, dry_run=False):
    """Get all DNS records for a domain"""
    method = "dns/retrieve"
    response = runner(method, url_args=[domain], dry_run=dry_run)
    
    if dry_run:
        logger.info(f"DRY RUN: Would retrieve records for {domain}")
        return dict()
        
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
    logger.info(f"Processing domain: {domain}")
    
    # Load desired state from output directory
    desired = load_domain(domain)
    if not desired:
        logger.warning(f"No configuration found for domain {domain}")
        return
    
    # Get existing state from Porkbun
    existing = get_records(domain, dry_run=dry_run)
    
    # Calculate differences
    deletes = set(existing.keys()) - set(desired.keys())
    adds = set(desired.keys()) - set(existing.keys())
    
    logger.info(f"Domain {domain}: {len(adds)} records to add, {len(deletes)} records to delete")
    
    # Delete records that shouldn't exist
    for delete_key in deletes:
        record = existing[delete_key]
        if 'id' in record:
            logger.info(f"Deleting {record['type']} record: {record['name']} -> {record['content']}")
            delete_record(domain, record['id'], dry_run=dry_run)
        else:
            logger.warning(f"Cannot delete record without ID: {delete_key}")
    
    # Create new records
    for add_key in adds:
        record = desired[add_key]
        create_record(domain, record, dry_run=dry_run)


@click.command()
@click.option('--dry-run', is_flag=True, help='Show what would be done without making changes')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.option('--domain', help='Process only this domain instead of all configured domains')
def main(dry_run, verbose, domain):
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
    
    # Check credentials
    logger.info("Checking API credentials...")
    res = check_credentials(dry_run=dry_run)
    if not dry_run and res.get("status") == "SUCCESS":
        our_ip = res.get("yourIp", "unknown")
        logger.info(f"API credentials valid. Your IP: {our_ip}")
    elif not dry_run:
        logger.error("Failed to verify API credentials")
        sys.exit(1)
    
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
    
    # Process each domain
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
