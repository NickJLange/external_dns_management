# External DNS Management

What are the Goal post(s) of repo:

* Manage DNS automatically pushed via APIs / Config instead of GUIs.
  * Current code just works with porkbun.
* Config / Data to be stored in private repo / submodule.
* Generate TLS Certs (Container Only)

### Config.ini format for manage_porkbun.py

```
[general]
porkbun_public_api_key=(OR USE ENV VAR PORKBUN_API_KEY)
porkbun_private_api_key=(OR USE ENV VAR PORKBUN_SECRET_API_KEY)
porkbun_rest_endpoint=https://api-ipv4.porkbun.com/api/json/v3

[domains]
5l-labs.com
myhouse.com
etc 
etc

```

### DNS domain format

```
[5l-labs.com]
#FORMAT: TYPE KEY VALUE TTL [PRIO]
# Lazy use of four spaces to support TXT records below - maybe increase to 20 down the line
ALIAS    5l-labs.com    pixie.porkbun.com    300

```

### Lego Management Example

 1. scripts/lego.sh
 1. Output stored in lego-data
 1. #FIXME - Upload lego-data/* to the vault for pushing out to hosts
