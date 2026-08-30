#!/usr/bin/env python3
"""Normalize recorded NFL plays into a deterministic fantasy feed snapshot."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence, TypeAlias

import espn


SCHEMA_VERSION = 1
PARSER_VERSION = "espn-narrative-v1"
DEFAULT_EVENT_CAP = 200
DEFAULT_SKIPPED_CAP = 200
SOURCE_STATES = {"live", "scheduled", "final", "idle", "offline", "malformed"}

# Values are integer hundredths per stat unit. This is the only scoring table.
SCORING_TABLE: Mapping[str, tuple[int, int]] = {
    "passing_yards": (4, 4),
    "passing_touchdown": (400, 400),
    "interception_thrown": (-200, -200),
    "rushing_yards": (10, 10),
    "rushing_touchdown": (600, 600),
    "reception": (100, 0),
    "receiving_yards": (10, 10),
    "receiving_touchdown": (600, 600),
    "passing_two_point_conversion": (200, 200),
    "rushing_two_point_conversion": (200, 200),
    "receiving_two_point_conversion": (200, 200),
    "fumble_lost": (-200, -200),
}


class FixtureError(ValueError):
    """The fixture cannot be interpreted without guessing."""


class UsageError(ValueError):
    """The command line does not describe one supported operation."""


@dataclass(frozen=True, slots=True)
class PlayKey:
    provider: str
    game_id: str
    play_id: str


@dataclass(frozen=True, slots=True)
class StatDelta:
    key: str
    value: int
    label: str


@dataclass(frozen=True, slots=True)
class PlayerDelta:
    player_id: str | None
    display_name: str
    team: str
    role: str
    stats: tuple[StatDelta, ...]
    ppr_hundredths: int
    standard_hundredths: int


@dataclass(frozen=True, slots=True)
class AttributedPlay:
    key: PlayKey
    revision: str
    source_revision: str
    provider_modified: str
    semantic_hash: str
    sequence: int
    quarter: int
    clock: str
    wallclock: str
    away: str
    home: str
    raw_text: str
    kind: str
    participants: tuple[PlayerDelta, ...]
    attribution: str
    parser_version: str


@dataclass(frozen=True, slots=True)
class RejectedPlay:
    key: PlayKey
    revision: str
    source_revision: str
    provider_modified: str
    semantic_hash: str
    sequence: int
    quarter: int
    clock: str
    wallclock: str
    away: str
    home: str
    raw_text: str
    reason: str
    parser_version: str


PlayResult: TypeAlias = AttributedPlay | RejectedPlay
AthleteIndex: TypeAlias = Mapping[tuple[str, str], tuple[tuple[str, str], ...]]


@dataclass(frozen=True, slots=True)
class _Candidate:
    kind: str
    participants: tuple[PlayerDelta, ...]
    expected_flags: Mapping[str, bool]
    stat_yardage: int | None


def score_stats(stats: Iterable[StatDelta]) -> tuple[int, int]:
    """Return PPR and standard points as exact integer hundredths."""
    ppr = 0
    standard = 0
    for stat in stats:
        try:
            ppr_rate, standard_rate = SCORING_TABLE[stat.key]
        except KeyError as error:
            raise ValueError(f"unsupported scoring stat: {stat.key}") from error
        ppr += ppr_rate * stat.value
        standard += standard_rate * stat.value
    return ppr, standard


def _player(
    name: str,
    team: str,
    role: str,
    stats: Sequence[StatDelta],
    player_id: str | None = None,
) -> PlayerDelta:
    frozen_stats = tuple(stats)
    ppr, standard = score_stats(frozen_stats)
    return PlayerDelta(player_id, name, team, role, frozen_stats, ppr, standard)


def _points(hundredths: int) -> float:
    return hundredths / 100.0


def stat_delta(key: str, value: int) -> StatDelta:
    """Construct a supported stat with its stable display label."""
    labels: Mapping[str, str] = {
        "passing_yards": f"{value} PASS YDS",
        "passing_touchdown": "PASS TD",
        "interception_thrown": "INT THROWN",
        "rushing_yards": f"{value} RUSH YDS",
        "rushing_touchdown": "RUSH TD",
        "reception": "REC" if value == 1 else f"{value} REC",
        "receiving_yards": f"{value} REC YDS",
        "receiving_touchdown": "REC TD",
        "passing_two_point_conversion": "PASS 2PT",
        "rushing_two_point_conversion": "RUSH 2PT",
        "receiving_two_point_conversion": "REC 2PT",
        "fumble_lost": "FUM LOST",
    }
    if key not in SCORING_TABLE:
        raise ValueError(f"unsupported scoring stat: {key}")
    return StatDelta(key, value, labels[key])


_NAME = r"[A-Z]\.[A-Za-z][A-Za-z.'-]*"
_TEAM = r"[A-Z]{2,4}"
_LANE = r"(?:left end|left tackle|left guard|up the middle|right guard|right tackle|right end)"
_PASS_DEPTH = r"(?:(?:short|deep) (?:left|middle|right) )?"
_PASS_LOCATION = rf"(?:(?:pushed ob at|to) {_TEAM} \d+ )?"
_TACKLER = r"(?: \([^()]+\))?"
_PAT = rf"(?: {_NAME} extra point is GOOD(?:, Center-{_NAME}, Holder-{_NAME})?\.)?"


_PASS_RECEPTION_PATTERNS = (
    re.compile(
        rf"(?:\(Shotgun\) )?(?P<passer>{_NAME}) pass {_PASS_DEPTH}to "
        rf"(?P<receiver>{_NAME}) {_PASS_LOCATION}for (?P<yards>-?\d+) "
        rf"yards?{_TACKLER}\."
    ),
    re.compile(
        rf"(?:\(Shotgun\) )?(?P<passer>{_NAME}) pass complete to "
        rf"(?P<receiver>{_NAME}) for (?P<yards>-?\d+) yards?\."
    ),
)

_PASS_NO_GAIN_PATTERN = re.compile(
    rf"(?:\(Shotgun\) )?(?P<passer>{_NAME}) pass {_PASS_DEPTH}to "
    rf"(?P<receiver>{_NAME}) for no gain{_TACKLER}\."
)

_PASS_TOUCHDOWN_PATTERN = re.compile(
    rf"(?:\(Shotgun\) )?(?P<passer>{_NAME}) pass {_PASS_DEPTH}to "
    rf"(?P<receiver>{_NAME}) {_PASS_LOCATION}for (?P<yards>-?\d+) "
    rf"yards?, TOUCHDOWN\.{_PAT}"
)

_RUSH_PATTERNS = (
    re.compile(
        rf"(?P<runner>{_NAME}) {_LANE} (?:to {_TEAM} \d+ )?for "
        rf"(?P<yards>-?\d+) yards?{_TACKLER}\."
    ),
    re.compile(rf"(?P<runner>{_NAME}) rushes for (?P<yards>-?\d+) yards?\."),
)

_SCRAMBLE_PATTERN = re.compile(
    rf"(?P<runner>{_NAME}) scrambles {_LANE} (?:to {_TEAM} \d+ )?for "
    rf"(?P<yards>-?\d+) yards?{_TACKLER}\."
)

_RUSH_TOUCHDOWN_PATTERN = re.compile(
    rf"(?P<runner>{_NAME}) {_LANE} (?:to {_TEAM} \d+ )?for "
    rf"(?P<yards>-?\d+) yards?, TOUCHDOWN\.{_PAT}"
)

_INTERCEPTION_PATTERN = re.compile(
    rf"(?:\(Shotgun\) )?(?P<passer>{_NAME}) pass {_PASS_DEPTH}intended for "
    rf"(?P<receiver>{_NAME}) INTERCEPTED by (?P<defender>{_NAME})"
    rf"(?: at {_TEAM} \d+)?\."
    rf"(?: (?P=defender) pushed ob at {_TEAM} \d+ for -?\d+ yards?{_TACKLER}\.)?"
)

_CATCH_FUMBLE_PATTERN = re.compile(
    rf"(?:\(Shotgun\) )?(?P<passer>{_NAME}) pass {_PASS_DEPTH}to "
    rf"(?P<receiver>{_NAME}) {_PASS_LOCATION}for (?P<yards>-?\d+) "
    rf"yards?{_TACKLER}\. (?P<fumbler>{_NAME}) FUMBLES(?: \([^()]+\))?, "
    rf"RECOVERED by {_TEAM}-{_NAME} at {_TEAM} \d+\."
)

_RUSH_FUMBLE_PATTERN = re.compile(
    rf"(?P<runner>{_NAME}) {_LANE} (?:to {_TEAM} \d+ )?for "
    rf"(?P<yards>-?\d+) yards?{_TACKLER}\. (?P<fumbler>{_NAME}) "
    rf"FUMBLES(?: \([^()]+\))?, RECOVERED by {_TEAM}-{_NAME} at {_TEAM} \d+\."
    rf"(?:  The fumble was assisted by replay\.)?"
)

_PASS_TWO_POINT_PATTERNS = (
    re.compile(
        rf"(?:\(Shotgun\) )?(?P<passer>{_NAME}) pass to (?P<receiver>{_NAME}) "
        rf"is complete for TWO-POINT CONVERSION\."
    ),
    re.compile(
        rf"(?:\(Shotgun\) )?(?P<passer>{_NAME}) pass complete to "
        rf"(?P<receiver>{_NAME}) for TWO-POINT CONVERSION\."
    ),
)

_RUSH_TWO_POINT_PATTERN = re.compile(
    rf"(?P<runner>{_NAME}) (?:rushes )?{_LANE} for TWO-POINT CONVERSION\."
)


def _first_full_match(
    patterns: Sequence[re.Pattern[str]], text: str
) -> re.Match[str] | None:
    for pattern in patterns:
        match = pattern.fullmatch(text)
        if match is not None:
            return match
    return None


def _parse_pass_reception(text: str, team: str) -> _Candidate | None:
    match = _first_full_match(_PASS_RECEPTION_PATTERNS, text)
    if match is not None:
        yards = int(match.group("yards"))
    else:
        match = _PASS_NO_GAIN_PATTERN.fullmatch(text)
        if match is None:
            return None
        yards = 0
    return _Candidate(
        "reception",
        (
            _player(match.group("passer"), team, "quarterback", [stat_delta("passing_yards", yards)]),
            _player(
                match.group("receiver"),
                team,
                "receiver",
                [stat_delta("reception", 1), stat_delta("receiving_yards", yards)],
            ),
        ),
        {"scoringPlay": False, "isTurnover": False},
        yards,
    )


def _parse_passing_touchdown(text: str, team: str) -> _Candidate | None:
    match = _PASS_TOUCHDOWN_PATTERN.fullmatch(text)
    if match is None:
        return None
    yards = int(match.group("yards"))
    return _Candidate(
        "passing_touchdown",
        (
            _player(
                match.group("passer"),
                team,
                "quarterback",
                [stat_delta("passing_yards", yards), stat_delta("passing_touchdown", 1)],
            ),
            _player(
                match.group("receiver"),
                team,
                "receiver",
                [
                    stat_delta("reception", 1),
                    stat_delta("receiving_yards", yards),
                    stat_delta("receiving_touchdown", 1),
                ],
            ),
        ),
        {"scoringPlay": True, "isTurnover": False},
        yards,
    )


def _parse_rush(text: str, team: str) -> _Candidate | None:
    match = _first_full_match(_RUSH_PATTERNS, text)
    if match is None:
        return None
    yards = int(match.group("yards"))
    return _Candidate(
        "rush",
        (_player(match.group("runner"), team, "rusher", [stat_delta("rushing_yards", yards)]),),
        {"scoringPlay": False, "isTurnover": False},
        yards,
    )


def _parse_scramble(text: str, team: str) -> _Candidate | None:
    match = _SCRAMBLE_PATTERN.fullmatch(text)
    if match is None:
        return None
    yards = int(match.group("yards"))
    return _Candidate(
        "rush",
        (_player(match.group("runner"), team, "rusher", [stat_delta("rushing_yards", yards)]),),
        {"scoringPlay": False, "isTurnover": False},
        yards,
    )


def _parse_rushing_touchdown(text: str, team: str) -> _Candidate | None:
    match = _RUSH_TOUCHDOWN_PATTERN.fullmatch(text)
    if match is None:
        return None
    yards = int(match.group("yards"))
    return _Candidate(
        "rushing_touchdown",
        (
            _player(
                match.group("runner"),
                team,
                "rusher",
                [stat_delta("rushing_yards", yards), stat_delta("rushing_touchdown", 1)],
            ),
        ),
        {"scoringPlay": True, "isTurnover": False},
        yards,
    )


def _parse_interception(text: str, team: str) -> _Candidate | None:
    match = _INTERCEPTION_PATTERN.fullmatch(text)
    if match is None:
        return None
    return _Candidate(
        "interception_thrown",
        (
            _player(
                match.group("passer"),
                team,
                "quarterback",
                [stat_delta("interception_thrown", 1)],
            ),
        ),
        {"scoringPlay": False, "isTurnover": True},
        None,
    )


def _parse_catch_fumble(text: str, team: str) -> _Candidate | None:
    match = _CATCH_FUMBLE_PATTERN.fullmatch(text)
    if match is None or match.group("receiver") != match.group("fumbler"):
        return None
    yards = int(match.group("yards"))
    return _Candidate(
        "reception_fumble_lost",
        (
            _player(match.group("passer"), team, "quarterback", [stat_delta("passing_yards", yards)]),
            _player(
                match.group("receiver"),
                team,
                "receiver",
                [
                    stat_delta("reception", 1),
                    stat_delta("receiving_yards", yards),
                    stat_delta("fumble_lost", 1),
                ],
            ),
        ),
        {"scoringPlay": False, "isTurnover": True},
        None,
    )


def _parse_rush_fumble(text: str, team: str) -> _Candidate | None:
    match = _RUSH_FUMBLE_PATTERN.fullmatch(text)
    if match is None or match.group("runner") != match.group("fumbler"):
        return None
    yards = int(match.group("yards"))
    return _Candidate(
        "rush_fumble_lost",
        (
            _player(
                match.group("runner"),
                team,
                "rusher",
                [stat_delta("rushing_yards", yards), stat_delta("fumble_lost", 1)],
            ),
        ),
        {"scoringPlay": False, "isTurnover": True},
        None,
    )


def _parse_passing_two_point(text: str, team: str) -> _Candidate | None:
    match = _first_full_match(_PASS_TWO_POINT_PATTERNS, text)
    if match is None:
        return None
    return _Candidate(
        "passing_two_point_conversion",
        (
            _player(
                match.group("passer"),
                team,
                "quarterback",
                [stat_delta("passing_two_point_conversion", 1)],
            ),
            _player(
                match.group("receiver"),
                team,
                "receiver",
                [stat_delta("receiving_two_point_conversion", 1)],
            ),
        ),
        {"scoringPlay": True, "isTurnover": False},
        0,
    )


def _parse_rushing_two_point(text: str, team: str) -> _Candidate | None:
    match = _RUSH_TWO_POINT_PATTERN.fullmatch(text)
    if match is None:
        return None
    return _Candidate(
        "rushing_two_point_conversion",
        (
            _player(
                match.group("runner"),
                team,
                "rusher",
                [stat_delta("rushing_two_point_conversion", 1)],
            ),
        ),
        {"scoringPlay": True, "isTurnover": False},
        0,
    )


Parser = Callable[[str, str], _Candidate | None]

# Exact provider type names are the first parser boundary. Order matters for fumbles.
PARSER_REGISTRY: Mapping[str, tuple[Parser, ...]] = {
    "Pass Reception": (_parse_catch_fumble, _parse_pass_reception),
    "Passing Touchdown": (_parse_passing_touchdown,),
    "Rush": (_parse_rush_fumble, _parse_scramble, _parse_rush),
    "Rushing Touchdown": (_parse_rushing_touchdown,),
    "Interception": (_parse_interception,),
    "Interception Return": (_parse_interception,),
    "Pass Interception Return": (_parse_interception,),
    "Fumble": (_parse_catch_fumble, _parse_rush_fumble),
    "Fumble Recovery (Opponent)": (_parse_catch_fumble, _parse_rush_fumble),
    "Two-point Pass": (_parse_passing_two_point,),
    "Two Point Pass": (_parse_passing_two_point,),
    "Two-point Rush": (_parse_rushing_two_point,),
    "Two Point Rush": (_parse_rushing_two_point,),
}


def _required_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise FixtureError(f"{path} must be a non-empty string")
    return value


def _required_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FixtureError(f"{path} must be an integer")
    return value


def _play_key(raw: Mapping[str, Any]) -> PlayKey:
    return PlayKey(
        _required_string(raw.get("provider"), "play.provider"),
        _required_string(raw.get("gameId"), "play.gameId"),
        _required_string(raw.get("id"), "play.id"),
    )


def _semantic_hash(raw: Mapping[str, Any]) -> str:
    semantic = {
        key: raw.get(key)
        for key in (
            "provider",
            "gameId",
            "id",
            "sequenceNumber",
            "type",
            "text",
            "period",
            "clock",
            "away",
            "home",
            "offenseTeam",
            "scoringPlay",
            "isPenalty",
            "isTurnover",
            "noPlay",
            "statYardage",
            "officialStats",
            "providerRejectReason",
        )
    }
    encoded = json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _source_revision(raw: Mapping[str, Any], modified: str) -> str:
    provider_revision = raw.get("providerRevision")
    if provider_revision is not None:
        return _required_string(provider_revision, "play.providerRevision")
    semantic = {
        key: raw.get(key)
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
    return f"{modified}:{digest}"


def _common_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    key = _play_key(raw)
    modified = _required_string(raw.get("modified"), "play.modified")
    semantic_hash = _semantic_hash(raw)
    period = raw.get("period")
    clock = raw.get("clock")
    if not isinstance(period, Mapping) or not isinstance(clock, Mapping):
        raise FixtureError("play.period and play.clock must be objects")
    return {
        "key": key,
        "revision": f"{modified}:{semantic_hash[:16]}",
        "source_revision": _source_revision(raw, modified),
        "provider_modified": modified,
        "semantic_hash": semantic_hash,
        "sequence": _required_int(raw.get("sequenceNumber"), "play.sequenceNumber"),
        "quarter": _required_int(period.get("number"), "play.period.number"),
        "clock": _required_string(clock.get("displayValue"), "play.clock.displayValue"),
        "wallclock": _required_string(raw.get("wallclock"), "play.wallclock"),
        "away": _required_string(raw.get("away"), "play.away"),
        "home": _required_string(raw.get("home"), "play.home"),
        "raw_text": _required_string(raw.get("text"), "play.text"),
    }


def _rejected(common: Mapping[str, Any], reason: str) -> RejectedPlay:
    return RejectedPlay(**common, reason=reason, parser_version=PARSER_VERSION)


def _candidate_stats(candidate: _Candidate) -> dict[str, int]:
    totals: dict[str, int] = {}
    for participant in candidate.participants:
        for stat in participant.stats:
            totals[stat.key] = totals.get(stat.key, 0) + stat.value
    return {key: value for key, value in totals.items() if value != 0}


def _official_stats(raw: Mapping[str, Any]) -> dict[str, int] | None:
    value = raw.get("officialStats")
    if not isinstance(value, Mapping):
        return None
    result: dict[str, int] = {}
    for key, amount in value.items():
        if key not in SCORING_TABLE:
            continue
        if isinstance(amount, bool) or not isinstance(amount, int):
            return None
        if amount:
            result[key] = amount
    return result


def build_athlete_index(entries: Any) -> AthleteIndex:
    """Index structured boxscore athletes by team and ESPN narrative alias."""
    if not isinstance(entries, list):
        raise FixtureError("fixture.athletes must be an array")
    index: dict[tuple[str, str], dict[str, str]] = {}
    for position, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise FixtureError(f"fixture.athletes[{position}] must be an object")
        athlete_id = _required_string(entry.get("id"), f"fixture.athletes[{position}].id")
        first_name = _required_string(
            entry.get("firstName"), f"fixture.athletes[{position}].firstName"
        )
        last_name = _required_string(
            entry.get("lastName"), f"fixture.athletes[{position}].lastName"
        )
        display_name = _required_string(
            entry.get("displayName"), f"fixture.athletes[{position}].displayName"
        )
        team = _required_string(entry.get("team"), f"fixture.athletes[{position}].team")
        alias = f"{first_name[0].upper()}.{last_name}"
        aliases = index.setdefault((team, alias), {})
        known_name = aliases.get(athlete_id)
        if known_name is not None and known_name != display_name:
            raise FixtureError(f"athlete {athlete_id} has conflicting display names")
        aliases[athlete_id] = display_name
    return {
        key: tuple(sorted(values.items()))
        for key, values in index.items()
    }


def _resolve_players(
    participants: Sequence[PlayerDelta], athlete_index: AthleteIndex
) -> tuple[tuple[PlayerDelta, ...] | None, str | None]:
    resolved: list[PlayerDelta] = []
    for participant in participants:
        matches = athlete_index.get((participant.team, participant.display_name), ())
        if not matches:
            return None, f"unresolved_athlete:{participant.display_name}"
        if len(matches) != 1:
            return None, f"ambiguous_athlete:{participant.display_name}"
        athlete_id, display_name = matches[0]
        resolved.append(
            PlayerDelta(
                athlete_id,
                display_name,
                participant.team,
                participant.role,
                participant.stats,
                participant.ppr_hundredths,
                participant.standard_hundredths,
            )
        )
    return tuple(resolved), None


def _review_result(text: str) -> str:
    prefix, marker, result = text.rpartition("REVERSED.")
    if marker and "challenged" in prefix.casefold() and result:
        return result.lstrip()
    return text


def parse_play(raw: Mapping[str, Any], athlete_index: AthleteIndex) -> PlayResult:
    """Parse one provider play. Unsupported or contradictory input fails closed."""
    if not isinstance(raw, Mapping):
        raise FixtureError("play must be an object")
    common = _common_fields(raw)
    text = common["raw_text"]

    if raw.get("noPlay") is True and raw.get("isPenalty") is True:
        return _rejected(common, "no_play_penalty")
    provider_rejection = raw.get("providerRejectReason")
    if provider_rejection is not None:
        return _rejected(
            common, _required_string(provider_rejection, "play.providerRejectReason")
        )
    if "LATERAL" in text.upper():
        return _rejected(common, "ambiguous_lateral")

    play_type = raw.get("type")
    if not isinstance(play_type, Mapping):
        raise FixtureError("play.type must be an object")
    type_name = _required_string(play_type.get("text"), "play.type.text")
    parsers = PARSER_REGISTRY.get(type_name)
    if parsers is None:
        return _rejected(common, "unknown_play_type")

    result_text = _review_result(text)
    offense_team = _required_string(raw.get("offenseTeam"), "play.offenseTeam")
    candidate = next(
        (candidate for parser in parsers if (candidate := parser(result_text, offense_team)) is not None),
        None,
    )
    if candidate is None:
        return _rejected(common, "unsupported_narrative")

    for flag, expected in candidate.expected_flags.items():
        if raw.get(flag) is not expected:
            return _rejected(common, f"contradictory_{flag}")
    if candidate.stat_yardage is not None:
        stat_yardage = raw.get("statYardage")
        if isinstance(stat_yardage, bool) or stat_yardage != candidate.stat_yardage:
            return _rejected(common, "contradictory_stat_yardage")
    official = _official_stats(raw)
    if official is None:
        return _rejected(common, "missing_or_invalid_official_stats")
    if official != _candidate_stats(candidate):
        return _rejected(common, "contradictory_official_stats")

    participants, identity_error = _resolve_players(candidate.participants, athlete_index)
    if identity_error is not None or participants is None:
        return _rejected(common, identity_error or "unresolved_athlete")

    return AttributedPlay(
        **common,
        kind=candidate.kind,
        participants=participants,
        attribution="exact",
        parser_version=PARSER_VERSION,
    )


def _stat_json(stat: StatDelta) -> dict[str, Any]:
    return {"key": stat.key, "value": stat.value, "label": stat.label}


def _participant_json(participant: PlayerDelta) -> dict[str, Any]:
    return {
        "playerId": participant.player_id,
        "displayName": participant.display_name,
        "team": participant.team,
        "role": participant.role,
        "stats": [_stat_json(stat) for stat in participant.stats],
        "points": {
            "ppr": _points(participant.ppr_hundredths),
            "standard": _points(participant.standard_hundredths),
        },
    }


def _event_json(
    play: AttributedPlay,
    lifecycle: str,
    previous_revision: str | None = None,
) -> dict[str, Any]:
    event = {
        "eventId": f"{play.key.provider}:{play.key.game_id}:{play.key.play_id}",
        "provider": play.key.provider,
        "gameId": play.key.game_id,
        "playId": play.key.play_id,
        "revision": play.revision,
        "sourceRevision": play.source_revision,
        "providerModified": play.provider_modified,
        "semanticHash": play.semantic_hash,
        "sequence": play.sequence,
        "lifecycle": lifecycle,
        "quarter": play.quarter,
        "clock": play.clock,
        "wallclock": play.wallclock,
        "away": play.away,
        "home": play.home,
        "rawText": play.raw_text,
        "kind": play.kind,
        "participants": [_participant_json(participant) for participant in play.participants],
        "attribution": play.attribution,
        "parserVersion": play.parser_version,
    }
    if previous_revision is not None:
        event["previousRevision"] = previous_revision
    return event


def _voided_event(
    prior: Mapping[str, Any], rejected: RejectedPlay, previous_revision: str
) -> dict[str, Any]:
    return {
        "eventId": prior["eventId"],
        "provider": rejected.key.provider,
        "gameId": rejected.key.game_id,
        "playId": rejected.key.play_id,
        "revision": rejected.revision,
        "sourceRevision": rejected.source_revision,
        "providerModified": rejected.provider_modified,
        "semanticHash": rejected.semantic_hash,
        "previousRevision": previous_revision,
        "sequence": rejected.sequence,
        "lifecycle": "voided",
        "quarter": rejected.quarter,
        "clock": rejected.clock,
        "wallclock": rejected.wallclock,
        "away": rejected.away,
        "home": rejected.home,
        "rawText": rejected.raw_text,
        "previousRawText": prior["rawText"],
        "kind": prior["kind"],
        "participants": [],
        "attribution": prior["attribution"],
        "parserVersion": rejected.parser_version,
        "voidReason": rejected.reason,
    }


def _skipped_json(play: RejectedPlay) -> dict[str, Any]:
    return {
        "provider": play.key.provider,
        "gameId": play.key.game_id,
        "playId": play.key.play_id,
        "revision": play.revision,
        "sourceRevision": play.source_revision,
        "providerModified": play.provider_modified,
        "semanticHash": play.semantic_hash,
        "sequence": play.sequence,
        "rawText": play.raw_text,
        "reason": play.reason,
        "parserVersion": play.parser_version,
    }


def _validated_frames(fixture: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if not isinstance(fixture, Mapping):
        raise FixtureError("fixture root must be an object")
    version = fixture.get("fixtureVersion")
    if version != 1:
        raise FixtureError("fixture.fixtureVersion must equal 1")
    frames = fixture.get("frames")
    if not isinstance(frames, list) or not frames:
        raise FixtureError("fixture.frames must be a non-empty array")
    for index, frame in enumerate(frames):
        if not isinstance(frame, Mapping):
            raise FixtureError(f"fixture.frames[{index}] must be an object")
        _required_string(frame.get("observedAt"), f"fixture.frames[{index}].observedAt")
        source_state = _required_string(
            frame.get("sourceState"), f"fixture.frames[{index}].sourceState"
        )
        if source_state not in SOURCE_STATES:
            raise FixtureError(f"fixture.frames[{index}].sourceState is unsupported")
        if not isinstance(frame.get("stale", False), bool):
            raise FixtureError(f"fixture.frames[{index}].stale must be boolean")
        if not isinstance(frame.get("plays", []), list):
            raise FixtureError(f"fixture.frames[{index}].plays must be an array")
        if not isinstance(frame.get("games", []), list):
            raise FixtureError(f"fixture.frames[{index}].games must be an array")
    return frames


def _normalized_item_key(item: Mapping[str, Any]) -> PlayKey:
    return PlayKey(
        _required_string(item.get("provider"), "snapshot item.provider"),
        _required_string(item.get("gameId"), "snapshot item.gameId"),
        _required_string(item.get("playId"), "snapshot item.playId"),
    )


def _normalized_week(value: Any, path: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise FixtureError(f"{path} must be an object")
    result = {
        "season": _required_int(value.get("season"), f"{path}.season"),
        "seasonType": _required_int(value.get("seasonType"), f"{path}.seasonType"),
        "number": _required_int(value.get("number"), f"{path}.number"),
        "label": _required_string(value.get("label"), f"{path}.label"),
        "detail": str(value.get("detail", "")),
    }
    if result["season"] < 2000 or result["seasonType"] < 1 or result["number"] < 1:
        raise FixtureError(f"{path} contains an invalid season or week")
    return result


def _week_key(value: Mapping[str, Any] | None) -> tuple[int, int, int] | None:
    if value is None:
        return None
    return (int(value["season"]), int(value["seasonType"]), int(value["number"]))


def _weekly_leaderboard(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise FixtureError("fixture frame weeklyPlayers must be an array")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        path = f"fixture frame weeklyPlayers[{index}]"
        if not isinstance(raw, Mapping):
            raise FixtureError(f"{path} must be an object")
        player_id = _required_string(raw.get("playerId"), f"{path}.playerId")
        if player_id in seen:
            raise FixtureError(f"{path}.playerId is duplicated")
        seen.add(player_id)
        position = _required_string(raw.get("position"), f"{path}.position")
        if position not in {"QB", "RB", "WR", "TE"}:
            raise FixtureError(f"{path}.position is unsupported")
        raw_game_ids = raw.get("gameIds", [])
        if not isinstance(raw_game_ids, list):
            raise FixtureError(f"{path}.gameIds must be an array")
        game_ids: list[str] = []
        for game_index, raw_game_id in enumerate(raw_game_ids):
            game_id = _required_string(raw_game_id, f"{path}.gameIds[{game_index}]")
            if game_id in game_ids:
                raise FixtureError(f"{path}.gameIds is duplicated")
            game_ids.append(game_id)
        raw_stats = raw.get("stats")
        if not isinstance(raw_stats, Mapping):
            raise FixtureError(f"{path}.stats must be an object")
        stats: list[StatDelta] = []
        for key in SCORING_TABLE:
            if key not in raw_stats:
                continue
            amount = _required_int(raw_stats[key], f"{path}.stats.{key}")
            if amount != 0:
                stats.append(stat_delta(key, amount))
        unsupported = sorted(set(raw_stats) - set(SCORING_TABLE))
        if unsupported:
            raise FixtureError(f"{path}.stats has unsupported keys: {', '.join(unsupported)}")
        ppr, standard = score_stats(stats)
        rows.append(
            {
                "playerId": player_id,
                "displayName": _required_string(
                    raw.get("displayName"), f"{path}.displayName"
                ),
                "team": _required_string(raw.get("team"), f"{path}.team"),
                "position": position,
                "games": _required_int(raw.get("games", 1), f"{path}.games"),
                "gameIds": sorted(game_ids),
                "stats": [
                    {"key": stat.key, "value": stat.value, "label": stat.label}
                    for stat in stats
                ],
                "points": {"ppr": _points(ppr), "standard": _points(standard)},
            }
        )
    return sorted(rows, key=lambda row: (row["position"], row["team"], row["playerId"]))


def reconcile_frame(
    previous_snapshot: Mapping[str, Any] | None,
    athletes: Any,
    frame: Mapping[str, Any],
    *,
    event_cap: int = DEFAULT_EVENT_CAP,
    skipped_cap: int = DEFAULT_SKIPPED_CAP,
) -> dict[str, Any]:
    """Merge one partial provider frame without treating absence as deletion."""
    _validated_frames({"fixtureVersion": 1, "frames": [frame]})
    athlete_index = build_athlete_index(athletes)
    if event_cap < 1 or skipped_cap < 1:
        raise ValueError("snapshot caps must be positive")

    previous = previous_snapshot if isinstance(previous_snapshot, Mapping) else {}
    frame_week = _normalized_week(frame.get("week"), "fixture frame.week")
    previous_week = _normalized_week(previous.get("week"), "snapshot.week")
    if frame_week is not None and previous_week is not None and _week_key(frame_week) != _week_key(previous_week):
        previous = {}
        previous_week = None
    active_events: dict[PlayKey, dict[str, Any]] = {}
    latest_revision: dict[PlayKey, str] = {}
    games: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []

    for game in previous.get("games", []):
        if not isinstance(game, Mapping):
            raise FixtureError("snapshot.games contains a non-object")
        game_id = _required_string(game.get("id"), "game.id")
        games[game_id] = dict(game)
    for item in previous.get("skipped", []):
        if not isinstance(item, Mapping):
            raise FixtureError("snapshot.skipped contains a non-object")
        copied = dict(item)
        skipped.append(copied)
        latest_revision[_normalized_item_key(copied)] = _required_string(
            copied.get("revision"), "snapshot skipped.revision"
        )
    for item in previous.get("events", []):
        if not isinstance(item, Mapping):
            raise FixtureError("snapshot.events contains a non-object")
        copied = copy.deepcopy(dict(item))
        key = _normalized_item_key(copied)
        active_events[key] = copied
        latest_revision[key] = _required_string(
            copied.get("revision"), "snapshot event.revision"
        )

    for game in frame.get("games", []):
        if not isinstance(game, Mapping):
            raise FixtureError("fixture frame games contains a non-object")
        game_id = _required_string(game.get("id"), "game.id")
        games[game_id] = dict(game)

    for play_index, raw in enumerate(frame.get("plays", [])):
        try:
            result = parse_play(raw, athlete_index)
        except FixtureError as error:
            raise FixtureError(f"fixture frame plays[{play_index}]: {error}") from error
        previous_revision = latest_revision.get(result.key)
        if previous_revision == result.revision:
            continue

        prior_event = active_events.get(result.key)
        if isinstance(result, AttributedPlay):
            lifecycle = "corrected" if previous_revision is not None else "current"
            active_events[result.key] = _event_json(result, lifecycle, previous_revision)
        else:
            skipped.append(_skipped_json(result))
            if prior_event is not None:
                active_events[result.key] = _voided_event(
                    prior_event, result, previous_revision or prior_event["revision"]
                )
        latest_revision[result.key] = result.revision

    events = sorted(
        active_events.values(),
        key=lambda event: (
            event["wallclock"],
            event["gameId"],
            event["sequence"],
            event["playId"],
        ),
    )[-event_cap:]
    frame_errors = frame.get("errors", [])
    if not isinstance(frame_errors, list) or not all(
        isinstance(error, Mapping) for error in frame_errors
    ):
        raise FixtureError("fixture frame errors must be an array of objects")
    if "weeklyPlayers" in frame:
        leaderboard = _weekly_leaderboard(frame.get("weeklyPlayers"))
    else:
        prior_leaderboard = previous.get("leaderboard", [])
        if not isinstance(prior_leaderboard, list):
            raise FixtureError("snapshot.leaderboard must be an array")
        leaderboard = copy.deepcopy(prior_leaderboard)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "observedAt": frame["observedAt"],
        "sourceState": frame["sourceState"],
        "stale": frame.get("stale", False),
        "week": frame_week or previous_week,
        "games": [games[game_id] for game_id in sorted(games)],
        "leaderboard": leaderboard,
        "events": events,
        "skipped": skipped[-skipped_cap:],
        "errors": [dict(error) for error in frame_errors][-skipped_cap:],
    }


def reduce_frames(
    fixture: Mapping[str, Any],
    at: int | None = None,
    event_cap: int = DEFAULT_EVENT_CAP,
    skipped_cap: int = DEFAULT_SKIPPED_CAP,
) -> dict[str, Any]:
    """Replay fixture frames through the same merger used by live observations."""
    frames = _validated_frames(fixture)
    athletes = fixture.get("athletes")
    if at is None:
        at = len(frames) - 1
    if isinstance(at, bool) or not isinstance(at, int) or at < 0 or at >= len(frames):
        raise FixtureError("frame index is outside fixture.frames")
    snapshot: dict[str, Any] | None = None
    for frame in frames[: at + 1]:
        snapshot = reconcile_frame(
            snapshot,
            athletes,
            frame,
            event_cap=event_cap,
            skipped_cap=skipped_cap,
        )
    if snapshot is None:
        raise FixtureError("fixture contains no frames")
    return snapshot


def load_fixture(path: str | Path) -> Mapping[str, Any]:
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FixtureError(str(error)) from error
    if not isinstance(value, Mapping):
        raise FixtureError("fixture root must be an object")
    return value


def validate_snapshot(value: Any) -> dict[str, Any]:
    """Validate the cached public schema and return a detached snapshot."""
    if not isinstance(value, Mapping):
        raise FixtureError("snapshot root must be an object")
    if value.get("schemaVersion") != SCHEMA_VERSION:
        raise FixtureError("snapshot.schemaVersion is unsupported")
    _required_string(value.get("observedAt"), "snapshot.observedAt")
    source_state = _required_string(value.get("sourceState"), "snapshot.sourceState")
    if source_state not in SOURCE_STATES:
        raise FixtureError("snapshot.sourceState is unsupported")
    if not isinstance(value.get("stale"), bool):
        raise FixtureError("snapshot.stale must be boolean")
    for key in ("games", "events", "skipped", "errors"):
        collection = value.get(key)
        if not isinstance(collection, list) or not all(
            isinstance(item, Mapping) for item in collection
        ):
            raise FixtureError(f"snapshot.{key} must be an array of objects")
    if value.get("week") is not None:
        _normalized_week(value.get("week"), "snapshot.week")
    leaderboard = value.get("leaderboard", [])
    if not isinstance(leaderboard, list) or not all(
        isinstance(item, Mapping) for item in leaderboard
    ):
        raise FixtureError("snapshot.leaderboard must be an array of objects")
    return copy.deepcopy(dict(value))


def default_cache_path() -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME")
    if cache_home and Path(cache_home).is_absolute():
        base = Path(cache_home)
    else:
        base = Path.home() / ".cache"
    return base / "fantasy-feed" / "snapshot.json"


def load_last_good_cache(path: str | Path) -> dict[str, Any] | None:
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            value = json.load(stream)
        return validate_snapshot(value)
    except (OSError, UnicodeError, json.JSONDecodeError, FixtureError):
        return None


def write_last_good_cache(path: str | Path, snapshot: Mapping[str, Any]) -> None:
    """Write a mode-0600 cache through fsync and same-directory atomic replace."""
    validated = validate_snapshot(snapshot)
    destination = Path(path)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(
                validated,
                stream,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(destination.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _normalized_error(code: str, error: BaseException) -> dict[str, str]:
    message = " ".join(str(error).split())[:240] or type(error).__name__
    return {"code": code, "message": message}


def _stale_snapshot(
    cached: Mapping[str, Any], code: str, error: BaseException
) -> dict[str, Any]:
    snapshot = validate_snapshot(cached)
    snapshot["sourceState"] = "offline"
    snapshot["stale"] = True
    snapshot["errors"] = [_normalized_error(code, error)]
    return snapshot


def refresh_live(
    cache_path: str | Path,
    *,
    get_json: espn.GetJson | None = None,
    observed_at: str | None = None,
) -> tuple[dict[str, Any] | None, int, dict[str, str] | None]:
    """Refresh once, falling back only to a previously validated last-good snapshot."""
    cached = load_last_good_cache(cache_path)
    try:
        fixture = espn.collect_live(
            cached, get_json=get_json, observed_at=observed_at
        )
        frames = _validated_frames(fixture)
        if len(frames) != 1:
            raise FixtureError("live provider must return exactly one frame")
        snapshot = reconcile_frame(cached, fixture.get("athletes"), frames[0])
        write_last_good_cache(cache_path, snapshot)
        return snapshot, 0, None
    except espn.ProviderError as error:
        normalized = _normalized_error(error.code, error)
    except (FixtureError, ValueError) as error:
        normalized = _normalized_error("malformed_response", error)
    except OSError as error:
        normalized = _normalized_error("cache_write_failed", error)

    if cached is not None:
        return _stale_snapshot(cached, normalized["code"], RuntimeError(normalized["message"])), 10, normalized
    return None, 20, normalized


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _ArgumentParser(prog="feed.py", add_help=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture", metavar="PATH")
    mode.add_argument("--once", action="store_true")
    parser.add_argument("--at", type=int, metavar="FRAME")
    parser.add_argument("--cache", metavar="PATH")
    parser.add_argument("--provider-base-url", metavar="LOOPBACK_URL")
    parser.add_argument("--reset-cache", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.at is not None and arguments.fixture is None:
        raise UsageError("--at requires --fixture")
    if arguments.cache is not None and not arguments.once:
        raise UsageError("--cache requires --once")
    if arguments.provider_base_url is not None and not arguments.once:
        raise UsageError("--provider-base-url requires --once")
    if arguments.reset_cache and (
        arguments.provider_base_url is None or arguments.cache is None
    ):
        raise UsageError("--reset-cache requires --provider-base-url and --cache")
    return arguments


def _write_snapshot(snapshot: Mapping[str, Any]) -> None:
    json.dump(snapshot, sys.stdout, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")


def main(
    argv: Sequence[str] | None = None,
    *,
    get_json: espn.GetJson | None = None,
    observed_at: str | None = None,
) -> int:
    try:
        arguments = _arguments(argv)
    except UsageError as error:
        print(f"feed.py: {error}", file=sys.stderr)
        return 64

    if arguments.once:
        request_json = get_json
        if arguments.provider_base_url is not None:
            if get_json is not None:
                print(
                    "feed.py: --provider-base-url cannot be combined with an injected provider",
                    file=sys.stderr,
                )
                return 64
            try:
                request_json = espn.simulator_get_json(arguments.provider_base_url)
            except espn.ProviderError as error:
                print(f"feed.py: {error}", file=sys.stderr)
                return 64
        if arguments.reset_cache:
            try:
                Path(arguments.cache).unlink()
            except FileNotFoundError:
                pass
            except OSError as error:
                print(f"feed.py: unable to reset simulator cache: {error}", file=sys.stderr)
                return 64
        snapshot, status, error = refresh_live(
            arguments.cache or default_cache_path(),
            get_json=request_json,
            observed_at=observed_at,
        )
        if snapshot is not None:
            _write_snapshot(snapshot)
        elif error is not None:
            print(f"feed.py: live refresh failed: {error['message']}", file=sys.stderr)
        return status

    try:
        snapshot = reduce_frames(load_fixture(arguments.fixture), at=arguments.at)
    except (FixtureError, ValueError) as error:
        print(f"feed.py: invalid fixture: {error}", file=sys.stderr)
        return 65
    _write_snapshot(snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
