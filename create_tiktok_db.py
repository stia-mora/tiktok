import sqlite3
import os
from pathlib import Path

# Database path
db_path = os.environ.get("TIKTOK_DB_PATH", str(Path(__file__).resolve().parent / "output" / "tiktok-local.db"))

# Ensure folder exists
os.makedirs(os.path.dirname(db_path), exist_ok=True)

# Connect to SQLite (will create file if not exists)
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# === Create tables ===
# Creators table: Primary key = (user_id, video_item_id) → ensure each user's video is unique
# If the same user_id + video_item_id is inserted again, SQLite will ignore (no overwrite)
cursor.execute("""
CREATE TABLE IF NOT EXISTS creators (
    nickname TEXT,
    uniqueId TEXT,
    user_id TEXT,
    follower_count INTEGER,
    bio TEXT,
    creator_rank INTEGER,
    video_type TEXT,
    video_item_id TEXT,
    video_name TEXT,
    video_url TEXT,
    profile_url TEXT,
    video_play_count INTEGER,
    video_like_count INTEGER,
    video_rank INTEGER,
    crawl_date TEXT,
    crawl_time TEXT,
    PRIMARY KEY (user_id, video_item_id)
)
""")

# Hashtags table: Primary key = (hashtag_id, crawl_date, crawl_time)
# Allow multiple historical versions of the same hashtag for trend analysis
cursor.execute("""
CREATE TABLE IF NOT EXISTS hashtags (
    hashtag_id TEXT,
    hashtag_name TEXT,
    country TEXT,
    rank INTEGER,
    video_views INTEGER,
    publish_count INTEGER,
    industry_value REAL,
    crawl_date TEXT,
    crawl_time TEXT,
    PRIMARY KEY (hashtag_id, crawl_date, crawl_time)
)
""")

# Posts table: Primary key = (item_id, crawl_date, crawl_time)
# Allow multiple historical versions of the same post for tracking changes over time
cursor.execute("""
CREATE TABLE IF NOT EXISTS posts (
    url TEXT,
    nickname TEXT,
    user_id TEXT,
    item_id TEXT,
    item_name TEXT,
    genre TEXT,
    like_count INTEGER,
    play_count INTEGER,
    crawl_date TEXT,
    crawl_time TEXT,
    PRIMARY KEY (item_id, crawl_date, crawl_time)
)
""")

conn.commit()
conn.close()
print("Database and tables created successfully.")
