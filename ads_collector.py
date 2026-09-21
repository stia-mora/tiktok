"""Small, sequential, country-specific Creative Center Top Ads collector."""
import argparse
import csv
from contextlib import closing
from datetime import datetime, timezone
import http.cookiejar
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlparse
import uuid

import requests

from local_http import get, proxy_options
from ads_store import DB_PATH, save_run

ROOT = Path(__file__).resolve().parent
COUNTRIES = json.loads((ROOT / "ads_countries.json").read_text(encoding="utf-8"))
SORTS = {"impression": "瑕嗙洊浜烘暟", "ctr": "CTR", "for_you": "鎺ㄨ崘"}
BASE = "https://ads.tiktok.com/creative_radar_api/v1/top_ads/v2/"
HEADERS = {"User-Agent": "Mozilla/5.0", "lang": "en", "Referer": "https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en"}


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def csv_text(value):
    value = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_csv(path, rows):
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({key: csv_text(value) for key, value in row.items()} for row in rows)


def normalize(material, country, crawled_at):
    info = material.get("video_info") or {}
    urls = info.get("video_url") or {}
    video_url = next((urls[key] for key in ("1080p", "720p", "540p", "480p") if urls.get(key)), next(iter(urls.values()), ""))
    ad_id = str(material["id"])
    if not ad_id.isdecimal():
        raise ValueError("Invalid material ID")
    return {
        "material_id": ad_id, "query_country": country,
        "delivery_countries": material.get("country_code") or [],
        "brand": material.get("brand_name", ""), "ad_text": material.get("ad_title", ""),
        "likes": material.get("like"), "ctr_raw": material.get("ctr"), "cost_level": material.get("cost"),
        "industry": material.get("industry_key", ""), "objective": material.get("objective_key", ""),
        "duration_seconds": info.get("duration"), "width": info.get("width"), "height": info.get("height"),
        "video_url": video_url, "cover_url": info.get("cover", ""),
        "landing_page": material.get("landing_page", ""),
        "detail_url": f"https://ads.tiktok.com/business/creativecenter/topads/{ad_id}/pc/en",
        "country_verified": country in (material.get("country_code") or []),
        "detail_status": "not_requested", "video_file": "", "download_status": "not_requested",
        "crawled_at": crawled_at,
    }


