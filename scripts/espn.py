#!/usr/bin/env python3
"""Bound the undocumented ESPN NFL JSON API behind normalized fixture frames."""

from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence


SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={}"
ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{}/roster"
REQUEST_TIMEOUT_SECONDS = 5
MAX_WORKERS = 8
MAX_CANDIDATE_PLAYS = 40
MAX_DIAGNOSTIC_PLAYS = 40
# ESPN currently rejects descriptive and browser UAs here, while this stable curl UA succeeds.
USER_AGENT = "curl/8.17.0"

_SCOREBOARD_LIMIT = 2 * 1024 * 1024
_SUMMARY_LIMIT = 6 * 1024 * 1024
_ROSTER_LIMIT = 2 * 1024 * 1024
_PLAY_STATS_LIMIT = 512 * 1024
_PRIVATE_STATS_HOST = "sports.core.api.espn.pvt"
_PUBLIC_STATS_HOST = "sports.core.api.espn.com"
_STATS_PATH = re.compile(
    r"/v2/sports/football/leagues/nfl/events/[A-Za-z0-9_-]+/"
    r"competitions/[A-Za-z0-9_-]+/plays/[A-Za-z0-9_-]+/"
    r"teams/[A-Za-z0-9_-]+/statistics/[0-9]+"
)

# This exact provider set mirrors the narrative families supported by feed.py.
SUPPORTED_PLAY_TYPES = frozenset(
    {
        "Pass Reception",
        "Passing Touchdown",
        "Rush",
        "Rushing Touchdown",
        "Interception",
        "Interception Return",
        "Pass Interception Return",
        "Fumble",
        "Fumble Recovery (Opponent)",
        "Two-point Pass",
        "Two Point Pass",
        "Two-point Rush",
        "Two Point Rush",
    }
)

GetJson = Callable[[str], Mapping[str, Any]]


