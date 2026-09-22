#!/bin/sh
set -eu

project_dir=/opt/tiktok
secret_dir=/opt/tiktok-secrets

mkdir -p "$project_dir/output/analysis"

for cookie in "$secret_dir/tiktok-cookies-1.txt" "$secret_dir/tiktok-cookies-2.txt"; do
    if [ ! -f "$cookie" ]; then
        echo "Missing collector Cookie at $cookie" >&2
        exit 1
    fi
done

for secret in "$secret_dir/jev-api-key.txt" "$secret_dir/vlm-api-key.txt" "$secret_dir/siliconflow-asr-api-key.txt"; do
    if [ ! -f "$secret" ]; then
        echo "Missing analysis secret at $secret" >&2
        exit 1
    fi
    chmod 0600 "$secret"
done

install -m 0755 "$project_dir/deploy/run-daily-collector.sh" /usr/local/bin/tiktok-daily-collector
install -m 0755 "$project_dir/deploy/run-analysis-worker.sh" /usr/local/bin/tiktok-analysis-worker
install -m 0644 "$project_dir/deploy/tiktok-collector.cron" /etc/cron.d/tiktok-collector
systemctl restart cron
