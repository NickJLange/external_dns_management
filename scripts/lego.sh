#!/bin/sh
echo "Renewing Certs"
podman run -v ../lego-data/:/.lego/ --env-file ../etc/lego.env -it goacme/lego --email dns@wafuu.design --dns porkbun --domains '*.newyork.nicklange.family' --domains newyork.nicklange.family run
podman run -v ../lego-data/:/.lego/ --env-file ../etc/lego.env -it goacme/lego --email dns@wafuu.design --dns porkbun --domains '*.wisconsin.nicklange.family' --domains wisconsin.nicklange.family run
podman run -v ../lego-data/:/.lego/ --env-file ../etc/lego.env -it goacme/lego --email dns@wafuu.design --dns porkbun --domains '*.miyagi.nicklange.family' --domains miyagi.nicklange.family run
