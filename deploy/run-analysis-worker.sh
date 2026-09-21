#!/bin/sh
set -eu

cd /opt/tiktok
mkdir -p /opt/tiktok/output/analysis
exec flock -n /opt/tiktok/output/analysis/worker.lock /usr/bin/docker compose --profile analyzer run --rm --no-deps analyzer
