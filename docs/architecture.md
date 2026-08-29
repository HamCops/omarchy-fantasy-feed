# Data boundary architecture

## Run the current slice

Replay the checked-in game without network access.

```sh
python3 scripts/feed.py --fixture fixtures/replays/demo.json
```

Stop after a specific zero-based frame.

```sh
python3 scripts/feed.py --fixture fixtures/replays/demo.json --at 2
```

Call the pure boundary from Python.

```python
from feed import build_athlete_index, parse_play, reduce_frames

athlete_index = build_athlete_index(fixture["athletes"])
result = parse_play(raw_play, athlete_index)
snapshot = reduce_frames(fixture)
```

The caller must add `scripts` to its import path. The future Omarchy service will invoke the command and consume only the snapshot on stdout. Diagnostics use stderr. Fixture mode returns status 0 on success, 64 for invalid arguments, and 65 for invalid fixture data. Live `--once` deliberately returns 69 until the provider adapter exists.

## Boundary

Version 1 keeps the data path in one standard-library module.

```text
recorded provider play and boxscore athletes
                    |
                    v
exact type registry and full-match narrative parser
                    |
                    v
unique structured athlete identity resolution
                    |
                    v
official stat and play-flag cross-check
                    |
                    v
integer-hundredths scoring
                    |
                    v
revision reducer and bounded FeedSnapshot JSON
```

Provider input ends at `parse_play`. UI input begins at `reduce_frames`. QML never needs ESPN fields, regular expressions, or scoring rules.

The first implementation synthesis favored one deep `scripts/feed.py` module over a package of shallow files. A single deployed helper reduces import and plugin-path failures before the Omarchy lifecycle is proven. The module still has explicit internal seams for models, identity, parsing, scoring, reduction, and CLI behavior. Split those seams only when the live adapter or a second provider creates an independent reason to change.

## Domain model

The public model uses frozen slotted dataclasses.

- `PlayKey` identifies one provider play by provider, game ID, and play ID.
- `StatDelta` carries one supported stat and label.
- `PlayerDelta` carries a proven athlete identity, role, stats, and exact internal points.
- `AttributedPlay` is the only result that can carry participants and points.
- `RejectedPlay` carries parser diagnostics and has no participant or point field.
- `PlayResult` is the tagged union of attributed and rejected results.

This shape makes a rejected play impossible to score by construction.

## Attribution

Narrative patterns assign roles and stat ownership. They do not establish identity. Each parsed narrative alias must resolve to exactly one entry in the structured boxscore athlete directory for the offensive team.

An athlete entry contains `id`, `firstName`, `lastName`, `displayName`, and `team`. The identity resolver derives ESPN's compact alias from the first initial and last name. For example, `Tyler Huntley` becomes `T.Huntley`. A successful lookup supplies the stable athlete ID and structured display name. Missing and duplicate aliases reject the whole play.

The boxscore may repeat one athlete in multiple stat groups. Identical entries with the same stable ID are deduplicated before alias uniqueness is checked. Two distinct athlete IDs with the same team and narrative alias remain ambiguous and reject.

The parser registry uses exact ESPN type names. Each registry entry contains an ordered set of supported narrative families. Every family uses `fullmatch`. There is no generic fallback. Review text is parsed only when it contains a challenge result followed by `REVERSED.` and a complete supported result narrative.

Current supported families are pass receptions including no gain, passing touchdowns, designed rushes, quarterback scrambles, rushing touchdowns, thrown interceptions, receiving or rushing fumbles lost, and successful offensive passing or rushing two-point conversions. Passing touchdown patterns accept the recorded extra-point suffix but never score it.

Laterals, no-play penalties, unknown types, unknown narratives, unresolved athletes, duplicate aliases, missing official stats, and contradictory data reject before scoring.

## Cross-checks

The parser produces candidate participants and stat deltas. It then proves the candidate against independent structured fields.

- `scoringPlay` must match the supported play family.
- `isTurnover` must match the supported play family.
- `statYardage` must match parsed yardage for ordinary passes and rushes. It is not an offensive-yardage check for interception returns or lost-fumble records because ESPN uses return or net values there.
- Nonzero supported `officialStats` must exactly match the aggregated candidate stats.

The recorded `officialStats` object is the adapter seam for ESPN's team-level per-play statistics. Unsupported categories such as extra points are ignored. A future provider adapter may translate provider stat names into these keys, but it may not bypass the equality check.

## Scoring

`SCORING_TABLE` is the only scoring source. Every rate is stored as integer hundredths per stat unit. PPR and standard differ only on receptions. JSON conversion to numeric points happens after all arithmetic is complete.

Supported keys are passing yards and touchdowns, interceptions thrown, rushing yards and touchdowns, receptions, receiving yards and touchdowns, passing, rushing, and receiving two-point conversions, and fumbles lost.

Negative yardage uses the same positive per-yard rate and therefore produces negative points. Kicker and team defense rules remain outside this contract.

## Revision reducer

The reducer processes fixture frames in observation order. Event identity is provider, game ID, and play ID. Revision combines the provider `modified` value with a hash of semantic play content.

- An unseen attributed revision inserts a current event.
- The same revision is a no-op.
- A changed attributed revision replaces the event and marks it corrected.
- A changed rejected or no-play revision retracts a scored event as a voided event with no participants.
- A later supported revision may replace a rejected revision and is marked corrected.
- A play missing from a later frame remains present.

The final snapshot sorts events deterministically and caps both events and skipped diagnostics. The default cap is 200. Games are upserted by ID. The final frame controls `observedAt`, `sourceState`, and `stale`.

## Fixture contract

A replay fixture contains `fixtureVersion`, `athletes`, and one or more `frames`. Each frame contains `observedAt`, `sourceState`, `stale`, `games`, and `plays`.

The fixtures are recorded-style boundary samples, not claims that raw ESPN responses already use this exact shape. The future adapter owns extraction from scoreboard, summary, boxscore, and per-play team-stat responses. Fixture values retain the relevant ESPN narrative, type, flags, modification time, athlete identity fields, and team stat deltas.

`fixtures/raw/scoring_plays.json` covers every scoring row. `fixtures/raw/rejections.json` covers fail-closed cases. `fixtures/raw/revisions.json` covers a same-ID review reversal. `fixtures/replays/demo.json` covers insert, duplicate, supported correction, void, unknown input, and absence in a later frame.

## Verification

Run all checks without network access.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/feed.py --fixture fixtures/replays/demo.json
```

The suite asserts the scoring examples, stable identity resolution, full rejection boundary, replay idempotence, replacement and void behavior, deterministic CLI output, malformed input status, and the 10,000-play performance gate.
