# Docker deployment on Ubuntu

The application runs as a non-root Streamlit container. Caddy is a separate container that forwards HTTP port 80 to the dashboard. Runtime data remains on the host under `/opt/tiktok/output` and is mounted read-only into the application.

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

The cloud firewall/NAT must map TCP 80 to the instance. TikTok Cookie files are neither stored in the image nor transmitted to the server; daily collection is intentionally not enabled there.
