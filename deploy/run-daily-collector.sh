#!/bin/sh
set -eu

cd /opt/tiktok
exec /usr/bin/docker compose --profile collector run --rm --no-deps collector
