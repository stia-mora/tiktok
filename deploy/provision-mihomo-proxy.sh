#!/bin/sh
set -eu

project_dir=/opt/tiktok
runtime_dir="$project_dir/runtime/mihomo"
provider_file="$runtime_dir/providers/tiktok.yaml"
raw_provider_file="$runtime_dir/providers/tiktok.raw.yaml"

if [ ! -s "$provider_file" ] && [ ! -s "$raw_provider_file" ]; then
    echo "Missing Mihomo subscription provider at $raw_provider_file" >&2
    exit 1
fi

install -d -m 0700 "$runtime_dir/providers"

# Clash Verge exports a full Clash configuration. Mihomo's `type: file`
# proxy-provider accepts only the top-level `proxies` collection, so retain the
# raw private subscription separately and generate the provider file from it.
if [ ! -s "$raw_provider_file" ]; then
    install -m 0600 "$provider_file" "$raw_provider_file"
fi
python3 "$project_dir/deploy/normalize_mihomo_subscription.py" \
    "$raw_provider_file" "$provider_file"
install -m 0600 "$project_dir/deploy/mihomo-config.yaml" "$runtime_dir/config.yaml"
cd "$project_dir"
exec /usr/bin/docker compose --profile proxy up -d proxy
