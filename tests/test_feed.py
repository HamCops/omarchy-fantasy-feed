from __future__ import annotations

import copy
import dataclasses
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import feed


def load_json(relative_path: str):
    with (ROOT / relative_path).open("r", encoding="utf-8") as stream:
        return json.load(stream)


def points(participant: feed.PlayerDelta) -> dict[str, float]:
    return {
        "ppr": participant.ppr_hundredths / 100.0,
        "standard": participant.standard_hundredths / 100.0,
    }


class ModelAndScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = load_json("fixtures/raw/scoring_plays.json")
        cls.expected = load_json("fixtures/expected/scoring.json")
        cls.athletes = feed.build_athlete_index(cls.raw["athletes"])

    def test_public_models_are_frozen_and_slotted(self):
        models = (
            feed.PlayKey,
            feed.StatDelta,
            feed.PlayerDelta,
            feed.AttributedPlay,
            feed.RejectedPlay,
        )
        for model in models:
            self.assertTrue(dataclasses.is_dataclass(model))
            self.assertNotIn("__dict__", model.__dict__)

        key = feed.PlayKey("espn", "game", "play")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            key.play_id = "changed"

    def test_required_scoring_examples_and_exact_identities(self):
        actual_stat_keys = set()
        for raw_play in self.raw["plays"]:
            with self.subTest(play_id=raw_play["id"]):
                result = feed.parse_play(raw_play, self.athletes)
                self.assertIsInstance(result, feed.AttributedPlay)
                self.assertEqual("exact", result.attribution)
                expected = self.expected[raw_play["id"]]
                self.assertEqual(expected["kind"], result.kind)
                self.assertEqual(len(expected["participants"]), len(result.participants))
                for expected_player, actual_player in zip(
                    expected["participants"], result.participants, strict=True
                ):
                    self.assertEqual(expected_player["id"], actual_player.player_id)
                    self.assertEqual(expected_player["name"], actual_player.display_name)
                    self.assertEqual(
                        {"ppr": expected_player["ppr"], "standard": expected_player["standard"]},
                        points(actual_player),
                    )
                    actual_stat_keys.update(stat.key for stat in actual_player.stats)
        self.assertEqual(set(feed.SCORING_TABLE), actual_stat_keys)

    def test_scoring_uses_integer_hundredths(self):
        reception = (
            feed.stat_delta("reception", 1),
            feed.stat_delta("receiving_yards", 18),
        )
        self.assertEqual((280, 180), feed.score_stats(reception))
        passing_touchdown = (
            feed.stat_delta("passing_yards", 25),
            feed.stat_delta("passing_touchdown", 1),
        )
        self.assertEqual((500, 500), feed.score_stats(passing_touchdown))

    def test_zero_yard_reception_keeps_zero_stat_labels(self):
        raw_play = next(play for play in self.raw["plays"] if play["id"] == "reception-zero")
        result = feed.parse_play(raw_play, self.athletes)
        self.assertIsInstance(result, feed.AttributedPlay)
        passer, receiver = result.participants
        self.assertEqual((0, 0), (passer.ppr_hundredths, passer.standard_hundredths))
        self.assertEqual((100, 0), (receiver.ppr_hundredths, receiver.standard_hundredths))
        self.assertEqual(["0 PASS YDS"], [stat.label for stat in passer.stats])
        self.assertEqual(["REC", "0 REC YDS"], [stat.label for stat in receiver.stats])

    def test_quarterback_scramble_scores_as_rushing_yards(self):
        raw_play = next(play for play in self.raw["plays"] if play["id"] == "scramble-14")
        result = feed.parse_play(raw_play, self.athletes)
        self.assertIsInstance(result, feed.AttributedPlay)
        self.assertEqual("rush", result.kind)
        self.assertEqual("athlete-1", result.participants[0].player_id)
        self.assertEqual((140, 140), (
            result.participants[0].ppr_hundredths,
            result.participants[0].standard_hundredths,
        ))

    def test_good_pat_suffix_does_not_create_fantasy_points(self):
        raw_play = next(play for play in self.raw["plays"] if play["id"] == "passing-td-25")
        result = feed.parse_play(raw_play, self.athletes)
        self.assertIsInstance(result, feed.AttributedPlay)
        self.assertIn("extra point is GOOD", result.raw_text)
        self.assertEqual(["athlete-1", "athlete-3"], [player.player_id for player in result.participants])
        self.assertNotIn(
            "kick_extra_points_made",
            {stat.key for player in result.participants for stat in player.stats},
        )

    def test_semantic_hash_changes_when_provider_text_changes(self):
        original = self.raw["plays"][0]
        changed = copy.deepcopy(original)
        changed["text"] = changed["text"].replace("18 yards", "19 yards")
        changed["statYardage"] = 19
        changed["officialStats"]["passing_yards"] = 19
        changed["officialStats"]["receiving_yards"] = 19
        first = feed.parse_play(original, self.athletes)
        second = feed.parse_play(changed, self.athletes)
        self.assertNotEqual(first.revision, second.revision)


class ParserRejectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = load_json("fixtures/raw/rejections.json")
        cls.athletes = feed.build_athlete_index(cls.raw["athletes"])

    def test_rejections_fail_closed_without_score_fields(self):
        expected_reasons = {
            "no-play": "no_play_penalty",
            "unknown-type": "unknown_play_type",
            "lateral": "ambiguous_lateral",
            "contradictory": "contradictory_official_stats",
            "unresolved": "unresolved_athlete:Z.Missing",
        }
        for raw_play in self.raw["plays"]:
            with self.subTest(play_id=raw_play["id"]):
                result = feed.parse_play(raw_play, self.athletes)
                self.assertIsInstance(result, feed.RejectedPlay)
                self.assertEqual(expected_reasons[raw_play["id"]], result.reason)
                self.assertFalse(hasattr(result, "participants"))
                self.assertFalse(hasattr(result, "points"))

    def test_rejected_candidates_never_become_scored_events(self):
        fixture = {
            "fixtureVersion": 1,
            "athletes": self.raw["athletes"],
            "frames": [
                {
                    "observedAt": "2026-08-28T21:00:00Z",
                    "sourceState": "live",
                    "stale": False,
                    "games": [],
                    "plays": self.raw["plays"],
                }
            ],
        }
        snapshot = feed.reduce_frames(fixture)
        self.assertEqual([], snapshot["events"])
        self.assertEqual(len(self.raw["plays"]), len(snapshot["skipped"]))

    def test_duplicate_alias_rejects_identity(self):
        entries = copy.deepcopy(self.raw["athletes"])
        entries.append(
            {
                "id": "duplicate-athlete",
                "firstName": "Tyrell",
                "lastName": "Huntley",
                "displayName": "Tyrell Huntley",
                "team": "CLE",
            }
        )
        scoring = load_json("fixtures/raw/scoring_plays.json")["plays"][0]
        result = feed.parse_play(scoring, feed.build_athlete_index(entries))
        self.assertIsInstance(result, feed.RejectedPlay)
        self.assertEqual("ambiguous_athlete:T.Huntley", result.reason)

    def test_repeated_boxscore_entry_for_same_athlete_is_deduplicated(self):
        entries = copy.deepcopy(self.raw["athletes"])
        entries.append(copy.deepcopy(entries[0]))
        scoring = load_json("fixtures/raw/scoring_plays.json")["plays"][0]
        result = feed.parse_play(scoring, feed.build_athlete_index(entries))
        self.assertIsInstance(result, feed.AttributedPlay)
        self.assertEqual("athlete-1", result.participants[0].player_id)

    def test_supported_type_with_unmatched_wording_is_rejected(self):
        raw = copy.deepcopy(self.raw["plays"][3])
        raw["text"] = "T.Huntley flips the football to J.Cuevas for 7 yards."
        result = feed.parse_play(raw, self.athletes)
        self.assertEqual("unsupported_narrative", result.reason)


class ReducerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.demo = load_json("fixtures/replays/demo.json")

    def test_duplicate_frame_is_idempotent(self):
        first = feed.reduce_frames(self.demo, at=0)
        duplicate = feed.reduce_frames(self.demo, at=1)
        self.assertEqual(first["events"], duplicate["events"])
        self.assertEqual(first["skipped"], duplicate["skipped"])

    def test_supported_revision_replaces_and_marks_corrected(self):
        snapshot = feed.reduce_frames(self.demo, at=2)
        event = next(event for event in snapshot["events"] if event["playId"] == "reviewed-touchdown")
        self.assertEqual("corrected", event["lifecycle"])
        self.assertIn("previousRevision", event)
        self.assertEqual(4.8, event["participants"][0]["points"]["ppr"])
        self.assertEqual(9.0, event["participants"][1]["points"]["ppr"])

    def test_changed_rejected_revision_voids_prior_score(self):
        snapshot = feed.reduce_frames(self.demo, at=3)
        event = next(event for event in snapshot["events"] if event["playId"] == "reviewed-touchdown")
        self.assertEqual("voided", event["lifecycle"])
        self.assertEqual([], event["participants"])
        self.assertEqual("no_play_penalty", event["voidReason"])
        self.assertIn("Penalty on CLE, No Play", event["rawText"])
        self.assertIn("REVERSED", event["previousRawText"])
        self.assertIn(
            ("reviewed-touchdown", "no_play_penalty"),
            [(item["playId"], item["reason"]) for item in snapshot["skipped"]],
        )

    def test_absence_never_deletes_an_event(self):
        before_empty_frame = feed.reduce_frames(self.demo, at=3)
        after_empty_frame = feed.reduce_frames(self.demo, at=4)
        self.assertEqual(before_empty_frame["events"], after_empty_frame["events"])

    def test_review_reversal_can_promote_rejected_play(self):
        fixture = load_json("fixtures/raw/revisions.json")
        initial = feed.reduce_frames(fixture, at=0)
        corrected = feed.reduce_frames(fixture, at=1)
        self.assertEqual([], initial["events"])
        self.assertEqual("unknown_play_type", initial["skipped"][0]["reason"])
        self.assertEqual(1, len(corrected["events"]))
        self.assertEqual("corrected", corrected["events"][0]["lifecycle"])
        self.assertEqual("exact", corrected["events"][0]["attribution"])

    def test_snapshot_matches_checked_in_summary(self):
        expected = load_json("fixtures/expected/demo_summary.json")
        snapshot = feed.reduce_frames(self.demo)
        actual = {
            "observedAt": snapshot["observedAt"],
            "sourceState": snapshot["sourceState"],
            "eventStates": [
                [event["playId"], event["lifecycle"]] for event in snapshot["events"]
            ],
            "skipped": [[item["playId"], item["reason"]] for item in snapshot["skipped"]],
        }
        self.assertEqual(expected, actual)

    def test_events_and_skips_are_bounded(self):
        snapshot = feed.reduce_frames(self.demo, event_cap=2, skipped_cap=1)
        self.assertEqual(2, len(snapshot["events"]))
        self.assertEqual(1, len(snapshot["skipped"]))


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/feed.py"), *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_fixture_stdout_is_one_deterministic_json_document(self):
        arguments = ("--fixture", "fixtures/replays/demo.json")
        first = self.run_cli(*arguments)
        second = self.run_cli(*arguments)
        self.assertEqual(0, first.returncode)
        self.assertEqual("", first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        snapshot = json.loads(first.stdout)
        self.assertEqual(feed.SCHEMA_VERSION, snapshot["schemaVersion"])
        self.assertEqual(6, len(snapshot["events"]))

    def test_frame_selection(self):
        result = self.run_cli("--fixture", "fixtures/replays/demo.json", "--at", "0")
        self.assertEqual(0, result.returncode)
        self.assertEqual("2026-08-28T20:00:30Z", json.loads(result.stdout)["observedAt"])

    def test_malformed_fixture_returns_data_error_without_stdout(self):
        result = self.run_cli("--fixture", "fixtures/replays/malformed.json")
        self.assertEqual(65, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("invalid fixture", result.stderr)

    def test_argument_error_returns_usage_status(self):
        result = self.run_cli("--at", "0")
        self.assertEqual(64, result.returncode)
        self.assertEqual("", result.stdout)

    def test_cache_requires_live_mode(self):
        result = self.run_cli("--fixture", "fixtures/replays/demo.json", "--cache", "cache.json")
        self.assertEqual(64, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("--cache requires --once", result.stderr)


class PerformanceTests(unittest.TestCase):
    def test_ten_thousand_recorded_plays_under_two_seconds(self):
        fixture = load_json("fixtures/raw/scoring_plays.json")
        athlete_index = feed.build_athlete_index(fixture["athletes"])
        raw = fixture["plays"][0]
        started = time.perf_counter()
        for _ in range(10_000):
            result = feed.parse_play(raw, athlete_index)
            self.assertIsInstance(result, feed.AttributedPlay)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 2.0, f"10,000 plays took {elapsed:.3f}s")


if __name__ == "__main__":
    unittest.main()
