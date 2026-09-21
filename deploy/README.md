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

Install `deploy/nginx-tiktok-dashboard.conf` as an Nginx snippet inside the existing port 80 server block, then run `nginx -t && systemctl reload nginx`. The dashboard is available at `/tiktok/`. TikTok Cookie files are neither stored in the image nor transmitted to the server; daily collection is intentionally not enabled there.
