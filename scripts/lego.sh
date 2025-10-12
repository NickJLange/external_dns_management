#!/bin/sh

# Discover the base directory
BASE_DIR=$(dirname "$0")/..
CONFIG_FILE="$BASE_DIR/etc/config.ini"

# Check if config file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Configuration file not found: $CONFIG_FILE"
    exit 1
fi

echo "Renewing Certs"

# Read domains from config.ini and process them
# Use awk to read the domains from the [domains] section
awk '/^\[domains\]/{f=1;next} /\[/{f=0} f' "$CONFIG_FILE" | while read -r domain || [ -n "$domain" ]; do
    # Skip empty lines
    if [ -z "$domain" ]; then
        continue
    fi

    echo "Processing domain: $domain"

    # Construct and run the podman command for each domain
    podman run -v "$BASE_DIR/lego-data:/lego-data" \
               --env-file "$BASE_DIR/etc/lego.env" -it goacme/lego \
               --email dns@wafuu.design \
               --dns porkbun \
               --domains "*.$domain" \
               --domains "$domain" run
done