class ProviderError(RuntimeError):
    """ESPN failed before a trustworthy normalized snapshot was available."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProviderError("malformed_response", f"{path} must be an object")
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ProviderError("malformed_response", f"{path} must be an array")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProviderError("malformed_response", f"{path} must be a non-empty string")
    return value


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ProviderError("malformed_response", f"{path} must be boolean")
    return value


def _integral_number(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderError("malformed_response", f"{path} must be an integral number")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise ProviderError("malformed_response", f"{path} must be an integral number")
    return int(value)


def _sequence(value: Any, path: str) -> int:
    if isinstance(value, str):
        if not value.isascii() or not value.isdigit():
            raise ProviderError("malformed_response", f"{path} must be an integer string")
        return int(value)
    return _integral_number(value, path)


def _response_limit(url: str) -> int:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
        raise ProviderError("invalid_url", "ESPN requests must use an approved HTTPS URL")
    if url == SCOREBOARD_URL:
        return _SCOREBOARD_LIMIT
    if parsed.hostname == "site.api.espn.com" and parsed.path == (
        "/apis/site/v2/sports/football/nfl/summary"
    ):
        query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
        if set(query) == {"event"} and len(query["event"]) == 1 and query["event"][0]:
            return _SUMMARY_LIMIT
    if parsed.hostname == "site.api.espn.com" and re.fullmatch(
        r"/apis/site/v2/sports/football/nfl/teams/[A-Za-z0-9_-]+/roster",
        parsed.path,
    ):
        if not parsed.query:
            return _ROSTER_LIMIT
    if parsed.hostname == _PUBLIC_STATS_HOST and _STATS_PATH.fullmatch(parsed.path):
        return _PLAY_STATS_LIMIT
    raise ProviderError("invalid_url", "ESPN request URL is outside the approved API boundary")


def _fetch_json(url: str, limit: int) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    announced_size = int(content_length)
                except ValueError as error:
                    raise ProviderError(
                        "malformed_response", "ESPN returned an invalid Content-Length"
                    ) from error
                if announced_size > limit:
                    raise ProviderError("response_too_large", "ESPN response exceeded its size cap")
            payload = response.read(limit + 1)
    except ProviderError:
        raise
    except urllib.error.HTTPError as error:
        raise ProviderError("http_error", f"ESPN returned HTTP {error.code}") from error
    except (OSError, urllib.error.URLError) as error:
        raise ProviderError("network_error", f"ESPN request failed: {type(error).__name__}") from error
    if len(payload) > limit:
        raise ProviderError("response_too_large", "ESPN response exceeded its size cap")
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ProviderError("malformed_response", "ESPN response was not valid JSON") from error
    return _object(value, "response")


def default_get_json(url: str) -> Mapping[str, Any]:
    """Fetch one capped ESPN JSON object without credentials."""
    return _fetch_json(url, _response_limit(url))


def normalize_statistics_url(reference: Any) -> str:
    """Convert exactly one private ESPN play-statistics reference to its public host."""
    value = _string(reference, "playStatistics.$ref")
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.netloc != _PRIVATE_STATS_HOST
        or parsed.username
        or parsed.password
        or parsed.port
        or parsed.fragment
        or _STATS_PATH.fullmatch(parsed.path) is None
    ):
        raise ProviderError("invalid_statistics_url", "play statistics reference is not approved")
    return urllib.parse.urlunsplit(
        ("https", _PUBLIC_STATS_HOST, parsed.path, parsed.query, "")
    )


def summary_url(game_id: str) -> str:
    if not game_id or not re.fullmatch(r"[A-Za-z0-9_-]+", game_id):
        raise ProviderError("malformed_response", "game id cannot form a summary URL")
    return SUMMARY_URL.format(urllib.parse.quote(game_id, safe=""))


def roster_url(team_id: str) -> str:
    if not team_id or not re.fullmatch(r"[A-Za-z0-9_-]+", team_id):
        raise ProviderError("malformed_response", "team id cannot form a roster URL")
    return ROSTER_URL.format(urllib.parse.quote(team_id, safe=""))


def _extract_week(root: Mapping[str, Any]) -> dict[str, Any]:
    season = _object(root.get("season"), "scoreboard.season")
    week = _object(root.get("week"), "scoreboard.week")
    season_year = _integral_number(season.get("year"), "scoreboard.season.year")
    season_type = _integral_number(season.get("type"), "scoreboard.season.type")
    week_number = _integral_number(week.get("number"), "scoreboard.week.number")
    label = "Week " + str(week_number)
    detail = ""
    leagues = root.get("leagues", [])
    if isinstance(leagues, list) and leagues and isinstance(leagues[0], Mapping):
        calendar = leagues[0].get("calendar", [])
        if isinstance(calendar, list):
            for period in calendar:
                if not isinstance(period, Mapping) or str(period.get("value", "")) != str(season_type):
                    continue
                entries = period.get("entries", [])
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, Mapping) or str(entry.get("value", "")) != str(week_number):
                        continue
                    if isinstance(entry.get("label"), str) and entry["label"]:
                        label = entry["label"]
                    if isinstance(entry.get("detail"), str):
                        detail = entry["detail"]
                    break
    return {
        "season": season_year,
        "seasonType": season_type,
        "number": week_number,
        "label": label,
        "detail": detail,
    }


def _team_abbreviation(competitor: Mapping[str, Any], path: str) -> str:
    team = _object(competitor.get("team"), f"{path}.team")
    return _string(team.get("abbreviation"), f"{path}.team.abbreviation")


def extract_scoreboard(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Extract normalized games and the game IDs eligible for summary requests."""
    root = _object(payload, "scoreboard")
    events = _array(root.get("events"), "scoreboard.events")
    week = _extract_week(root)
    games: list[dict[str, Any]] = []
    summary_game_ids: list[str] = []
    provider_states: list[str] = []

    for event_index, event_value in enumerate(events):
        event_path = f"scoreboard.events[{event_index}]"
        event = _object(event_value, event_path)
        game_id = _string(event.get("id"), f"{event_path}.id")
        competitions = _array(event.get("competitions"), f"{event_path}.competitions")
        if not competitions:
            raise ProviderError("malformed_response", f"{event_path}.competitions is empty")
        competition = _object(competitions[0], f"{event_path}.competitions[0]")
        status = _object(competition.get("status", event.get("status")), f"{event_path}.status")
        status_type = _object(status.get("type"), f"{event_path}.status.type")
        provider_state = _string(status_type.get("state"), f"{event_path}.status.type.state")
        if provider_state not in {"pre", "in", "post"}:
            raise ProviderError("malformed_response", f"{event_path} has an unknown game state")
        provider_states.append(provider_state)

        competitors = _array(competition.get("competitors"), f"{event_path}.competitors")
        by_side: dict[str, Mapping[str, Any]] = {}
        for competitor_index, competitor_value in enumerate(competitors):
            competitor = _object(
                competitor_value, f"{event_path}.competitors[{competitor_index}]"
            )
            side = _string(
                competitor.get("homeAway"),
                f"{event_path}.competitors[{competitor_index}].homeAway",
            )
            if side in {"away", "home"}:
                by_side[side] = competitor
        if set(by_side) != {"away", "home"}:
            raise ProviderError("malformed_response", f"{event_path} lacks home or away team")

        state = {"pre": "scheduled", "in": "live", "post": "final"}[provider_state]
        possession = ""
        is_red_zone = False
        down_distance = ""
        situation = competition.get("situation")
        if isinstance(situation, Mapping):
            possession_id = situation.get("possession")
            if isinstance(possession_id, (str, int)) and not isinstance(possession_id, bool):
                possession_text = str(possession_id)
                for side in ("away", "home"):
                    team = by_side[side].get("team")
                    if not isinstance(team, Mapping) or str(team.get("id", "")) != possession_text:
                        continue
                    abbreviation = team.get("abbreviation")
                    if isinstance(abbreviation, str):
                        possession = abbreviation
                    break
            is_red_zone = situation.get("isRedZone") is True
            raw_down_distance = situation.get("downDistanceText")
            if isinstance(raw_down_distance, str):
                down_distance = raw_down_distance
        game = {
            "id": game_id,
            "state": state,
            "startTime": _string(event.get("date"), f"{event_path}.date"),
            "away": _team_abbreviation(by_side["away"], f"{event_path}.away"),
            "home": _team_abbreviation(by_side["home"], f"{event_path}.home"),
            "awayTeamId": _string(
                _object(by_side["away"].get("team"), f"{event_path}.away.team").get("id"),
                f"{event_path}.away.team.id",
            ),
            "homeTeamId": _string(
                _object(by_side["home"].get("team"), f"{event_path}.home.team").get("id"),
                f"{event_path}.home.team.id",
            ),
            "awayScore": str(by_side["away"].get("score", "0")),
            "homeScore": str(by_side["home"].get("score", "0")),
            "detail": str(status_type.get("shortDetail", status_type.get("detail", state))),
            "period": (
                int(status["period"])
                if isinstance(status.get("period"), (int, float))
                and not isinstance(status.get("period"), bool)
                and math.isfinite(status["period"])
                and float(status["period"]).is_integer()
                else 0
            ),
            "clock": (
                status["displayClock"]
                if isinstance(status.get("displayClock"), str)
                else ""
            ),
            "possession": possession,
            "isRedZone": is_red_zone,
            "downDistance": down_distance,
        }
        games.append(game)
        if competition.get("playByPlayAvailable") is True and provider_state in {"in", "post"}:
            summary_game_ids.append(game_id)

    if "in" in provider_states:
        source_state = "live"
    elif "post" in provider_states:
        source_state = "final"
    elif "pre" in provider_states:
        source_state = "scheduled"
    else:
        source_state = "idle"
    return {
        "sourceState": source_state,
        "week": week,
        "games": sorted(games, key=lambda game: game["id"]),
        "summaryGameIds": sorted(set(summary_game_ids)),
    }


