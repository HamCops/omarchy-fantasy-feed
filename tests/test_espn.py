from __future__ import annotations

import copy
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import espn
import feed


def load_json(relative_path: str):
    with (ROOT / relative_path).open("r", encoding="utf-8") as stream:
        return json.load(stream)


SCOREBOARD = load_json("fixtures/espn/scoreboard.json")
SUMMARY = load_json("fixtures/espn/summary-game-1.json")
RECEPTION_STATS = load_json("fixtures/espn/play-stat-reception.json")
STATS_URL = espn.normalize_statistics_url(
    SUMMARY["drives"]["previous"][0]["plays"][0]["teamParticipants"][0][
        "playStatistics"
    ]["$ref"]
)


class FakeJson:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        value = self.responses[url]
        if isinstance(value, BaseException):
            raise value
        return copy.deepcopy(value)


def live_fake(scoreboard=None, summary=None, statistics=None):
    return FakeJson(
        {
            espn.SCOREBOARD_URL: scoreboard or SCOREBOARD,
            espn.summary_url("game-1"): summary or SUMMARY,
            STATS_URL: statistics or RECEPTION_STATS,
        }
    )


class ExtractionTests(unittest.TestCase):
    def test_scoreboard_and_string_sequence_are_normalized(self):
        scoreboard = espn.extract_scoreboard(SCOREBOARD)
        self.assertEqual("live", scoreboard["sourceState"])
        self.assertEqual(["game-1"], scoreboard["summaryGameIds"])
        self.assertEqual("BAL", scoreboard["games"][0]["away"])
        plays = espn.extract_plays(SUMMARY, scoreboard["games"][0])
        self.assertEqual(120, plays[0]["sequenceNumber"])
        self.assertIsInstance(plays[0]["sequenceNumber"], int)
        self.assertEqual("CLE", plays[0]["offenseTeam"])
        self.assertEqual(STATS_URL, plays[0]["_statisticsUrl"])

    def test_missing_wallclock_falls_back_to_required_modified_time(self):
        summary = copy.deepcopy(SUMMARY)
        raw_play = summary["drives"]["previous"][0]["plays"][0]
        del raw_play["wallclock"]
        game = espn.extract_scoreboard(SCOREBOARD)["games"][0]
        play = espn.extract_plays(summary, game)[0]
        self.assertEqual(raw_play["modified"], play["wallclock"])

    def test_current_drive_plays_are_extracted_before_the_drive_completes(self):
        summary = copy.deepcopy(SUMMARY)
        current_play = copy.deepcopy(summary["drives"]["previous"][0]["plays"][0])
        current_play["id"] = "play-current"
        current_play["sequenceNumber"] = "122"
        current_play["text"] = "T.Huntley pass complete to J.Cuevas for 9 yards."
        current_play["statYardage"] = 9
        summary["drives"]["current"] = {"plays": [current_play]}
        game = espn.extract_scoreboard(SCOREBOARD)["games"][0]

        plays = espn.extract_plays(summary, game)

        self.assertIn("play-current", [play["id"] for play in plays])
        current = next(play for play in plays if play["id"] == "play-current")
        self.assertEqual(122, current["sequenceNumber"])

    def test_current_to_previous_drive_overlap_keeps_only_current_revision(self):
        summary = copy.deepcopy(SUMMARY)
        current_play = copy.deepcopy(summary["drives"]["previous"][0]["plays"][0])
        current_play["text"] = "T.Huntley pass complete to J.Cuevas for 19 yards."
        current_play["statYardage"] = 19
        current_play["modified"] = "2026-08-28T20:16:30Z"
        summary["drives"]["current"] = {"plays": [current_play]}
        game = espn.extract_scoreboard(SCOREBOARD)["games"][0]

        plays = espn.extract_plays(summary, game)

        overlapping = [play for play in plays if play["id"] == current_play["id"]]
        self.assertEqual(1, len(overlapping))
        self.assertEqual(19, overlapping[0]["statYardage"])

    def test_boxscore_athletes_are_unique_by_stable_id(self):
        athletes = espn.extract_athletes(SUMMARY)
        ids = [athlete["id"] for athlete in athletes]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(1, ids.count("athlete-1"))
        self.assertEqual("CLE", next(a for a in athletes if a["id"] == "athlete-3")["team"])

    def test_week_and_full_boxscore_totals_are_normalized(self):
        scoreboard = espn.extract_scoreboard(SCOREBOARD)
        self.assertEqual(
            {"season": 2026, "seasonType": 2, "number": 1, "label": "Week 1", "detail": "Sep 6-15"},
            scoreboard["week"],
        )
        self.assertEqual("22", scoreboard["games"][0]["awayTeamId"])
        self.assertEqual("33", scoreboard["games"][0]["homeTeamId"])
        rows = espn.extract_weekly_players(SUMMARY, scoreboard["games"][0])
        huntley = next(row for row in rows if row["playerId"] == "athlete-1")
        self.assertEqual(
            {"passing_yards": 100, "passing_touchdown": 1, "interception_thrown": 0, "reception": 1, "receiving_yards": 5, "receiving_touchdown": 0},
            huntley["stats"],
        )
        self.assertEqual(["game-1"], huntley["gameIds"])
        self.assertEqual({"athlete-1": "QB", "athlete-3": "WR"}, espn.extract_leader_positions(SUMMARY))

    def test_roster_positions_keep_only_supported_fantasy_positions(self):
        roster = {
            "athletes": [
                {
                    "position": "offense",
                    "items": [
                        {"id": "qb", "position": {"abbreviation": "QB"}},
                        {"id": "fullback", "position": {"abbreviation": "FB"}},
                        {"id": "center", "position": {"abbreviation": "C"}},
                    ],
                }
            ]
        }
        self.assertEqual({"qb": "QB", "fullback": "RB"}, espn.extract_roster_positions(roster))

    def test_exact_statistics_mapping_ignores_scoring_and_kicking(self):
        self.assertEqual(
            {"passing_yards": 18, "reception": 1, "receiving_yards": 18},
            espn.extract_play_statistics(RECEPTION_STATS),
        )

    def test_duplicate_fumble_sources_map_to_one_loss(self):
        payload = {
            "splits": {
                "categories": [
                    {
                        "name": "passing",
                        "stats": [{"name": "passingFumblesLost", "value": 1}],
                    },
                    {
                        "name": "receiving",
                        "stats": [{"name": "receivingFumblesLost", "value": 1}],
                    },
                ]
            }
        }
        self.assertEqual({"fumble_lost": 1}, espn.extract_play_statistics(payload))

    def test_fumble_loss_must_equal_exactly_one(self):
        payload = {
            "splits": {
                "categories": [
                    {
                        "name": "rushing",
                        "stats": [{"name": "rushingFumblesLost", "value": 2}],
                    }
                ]
            }
        }
        with self.assertRaisesRegex(espn.ProviderError, "must equal one"):
            espn.extract_play_statistics(payload)

    def test_non_integral_supported_stat_is_malformed(self):
        payload = copy.deepcopy(RECEPTION_STATS)
        payload["splits"]["categories"][0]["stats"][0]["value"] = 18.5
        with self.assertRaisesRegex(espn.ProviderError, "integral number"):
            espn.extract_play_statistics(payload)

    def test_statistics_reference_allows_only_verified_private_path(self):
        self.assertTrue(STATS_URL.startswith("https://sports.core.api.espn.com/"))
        rejected = (
            STATS_URL,
            "http://example.com/v2/sports/football/leagues/nfl/events/a/competitions/a/plays/a/teams/a/statistics/0",
            "http://sports.core.api.espn.pvt/v2/sports/basketball/leagues/nfl/events/a/competitions/a/plays/a/teams/a/statistics/0",
            "https://sports.core.api.espn.pvt/v2/sports/football/leagues/nfl/events/a/competitions/a/plays/a/teams/a/statistics/0",
        )
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(espn.ProviderError):
                espn.normalize_statistics_url(value)


