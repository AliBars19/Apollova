"""
Tests for Apollova Render Watcher v2.

Covers: config, state manager, smart scheduler (12/day limit + overflow),
folder→account mapping, upload pipeline, and full integration.

Run: python tests/test_render_watcher.py
"""

import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from upload_state import StateManager, UploadStatus, ScheduleStatus, compute_file_hash
from config import Config
from notification import NotificationService


class TestConfig(unittest.TestCase):
    """Test configuration and folder→account mapping."""

    def test_default_requires_password(self):
        config = Config()
        errors = config.validate()
        self.assertTrue(any("GATE_PASSWORD" in e for e in errors))

    def test_valid_config(self):
        config = Config(gate_password="test")
        self.assertEqual(len(config.validate()), 0)

    def test_folder_account_mapping(self):
        config = Config(gate_password="test")
        self.assertEqual(config.folder_account_map["Apollova-Aurora"], "aurora")
        self.assertEqual(config.folder_account_map["Apollova-Mono"], "nova")
        self.assertEqual(config.folder_account_map["Apollova-Onyx"], "nova")

    def test_get_template_from_path(self):
        config = Config()
        self.assertEqual(config.get_template_from_path("/foo/Apollova-Aurora/jobs/renders/v.mp4"), "aurora")
        self.assertEqual(config.get_template_from_path("/foo/Apollova-Mono/jobs/renders/v.mp4"), "mono")
        self.assertEqual(config.get_template_from_path("/foo/Apollova-Onyx/jobs/renders/v.mp4"), "onyx")

    def test_get_watch_paths(self):
        tmp = tempfile.mkdtemp()
        config = Config(gate_password="test", apollova_root=tmp)
        # Create the directories
        for name in config.folder_account_map:
            (Path(tmp) / name / config.renders_subfolder).mkdir(parents=True, exist_ok=True)

        paths = config.get_watch_paths()
        self.assertEqual(len(paths), 3)
        accounts = set(acct for _, acct in paths.values())
        self.assertIn("aurora", accounts)
        self.assertIn("nova", accounts)
        # Verify keys are the folder names
        self.assertIn("Apollova-Aurora", paths)
        self.assertIn("Apollova-Mono", paths)
        self.assertIn("Apollova-Onyx", paths)
        shutil.rmtree(tmp)

    def test_onyx_account_easy_change(self):
        """Verify changing Onyx to its own account is a one-line change."""
        config = Config(gate_password="test")
        config.folder_account_map["Apollova-Onyx"] = "onyx"
        self.assertEqual(config.folder_account_map["Apollova-Onyx"], "onyx")


class TestStateManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = StateManager(os.path.join(self.tmp, "test.db"))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_add_and_retrieve(self):
        rid = self.state.add_upload("/v.mp4", "aurora", "aurora")
        record = self.state.get_record(rid)
        self.assertEqual(record.template, "aurora")
        self.assertEqual(record.account, "aurora")
        self.assertEqual(record.upload_status, "pending")

    def test_duplicate_returns_same_id(self):
        r1 = self.state.add_upload("/v.mp4", "aurora", "aurora")
        r2 = self.state.add_upload("/v.mp4", "mono", "nova")  # different params, same path
        self.assertEqual(r1, r2)

    def test_full_lifecycle(self):
        rid = self.state.add_upload("/v.mp4", "aurora", "aurora")
        self.state.mark_uploading(rid)
        self.state.mark_uploaded(rid, "vid_123")
        self.state.mark_scheduled(rid, "2026-02-13T14:00:00")

        r = self.state.get_record(rid)
        self.assertEqual(r.upload_status, "uploaded")
        self.assertEqual(r.video_id, "vid_123")
        self.assertEqual(r.schedule_status, "scheduled")
        self.assertTrue(self.state.is_processed("/v.mp4"))

    def test_failed_and_retry(self):
        rid = self.state.add_upload("/v.mp4", "mono", "nova")
        self.state.mark_upload_failed(rid, "timeout")
        self.assertEqual(len(self.state.get_failed()), 1)

        self.state.reset_failed(rid)
        self.assertEqual(self.state.get_record(rid).upload_status, "pending")

    def test_retryable_max_attempts(self):
        rid = self.state.add_upload("/v.mp4", "mono", "nova")
        for _ in range(3):
            self.state.mark_upload_failed(rid, "err")
        self.assertEqual(len(self.state.get_retryable(3)), 0)  # exhausted

    def test_count_scheduled_for_date(self):
        today = datetime.now()
        for i in range(5):
            rid = self.state.add_upload(f"/v{i}.mp4", "aurora", "aurora")
            self.state.mark_uploaded(rid, f"vid_{i}")
            sched = today.replace(hour=11 + i, minute=0, second=0)
            self.state.mark_scheduled(rid, sched.isoformat())

        self.assertEqual(self.state.count_scheduled_for_date("aurora", today), 5)
        self.assertEqual(self.state.count_scheduled_for_date("nova", today), 0)

    def test_get_last_scheduled_time(self):
        today = datetime.now()
        rid1 = self.state.add_upload("/a.mp4", "aurora", "aurora")
        self.state.mark_uploaded(rid1, "v1")
        t1 = today.replace(hour=11, minute=0, second=0, microsecond=0)
        self.state.mark_scheduled(rid1, t1.isoformat())

        rid2 = self.state.add_upload("/b.mp4", "aurora", "aurora")
        self.state.mark_uploaded(rid2, "v2")
        t2 = today.replace(hour=14, minute=0, second=0, microsecond=0)
        self.state.mark_scheduled(rid2, t2.isoformat())

        last = self.state.get_last_scheduled_time("aurora", today)
        self.assertEqual(last.hour, 14)

    def test_stats_includes_today(self):
        today = datetime.now()
        rid = self.state.add_upload("/v.mp4", "aurora", "aurora")
        self.state.mark_uploaded(rid, "v1")
        self.state.mark_scheduled(rid, today.replace(hour=12).isoformat())

        stats = self.state.get_stats()
        self.assertEqual(stats.get("aurora_today", 0), 1)


