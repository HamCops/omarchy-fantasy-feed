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


class SimulatorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.server = espn_simulator.create_server(
            "127.0.0.1", 0, games=10, max_plays=20, latency_ms=10
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
            second_status, second = self.run_once(cache_path)

        self.assertEqual(0, first_status)
        self.assertEqual(0, second_status)
        self.assertEqual("live", second["sourceState"])
        self.assertEqual(10, len(second["games"]))
        self.assertEqual(20, len(second["events"]))
        self.assertEqual(60, len(second["leaderboard"]))
        self.assertEqual([], second["skipped"])
        self.assertTrue(all(game["period"] > 0 and game["clock"] for game in second["games"]))
        newest = second["events"][-10:]
        self.assertEqual(10, len({event["gameId"] for event in newest}))
        metrics = self.server.simulator_state.metrics()
        self.assertEqual(2, metrics["tick"])
        self.assertGreaterEqual(metrics["peakConcurrentRequests"], 2)


if __name__ == "__main__":
    unittest.main()
