#!/usr/bin/env python3
"""Sync your ESPN fantasy matchup into the Fantasy Feed plugin.

The feed itself follows NFL plays with no account. This script is the league
side: it reads your ESPN league with your session cookies and writes the two
files the plugin watches, so the bar shows your live head-to-head and the
matchup tab shows both lineups scored by your league's rules.

  ~/.config/omarchy/fantasy-feed.json      favorites = this week's starters on
                                           both sides of your matchup, tagged
                                           side: "me" | "opp" and slot, plus a
                                           `league` block with the league's
                                           scoring rules.
  ~/.cache/fantasy-feed/league.json        ESPN's own live matchup totals and
                                           win probability, plus ESPN's weekly
                                           points and projection for every
                                           starter (the K and D/ST rows, which
                                           plays cannot score).

Credentials live in ~/.config/fantasy-feed/espn.json (mode 0600), outside the
Omarchy config tree so a dotfiles sync never picks them up:

  python3 scripts/league_sync.py --init        # write the template, then fill it in
  python3 scripts/league_sync.py --once        # sync now
  python3 scripts/league_sync.py --loop        # every minute while games are live
  python3 scripts/league_sync.py --install-service   # systemd --user unit for --loop

Standard library only, like the rest of the plugin's scripts.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# --- ESPN wire constants -------------------------------------------------------

READS_HOST = "lm-api-reads.fantasy.espn.com"
BASE = f"https://{READS_HOST}/apis/v3/games/ffl"

POSITION_BY_ID = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
SLOT_BY_ID = {
    0: "QB", 1: "TQB", 2: "RB", 3: "RB/WR", 4: "WR", 5: "WR/TE", 6: "TE", 7: "OP",
    16: "D/ST", 17: "K", 18: "P", 19: "HC", 20: "BE", 21: "IR", 23: "FLEX",
}
NON_STARTING_SLOTS = {20, 21}
PRO_TEAM_BY_ID = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA",
    16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI",
    23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WSH", 29: "CAR",
    30: "JAX", 33: "BAL", 34: "HOU",
}
STAT_SOURCE_ACTUAL = 0
STAT_SOURCE_PROJECTED = 1
STAT_SPLIT_WEEKLY = 1

# Every lineup slot the plugin lists. Plays score only QB/RB/WR/TE; K and D/ST
# rows take ESPN's own points from league.json.
FEED_POSITIONS = {"QB", "RB", "WR", "TE", "K", "D/ST"}
_SLOT_ORDER = {"QB": 0, "RB": 1, "WR": 2, "TE": 3, "FLEX": 4, "RB/WR": 4, "WR/TE": 4,
               "OP": 4, "K": 5, "D/ST": 6}

# The plugin's scoring keys, mapped to the ESPN statIds that can carry them.
# ESPN has two ways to score yardage: per yard (statId 3/24/42, e.g. 0.04) or
# per full bucket (statId 8/28/48: 1 point per complete 25/10/10 yards, floor).
_YARDAGE = {
    "passing_yards": ((3, 1), (8, 25)),
    "rushing_yards": ((24, 1), (28, 10)),
    "receiving_yards": ((42, 1), (48, 10)),
}
_COUNTING = {
    "passing_touchdown": 4,
    "interception_thrown": 20,
    "rushing_touchdown": 25,
    "reception": 53,
    "receiving_touchdown": 43,
    "passing_two_point_conversion": 19,
    "rushing_two_point_conversion": 26,
    "receiving_two_point_conversion": 44,
    "fumble_lost": 72,
}


# --- Paths ---------------------------------------------------------------------


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var, "")
    return Path(value) if value.startswith("/") else Path.home() / default


def favorites_path() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "omarchy" / "fantasy-feed.json"


def live_path() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / "fantasy-feed" / "league.json"


def snapshot_path() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / "fantasy-feed" / "snapshot.json"


def credentials_path() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "fantasy-feed" / "espn.json"


def write_atomic(path: Path, payload: dict, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".sync-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# --- Credentials ---------------------------------------------------------------

CREDENTIALS_TEMPLATE = {
    "leagueId": "",
    "season": datetime.now().year,
    "teamId": 0,
    "espn_s2": "",
    "swid": "{00000000-0000-0000-0000-000000000000}",
}


class ConfigError(SystemExit):
    pass


def load_credentials(path: Path | None = None) -> dict:
    """League id, season, team id and the two ESPN session cookies.

    Read from the JSON file; any ESPN_LEAGUE_ID / ESPN_SEASON / ESPN_TEAM_ID /
    ESPN_S2 / SWID in the environment wins over it.
    """
    path = path or credentials_path()
    data: dict = {}
    if path.is_file():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            print(f"warning: {path} is readable by others (mode {mode:o}); "
                  "chmod 600 it", file=sys.stderr)
        try:
            data = json.loads(path.read_text()) or {}
        except ValueError as exc:
            raise ConfigError(f"{path} is not valid JSON: {exc}")
    env = os.environ
    cfg = {
        "league_id": str(env.get("ESPN_LEAGUE_ID") or data.get("leagueId") or "").strip(),
        "season": int(env.get("ESPN_SEASON") or data.get("season") or datetime.now().year),
        "team_id": int(env.get("ESPN_TEAM_ID") or data.get("teamId") or 0),
        "espn_s2": (env.get("ESPN_S2") or data.get("espn_s2") or "").strip(),
        "swid": (env.get("SWID") or data.get("swid") or "").strip(),
    }
    if cfg["swid"] and not cfg["swid"].startswith("{"):
        cfg["swid"] = "{" + cfg["swid"].strip("{}") + "}"
    missing = [k for k in ("league_id", "team_id", "espn_s2", "swid") if not cfg[k]]
    if missing:
        raise ConfigError(
            f"missing {', '.join(missing)} -- fill in {path} "
            "(python3 scripts/league_sync.py --init writes the template)"
        )
    return cfg


def init_credentials(path: Path | None = None) -> int:
    path = path or credentials_path()
    if path.exists():
        print(f"{path} already exists; not overwriting")
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, CREDENTIALS_TEMPLATE, mode=0o600)
    print(f"wrote {path} (mode 600). Fill in:")
    print("  leagueId  from the league URL: fantasy.espn.com/football/league?leagueId=NNN")
    print("  teamId    from your roster URL: ...&teamId=N")
    print("  espn_s2, swid  from a logged-in browser: DevTools > Application > Cookies")
    print("                 > fantasy.espn.com. SWID keeps its braces.")
    return 0


# --- ESPN client ---------------------------------------------------------------


class ESPNError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the cookies go to one host only, and ESPN
    redirects to a login page when they are stale, which is an error here."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


class League:
    def __init__(self, cfg: dict, timeout: float = 20.0) -> None:
        self.cfg = cfg
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect())
        self._settings: dict | None = None

    @property
    def _league_url(self) -> str:
        return f"{BASE}/seasons/{self.cfg['season']}/segments/0/leagues/{self.cfg['league_id']}"

    def _scrub(self, text: str) -> str:
        for secret in (self.cfg["espn_s2"], self.cfg["swid"]):
            if secret:
                text = text.replace(secret, "***")
        return text

    def _get(self, views: list[str], week: int | None = None) -> dict:
        query = [("view", v) for v in views]
        if week is not None:
            query.append(("scoringPeriodId", str(week)))
        url = f"{self._league_url}?{urllib.parse.urlencode(query)}"
        assert urllib.parse.urlsplit(url).hostname == READS_HOST
        req = urllib.request.Request(url, headers={
            "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
            "Accept": "application/json",
            "Cookie": f"espn_s2={self.cfg['espn_s2']}; SWID={self.cfg['swid']}",
        })
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise ESPNError(
                    f"ESPN rejected the credentials (HTTP {exc.code}). The cookies "
                    "expire; re-copy espn_s2 and swid from a logged-in browser."
                ) from None
            if exc.code == 404:
                raise ESPNError(
                    f"league {self.cfg['league_id']} not found for season "
                    f"{self.cfg['season']}") from None
            if 300 <= exc.code < 400:
                raise ESPNError("ESPN redirected (stale cookies, most likely).") from None
            raise ESPNError(self._scrub(f"ESPN returned HTTP {exc.code}")) from None
        except urllib.error.URLError as exc:
            raise ESPNError(self._scrub(f"network error talking to ESPN: {exc.reason}")) from None
        try:
            data = json.loads(body)
        except ValueError:
            raise ESPNError("ESPN returned a non-JSON body (often an auth redirect).") from None
        if isinstance(data, list):
            if not data:
                raise ESPNError("ESPN returned an empty league payload.")
            data = data[0]
        return data

    # -- views --

    def settings(self) -> dict:
        if self._settings is None:
            self._settings = self._get(["mSettings", "mStatus"])
        return self._settings

    def current_week(self) -> int:
        status = self.settings().get("status") or {}
        return int(status.get("latestScoringPeriod")
                   or status.get("currentMatchupPeriod") or 1)

    def name(self) -> str:
        return (self.settings().get("settings") or {}).get("name") or "Unnamed league"

    def scoring_points(self) -> dict[int, float]:
        """statId -> points, the league's scoring table."""
        scoring = (self.settings().get("settings") or {}).get("scoringSettings") or {}
        return {int(i["statId"]): float(i.get("points") or 0.0)
                for i in scoring.get("scoringItems") or [] if "statId" in i}

    def teams(self, week: int) -> dict[int, dict]:
        """team id -> {name, abbrev, starters: [player records]} for `week`."""
        payload = self._get(["mTeam", "mRoster"], week)
        season = self.cfg["season"]
        out: dict[int, dict] = {}
        for t in payload.get("teams") or []:
            players = []
            for e in ((t.get("roster") or {}).get("entries") or []):
                pl = (e.get("playerPoolEntry") or {}).get("player") or {}
                if not pl:
                    continue
                slot_id = int(e.get("lineupSlotId", 20))
                pos_id = int(pl.get("defaultPositionId") or 0)
                players.append({
                    "player_id": int(e["playerId"]),
                    "name": pl.get("fullName"),
                    "position": POSITION_BY_ID.get(pos_id, str(pos_id)),
                    "pro_team": PRO_TEAM_BY_ID.get(int(pl.get("proTeamId") or 0), "FA"),
                    "slot_id": slot_id,
                    "slot": SLOT_BY_ID.get(slot_id, str(slot_id)),
                    "points": _week_stat(pl, season, week, STAT_SOURCE_ACTUAL),
                    "projected": _week_stat(pl, season, week, STAT_SOURCE_PROJECTED),
                })
            out[int(t["id"])] = {
                "team_id": int(t["id"]),
                "name": (t.get("name")
                         or f"{t.get('location', '')} {t.get('nickname', '')}").strip(),
                "abbrev": t.get("abbrev"),
                "players": players,
            }
        return out

    def matchup(self, week: int, team_id: int) -> dict | None:
        """This team's game in `week`, with ESPN's live totals, or None (bye)."""
        payload = self._get(["mMatchupScore", "mScoreboard"], week)
        for m in payload.get("schedule") or []:
            if int(m.get("matchupPeriodId") or 0) != week:
                continue
            home, away = m.get("home") or {}, m.get("away") or {}
            ids = (int(home.get("teamId") or 0), int(away.get("teamId") or 0))
            if team_id not in ids:
                continue
            return {
                "home_team_id": ids[0],
                "away_team_id": ids[1],
                # Mid-week ESPN leaves totalPoints at 0 and reports the running
                # score in the *Live fields; the plain fields fill in when final.
                "home_points": _live_first(home, "totalPoints"),
                "away_points": _live_first(away, "totalPoints"),
                "home_projected": _live_first(home, "totalProjectedPoints"),
                "away_projected": _live_first(away, "totalProjectedPoints"),
                "home_win_prob": home.get("winProbability"),
                "winner": m.get("winner"),
            }
        return None