class HttpBoundaryTests(unittest.TestCase):
    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_arguments):
            return False

        def read(self, _limit):
            return b'{"events":[]}'

    def test_request_uses_verified_user_agent_and_timeout(self):
        with mock.patch.object(
            espn.urllib.request, "urlopen", return_value=self.Response()
        ) as urlopen:
            self.assertEqual({"events": []}, espn.default_get_json(espn.SCOREBOARD_URL))
        request = urlopen.call_args.args[0]
        self.assertEqual("curl/8.17.0", request.get_header("User-agent"))
        self.assertEqual(espn.REQUEST_TIMEOUT_SECONDS, urlopen.call_args.kwargs["timeout"])

    def test_http_error_reports_status_without_reading_body(self):
        http_error = urllib.error.HTTPError(
            espn.SCOREBOARD_URL,
            403,
            "Forbidden",
            {},
            io.BytesIO(b"provider response body must stay private"),
        )
        self.addCleanup(http_error.close)
        with mock.patch.object(
            espn.urllib.request, "urlopen", side_effect=http_error
        ), self.assertRaises(espn.ProviderError) as raised:
            espn.default_get_json(espn.SCOREBOARD_URL)
        self.assertEqual("http_error", raised.exception.code)
        self.assertEqual("ESPN returned HTTP 403", str(raised.exception))
        self.assertNotIn("provider response body", str(raised.exception))


