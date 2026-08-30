#!/usr/bin/env python3
"""Serve deterministic ESPN-shaped NFL data for local Fantasy Feed load tests."""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping


TEAM_ABBREVIATIONS = (
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA",
    "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB",
    "TEN", "WAS",
)
LAST_NAMES = (
    "Archer", "Baker", "Carter", "Dalton", "Ellis", "Foster", "Grant", "Hayes",
    "Irwin", "Jones", "Keller", "Lewis", "Miller", "Nolan", "Owens", "Parker",
    "Reed", "Sawyer", "Turner", "Walker", "Young", "Bennett", "Collins", "Davis",
    "Evans", "Franklin", "Green", "Harris", "King", "Morgan", "Price", "Scott",
)
PLAYER_ROLES = {
    "QB": "Quinn",
    "RB": "Taylor",
    "WR": "Riley",
}
SCOREBOARD_PATH = "/apis/site/v2/sports/football/nfl/scoreboard"
SUMMARY_PATH = "/apis/site/v2/sports/football/nfl/summary"
STATS_PATH = re.compile(
    r"/v2/sports/football/leagues/nfl/events/(?P<game>sim-game-\d{2})/"
    r"competitions/(?P=game)/plays/(?P<play>sim-game-\d{2}-play-(?P<number>\d{4}))/"
    r"teams/(?P<team>sim-team-\d{2})/statistics/0"
)
STATUS_PATH = "/__simulator__/status"


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


