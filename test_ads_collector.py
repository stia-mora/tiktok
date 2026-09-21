import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ads_collector import collect_ads, download_video, export_csv


class AdsCollectorTests(unittest.TestCase):
    def test_country_isolation_pagination_dedup_and_partial_failure(self):
        requests_seen = []

        def upstream(url, **kwargs):
            params = kwargs["params"]
            requests_seen.append(params)
            if params["country_code"] == "JP":
                raise RuntimeError("Upstream application error: 40101")
            page = params["page"]
            ids = ["100", "101"] if page == 1 else ["101", "102"]
            return Mock(json=lambda: {"data": {"materials": [{"id": ad_id} for ad_id in ids], "pagination": {"has_more": page == 1}}})

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cookies = root / "cookies.txt"
            cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            with patch("ads_collector.get", side_effect=upstream), patch("ads_collector.time.sleep"):
                report = collect_ads(["US", "JP"], cookies, pages=3, details=False, output_root=root / "results")
            self.assertEqual([(p["country_code"], p["page"]) for p in requests_seen], [("US", 1), ("US", 2), ("JP", 1)])
            self.assertEqual(report["countries"]["US"]["records"], 3)
            self.assertEqual(report["countries"]["JP"]["status"], "failed")
            rows = json.loads((Path(report["output_dir"]) / "ads.json").read_text(encoding="utf-8"))
            self.assertTrue(all(row["query_country"] == "US" for row in rows))
            self.assertFalse(any(row["country_verified"] for row in rows))

    def test_download_rejects_untrusted_host_before_network(self):
        with patch("ads_collector.requests.get") as network:
            with self.assertRaises(ValueError):
                download_video("https://tiktokcdn.com.evil.example/video.mp4", Path("unused.mp4"))
            network.assert_not_called()

    def test_csv_untrusted_text_does_not_become_formula(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "data.csv"
            export_csv(path, [{"ad_text": "=1+1", "likes": 123}])
            self.assertIn("'=1+1", path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
