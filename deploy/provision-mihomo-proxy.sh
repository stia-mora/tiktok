#!/bin/sh
set -eu

project_dir=/opt/tiktok
runtime_dir="$project_dir/runtime/mihomo"
provider_file="$runtime_dir/providers/tiktok.yaml"

if [ ! -s "$provider_file" ]; then
    echo "Missing Mihomo subscription provider at $provider_file" >&2
    exit 1
fi

install -d -m 0700 "$runtime_dir/providers"
install -m 0600 "$project_dir/deploy/mihomo-config.yaml" "$runtime_dir/config.yaml"
cd "$project_dir"
exec /usr/bin/docker compose --profile proxy up -d proxy
