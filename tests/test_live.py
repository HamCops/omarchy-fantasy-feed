from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import espn
import feed
from test_espn import SCOREBOARD, STATS_URL, SUMMARY, RECEPTION_STATS, FakeJson, live_fake


class CacheTests(unittest.TestCase):
    def fresh_snapshot(self):
        fixture = espn.collect_live(
            get_json=live_fake(), observed_at="2026-08-28T20:16:00Z"
        )
        return feed.reduce_frames(fixture)

    def test_atomic_cache_uses_same_directory_and_mode_0600(self):
        snapshot = self.fresh_snapshot()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "snapshot.json"
            real_replace = os.replace
            replacements = []

            def recording_replace(source, destination):
                replacements.append((Path(source), Path(destination)))
                real_replace(source, destination)

            with mock.patch.object(feed.os, "replace", side_effect=recording_replace):
                feed.write_last_good_cache(path, snapshot)
            self.assertEqual(snapshot, feed.load_last_good_cache(path))
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            self.assertEqual(path.parent, replacements[0][0].parent)
            self.assertEqual(path, replacements[0][1])

    def test_failed_refresh_preserves_cache_and_returns_stale_ten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            snapshot, status, _ = feed.refresh_live(
                path,
                get_json=live_fake(),
                observed_at="2026-08-28T20:16:00Z",
            )
            self.assertEqual(0, status)
            original_bytes = path.read_bytes()
            failure = FakeJson(
                {espn.SCOREBOARD_URL: espn.ProviderError("network_error", "offline")}
            )
            stale, status, error = feed.refresh_live(path, get_json=failure)
            self.assertEqual(10, status)
            self.assertTrue(stale["stale"])
            self.assertEqual("offline", stale["sourceState"])
            self.assertEqual(1, len(stale["errors"]))
            self.assertEqual("network_error", error["code"])
            self.assertEqual(original_bytes, path.read_bytes())
            self.assertFalse(snapshot["stale"])

    def test_failure_without_valid_cache_returns_twenty_and_no_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text("not json", encoding="utf-8")
            failure = FakeJson(
                {espn.SCOREBOARD_URL: espn.ProviderError("network_error", "offline")}
            )
            snapshot, status, error = feed.refresh_live(path, get_json=failure)
            self.assertIsNone(snapshot)
            self.assertEqual(20, status)
            self.assertEqual("network_error", error["code"])
            self.assertEqual("not json", path.read_text(encoding="utf-8"))

    def test_scheduled_success_is_cacheable(self):
        scoreboard = copy.deepcopy(SCOREBOARD)
        scoreboard["events"][0]["competitions"][0]["status"]["type"]["state"] = "pre"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            snapshot, status, error = feed.refresh_live(
                path,
                get_json=FakeJson({espn.SCOREBOARD_URL: scoreboard}),
                observed_at="2026-08-28T18:00:00Z",
            )
            self.assertEqual(0, status)
            self.assertIsNone(error)
            self.assertEqual("scheduled", snapshot["sourceState"])
            self.assertEqual(snapshot, feed.load_last_good_cache(path))

    def test_default_cache_honors_absolute_xdg_home(self):
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": "/tmp/fantasy-cache"}):
            self.assertEqual(
                Path("/tmp/fantasy-cache/fantasy-feed/snapshot.json"),
                feed.default_cache_path(),
            )


class LiveApplicationTests(unittest.TestCase):
    def run_main(self, arguments, fake, observed_at=None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = feed.main(
                arguments, get_json=fake, observed_at=observed_at
            )
        return status, stdout.getvalue(), stderr.getvalue()

    def test_mocked_once_application_path_outputs_one_normalized_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            status, stdout, stderr = self.run_main(
                ["--once", "--cache", str(path)],
                live_fake(),
                "2026-08-28T20:16:00Z",
            )
            snapshot = json.loads(stdout)
            self.assertEqual(0, status)
            self.assertEqual("", stderr)
            self.assertEqual(feed.SCHEMA_VERSION, snapshot["schemaVersion"])
            self.assertEqual(1, len(snapshot["events"]))
            self.assertNotIn("boxscore", stdout)
            self.assertNotIn("drives", stdout)

    def test_stale_application_path_outputs_cache_and_exits_ten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            feed.refresh_live(
                path,
                get_json=live_fake(),
                observed_at="2026-08-28T20:16:00Z",
            )
            failure = FakeJson(
                {espn.SCOREBOARD_URL: espn.ProviderError("network_error", "offline")}
            )
            status, stdout, stderr = self.run_main(
                ["--once", "--cache", str(path)], failure
            )
            snapshot = json.loads(stdout)
            self.assertEqual(10, status)
            self.assertEqual("", stderr)
            self.assertTrue(snapshot["stale"])
            self.assertEqual(1, len(snapshot["errors"]))

    def test_no_cache_application_failure_has_no_stdout_and_exits_twenty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            failure = FakeJson(
                {espn.SCOREBOARD_URL: espn.ProviderError("network_error", "offline")}
            )
            status, stdout, stderr = self.run_main(
                ["--once", "--cache", str(path)], failure
            )
            self.assertEqual(20, status)
            self.assertEqual("", stdout)
            self.assertIn("live refresh failed", stderr)


if __name__ == "__main__":
    unittest.main()
