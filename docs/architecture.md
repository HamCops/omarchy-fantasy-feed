# Fantasy Feed architecture

## Deployed shape

```text
ESPN scoreboard, summaries, per-play statistics, and rosters
                         |
                         v
                 scripts/espn.py
             provider validation/extraction
                         |
                         v
                 scripts/feed.py
       attribution, scoring, revisions, and cache
                         |
                         v
      FeedSnapshot schema v1 JSON (plays + weekly totals)
                         |
                         v
                  Service.qml
          singleton polling and last-good state
              |              |                 |
              v              v                 v
       BarWidget.qml    FeedPanel.qml     Standalone.qml
        per monitor      per monitor       one normal window
```

The Python helper owns data correctness; QML owns presentation. `Service.qml`
is loaded once for the plugin and is the only owner of the data process and
polling timers.
Widgets on multiple monitors read that shared service, so they cannot multiply
provider requests. Each panel instance keeps its own selection and scroll.

Runtime code uses only the Python standard library and Omarchy's existing QML
components.

## Run the data boundary

Fetch and normalize one live observation:

```sh
python3 scripts/feed.py --once
```

Replay the checked-in demo without network access, optionally stopping after a
zero-based frame:

```sh
python3 scripts/feed.py --fixture fixtures/replays/demo.json
python3 scripts/feed.py --fixture fixtures/replays/demo.json --at 2
```

The pure boundary remains available to tests and tooling:

```python
from feed import build_athlete_index, parse_play, reduce_frames

athlete_index = build_athlete_index(fixture["athletes"])
result = parse_play(raw_play, athlete_index)
snapshot = reduce_frames(fixture)
```

Callers importing `feed` directly add `scripts` to their Python path. All CLI
modes emit one normalized JSON document on stdout and diagnostics on stderr.

## Provider adapter

`scripts/espn.py` is the only module that understands ESPN wire data. One live
collection does the following:

1. Fetches the NFL scoreboard and normalizes game/status metadata.
2. Fetches eligible game summaries concurrently with at most eight workers.
3. Extracts stable athlete IDs from boxscore statistics, complete supported
   weekly player totals, and plays from completed plus current drive summaries.
4. Resolves QB/RB/WR/TE positions from free summary hints, the last-good
   leaderboard, then only the still-needed team roster endpoints.
5. Selects only known fantasy candidate types plus a bounded diagnostic sample.
6. Converts exact private per-play team-stat references to their approved
   public HTTPS host and fetches those structured deltas.
7. Produces the same fixture frame shape consumed by deterministic replay.

Network requests have a five-second per-request timeout and strict URL,
protocol, host, path, response-type, and response-size validation. Scoreboard,
summary, roster, and play-stat responses have separate caps. A cold observation follows
at most 40 supported candidates and retains at most 40 unsupported diagnostics;
unchanged provider revisions reuse the existing normalized record without
another play-stat request.

Any response needed for a trustworthy observation failing validation fails the
refresh. Partial provider data never becomes a fresh snapshot.

## Normalized boundary and attribution

Provider input ends at `parse_play`. UI input begins at the versioned
`FeedSnapshot`, whose top-level fields are `schemaVersion`, `observedAt`,
`sourceState`, `stale`, `week`, `games`, `leaderboard`, `events`, `skipped`,
and `errors`. QML does not
inspect boxscores, drive objects, regular expressions, or scoring rules.

The public Python model uses frozen slotted dataclasses:

- `PlayKey` identifies a provider play by provider, game ID, and play ID.
- `StatDelta` carries one supported stat and display label.
- `PlayerDelta` carries a proven athlete identity, role, stats, and exact
  internal points.
- `AttributedPlay` is the only result allowed to carry participants and points.
- `RejectedPlay` carries diagnostics and cannot carry fantasy points.
- `PlayResult` is the tagged union of attributed and rejected results.

Narrative patterns assign roles and proposed stat ownership; they do not prove
identity. Each narrative alias must resolve to exactly one structured boxscore
athlete on the offensive team. Repeated copies of the same stable athlete ID
are deduplicated, while two distinct IDs with the same alias remain ambiguous
and reject the entire play.

Every narrative family uses a full match and an exact ESPN type registry. The
current families are pass receptions (including no gain), passing touchdowns,
designed rushes, quarterback scrambles, rushing touchdowns, thrown
interceptions, receiving/rushing fumbles lost, and successful offensive
passing/rushing two-point conversions. Passing-touchdown patterns may consume a
recorded extra-point suffix but never award kicker points.

Laterals, no-play penalties, unknown types or narratives, unresolved athletes,
duplicate aliases, missing official stats, and contradictory data reject before
scoring. Review text is considered only when it contains a completed reversal
and then a complete supported result narrative.

## Independent cross-checks

The parser proves candidate participants and deltas against structured provider
fields:

- `scoringPlay` and `isTurnover` must match the play family.
- `statYardage` must match ordinary pass/rush narrative yardage. It is not used
  as offensive yardage for interception returns or lost-fumble records.
- Nonzero supported per-play `officialStats` must exactly equal the aggregated
  candidate deltas.

Unsupported provider categories are ignored, but a provider adapter may not
bypass these equality checks.

## Scoring and revision reducer

`SCORING_TABLE` in `scripts/feed.py` is the only scoring source. Rates and
totals use integer hundredths internally, and only the JSON boundary converts
them to numeric points. PPR and standard differ solely on the reception bonus;
negative yardage naturally produces negative points. Kicker and team-defense
rules are outside schema version 1.

Event identity is `(provider, gameId, playId)`. A revision combines the provider
modification value with a semantic-content hash.

