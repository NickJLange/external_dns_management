#!/bin/sh
set -a
. ../etc/lego.env
set +a

echo "Renewing Certs"
for host in $LEGO_HOSTS; do
  podman run -v ../lego-data/:/.lego/ --env-file ../etc/lego.env -it goacme/lego \
    --email "$LEGO_EMAIL" --dns porkbun \
    --domains "*.$host.$LEGO_BASE_DOMAIN" --domains "$host.$LEGO_BASE_DOMAIN" run
done
