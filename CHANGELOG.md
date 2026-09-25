# Changelog

All notable changes to Fantasy Feed are documented here.

## [Unreleased]

- Highlight clips keep arriving after a game is final: the r/nfl feed is
  read every 10 minutes for up to 36 hours while any play still lacks a
  clip, instead of stopping 25 minutes after the last play, and posts are
  cached for three days instead of eight hours. A game missed live picks up
  its clips at the next refresh.

- The play parser accepts ESPN's two-letter initials (`Bi.Robinson` and
  `Br.Robinson` on one roster), resolves players whose roster name carries a
  suffix (`M.Penix` for Michael Penix Jr.), and reads an interception return
  that is not pushed out of bounds. Every Falcons play in GB-ATL week 3 was
  rejected before this; the parser version is bumped so cached rejections are
  re-read.

- The standalone window no longer appears on its own when the shell starts.
  The plugin is `keepLoaded`, so its `FloatingWindow` was created at shell
  start with Quickshell's default `visible: true`; it now starts hidden and
  only `open()` shows it.

- Feed rows pick up a clip that lands after the play. A highlight attaches
  without a new play revision, so the presentation queue treated the play
  as already shown and only the notification carried the clip; presented
  and queued rows now take the clip in place.
- The league sync is part of the plugin: `scripts/league_sync.py` replaces
  espn-mcp's `feed_sync.py`, standard library only, with its own credentials
  file at `~/.config/fantasy-feed/espn.json` (`--init` writes the template,
  `--install-service` the systemd unit). Same two output files, same shape.
- No hover tooltips anywhere: bar capsule, game chips, rail chips, feed rows,
  buttons and the points filter.
- Bar matchup line is just the two scores, yours first: `41.2 – 37.9`.
  Team names stay in the tooltip.
- Matchup rows show ESPN's weekly projection under each starter's points;
  rail chips show it as `P x.x` on the card. Needs a sync that writes
  `league.json` `players`.
- Bar capsule shows text only: no football emoji. A vertical bar shows `FF`.
- One scoring, no menu. Every surface shows the synced league's points
  (standard when nothing is synced). The PPR/STD/LEAGUE dropdown, the `p`
  key and the persisted `scoringMode` setting are gone.
- Alerts always on, my side only. Every new play by one of your starters or
  hand-starred favorites notifies; the opponent's lineup never does. The
  alert preset menu, `⚔ OPP` alerts and the persisted `alertPreset` setting
  are gone.
- Remove Demo mode. The DEMO/LIVE buttons, `d` key, `demo`/`live` IPC calls,
  and the fixture's `demo` profile block are gone; the plugin always runs
  live. `scripts/feed.py --fixture` still replays the checked-in fixture for
  development and CI.
- Quieter play rows on both surfaces: hairline separators instead of boxed
  cards, and no per-row `CURRENT` tag. A row is tagged only for a clip, a
  favorite spotlight, or a corrected/voided lifecycle.
- Standalone window: three tabs, `1` feed, `2` matchup, `3` leaders. The
  favorites-only feed is now a `★ MINE` toggle (`m`) inside the feed tab;
  alert clicks and rail clicks land there.
- Roll the feed to the next NFL week on Tuesday. ESPN's default scoreboard
  keeps a finished week until Wednesday; once every game is final and the
  last kickoff is six hours old, the provider fetches the following calendar
  week's scoreboard instead. The explicit-week scoreboard URL is the only new
  request shape the adapter accepts.
- List kickers and defenses in the synced matchup. Plays cannot score them,
  so those rows show ESPN's own weekly points from the league sync
  (`league.json` now carries a per-starter `players` map), marked `ESPN`.
  Requires the matching league sync.

## [1.1.0] - 2026-09-08 (HamCops fork)

- Parse plays ESPN wraps in extra text: a "reported in as eligible" preamble
  (which hid a passing touchdown), formation notes such as `(No Huddle,
  Shotgun)` on runs, runs and catches ending `ran ob at`, and stray
  whitespace. Parser version is now `espn-narrative-v2`, and a play rejected
  by an older parser is fetched and parsed again on the next refresh instead
  of staying hidden. A play first seen after such a retry arrives as
  `current`, not `corrected`.
- Add a points filter to the feed lists (`ALL` / `3+` / `6+` / `TD`, key `f`),
  beside the scoring menu in both the panel and the standalone window. Every
  carry and catch scores something, so the full feed is busy; the filter
  keeps plays worth at least that much to someone in the selected scoring, or
  touchdowns. Bar, rail, leaderboard, matchup totals and alerts still count
  every play. Persisted with the other settings.
- Acknowledge a clip click at once: the play flashes in the accent colour,
  pulses and reads `▶ OPENING…` for three seconds while mpv starts.
- Open Reddit-hosted clips through their DASH manifest instead of the HLS
  playlist: ffmpeg's HLS demuxer stops a few seconds into Reddit's byte-range
  CMAF segments, so clips ended early. Cached posts are rewritten on load.
- Only open highlight clips hosted on v.redd.it, streamable, x.com/twitter or
  YouTube over https. Any r/nfl poster could otherwise hand an arbitrary URL to
  mpv and yt-dlp; such posts are now dropped instead of matched.
- Watch the favorites file so an external league sync applies live, and keep
  the `side`, `slot` and `league` fields it writes.
- Add league scoring: `points.league` on every play and weekly total, from the
  synced rules, with ESPN's floor-bucket yardage honoured in weekly totals.
- Add a `LEAGUE` scoring mode to both scoring menus and the `p` cycle.
- Show the head-to-head in the bar (`ME 41.2 – 37.9 TM2`), preferring ESPN's
  live totals from `~/.cache/fantasy-feed/league.json` when fresh.
- Split the My Players rail into my starters and the opponent's; opponent
  gains pulse red; chips show lineup slots.
- Add a `⚔ MATCHUP` tab (key `4`) to the standalone window with both lineups.
- Headline opponent-player alerts with `⚔ OPP`.
- Match plays to r/nfl `[Highlight]` posts (Atom feed, throttled, cached);
  badge them `▶ CLIP`, open in mpv on click or `Enter`/`v`, and send one
  follow-up alert per clip for plays the alert policy covers.

## [1.0.1] - 2026-08-30

- Keep the submitted plugin tree production-only while retaining the small
  deterministic fixture required by the user-facing offline Demo mode.
- Preserve development and load-testing assets on the separate development
  branch.

## [1.0.0] - 2026-08-30

- Follow fantasy-relevant NFL plays across an arbitrary game selection.
- Insert the selected PPR or standard score beside each affected player in the
  original play sentence.
- Add a sortable weekly QB/RB/WR/TE leaderboard with player and team search.
- Add persistent favorites, a My Players pulse rail, and a favorites-only feed.
- Add favorite-player desktop alerts with all-play, touchdown, three-point, and
  six-point policies.
- Highlight favorite-team red-zone possessions and expose down-and-distance.
- Stage multi-game arrivals into a readable live tape with independent scroll
  position on every surface.
- Add a normal tileable standalone window, adaptive polling, last-good caching,
  correction/void handling, and system-local kickoff times.

[1.0.1]: https://github.com/studioxvii/omarchy-fantasy-feed/releases/tag/v1.0.1
[1.0.0]: https://github.com/studioxvii/omarchy-fantasy-feed/releases/tag/v1.0.0