- An unseen attributed revision inserts a current event.
- The same revision is an idempotent no-op.
- A changed supported revision replaces the event and marks it corrected.
- A changed rejected or no-play revision retracts the prior score as a voided
  event with no participants.
- A later supported revision can replace a rejected revision and is corrected.
- Absence from a later observation does not delete an existing event.

Events sort deterministically across games. Events and skipped diagnostics are
independently capped at 200.

## Cache and CLI status

Live success validates the complete snapshot and atomically replaces the cache
through a same-directory temporary file, `fsync`, and mode `0600`. The default
path is `$XDG_CACHE_HOME/fantasy-feed/snapshot.json` when `XDG_CACHE_HOME` is
absolute, otherwise `~/.cache/fantasy-feed/snapshot.json`. `--cache PATH`
provides an explicit live-only override.

The process statuses are part of the service boundary:

| Status | Meaning | Stdout |
| ---: | --- | --- |
| 0 | Fresh live snapshot or valid fixture replay | Snapshot JSON |
| 10 | Live refresh failed and a valid cache was recovered | Stale/offline snapshot JSON |
| 20 | Live refresh failed without a valid cache | Empty |
| 64 | Invalid command arguments | Empty |
| 65 | Invalid fixture | Empty |

A failed refresh never overwrites a last-good cache. Error messages are
normalized and capped before entering stale snapshots or stderr.

## Singleton service lifecycle

Omarchy injects `manifest.__sourceDir`; the service waits for that value before
starting. It executes Python with an argument array, never interpolated shell
text, and permits one child process at a time. Repeated manual refresh requests
while a live refresh is running return `already refreshing`; a demo/live mode
switch is queued and starts after the current helper exits.

The service validates schema version and collection shapes before accepting
stdout. Exit status `0` accepts a fresh snapshot, while `10` accepts the stale
cache snapshot and exposes its error. Any other status, invalid JSON, invalid
schema, or the 18-second watchdog keeps the last in-memory snapshot visible and
marks it stale.

Polling is a one-shot decision based on individual normalized games:

| Slate condition | Next refresh |
| --- | ---: |
| Any game live | 15 seconds |
| Scheduled kickoff within 10 minutes | 30 seconds |
| Scheduled kickoff within 1 hour | 2 minutes |
| Scheduled kickoff more than 1 hour away | 15 minutes |
| Scheduled game with no usable start time | 60 seconds |
| All games final or no games | Next 6:00 AM local check |
| Consecutive refresh failures | 1, 2, 5, then 15 minutes |

Looking at each game avoids the aggregate-state edge case where an already
final game and a future scheduled game share one slate. A successful refresh
resets failure backoff; manual refresh remains available during every wait.

Component destruction stops timers, the watchdog, and any active helper. The
IPC target `tdh.fantasy-feed` exposes `status`, `refresh`, `demo`, and `live`;
status includes mode, loading/stale state, source state, event count, last
update/error, countdown and reason for the next poll, and consecutive failure
count.

## UI contract

`BarWidget.qml` renders a stable source-state/play-count/favorite-count capsule;
the newest raw play remains in its tooltip. Vertical bars show the glyph only.
Stale state is explicit. Left click toggles `FeedPanel.qml`, and middle click
requests an optional immediate shared refresh.

The panel is presentation-only: it contains no process, timer, provider, cache,
or parser logic. It uses `KeyboardPanel`, `PanelKeyCatcher`, and a virtualized
`ListView`; renders newest events first; and marks corrected and voided
lifecycle states. Event cards use compact outer padding. A themed PPR/STD
dropdown selects the score inserted in parentheses directly after each
affected player's first name occurrence in the provider play sentence; the
standalone window applies that same local mode to its leaderboard sort. Raw play text is never line-capped, so narrower
surfaces wrap instead of dropping context. Arrow keys and `j`/`k` move the
monitor-local selection, `r` refreshes, `d` switches demo/live, `o` opens the
standalone window, and `Esc` closes. The standalone leaderboard also filters
by player name, team, or position, with `/` focusing its search field.

`GameSelector.qml` is a shared presentation component for the compact and
standalone surfaces. The singleton service owns a set of hidden game IDs and
derives selected event and favorite-event views, so toggling any combination of
matchups immediately stays in sync across windows and the bar. Weekly player
rows retain their game IDs so the same selection also filters the leaderboard.

`Standalone.qml` owns an ordinary `FloatingWindow`, so Hyprland can move, tile,
or place it like another app instead of covering the current workspace as a
transient bar popup. It presents feed, leaderboard, and favorite-feed tabs.
Leaderboard sorting/filtering and view selection are presentation state. The
service persists favorite player identities atomically under Omarchy config and
derives the favorites-only feed from normalized participant IDs. Favorite
controls and structured weekly stat deltas live on leaderboard rows, keeping
the play feed to one scored sentence per event.

## Verification

All automated checks are offline and use the standard library:

```sh
python3 -m compileall -q scripts tests
python3 -m unittest discover -s tests -v
python3 scripts/feed.py --fixture fixtures/replays/demo.json
omarchy plugin validate "$PWD"
git diff --check
```

On 2026-08-29 this checkout passed all 77 tests and
`omarchy plugin validate "$PWD"`.

The current suite covers every scoring row, stable identity resolution,
fail-closed parsing, semantic revisions, replacement and void behavior,
deterministic replay, malformed inputs, atomic cache fallback, mocked provider
timeouts and response boundaries, unchanged-revision reuse, singleton process
ownership, adaptive polling, and the bar/panel presentation contract. Runtime
screenshots and multi-monitor/compositor checks remain explicit release gates in
[release-checklist.md](release-checklist.md).
