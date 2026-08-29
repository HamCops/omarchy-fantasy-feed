# Fantasy Feed

Fantasy Feed is a small Omarchy bar plugin for following NFL plays through a
fantasy-football lens. The bar keeps the newest meaningful play compact; the
panel expands it into the raw play, stat deltas, and side-by-side full-PPR and
standard scores for every affected player.

It uses the active Omarchy theme and deliberately avoids sportsbook branding,
accounts, contests, and roster management.

## What it looks like

The horizontal bar presents one line such as:

```text
CUEVAS · +2.8 PPR / +1.8 STD
```

Opening the panel shows the game clock and matchup, ESPN's play text, the
current/corrected/voided lifecycle, and one scoring row per player. A bundled
demo covers a reception, negative rush, interception, catch-and-fumble, passing
two-point conversion, and a reviewed touchdown that becomes voided.

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
- Middle-click the bar item to refresh.
- Use **Refresh** in the panel, or **Demo/Live** to switch data modes.
- Use the arrow keys or `j`/`k` to move through plays, `r` to refresh, `d` to
  switch demo/live, `Tab` to switch panels, and `Esc` to close.

The same service controls are available through Omarchy shell IPC:

```sh
omarchy-shell tdh.fantasy-feed status
omarchy-shell tdh.fantasy-feed refresh
omarchy-shell tdh.fantasy-feed demo
omarchy-shell tdh.fantasy-feed live
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

Negative yardage produces negative points. Version 1 intentionally excludes
kickers, team defense, points-allowed bands, half PPR, custom scoring, rosters,
projections, alerts, leaderboards, contests, betting data, and other sports.

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

The singleton service permits only one helper process for every monitor. It
polls every 30 seconds during live games, 60 seconds for scheduled or failed
refreshes, and 300 seconds for idle/final states, with an 18-second watchdog.

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
network. The suite covers scoring, identity, fail-closed parsing, revision
replacement, atomic cache recovery, provider boundaries, process ownership,
and the bar/panel contract. Architecture details live in
[docs/architecture.md](docs/architecture.md).

## License

[MIT](LICENSE) © 2026 Tom Hammond.
