#!/usr/bin/env python3
import json
import csv 
import requests
import re
import sys
import os
from pprint import pprint, pformat
from collections import defaultdict

import logging
import configparser

porkbun_public_api_key = "porkbun_public_api_key"
porkbun_private_api_key = "porkbun_private_api_key"
porkbun_rest_endpoint = "porkbun_rest_endpoint"

basic_rest_data = dict()
base_endpoint = None
###################### WARNING
## Will blow away entries that are not found in config - this is the law
## Will leave carve out for anything found north of a NS record (indicating served by another provider)
# FIXME: Move to GUNICORN Logging object
logger = logging.getLogger()
logger.setLevel(logging.INFO)
streamHandler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter(
    "[%(asctime)s] - [%(name)s] - [%(levelname)s] - %(message)s"
)
streamHandler.setFormatter(formatter)
logger.addHandler(streamHandler)
# annoying

def gen_key(ds):
    key = "_".join([ds["name"],ds["content"],ds["type"],ds["ttl"]]).lower()
    return key

def init_config(config_location="../etc/config.ini"):
    app_config = dict()
    config = configparser.ConfigParser(allow_no_value=True)
    try:
        config.read(config_location)
        # Load DNS blocks into
        app_config["domains"] = list()
        for domain in config["domains"]:
            app_config["domains"].append(domain)
        app_config[porkbun_public_api_key] = config.get(
            "general",
            porkbun_public_api_key,
            fallback=os.environ.get("PORKBUN_PUBLIC_API_KEY",""),
        )
        app_config[porkbun_private_api_key] = config.get(
            "general",
            porkbun_private_api_key,
            fallback=os.environ.get("PORKBUN_PRIVATE_API_KEY",""),
        )
        app_config["porkbun_rest_endpoint"] = config.get(
            "general",
            "porkbun_rest_endpoint",
            fallback=os.environ.get("PORKBUN_REST_ENDPOINT"),
        )

        logger.info("Succesfully read configs from: %s " % config_location)
    except configparser.Error as a:
        logger.error("Couldn't read configs from: %s %s" % (config_location, a))
    logger.debug(pformat(app_config))
    return app_config


def load_domain(domain,config_location=None):
    if not config_location:
        config_location = ("%s%s")%("../etc/",domain)
    desired_state = dict()
    config = configparser.ConfigParser(allow_no_value=True,delimiters=["|"])
    try:
        config.read(config_location)
        for raw in config[domain]:
            parts = re.split(r'\s{4}',raw)
#            pprint(parts)
            ds = {
                "name":parts[1],
                "type":parts[0],
                "prio":"None",
                "ttl":parts[3],
                "content":parts[2]
            }
            if 4 in parts: ds["prio"] = parts[4]
            key = gen_key(ds)
            desired_state[key] = ds
        logger.info("Succesfully read domain config of %s config from: %s " % (domain, config_location))
    except configparser.Error as a:
        logger.error("Couldn't read configs from: %s %s" % (config_location, a))
    logger.debug(pformat(desired_state))
    return desired_state


def runner(method,url_args=None,data_args=None):
    global basic_rest_data
    global base_endpoint
    full_url = [base_endpoint, method]
    if url_args: full_url.extend(url_args)
    url  = "/".join(full_url)
    logger.info("Calling URI %s"%url)
    req_data = dict(basic_rest_data)
    if data_args: req_data = basic_rest_data | data_args
    payload = json.dumps(req_data)
    #print(payload)
    logger.debug("Payload %s"%pformat(req_data))
    req = requests.post(
            url,
            data=payload,
        )
    response = json.loads(req.text)
    return response


def deleteRecord():
    for i in getRecords(rootDomain)["records"]:
        if i["name"] == fqdn and (
            i["type"] == "A" or i["type"] == "ALIAS" or i["type"] == "CNAME"
        ):
            print("Deleting existing " + i["type"] + " Record")
            deleteRecord = json.loads(
                requests.post(
                    apiConfig["endpoint"] + "/dns/delete/" + rootDomain + "/" + i["id"],
                    data=json.dumps(apiConfig),
                ).text
            )


def create_record(domain,record):
    method = "dns/create"
    data = {
        "type": record["type"].upper(),
        "ttl":record["ttl"],
        "content":record["content"],
        "name":re.split(r'.?%s'%domain, record["name"])[0]
    }
    if 'prio' in record and record["prio"] != "None" and record["prio"] != "0":
        data['prio'] = record['prio'] 
    pprint(data)
    response = runner(method, url_args=[domain],data_args=data)
    pprint(response)
    return response





def check_credentials():
    return runner("ping")


def get_records(domain): 
    # grab all the records so we know which ones to delete to make room for our record. Also checks to make sure we've got the right domain
    method = "dns/retrieve"
    response = runner(method, url_args=[domain])
    if response["status"] == "ERROR":
        logger.error(
            "Error getting domain. Check to make sure you specified the correct domain, and that API access has been switched on for this domain."
        )
        sys.exit()
#    pprint (response)
    existing = dict()
    for entry in response["records"]:
        if not entry["prio"]: entry["prio"] = "None"
        key = gen_key(entry)
        existing[key] = entry
    return existing

app_config = init_config()
basic_rest_data = {
      "secretapikey": app_config[porkbun_private_api_key],
      "apikey" : app_config[porkbun_public_api_key]    
    }
base_endpoint = app_config[porkbun_rest_endpoint]

res = check_credentials()
ourIp = res["yourIp"]
logger.info("%s is our IP"%ourIp)
for domain in app_config["domains"]:
    desired = load_domain(domain)
    existing = get_records(domain)
    deletes = set(existing.keys()) - set(desired.keys())
    adds = set(desired.keys()) - set(existing.keys())
    #pprint(existing)
    #pprint(desired)
    pprint(adds)
    for add in adds:
        create_record(domain,desired[add])
    pprint(deletes)