def _live_first(side: dict, key: str):
    live = side.get(key + "Live")
    return live if live else side.get(key)


def _week_stat(player: dict, season: int, week: int, source: int) -> float:
    """League-scored points for one week from a roster player's stat splits."""
    for entry in player.get("stats") or []:
        if (entry.get("statSourceId") == source
                and entry.get("statSplitTypeId") == STAT_SPLIT_WEEKLY
                and int(entry.get("seasonId") or 0) == season
                and int(entry.get("scoringPeriodId") or 0) == week):
            applied = entry.get("appliedTotal")
            if applied is None:
                applied = sum(float(v) for v in (entry.get("appliedStats") or {}).values())
            return round(float(applied), 2)
    return 0.0


# --- Payloads ------------------------------------------------------------------


def scoring_rules(points: dict[int, float]) -> dict[str, dict]:
    """The league's rules in the plugin's vocabulary."""
    rules: dict[str, dict] = {}
    for key, candidates in _YARDAGE.items():
        # Prefer the bucket form when the league sets it; per-yard otherwise.
        for stat_id, per in reversed(candidates):
            value = points.get(stat_id, 0.0)
            if value:
                rules[key] = {"points": value, "per": per}
                break
        else:
            rules[key] = {"points": 0.0, "per": 1}
    for key, stat_id in _COUNTING.items():
        rules[key] = {"points": points.get(stat_id, 0.0), "per": 1}
    # Some leagues score every two-point conversion under one combined stat
    # (statId 62) rather than the three per-type ids.
    combined = points.get(62, 0.0)
    if combined:
        for key in ("passing_two_point_conversion", "rushing_two_point_conversion",
                    "receiving_two_point_conversion"):
            if not rules[key]["points"]:
                rules[key] = {"points": combined, "per": 1}
    return rules


