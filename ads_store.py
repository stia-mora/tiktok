"""Append-only observations and deduplicated material index for local analysis."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "output" / "ads_history.sqlite3"


def connect(db_path=DB_PATH, *, readonly=False):
    path = Path(db_path)
    if readonly:
        # Dashboard queries run against a read-only mounted archive. SQLite must not
        # initialize WAL or schema objects in that mode.
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS collection_runs (
        run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, report_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS materials (
        material_id TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
        brand TEXT, ad_text TEXT, video_file TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS observations (
        run_id TEXT NOT NULL REFERENCES collection_runs(run_id),
        country TEXT NOT NULL, material_id TEXT NOT NULL REFERENCES materials(material_id),
        observed_at TEXT NOT NULL, observed_date TEXT NOT NULL,
        likes INTEGER, ctr_raw REAL, cost_level INTEGER, country_verified INTEGER,
        payload_json TEXT NOT NULL, PRIMARY KEY(run_id, country, material_id)
    );
    CREATE INDEX IF NOT EXISTS observations_date_country ON observations(observed_date, country);
    CREATE INDEX IF NOT EXISTS observations_material_time ON observations(material_id, observed_at);
    CREATE VIEW IF NOT EXISTS daily_snapshots AS
    SELECT * FROM (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY observed_date, country, material_id ORDER BY observed_at DESC, run_id DESC
        ) AS daily_rank FROM observations
    ) WHERE daily_rank=1;
    """)
    # SQLite's CREATE TABLE IF NOT EXISTS cannot extend archives created by an
    # older collector, so add this optional video-only metadata separately.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(materials)")}
    if "published_at" not in columns:
        conn.execute("ALTER TABLE materials ADD COLUMN published_at TEXT")
    if "published_at_source" not in columns:
        conn.execute("ALTER TABLE materials ADD COLUMN published_at_source TEXT")
    return conn


def save_run(report, rows, db_path=DB_PATH):
    timestamp = report.get("started_at") or (min((row["crawled_at"] for row in rows), default=None))
    if not timestamp:
        # A legacy failed run still gets its original date, not the migration date.
        timestamp = datetime.strptime(report["run_id"][:15], "%Y%m%d_%H%M%S").replace(tzinfo=ZoneInfo("Asia/Shanghai")).isoformat()
    with closing(connect(db_path)) as conn, conn:
        conn.execute("INSERT INTO collection_runs VALUES (?, ?, ?) ON CONFLICT(run_id) DO UPDATE SET report_json=excluded.report_json",
                     (report["run_id"], timestamp, json.dumps(report, ensure_ascii=False)))
        for row in rows:
            instant = datetime.fromisoformat(row["crawled_at"])
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            observed_at = instant.astimezone(timezone.utc).isoformat()
            observed_date = instant.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
            conn.execute("""INSERT INTO materials
                (material_id, first_seen, last_seen, brand, ad_text, video_file, published_at, published_at_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(material_id) DO UPDATE SET
                first_seen=MIN(materials.first_seen, excluded.first_seen),
                last_seen=MAX(materials.last_seen, excluded.last_seen),
                brand=CASE WHEN excluded.last_seen>=materials.last_seen THEN excluded.brand ELSE materials.brand END,
                ad_text=CASE WHEN excluded.last_seen>=materials.last_seen THEN excluded.ad_text ELSE materials.ad_text END,
                video_file=CASE WHEN excluded.video_file!='' THEN excluded.video_file ELSE materials.video_file END,
                published_at=COALESCE(materials.published_at, excluded.published_at),
                published_at_source=COALESCE(materials.published_at_source, excluded.published_at_source)
                """, (row["material_id"], observed_at, observed_at, row.get("brand", ""), row.get("ad_text", ""), row.get("video_file", ""),
                      row.get("published_at"), row.get("published_at_source")))
            conn.execute("""INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, country, material_id) DO UPDATE SET payload_json=excluded.payload_json""",
                         (report["run_id"], row["query_country"], row["material_id"], observed_at, observed_date,
                          row.get("likes"), row.get("ctr_raw"), row.get("cost_level"), int(row.get("country_verified", False)), json.dumps(row, ensure_ascii=False)))


def import_previous_runs(root=None, db_path=DB_PATH):
    root = Path(root or ROOT / "output" / "ads")
    imported = 0
    with closing(connect(db_path)) as conn:
        known = {row[0] for row in conn.execute("SELECT run_id FROM collection_runs")}
    for file in sorted(root.glob("*/report.json")):
        report = json.loads(file.read_text(encoding="utf-8"))
        data_file = file.parent / "ads.json"
        if report["run_id"] in known or not data_file.exists():
            continue
        save_run(report, json.loads(data_file.read_text(encoding="utf-8")), db_path)
        imported += 1
    return imported


if __name__ == "__main__":
    print(f"Imported runs: {import_previous_runs()}; database: {DB_PATH}")
