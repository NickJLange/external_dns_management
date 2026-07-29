#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

set -a
. "$REPO_ROOT/etc/lego.env"
set +a

: "${LEGO_EMAIL:?LEGO_EMAIL not set in etc/lego.env}"
: "${LEGO_BASE_DOMAIN:?LEGO_BASE_DOMAIN not set in etc/lego.env}"
: "${LEGO_HOSTS:?LEGO_HOSTS not set in etc/lego.env}"

echo "Renewing Certs"
status=0
for host in $LEGO_HOSTS; do
  podman run -v "$REPO_ROOT/lego-data/:/.lego/" --env-file "$REPO_ROOT/etc/lego.env" goacme/lego \
    --email "$LEGO_EMAIL" --dns porkbun \
    --domains "*.$host.$LEGO_BASE_DOMAIN" --domains "$host.$LEGO_BASE_DOMAIN" run || status=1
done
exit "$status"