def starters(players: list[dict]) -> list[dict]:
    """Starters in lineup order (QB, RB, WR, TE, flex, K, D/ST)."""
    out = [p for p in players
           if p["slot_id"] not in NON_STARTING_SLOTS and p["position"] in FEED_POSITIONS]
    out.sort(key=lambda p: (_SLOT_ORDER.get(p["slot"], 9), p["name"] or ""))
    return out


def _favorite(p: dict, side: str) -> dict:
    return {
        "playerId": str(p["player_id"]),
        "displayName": p["name"],
        "team": p["pro_team"],
        "position": p["position"],
        "side": side,
        "slot": p["slot"],
    }


def _team_ref(t: dict) -> dict:
    return {"teamId": t["team_id"], "name": t["name"], "abbrev": t["abbrev"]}


def build_payloads(league: League, week: int) -> tuple[dict, dict | None]:
    """(favorites file payload, live file payload or None on a bye)."""
    me = league.cfg["team_id"]
    teams = league.teams(week)
    if me not in teams:
        raise ESPNError(f"team {me} is not in this league (teams: {sorted(teams)})")
    game = league.matchup(week, me)
    opp = None
    if game:
        opp = game["away_team_id"] if game["home_team_id"] == me else game["home_team_id"]

    favorites = [_favorite(p, "me") for p in starters(teams[me]["players"])]
    if opp:
        favorites += [_favorite(p, "opp") for p in starters(teams[opp]["players"])]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fav = {
        "version": 1,
        "favorites": favorites,
        "settings": {},  # filled from the current file by sync_favorites
        "league": {
            "name": league.name(),
            "season": league.cfg["season"],
            "week": week,
            "me": _team_ref(teams[me]),
            "opponent": _team_ref(teams[opp]) if opp else None,
            "scoring": scoring_rules(league.scoring_points()),
            "syncedAt": now,
        },
    }
    if not game:
        return fav, None

    home = game["home_team_id"] == me

    def side(tid: int, is_home: bool) -> dict:
        return {
            **_team_ref(teams[tid]),
            "points": round(float((game["home_points"] if is_home else game["away_points"]) or 0.0), 2),
            "projected": round(float((game["home_projected"] if is_home else game["away_projected"]) or 0.0), 2),
        }

    # ESPN's own weekly points per starter, both sides: the K and D/ST rows.
    players = {}
    for tid in (me, opp):
        for p in starters(teams[tid]["players"]):
            players[str(p["player_id"])] = {
                "position": p["position"],
                "points": p["points"],
                "projected": p["projected"],
            }
    prob = game["home_win_prob"]
    if prob is not None and not home:
        prob = round(1 - prob, 3)
    live = {
        "version": 1,
        "observedAt": now,
        "week": week,
        "status": game["winner"],
        "me": side(me, home),
        "opponent": side(opp, not home),
        "winProbability": prob,
        "players": players,
    }
    return fav, live


