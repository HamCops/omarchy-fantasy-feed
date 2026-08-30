# Fantasy Feed

Fantasy Feed is an Omarchy plugin for following NFL plays through a
fantasy-football lens. A stable bar capsule shows feed health without resizing
on every snap. The compact panel expands each play into raw text, stat deltas,
and the points from a selectable PPR or standard profile; a standalone window
adds weekly leaderboards and a favorites-only feed.

It uses the active Omarchy theme and deliberately avoids sportsbook branding,
accounts, contests, and roster management.

## What it looks like

The horizontal bar presents a stable status such as:

```text
LIVE · 24 PLAYS · ★3
```

Opening the compact panel shows the game clock and matchup, ESPN's play text, the
current/corrected/voided lifecycle, with each affected player's selected points
inserted directly after their name in the play sentence. A PPR/STD menu in the
header changes every inline score and the weekly leaderboard sort together.
Play text wraps in full instead of being truncated; unusually long plays grow
only as much as needed. A bundled demo covers a reception, negative rush, interception,
catch-and-fumble, passing two-point conversion, and a reviewed touchdown that
becomes voided. Positive points are green, negative points are red, and zero is
neutral.

Pop the panel into a normal movable/tileable window for three views: the full
feed, a weekly QB/RB/WR/TE leaderboard sortable by PPR or standard points, and
a custom feed containing only plays by locally favorited players.

A horizontally scrollable game strip appears across both feed surfaces. Click
any matchup to toggle it independently; click **ALL** to hide or restore the
entire slate. Compact two-line chips show `ARI 21–18 ATL` above the live quarter
and remaining clock (or the scheduled/final provider detail). The same selection filters the compact feed, bar count,
standalone feed, favorites feed, and weekly leaderboard.

Newly discovered plays enter a shared live tape one at a time instead of
appearing as an unreadable poll-sized batch. Normal arrivals land every 600 ms;
the tape accelerates only when it is falling behind. A play involving a
favorited player receives a green `★` spotlight and remains at the live edge for
2.6 seconds. Scrolling away pauses auto-follow and exposes a `NEW ↑` control,
so incoming plays cannot pull the reader away from the play they are reading.

## Requirements

- Omarchy with the current shell plugin commands.
- Python 3. The runtime uses only the Python standard library.
- Network access for live data. Demo mode is deterministic and offline.

## Install

From a local clone, commit the files you want Omarchy to clone, then run this
from the repository root:

```sh
omarchy plugin add "file://$PWD" --enable --yes
```

Once a public repository exists, the equivalent published form is:

```sh
omarchy plugin add "https://github.com/<owner>/<repository>.git" --enable --yes
```

No public repository URL is claimed by this project yet. The manifest installs
one non-duplicated widget in the center section by default.

To disable or remove an installed copy:

```sh
omarchy plugin disable tdh.fantasy-feed
omarchy plugin remove tdh.fantasy-feed --yes
```

## Use

- Left-click the bar item to open or close the feed.
- The feed refreshes automatically: every 15 seconds during live games, every
  30 seconds in the final 10 minutes before kickoff, every 2 minutes during the
  preceding hour, and every 15 minutes when kickoff is farther away. Once the
  slate is final it sleeps until a 6:00 AM local daily schedule check.
- Middle-click or **Refresh** requests an optional immediate refresh.
- Use **Demo/Live** to switch data modes and **↗** (or `o`) to pop out.
- Click any matchup in the game strip to add or remove that game. Any number of
  games can be selected at once; **ALL** toggles the complete slate.
- Use the arrow keys or `j`/`k` to move through plays, `r` to refresh, `d` to
  switch demo/live, `p` to toggle the selected PPR/STD profile, and `Esc` to
  close the compact panel. The header menu provides the same scoring control.
