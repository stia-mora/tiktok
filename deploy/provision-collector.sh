#!/bin/sh
set -eu

project_dir=/opt/tiktok
secret_file=/opt/tiktok-secrets/tiktok-cookies.txt

if [ ! -f "$secret_file" ]; then
    echo "Missing collector Cookie at $secret_file" >&2
    exit 1
fi

install -m 0755 "$project_dir/deploy/run-daily-collector.sh" /usr/local/bin/tiktok-daily-collector
install -m 0644 "$project_dir/deploy/tiktok-collector.cron" /etc/cron.d/tiktok-collector
systemctl restart cron
