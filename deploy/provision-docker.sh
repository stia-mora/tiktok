#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/tiktok
REPOSITORY_URL=https://github.com/stia-mora/tiktok.git

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this script as root." >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io docker-compose-v2 git
systemctl enable --now docker

if [ -e "$APP_DIR/.git" ]; then
    echo "$APP_DIR already contains a Git repository; update it separately before provisioning." >&2
    exit 1
fi

if [ -d "$APP_DIR" ] && [ "$(find "$APP_DIR" -mindepth 1 -maxdepth 1 | wc -l)" -ne 0 ]; then
    echo "$APP_DIR is not empty; refusing to overwrite it." >&2
    exit 1
fi

git clone --depth 1 "$REPOSITORY_URL" "$APP_DIR"
mkdir -p "$APP_DIR/output"
docker compose --project-directory "$APP_DIR" build dashboard

echo "Provisioning complete. Upload output/ before running docker compose up -d."
