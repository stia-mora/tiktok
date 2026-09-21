"""Run the saved daily collection plan, resuming failed countries on retry."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from ads_collector import COUNTRIES, ROOT, collect_ads, write_json
from ads_store import import_previous_runs
from video_collector import collect_videos

CONFIG = ROOT / "daily_config.json"


def acquire_lock(lock):
    lock.seek(0)
    if os.name == "nt":
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def release_lock(lock):
    lock.seek(0)
    if os.name == "nt":
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def cookie_files(config):
    files = config.get("cookie_files") or [config.get("cookie_file")]
    files = [str(file) for file in files if file]
    if not files:
        raise ValueError("Daily collection requires at least one Cookie file")
    if any(not Path(file).is_file() for file in files):
        raise ValueError("A configured Cookie file is missing")
    return files


def collect_source(source, country, config, cookies):
    """Run one country with the active Cookie first, then fail over once per Cookie."""
    start = config["active_cookie_indexes"].get(source, 0) % len(cookies)
    attempts = []
    final_status = None
    final_run_id = None
    for offset in range(len(cookies)):
        index = (start + offset) % len(cookies)
        report = (collect_ads([country], cookies[index], pages=0, limit=20, period=config["period"], download_per_country=0, details=False)
                  if source == "ads" else collect_videos([country], cookies[index], pages=0, genres=config["video_genres"], detail_limit=config.get("video_detail_limit", 20)))
        status = report["countries"][country]
        final_run_id = report["run_id"]
        complete = status["pagination_complete"] and not status["errors"]
        attempts.append({"cookie_slot": index + 1, "status": status["status"], "complete": complete,
                         "errors": sorted({error.get("error", "unknown") for error in status["errors"]})})
        final_status = status
        if complete:
            config["active_cookie_indexes"][source] = index
            break
        config["active_cookie_indexes"][source] = (index + 1) % len(cookies)
    return {**final_status, "run_id": final_run_id, "cookie_slot": attempts[-1]["cookie_slot"],
            "cookie_attempts": attempts}


def main():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if not config.get("sources") or any(source not in ("ads", "videos") for source in config["sources"]):
        raise ValueError("Invalid daily collection sources")
    cookies = cookie_files(config)
    directory = ROOT / "output" / "daily"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "daily.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        try:
            acquire_lock(lock)
        except OSError:
            print("Daily collection already running")
            return 3
        try:
            import_previous_runs()
            today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
            plan_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:10]
            state_path = directory / f"{today}_{plan_hash}.json"
            state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"date": today, "countries": {}}
            state.setdefault("active_cookie_indexes", {})
            config["active_cookie_indexes"] = state["active_cookie_indexes"]
            jobs = [(source, code) for source in config["sources"] for code in config["countries"]]
            for source, code in jobs:
                job_key = source + ":" + code
                if code not in COUNTRIES:
                    raise ValueError("Unsupported country in daily configuration")
                if state["countries"].get(job_key, {}).get("complete"):
                    continue
                try:
                    status = collect_source(source, code, config, cookies)
                    state["countries"][job_key] = {"complete": status["pagination_complete"] and not status["errors"], **status}
                except Exception as exc:
                    state["countries"][job_key] = {"complete": False, "status": "failed", "error": type(exc).__name__}
                temporary = state_path.with_suffix(".tmp")
                write_json(temporary, state)
                temporary.replace(state_path)
                print(json.dumps({"source": source, "country": code, **state["countries"][job_key]}, ensure_ascii=True), flush=True)
            return 0 if all(state["countries"].get(source + ":" + code, {}).get("complete") for source, code in jobs) else 2
        finally:
            release_lock(lock)


if __name__ == "__main__":
    raise SystemExit(main())
