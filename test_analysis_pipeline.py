import json
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ads_store import connect, save_run
from analysis_pipeline import (
    ANALYSIS_VERSION,
    AnalysisError,
    ConfigurationError,
    RULE_VERSION,
    _detail_play_url,
    VlmSchemaError,
    _extract_json,
    age_bucket,
    backfill_accepted_jobs,
    call_siliconflow_asr,
    call_vlm,
    claim_job,
    enrich_publication_times,
    enqueue,
    ensure_schema,
    jev_input,
    model_session,
    process_job,
    parse_jev_response,
    score_candidates,
    should_enqueue,
    valid_media_url,
)
from comment_collector import normalize_comment


class AnalysisPipelineTests(unittest.TestCase):
    def test_model_session_uses_only_an_explicit_credential_free_proxy(self):
        with patch.dict("analysis_pipeline.os.environ", {"MODEL_PROXY_URL": "http://model-proxy:7890"}):
            session = model_session()
        self.assertFalse(session.trust_env)
        self.assertEqual("http://model-proxy:7890", session.proxies["https"])

        with patch.dict("analysis_pipeline.os.environ", {"MODEL_PROXY_URL": "http://user:pass@model-proxy:7890"}):
            with self.assertRaises(ConfigurationError):
                model_session()

    def add_rows(self, db: Path, count=30, observations=1):
        observed = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
        rows = []
        for index in range(count):
            published = observed - timedelta(hours=48)
            rows.append({
                "material_id": str(9000 + index), "query_country": "US", "brand": "Creator",
                "ad_text": f"Caption {index}", "video_file": "", "published_at": published.isoformat(),
                "published_at_source": "tiktok_video_detail", "crawled_at": observed.isoformat(),
                "likes": 10 + index, "plays": 100 + index * 100, "categories": ["Lifestyle"],
                "video_url": "https://v16.tiktokcdn.com/example.mp4", "detail_url": f"https://www.tiktok.com/@creator/video/{9000 + index}",
            })
        save_run({"run_id": "20260921_120000_a", "started_at": observed.isoformat()}, rows, db)
        if observations > 1:
            second = []
            for row in rows:
                copy = dict(row)
                copy["crawled_at"] = (observed + timedelta(hours=24)).isoformat()
                copy["plays"] += 1000
                second.append(copy)
            save_run({"run_id": "20260922_120000_b", "started_at": (observed + timedelta(hours=24)).isoformat()}, second, db)

    def test_age_buckets_exclude_unready_and_old_videos(self):
        self.assertIsNone(age_bucket(5.99))
        self.assertEqual("6-24h", age_bucket(6))
        self.assertEqual("1-7d", age_bucket(24))
        self.assertEqual("8-30d", age_bucket(24 * 8))
        self.assertIsNone(age_bucket(24 * 30 + .01))

    def test_scoring_uses_country_category_cohort_and_growth(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "history.sqlite3"
            self.add_rows(db, observations=2)
            candidates = score_candidates(db, now=datetime(2026, 9, 22, 12, tzinfo=timezone.utc))
        self.assertEqual(30, len(candidates))
        self.assertGreater(candidates[0].score, candidates[-1].score)
        self.assertGreater(candidates[0].metrics["speed"], 0)
        self.assertEqual("1-7d", candidates[0].age_bucket)
        self.assertEqual(100.0, candidates[0].percentiles["plays"])

    def test_jev_result_is_fail_closed_and_queue_gate_is_deterministic(self):
        response = {
            "model": "jev-1.test", "answers": {
                "route": {"choice": "deep", "confidence": .91},
                "creative_reusability": {"score": .8},
                "commerce_conversion": {"score": .6},
                "duplicate_risk": {"noul": .1},
            },
        }
        parsed = parse_jev_response(response)
        self.assertEqual(8, parsed["creative_score"])
        self.assertEqual(6, parsed["conversion_score"])
        self.assertTrue(should_enqueue(parsed))
        response["answers"]["route"]["choice"] = "unexpected"
        with self.assertRaises(Exception):
            parse_jev_response(response)

    def test_jev_score_criteria_follow_the_typesafe_request_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "history.sqlite3"
            self.add_rows(db, count=1)
            candidate = score_candidates(db, now=datetime(2026, 9, 22, 12, tzinfo=timezone.utc))[0]
        request, _ = jev_input(candidate)
        self.assertIsInstance(request["questions"]["creative_reusability"]["criteria"], list)
        self.assertIsInstance(request["questions"]["commerce_conversion"]["criteria"], list)
        self.assertEqual("fresh_breakout", request["state"]["video"]["score_profile"])
        self.assertIn("speed", request["state"]["video"]["score_components"])

    def test_publication_time_enrichment_updates_missing_recent_material(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "history.sqlite3"
            observed = datetime.now(timezone.utc)
            row = {
                "material_id": "9000", "query_country": "US", "brand": "Creator",
                "ad_text": "Caption", "video_file": "", "crawled_at": observed.isoformat(),
                "likes": 10, "plays": 100, "categories": ["Lifestyle"],
                "video_url": "https://v16.tiktokcdn.com/example.mp4",
                "detail_url": "https://www.tiktok.com/@creator/video/9000",
            }
            save_run({"run_id": "20260921_120000_a", "started_at": observed.isoformat()}, [row], db)
            resolved = "2026-09-20T12:00:00+00:00"
            with patch("analysis_pipeline.fetch_video_published_at", return_value=resolved), patch("analysis_pipeline.time.sleep"):
                result = enrich_publication_times(db, limit=1)
            with closing(connect(db)) as conn:
                material = conn.execute("SELECT published_at, published_at_source FROM materials WHERE material_id='9000'").fetchone()
                enrichment = conn.execute("SELECT resolved_at, attempt_count FROM publication_enrichment WHERE material_id='9000'").fetchone()
        self.assertEqual({"publish_attempted": 1, "publish_resolved": 1, "publish_failed": 0}, result)
        self.assertEqual(resolved, material["published_at"])
        self.assertEqual("tiktok_video_detail", material["published_at_source"])
        self.assertIsNotNone(enrichment["resolved_at"])
        self.assertEqual(1, enrichment["attempt_count"])

    def test_queue_claims_one_material_once(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "history.sqlite3"
            self.add_rows(db, count=1)
            ensure_schema(db)
            with closing(connect(db)) as conn, conn:
                self.assertTrue(enqueue(conn, "9000"))
                self.assertFalse(enqueue(conn, "9000"))
                # An earlier legacy retry must not starve the current pipeline.
                conn.execute("""INSERT INTO analysis_jobs
                    (material_id, analysis_version, evaluation_version, status, next_attempt_at)
                    VALUES (?, 'vlm-v1', ?, 'retry_wait', '2000-01-01T00:00:00+00:00')""",
                             ("9000", RULE_VERSION))
            claimed = claim_job(db)
            self.assertEqual("9000", claimed["material_id"])
            self.assertEqual(ANALYSIS_VERSION, claimed["analysis_version"])
            self.assertEqual("running", claimed["status"])
            self.assertEqual(1, claimed["attempt_count"])
            self.assertIsNone(claim_job(db))

    def test_analysis_version_backfill_queues_previously_accepted_material(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "history.sqlite3"
            self.add_rows(db, count=1)
            ensure_schema(db)
            with closing(connect(db)) as conn, conn:
                conn.execute("""INSERT INTO analysis_evaluations (
                    material_id, evaluation_version, evaluated_at, observed_at, published_at, country, category, age_bucket,
                    score, metrics_json, percentiles_json, input_hash, jev_decision, jev_confidence, creative_score,
                    conversion_score, duplicate_risk, jev_model, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    ("9000", RULE_VERSION, "2026-09-21T12:00:00+00:00", "2026-09-21T12:00:00+00:00", "2026-09-19T12:00:00+00:00",
                     "US", "Lifestyle", "1-7d", 90, "{}", "{}", "hash", "deep", .9, 8, 8, .1, "jev-test", "evaluated"))
            self.assertEqual(1, backfill_accepted_jobs(db))
            self.assertEqual(0, backfill_accepted_jobs(db))

    def test_media_url_whitelist_and_vlm_json_contract(self):
        self.assertTrue(valid_media_url("https://v16.tiktokcdn.com/object.mp4"))
        self.assertTrue(valid_media_url("https://v1.tiktokv.com/object.mp4"))
        self.assertTrue(valid_media_url("https://v16-webapp.tiktok.com/object.mp4"))
        self.assertFalse(valid_media_url("http://v16.tiktokcdn.com/object.mp4"))
        self.assertFalse(valid_media_url("https://example.com/object.mp4"))
        self.assertFalse(valid_media_url("https://www.tiktok.com/@creator/video/123"))
        self.assertEqual("https://v16-webapp.tiktok.com/object.mp4", _detail_play_url({"video": {"playAddr": "https://v16-webapp.tiktok.com/object.mp4"}}))
        report = {key: "ok" for key in ("summary_zh", "viral_mechanisms", "hook", "creative_structure", "visual_language", "on_screen_text", "subtitle_summary", "audience", "comment_insights", "conversion_analysis", "reusable_playbook", "risks", "confidence", "missing_inputs")}
        self.assertEqual(report, _extract_json(json.dumps(report)))
        with self.assertRaises(VlmSchemaError):
            _extract_json('{"summary_zh":"only"}')

    def test_vlm_uses_retry_after_for_temporary_gateway_failure(self):
        report = {key: "ok" for key in ("summary_zh", "viral_mechanisms", "hook", "creative_structure", "visual_language", "on_screen_text", "subtitle_summary", "audience", "comment_insights", "conversion_analysis", "reusable_playbook", "risks", "confidence", "missing_inputs")}

        class Response:
            def __init__(self, status, body=None, headers=None):
                self.status_code = status
                self._body = body or {}
                self.headers = headers or {}

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError("unexpected non-retry HTTP status")

            def json(self):
                return self._body

        class Session:
            def __init__(self):
                self.responses = [Response(429, headers={"Retry-After": "1"}), Response(200, {"choices": [{"message": {"content": json.dumps(report)}}]})]

            def post(self, *args, **kwargs):
                return self.responses.pop(0)

        with patch("analysis_pipeline.read_secret", return_value="not-recorded"), patch("analysis_pipeline.time.sleep") as sleep:
            self.assertEqual(report, call_vlm({"model": "test"}, session=Session()))
        sleep.assert_called_once_with(1)

    def test_asr_uses_retry_after_and_never_logs_audio_or_secret(self):
        class Response:
            def __init__(self, status, body=None, headers=None):
                self.status_code = status
                self._body = body or {}
                self.headers = headers or {}

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError("unexpected non-retry HTTP status")

            def json(self):
                return self._body

        class Session:
            def __init__(self):
                self.responses = [Response(429, headers={"Retry-After": "1"}), Response(200, {"text": "hello world"})]
                self.calls = []

            def post(self, *args, **kwargs):
                self.calls.append(kwargs)
                return self.responses.pop(0)

        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "sample.mp3"
            audio.write_bytes(b"ID3" + b"x" * 2048)
            session = Session()
            with patch("analysis_pipeline.read_secret", return_value="not-recorded"), patch("analysis_pipeline.time.sleep") as sleep:
                transcript = call_siliconflow_asr(audio, session=session)
        self.assertEqual("hello world", transcript["text"])
        self.assertEqual("siliconflow_asr", transcript["source"])
        self.assertEqual(2, len(session.calls))
        sleep.assert_called_once_with(1)

    def test_asr_rejected_request_is_not_retried(self):
        class Response:
            status_code = 422
            headers = {}

        class Session:
            def __init__(self):
                self.calls = 0

            def post(self, *args, **kwargs):
                self.calls += 1
                return Response()

        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "sample.mp3"
            audio.write_bytes(b"ID3" + b"x" * 2048)
            session = Session()
            with patch("analysis_pipeline.read_secret", return_value="not-recorded"):
                with self.assertRaisesRegex(AnalysisError, "AsrSchemaError"):
                    call_siliconflow_asr(audio, session=session)
        self.assertEqual(1, session.calls)

    def test_vlm_rejected_request_is_not_retried(self):
        class Response:
            status_code = 422
            headers = {}

        class Session:
            def __init__(self):
                self.calls = 0

            def post(self, *args, **kwargs):
                self.calls += 1
                return Response()

        session = Session()
        with patch("analysis_pipeline.read_secret", return_value="not-recorded"):
            with self.assertRaisesRegex(AnalysisError, "VlmSchemaError"):
                call_vlm({"model": "test"}, session=session)
        self.assertEqual(1, session.calls)

    def test_comment_normalization_drops_account_identity(self):
        normalized = normalize_comment({
            "cid": "comment-1", "text": "  useful   comment ", "digg_count": 7,
            "reply_comment_total": 3, "create_time": 123, "user": {"unique_id": "private-account"},
        })
        self.assertEqual({"comment_id": "comment-1", "text": "useful comment", "likes": 7,
                          "reply_count": 3, "created_at_unix": 123}, normalized)
        self.assertNotIn("user", normalized)

    def test_failed_media_work_deletes_temporary_mp4(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "history.sqlite3"
            tmp = Path(directory) / "tmp"
            self.add_rows(db, count=1)
            ensure_schema(db)
            with closing(connect(db)) as conn, conn:
                conn.execute("""INSERT INTO analysis_evaluations (
                    material_id, evaluation_version, evaluated_at, observed_at, published_at, country, category, age_bucket,
                    score, metrics_json, percentiles_json, input_hash, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("9000", RULE_VERSION, "2026-09-21T12:00:00+00:00", "2026-09-21T12:00:00+00:00", "2026-09-19T12:00:00+00:00", "US", "Lifestyle", "1-7d", 90, "{}", "{}", "hash", "evaluated"))
                enqueue(conn, "9000")
            job = claim_job(db)

            download_sessions = []

            def fake_download(_url, target, *, session=None):
                download_sessions.append(session)
                target.write_bytes(b"0000ftyp" + b"x" * 2048)

            with patch("analysis_pipeline.TMP_ROOT", tmp), patch("analysis_pipeline.fetch_subtitles_and_comments", return_value=([], [], [], "")), patch("analysis_pipeline.download_media", side_effect=fake_download), patch("analysis_pipeline.extract_keyframes", side_effect=RuntimeError("frame error")):
                with self.assertRaises(RuntimeError):
                    process_job(job, db)
            self.assertEqual([], list(tmp.glob("*.mp4")))
            self.assertIsNotNone(download_sessions[0])


if __name__ == "__main__":
    unittest.main()