def sync(league: League, week: int, dry_run: bool = False) -> tuple[dict, dict | None]:
    fav, live = build_payloads(league, week)
    path = favorites_path()
    try:
        current = json.loads(path.read_text()) if path.is_file() else {}
    except (OSError, ValueError):
        current = {}
    # The plugin's own settings (points filter) pass through untouched.
    fav["settings"] = dict(current.get("settings") or {})
    if not dry_run:
        write_atomic(path, fav)
        if live:
            write_atomic(live_path(), live, mode=0o600)
    return fav, live


def feed_is_live() -> bool:
    """Borrow the plugin's own view of the slate instead of asking ESPN again."""
    try:
        snap = json.loads(snapshot_path().read_text())
        return snap.get("sourceState") == "live"
    except (OSError, ValueError):
        return False


# --- Commands ------------------------------------------------------------------


def run_once(args) -> int:
    league = League(load_credentials(args.config))
    week = args.week or league.current_week()
    fav, live = sync(league, week, args.dry_run)
    mine = [f["displayName"] for f in fav["favorites"] if f["side"] == "me"]
    theirs = [f["displayName"] for f in fav["favorites"] if f["side"] == "opp"]
    opp = fav["league"]["opponent"]
    print(f"week {week}: {len(mine)} of mine, {len(theirs)} of "
          f"{opp['name'] if opp else 'nobody (bye)'}")
    print("  me : " + ", ".join(mine))
    print("  opp: " + ", ".join(theirs))
    if live:
        print(f"  live: {live['me']['points']} - {live['opponent']['points']} "
              f"(proj {live['me']['projected']} - {live['opponent']['projected']}, "
              f"win {live['winProbability']})")
    if args.dry_run:
        print(json.dumps({"favorites": fav, "live": live}, indent=2)[:2000])
    else:
        print(f"  wrote {favorites_path()} and {live_path()}")
    return 0


