# External DNS Management

What is the Goal post: Regardless of Authority / Provider, have the data automatically pushed via APIs / Config instead of GUIs. Current code just works with porkbun.

Config / Data to be stored in private repo / submodule.

### Config.ini format

```
[general]
porkbun_public_api_key=(OR USE ENV VAR)
porkbun_private_api_key=(OR USE ENV VAR)
porkbun_rest_endpoint=https://api-ipv4.porkbun.com/api/json/v3

[domains]
5l-labs.com



```

### domain format

```
[5l-labs.com]
#FORMAT: TYPE KEY VALUE TTL [PRIO]
# Lazy use of four spaces to support TXT records below - maybe increase to 20 down the line
ALIAS    5l-labs.com    pixie.porkbun.com    300

```