class OrchestrationTests(unittest.TestCase):
    def test_live_collection_uses_normalized_fixture_boundary(self):
        fake = live_fake()
        fixture = espn.collect_live(
            get_json=fake, observed_at="2026-08-28T20:16:00Z"
        )
        self.assertEqual(1, len(fixture["frames"]))
        self.assertEqual("live", fixture["frames"][0]["sourceState"])
        self.assertEqual(["play-1", "play-timeout"], [p["id"] for p in fixture["frames"][0]["plays"]])
        supported = fixture["frames"][0]["plays"][0]
        self.assertEqual(120, supported["sequenceNumber"])
        self.assertEqual(18, supported["officialStats"]["passing_yards"])
        self.assertEqual("Week 1", fixture["frames"][0]["week"]["label"])
        self.assertEqual(2, len(fixture["frames"][0]["weeklyPlayers"]))
        self.assertEqual(
            ["game-1"], fixture["frames"][0]["weeklyPlayers"][0]["gameIds"]
        )
        self.assertNotIn("_statisticsUrl", supported)
        self.assertEqual(
            [espn.SCOREBOARD_URL, espn.summary_url("game-1"), STATS_URL],
            fake.calls,
        )

    def test_unknown_play_never_requests_statistics(self):
        fake = live_fake()
        fixture = espn.collect_live(get_json=fake, observed_at="2026-08-28T20:16:00Z")
        timeout = next(p for p in fixture["frames"][0]["plays"] if p["id"] == "play-timeout")
        self.assertNotIn("officialStats", timeout)
        self.assertEqual(1, sum(url.startswith("https://sports.core") for url in fake.calls))

    def test_cold_snapshot_caps_supported_stat_requests_at_forty(self):
        summary = copy.deepcopy(SUMMARY)
        template = summary["drives"]["previous"][0]["plays"][0]
        plays = []
        stats_by_url = {}
        for index in range(60):
            play = copy.deepcopy(template)
            play["id"] = f"play-{index}"
            play["sequenceNumber"] = str(index)
            play["wallclock"] = f"2026-08-28T20:{index // 60:02d}:{index % 60:02d}Z"
            private_url = (
                "http://sports.core.api.espn.pvt/v2/sports/football/leagues/nfl/"
                f"events/game-1/competitions/game-1/plays/play-{index}/teams/33/statistics/0"
            )
            play["teamParticipants"][0]["playStatistics"]["$ref"] = private_url
            stats_by_url[espn.normalize_statistics_url(private_url)] = RECEPTION_STATS
            plays.append(play)
        summary["drives"]["previous"][0]["plays"] = plays
        responses = {
            espn.SCOREBOARD_URL: SCOREBOARD,
            espn.summary_url("game-1"): summary,
            **stats_by_url,
        }
        fake = FakeJson(responses)
        fixture = espn.collect_live(get_json=fake, observed_at="2026-08-28T20:16:00Z")
        stat_calls = [url for url in fake.calls if url.startswith("https://sports.core")]
        self.assertEqual(espn.MAX_CANDIDATE_PLAYS, len(stat_calls))
        self.assertEqual(espn.MAX_CANDIDATE_PLAYS, len(fixture["frames"][0]["plays"]))
        self.assertEqual("play-20", fixture["frames"][0]["plays"][0]["id"])
        self.assertEqual("play-59", fixture["frames"][0]["plays"][-1]["id"])

    def test_unchanged_source_revision_reuses_event_without_stat_call(self):
        first_fixture = espn.collect_live(
            get_json=live_fake(), observed_at="2026-08-28T20:16:00Z"
        )
        first_snapshot = feed.reduce_frames(first_fixture)
        fake = live_fake()
        second_fixture = espn.collect_live(
            first_snapshot, get_json=fake, observed_at="2026-08-28T20:17:00Z"
        )
        second_snapshot = feed.reconcile_frame(
            first_snapshot,
            second_fixture["athletes"],
            second_fixture["frames"][0],
        )
        self.assertEqual(first_snapshot["events"], second_snapshot["events"])
        self.assertEqual(first_snapshot["skipped"], second_snapshot["skipped"])
        self.assertEqual(
            [espn.SCOREBOARD_URL, espn.summary_url("game-1")], fake.calls
        )

    def test_changed_revision_fetches_stats_and_replaces_event(self):
        first_fixture = espn.collect_live(
            get_json=live_fake(), observed_at="2026-08-28T20:16:00Z"
        )
        first_snapshot = feed.reduce_frames(first_fixture)
        changed_summary = copy.deepcopy(SUMMARY)
        play = changed_summary["drives"]["previous"][0]["plays"][0]
        play["text"] = play["text"].replace("18 yards", "19 yards")
        play["statYardage"] = 19
        play["modified"] = "2026-08-28T20:16:30Z"
        changed_stats = copy.deepcopy(RECEPTION_STATS)
        changed_stats["splits"]["categories"][0]["stats"][0]["value"] = 19
        changed_stats["splits"]["categories"][1]["stats"][1]["value"] = 19
        fake = live_fake(summary=changed_summary, statistics=changed_stats)
        changed_fixture = espn.collect_live(
            first_snapshot, get_json=fake, observed_at="2026-08-28T20:17:00Z"
        )
        snapshot = feed.reconcile_frame(
            first_snapshot,
            changed_fixture["athletes"],
            changed_fixture["frames"][0],
        )
        self.assertEqual(1, len(snapshot["events"]))
        self.assertEqual("corrected", snapshot["events"][0]["lifecycle"])
        self.assertEqual(2.9, snapshot["events"][0]["participants"][1]["points"]["ppr"])
        self.assertIn(STATS_URL, fake.calls)

    def test_malformed_scoreboard_fails_before_summary_calls(self):
        fake = FakeJson({espn.SCOREBOARD_URL: {"events": {}}})
        with self.assertRaisesRegex(espn.ProviderError, "events.*array"):
            espn.collect_live(get_json=fake)
        self.assertEqual([espn.SCOREBOARD_URL], fake.calls)

    def test_scheduled_only_snapshot_does_not_fetch_summary(self):
        scoreboard = copy.deepcopy(SCOREBOARD)
        scoreboard["events"][0]["competitions"][0]["status"]["type"]["state"] = "pre"
        fake = FakeJson({espn.SCOREBOARD_URL: scoreboard})
        fixture = espn.collect_live(
            get_json=fake, observed_at="2026-08-28T18:00:00Z"
        )
        self.assertEqual("scheduled", fixture["frames"][0]["sourceState"])
        self.assertEqual([], fixture["frames"][0]["plays"])
        self.assertEqual([espn.SCOREBOARD_URL], fake.calls)


if __name__ == "__main__":
    unittest.main()