class TestSmartScheduler(unittest.TestCase):
    """Test scheduling logic: slots, 12/day limit, next-day overflow."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = StateManager(os.path.join(self.tmp, "test.db"))
        self.config = Config(
            gate_password="test",
            videos_per_day_per_account=12,
            schedule_interval_minutes=60,
            schedule_day_start_hour=11,
            schedule_day_end_hour=23,
        )
        # Import here to avoid issues with rich
        from render_watcher import SmartScheduler
        self.scheduler = SmartScheduler(self.config, self.state)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_first_slot_is_start_hour(self):
        """First video of the day starts at 11 AM (or 10 min from now if later)."""
        slot = self.scheduler.get_next_slot("aurora")
        now = datetime.now()
        # Should be today at start hour or a bit into the future
        self.assertEqual(slot.date(), now.date())
        self.assertGreaterEqual(slot.hour, self.config.schedule_day_start_hour)

    def test_slots_are_spaced_correctly(self):
        """Each subsequent video is 1 hour after the previous."""
        # Schedule first video, then verify the next one is 60 min later
        slot1 = self.scheduler.get_next_slot("aurora")

        # Simulate scheduling at slot1
        rid = self.state.add_upload("/a.mp4", "aurora", "aurora")
        self.state.mark_uploaded(rid, "v1")
        self.state.mark_scheduled(rid, slot1.isoformat())

        # Next slot should be exactly 60 min after slot1
        slot2 = self.scheduler.get_next_slot("aurora")
        diff = (slot2 - slot1).total_seconds()
        self.assertAlmostEqual(diff, 3600, delta=60)  # 60 min ± 1 min

    def test_12_limit_overflows_to_next_day(self):
        """When 12 videos fill today, the 13th goes to tomorrow."""
        today = datetime.now()

        for i in range(12):
            rid = self.state.add_upload(f"/v{i}.mp4", "aurora", "aurora")
            self.state.mark_uploaded(rid, f"vid_{i}")
            sched = today.replace(hour=11 + i, minute=0, second=0, microsecond=0)
            self.state.mark_scheduled(rid, sched.isoformat())

        # 13th video should go to tomorrow
        slot = self.scheduler.get_next_slot("aurora")
        self.assertEqual(slot.date(), (today + timedelta(days=1)).date())
        self.assertEqual(slot.hour, self.config.schedule_day_start_hour)

    def test_different_accounts_independent(self):
        """Aurora and Nova have separate 12/day limits."""
        today = datetime.now()

        # Fill aurora
        for i in range(12):
            rid = self.state.add_upload(f"/a{i}.mp4", "aurora", "aurora")
            self.state.mark_uploaded(rid, f"a_vid_{i}")
            self.state.mark_scheduled(rid, today.replace(hour=11 + i).isoformat())

        # Nova should still have today slots
        slot = self.scheduler.get_next_slot("nova")
        self.assertEqual(slot.date(), today.date())

    def test_overflow_multiple_days(self):
        """If today AND tomorrow are full, goes to day after."""
        today = datetime.now()

        # Fill today and tomorrow for aurora
        for day_offset in range(2):
            for i in range(12):
                d = today + timedelta(days=day_offset)
                rid = self.state.add_upload(f"/v_d{day_offset}_{i}.mp4", "aurora", "aurora")
                self.state.mark_uploaded(rid, f"vid_d{day_offset}_{i}")
                self.state.mark_scheduled(rid, d.replace(hour=11 + i).isoformat())

        slot = self.scheduler.get_next_slot("aurora")
        expected_date = (today + timedelta(days=2)).date()
        self.assertEqual(slot.date(), expected_date)


class TestVideoUploaderTestMode(unittest.TestCase):
    def setUp(self):
        from render_watcher import VideoUploader
        self.config = Config(gate_password="test", api_base_url="https://example.com")
        self.uploader = VideoUploader(self.config, test_mode=True)

    def test_auth(self):
        self.assertTrue(self.uploader.authenticate())

    def test_upload_returns_fake_id(self):
        result = self.uploader.upload_video("/fake.mp4", "aurora")
        self.assertIn("id", result)
        self.assertTrue(result["id"].startswith("test_"))

    def test_schedule(self):
        self.assertTrue(self.uploader.schedule_video("test_123", "2026-02-13T12:00:00"))


class TestFileHash(unittest.TestCase):
    def test_deterministic(self):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        tmp.write(b"video content" * 1000)
        tmp.close()
        self.assertEqual(compute_file_hash(tmp.name), compute_file_hash(tmp.name))
        self.assertEqual(len(compute_file_hash(tmp.name)), 64)
        os.unlink(tmp.name)


class TestNotifications(unittest.TestCase):
    def test_disabled_no_error(self):
        ns = NotificationService(enabled=False)
        ns.video_uploaded("test.mp4", "aurora", "12:00")

    def test_no_backend_no_error(self):
        ns = NotificationService(enabled=True)
        ns._backend = None
        ns.notify("Test", "msg")


class TestIntegration(unittest.TestCase):
    """Full pipeline test: create video files → scan → upload → schedule."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.config = Config(
            gate_password="test",
            apollova_root=self.tmp,
            state_db_path=os.path.join(self.tmp, "data", "state.db"),
            log_dir=os.path.join(self.tmp, "logs"),
            videos_per_day_per_account=12,
            schedule_interval_minutes=60,
            schedule_day_start_hour=11,
        )
        self.config.ensure_dirs()

        self.state = StateManager(self.config.state_db_path)

        from render_watcher import VideoUploader, SmartScheduler, FolderWatcher
        self.uploader = VideoUploader(self.config, test_mode=True)
        self.uploader.authenticate()
        self.scheduler = SmartScheduler(self.config, self.state)
        self.notifications = NotificationService(enabled=False)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _create_video(self, folder: str, name: str) -> Path:
        renders = Path(self.tmp) / folder / self.config.renders_subfolder
        renders.mkdir(parents=True, exist_ok=True)
        fp = renders / name
        fp.write_bytes(b"fake video " * 100)
        return fp

    def test_aurora_folder_assigns_aurora_account(self):
        """Videos in Apollova-Aurora go to aurora account."""
        from render_watcher import FolderWatcher
        video = self._create_video("Apollova-Aurora", "Song - Artist.mp4")
        watch_path = video.parent

        watcher = FolderWatcher(
            watch_path, "aurora", "aurora",
            self.uploader, self.state, self.scheduler, self.notifications, self.config,
        )
        watcher._process_video(video)

        record = self.state.get_by_path(str(video))
        self.assertEqual(record.account, "aurora")
        self.assertEqual(record.upload_status, "uploaded")

    def test_mono_folder_assigns_nova_account(self):
        """Videos in Apollova-Mono go to nova account."""
        from render_watcher import FolderWatcher
        video = self._create_video("Apollova-Mono", "Track - Producer.mp4")
        watch_path = video.parent

        watcher = FolderWatcher(
            watch_path, "nova", "mono",
            self.uploader, self.state, self.scheduler, self.notifications, self.config,
        )
        watcher._process_video(video)

        record = self.state.get_by_path(str(video))
        self.assertEqual(record.account, "nova")

    def test_no_duplicate_processing(self):
        """Same video can't be processed twice."""
        from render_watcher import FolderWatcher
        video = self._create_video("Apollova-Aurora", "Test.mp4")

        watcher = FolderWatcher(
            video.parent, "aurora", "aurora",
            self.uploader, self.state, self.scheduler, self.notifications, self.config,
        )
        watcher._process_video(video)
        watcher._process_video(video)  # Second call should be no-op

        self.assertEqual(self.state.get_stats()["uploaded"], 1)

    def test_sequential_scheduling(self):
        """Videos uploaded one-by-one get sequential schedule times."""
        from render_watcher import FolderWatcher
        renders_path = Path(self.tmp) / "Apollova-Aurora" / self.config.renders_subfolder
        renders_path.mkdir(parents=True, exist_ok=True)

        watcher = FolderWatcher(
            renders_path, "aurora", "aurora",
            self.uploader, self.state, self.scheduler, self.notifications, self.config,
        )

        times = []
        for i in range(3):
            video = renders_path / f"Song_{i}.mp4"
            video.write_bytes(b"video" * 100)
            watcher._process_video(video)
            record = self.state.get_by_path(str(video))
            times.append(datetime.fromisoformat(record.scheduled_at))

        # Each should be ~60 min after the previous
        for i in range(1, len(times)):
            diff = (times[i] - times[i - 1]).total_seconds()
            self.assertAlmostEqual(diff, 3600, delta=600)  # ~60min ± 10min tolerance

    def test_12_limit_overflow(self):
        """13th video of the day gets scheduled for tomorrow."""
        from render_watcher import FolderWatcher
        renders = Path(self.tmp) / "Apollova-Aurora" / self.config.renders_subfolder
        renders.mkdir(parents=True, exist_ok=True)

        watcher = FolderWatcher(
            renders, "aurora", "aurora",
            self.uploader, self.state, self.scheduler, self.notifications, self.config,
        )

        today = datetime.now().date()
        for i in range(13):
            video = renders / f"Song_{i:02d}.mp4"
            video.write_bytes(b"video" * 100)
            watcher._process_video(video)

        # Last video should be tomorrow
        last_record = self.state.get_by_path(str(renders / "Song_12.mp4"))
        last_sched = datetime.fromisoformat(last_record.scheduled_at)
        self.assertGreater(last_sched.date(), today)


if __name__ == "__main__":
    unittest.main(verbosity=2)