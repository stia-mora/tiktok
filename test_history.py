from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ads_store import connect, save_run
from video_collector import collect_videos
import daily_collect


class HistoryTests(unittest.TestCase):
    def test_daily_latest_idempotency_and_beijing_date(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "history.db"
            def add(run, at, likes):
                row = {"material_id": "123", "query_country": "US", "crawled_at": at, "likes": likes, "brand": run}
                report = {"run_id": run, "countries": {}}
                save_run(report, [row], db)
                save_run(report, [row], db)
            add("second", "2026-09-19T18:00:00+00:00", 150)
            add("first", "2026-09-19T17:00:00+00:00", 100)
            add("third", "2026-09-20T17:00:00+00:00", 200)
            with closing(connect(db)) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 3)
                self.assertEqual([tuple(row) for row in conn.execute("SELECT observed_date, likes FROM daily_snapshots ORDER BY observed_date")], [("2026-09-20", 150), ("2026-09-21", 200)])
                row = conn.execute("SELECT * FROM materials").fetchone()
                self.assertEqual(row["brand"], "third")
                self.assertEqual(row["first_seen"], "2026-09-19T17:00:00+00:00")

    def test_video_repeated_page_and_cross_category_dedup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cookies = root / "cookies.txt"
            cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            payload = {"TrendingVideos": [{"ItemId": "123", "ItemName": "test", "PlayCount": 100, "Author": {"UniqueId": "alice"}}], "HasMore": True}
            with patch("video_collector.get", return_value=Mock(json=lambda: payload)), patch("video_collector.time.sleep"):
                report = collect_videos(["US"], cookies, genres=["Entertainment", "Nature"], output_root=root / "output", history_db=root / "history.db")
            self.assertEqual(report["countries"]["US"]["stop_reason"], "repeated_page")
            self.assertEqual(report["total_records"], 1)
            with closing(connect(root / "history.db")) as conn:
                row = json.loads(conn.execute("SELECT payload_json FROM observations").fetchone()[0])
                self.assertEqual(row["categories"], ["Entertainment", "Nature"])

    def test_daily_runner_handles_both_sources_and_skips_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "daily_config.json"
            cookies = root / "cookies.txt"
            cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            config.write_text(json.dumps({"countries": ["US"], "sources": ["ads", "videos"], "cookie_file": str(cookies), "period": 30, "video_genres": ["Entertainment"]}), encoding="utf-8")
            status = {"pagination_complete": True, "errors": [], "status": "ok", "pages": 2, "records": 20}
            report = {"run_id": "example", "countries": {"US": status}}
            with patch.object(daily_collect, "ROOT", root), patch.object(daily_collect, "CONFIG", config), patch.object(daily_collect, "import_previous_runs"), patch.object(daily_collect, "collect_ads", return_value=report) as ads, patch.object(daily_collect, "collect_videos", return_value=report) as videos:
                self.assertEqual(daily_collect.main(), 0)
                self.assertEqual(daily_collect.main(), 0)
                ads.assert_called_once()
                videos.assert_called_once()

    def test_daily_runner_rotates_cookies_after_a_failed_country(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_cookie = root / "first.cookies.txt"
            second_cookie = root / "second.cookies.txt"
            for cookie in (first_cookie, second_cookie):
                cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            config = root / "daily_config.json"
            config.write_text(json.dumps({"countries": ["US", "CA"], "sources": ["ads"], "cookie_files": [str(first_cookie), str(second_cookie)], "period": 30, "video_genres": ["Entertainment"]}), encoding="utf-8")
            failed = {"run_id": "first", "countries": {"US": {"pagination_complete": False, "errors": [{"error": "rate_limited"}], "status": "failed", "pages": 0, "records": 0}}}
            succeeded_us = {"run_id": "second", "countries": {"US": {"pagination_complete": True, "errors": [], "status": "ok", "pages": 1, "records": 5}}}
            succeeded_ca = {"run_id": "third", "countries": {"CA": {"pagination_complete": True, "errors": [], "status": "ok", "pages": 1, "records": 5}}}
            with patch.object(daily_collect, "ROOT", root), patch.object(daily_collect, "CONFIG", config), patch.object(daily_collect, "import_previous_runs"), patch.object(daily_collect, "collect_ads", side_effect=[failed, succeeded_us, succeeded_ca]) as ads:
                self.assertEqual(daily_collect.main(), 0)
                self.assertEqual([call.args[1] for call in ads.call_args_list], [str(first_cookie), str(second_cookie), str(second_cookie)])


if __name__ == "__main__":
    unittest.main()
