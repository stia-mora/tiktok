"""Collect Creator Studio trending video materials, separately from paid ads."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import http.cookiejar
import json
from pathlib import Path
import re
import time
import uuid
from urllib.parse import quote, urlparse

import requests

from ads_collector import COUNTRIES, ROOT, export_csv, write_json
from ads_store import connect, save_run
from local_http import get, error_summary, proxy_options
from ui_zh import GENRES

VIDEO_DB = ROOT / "output" / "video_history.sqlite3"
ENDPOINT = "https://www.tiktok.com/creator_studio/inspiration/trending/video/v2"
DETAIL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Referer": "https://www.tiktok.com/",
    "Accept-Language": "en-US,en;q=0.9",
}
UNIVERSAL_DATA_RE = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


def normalize_video(video, country, genre):
    author = video.get("Author") or {}
    video_id = str(video["ItemId"])
    if not video_id.isdecimal():
        raise ValueError("Invalid video ID")
    username = author.get("UniqueId") or video.get("UniqueId") or ""
    addresses = video.get("PlayAddress") or []
    if isinstance(addresses, str):
        addresses = [addresses]
    return {
        "source": "trending_video", "material_id": video_id, "query_country": country,
        "delivery_countries": [], "country_verified": False,
        "brand": author.get("NickName") or video.get("NickName") or "", "author_id": str(author.get("UserId") or video.get("UserId") or ""),
        "author_username": username, "ad_text": video.get("ItemName", ""),
        "likes": video.get("LikeCount"), "plays": video.get("PlayCount"), "categories": [genre],
        "ctr_raw": None, "cost_level": None, "duration_seconds": None,
        "video_url": addresses[0] if addresses else "", "cover_url": video.get("CoverUrl", ""),
        "detail_url": f"https://www.tiktok.com/@{quote(username, safe='')}/video/{video_id}" if username else f"https://www.tiktok.com/share/video/{video_id}",
        "video_file": "", "crawled_at": datetime.now(timezone.utc).isoformat(),
    }


def published_at_from_video_page(page_html, video_id):
    """Read the public video-detail payload instead of inferring a time from its ID."""
    match = UNIVERSAL_DATA_RE.search(page_html)
    if not match:
        raise ValueError("Video detail payload missing")
    try:
        item = json.loads(match.group(1))["__DEFAULT_SCOPE__"]["webapp"]["video-detail"]["itemInfo"]["itemStruct"]
        timestamp = int(item["createTime"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Video publication time missing") from exc
    if str(item.get("id")) != str(video_id) or timestamp <= 0:
        raise ValueError("Unexpected video detail payload")
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def fetch_video_published_at(detail_url, video_id, client):
    parsed = urlparse(detail_url)
    if parsed.scheme != "https" or parsed.hostname != "www.tiktok.com":
        raise ValueError("Unexpected video detail host")
    try:
        response = client.get(detail_url, headers=DETAIL_HEADERS, allow_redirects=False, timeout=30, **proxy_options())
    except requests.RequestException as exc:
        raise RuntimeError("Video detail request failed") from exc
    if response.status_code != 200:
        raise RuntimeError(f"Video detail returned HTTP {response.status_code}")
    return published_at_from_video_page(response.text, video_id)


def known_video_published_at(history_db):
    with closing(connect(history_db)) as conn:
        return {row[0]: row[1] for row in conn.execute(
            "SELECT material_id, published_at FROM materials WHERE published_at IS NOT NULL"
        )}


def collect_videos(countries, cookie_file, pages=0, genres=None, output_root=None, history_db=None, detail_limit=20):
    countries = list(dict.fromkeys(countries))
    genres = list(dict.fromkeys(genres or GENRES))
    if not countries or any(code not in COUNTRIES for code in countries) or not genres or any(genre not in GENRES for genre in genres) or not 0 <= pages <= 100 or not 0 <= detail_limit <= 100:
        raise ValueError("Invalid video collection parameters")
    client = requests.Session()
    jar = http.cookiejar.MozillaCookieJar(str(cookie_file))
    jar.load(ignore_discard=True, ignore_expires=False)
    client.cookies.update(jar)
    output_root = Path(output_root or ROOT / "output" / "videos")
    history_db = Path(history_db or VIDEO_DB)
    known_publish_times = known_video_published_at(history_db)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    output = output_root / run_id
    output.mkdir(parents=True)
    report = {"run_id": run_id, "source": "Creator Studio trending videos", "started_at": datetime.now(timezone.utc).isoformat(),
              "genres": genres, "requested_pages": pages, "output_dir": str(output), "history_db": str(history_db), "countries": {}}
    all_rows = []
    try:
        for country in countries:
            rows_by_id = {}
            status = {"status": "running", "pages": 0, "records": 0, "verified_records": 0, "downloaded": 0,
                      "errors": [], "pagination_complete": True, "stop_reason": "end_of_results", "categories": {},
                      "publish_times": {"limit": detail_limit, "attempted": 0, "resolved": 0, "cached": 0, "failed": 0}}
            report["countries"][country] = status
            save_run(report, [], history_db)
            for genre in genres:
                seen = set()
                result = {"pages": 0, "complete": False, "stop_reason": "page_limit" if pages else "safety_limit"}
                status["categories"][genre] = result
                for page in range(pages or 100):
                    try:
                        payload = get(ENDPOINT, params={"aid": "1988", "PageNum": page, "PageSize": 10, "Region": country, "Vertical": genre, "TrendingType": 0},
                                      headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.tiktok.com/creator_studio/"}, timeout=30, client=client).json()
                        videos = payload["TrendingVideos"]
                        if not isinstance(videos, list):
                            raise ValueError("Unexpected video response")
                        category_dir = output / country / genre.replace(" ", "_").replace("&", "and")
                        category_dir.mkdir(parents=True, exist_ok=True)
                        write_json(category_dir / f"page_{page + 1}.json", payload)
                        new_ids = 0
                        for video in videos:
                            row = normalize_video(video, country, genre)
                            video_id = row["material_id"]
                            if video_id not in seen:
                                new_ids += 1
                                seen.add(video_id)
                            if video_id in rows_by_id:
                                if genre not in rows_by_id[video_id]["categories"]:
                                    rows_by_id[video_id]["categories"].append(genre)
                            else:
                                publish_times = status["publish_times"]
                                if video_id in known_publish_times:
                                    row["published_at"] = known_publish_times[video_id]
                                    row["published_at_source"] = "tiktok_video_detail"
                                    publish_times["cached"] += 1
                                elif publish_times["attempted"] < detail_limit:
                                    publish_times["attempted"] += 1
                                    try:
                                        row["published_at"] = fetch_video_published_at(row["detail_url"], video_id, client)
                                        row["published_at_source"] = "tiktok_video_detail"
                                        known_publish_times[video_id] = row["published_at"]
                                        publish_times["resolved"] += 1
                                    except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError):
                                        # A detail page is optional enrichment; list collection still completed.
                                        publish_times["failed"] += 1
                                rows_by_id[video_id] = row
                        result["pages"] += 1
                        status["pages"] += 1
                        status["records"] = len(rows_by_id)
                        save_run(report, list(rows_by_id.values()), history_db)
                        if not videos or not payload.get("HasMore"):
                            result.update(complete=True, stop_reason="end_of_results")
                            break
                        if not new_ids:
                            result["stop_reason"] = "repeated_page"
                            break
                        time.sleep(0.6)
                    except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError) as exc:
                        result["stop_reason"] = "request_failed"
                        status["errors"].append({"stage": "list", "genre": genre, "page": page + 1, "error": error_summary(exc)})
                        break
                if not result["complete"]:
                    status["pagination_complete"] = False
                    status["stop_reason"] = result["stop_reason"]
            rows = list(rows_by_id.values())
            status["status"] = "ok" if status["pagination_complete"] else "partial" if rows else "failed"
            if not rows and status["pagination_complete"]:
                status["status"] = "empty"
            country_dir = output / country
            country_dir.mkdir(exist_ok=True)
            write_json(country_dir / "videos.json", rows)
            export_csv(country_dir / "videos.csv", rows)
            all_rows.extend(rows)
            save_run(report, rows, history_db)
            write_json(output / "report.json", report)
    finally:
        client.close()
    report["total_records"] = len(all_rows)
    report["unique_materials"] = len({row["material_id"] for row in all_rows})
    report["unique_videos_downloaded"] = 0
    write_json(output / "videos.json", all_rows)
    export_csv(output / "videos.csv", all_rows)
    write_json(output / "report.json", report)
    save_run(report, all_rows, history_db)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cookies", required=True)
    parser.add_argument("--countries", nargs="+", choices=list(COUNTRIES), default=["US", "JP", "GB"])
    parser.add_argument("--pages", type=int, default=0)
    parser.add_argument("--genres", nargs="+", choices=list(GENRES), default=list(GENRES))
    parser.add_argument("--detail-limit", type=int, default=20, help="Maximum new video detail pages to enrich per country (0 disables enrichment)")
    args = parser.parse_args()
    result = collect_videos(args.countries, args.cookies, args.pages, args.genres, detail_limit=args.detail_limit)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    raise SystemExit(0 if all(item["status"] in ("ok", "empty") for item in result["countries"].values()) else 2)
