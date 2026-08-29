# Fantasy Feed architecture

## Deployed shape

```text
ESPN scoreboard, summaries, and per-play statistics
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
              FeedSnapshot schema v1 JSON
                         |
                         v
                  Service.qml
          singleton polling and last-good state
                   |              |
                   v              v
            BarWidget.qml    FeedPanel.qml
             per monitor      per monitor
```

The Python helper owns data correctness; QML owns presentation. `Service.qml`
is loaded once for the plugin and is the only owner of a process or timer.
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
3. Extracts stable athlete IDs from boxscore statistics and plays from drive
   summaries.
4. Selects only known fantasy candidate types plus a bounded diagnostic sample.
5. Converts exact private per-play team-stat references to their approved
   public HTTPS host and fetches those structured deltas.
6. Produces the same fixture frame shape consumed by deterministic replay.

Network requests have a five-second per-request timeout and strict URL,
protocol, host, path, response-type, and response-size validation. Scoreboard,
summary, and play-stat responses have separate caps. A cold observation follows
at most 40 supported candidates and retains at most 40 unsupported diagnostics;
unchanged provider revisions reuse the existing normalized record without
another play-stat request.

Any response needed for a trustworthy observation failing validation fails the
refresh. Partial provider data never becomes a fresh snapshot.

## Normalized boundary and attribution

Provider input ends at `parse_play`. UI input begins at the versioned
`FeedSnapshot`, whose top-level fields are `schemaVersion`, `observedAt`,
`sourceState`, `stale`, `games`, `events`, `skipped`, and `errors`. QML does not
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

Polling adapts to source state:

| State | Next refresh |
| --- | ---: |
| Live | 30 seconds |
| Scheduled | 60 seconds |
| Refresh failure/offline/malformed | 60 seconds |
| Idle/final | 300 seconds |

Component destruction stops timers, the watchdog, and any active helper. The
IPC target `tdh.fantasy-feed` exposes `status`, `refresh`, `demo`, and `live`;
status includes mode, loading/stale state, source state, event count, last
update/error, and the countdown to the next poll.

## UI contract

`BarWidget.qml` renders only the latest normalized event. Horizontal bars show
a football glyph, player, and PPR/standard point pair; vertical bars show the
glyph only. Stale state is explicit. Left click toggles `FeedPanel.qml`, and
middle click requests one shared refresh. The widget forwards Omarchy's full
open, close, toggle, and popout-switch contract.

The panel is presentation-only: it contains no process, timer, provider, cache,
or parser logic. It uses `KeyboardPanel`, `PanelKeyCatcher`, and a virtualized
`ListView`; renders newest events first; presents one row per participant; and
marks corrected and voided lifecycle states. Arrow keys and `j`/`k` move the
monitor-local selection, `r` refreshes, `d` switches demo/live, `Tab` switches
panels, and `Esc` closes. Colors, fonts, spacing, and bar sizing come from
Omarchy theme tokens.

## Verification

All automated checks are offline and use the standard library:

```sh
python3 -m compileall -q scripts tests
python3 -m unittest discover -s tests -v
python3 scripts/feed.py --fixture fixtures/replays/demo.json
omarchy plugin validate "$PWD"
git diff --check
```

On 2026-08-29 this checkout passed all 60 tests and
`omarchy plugin validate "$PWD"`.

The current suite covers every scoring row, stable identity resolution,
fail-closed parsing, semantic revisions, replacement and void behavior,
deterministic replay, malformed inputs, atomic cache fallback, mocked provider
timeouts and response boundaries, unchanged-revision reuse, singleton process
ownership, adaptive polling, and the bar/panel presentation contract. Runtime
screenshots and multi-monitor/compositor checks remain explicit release gates in
[release-checklist.md](release-checklist.md).
