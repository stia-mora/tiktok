"""Local cookie loading and response diagnostics. Never logs credentials."""
import http.cookiejar
import hashlib
import os
import json
from pathlib import Path
import time
import uuid
from urllib.parse import urlparse

import requests

PROXY_CONFIG = Path(__file__).resolve().parent / "proxy.local.json"


def proxy_options():
    """Project-only proxy; an unavailable configured proxy never falls back to direct."""
    config = json.loads(PROXY_CONFIG.read_text(encoding="utf-8")) if PROXY_CONFIG.exists() else {}
    proxy = os.environ.get("TIKTOK_PROXY_URL", config.get("proxy_url", ""))
    if not proxy:
        return {}
    parsed = urlparse(proxy)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or not parsed.port:
        raise ValueError("Invalid project HTTP proxy configuration")
    return {"proxies": {"http": proxy, "https": proxy}}


def error_summary(exc):
    # Our RuntimeError messages are sanitized; requests errors can contain URLs/secrets.
    return str(exc)[:250] if isinstance(exc, RuntimeError) else type(exc).__name__


diagnostics = []
session = requests.Session()
anonymous_id = str(uuid.uuid4())
cookie_path = os.environ.get("TIKTOK_COOKIE_FILE")
if cookie_path:
    jar = http.cookiejar.MozillaCookieJar(cookie_path)
    jar.load(ignore_discard=True, ignore_expires=False)
    session.cookies.update(jar)


def get(url, **kwargs):
    client = kwargs.pop("client", session)
    host = urlparse(url).hostname
    if host not in {"ads.tiktok.com", "www.tiktok.com"}:
        raise ValueError("Unexpected request host")
    headers = dict(kwargs.pop("headers", {}))
    # Do not use the repository author's embedded credentials or signatures.
    for key in list(headers):
        if key.lower() in {"cookie", "x-csrftoken", "web-id", "anonymous-user-id", "timestamp", "user-sign"}:
            headers.pop(key)
    if host == "ads.tiktok.com":
        # Same per-request signature as Creative Center's public web client
        # (module 72753). This is separate from account authentication cookies.
        timestamp = str(int(time.time()))
        digest = hashlib.md5(f"A7B&9z#1G6$2K@8M!3-{anonymous_id}-{timestamp}".encode()).hexdigest()
        signature = "".join(format(int(a, 16) ^ int(b, 16), "x") for a, b in zip(digest[:16], digest[16:]))
        headers.update({"anonymous-user-id": anonymous_id, "timestamp": timestamp, "user-sign": signature})
        for cookie in client.cookies:
            if cookie.name == "csrftoken" and (host == cookie.domain.lstrip(".") or host.endswith("." + cookie.domain.lstrip("."))):
                headers["x-csrftoken"] = cookie.value
    record = {"endpoint": url, "params": kwargs.get("params", {})}
    diagnostics.append(record)
    try:
        kwargs.update(proxy_options())
        response = client.get(url, headers=headers, allow_redirects=False, **kwargs)
    except requests.RequestException as exc:
        record["error"] = type(exc).__name__
        raise RuntimeError(record["error"]) from None
    record.update(http_status=response.status_code, bytes=len(response.content), content_type=response.headers.get("Content-Type", ""))
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError:
        record["error"] = "Non-JSON response"
        raise RuntimeError(record["error"]) from None
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected JSON response type")
    record["keys"] = list(data)
    for key in ("code", "msg", "status_code", "status_msg", "message", "statusCode"):
        if key in data:
            record[key] = data[key]
    for key in ("code", "status_code", "statusCode"):
        if data.get(key) not in (None, 0, "0"):
            raise RuntimeError(f"Upstream application error: {data[key]}")
    if not any(key in data for key in ("TrendingVideos", "TrendingCreators", "data")):
        raise RuntimeError("Expected data field missing")
    return response