class SimulatorState:
    def __init__(self, games: int = 10, max_plays: int = 120, latency_ms: int = 25):
        if games < 1 or games > len(TEAM_ABBREVIATIONS) // 2:
            raise ValueError(f"games must be between 1 and {len(TEAM_ABBREVIATIONS) // 2}")
        if max_plays < 1 or max_plays > 9999:
            raise ValueError("max_plays must be between 1 and 9999")
        if latency_ms < 0 or latency_ms > 5000:
            raise ValueError("latency_ms must be between 0 and 5000")
        self.games = games
        self.max_plays = max_plays
        self.latency_ms = latency_ms
        self.tick = 0
        self.total_requests = 0
        self.active_requests = 0
        self.peak_concurrent_requests = 0
        self._lock = threading.Lock()
        self._base_time = datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)

    def request_started(self) -> None:
        with self._lock:
            self.total_requests += 1
            self.active_requests += 1
            self.peak_concurrent_requests = max(
                self.peak_concurrent_requests, self.active_requests
            )

    def request_finished(self) -> None:
        with self._lock:
            self.active_requests = max(0, self.active_requests - 1)

    def advance(self) -> int:
        with self._lock:
            self.tick = min(self.max_plays, self.tick + 1)
            return self.tick

    def current_tick(self) -> int:
        with self._lock:
            return self.tick

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return {
                "tick": self.tick,
                "games": self.games,
                "maxPlays": self.max_plays,
                "totalRequests": self.total_requests,
                "activeRequests": self.active_requests,
                "peakConcurrentRequests": self.peak_concurrent_requests,
            }

    @staticmethod
    def game_id(game_index: int) -> str:
        return f"sim-game-{game_index + 1:02d}"

    @staticmethod
    def team_id(team_index: int) -> str:
        return f"sim-team-{team_index + 1:02d}"

    @staticmethod
    def athlete_id(team_index: int, position: str) -> str:
        return f"sim-player-{team_index + 1:02d}-{position.lower()}"

    @staticmethod
    def teams_for_game(game_index: int) -> tuple[int, int]:
        return game_index * 2, game_index * 2 + 1

    def athlete(self, team_index: int, position: str) -> dict[str, str]:
        first_name = PLAYER_ROLES[position]
        last_name = LAST_NAMES[team_index]
        return {
            "id": self.athlete_id(team_index, position),
            "firstName": first_name,
            "lastName": last_name,
            "displayName": f"{first_name} {last_name}",
        }

    def game_clock(self, game_index: int, tick: int) -> tuple[int, str]:
        elapsed = (game_index * 95 + max(0, tick) * 37) % (4 * 15 * 60)
        period = elapsed // (15 * 60) + 1
        remaining = 15 * 60 - elapsed % (15 * 60)
        minutes, seconds = divmod(remaining, 60)
        return period, f"{minutes}:{seconds:02d}"

    def scoreboard(self) -> dict[str, Any]:
        tick = self.advance()
        events = []
        for game_index in range(self.games):
            away_index, home_index = self.teams_for_game(game_index)
            period, clock = self.game_clock(game_index, tick)
            events.append(
                {
                    "id": self.game_id(game_index),
                    "date": _timestamp(self._base_time),
                    "competitions": [
                        {
                            "playByPlayAvailable": True,
                            "status": {
                                "period": period,
                                "displayClock": clock,
                                "type": {
                                    "state": "in",
                                    "detail": f"Q{period} {clock}",
                                    "shortDetail": f"Q{period} {clock}",
                                },
                            },
                            "competitors": [
                                {
                                    "homeAway": "away",
                                    "score": str((tick + game_index) // 5 * 3),
                                    "team": {
                                        "id": self.team_id(away_index),
                                        "abbreviation": TEAM_ABBREVIATIONS[away_index],
                                    },
                                },
                                {
                                    "homeAway": "home",
                                    "score": str((tick + game_index + 2) // 6 * 3),
                                    "team": {
                                        "id": self.team_id(home_index),
                                        "abbreviation": TEAM_ABBREVIATIONS[home_index],
                                    },
                                },
                            ],
                        }
                    ],
                }
            )
        return {
            "season": {"type": 2, "year": 2026},
            "week": {"number": 1},
            "events": events,
        }

    def offense_team(self, game_index: int, play_number: int) -> int:
        away_index, home_index = self.teams_for_game(game_index)
        return away_index if (game_index + play_number) % 2 == 0 else home_index

    def play_kind(self, game_index: int, play_number: int) -> str:
        return "pass" if (game_index + play_number) % 3 != 0 else "rush"

    def play_yards(self, game_index: int, play_number: int) -> int:
        if self.play_kind(game_index, play_number) == "rush" and play_number % 4 == 0:
            return -2
        return 4 + (game_index * 3 + play_number * 5) % 18

    def play(self, game_index: int, play_number: int) -> dict[str, Any]:
        game_id = self.game_id(game_index)
        play_id = f"{game_id}-play-{play_number:04d}"
        offense_index = self.offense_team(game_index, play_number)
        away_index, home_index = self.teams_for_game(game_index)
        defense_index = home_index if offense_index == away_index else away_index
        yards = self.play_yards(game_index, play_number)
        period, clock = self.game_clock(game_index, play_number)
        kind = self.play_kind(game_index, play_number)
        quarterback = self.athlete(offense_index, "QB")
        receiver = self.athlete(offense_index, "WR")
        runner = self.athlete(offense_index, "RB")
        if kind == "pass":
            play_type = "Pass Reception"
            text = (
                f"{quarterback['firstName'][0]}.{quarterback['lastName']} pass complete to "
                f"{receiver['firstName'][0]}.{receiver['lastName']} for {yards} yards."
            )
        else:
            play_type = "Rush"
            text = f"{runner['firstName'][0]}.{runner['lastName']} rushes for {yards} yards."
        wallclock = self._base_time + timedelta(
            seconds=play_number * 20, milliseconds=game_index * 25
        )
        return {
            "id": play_id,
            "sequenceNumber": str(play_number * 10 + game_index),
            "type": {"text": play_type},
            "text": text,
            "period": {"number": period},
            "clock": {"displayValue": clock},
            "wallclock": _timestamp(wallclock),
            "modified": _timestamp(wallclock + timedelta(seconds=1)),
            "scoringPlay": False,
            "isPenalty": False,
            "isTurnover": False,
            "statYardage": yards,
            "teamParticipants": [
                {
                    "id": self.team_id(offense_index),
                    "type": "offense",
                    "playStatistics": {
                        "$ref": (
                            "http://sports.core.api.espn.pvt/v2/sports/football/leagues/nfl/"
                            f"events/{game_id}/competitions/{game_id}/plays/{play_id}/"
                            f"teams/{self.team_id(offense_index)}/statistics/0"
                            "?lang=en&region=us"
                        )
                    },
                },
                {"id": self.team_id(defense_index), "type": "defense"},
            ],
        }

    def totals(self, game_index: int, team_index: int, tick: int) -> dict[str, int]:
        totals = {
            "passingYards": 0,
            "passingTouchdowns": 0,
            "interceptions": 0,
            "rushingYards": 0,
            "rushingTouchdowns": 0,
            "receptions": 0,
            "receivingYards": 0,
            "receivingTouchdowns": 0,
        }
        for play_number in range(1, tick + 1):
            if self.offense_team(game_index, play_number) != team_index:
                continue
            yards = self.play_yards(game_index, play_number)
            if self.play_kind(game_index, play_number) == "pass":
                totals["passingYards"] += yards
                totals["receptions"] += 1
                totals["receivingYards"] += yards
            else:
                totals["rushingYards"] += yards
        return totals

    def player_group(self, team_index: int, totals: Mapping[str, int]) -> dict[str, Any]:
        quarterback = self.athlete(team_index, "QB")
        running_back = self.athlete(team_index, "RB")
        receiver = self.athlete(team_index, "WR")
        return {
            "team": {
                "id": self.team_id(team_index),
                "abbreviation": TEAM_ABBREVIATIONS[team_index],
            },
            "statistics": [
                {
                    "name": "passing",
                    "labels": ["YDS", "TD", "INT"],
                    "athletes": [
                        {
                            "athlete": quarterback,
                            "stats": [
                                str(totals["passingYards"]),
                                str(totals["passingTouchdowns"]),
                                str(totals["interceptions"]),
                            ],
                        }
                    ],
                },
                {
                    "name": "rushing",
                    "labels": ["YDS", "TD"],
                    "athletes": [
                        {
                            "athlete": running_back,
                            "stats": [
                                str(totals["rushingYards"]),
                                str(totals["rushingTouchdowns"]),
                            ],
                        }
                    ],
                },
                {
                    "name": "receiving",
                    "labels": ["REC", "YDS", "TD"],
                    "athletes": [
                        {
                            "athlete": receiver,
                            "stats": [
                                str(totals["receptions"]),
                                str(totals["receivingYards"]),
                                str(totals["receivingTouchdowns"]),
                            ],
                        }
                    ],
                },
            ],
        }

    def leaders(self, team_index: int) -> dict[str, Any]:
        categories = []
        for position, category in (
            ("QB", "passingYards"),
            ("RB", "rushingYards"),
            ("WR", "receivingYards"),
        ):
            athlete = self.athlete(team_index, position)
            athlete["position"] = {"abbreviation": position}
            categories.append({"name": category, "leaders": [{"athlete": athlete}]})
        return {
            "team": {
                "id": self.team_id(team_index),
                "abbreviation": TEAM_ABBREVIATIONS[team_index],
            },
            "leaders": categories,
        }

    def summary(self, game_id: str) -> dict[str, Any] | None:
        match = re.fullmatch(r"sim-game-(\d{2})", game_id)
        if match is None:
            return None
        game_index = int(match.group(1)) - 1
        if game_index < 0 or game_index >= self.games:
            return None
        tick = self.current_tick()
        away_index, home_index = self.teams_for_game(game_index)
        return {
            "boxscore": {
                "players": [
                    self.player_group(
                        away_index, self.totals(game_index, away_index, tick)
                    ),
                    self.player_group(
                        home_index, self.totals(game_index, home_index, tick)
                    ),
                ]
            },
            "leaders": [self.leaders(away_index), self.leaders(home_index)],
            "drives": {
                "previous": [],
                "current": {
                    "plays": [
                        self.play(game_index, play_number)
                        for play_number in range(1, tick + 1)
                    ]
                },
            },
        }

    def play_statistics(
        self, game_id: str, play_id: str, play_number: int, team_id: str
    ) -> dict[str, Any] | None:
        match = re.fullmatch(r"sim-game-(\d{2})", game_id)
        if match is None or play_id != f"{game_id}-play-{play_number:04d}":
            return None
        game_index = int(match.group(1)) - 1
        if game_index < 0 or game_index >= self.games:
            return None
        offense_index = self.offense_team(game_index, play_number)
        if team_id != self.team_id(offense_index):
            return None
        yards = self.play_yards(game_index, play_number)
        if self.play_kind(game_index, play_number) == "pass":
            categories = [
                {
                    "name": "passing",
                    "stats": [{"name": "passingYards", "value": yards}],
                },
                {
                    "name": "receiving",
                    "stats": [
                        {"name": "receptions", "value": 1},
                        {"name": "receivingYards", "value": yards},
                    ],
                },
            ]
        else:
            categories = [
                {
                    "name": "rushing",
                    "stats": [{"name": "rushingYards", "value": yards}],
                }
            ]
        return {"splits": {"categories": categories}}


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    games: int = 10,
    max_plays: int = 120,
    latency_ms: int = 25,
    log_ticks: bool = False,
) -> ThreadingHTTPServer:
    state = SimulatorState(games=games, max_plays=max_plays, latency_ms=latency_ms)

    class Handler(BaseHTTPRequestHandler):
        server_version = "FantasyFeedSimulator/1"

        def log_message(self, _format: str, *_arguments: object) -> None:
            return

        def send_json(self, status: int, payload: Mapping[str, Any]) -> None:
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # Normal when a load-test client exits while parallel requests
                # are still completing or the simulator receives Ctrl+C.
                return

        def do_GET(self) -> None:
            state.request_started()
            try:
                if state.latency_ms:
                    time.sleep(state.latency_ms / 1000)
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path == SCOREBOARD_PATH and not parsed.query:
                    payload = state.scoreboard()
                    if log_ticks and (
                        state.current_tick() == 1 or state.current_tick() % 10 == 0
                    ):
                        print(
                            f"simulator tick {state.current_tick()}: "
                            f"{state.games} games, {state.current_tick() * state.games} plays exposed",
                            file=sys.stderr,
                            flush=True,
                        )
                    self.send_json(200, payload)
                    return
                if parsed.path == SUMMARY_PATH:
                    query = urllib.parse.parse_qs(parsed.query)
                    game_values = query.get("event", [])
                    payload = state.summary(game_values[0]) if len(game_values) == 1 else None
                    if payload is not None:
                        self.send_json(200, payload)
                        return
                stats_match = STATS_PATH.fullmatch(parsed.path)
                if stats_match is not None:
                    payload = state.play_statistics(
                        stats_match.group("game"),
                        stats_match.group("play"),
                        int(stats_match.group("number")),
                        stats_match.group("team"),
                    )
                    if payload is not None:
                        self.send_json(200, payload)
                        return
                if parsed.path == STATUS_PATH and not parsed.query:
                    self.send_json(200, state.metrics())
                    return
                self.send_json(404, {"error": "unknown simulator resource"})
            finally:
                state.request_finished()

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.simulator_state = state  # type: ignore[attr-defined]
    return server


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--games", type=_positive_int, default=10)
    parser.add_argument("--max-plays", type=_positive_int, default=120)
    parser.add_argument("--latency-ms", type=int, default=25)
    arguments = parser.parse_args()
    try:
        server = create_server(
            "127.0.0.1",
            arguments.port,
            games=arguments.games,
            max_plays=arguments.max_plays,
            latency_ms=arguments.latency_ms,
            log_ticks=True,
        )
    except (OSError, ValueError) as error:
        print(f"espn_simulator.py: {error}", file=sys.stderr)
        return 64
    print(
        f"Fantasy Feed ESPN simulator listening on http://127.0.0.1:{arguments.port} "
        f"with {arguments.games} live games",
        file=sys.stderr,
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
