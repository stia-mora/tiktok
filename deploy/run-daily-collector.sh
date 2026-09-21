#!/bin/sh
set -eu

cd /opt/tiktok
exec /usr/bin/docker compose run --rm --no-deps collector