def download_video(url, target, max_bytes=100 * 1024 * 1024):
    """Use a fresh unauthenticated request; never send login cookies to a CDN."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".tiktokcdn.com"):
        raise ValueError("Unsupported media host")
    partial = target.with_suffix(".part")
    try:
        with requests.get(url, stream=True, timeout=(10, 45), allow_redirects=False, **proxy_options()) as response:
            if response.status_code != 200:
                raise RuntimeError(f"Media HTTP {response.status_code}")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
            if content_type not in ("video/mp4", "application/octet-stream"):
                raise ValueError("Unexpected media type")
            total = 0
            with partial.open("wb") as stream:
                for block in response.iter_content(65536):
                    total += len(block)
                    if total > max_bytes:
                        raise ValueError("Media exceeds 100 MB")
                    stream.write(block)
        with partial.open("rb") as stream:
            if stream.read(12)[4:8] != b"ftyp":
                raise ValueError("Response is not an MP4")
        partial.replace(target)
        return total
    finally:
        partial.unlink(missing_ok=True)


def collect_ads(countries, cookie_file, pages=1, limit=20, period=30, keyword="", sort="impression", download_per_country=0, details=True, output_root=None, history_db=None):
    countries = list(dict.fromkeys(countries))
    if not countries or any(country not in COUNTRIES for country in countries):
        raise ValueError("Select supported country codes")
    if not 0 <= pages <= 1000 or not 1 <= limit <= 20 or period not in (7, 30, 180) or sort not in SORTS:
        raise ValueError("Invalid pagination, period or sort")
    if not 0 <= download_per_country <= 20:
        raise ValueError("Download count must be between 0 and 20")
    jar = http.cookiejar.MozillaCookieJar(str(cookie_file))
    jar.load(ignore_discard=True, ignore_expires=False)
    client = requests.Session()
    client.cookies.update(jar)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    output = Path(output_root or ROOT / "output" / "ads") / run_id
    output.mkdir(parents=True)
    history_db = Path(history_db or (Path(output_root) / "history.sqlite3" if output_root else DB_PATH))
    report = {"run_id": run_id, "source": "TikTok Creative Center Top Ads", "period_days": period,
              "started_at": datetime.now(timezone.utc).isoformat(), "requested_pages": pages, "page_size": limit,
              "keyword": keyword, "sort": sort, "countries": {}, "output_dir": str(output), "history_db": str(history_db)}
    all_rows, detail_cache, media_cache = [], {}, {}
    consecutive_detail_failures = 0
    try:
        for country in countries:
            country_dir = output / country
            country_dir.mkdir()
            rows, seen = [], set()
            status = {"status": "running", "pages": 0, "records": 0, "verified_records": 0, "downloaded": 0, "errors": [], "pagination_complete": False, "stop_reason": "running"}
            report["countries"][country] = status
            save_run(report, [], history_db)
            for page in range(1, (pages or 1000) + 1):
                params = {"country_code": country, "page": page, "limit": limit, "period": period, "keyword": keyword, "order_by": sort}
                try:
                    payload = get(BASE + "list", params=params, headers=HEADERS, timeout=30, client=client).json()
                    data = payload["data"]
                    materials = data["materials"]
                    if not isinstance(materials, list):
                        raise ValueError("Unexpected materials structure")
                    write_json(country_dir / f"page_{page}.json", payload)
                    status["pages"] += 1
                    status["total_available"] = (data.get("pagination") or {}).get("total_count")
                    before = len(rows)
                    for material in materials:
                        if str(material["id"]) in seen:
                            continue
                        seen.add(str(material["id"]))
                        detail_status = "not_requested"
                        if details and consecutive_detail_failures < 3:
                            try:
                                ad_id = str(material["id"])
                                if ad_id not in detail_cache:
                                    time.sleep(0.35)
                                    detail_cache[ad_id] = get(BASE + "detail", params={"material_id": ad_id}, headers=HEADERS, timeout=30, client=client).json()["data"]
                                    if str(detail_cache[ad_id].get("id")) != ad_id:
                                        del detail_cache[ad_id]
                                        raise ValueError("Detail ID mismatch")
                                    detail_dir = output / "details"
                                    detail_dir.mkdir(exist_ok=True)
                                    write_json(detail_dir / f"{ad_id}.json", detail_cache[ad_id])
                                material = {**material, **detail_cache[ad_id]}
                                detail_status = "ok"
                                consecutive_detail_failures = 0
                            except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError) as exc:
                                consecutive_detail_failures += 1
                                detail_status = "failed"
                                status["errors"].append({"stage": "detail", "material_id": str(material["id"]), "error": type(exc).__name__})
                        elif details:
                            detail_status = "skipped_after_errors"
                            status["details_paused"] = True
                        row = normalize(material, country, datetime.now(timezone.utc).isoformat())
                        row["detail_status"] = detail_status
                        rows.append(row)
                    status["records"] = len(rows)
                    save_run(report, rows, history_db)
                    write_json(country_dir / "ads.json", rows)
                    if not materials or not (data.get("pagination") or {}).get("has_more"):
                        status["pagination_complete"] = True
                        status["stop_reason"] = "end_of_results"
                        status["status"] = "ok"
                        break
                    if len(rows) == before:
                        status["status"] = "partial"
                        status["stop_reason"] = "repeated_page"
                        break
                    time.sleep(0.5)
                except KeyboardInterrupt:
                    status["status"] = "partial"
                    status["stop_reason"] = "interrupted"
                    save_run(report, rows, history_db)
                    write_json(output / "report.json", report)
                    raise
                except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError) as exc:
                    status["status"] = "partial" if rows else "failed"
                    status["stop_reason"] = "request_failed"
                    status["errors"].append({"stage": "list", "page": page, "error": str(exc)[:250]})
                    break
            if status["status"] == "running":
                status["status"] = "partial"
                status["stop_reason"] = "page_limit" if pages else "safety_limit"
            for row in rows[:download_per_country]:
                try:
                    ad_id = row["material_id"]
                    if ad_id not in media_cache:
                        media_dir = output / "videos"
                        media_dir.mkdir(exist_ok=True)
                        target = media_dir / f"{ad_id}.mp4"
                        download_video(row["video_url"], target)
                        media_cache[ad_id] = str(target)
                    row["video_file"] = media_cache[ad_id]
                    row["download_status"] = "ok"
                    status["downloaded"] += 1
                except (requests.RequestException, RuntimeError, ValueError, OSError) as exc:
                    row["download_status"] = "failed"
                    status["errors"].append({"stage": "download", "material_id": row["material_id"], "error": type(exc).__name__})
            status["records"] = len(rows)
            status["verified_records"] = sum(row["country_verified"] for row in rows)
            if status["errors"] and status["status"] == "ok":
                status["status"] = "partial"
            if not rows and status["status"] == "ok":
                status["status"] = "empty"
            write_json(country_dir / "ads.json", rows)
            export_csv(country_dir / "ads.csv", rows)
            all_rows.extend(rows)
            save_run(report, rows, history_db)
            write_json(output / "report.json", report)
    finally:
        client.close()
    write_json(output / "ads.json", all_rows)
    export_csv(output / "ads.csv", all_rows)
    report["total_records"] = len(all_rows)
    report["unique_materials"] = len({row["material_id"] for row in all_rows})
    report["unique_videos_downloaded"] = len(media_cache)
    with closing(sqlite3.connect(output / "ads.sqlite3")) as conn, conn:
        conn.execute("CREATE TABLE ads (country TEXT, material_id TEXT, payload TEXT, PRIMARY KEY(country, material_id))")
        conn.executemany("INSERT INTO ads VALUES (?, ?, ?)", [(row["query_country"], row["material_id"], json.dumps(row, ensure_ascii=False)) for row in all_rows])
    write_json(output / "report.json", report)
    save_run(report, all_rows, history_db)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--countries", nargs="+", default=["US", "JP", "GB"], choices=list(COUNTRIES))
    parser.add_argument("--cookies", required=True)
    parser.add_argument("--pages", type=int, default=0, help="0: continue until upstream ends; safety cap 1000 pages")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--period", type=int, default=30, choices=[7, 30, 180])
    parser.add_argument("--keyword", default="")
    parser.add_argument("--sort", choices=list(SORTS), default="impression")
    parser.add_argument("--download-per-country", type=int, default=0)
    args = parser.parse_args()
    report = collect_ads(args.countries, args.cookies, args.pages, args.limit, args.period, args.keyword, args.sort, args.download_per_country)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if all(item["status"] in ("ok", "empty") for item in report["countries"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