def run_loop(args) -> int:
    league = League(load_credentials(args.config))
    while True:
        try:
            # Lineups change right up to kickoff and between games, so while
            # the slate is live re-sync everything every minute.
            live = feed_is_live()
            sync(league, args.week or league.current_week())
            delay = 60 if live else 15 * 60
        except ESPNError as exc:
            print(f"espn: {exc}", file=sys.stderr)
            delay = 5 * 60
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            delay = 5 * 60
        sys.stdout.flush()
        # Settings (and the current week) are cached per League; refresh them
        # each pass so the loop follows the week rollover.
        league._settings = None
        time.sleep(delay)


UNIT = """[Unit]
Description=Sync ESPN fantasy matchup into Omarchy Fantasy Feed
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/env python3 {script} --loop
Restart=on-failure
RestartSec=60

[Install]
WantedBy=default.target
"""


def install_service() -> int:
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit = unit_dir / "fantasy-feed-sync.service"
    unit.write_text(UNIT.format(script=Path(__file__).resolve()))
    print(f"wrote {unit}")
    print("enable with:\n  systemctl --user daemon-reload && "
          "systemctl --user enable --now fantasy-feed-sync.service")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="sync once and exit (default)")
    mode.add_argument("--loop", action="store_true",
                      help="keep syncing; every minute while games are live")
    mode.add_argument("--init", action="store_true", help="write the credentials template")
    mode.add_argument("--install-service", action="store_true",
                      help="write a systemd --user unit that runs --loop")
    ap.add_argument("--config", type=Path, help="credentials file (default: "
                    "$XDG_CONFIG_HOME/fantasy-feed/espn.json)")
    ap.add_argument("--week", type=int, help="override the current week")
    ap.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = ap.parse_args()
    if args.init:
        return init_credentials(args.config)
    if args.install_service:
        return install_service()
    if args.loop:
        return run_loop(args)
    return run_once(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ESPNError as exc:
        print(f"espn: {exc}", file=sys.stderr)
        sys.exit(2)
