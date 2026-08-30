from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import espn_simulator
import feed


class SimulatorScheduleTests(unittest.TestCase):
    def test_default_schedule_staggers_games_with_deterministic_bursts(self):
        state = espn_simulator.SimulatorState(
            games=10, max_plays=30, latency_ms=0
        )
        arrivals = []
        previous_total = 0
        for _tick in range(12):
            state.scoreboard()
            total = state.exposed_play_count()
            arrivals.append(total - previous_total)
            previous_total = total

        self.assertEqual([2, 3, 1, 2, 3, 1, 2, 3, 1, 2, 5, 1], arrivals)
        self.assertTrue(all(count > 0 for count in state.metrics()["gamePlayCounts"]))
        self.assertNotIn(10, arrivals)


class SimulatorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.server = espn_simulator.create_server(
            "127.0.0.1",
            0,
            games=10,
            max_plays=30,
            latency_ms=5,
            staggered=False,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def run_once(self, cache_path: Path, *, reset_cache: bool = False):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            arguments = [
                "--once",
                "--cache",
                str(cache_path),
                "--provider-base-url",
                self.base_url,
            ]
            if reset_cache:
                arguments.append("--reset-cache")
            status = feed.main(arguments)
        self.assertEqual("", stderr.getvalue())
        return status, json.loads(stdout.getvalue())

    def test_ten_game_http_simulation_exercises_the_complete_live_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "simulator.json"
            cache_path.write_text("stale simulator run", encoding="utf-8")
            first_status, first = self.run_once(cache_path, reset_cache=True)
            latest_status, latest = first_status, first
            for _tick in range(2, 26):
                latest_status, latest = self.run_once(cache_path)

        self.assertEqual(0, first_status)
        self.assertEqual(0, latest_status)
        self.assertEqual("live", latest["sourceState"])
        self.assertEqual(10, len(latest["games"]))
        self.assertEqual(200, len(latest["events"]))
        self.assertEqual(60, len(latest["leaderboard"]))
        self.assertEqual([], latest["skipped"])
        self.assertTrue(all(game["period"] > 0 and game["clock"] for game in latest["games"]))
        self.assertTrue(all("possession" in game for game in latest["games"]))
        self.assertTrue(any(game["isRedZone"] for game in latest["games"]))
        self.assertTrue(any("touchdown" in event["kind"] for event in latest["events"]))
        newest = latest["events"][-10:]
        self.assertEqual(10, len({event["gameId"] for event in newest}))
        metrics = self.server.simulator_state.metrics()
        self.assertEqual(25, metrics["tick"])
        self.assertGreaterEqual(metrics["peakConcurrentRequests"], 2)
        self.assertLessEqual(metrics["totalRequests"], 25 * 22)


if __name__ == "__main__":
    unittest.main()