def _boxscore_team_map(payload: Mapping[str, Any]) -> dict[str, str]:
    boxscore = _object(payload.get("boxscore"), "summary.boxscore")
    player_groups = _array(boxscore.get("players"), "summary.boxscore.players")
    teams: dict[str, str] = {}
    for group_index, group_value in enumerate(player_groups):
        group = _object(group_value, f"summary.boxscore.players[{group_index}]")
        team = _object(group.get("team"), f"summary.boxscore.players[{group_index}].team")
        team_id = _string(team.get("id"), f"summary.boxscore.players[{group_index}].team.id")
        abbreviation = _string(
            team.get("abbreviation"),
            f"summary.boxscore.players[{group_index}].team.abbreviation",
        )
        known = teams.get(team_id)
        if known is not None and known != abbreviation:
            raise ProviderError("malformed_response", f"team {team_id} has conflicting abbreviations")
        teams[team_id] = abbreviation
    return teams


def extract_athletes(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    """Extract unique structured boxscore athlete identities."""
    boxscore = _object(payload.get("boxscore"), "summary.boxscore")
    player_groups = _array(boxscore.get("players"), "summary.boxscore.players")
    athletes: dict[str, dict[str, str]] = {}
    for group_index, group_value in enumerate(player_groups):
        group_path = f"summary.boxscore.players[{group_index}]"
        group = _object(group_value, group_path)
        team = _object(group.get("team"), f"{group_path}.team")
        abbreviation = _string(team.get("abbreviation"), f"{group_path}.team.abbreviation")
        statistics = _array(group.get("statistics"), f"{group_path}.statistics")
        for stat_index, statistic_value in enumerate(statistics):
            statistic_path = f"{group_path}.statistics[{stat_index}]"
            statistic = _object(statistic_value, statistic_path)
            entries = _array(statistic.get("athletes"), f"{statistic_path}.athletes")
            for entry_index, entry_value in enumerate(entries):
                entry_path = f"{statistic_path}.athletes[{entry_index}]"
                entry = _object(entry_value, entry_path)
                athlete = _object(entry.get("athlete"), f"{entry_path}.athlete")
                normalized = {
                    "id": _string(athlete.get("id"), f"{entry_path}.athlete.id"),
                    "firstName": _string(
                        athlete.get("firstName"), f"{entry_path}.athlete.firstName"
                    ),
                    "lastName": _string(
                        athlete.get("lastName"), f"{entry_path}.athlete.lastName"
                    ),
                    "displayName": _string(
                        athlete.get("displayName"), f"{entry_path}.athlete.displayName"
                    ),
                    "team": abbreviation,
                }
                known = athletes.get(normalized["id"])
                if known is not None and known != normalized:
                    raise ProviderError(
                        "malformed_response",
                        f"athlete {normalized['id']} has conflicting boxscore identities",
                    )
                athletes[normalized["id"]] = normalized
    return sorted(athletes.values(), key=lambda athlete: (athlete["team"], athlete["id"]))


def _offense_participant(
    raw: Mapping[str, Any], team_by_id: Mapping[str, str]
) -> tuple[str | None, str | None, str | None]:
    participants = raw.get("teamParticipants", [])
    if not isinstance(participants, list):
        return None, None, "provider_invalid_team_participants"
    offense = [
        participant
        for participant in participants
        if isinstance(participant, Mapping) and participant.get("type") == "offense"
    ]
    if len(offense) != 1:
        return None, None, "provider_missing_offense"
    team_id = offense[0].get("id")
    if not isinstance(team_id, str) or team_id not in team_by_id:
        return None, None, "provider_unknown_offense_team"
    play_statistics = offense[0].get("playStatistics")
    if not isinstance(play_statistics, Mapping) or "$ref" not in play_statistics:
        return team_by_id[team_id], None, "provider_missing_play_statistics"
    try:
        statistics_url = normalize_statistics_url(play_statistics["$ref"])
    except ProviderError:
        return team_by_id[team_id], None, "provider_invalid_play_statistics"
    return team_by_id[team_id], statistics_url, None


def _source_revision(play: Mapping[str, Any]) -> str:
    semantic = {
        key: play.get(key)
        for key in (
            "provider",
            "gameId",
            "id",
            "sequenceNumber",
            "type",
            "text",
            "period",
            "clock",
            "wallclock",
            "modified",
            "away",
            "home",
            "offenseTeam",
            "scoringPlay",
            "isPenalty",
            "isTurnover",
            "noPlay",
            "statYardage",
            "providerRejectReason",
        )
    }
    encoded = json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"{play['modified']}:{digest}"


def extract_plays(payload: Mapping[str, Any], game: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract provider-neutral play candidates while retaining private fetch metadata."""
    team_by_id = _boxscore_team_map(payload)
    drives = payload.get("drives", {})
    if drives is None:
        drives = {}
    drives = _object(drives, "summary.drives")
    previous = drives.get("previous", [])
    if previous is None:
        previous = []
    drive_values = _array(previous, "summary.drives.previous")
    drive_entries: list[tuple[str, Mapping[str, Any]]] = []
    for drive_index, drive_value in enumerate(drive_values):
        drive_path = f"summary.drives.previous[{drive_index}]"
        drive_entries.append((drive_path, _object(drive_value, drive_path)))

    # ESPN keeps the drive in progress outside `previous`. Reading only the
    # completed-drive array delays every play until the possession ends.
    current_value = drives.get("current")
    if current_value is not None:
        drive_entries.append(
            ("summary.drives.current", _object(current_value, "summary.drives.current"))
        )

    plays: list[dict[str, Any]] = []
    for drive_path, drive in drive_entries:
        raw_plays = _array(drive.get("plays", []), f"{drive_path}.plays")
        for play_index, raw_value in enumerate(raw_plays):
            play_path = f"{drive_path}.plays[{play_index}]"
            raw = _object(raw_value, play_path)
            play_type = _object(raw.get("type"), f"{play_path}.type")
            type_name = _string(play_type.get("text"), f"{play_path}.type.text")
            text = _string(raw.get("text"), f"{play_path}.text")
            period = _object(raw.get("period"), f"{play_path}.period")
            clock = _object(raw.get("clock"), f"{play_path}.clock")
            is_penalty = _boolean(raw.get("isPenalty"), f"{play_path}.isPenalty")
            no_play = is_penalty and "no play" in text.casefold()
            modified = _string(raw.get("modified"), f"{play_path}.modified")
            raw_wallclock = raw.get("wallclock")
            wallclock = raw_wallclock if isinstance(raw_wallclock, str) and raw_wallclock else modified
            offense_team: str | None = None
            statistics_url: str | None = None
            provider_issue: str | None = None
            if type_name in SUPPORTED_PLAY_TYPES and not no_play:
                offense_team, statistics_url, provider_issue = _offense_participant(
                    raw, team_by_id
                )
            normalized: dict[str, Any] = {
                "provider": "espn",
                "gameId": _string(game.get("id"), "game.id"),
                "id": _string(raw.get("id"), f"{play_path}.id"),
                "sequenceNumber": _sequence(
                    raw.get("sequenceNumber"), f"{play_path}.sequenceNumber"
                ),
                "type": {"text": type_name},
                "text": text,
                "period": {
                    "number": _integral_number(
                        period.get("number"), f"{play_path}.period.number"
                    )
                },
                "clock": {
                    "displayValue": _string(
                        clock.get("displayValue"), f"{play_path}.clock.displayValue"
                    )
                },
                "wallclock": wallclock,
                "modified": modified,
                "away": _string(game.get("away"), "game.away"),
                "home": _string(game.get("home"), "game.home"),
                "scoringPlay": _boolean(
                    raw.get("scoringPlay"), f"{play_path}.scoringPlay"
                ),
                "isPenalty": is_penalty,
                "isTurnover": _boolean(
                    raw.get("isTurnover"), f"{play_path}.isTurnover"
                ),
                "noPlay": no_play,
                "statYardage": _integral_number(
                    raw.get("statYardage"), f"{play_path}.statYardage"
                ),
                "_supportedCandidate": type_name in SUPPORTED_PLAY_TYPES and not no_play,
            }
            if offense_team is not None:
                normalized["offenseTeam"] = offense_team
            if statistics_url is not None:
                normalized["_statisticsUrl"] = statistics_url
            if provider_issue is not None:
                normalized["providerRejectReason"] = provider_issue
            normalized["providerRevision"] = _source_revision(normalized)
            plays.append(normalized)

    # During the provider's current-to-previous transition the same play can
    # briefly exist in both collections. Current is processed last, so its
    # newest revision wins without emitting a duplicate fantasy event.
    by_play_id: dict[str, dict[str, Any]] = {}
    for play in plays:
        by_play_id[play["id"]] = play
    return list(by_play_id.values())


_STAT_MAP: Mapping[str, Mapping[str, str]] = {
    "passing": {
        "passingYards": "passing_yards",
        "passingTouchdowns": "passing_touchdown",
        "interceptions": "interception_thrown",
        "twoPointPassConvs": "passing_two_point_conversion",
        "passingFumblesLost": "fumble_lost",
    },
    "rushing": {
        "rushingYards": "rushing_yards",
        "rushingTouchdowns": "rushing_touchdown",
        "twoPointRushConvs": "rushing_two_point_conversion",
        "rushingFumblesLost": "fumble_lost",
    },
    "receiving": {
        "receptions": "reception",
        "receivingYards": "receiving_yards",
        "receivingTouchdowns": "receiving_touchdown",
        "twoPointRecConvs": "receiving_two_point_conversion",
        "receivingFumblesLost": "fumble_lost",
    },
}


def extract_play_statistics(payload: Mapping[str, Any]) -> dict[str, int]:
    """Map only exact supported category and stat names from one play response."""
    root = _object(payload, "playStatistics")
    splits = _object(root.get("splits"), "playStatistics.splits")
    categories = _array(splits.get("categories"), "playStatistics.splits.categories")
    result: dict[str, int] = {}
    fumble_lost = False
    for category_index, category_value in enumerate(categories):
        category_path = f"playStatistics.splits.categories[{category_index}]"
        category = _object(category_value, category_path)
        name = category.get("name")
        mapping = _STAT_MAP.get(name) if isinstance(name, str) else None
        if mapping is None:
            continue
        stats = _array(category.get("stats"), f"{category_path}.stats")
        for stat_index, stat_value in enumerate(stats):
            stat_path = f"{category_path}.stats[{stat_index}]"
            stat = _object(stat_value, stat_path)
            provider_name = stat.get("name")
            normalized_name = mapping.get(provider_name) if isinstance(provider_name, str) else None
            if normalized_name is None:
                continue
            amount = _integral_number(stat.get("value"), f"{stat_path}.value")
            if amount == 0:
                continue
            if normalized_name == "fumble_lost":
                if amount != 1:
                    raise ProviderError(
                        "malformed_response", "fumble-lost play statistic must equal one"
                    )
                fumble_lost = True
                continue
            if normalized_name in result:
                raise ProviderError(
                    "malformed_response", f"duplicate supported play statistic {provider_name}"
                )
            result[normalized_name] = amount
    if fumble_lost:
        result["fumble_lost"] = 1
    return dict(sorted(result.items()))


_BOX_SCORE_STAT_MAP: Mapping[str, Mapping[str, str]] = {
    "passing": {
        "YDS": "passing_yards",
        "TD": "passing_touchdown",
        "INT": "interception_thrown",
    },
    "rushing": {
        "YDS": "rushing_yards",
        "TD": "rushing_touchdown",
    },
    "receiving": {
        "REC": "reception",
        "YDS": "receiving_yards",
        "TD": "receiving_touchdown",
    },
    "fumbles": {"LOST": "fumble_lost"},
}
_FANTASY_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})


def _fantasy_position(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    position = value.upper()
    if position in {"HB", "FB"}:
        return "RB"
    return position if position in _FANTASY_POSITIONS else ""


def extract_leader_positions(payload: Mapping[str, Any]) -> dict[str, str]:
    """Use summary leaders as a free position hint before requesting a roster."""
    positions: dict[str, str] = {}
    leaders = payload.get("leaders", [])
    if not isinstance(leaders, list):
        return positions
    for team in leaders:
        if not isinstance(team, Mapping) or not isinstance(team.get("leaders"), list):
            continue
        for category in team["leaders"]:
            if not isinstance(category, Mapping) or not isinstance(category.get("leaders"), list):
                continue
            for entry in category["leaders"]:
                if not isinstance(entry, Mapping) or not isinstance(entry.get("athlete"), Mapping):
                    continue
                athlete = entry["athlete"]
                position = athlete.get("position", {})
                normalized = _fantasy_position(
                    position.get("abbreviation") if isinstance(position, Mapping) else ""
                )
                player_id = athlete.get("id")
                if normalized and isinstance(player_id, str) and player_id:
                    positions[player_id] = normalized
    return positions


def extract_roster_positions(payload: Mapping[str, Any]) -> dict[str, str]:
    root = _object(payload, "roster")
    groups = _array(root.get("athletes"), "roster.athletes")
    positions: dict[str, str] = {}
    for group_index, group_value in enumerate(groups):
        group = _object(group_value, f"roster.athletes[{group_index}]")
        items = _array(group.get("items"), f"roster.athletes[{group_index}].items")
        for item_index, item_value in enumerate(items):
            path = f"roster.athletes[{group_index}].items[{item_index}]"
            item = _object(item_value, path)
            position = item.get("position", {})
            normalized = _fantasy_position(
                position.get("abbreviation") if isinstance(position, Mapping) else ""
            )
            if not normalized:
                continue
            player_id = _string(item.get("id"), f"{path}.id")
            known = positions.get(player_id)
            if known is not None and known != normalized:
                raise ProviderError(
                    "malformed_response", f"athlete {player_id} has conflicting roster positions"
                )
            positions[player_id] = normalized
    return positions


def extract_weekly_players(
    payload: Mapping[str, Any], game: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Extract complete supported player totals from one structured box score."""
    boxscore = _object(payload.get("boxscore"), "summary.boxscore")
    player_groups = _array(boxscore.get("players"), "summary.boxscore.players")
    game_id = _string(game.get("id"), "game.id")
    rows: dict[str, dict[str, Any]] = {}
    for group_index, group_value in enumerate(player_groups):
        group_path = f"summary.boxscore.players[{group_index}]"
        group = _object(group_value, group_path)
        team = _object(group.get("team"), f"{group_path}.team")
        team_id = _string(team.get("id"), f"{group_path}.team.id")
        abbreviation = _string(team.get("abbreviation"), f"{group_path}.team.abbreviation")
        statistics = _array(group.get("statistics"), f"{group_path}.statistics")
        for statistic_index, statistic_value in enumerate(statistics):
            statistic_path = f"{group_path}.statistics[{statistic_index}]"
            statistic = _object(statistic_value, statistic_path)
            name = statistic.get("name")
            mapping = _BOX_SCORE_STAT_MAP.get(name) if isinstance(name, str) else None
            if mapping is None:
                continue
            labels = _array(statistic.get("labels"), f"{statistic_path}.labels")
            label_indexes = {
                label: index for index, label in enumerate(labels) if isinstance(label, str)
            }
            for required_label in mapping:
                if required_label not in label_indexes:
                    raise ProviderError(
                        "malformed_response",
                        f"{statistic_path}.labels lacks {required_label}",
                    )
            entries = _array(statistic.get("athletes"), f"{statistic_path}.athletes")
            for entry_index, entry_value in enumerate(entries):
                entry_path = f"{statistic_path}.athletes[{entry_index}]"
                entry = _object(entry_value, entry_path)
                athlete = _object(entry.get("athlete"), f"{entry_path}.athlete")
                player_id = _string(athlete.get("id"), f"{entry_path}.athlete.id")
                display_name = _string(
                    athlete.get("displayName"), f"{entry_path}.athlete.displayName"
                )
                values = _array(entry.get("stats"), f"{entry_path}.stats")
                row = rows.setdefault(
                    player_id,
                    {
                        "playerId": player_id,
                        "displayName": display_name,
                        "team": abbreviation,
                        "teamId": team_id,
                        "gameIds": [game_id],
                        "stats": {},
                    },
                )
                if row["displayName"] != display_name or row["team"] != abbreviation:
                    raise ProviderError(
                        "malformed_response", f"athlete {player_id} conflicts within a box score"
                    )
                for provider_label, normalized_name in mapping.items():
                    value_index = label_indexes[provider_label]
                    if value_index >= len(values):
                        raise ProviderError(
                            "malformed_response", f"{entry_path}.stats is shorter than labels"
                        )
                    raw_value = values[value_index]
                    try:
                        amount = int(str(raw_value))
                    except (TypeError, ValueError) as error:
                        raise ProviderError(
                            "malformed_response",
                            f"{entry_path}.stats[{value_index}] must be an integer string",
                        ) from error
                    if normalized_name == "fumble_lost":
                        row["stats"][normalized_name] = max(
                            amount, int(row["stats"].get(normalized_name, 0))
                        )
                    else:
                        row["stats"][normalized_name] = (
                            int(row["stats"].get(normalized_name, 0)) + amount
                        )
    return sorted(rows.values(), key=lambda row: (row["team"], row["playerId"]))


def _previous_positions(snapshot: Mapping[str, Any] | None) -> dict[str, str]:
    positions: dict[str, str] = {}
    if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("leaderboard"), list):
        return positions
    for row in snapshot["leaderboard"]:
        if not isinstance(row, Mapping):
            continue
        player_id = row.get("playerId")
        position = _fantasy_position(row.get("position"))
        if isinstance(player_id, str) and player_id and position:
            positions[player_id] = position
    return positions


def _aggregate_weekly_players(
    game_rows: Sequence[Mapping[str, Any]], positions: Mapping[str, str]
) -> list[dict[str, Any]]:
    players: dict[str, dict[str, Any]] = {}
    for raw in game_rows:
        player_id = str(raw["playerId"])
        position = positions.get(player_id, "")
        if position not in _FANTASY_POSITIONS:
            continue
        known = players.get(player_id)
        if known is None:
            known = {
                "playerId": player_id,
                "displayName": str(raw["displayName"]),
                "team": str(raw["team"]),
                "position": position,
                "gameIds": set(),
                "stats": {},
            }
            players[player_id] = known
        if (
            known["displayName"] != raw["displayName"]
            or known["team"] != raw["team"]
            or known["position"] != position
        ):
            raise ProviderError(
                "malformed_response", f"athlete {player_id} conflicts across weekly games"
            )
        known["gameIds"].update(raw["gameIds"])
        for key, value in raw["stats"].items():
            known["stats"][key] = int(known["stats"].get(key, 0)) + int(value)
    result: list[dict[str, Any]] = []
    for player in players.values():
        result.append(
            {
                "playerId": player["playerId"],
                "displayName": player["displayName"],
                "team": player["team"],
                "position": player["position"],
                "games": len(player["gameIds"]),
                "gameIds": sorted(player["gameIds"]),
                "stats": dict(sorted(player["stats"].items())),
            }
        )
    return sorted(result, key=lambda row: (row["position"], row["team"], row["playerId"]))


def _fetch_many(urls: Sequence[str], get_json: GetJson) -> dict[str, Mapping[str, Any]]:
    unique_urls = tuple(sorted(set(urls)))
    if not unique_urls:
        return {}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(unique_urls))) as executor:
        futures = {url: executor.submit(get_json, url) for url in unique_urls}
        results: dict[str, Mapping[str, Any]] = {}
        for url in unique_urls:
            try:
                value = futures[url].result()
            except ProviderError:
                raise
            except Exception as error:
                raise ProviderError(
                    "network_error", f"injected ESPN request failed: {type(error).__name__}"
                ) from error
            results[url] = _object(value, "response")
        return results


