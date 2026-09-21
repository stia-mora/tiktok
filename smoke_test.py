"""One page per source; isolate new results from bundled historical data."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--cookies", required=True)
args = parser.parse_args()
os.environ["TIKTOK_COOKIE_FILE"] = str(Path(args.cookies).resolve())
root = Path(__file__).resolve().parent
output = root / "output" / datetime.now().strftime("%Y%m%d_%H%M%S")
output.mkdir(parents=True)
os.environ["TIKTOK_DB_PATH"] = str(root / "output" / "tiktok-local.db")

import create_tiktok_db
import script
from local_http import diagnostics
import pandas as pd

jobs = [
    ("posts", lambda: script.call_tiktok_trending_api("Entertainment", 0)),
    ("creators", lambda: script.call_tiktok_trending_creators("Entertainment", 0)),
    ("hashtags", lambda: script.call_tiktok_trending_hashtags(1, limit=5, country="US")),
]
summary = {}
for name, fetch in jobs:
    rows = fetch()
    summary[name] = {"rows": len(rows or []), "status": "failed" if rows is None else "ok" if rows else "empty"}
    if rows:
        now = datetime.now()
        for row in rows:
            row.update(crawl_date=now.strftime("%Y-%m-%d"), crawl_time=now.strftime("%H:%M:%S"))
        (output / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        pd.DataFrame(rows).to_csv(output / f"{name}.csv", index=False, encoding="utf-8-sig")
        script.save_to_sqlite(os.environ["TIKTOK_DB_PATH"], name, rows, list(rows[0]))
report = {"summary": summary, "requests": diagnostics}
(output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
print(f"Report: {output / 'report.json'}")
raise SystemExit(0 if any(result["rows"] for result in summary.values()) else 2)
