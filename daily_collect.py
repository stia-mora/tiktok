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


def main():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if not config.get("sources") or any(source not in ("ads", "videos") for source in config["sources"]):
        raise ValueError("Invalid daily collection sources")
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
            jobs = [(source, code) for source in config["sources"] for code in config["countries"]]
            for source, code in jobs:
                job_key = source + ":" + code
                if code not in COUNTRIES:
                    raise ValueError("Unsupported country in daily configuration")
                if state["countries"].get(job_key, {}).get("complete"):
                    continue
                try:
                    report = (collect_ads([code], config["cookie_file"], pages=0, limit=20, period=config["period"], download_per_country=0, details=False)
                              if source == "ads" else collect_videos([code], config["cookie_file"], pages=0, genres=config["video_genres"]))
                    status = report["countries"][code]
                    state["countries"][job_key] = {"complete": status["pagination_complete"] and not status["errors"], "run_id": report["run_id"], **status}
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