def _known_source_revisions(snapshot: Mapping[str, Any] | None) -> dict[tuple[str, str, str], str]:
    known: dict[tuple[str, str, str], str] = {}
    if not isinstance(snapshot, Mapping):
        return known
    for collection_name in ("skipped", "events"):
        collection = snapshot.get(collection_name, [])
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, Mapping):
                continue
            key = (item.get("provider"), item.get("gameId"), item.get("playId"))
            revision = item.get("sourceRevision")
            if all(isinstance(part, str) and part for part in key) and isinstance(revision, str):
                known[key] = revision
    return known


def _play_order(play: Mapping[str, Any]) -> tuple[str, str, int, str]:
    return (
        str(play.get("wallclock", "")),
        str(play.get("gameId", "")),
        int(play.get("sequenceNumber", 0)),
        str(play.get("id", "")),
    )


def collect_live(
    previous_snapshot: Mapping[str, Any] | None = None,
    *,
    get_json: GetJson | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Fetch one live provider observation as the same fixture shape used by replay."""
    request_json = get_json or default_get_json
    scoreboard = extract_scoreboard(request_json(SCOREBOARD_URL))
    games = scoreboard["games"]
    games_by_id = {game["id"]: game for game in games}
    summary_urls = [summary_url(game_id) for game_id in scoreboard["summaryGameIds"]]
    summaries = _fetch_many(summary_urls, request_json)

    athletes_by_id: dict[str, dict[str, str]] = {}
    extracted_plays: list[dict[str, Any]] = []
    weekly_game_rows: list[dict[str, Any]] = []
    positions = _previous_positions(previous_snapshot)
    for game_id in scoreboard["summaryGameIds"]:
        payload = summaries[summary_url(game_id)]
        positions.update(extract_leader_positions(payload))
        for athlete in extract_athletes(payload):
            known = athletes_by_id.get(athlete["id"])
            if known is not None and known != athlete:
                raise ProviderError(
                    "malformed_response", f"athlete {athlete['id']} conflicts across games"
                )
            athletes_by_id[athlete["id"]] = athlete
        extracted_plays.extend(extract_plays(payload, games_by_id[game_id]))
        weekly_game_rows.extend(extract_weekly_players(payload, games_by_id[game_id]))

    missing_team_ids = sorted(
        {
            str(row["teamId"])
            for row in weekly_game_rows
            if str(row["playerId"]) not in positions
        }
    )
    roster_payloads = _fetch_many(
        [roster_url(team_id) for team_id in missing_team_ids], request_json
    )
    for team_id in missing_team_ids:
        positions.update(extract_roster_positions(roster_payloads[roster_url(team_id)]))
    weekly_players = _aggregate_weekly_players(weekly_game_rows, positions)

    known_revisions = _known_source_revisions(previous_snapshot)
    supported_window: list[dict[str, Any]] = []
    diagnostic_window: list[dict[str, Any]] = []
    for play in extracted_plays:
        if play.pop("_supportedCandidate"):
            supported_window.append(play)
        else:
            diagnostic_window.append(play)

    # Bound the provider window before comparing revisions. Once the public
    # event cache reaches its own cap, older evicted plays must not re-enter as
    # apparently unseen candidates and consume stat requests every refresh.
    supported_window = sorted(supported_window, key=_play_order, reverse=True)[
        :MAX_CANDIDATE_PLAYS
    ]
    diagnostic_window = sorted(diagnostic_window, key=_play_order, reverse=True)[
        :MAX_DIAGNOSTIC_PLAYS
    ]
    supported = [
        play
        for play in supported_window
        if known_revisions.get((play["provider"], play["gameId"], play["id"]))
        != play["providerRevision"]
    ]
    diagnostics = [
        play
        for play in diagnostic_window
        if known_revisions.get((play["provider"], play["gameId"], play["id"]))
        != play["providerRevision"]
    ]
    stat_urls = [
        play["_statisticsUrl"]
        for play in supported
        if "_statisticsUrl" in play and "providerRejectReason" not in play
    ]
    statistic_payloads = _fetch_many(stat_urls, request_json)
    for play in supported:
        statistics_url = play.pop("_statisticsUrl", None)
        if statistics_url is not None and "providerRejectReason" not in play:
            play["officialStats"] = extract_play_statistics(statistic_payloads[statistics_url])
    for play in diagnostics:
        play.pop("_statisticsUrl", None)

    frame_plays = sorted(supported + diagnostics, key=_play_order)
    timestamp = observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "fixtureVersion": 1,
        "athletes": sorted(
            athletes_by_id.values(), key=lambda athlete: (athlete["team"], athlete["id"])
        ),
        "frames": [
            {
                "observedAt": timestamp,
                "sourceState": scoreboard["sourceState"],
                "stale": False,
                "week": scoreboard["week"],
                "games": games,
                "weeklyPlayers": weekly_players,
                "plays": frame_plays,
            }
        ],
    }
