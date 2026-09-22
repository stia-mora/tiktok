"""Bounded collection of public TikTok comments through a browser session.

The TikTokApi dependency is deliberately imported only when the collector is
used.  That keeps the Streamlit and daily collection images free of Chromium.
"""
from __future__ import annotations

import asyncio
import http.cookiejar
import logging
import os
from pathlib import Path
import time
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from local_http import proxy_options


MAX_COMMENTS = 50


class CommentCollectorError(RuntimeError):
    """A sanitized error that is safe to save in analysis state."""


def _as_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _cookie_files() -> list[Path | None]:
    configured = os.environ.get("TIKTOK_COMMENT_COOKIE_FILES", "").strip()
    if configured:
        candidates = [Path(value.strip()) for value in configured.split(",") if value.strip()]
    else:
        primary = Path(os.environ.get("TIKTOK_COOKIE_FILE", "/run/secrets/tiktok/tiktok-cookies-1.txt"))
        candidates = [primary]
        if primary.name == "tiktok-cookies-1.txt":
            candidates.append(primary.with_name("tiktok-cookies-2.txt"))
    result: list[Path | None] = []
    for candidate in candidates:
        if candidate.is_file() and candidate not in result:
            result.append(candidate)
    # TikTokApi can attempt to create its own msToken, although an explicit
    # logged-in Cookie is materially more reliable.
    return result or [None]


def _ms_token(cookie_file: Path | None) -> str | None:
    if cookie_file is None:
        return None
    jar = http.cookiejar.MozillaCookieJar(str(cookie_file))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, http.cookiejar.LoadError):
        return None
    for cookie in jar:
        if cookie.name.lower() == "mstoken" and "tiktok.com" in cookie.domain.lower() and cookie.value:
            return cookie.value
    return None


def _playwright_proxy() -> dict[str, str] | None:
    proxy = proxy_options().get("proxies", {}).get("https")
    if not proxy:
        return None
    parsed = urlparse(proxy)
    if not parsed.scheme or not parsed.hostname or not parsed.port:
        raise CommentCollectorError("Invalid TikTok browser proxy configuration")
    settings = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        settings["username"] = unquote(parsed.username)
    if parsed.password:
        settings["password"] = unquote(parsed.password)
    return settings


def normalize_comment(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Keep only VLM-relevant public fields and drop account identity data."""
    text = " ".join(str(raw.get("text") or "").split())[:1000]
    if not text:
        return None
    try:
        likes = max(0, int(raw.get("digg_count") or raw.get("like_count") or 0))
    except (TypeError, ValueError):
        likes = 0
    try:
        reply_count = max(0, int(raw.get("reply_comment_total") or raw.get("replyCommentTotal") or 0))
    except (TypeError, ValueError):
        reply_count = 0
    try:
        created_at = max(0, int(raw.get("create_time") or raw.get("createTime") or 0))
    except (TypeError, ValueError):
        created_at = 0
    return {
        "comment_id": str(raw.get("cid") or raw.get("id") or "")[:80],
        "text": text,
        "likes": likes,
        "reply_count": reply_count,
        "created_at_unix": created_at or None,
    }


async def _collect_one_session(material_id: str, max_comments: int, ms_token: str | None) -> list[dict[str, Any]]:
    try:
        from TikTokApi import TikTokApi
    except ImportError as exc:
        raise CommentCollectorError("TikTok comment collector is not installed") from exc
    # Third-party debug output can include responses from private TikTok routes;
    # the worker persists only our sanitized result below.
    logging.getLogger("TikTokApi").setLevel(logging.CRITICAL)
    settings: dict[str, Any] = {
        "num_sessions": 1,
        "headless": _as_bool(os.environ.get("TIKTOK_COMMENTS_HEADLESS"), True),
        "enable_session_recovery": True,
        "allow_partial_sessions": False,
    }
    if ms_token:
        settings["ms_tokens"] = [ms_token]
    proxy = _playwright_proxy()
    if proxy:
        settings["proxies"] = [proxy]
    try:
        async with TikTokApi() as api:
            await api.create_sessions(**settings)
            video = api.video(id=material_id)
            comments: list[dict[str, Any]] = []
            async for comment in video.comments(count=max_comments):
                normalized = normalize_comment(getattr(comment, "as_dict", {}))
                if normalized:
                    comments.append(normalized)
                if len(comments) >= max_comments:
                    break
            return comments
    except Exception as exc:
        # Library/network messages may contain internal URLs or session data.
        raise CommentCollectorError("TikTok comment collection failed") from exc


def collect_public_comments(
    material_id: str,
    max_comments: int = MAX_COMMENTS,
    *,
    collector: Callable[[str, int, str | None], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch a small top-level public-comment sample, rotating Cookie sessions.

    A failed primary session tries the second mounted Cookie once.  No username,
    avatar, secUid, Cookie or proxy credential is returned or persisted.
    """
    if not str(material_id).isdigit():
        raise CommentCollectorError("TikTok material id is invalid")
    limit = min(MAX_COMMENTS, max(1, int(max_comments)))
    run = collector or (lambda video_id, count, token: asyncio.run(_collect_one_session(video_id, count, token)))
    last_error: Exception | None = None
    for index, cookie_file in enumerate(_cookie_files()):
        try:
            return run(str(material_id), limit, _ms_token(cookie_file))
        except CommentCollectorError as exc:
            last_error = exc
        except Exception as exc:
            last_error = exc
        if index == 0:
            time.sleep(1)
    raise CommentCollectorError("TikTok comment collection failed") from last_error