- In the standalone window, use `1`/`2`/`3` for feed/leaderboard/favorites and
  `p` to toggle PPR/standard display and sorting. Select `ALL`, `QB`, `RB`, `WR`, or `TE`,
  type in the player/team search (`/` focuses it), and use `☆`/`★` to update
  favorites from the leaderboard.

The same service controls are available through Omarchy shell IPC:

```sh
omarchy-shell tdh.fantasy-feed status
omarchy-shell tdh.fantasy-feed refresh
omarchy-shell tdh.fantasy-feed demo
omarchy-shell tdh.fantasy-feed live
omarchy-shell tdh.fantasy-feed simulate
omarchy-shell shell toggle tdh.fantasy-feed
```

The data helper is also useful on its own:

```sh
# One live normalized snapshot
python3 scripts/feed.py --once

# The complete offline demo, or a specific zero-based replay frame
python3 scripts/feed.py --fixture fixtures/replays/demo.json
python3 scripts/feed.py --fixture fixtures/replays/demo.json --at 2
```

Normal JSON goes to stdout and diagnostics go to stderr, so the output can be
piped safely to tools such as `jq`.

### Ten-game simulator

The development simulator exercises the real provider boundary rather than
injecting normalized plays into QML. It serves ESPN-shaped scoreboard, summary,
per-play statistics, and leaderboard data over loopback HTTP. Its deterministic
schedule advances one to three of the ten games on most ticks, with an occasional
five-game burst. The adapter
still validates canonical ESPN URLs, routes them only to the explicit loopback
origin, fetches summaries/statistics concurrently, and passes the result through
the normal attribution, reducer, cache, service, and UI path.

Start it from the repository in one terminal:

```sh
python3 scripts/espn_simulator.py
```

Then switch the installed plugin to its one-second load-test poll in another:

```sh
omarchy-shell tdh.fantasy-feed simulate
omarchy-shell shell toggle tdh.fantasy-feed
```

The bar and headers show `SIM` while this mode is active. Calling `simulate`
starts a fresh simulator-only cache; it never touches the real ESPN cache. View
request count and measured peak concurrency with:

```sh
curl -s http://127.0.0.1:8765/__simulator__/status | jq
```

Use `Ctrl+C` in the server terminal and return the plugin to real data with
`omarchy-shell tdh.fantasy-feed live`. The simulator accepts `--games`,
`--max-plays`, `--latency-ms`, and `--all-games-per-tick` for alternate load
profiles. The helper's
`--provider-base-url` option rejects anything other than an HTTP loopback origin
with an explicit port.

## Scoring

The plugin ships two fixed scoring profiles. PPR differs from standard only by
the reception bonus.

| Stat | PPR | Standard |
| --- | ---: | ---: |
| Passing yard | 0.04 | 0.04 |
| Passing touchdown | 4 | 4 |
| Interception thrown | -2 | -2 |
| Rushing yard | 0.1 | 0.1 |
| Rushing touchdown | 6 | 6 |
| Reception | 1 | 0 |
| Receiving yard | 0.1 | 0.1 |
| Receiving touchdown | 6 | 6 |
| Passing two-point conversion | 2 | 2 |
| Rushing two-point conversion | 2 | 2 |
| Receiving two-point conversion | 2 | 2 |
| Fumble lost | -2 | -2 |

Negative yardage produces negative points. Version 0.3 intentionally excludes
kickers, team defense, points-allowed bands, half PPR, custom scoring, fantasy
league roster sync, projections, alerts, contests, betting data, and other
sports.

Weekly leaderboard totals come from complete structured game box scores rather
than the bounded play feed. ESPN roster metadata is used only to assign the
QB/RB/WR/TE grouping. Favorites are stored locally in
`$XDG_CONFIG_HOME/omarchy/fantasy-feed.json` (normally
`~/.config/omarchy/fantasy-feed.json`); no fantasy account is required.

## Reliability and corrections

