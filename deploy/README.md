# Docker deployment on Ubuntu

The application runs as a non-root Streamlit container. It listens only on `127.0.0.1:8501`; an existing host Nginx service proxies `/tiktok/` to it. Runtime data remains on the host under `/opt/tiktok/output` and is mounted read-only into the application.

On a fresh Ubuntu server, run as `root`:

```bash
git clone https://github.com/stia-mora/tiktok.git /tmp/tiktok-deploy
cd /tmp/tiktok-deploy
bash deploy/provision-docker.sh
```

After uploading the local `output/` directory to `/opt/tiktok/output/`, start the containers:

```bash
cd /opt/tiktok
docker compose up -d
docker compose ps
```

Install `deploy/nginx-tiktok-dashboard.conf` as an Nginx snippet inside the existing port 80 server block, then run `nginx -t && systemctl reload nginx`. The dashboard is available at `/tiktok/`.

## Daily collector

The collector runs in Docker every day at 09:00 Asia/Shanghai. The scheduler is host cron, but each run uses the pinned `/opt/tiktok` Git checkout and starts a one-off `collector` container. It never runs `git pull`, so code updates remain an explicit deployment action.

Store the Netscape Cookie file outside the repository at `/opt/tiktok-secrets/tiktok-cookies.txt`, owned by root with mode `0600`. The file is mounted read-only only into the collector container. It is not in Git, the image, or the dashboard container.

After the Cookie is installed, run:

```bash
cd /opt/tiktok
bash deploy/provision-collector.sh
docker compose run --rm --no-deps collector
```

The first command installs `/etc/cron.d/tiktok-collector`; logs and resumable run state are in `output/daily/`. The daily job is protected by a cross-platform file lock, so an overlapping run exits without duplicating collection.