Fantasy Feed does not award plausible-looking points when attribution is
uncertain. A supported play must match a constrained narrative family, resolve
every player uniquely against structured boxscore athlete IDs, and agree with
the provider's flags, yardage, and per-play official statistics. Unsupported or
contradictory plays stay in bounded diagnostics rather than the scored feed.

Events are keyed by provider, game ID, and play ID. A changed provider revision
replaces that event and marks it corrected. If a revision becomes a no-play or
unsupported result, the former score becomes a voided event instead of leaving
duplicate points behind. The visible event and diagnostic lists are each capped
at 200 records.

The provider adapter merges both completed drives and the drive currently in
progress. ESPN can briefly expose the same play in both locations while moving
a finished possession, so play IDs are deduplicated with the current revision
winning. This prevents live fantasy plays from arriving in a batch only after
the drive ends.

The singleton service permits only one helper process for every monitor and
for the standalone window. Its one-shot scheduler inspects every game rather
than trusting only the aggregate slate state, so a final Thursday game cannot
hide scheduled Sunday games. Live polling runs every 15 seconds; scheduled
polling tightens from 15 minutes to 2 minutes to 30 seconds as kickoff nears.
An entirely final/idle slate sleeps until the next 6:00 AM local check. Failed
refreshes back off through 1, 2, 5, and 15 minutes. The helper retains its
18-second watchdog and never overlaps another refresh.

Provider ingestion and feed presentation are deliberately separate. Scoreboard,
leaderboard, and cache state apply immediately, while new event revisions enter
one shared arrival queue used by every monitor and the standalone window. The
queue uses 600/300/160 ms normal, catch-up, and urgent pacing; a favorite arrival
holds for 2.6 seconds. Initial loads and data-mode/week changes hydrate at once
instead of replaying an old cache card by card.

Fresh live data is written atomically to a mode-`0600` last-good cache at:

```text
$XDG_CACHE_HOME/fantasy-feed/snapshot.json
```

`XDG_CACHE_HOME` must be absolute; otherwise the path is
`~/.cache/fantasy-feed/snapshot.json`. A failed refresh never overwrites that
cache. With a valid cache, the helper emits a stale/offline snapshot and exits
`10`; without one, it emits no snapshot and exits `20`. The UI retains its last
valid in-memory snapshot and marks it stale when a later helper run fails.

## Data source and design note

Live mode reads undocumented public ESPN NFL JSON endpoints. They require no
credentials, but they are unsupported and may change or disappear. Recorded
fixtures and demo mode remain useful without ESPN, and the adapter is isolated
in `scripts/espn.py` so provider changes do not leak into QML.

Matt Van Horn's [CLI Printing Press](https://github.com/mvanhorn/cli-printing-press)
and its generated [ESPN CLI](https://github.com/mvanhorn/printing-press-library/tree/main/library/media-and-entertainment/espn)
were evaluated as an operational reference, particularly for its 30-second
watch cadence and cache/retry discipline. It is not a runtime dependency:
Fantasy Feed needs ESPN's per-play participant-stat references and a revision
reducer tailored to correcting fantasy events.

Fantasy Feed is not affiliated with, endorsed by, or sponsored by ESPN or
DraftKings. ESPN and DraftKings are trademarks of their respective owners.

## Develop and verify

Run the offline suite and plugin validator from the repository root:

```sh
python3 -m compileall -q scripts tests
python3 -m unittest discover -s tests -v
python3 scripts/feed.py --fixture fixtures/replays/demo.json
omarchy plugin validate "$PWD"
git diff --check
```

Tests use injected responses and checked-in fixtures; they do not require the
network. A loopback-only integration test starts the ten-game simulator on an
ephemeral port. The suite covers scoring, weekly aggregation, position
resolution,
identity, fail-closed parsing, revision replacement, atomic cache recovery,
provider boundaries, concurrent simulated games, favorites persistence,
process ownership, and the three UI hosts. Architecture details live in
[docs/architecture.md](docs/architecture.md).

## License

[MIT](LICENSE) © 2026 Tom Hammond.
